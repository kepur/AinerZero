"""P262-sub: does source_sets() evaluate attribute chains it claims to exclude? (harmless payload, isolated copy)

usage: python -B source_sets_dunder_sub.py <isolated_copy_root>
Adds one key to the copy's run_s6p1.py SETS whose value walks ().__class__.__base__.__subclasses__() and only
counts the result. Calls PE.source_sets on the copy. The payload executes no command; it only shows that the
node filter (Attribute/Call allowed without name restriction) does not confine evaluation to configuration
literals, and that source_sets runs before the code-identity check in validate_probe.
"""
import importlib.abc
import importlib.util
import sys
from pathlib import Path

sys.dont_write_bytecode = True


class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            raise RuntimeError("forbidden MLX import: " + fullname)


sys.meta_path.insert(0, NoMLX())
root = Path(sys.argv[1]).resolve()
assert not root.is_relative_to(Path("/Users/mac/AinerWorkFlow/AinerZero"))
runner = root / "reports/V9-S6-PHASE1/run_s6p1.py"
src = runner.read_text()
old = '    "final": {"cand_ns": "s6p1-cand"'
assert src.count(old) == 1
runner.write_text(src.replace(old, '    "reached": ().__class__.__base__.__subclasses__().__len__(),\n' + old))
sys.path.insert(0, str(root / "src"))
spec = importlib.util.spec_from_file_location("pe_sub", root / "reports/V9-S6-PHASE1/prereg_evidence.py")
PE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PE)
sets = PE.source_sets(root)
print("SOURCE_SETS_KEYS", sorted(sets))
print("EVALUATED_DUNDER_CHAIN_RESULT", sets.get("reached"))
print("MLX_IN_SYS_MODULES", any(k == "mlx" or k.startswith("mlx.") for k in sys.modules))
