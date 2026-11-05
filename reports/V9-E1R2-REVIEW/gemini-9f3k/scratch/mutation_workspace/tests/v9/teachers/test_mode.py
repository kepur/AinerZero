"""ModeGuard + WorkerLock + F5/F6/F7 handle/TTL/RSS tests (temp lock only)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from ainerzero.v9.teachers.fake import FakeTeacher
from ainerzero.v9.teachers.mode import (
    LockBusyError,
    ModeGuard,
    ModeViolationError,
    UnloadIncompleteError,
    WorkerLock,
    run_interleaving_test,
    run_mode_guard_tests,
    run_mode_process,
    verify_dual_process_lock_protocol,
)


@pytest.fixture(autouse=True)
def _reset_guard():
    ModeGuard.reset()
    ModeGuard.set_rss_probe(lambda: 1_000_000)
    yield
    ModeGuard.reset()
    ModeGuard.set_rss_probe(None)


def test_worker_lock_acquire_release(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "m0-worker.lease.json"
    lock = WorkerLock("teacher", "t1", lock_path=lock_path, lease_path=lease_path)
    assert lock.acquire() is True
    assert lease_path.exists()
    lease = json.loads(lease_path.read_text())
    assert lease["mode"] == "teacher"
    lock.release()
    assert lock.locked is False


def test_worker_lock_non_blocking_busy(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "m0-worker.lease.json"
    a = WorkerLock("teacher", "a", lock_path=lock_path, lease_path=lease_path)
    b = WorkerLock("train", "b", lock_path=lock_path, lease_path=lease_path)
    assert a.acquire() is True
    assert b.acquire() is False
    a.release()


def test_worker_lock_context_manager(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "m0-worker.lease.json"
    with WorkerLock("world", "ctx", lock_path=lock_path, lease_path=lease_path) as lock:
        assert lock.locked is True
        with pytest.raises(LockBusyError, match="skipped_lock_busy"):
            with WorkerLock("train", "waiter", lock_path=lock_path, lease_path=lease_path):
                pass
    assert lock.locked is False


def test_worker_lock_kernel_cleanup_on_fd_close(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "m0-worker.lease.json"
    lock = WorkerLock("teacher", "crash", lock_path=lock_path, lease_path=lease_path)
    assert lock.acquire()
    os.close(lock.fd)
    lock.fd = None
    lock.locked = False
    lock2 = WorkerLock("train", "after", lock_path=lock_path, lease_path=lease_path)
    assert lock2.acquire() is True
    lock2.release()


def test_mode_guard_train_teacher_world_rules():
    ModeGuard.set_mode("train")
    with pytest.raises(ModeViolationError, match="Train Mode"):
        ModeGuard.check_teacher_load("t1", "feature")

    ModeGuard.reset()
    ModeGuard.set_mode("teacher")
    ModeGuard.check_teacher_load("t1", "feature")
    with pytest.raises(ModeViolationError, match="second teacher"):
        ModeGuard.check_teacher_load("t2", "geometry")

    ModeGuard.reset()
    ModeGuard.set_mode("world")
    ModeGuard.check_teacher_load("da3", "geometry")
    with pytest.raises(ModeViolationError, match="second teacher"):
        ModeGuard.check_teacher_load("da3b", "geometry")

    ModeGuard.reset()
    ModeGuard.set_mode("world")
    with pytest.raises(ModeViolationError, match="only geometry"):
        ModeGuard.check_teacher_load("vjepa", "feature")


def test_mode_guard_switch_requires_unload():
    ModeGuard.set_mode("teacher")
    ModeGuard.check_teacher_load("t1", "feature")
    with pytest.raises(ModeViolationError, match="teacher still loaded"):
        ModeGuard.set_mode("train")
    ModeGuard.release_teacher()
    ModeGuard.set_mode("train")
    assert ModeGuard.get_mode() == "train"


def test_mode_guard_ttl():
    ModeGuard.set_mode("world", world_ttl_s=0.05)
    ModeGuard.check_teacher_load("da3", "geometry")
    time.sleep(0.08)
    ModeGuard.check_teacher_load("da3b", "geometry")


def test_mode_guard_no_mode():
    with pytest.raises(ModeViolationError, match="Mode not set"):
        ModeGuard.check_teacher_load("t1")
    with pytest.raises(ValueError):
        ModeGuard.set_mode("invalid")


def test_f5_handle_invalid_after_release_and_train_switch():
    ModeGuard.set_mode("teacher")
    t = FakeTeacher("vjepa2.1-vitl", "feature", dim=4)
    out = t.extract("c" * 64, [0, 1, 2])
    assert len(out) == 4 * 3 * 4
    ModeGuard.release_teacher()
    ModeGuard.set_mode("train")
    with pytest.raises(ModeViolationError):
        t.extract("c" * 64, [0, 1, 2])


def test_f6_ttl_invalidates_handle():
    ModeGuard.set_mode("world", world_ttl_s=0.05)
    t = FakeTeacher("da3-small", "geometry", dim=4)
    assert len(t.extract("c" * 64, [0])) == 16
    time.sleep(0.12)
    assert ModeGuard.teacher_loaded() is False
    with pytest.raises(ModeViolationError):
        t.extract("c" * 64, [0])


def test_f7_rss_probe_fail_closed_and_unload_incomplete():
    ModeGuard.set_mode("teacher")
    ModeGuard.check_teacher_load("t1", "feature")
    ModeGuard.release_teacher()
    ModeGuard.set_rss_probe(lambda: None)
    with pytest.raises(UnloadIncompleteError, match="unload_incomplete"):
        ModeGuard.set_mode("train")

    ModeGuard.reset()
    ModeGuard.set_rss_probe(lambda: 100)
    ModeGuard.set_mode("teacher")
    ModeGuard.check_teacher_load("t1", "feature")  # baseline 100
    ModeGuard.release_teacher()
    ModeGuard.set_rss_probe(lambda: 100 + 3 * 1024 * 1024 * 1024)  # +3GB
    with pytest.raises(UnloadIncompleteError, match="unload_incomplete"):
        ModeGuard.set_mode("world")


def test_run_mode_process_and_interleaving(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "lease.json"
    r = run_mode_process("teacher", 0.05, "p", lock_path, lease_path)
    assert r.acquired and r.released and r.violation is None
    results = run_interleaving_test("teacher", "train", lock_path, lease_path, hold_time=0.1)
    assert len(results) == 2
    assert sum(1 for x in results if x.acquired) <= 1


def test_verify_dual_process_lock_protocol(tmp_path):
    result = verify_dual_process_lock_protocol(tmp_path)
    assert result["all_mutually_exclusive"] is True
    assert result["sabotage_early_release_caught"] is True
    assert result["sabotage_late_acquire_caught"] is True
    assert result["ok"] is True


def test_run_mode_guard_tests_bundle():
    out = run_mode_guard_tests()
    assert out["all_passed"] is True


def test_deliberate_error_early_release_turns_red(tmp_path):
    lock_path = tmp_path / "m0-worker.lock"
    lease_path = tmp_path / "lease.json"
    a = WorkerLock("teacher", "early", lock_path=lock_path, lease_path=lease_path)
    assert a.acquire()
    a.release()
    b = WorkerLock("train", "intruder", lock_path=lock_path, lease_path=lease_path)
    assert b.acquire() is True
    assert a.acquire() is False
    b.release()


def test_deliberate_error_mode_violations_turn_red():
    ModeGuard.set_mode("train")
    with pytest.raises(ModeViolationError):
        ModeGuard.check_teacher_load("x", "feature")
    ModeGuard.reset()
    ModeGuard.set_mode("teacher")
    ModeGuard.check_teacher_load("a", "feature")
    with pytest.raises(ModeViolationError):
        ModeGuard.check_teacher_load("b", "feature")
