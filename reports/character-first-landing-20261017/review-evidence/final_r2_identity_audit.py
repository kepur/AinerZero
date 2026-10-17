"""r2勘误与最终条件发布身份；独立只读GET收尾，不运行产品代码。"""
import hashlib
import json
import re
import urllib.request
from pathlib import Path

B = Path('/Users/mac/AinerWorkFlow/AinerZero/reports/character-first-landing-20261017')
O = B / 'review-evidence'


def read(p):
    return json.loads(Path(p).read_text())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def get(p):
    with urllib.request.urlopen('http://127.0.0.1:8790' + p, timeout=15) as r:
        return json.load(r)


def save(name, v):
    with (O / name).open('x') as f:
        json.dump(v, f, ensure_ascii=False, indent=2)
        f.write('\n')


r1 = read(B / 'source-after.json')
r2 = read(B / 'revision-r2/source-after.json')
pub = read(B / 'publication.json')
prior = read(O / 'independent-live-tasks.json')
payload = read(B / 'workbench/payloads.json')
cfids = [f"{p['project']}.{p['phase']}.{p['track']}{p['seq']}" for p in payload]
old = read(B / 'workbench/old-gated-tasks-before.json')
now = {tid: get('/api/tasks/' + tid) for tid in dict.fromkeys(cfids + list(old))}
static = ['title', 'kind', 'tier', 'status', 'prompt', 'params', 'params_version', 'acceptance', 'context_files',
          'file_scope', 'depends_on', 'verifies', 'needs_gpu', 'needs', 'dedupe_key', 'max_attempts', 'max_stalls',
          'lease_s', 'callback_url', 'workdirs']
old_deltas = [{'task': tid, 'field': k, 'before': t.get(k), 'after': now[tid].get(k)}
              for tid, t in old.items() for k in static if t.get(k) != now[tid].get(k)]
cf_deltas = [{'task': tid, 'field': k, 'previous': prior[tid].get(k), 'final': now[tid].get(k)}
             for tid in cfids for k in static if prior[tid].get(k) != now[tid].get(k)]
checks = {}
for category in ['output_files', 'immutable_references', 'original_published_input_snapshots']:
    checks[category] = [{'path': x['path'], 'matches': sha(x['path']) == x['sha256'] and Path(x['path']).stat().st_size == x['size_bytes']}
                        for x in r2[category]]
before = read(B / 'source-before.json')
checks['backups'] = [{'path': x['backup_path'], 'matches': sha(x['backup_path']) == x['sha256'] and Path(x['backup_path']).stat().st_size == x['size_bytes']}
                     for x in before['edited_existing_files']]
frozen = {
    B / 'source-after.json': 'cf2ee745a8d6174c0d8e1dc75e80c0213a78847a0e9e03a0264d94fd13fee3d4',
    B / 'revision-r2/r1source-after.json': 'cf2ee745a8d6174c0d8e1dc75e80c0213a78847a0e9e03a0264d94fd13fee3d4',
    B / 'revision-r2/plan.r1.md': 'f4402743cd5c5da1e281b53557d3f78fec95dbc002ed50cb170f45bd568c0137',
    B / 'revision-r2/publication-r1/DECISION.md': 'af40a3ea284e4506bee8b3265585290eaa80cdca630a5cd537aa10dcc329ff80',
    B / 'revision-r2/publication-r1/publication.json': '3b2f179fee03230de0a07c9888db8544f4d03a664b7f21727c77bcd1ea80627b',
    B / 'revision-r2/source-after.json': '2c9ffc2ac0f830468d3bd189872ceb80918cc97407682dc925cc816c499691ad',
    B / 'DECISION.md': 'e4dccb35d0f780bdc19e0803da571a8f858dbbfe1112ff2ed8dfb10ac11ad801',
    B / 'publication.json': 'ab14a9ddf1b0252332505bb41591f20944d05922f2a473c4e121fa39aa1067de',
    Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md'): 'b0f483d34ae86263047e16340b2bb7b6ad5e4ec11f43c138ca55bf997333fff9',
}
frozen_checks = [{'path': str(p), 'actual_sha256': sha(p), 'expected_sha256': x, 'matches': sha(p) == x} for p, x in frozen.items()]
plan = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md').read_text().splitlines()
a3_needs = [x.strip() for x in re.search(r'`([^`]+)`', plan[91]).group(1).split(',')]
a3_deps = re.findall(r'(?:awz|hub)\.[A-Za-z0-9]+\.[A-Za-z]\d+', plan[92])
changed_outputs = [{'path': x['path'], 'r1_sha256': r1['output_files'][i]['sha256'], 'r2_sha256': x['sha256']}
                   for i, x in enumerate(r2['output_files']) if x['sha256'] != r1['output_files'][i]['sha256']]
registry_path = Path('/Users/mac/AinerWorkFlow/AinerRelay/modules/modules.v1.json')
summary = {
    'schema': 'CF-independent-final-r2/v1', 'frozen_checks': frozen_checks, 'file_checks': checks,
    'changed_outputs_from_r1': changed_outputs, 'final_live_old_deltas': old_deltas,
    'final_live_cf_deltas_since_r1_audit': cf_deltas,
    'r2_A3_needs_match_live': a3_needs == now['awz.P3.A3']['needs'],
    'r2_A3_deps_match_live': a3_deps == now['awz.P3.A3']['depends_on'],
    'publication_source_manifest_match': sha(pub['source_manifest']['path']) == pub['source_manifest']['sha256'],
    'publication_decision_match': sha(pub['decision']['path']) == pub['decision']['sha256'],
    'publication_all_content_matches': all(sha(x['path']) == x['sha256'] and Path(x['path']).stat().st_size == x['size_bytes'] for x in pub['content_files']),
    'publication_payloads_match': sha(B / 'workbench/payloads.json') == pub['workbench']['payloads_sha256'],
    'publication_registry_match': sha(registry_path) == pub['workbench']['registry_sha256'],
    'projects_still_unchanged': get('/api/projects') == read(B / 'workbench/projects.json'),
    'A1_A2_A3_observed': {t: {'status': now[t]['status'], 'assignee': now[t]['assignee']} for t in ['awz.CF.A1','awz.CF.A2','awz.CF.A3']},
    'A10_status': now['awz.V9.A10']['status'], 'limits': 'metadata only; conditional adoption not yet effective'}
save('final-r2-live-tasks.json', now)
save('final-r2-result.json', summary)
print(json.dumps({**{k: v for k, v in summary.items() if k not in ['frozen_checks','file_checks','final_live_cf_deltas_since_r1_audit']},
                  'frozen_matches': sum(x['matches'] for x in frozen_checks), 'frozen_count': len(frozen_checks),
                  'file_counts': {k: {'count': len(v), 'matches': sum(x['matches'] for x in v)} for k, v in checks.items()},
                  'cf_delta_keys': [(x['task'],x['field']) for x in cf_deltas]}, ensure_ascii=False, indent=2))
