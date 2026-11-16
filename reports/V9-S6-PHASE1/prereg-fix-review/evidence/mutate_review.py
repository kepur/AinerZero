"""P262 independently authored production-validator mutations, copies only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

OUT = Path(__file__).resolve().parents[1]
REL = 'reports/V9-S6-PHASE1/prereg_evidence.py'
BASE = OUT / 'snapshot'
original = (BASE / REL).read_text()
mutants = [
    ('I1-open-ledger', "same(row['closed'], True, 'training ledger must be closed')", 'pass  # I1', 'test_independent_closed_ledger'),
    ('I2-old-train-code', "same(row['code_manifest_sha256'], code_sha, 'training/evaluation/current code identity')", 'pass  # I2', 'test_independent_old_training_identity'),
    ('I3-no-retraining-records', "keys(v['retrain'], ('E-r0-n0', 'P-r0-n0'), 'retraining cells')", 'pass  # I3', 'test_independent_missing_all_retraining'),
    ('I4-world-order', "same(worlds, {'main6': [[w, 6] for w in range(50)], 'extrap10': [[1000 + w, 10] for w in range(25)]}, 'test world identities')", 'pass  # I4', 'test_independent_reordered_world_identity'),
    ('I5-counts-dtype', "and arr.dtype.kind in ('iu' if key == 'counts' else 'f')", 'and True', 'test_independent_float_counts'),
    ('I6-weight-hash', "require(actual == want, f'hash differs: {directory / name}')", 'pass  # I6', 'test_independent_last_saved_weight_integrity'),
    ('I7-negative-number', 'and (value >= 0 if zero else value > 0)', 'and True', 'test_independent_invalid_contact_share'),
]
jobs = []
for name, old, new, target in mutants:
    assert original.count(old) == 1, name
    dest = OUT / 'mutations' / name
    snap = dest / 'snapshot'
    shutil.copytree(BASE, snap)
    changed = original.replace(old, new, 1)
    (snap / REL).write_text(changed)
    meta = {'name': name, 'source_file': REL, 'target': target,
            'before_sha256': hashlib.sha256(original.encode()).hexdigest(),
            'after_sha256': hashlib.sha256(changed.encode()).hexdigest(), 'old': old, 'new': new}
    (dest / 'mutation.json').write_text(json.dumps(meta, indent=2))
    jobs.append((dest, snap, meta))


def run(job):
    dest, snap, meta = job
    argv = [sys.executable, '-B', str(OUT / 'evidence/run_tests.py'), str(snap), meta['name'], '-k', meta['target']]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    text = r.stdout + r.stderr
    (dest / 'pytest.out').write_text(text)
    meta.update(argv=argv, returncode=r.returncode,
                killed=r.returncode == 1 and 'DID NOT RAISE' in text and '1 failed' in text and 'MLX_IN_SYS_MODULES False' in text)
    print(meta['name'], 'KILLED' if meta['killed'] else 'NOT_KILLED', 'returncode', r.returncode, flush=True)
    return meta


with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(run, jobs))
(OUT / 'evidence/mutation-results.json').write_text(json.dumps(results, indent=2))
assert all(r['killed'] for r in results)
print('INDEPENDENT_PRODUCTION_MUTATIONS_KILLED', len(results), 'of', len(results))
