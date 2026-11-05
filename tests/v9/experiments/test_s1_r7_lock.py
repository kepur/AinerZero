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
from ainerzero.cli import WorkerLockBusy, worker_lock
from ainerzero.v9.experiments.s1 import commands

try:
    with worker_lock(commands._lock_path()):
        print("acquired")
except WorkerLockBusy:
    print("busy")
    sys.exit(3)
"""


def _run_from_checkout(checkout: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout / "src")
    return subprocess.run(
        [sys.executable, "-c", _TRY_LOCK],
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


def test_two_checkouts_cannot_hold_the_lock_at_the_same_time(tmp_path):
    first = make_source_checkout(tmp_path / "a")
    second = make_source_checkout(tmp_path / "b")

    with worker_lock(Path(spec.host_anchor()["lock"])):
        blocked = _run_from_checkout(second)
        assert blocked.returncode == 3
        assert blocked.stdout.strip() == "busy"

    # Released: the *other* checkout can now take the same anchored lock.
    acquired = _run_from_checkout(first)
    assert acquired.returncode == 0
    assert acquired.stdout.strip() == "acquired"
