"""S1 r7: the shared m0-worker lock belongs to the host anchor.

S1-R7-DECISION item 5: with the real shared lock, two source checkouts must not
each hold "their own" lock.  These tests use real processes and real ``flock``;
no model, no GPU, no MLX.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ainerzero.cli import worker_lock
from ainerzero.v9.experiments.s1 import spec

from s1_testkit import checkout_anchor, make_source_checkout

_TRY_LOCK = """
import sys
from pathlib import Path
from ainerzero.cli import WorkerLockBusy, worker_lock
from ainerzero.v9.experiments.s1 import commands, spec

if len(sys.argv) > 1 and sys.argv[1]:
    spec.REGISTERED_HOST_ROOT = Path(sys.argv[1])

try:
    with worker_lock(commands._lock_path()):
        print("acquired")
except WorkerLockBusy:
    print("busy")
    sys.exit(3)
"""


def _run_from_checkout(checkout: Path, host_root: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout / "src")
    args = [sys.executable, "-c", _TRY_LOCK]
    if host_root is not None:
        args.append(str(host_root))
    return subprocess.run(
        args,
        cwd=str(checkout),
        env=env,
        capture_output=True,
        text=True,
    )


def test_every_checkout_names_the_same_lock_file(tmp_path):
    first = checkout_anchor(make_source_checkout(tmp_path / "a"))
    second = checkout_anchor(make_source_checkout(tmp_path / "b"))
    assert first["lock"] == second["lock"]
    assert first["lock"] == spec.host_anchor_state()["lock"]
    assert Path(first["lock"]).parent.parent == Path(first["root"]) / "artifacts"
    assert str(tmp_path / "a") not in first["lock"]


def test_two_checkouts_cannot_hold_the_lock_at_the_same_time(tmp_path, monkeypatch):
    first = make_source_checkout(tmp_path / "a")
    second = make_source_checkout(tmp_path / "b")

    staged_host = tmp_path / "host"
    staged_phase1 = staged_host / "artifacts" / "v9" / "s1" / "phase1"
    staged_phase1.mkdir(parents=True, exist_ok=True)
    staged_locks = staged_host / "artifacts" / "locks"
    staged_locks.mkdir(parents=True, exist_ok=True)
    staged_log = staged_host / "RESEARCH_LOG.md"
    staged_log.write_text("# log\n", encoding="utf-8")

    monkeypatch.setattr(spec, "REGISTERED_HOST_ROOT", staged_host)

    with worker_lock(Path(spec.host_anchor()["lock"])):
        blocked = _run_from_checkout(second, host_root=staged_host)
        assert blocked.returncode == 3
        assert blocked.stdout.strip() == "busy"

    # Released: the *other* checkout can now take the same anchored lock.
    acquired = _run_from_checkout(first, host_root=staged_host)
    assert acquired.returncode == 0
    assert acquired.stdout.strip() == "acquired"
