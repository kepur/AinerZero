"""Audit plugin: block and attribute every run-time MLX import (diagnostic only)."""
import json, os, sys, traceback
import pytest
_ROOT = os.path.realpath(os.getcwd()) + os.sep  # run pytest from the repository root
_current = {"id": "<collection>"}
_hits = {}
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "mlx" or name.startswith("mlx."):
            stack = [f"{os.path.relpath(f.filename)}:{f.lineno}:{f.name}" for f in traceback.extract_stack()[:-1]
                     if f.filename.startswith(_ROOT) and "/_pytest/" not in f.filename and "pluggy" not in f.filename]
            _hits.setdefault(_current["id"], stack[-6:])
            raise ImportError("runtime MLX import blocked for audit: " + name)
sys.meta_path.insert(0, _Block())
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _current["id"] = item.nodeid
    yield
    _current["id"] = "<between>"
def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["MLX_BLOCK_OUT"], "w") as h:
        json.dump(_hits, h, indent=1)
