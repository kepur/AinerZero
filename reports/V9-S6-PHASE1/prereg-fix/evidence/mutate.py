"""Persist and exercise adversarial source mutations in isolated CPU snapshots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from ainerzero.v9.experiments.s3 import run_guard as GD
HERE = ROOT / 'reports/V9-S6-PHASE1'
OUT = HERE / 'prereg-fix/evidence' / (sys.argv[1] if len(sys.argv) > 1 else 'mutations')
OUT.mkdir(exist_ok=False)
code = GD.build_manifest(ROOT, [HERE / 'run_s6p1.py'], src_root=ROOT / 'src', extra=[HERE / 'verify_s6p1.py'])
mutants = [
    ('M1-replay-summary-only', "    check_verify(v, recs)", "    # MUTANT accepts summary only", 'replay-false or replay-truthy or retrain-false'),
    ('M2-training-code-unchecked', "        same(row['code_manifest_sha256'], code_sha, 'training/evaluation/current code identity')", "        # MUTANT omits training code identity", 'training-code'),
    ('M3-gates-not-recomputed', "    same(pr['result'], AN.decide(analysis_input(arrays, 3)), 'recomputed gates')", "    # MUTANT trusts reported gates", 'empty-gates or gate-value or gate-bool'),
    ('M4-budget-guard-removed', 'and est_train <= final[\'train_cap_s\'] and est_eval <= final[\'eval_limit_s\']', 'and True', 'budget_boundaries or over-budget'),
    ('M5-file-hash-unchecked', "            require(actual == want, f'hash differs: {directory / name}')", '            # MUTANT trusts file hashes', 'weights or eval-hash'),
    ('M6-rounds-unchecked', "        same(row['rounds_ok'], [True] * (3 * len(rec['tracks'])), 'replayed selection rounds')", '        # MUTANT omits per-round verification', 'replay-truthy'),
]
results = []
for name, old, new, selection in mutants:
    snap = OUT / name / 'snapshot'
    for rel in [*code, 'reports/V9-S6-PHASE1/make_prereg.py', 'reports/V9-S6-PHASE1/prereg_evidence.py',
                'tests/v9/experiments/test_s6_prereg.py', 'reports/V9-S6-DESIGN/DESIGN-r2.md']:
        dest = snap / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    target = snap / 'reports/V9-S6-PHASE1/prereg_evidence.py'
    source = target.read_text()
    assert source.count(old) == 1, (name, source.count(old))
    target.write_text(source.replace(old, new))
    command = [sys.executable, '-B', str(HERE / 'prereg-fix/evidence/run_cpu.py'), str(snap), '-k', selection]
    with (OUT / name / 'pytest.log').open('w') as log:
        run = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=log, stderr=subprocess.STDOUT)
    output = (OUT / name / 'pytest.log').read_text()
    row = {'mutation': name, 'old': old, 'new': new, 'argv': command, 'returncode': run.returncode,
           'killed': run.returncode == 1 and 'FAILED' in output and 'MLX_IN_SYS_MODULES False' in output,
           'mutant_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    results.append(row)
    print(json.dumps(row), flush=True)
(OUT / 'results.json').write_text(json.dumps(results, indent=2))
assert all(r['killed'] for r in results)
