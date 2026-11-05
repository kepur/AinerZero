"""Shared-lock and exit-code tests (S1 run entry).

The project-wide lock is the only thing that keeps two S1 runs off the same
machine at once; a busy lock must be a refusal with its own exit code (4), not a
generic failure.  The test holds a *temporary* lock file, never the real
``artifacts/locks/m0-worker.lock``.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero.cli import WorkerLockBusy
from ainerzero.v9.experiments.s1 import commands


def test_busy_lock_is_refused_with_exit_four(tmp_path, monkeypatch):
    lock_path = tmp_path / "locks" / "m0-worker.lock"
    lock_path.parent.mkdir(parents=True)
    monkeypatch.setattr(commands, "_lock_path", lambda: lock_path)
    output_root = tmp_path / "phase1"
    output_root.mkdir()
    with lock_path.open("a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report, code = commands.s1_phase1_command(
            SimpleNamespace(
                mode="freeze",
                output_root=output_root,
                limits_file=None,
                wall_budget_seconds=None,
                prereg=None,
                research_log=None,
            )
        )
    assert code == commands.EXIT_LOCK_BUSY == 4
    assert report["status"] == "refused"
    assert report["stage"] == "lock_busy"


def test_exit_code_map_is_total():
    assert commands._exit_code_for({"status": "completed"}) == 0
    assert commands._exit_code_for({"status": "refused"}) == 2
    assert commands._exit_code_for({"stage": "lock_busy", "status": "refused"}) == 4
    assert commands._exit_code_for({"status": "refused", "stage": "preregistration_not_approved"}) == 3
    assert commands._exit_code_for({"status": "failed"}) == 1


def test_lock_busy_is_a_runtime_error_subclass():
    assert issubclass(WorkerLockBusy, RuntimeError)
