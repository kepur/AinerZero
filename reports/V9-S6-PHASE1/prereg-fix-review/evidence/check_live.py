"""P262 real 84-file closure, CPU only, read-only outside our review directory."""
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parents[1]
REPO = OUT.parents[2]
HERE = REPO / 'reports/V9-S6-PHASE1'
sys.dont_write_bytecode = True


class DenyMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'mlx' or name.startswith('mlx.'):
            raise RuntimeError('FORBIDDEN_MLX_IMPORT: ' + name)


sys.meta_path.insert(0, DenyMLX())


def audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and flags & (1 | 2 | 64 | 512 | 1024):
            if not Path(path).resolve().is_relative_to(OUT):
                raise RuntimeError('WRITE_OUTSIDE_REVIEW: ' + str(path))


sys.addaudithook(audit)
sys.path.insert(0, str(REPO / 'src'))
spec = importlib.util.spec_from_file_location('p262_live_builder', HERE / 'make_prereg.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
PE, GD = B.PE, B.GD
code = GD.build_manifest(REPO, [HERE / 'run_s6p1.py'], src_root=REPO / 'src', extra=[HERE / 'verify_s6p1.py'])
code_sha = PE.manifest_sha(code)
assert len(code) == 42 and code_sha == '839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3'
versions = PE.cpu_versions(REPO)
probe = HERE / 'probe/EVAL-probe.json'
pr, evidence = PE.validate_probe(REPO, probe, code, versions)
assert len(evidence['files_sha256']) == 84
print('LIVE_CLOSURE_VALIDATED', len(evidence['files_sha256']), 'code_files', len(code), 'sha256', code_sha, flush=True)
(OUT / 'evidence/live-closure.json').write_text(json.dumps(evidence, indent=2))
(OUT / 'evidence/numerical-manifest.json').write_text(json.dumps({'manifest': code, 'sha256': code_sha}, indent=2))

# Independent arithmetic for all 8 gate point estimates, not PE/AN point_stats.
import numpy as np
raw = REPO / 'artifacts/v9/s6/phase1/probe/eval-s6p1-probe/errors.npz'
with np.load(raw, allow_pickle=False) as data:
    values = {}
    for t in ('main6', 'extrap10'):
        stats = {}
        counts, eb = data[t + '/counts'], data[t + '/eb']
        for a in ('R', 'E', 'Z', 'T', 'P', 'G'):
            s = data[t + '/sums/' + a][:, :, 3]
            totals = s.sum(axis=2).mean(axis=(0, 1))
            stats[a] = {'D': float(1 - totals[0] / eb.sum()),
                        'wall': float(totals[2] / counts[:, 2].sum()),
                        'free': float(totals[3] / counts[:, 3].sum()),
                        'all': float(totals.sum() / counts.sum())}
        values[t] = stats
m, x = values['main6'], values['extrap10']
points = {'GS': m['E']['D'] - m['R']['D'],
          'GT': m['E']['D'] - m['R']['D'] - .5 * (m['T']['D'] - m['R']['D']),
          'GZ-D': m['E']['D'] - m['Z']['D'], 'GZ-W': m['E']['wall'] / m['Z']['wall'],
          'GK-A': m['E']['all'] / m['R']['all'], 'GK-F': m['E']['free'] / m['Z']['free'],
          'GP': m['P']['D'] - m['R']['D'], 'GX': x['E']['D'] - x['R']['D']}
for g in points:
    # Only interval construction uses the log scale; point estimates are ratios.
    assert abs(points[g] - pr['result']['gates'][g]['point']) < 1e-12
print('INDEPENDENT_GATE_POINTS', json.dumps(points), flush=True)

# Independent original-formula extrapolation, then the unmodified public builder.
train = 1.15 * (sum(pr['train_seconds'][a + '-r0'] * (3 if a == 'G' else 5) for a in ('R', 'E', 'Z', 'T', 'P', 'G')) + 450)
ev = 1.3 * (pr['verify_seconds'] * (28 / 6) + pr['eval_seconds'] * (28 / 6) * 4)
assert abs(train - 18072.25) < 1e-6 and abs(ev - 4212.693333333334) < 1e-6
op = OUT / 'LIVE-MUST-NOT-BE-WRITTEN.json'
assert not op.exists()
sys.argv = ['make_prereg.py', '--design', str(REPO / 'reports/V9-S6-DESIGN/DESIGN-r2.md'),
            '--probe', str(probe), '--out', str(op)]
try:
    B.main()
except PE.EvidenceError as exc:
    message = str(exc)
    assert '预计超出上限' in message
    print('EXPECTED_REAL_BUILDER_REFUSAL', message, flush=True)
else:
    raise AssertionError('Real probe must not generate preregistration above budget')
assert not op.exists()
assert not GD.check_manifest(REPO, evidence['files_sha256'])
assert not GD.check_manifest(REPO, code)
assert not any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules)
result = {'closure_files': len(evidence['files_sha256']), 'numerical_files': len(code),
          'numerical_sha256': code_sha, 'report_sha256': hashlib.sha256(probe.read_bytes()).hexdigest(),
          'estimated_train_s': train, 'estimated_eval_s': ev, 'train_cap_s': 21600, 'eval_limit_s': 3600,
          'builder_refused': True, 'refusal': message, 'output_created': op.exists(), 'mlx_imported': False,
          'independent_gate_points': points, 'raw_science_all_pass': pr['result']['all_pass']}
(OUT / 'evidence/live-result.json').write_text(json.dumps(result, indent=2))
print('LIVE_ALL_INPUT_BYTES_UNCHANGED True; MLX_IN_SYS_MODULES False')
