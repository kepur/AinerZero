"""Read-only state check, not a freeze or a model evaluation."""
import importlib.abc
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            raise RuntimeError('P261 forbidden MLX import: ' + fullname)
sys.meta_path.insert(0, NoMLX())
repo = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(repo / 'src'))
sys.path.insert(0, str(repo / 'reports/V9-S6-PHASE1'))
import make_prereg as B
probe = repo / 'reports/V9-S6-PHASE1/probe/EVAL-probe.json'
pr = json.loads(probe.read_text())
code = B.GD.build_manifest(repo, [B.RUNNER], src_root=repo / 'src', extra=[B.VERIFY])
print('CURRENT_NUMERICAL_MANIFEST', len(code), B.PE.manifest_sha(code))
print('REAL_REPORT_FIELDS', sorted(pr))
print('REAL_REPORT_SHA256', B.GD.sha256_file(probe))
try:
    pr, evidence = B.PE.validate_probe(repo, probe, code, B.PE.cpu_versions(repo))
    print('COMPLETE_LIVE_CLOSURE', json.dumps(evidence, sort_keys=True))
    try:
        print('BUDGET_ESTIMATE', B.PE.estimate_budget(pr))
    except B.PE.EvidenceError as exc:
        print('BUDGET_REFUSED', str(exc))
except (B.PE.EvidenceError, KeyError, OSError) as exc:
    print('LIVE_NOT_ACCEPTED', type(exc).__name__, str(exc))
print('FORMAL_OUTPUT_WRITES', 0)
print('MLX_IN_SYS_MODULES', any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules))
