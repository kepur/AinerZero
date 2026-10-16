"""Run baseline + new adverse cases in real subprocesses; preserve all failures."""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
TMP = OUT / 'tmp'
TMP.mkdir(exist_ok=False)
original = json.loads((ROOT / 'docs/research/adapter_registry.json').read_text())
md = (ROOT / 'docs/research/ADAPTER_REGISTRY.md').read_text()
records = []


def run(name, obj, text, mode, expected):
    jp, mp = TMP / (name + '.json'), TMP / (name + '.md')
    jp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    mp.write_text(text)
    argv = [sys.executable, '-B', str(OUT / 'independent_check.py'), mode, str(jp), str(mp)]
    proc = subprocess.run(argv, capture_output=True, text=True)
    (OUT / (name + '.log')).write_text(proc.stdout + proc.stderr)
    row = {'case': name, 'argv': argv, 'expected_exit': expected,
           'actual_exit': proc.returncode,
           'input_json_sha256': hashlib.sha256(jp.read_bytes()).hexdigest(),
           'input_md_sha256': hashlib.sha256(mp.read_bytes()).hexdigest(),
           'log': str(OUT / (name + '.log'))}
    records.append(row)
    assert proc.returncode == expected, row


run('original_schema', original, md, 'schema', 0)
run('original_wrong_date', original, md, 'date', 1)
run('original_thick_missing_repo', original, md, 'thick_repo', 1)
run('original_thick_missing_license', original, md, 'thick_license', 1)
# This is a checker control fixture, NOT a changed registry or proposed release.
# Only the three independently observed facts are substituted in this report dir.
positive = copy.deepcopy(original)
emap = {e['id']: e for e in positive['entries']}
emap['stable-worldmodel']['paper']['date'] = '2026-05-20 (v1)'
emap['thick']['repo']['url'] = 'https://github.com/CognitiveModeling/THICK'
emap['thick']['license']['license'] = 'MIT'
positive_md = md.replace('2026-05-26', '2026-05-20').replace('| 未找到官方仓库（不臆测） | 未核 |', '| https://github.com/CognitiveModeling/THICK | MIT |')
run('control_fixture_facts', positive, positive_md, 'facts', 0)
cases = [
    ('adverse_01_missing_entry', 'count', 'schema'),
    ('adverse_02_duplicate_id', 'duplicate', 'schema'),
    ('adverse_03_bad_paper_url', 'url', 'schema'),
    ('adverse_04_calendar_date', 'calendar', 'schema'),
    ('adverse_05_empty_license', 'license', 'schema'),
    ('adverse_06_no_limitations', 'limitations', 'schema'),
    ('adverse_07_false_paper_date', 'date', 'facts'),
    ('adverse_08_false_thick_repo', 'repo', 'facts'),
    ('adverse_09_false_thick_license', 'thick_license', 'facts'),
    ('adverse_10_markdown_divergence', 'md_license', 'schema'),
]
for name, mutation, mode in cases:
    obj, text = copy.deepcopy(positive), positive_md
    emap = {e['id']: e for e in obj['entries']}
    if mutation == 'count': obj['entries'].pop()
    elif mutation == 'duplicate': obj['entries'][-1]['id'] = 'h-jepa'
    elif mutation == 'url': emap['h-jepa']['paper']['url'] = 'https://'
    elif mutation == 'calendar': obj['access_date'] = '2026-02-30'
    elif mutation == 'license': emap['egnn']['license']['license'] = ''
    elif mutation == 'limitations': emap['lewm']['non_inferables'] = []
    elif mutation == 'date': emap['stable-worldmodel']['paper']['date'] = '2026-05-26'
    elif mutation == 'repo': emap['thick']['repo']['url'] = '未找到（故意伪造）'
    elif mutation == 'thick_license':
        emap['thick']['license']['license'] = 'Apache-2.0'
        text = text.replace('| https://github.com/CognitiveModeling/THICK | MIT |', '| https://github.com/CognitiveModeling/THICK | Apache-2.0 |')
    elif mutation == 'md_license':
        text = text.replace('| MIT | 中（小而干净；需移植验证）', '| Apache-2.0 | 中（小而干净；需移植验证）')
    assert obj != positive or text != positive_md, 'mutation must actually change input'
    run(name, obj, text, mode, 1)
assert len(records) == 15
assert sum(r['actual_exit'] != 0 for r in records if r['case'].startswith('adverse')) == 10
for p, digest in json.loads((OUT / 'input_sha256.json').read_text()).items():
    assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest, 'R1 input changed during verification: ' + p
(OUT / 'controls.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
print('15 subprocess results verified: 2 green, 3 original fact failures, 10 new red controls; R1 inputs unchanged')
