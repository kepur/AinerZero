"""A39: the default pytest entry must be pure CPU (no real MLX import at collection)."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import conftest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent

SENTINEL = '''
import json, os, sys
LOG = os.environ["A39_SENTINEL_LOG"]
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "mlx" or name.startswith("mlx."):
            with open(LOG, "a") as h:
                h.write(json.dumps({"pid": os.getpid(), "module": name}) + "\\n")
            raise RuntimeError("A39 sentinel: real MLX import blocked: " + name)
sys.meta_path.insert(0, _Block())
'''


def _module_level_mlx(path):
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "mlx" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "mlx":
            return True
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if (getattr(call.func, "attr", None) == "importorskip" and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and str(call.args[0].value).split(".")[0] == "mlx"):
                return True
    return False


def test_native_module_inventory_is_complete():
    found = {p.name for p in TESTS.glob("test_*.py") if _module_level_mlx(p)}
    assert found == set(conftest.NATIVE_MODULES)


def test_native_modules_carry_native_mark():
    for name in conftest.NATIVE_MODULES:
        assert 'pytestmark = pytest.mark.native_mlx' in (TESTS / name).read_text(), name


def test_default_collection_imports_no_mlx(tmp_path):
    (tmp_path / "sitecustomize.py").write_text(SENTINEL)
    log = tmp_path / "mlx-attempts.jsonl"
    env = dict(os.environ, A39_SENTINEL_LOG=str(log), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(tmp_path), str(ROOT / "src")]))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "tests"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert not log.exists(), log.read_text()
    collected = result.stdout
    for name in conftest.NATIVE_MODULES:
        assert "tests/" + name not in collected, name
    for nodeid in conftest.NATIVE_TESTS:
        assert nodeid + "\n" not in collected and nodeid + "[" not in collected, nodeid
    assert "deselected" in collected
    json.dumps(collected[-200:])
