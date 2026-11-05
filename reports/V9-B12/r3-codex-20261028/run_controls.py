"""Write new evidence only; refuses to overwrite an existing execution directory.
Run: .venv/bin/python reports/V9-B12/r3-codex-20261028/run_controls.py --output NEW_DIR
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
p = argparse.ArgumentParser()
p.add_argument('--output', required=True)
args = p.parse_args()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=False)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Only copied sources are mutated. Keep copies, logs and commands for review.
work = out / 'copy'
shutil.copytree(ROOT / 'src', work, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
original = {str(x.relative_to(work)): x.read_bytes() for x in work.rglob('*.py')}
assert all(sha(ROOT / 'src' / x) == hashlib.sha256(b).hexdigest() for x, b in original.items())
block = out / 'import_block'
block.mkdir()
(block / 'sitecustomize.py').write_text('''import sys
class NoModels:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mlx', 'torch', 'onnxruntime', 'transformers'):
            raise RuntimeError('B12 CPU-only import blocked: ' + fullname)
sys.meta_path.insert(0, NoModels())
''')
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
           PYTHONPATH=os.pathsep.join(map(str, [block, work, ROOT / 'tests/v9/contracts'])))
records = []

def execute(label, argv):
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    record = {'label': label, 'argv': list(map(str, argv)), 'cwd': str(ROOT),
              'PYTHONPATH': env['PYTHONPATH'], 'returncode': result.returncode}
    (out / (label + '.txt')).write_text(json.dumps(record) + '\nSTDOUT\n' + result.stdout + '\nSTDERR\n' + result.stderr)
    records.append(record)
    return result

sp = work / 'ainerzero/v9/interfaces/spatial_memory.py'
vp = work / 'ainerzero/v9/interfaces/validation.py'
sp0, vp0 = sp.read_text(), vp.read_text()
# Original rejected candidate reconstructed and SHA-checked against pre-edit manifest.
a = sp0.index('        try:\n', sp0.index('def require_evidence'))
b = sp0.index('        return evidence', a)
old_gate = '''        if not evidence.is_v2():
            raise EvidenceRequired(
                f"promote() only accepts PromotionEvidence schema_version='v2', got "
                f"{evidence.schema_version!r}; v1 evidence stays readable but may not promote "
                "(ADR-0014 §3 C1, fail-closed)"
            )
        require_independent_slow_producer(evidence.producer, trusted_context=evidence.trusted_context)
        require_slow_eligible_origin(evidence.origin_category)   # V9.B13 K3：起源轴；LLM/教师起源不能靠换 producer 晋升
'''
old_sp = (sp0[:a] + old_gate + sp0[b:]).replace('只接受 v2 证据；在消费时复验完整不变量，不信任构造历史。', '只接受 v2 证据，并再跑一次独立出具者守卫。')
new_origin = '''    from .types import KNOWLEDGE_ORIGIN_CATEGORIES

    if (not isinstance(origin_category, str)
            or origin_category not in KNOWLEDGE_ORIGIN_CATEGORIES
            or origin_category in SLOW_FORBIDDEN_ORIGINS):
'''
old_vp = vp0.replace(new_origin, '    if origin_category in SLOW_FORBIDDEN_ORIGINS:\n')
before = json.loads((HERE / 'before.json').read_text())['sha256']
for path, data in ((sp, old_sp), (vp, old_vp)):
    rel = 'src/' + str(path.relative_to(work))
    assert hashlib.sha256(data.encode()).hexdigest() == before[rel], rel
    path.write_text(data)
execute('00-rejected-r2-original-failures', [sys.executable, '-m', 'pytest', 'tests/v9/contracts/test_promotion_consumption_r3.py', '-q', '-p', 'no:cacheprovider'])
sp.write_text(sp0)
vp.write_text(vp0)
result = execute('01-contracts', [sys.executable, '-m', 'pytest', 'tests/v9/contracts', '-q', '-p', 'no:cacheprovider', '--junitxml=' + str(out / 'contracts.xml')])
assert result.returncode == 0
baseline = json.loads(execute('02-ordinary-negatives', [sys.executable, str(HERE / 'probe.py')]).stdout)
assert [r['outcome'] for r in baseline['rows']] == ['promoted_and_usable'] + ['rejected'] * 5

# G1: remove only version rejection. Same full v2 field payload, v1 label.
start = sp0.index('            if values["schema_version"] != "v2":')
end = sp0.index('            require_independent_slow_producer', start)
# G5: absence branch returns registry category, rather than dereferencing None.
# Existing bound-context/category/digest guards are unchanged for present bindings.
g5a = vp0.index('    if matched is None:')
g5b = vp0.index('    bound_context =', g5a)
mutants = [
    ('G1', sp, sp0[:start] + sp0[end:], 'G1'),
    ('G5', vp, vp0[:g5a] + '    if matched is None:\n        return category  # mutant: accept absent binding\n\n' + vp0[g5b:], 'G5'),
    ('origin', sp, sp0.replace('            require_slow_eligible_origin(values["origin_category"])\n', ''), 'origin'),
    ('v2-overlap', sp, sp0.replace('            evidence = PromotionEvidence(**values)\n', ''), 'overlap'),
    ('v2-kind', sp, sp0.replace('            evidence = PromotionEvidence(**values)\n', ''), 'kind'),
]
results = []
for name, path, mutant, target in mutants:
    prior = path.read_bytes()
    assert mutant.encode() != prior
    path.write_text(mutant)
    mutated_sha = sha(path)
    result = execute('03-mutant-' + name, [sys.executable, str(HERE / 'probe.py')])
    path.write_bytes(prior)
    assert result.returncode == 0
    probe = json.loads(result.stdout)
    rows = {r['case']: r['outcome'] for r in probe['rows']}
    assert rows['positive'] == rows[target] == 'promoted_and_usable', (name, rows)
    # Each other independent gate must retain its rejection; full-v2 gate covers both overlap/kind.
    flipped = {'overlap', 'kind'} if name.startswith('v2-') else {target}
    assert all(rows[x] == 'rejected' for x in ('G1','G5','origin','overlap','kind') if x not in flipped)
    results.append({'mutant': name, 'target': target, 'baseline': 'rejected',
                    'mutated': rows[target], 'positive': rows['positive'],
                    'source_sha256': hashlib.sha256(prior).hexdigest(),
                    'mutated_sha256': mutated_sha, 'restored_sha256': sha(path)})
assert all((work / x).read_bytes() == data for x, data in original.items())
assert all((ROOT / 'src' / x).read_bytes() == data for x, data in original.items())
(out / 'execution.json').write_text(json.dumps({'commands': records, 'controls': results,
    'source_restored': True, 'ordinary_negatives': baseline}, indent=2, allow_nan=False))
print(json.dumps({'contract_returncode': 0, 'genuine_success_controls': results}, indent=2))
