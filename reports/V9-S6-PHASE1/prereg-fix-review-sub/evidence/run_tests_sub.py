"""P262-sub reviewer driver: run test_s6_prereg.py inside an ISOLATED copy with MLX imports blocked.

usage: python -B run_tests_sub.py <copy_root> <basetemp> [extra pytest args]

- Installs a meta-path finder that raises on any mlx / mlx.* import (no fake mlx installed).
- Puts <copy_root>/src first on sys.path; after the run prints where ainerzero, the builder and the
  helper were loaded from, so a run that silently used the live repository is visible.
- Uses the copy's own pyproject/conftest (project default CPU entry), no cache provider.
"""
import importlib.abc
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


class NoMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            raise RuntimeError("P262-sub FORBIDDEN MLX IMPORT: " + fullname)


sys.meta_path.insert(0, NoMLX())
root = Path(sys.argv[1]).resolve()
basetemp = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / "src"))
import pytest  # noqa: E402

args = [str(root / "tests/v9/experiments/test_s6_prereg.py"), "--rootdir", str(root), "-p", "no:cacheprovider",
        "--basetemp", str(basetemp), "-q", *sys.argv[3:]]
print("ARGV", json.dumps([sys.executable, __file__, *sys.argv[1:]]), flush=True)
print("PYTEST_ARGS", json.dumps(args), flush=True)
rc = pytest.main(args)
mods = {n: getattr(m, "__file__", None) for n, m in list(sys.modules.items())
        if n in ("ainerzero", "prereg_evidence", "s6_prereg_builder_test", "ainerzero.v9.experiments.s6.analysis",
                 "ainerzero.v9.experiments.s3.run_guard")}
print("MODULE_ORIGINS", json.dumps(mods, sort_keys=True), flush=True)
print("ALL_FROM_COPY", all(str(v).startswith(str(root)) for v in mods.values() if v), flush=True)
print("MLX_IN_SYS_MODULES", any(n == "mlx" or n.startswith("mlx.") for n in sys.modules), flush=True)
print("PYTEST_RC", int(rc), flush=True)
raise SystemExit(rc)
