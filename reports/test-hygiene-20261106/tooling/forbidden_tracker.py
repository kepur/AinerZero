"""Audit plugin: first test after which mlx/torch/... appear in sys.modules."""
import json, os, sys
import pytest
FORBIDDEN = {"mlx", "torch", "onnxruntime", "tensorflow", "jax"}
_seen = {}
def _present():
    return {n.split(".")[0] for n in list(sys.modules)} & FORBIDDEN
def pytest_collection_finish(session):
    for m in _present():
        _seen.setdefault(m, "<collection>")
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    before = _present()
    yield
    for m in _present() - before:
        _seen.setdefault(m, item.nodeid)
def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["FORBIDDEN_TRACK_OUT"], "w") as h:
        json.dump(_seen, h, indent=1)
