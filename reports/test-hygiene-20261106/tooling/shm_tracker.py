"""Per-test stat watch of the live S1 ledger side files and the shared lock (read-only)."""
import json, os
import pytest
# Repository root: SHM_TRACK_ROOT, else the pytest working directory.
ROOT = os.environ.get("SHM_TRACK_ROOT", os.getcwd())
WATCH = [os.path.join(ROOT, rel) for rel in (
    "artifacts/v9/s1/phase1/control.sqlite3-shm",
    "artifacts/v9/s1/phase1/control.sqlite3-wal",
    "artifacts/locks/m0-worker.lock")]
_hits = []
def _st():
    return {p: (lambda s: (s.st_mtime_ns, s.st_ctime_ns, s.st_size))(os.lstat(p)) for p in WATCH}
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    before = _st()
    yield
    after = _st()
    for p in WATCH:
        if before[p] != after[p]:
            _hits.append([item.nodeid, os.path.basename(p)])
def pytest_sessionfinish(session, exitstatus):
    json.dump(_hits, open(os.environ["SHM_TRACK_OUT"], "w"), indent=1)
