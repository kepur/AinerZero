"""只读 HTTP/文件元数据复核；仅写本目录全新证据，不导入仓库应用或执行测试。"""
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/Users/mac/AinerWorkFlow/AinerZero/reports/character-first-landing-20261017')
OUT = BASE / 'review-evidence'
API = 'http://127.0.0.1:8790'


def read(path):
    return json.loads(Path(path).read_text())


def save(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def get(endpoint):
    with urllib.request.urlopen(API + endpoint, timeout=15) as response:
        return json.load(response)


def identity(row):
    path = Path(row['path'])
    try:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        return {'path': str(path), 'sha256': sha, 'size_bytes': len(data),
                'matches': sha == row['sha256'] and len(data) == row.get('size_bytes', len(data))}
    except OSError as exc:
        return {'path': str(path), 'matches': False, 'error': str(exc)}


payloads = read(BASE / 'workbench/payloads.json')
expected = {f"{p['project']}.{p['phase']}.{p['track']}{p['seq']}": p for p in payloads}
old_before = read(BASE / 'workbench/old-gated-fields-before.json')
tasks = {}
missing = []
queue = list(dict.fromkeys(list(expected) + list(old_before)))
while queue:
    tid = queue.pop(0)
    if tid in tasks or tid in missing:
        continue
    try:
        t = get('/api/tasks/' + tid)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            missing.append(tid)
            continue
        raise
    tasks[tid] = t
    queue.extend(d['id'] for d in t.get('deps', []) if d['id'] not in tasks)

fields = ['title', 'kind', 'tier', 'prompt', 'params', 'acceptance', 'context_files', 'file_scope',
          'depends_on', 'verifies', 'workdirs', 'needs', 'dedupe_key', 'max_attempts', 'max_stalls', 'lease_s']
payload_mismatches = []
authorized_new_scopes = {}
for tid, p in expected.items():
    t = tasks[tid]
    for field in fields:
        if p.get(field) != t.get(field):
            row = {'task': tid, 'field': field, 'expected': p.get(field), 'actual': t.get(field)}
            if field == 'file_scope' and tid in ['awz.CF.A2', 'awz.CF.A3']:
                authorized_new_scopes[tid] = row
            else:
                payload_mismatches.append(row)
    if int(p['needs_gpu']) != int(t['gpu_level']):
        payload_mismatches.append({'task': tid, 'field': 'gpu_level', 'expected': p['needs_gpu'], 'actual': t['gpu_level']})

allowed_needs = {'text', 'code', 'math', 'vision', 'godot', 'multimodal', 'longrun'}
needs_errors = []
product_errors = []
verify_errors = []
status_errors = []
design_ids = {'awz.CF.A1', 'awz.CF.A2', 'awz.CF.A3', 'awz.CF.B1', 'awz.CF.B2'}
for tid, p in expected.items():
    t = tasks[tid]
    if set(t['needs']) - allowed_needs:
        needs_errors.append(tid)
    if tid not in design_ids:
        if (t['status'] != 'blocked' or 'awz.V9.A10' not in (t['depends_on'] or [])
                or t['params'].get('run_authorized') is not False
                or t['params'].get('all_new_runtime_budgets') != 'unapproved'):
            product_errors.append(tid)
    elif tid not in ['awz.CF.A1', 'awz.CF.A2'] and t['status'] != p['status']:
        status_errors.append(tid)
    if t['kind'] == 'verify':
        for target in t['verifies']:
            if target not in [d['id'] for d in t['deps']]:
                verify_errors.append({'task': tid, 'reason': 'verified target not dependency', 'target': target})
            if t.get('assignee') and t['assignee'] == tasks[target].get('author'):
                verify_errors.append({'task': tid, 'reason': 'same author/assignee', 'target': target})
    elif tid not in ['awz.CF.A3']:
        verifier = p['params'].get('non_author_verification_task')
        if tid == 'awz.CF.A1':
            verifier = 'awz.CF.A2'
        if not verifier or tid not in tasks.get(verifier, {}).get('verifies', []):
            verify_errors.append({'task': tid, 'reason': 'no explicit nonauthor verifier', 'verifier': verifier})

graph = {tid: [d['id'] for d in t.get('deps', [])] for tid, t in tasks.items()}
cycles = []
seen = set()
stack = []


def visit(tid):
    if tid in stack:
        cycles.append(stack[stack.index(tid):] + [tid])
        return
    if tid in seen:
        return
    stack.append(tid)
    for dep in graph.get(tid, []):
        visit(dep)
    stack.pop()
    seen.add(tid)


for tid in expected:
    visit(tid)

old_changes = []
old_unexpected = []
additions = ['awz.CF.B2', 'awz.CF.C2', 'hub.CF.B2']
for tid, old in old_before.items():
    for field, value in old.items():
        actual = tasks[tid].get(field)
        if value != actual:
            row = {'task': tid, 'field': field, 'before': value, 'after': actual}
            old_changes.append(row)
            if not (tid == 'awz.P3.A3' and field == 'depends_on' and actual == value + additions):
                old_unexpected.append(row)

registry = read('/Users/mac/AinerWorkFlow/AinerRelay/modules/modules.v1.json')
reg_before = read(BASE / 'workbench/registry-before.json')
modules = {m['code']: m for m in registry['modules']}
mods_before = {m['code']: m for m in reg_before['modules']}
module_mutations = []
module_errors = []
members = {}
for code, m in modules.items():
    for tid in m.get('tasks', []):
        members.setdefault(tid, []).append(code)
    old = mods_before[code]
    changed = [k for k in set(m) | set(old) if m.get(k) != old.get(k)]
    if changed:
        module_mutations.append({'module': code, 'changed_fields': changed,
                                 'old_tasks': old.get('tasks', []), 'new_tasks': m.get('tasks', [])})
        if changed != ['tasks'] or m['tasks'][:len(old['tasks'])] != old['tasks']:
            module_errors.append({'module': code, 'reason': 'non-additive or non-task changes', 'fields': changed})
        if set(m['tasks']) - set(old['tasks']) - set(expected):
            module_errors.append({'module': code, 'reason': 'unexpected additions'})
for tid, p in expected.items():
    if members.get(tid) != [p['params']['module_hint']]:
        module_errors.append({'task': tid, 'reason': 'non-unique/wrong module', 'actual': members.get(tid)})
if set(modules) != set(mods_before):
    module_errors.append({'reason': 'module catalogue changed'})
live_modules = get('/api/modules')
live_members = {}
for m in live_modules['modules']:
    for tid in m['tasks']:
        if tid in expected:
            live_members.setdefault(tid, []).append(m['code'])
for tid in expected:
    if live_members.get(tid) != members.get(tid):
        module_errors.append({'task': tid, 'reason': 'live/registry differ'})

projects = get('/api/projects')
projects_before = read(BASE / 'workbench/projects.json')
source_before = read(BASE / 'source-before.json')
source_after = read(BASE / 'source-after.json')
file_checks = {key: [identity(r) for r in source_after[key]] for key in
               ['output_files', 'immutable_references', 'original_published_input_snapshots']}
backup_checks = []
for row in source_before['edited_existing_files']:
    b = identity({'path': row['backup_path'], 'sha256': row['sha256'], 'size_bytes': row['size_bytes']})
    backup_checks.append(b)
file_checks['backups'] = backup_checks
summary = {
    'schema': 'CF-independent-metadata-audit/v1', 'at': datetime.now(timezone.utc).isoformat(),
    'health': get('/api/health'), 'task_count': len(expected), 'fetched_dependency_nodes': len(tasks),
    'reachable_nodes': len(seen), 'missing_dependencies': missing, 'cycles': cycles,
    'payload_mismatches': payload_mismatches, 'authorized_new_scope_deltas': authorized_new_scopes,
    'needs_errors': needs_errors, 'product_blocked_A10_budget_errors': product_errors,
    'design_status_errors': status_errors, 'verify_errors': verify_errors,
    'old_captured_count': len(old_before), 'old_changes': old_changes, 'unexpected_old_changes': old_unexpected,
    'A10_status': tasks['awz.V9.A10']['status'], 'module_count': len(modules),
    'changed_modules': module_mutations, 'module_errors': module_errors,
    'live_module_errors': live_modules.get('errors'), 'live_orphans': live_modules.get('orphans'),
    'live_missing': live_modules.get('missing'), 'projects_unchanged': projects == projects_before,
    'file_checks': file_checks,
    'registry_sha256': hashlib.sha256(Path('/Users/mac/AinerWorkFlow/AinerRelay/modules/modules.v1.json').read_bytes()).hexdigest(),
    'payloads_sha256': hashlib.sha256((BASE / 'workbench/payloads.json').read_bytes()).hexdigest(),
    'limits': ['metadata-only, no product tests', 'A1/A2 lifecycle status expected to change',
               'A2/A3 scope additive authorization independently checked in report', 'GET snapshots are not atomic']}
save('independent-live-tasks.json', tasks)
save('independent-live-modules.json', live_modules)
save('independent-live-projects.json', projects)
save('independent-audit-result.json', summary)
compact = {k: v for k, v in summary.items() if k not in ['file_checks', 'changed_modules', 'authorized_new_scope_deltas']}
compact['file_counts'] = {k: {'count': len(v), 'matches': sum(x['matches'] for x in v)} for k, v in file_checks.items()}
compact['scope_deltas'] = authorized_new_scopes
print(json.dumps(compact, ensure_ascii=False, indent=2))
