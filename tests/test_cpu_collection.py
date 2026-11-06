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

# Same blocker, but it also records which test module was being collected: the outermost
# ``tests/**/test_*.py`` frame on the stack (a test module importing another test module
# is attributed to the one pytest was collecting).
SENTINEL_ATTRIBUTING = '''
import json, os, sys
LOG = os.environ["A39_SENTINEL_LOG"]
TESTS = os.environ["A39_TESTS_DIR"]
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "mlx" or name.startswith("mlx."):
            outer = None
            frame = sys._getframe(1)
            while frame is not None:
                filename = os.path.realpath(frame.f_code.co_filename)
                base = os.path.basename(filename)
                if (filename.startswith(TESTS + os.sep) and base.startswith("test_")
                        and base.endswith(".py")):
                    outer = os.path.relpath(filename, TESTS)
                frame = frame.f_back
            with open(LOG, "a") as h:
                h.write(json.dumps({"pid": os.getpid(), "module": name, "test": outer}) + "\\n")
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


def _test_modules():
    return sorted(TESTS.rglob("test_*.py"))


def _native_paths():
    """Every registered basename resolves to exactly one test module under tests/."""
    paths = {}
    for name in conftest.NATIVE_MODULES:
        matches = [p for p in _test_modules() if p.name == name]
        assert len(matches) == 1, (name, matches)
        paths[name] = matches[0]
    return paths


def _collect(tmp_path, sentinel, *extra):
    (tmp_path / "sitecustomize.py").write_text(sentinel)
    log = tmp_path / "mlx-attempts.jsonl"
    env = dict(os.environ, A39_SENTINEL_LOG=str(log), A39_TESTS_DIR=str(TESTS),
               PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join([str(tmp_path), str(ROOT / "src")]))
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         *extra, "tests"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    return result, log


def test_native_module_inventory_is_complete(tmp_path):
    # Static: every test module with a direct module-level MLX import is registered.
    direct = {p.name for p in _test_modules() if _module_level_mlx(p)}
    assert direct <= set(conftest.NATIVE_MODULES), sorted(direct - set(conftest.NATIVE_MODULES))
    paths = _native_paths()
    # Dynamic, both directions: with the opt-in, exactly the registered modules reach a
    # real MLX import during collection (direct or transitive), and nothing else does.
    result, log = _collect(tmp_path, SENTINEL_ATTRIBUTING, conftest.NATIVE_OPTION)
    assert log.exists(), result.stdout[-3000:] + result.stderr[-3000:]
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(r["test"] for r in records), [r for r in records if not r["test"]]
    blocked = {r["test"] for r in records}
    registered = {str(p.relative_to(TESTS)) for p in paths.values()}
    assert blocked == registered, {"unregistered": sorted(blocked - registered),
                                   "registered_but_cpu": sorted(registered - blocked)}
    # The opt-in run fails only on those modules: one collection error each.
    assert result.stdout.count("ERROR collecting ") == len(registered), result.stdout[-3000:]


def test_native_modules_carry_native_mark():
    for name, path in _native_paths().items():
        assert 'pytestmark = pytest.mark.native_mlx' in path.read_text(), name


def test_default_collection_imports_no_mlx(tmp_path):
    result, log = _collect(tmp_path, SENTINEL)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert not log.exists(), log.read_text()
    collected = result.stdout
    for name, path in _native_paths().items():
        assert str(path.relative_to(ROOT)) not in collected, name
    for nodeid in conftest.NATIVE_TESTS:
        assert nodeid + "\n" not in collected and nodeid + "[" not in collected, nodeid
    assert "deselected" in collected
    json.dumps(collected[-200:])
