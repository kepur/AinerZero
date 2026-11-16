"""P266 independent mutation verification on isolated git archive b40d97e0."""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REAL_ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero').resolve()
REVIEW_DIR = REAL_ROOT / 'reports/V9-S6-PHASE1/p264-review'
EVIDENCE_DIR = REVIEW_DIR / 'evidence'
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# 1. Create isolated copy from git archive b40d97e0
tmp_dir = tempfile.mkdtemp(prefix='p266-mutation-sandbox-')
sandbox = Path(tmp_dir).resolve()
assert str(sandbox) != str(REAL_ROOT), 'Target must not be real repository!'
assert not sandbox.is_relative_to(REAL_ROOT), 'Target must be outside real repository!'
print(f'Isolated sandbox created at: {sandbox}')

# Export b40d97e0
data = subprocess.run(['git', 'archive', 'b40d97e0'], cwd=REAL_ROOT, capture_output=True, check=True).stdout
with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
    archive.extractall(sandbox)

# Also ensure local uncommitted files or tests are copied if needed
# In b40d97e0 everything was committed, so archive has all required files.
print('Git archive extracted successfully.')

PY = REAL_ROOT / '.venv/bin/python'
env = os.environ.copy()
env['PYTHONPATH'] = str(sandbox / 'src')
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['S6_PREREG_GIT_REPO'] = str(REAL_ROOT)

def run_pytest(extra_args=None):
    cmd = [
        str(PY), '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
        'tests/v9/experiments/test_s6_prereg.py',
        'tests/v9/experiments/test_s6_prereg_identity.py'
    ]
    if extra_args:
        cmd.extend(extra_args)
    r = subprocess.run(cmd, cwd=sandbox, env=env, capture_output=True, text=True)
    return r

# Run baseline
print('Running baseline tests...')
base_res = run_pytest()
print('Baseline return code:', base_res.returncode)
last_line = base_res.stdout.strip().splitlines()[-1] if base_res.stdout.strip() else ''
print('Baseline summary:', last_line)
assert base_res.returncode == 0, f'Baseline tests failed: {base_res.stderr}'
assert '150 passed' in last_line

# Define mutations: (id, relative_path, old_str, new_str, description)
mutations = [
    # Author mutations to re-verify (5 of 14)
    ('P1', 'reports/V9-S6-PHASE1/make_prereg.py',
     '    PE.require(hashlib.sha256(data).hexdigest() == PROBE_REPORT_SHA256, "probe report SHA differs from the recorded anchor")',
     '    pass',
     'Author P1: make_prereg skips probe report anchor verification'),

    ('P4', 'reports/V9-S6-PHASE1/prereg_evidence.py',
     'def estimate_budget(pr, final):',
     'def estimate_budget(pr, final):\n    final = pr["sets"]["final"]',
     'Author P4: prereg_evidence takes budget caps from probe record (old caps) instead of frozen runner'),

    ('P7', 'reports/V9-S6-PHASE1/make_prereg.py',
     '    environment = PI.mlx_environment()',
     '    environment = {}',
     'Author P7: make_prereg skips MLX_* environment variables check'),

    ('P10', 'reports/V9-S6-PHASE1/make_prereg.py',
     ' and design.name == "DESIGN-r3.md"',
     '',
     'Author P10: make_prereg accepts any design file name instead of DESIGN-r3.md'),

    ('P14', 'reports/V9-S6-PHASE1/prereg_identity.py',
     '        values[name] = _number(final.values[idx[0]], fold=old)',
     '        values[name] = _number(final.values[idx[0]], fold=True)',
     'Author P14: prereg_identity allows expression for new values (fold=True)'),

    # Custom independent mutations (3 custom)
    ('M1', 'reports/V9-S6-PHASE1/prereg_identity.py',
     'NEW = {"train_cap_s": 19800, "eval_limit_s": 5400, "third_party": ("numpy", "mlx.core")}',
     'NEW = {"train_cap_s": 19800, "eval_limit_s": 5400, "third_party": ("numpy", "mlx")}',
     'Custom M1: prereg_identity mistakenly allows old third_party tuple ("numpy", "mlx") as NEW'),

    ('M2', 'reports/V9-S6-PHASE1/prereg_identity.py',
     'NEW = {"train_cap_s": 19800, "eval_limit_s": 5400, "third_party": ("numpy", "mlx.core")}',
     'NEW = {"train_cap_s": 21600, "eval_limit_s": 3600, "third_party": ("numpy", "mlx.core")}',
     'Custom M2: prereg_identity accepts old budget caps (21600/3600) instead of r3 caps'),

    ('M3', 'reports/V9-S6-PHASE1/prereg_identity.py',
     '    require(old_dump == new_dump, "the runner differs from the probe\'s beyond the three registered constants")',
     '    pass',
     'Custom M3: prereg_identity skips comparing masked syntax trees')
]

results = []
for mut_id, rel_path, old_s, new_s, desc in mutations:
    target_file = sandbox / rel_path
    orig_content = target_file.read_text(encoding='utf-8')
    assert old_s in orig_content, f'Target string not found for mutation {mut_id} in {rel_path}'
    mutated_content = orig_content.replace(old_s, new_s, 1)
    target_file.write_text(mutated_content, encoding='utf-8')

    print(f'Running mutation {mut_id}: {desc}...')
    res = run_pytest(['-x']) # stop on first failure for speed
    killed = res.returncode != 0
    fail_summary = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else res.stderr.strip()
    print(f'  Result: {"KILLED" if killed else "SURVIVED"} (rc={res.returncode}): {fail_summary}')

    # Find which test failed
    failed_test = None
    for line in res.stdout.splitlines():
        if 'FAILED ' in line:
            failed_test = line.strip()
            break

    results.append({
        'id': mut_id,
        'description': desc,
        'file': rel_path,
        'killed': killed,
        'returncode': res.returncode,
        'summary': fail_summary,
        'failed_test': failed_test
    })

    # Restore original content
    target_file.write_text(orig_content, encoding='utf-8')

# Final check that sandbox is clean and passes all tests
final_res = run_pytest()
assert final_res.returncode == 0, 'Sandbox not cleanly restored!'
print('Sandbox cleanly restored and verified.')

# Clean up sandbox
shutil.rmtree(sandbox)
print('Sandbox removed.')

# Save mutation results
(EVIDENCE_DIR / 'mutation-results.json').write_text(json.dumps(results, indent=2))
print('Saved mutation results to evidence/mutation-results.json')
assert all(r['killed'] for r in results), 'Not all mutations were killed!'
print('All 8 mutations (5 author + 3 custom) successfully killed by test suite!')
