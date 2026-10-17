"""只解析文档/元数据，独立比对正文任务与冻结快照；不运行产品代码。"""
import difflib
import hashlib
import json
import re
from pathlib import Path

BASE = Path('/Users/mac/AinerWorkFlow/AinerZero/reports/character-first-landing-20261017')
OUT = BASE / 'review-evidence'
AZ = Path('/Users/mac/AinerWorkFlow/AinerZero')
PLAN = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md')


def read(path):
    return json.loads(Path(path).read_text())


def save(name, value):
    with (OUT / name).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


before = read(BASE / 'source-before.json')
after = read(BASE / 'source-after.json')
payloads = read(BASE / 'workbench/payloads.json')
payload = {f"{p['project']}.{p['phase']}.{p['track']}{p['seq']}": p for p in payloads}
live = read(OUT / 'independent-live-tasks.json')
data = PLAN.read_bytes()
assert sha(data) == 'f4402743cd5c5da1e281b53557d3f78fec95dbc002ed50cb170f45bd568c0137', 'plan changed before r1 independent parse'
with (OUT / 'r1-plan-observed.md').open('xb') as f:
    f.write(data)
text = data.decode()
headers = list(re.finditer(r'^### ((?:awz|hub)\.CF\.[A-Z]\d+) (.+)$', text, re.M))
parsed = []
errors = []
for i, h in enumerate(headers):
    end = headers[i + 1].start() if i + 1 < len(headers) else text.find('### CF-X14', h.end())
    block = text[h.start():end if end >= 0 else len(text)]
    # CF-W03A reuse paragraph belongs to the separate original task, not C1's fields.
    block = block.split('\n### CF-W03A')[0]
    tid = h.group(1)
    needline = next(x for x in block.splitlines() if x.startswith('- 层级/needs/项目模块：'))
    needs = [x.strip() for x in re.search(r'`([^`]+)`', needline).group(1).split(',')]
    module = re.search(r'主模块([\d.]+)', needline).group(1).rstrip('.')
    depline = next(x for x in block.splitlines() if x.startswith('- 前置（本轮在线登记值）：'))
    deps = re.findall(r'(?:awz|hub|ainerzero|forge)\.[A-Za-z0-9]+\.[A-Za-z]\d+', depline)
    scopeline = next(x for x in block.splitlines() if x.startswith('- 文件范围'))
    root = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero' if tid.startswith('awz.') else '/Users/mac/AinerWorkFlow/AinerHub_IDEA')
    scope = [str(root / x).rstrip('/') for x in re.findall(r'`([^`]+)`', scopeline)]
    verifyline = next(x for x in block.splitlines() if x.startswith('- 验证/正反例：'))
    verifier = re.search(r'(?:awz|hub)\.CF\.[A-Z]\d+', verifyline).group(0)
    row = {'id': tid, 'line': text[:h.start()].count('\n') + 1, 'needs': needs,
           'module': module, 'depends_on': deps, 'file_scope': scope, 'verifier': verifier,
           'positive_negative_text': verifyline}
    parsed.append(row)
    p = payload[tid]
    expected = {'needs': p['needs'], 'module': p['params']['module_hint'], 'depends_on': p['depends_on'],
                'file_scope': [x.rstrip('/') for x in p['file_scope']],
                'verifier': p['params'].get('non_author_verification_task')}
    for k, v in expected.items():
        if row[k] != v:
            errors.append({'task': tid, 'field': k, 'document': row[k], 'payload': v})
    if tid not in live[verifier]['verifies']:
        errors.append({'task': tid, 'reason': 'document verifier does not verify task in live'})

baseline = read(AZ / 'docs/architecture/baseline.v1.json')
binding_rows = []
for category in ['published_documents', 'publication_entries', 'accepted_contracts_limited_scope', 'candidate_snapshots_not_adopted']:
    for entry in baseline[category]:
        snap = AZ / entry['snapshot']
        observed = snap.read_bytes()
        matches = sha(observed) == entry['sha256'] and len(observed) == entry['bytes']
        manifests = [x for x in after['original_published_input_snapshots'] if Path(x['path']) == snap]
        binding_rows.append({'category': category, 'path': str(snap), 'actual_sha256': sha(observed),
                             'matches_original_baseline': matches,
                             'after_manifest_matches_baseline': len(manifests) == 1 and manifests[0]['sha256'] == entry['sha256'],
                             'live_path_mutable_original': entry.get('live_path_mutable')})

entry_rows = []
diffs = []
added_link_errors = []
for r in before['edited_existing_files']:
    old = Path(r['backup_path']).read_text().splitlines()
    now = Path(r['path']).read_text().splitlines()
    opcodes = difflib.SequenceMatcher(a=old, b=now, autojunk=False).get_opcodes()
    additions = [line for tag, a, b, c, d in opcodes if tag == 'insert' for line in now[c:d]]
    entry_rows.append({'path': r['path'], 'before_sha_match': sha(Path(r['backup_path']).read_bytes()) == r['sha256'],
                       'only_insertions': all(x[0] in ['equal', 'insert'] for x in opcodes),
                       'inserted_line_count': len(additions), 'added_text': additions})
    diffs.extend(['\nFILE ' + r['path'], *difflib.unified_diff(old, now, n=1)])
    for label, target in re.findall(r'\[([^\]]*)\]\(([^)]+)\)', '\n'.join(additions)):
        if '://' not in target and not target.startswith('#'):
            target = target.split('#')[0]
            resolved = Path(r['path']).parent / target
            if not resolved.exists():
                added_link_errors.append({'path': r['path'], 'label': label, 'target': target})

save('r1-document-structure-result.json', {'plan_sha256': sha(data), 'parsed_task_count': len(parsed),
     'parsed_tasks': parsed, 'document_payload_errors': errors,
     'baseline_snapshot_bindings': binding_rows, 'entry_diffs': entry_rows, 'added_link_errors': added_link_errors,
     'known_reuse_paragraph_findings': 'CF-R1-F01 preserved separately; original A3 needs/direct deps mismatch'})
with (OUT / 'r1-entry-diff.txt').open('x') as f:
    f.write('\n'.join(diffs))
print(json.dumps({'parsed_tasks': len(parsed), 'document_payload_errors': errors,
      'baseline_bindings': len(binding_rows), 'baseline_matches': sum(r['matches_original_baseline'] and r['after_manifest_matches_baseline'] for r in binding_rows),
      'entries': len(entry_rows), 'insert_only_entries': sum(r['only_insertions'] for r in entry_rows),
      'added_link_errors': added_link_errors}, ensure_ascii=False, indent=2))
