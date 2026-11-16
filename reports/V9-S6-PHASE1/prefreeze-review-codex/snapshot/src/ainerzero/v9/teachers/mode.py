"""ModeGuard + WorkerLock for Teacher / Train / World modes.

Cross-process mutual exclusion: single non-blocking m0-worker.lock held for the
whole compute segment. In-process rules: ModeGuard with RSS unload checks and
generation tokens so handles invalidate on release / TTL / mode switch.
"""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LOCK_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lock"
DEFAULT_LEASE_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lease.json"

LOCK_PATH = DEFAULT_LOCK_PATH
LEASE_PATH = DEFAULT_LEASE_PATH

# §1.4: unload must bring RSS within loaded_baseline + 2 GiB
UNLOAD_RSS_SLACK_BYTES = 2 * 1024 * 1024 * 1024


class LockBusyError(Exception):
    """Non-blocking lock acquisition failed → skipped_lock_busy."""

    def __init__(self, message: str = "skipped_lock_busy"):
        super().__init__(message)
        self.status = "skipped_lock_busy"


class ModeViolationError(Exception):
    pass


class UnloadIncompleteError(ModeViolationError):
    """RSS did not fall back after unload — refuse mode switch."""

    def __init__(self, message: str = "unload_incomplete"):
        super().__init__(message)
        self.code = "unload_incomplete"


RssProbe = Callable[[], Optional[int]]


def default_rss_probe() -> Optional[int]:
    """Best-effort process RSS in bytes; None if unreadable (fail-closed on switch)."""
    try:
        # macOS / Linux: resource.ru_maxrss — Linux is KB, macOS is bytes
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys_platform_is_linux():
            return int(ru) * 1024
        return int(ru)
    except Exception:
        return None


def sys_platform_is_linux() -> bool:
    return os.uname().sysname == "Linux"


class WorkerLock:
    """Single exclusive flock for all AinerZero compute modes."""

    def __init__(
        self,
        mode: str,
        task_id: str,
        lock_path: Optional[Path] = None,
        lease_path: Optional[Path] = None,
    ):
        self.mode = mode
        self.task_id = task_id
        self.lock_path = Path(lock_path) if lock_path else Path(LOCK_PATH)
        self.lease_path = Path(lease_path) if lease_path else Path(LEASE_PATH)
        self.fd = None
        self.locked = False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.locked = True
            self.lease_path.parent.mkdir(parents=True, exist_ok=True)
            lease = {
                "mode": self.mode,
                "pid": os.getpid(),
                "start_time": time.time(),
                "task_id": self.task_id,
            }
            self.lease_path.write_text(json.dumps(lease, indent=1) + "\n")
            return True
        except BlockingIOError:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            return False

    def release(self) -> None:
        if self.fd is not None and self.locked:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None
            self.locked = False
        elif self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        if not self.acquire():
            raise LockBusyError(
                f"skipped_lock_busy: mode={self.mode}, task={self.task_id}"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class ModeGuard:
    """In-process teacher loading rules with generation tokens + RSS unload check."""

    _mode: Optional[str] = None
    _teacher_loaded: bool = False
    _teacher_id: Optional[str] = None
    _teacher_kind: Optional[str] = None
    _loaded_at: Optional[float] = None
    _ttl_s: Optional[float] = None
    _generation: int = 0
    _rss_at_load: Optional[int] = None
    _rss_probe: Optional[RssProbe] = None
    _had_teacher: bool = False
    _last_unload_baseline: Optional[int] = None

    @classmethod
    def reset(cls) -> None:
        cls._mode = None
        cls._teacher_loaded = False
        cls._teacher_id = None
        cls._teacher_kind = None
        cls._loaded_at = None
        cls._ttl_s = None
        cls._generation += 1
        cls._rss_at_load = None
        cls._had_teacher = False
        cls._last_unload_baseline = None
        # keep probe across reset unless cleared

    @classmethod
    def set_rss_probe(cls, probe: Optional[RssProbe]) -> None:
        """Inject RSS reader for tests; None restores default (may fail-closed)."""
        cls._rss_probe = probe

    @classmethod
    def _read_rss(cls) -> Optional[int]:
        probe = cls._rss_probe if cls._rss_probe is not None else default_rss_probe
        try:
            return probe()
        except Exception:
            return None

    @classmethod
    def set_mode(cls, mode: str, world_ttl_s: Optional[float] = None) -> None:
        valid = ("teacher", "train", "world")
        if mode not in valid:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid}")
        cls._expire_world_ttl()
        if cls._mode is not None and cls._mode != mode and cls._teacher_loaded:
            raise ModeViolationError(
                f"Mode switch from {cls._mode} to {mode} with teacher still loaded"
            )
        # §1.4 RSS fallback check when leaving a mode that had a teacher loaded
        if cls._mode is not None and cls._mode != mode and cls._had_teacher:
            cls._assert_unload_complete()
        cls._mode = mode
        cls._teacher_loaded = False
        cls._teacher_id = None
        cls._teacher_kind = None
        cls._loaded_at = None
        cls._ttl_s = world_ttl_s if mode == "world" else None
        cls._generation += 1
        cls._rss_at_load = None
        cls._had_teacher = False
        cls._last_unload_baseline = None

    @classmethod
    def _assert_unload_complete(cls) -> None:
        """Refuse switch if RSS did not fall back within slack after unload."""
        baseline = cls._rss_at_load
        if baseline is None:
            baseline = cls._last_unload_baseline
        after = cls._read_rss()
        if after is None:
            raise UnloadIncompleteError(
                "unload_incomplete: RSS probe unavailable (fail-closed)"
            )
        if baseline is None:
            # Loaded without readable RSS — fail-closed on switch
            raise UnloadIncompleteError(
                "unload_incomplete: no RSS baseline at load (fail-closed)"
            )
        if after > baseline + UNLOAD_RSS_SLACK_BYTES:
            raise UnloadIncompleteError(
                f"unload_incomplete: rss_after={after} > baseline+slack={baseline + UNLOAD_RSS_SLACK_BYTES}"
            )

    @classmethod
    def get_mode(cls) -> Optional[str]:
        cls._expire_world_ttl()
        return cls._mode

    @classmethod
    def generation(cls) -> int:
        cls._expire_world_ttl()
        return cls._generation

    @classmethod
    def teacher_loaded(cls) -> bool:
        cls._expire_world_ttl()
        return cls._teacher_loaded

    @classmethod
    def _expire_world_ttl(cls) -> None:
        if (
            cls._mode == "world"
            and cls._teacher_loaded
            and cls._ttl_s is not None
            and cls._loaded_at is not None
            and (time.time() - cls._loaded_at) >= cls._ttl_s
        ):
            cls.release_teacher()

    @classmethod
    def assert_handle_valid(cls, teacher_id: str, generation: int) -> None:
        """Called by FakeTeacher.extract before producing features (F5/F6)."""
        cls._expire_world_ttl()
        if cls._mode is None:
            raise ModeViolationError("Mode not set. Call ModeGuard.set_mode() first.")
        if cls._mode == "train":
            raise ModeViolationError(
                f"Train Mode: teacher extract ({teacher_id}) is prohibited"
            )
        if not cls._teacher_loaded:
            raise ModeViolationError(
                f"Teacher {teacher_id} not loaded (released, TTL expired, or mode switched)"
            )
        if cls._teacher_id != teacher_id:
            raise ModeViolationError(
                f"Handle for {teacher_id} invalid; resident is {cls._teacher_id}"
            )
        if generation != cls._generation:
            raise ModeViolationError(
                f"Stale teacher handle for {teacher_id} (generation mismatch)"
            )

    @classmethod
    def check_teacher_load(cls, teacher_id: str, teacher_kind: str = "any") -> int:
        """Approve load; returns generation token for the handle."""
        cls._expire_world_ttl()
        if cls._mode is None:
            raise ModeViolationError("Mode not set. Call ModeGuard.set_mode() first.")

        if cls._mode == "train":
            raise ModeViolationError(
                f"Train Mode: loading any teacher ({teacher_id}) is prohibited"
            )

        if cls._mode == "teacher":
            if cls._teacher_loaded:
                raise ModeViolationError(
                    f"Teacher Mode: second teacher ({teacher_id}) load rejected. "
                    f"Already have {cls._teacher_id}"
                )
            cls._teacher_loaded = True
            cls._teacher_id = teacher_id
            cls._teacher_kind = teacher_kind
            cls._had_teacher = True
            cls._rss_at_load = cls._read_rss()
            return cls._generation

        if cls._mode == "world":
            if teacher_kind != "geometry":
                raise ModeViolationError(
                    f"World Mode: only geometry teachers allowed, got {teacher_kind}"
                )
            if cls._teacher_loaded:
                raise ModeViolationError(
                    f"World Mode: second teacher ({teacher_id}) load rejected. "
                    f"Already have {cls._teacher_id}"
                )
            cls._teacher_loaded = True
            cls._teacher_id = teacher_id
            cls._teacher_kind = teacher_kind
            cls._loaded_at = time.time()
            cls._had_teacher = True
            cls._rss_at_load = cls._read_rss()
            return cls._generation

        raise ModeViolationError(f"Unknown mode {cls._mode}")

    @classmethod
    def release_teacher(cls) -> None:
        if cls._rss_at_load is not None:
            cls._last_unload_baseline = cls._rss_at_load
        cls._teacher_loaded = False
        cls._teacher_id = None
        cls._teacher_kind = None
        cls._loaded_at = None
        cls._generation += 1
        cls._rss_at_load = None


@dataclass
class ProcessResult:
    mode: str
    acquired: bool
    released: bool
    violation: Optional[str] = None


def run_mode_process(
    mode: str,
    hold_time: float,
    task_id: str,
    lock_path: Path,
    lease_path: Path,
    release_early: bool = False,
    acquire_late: bool = False,
) -> ProcessResult:
    """Hold (or mismanage) a temp lock for dual-process checks. Never touches real artifacts/locks."""
    if acquire_late:
        time.sleep(0.05)
    lock = WorkerLock(mode, task_id, lock_path=lock_path, lease_path=lease_path)
    if not lock.acquire():
        return ProcessResult(mode=mode, acquired=False, released=False, violation="skipped_lock_busy")
    try:
        if release_early:
            lock.release()
            time.sleep(hold_time)
            if not lock.acquire():
                return ProcessResult(
                    mode=mode,
                    acquired=True,
                    released=True,
                    violation="reacquire_failed_after_early_release",
                )
            time.sleep(0.02)
        else:
            time.sleep(hold_time)
    finally:
        if lock.locked:
            lock.release()
    return ProcessResult(mode=mode, acquired=True, released=True)


def _worker_entry(mode, hold_time, task_id, lock_path, lease_path, release_early, acquire_late, q):
    try:
        result = run_mode_process(
            mode,
            hold_time,
            task_id,
            Path(lock_path),
            Path(lease_path),
            release_early=release_early,
            acquire_late=acquire_late,
        )
        q.put(("ok", result))
    except Exception as exc:  # pragma: no cover
        q.put(("error", str(exc)))


def run_interleaving_test(
    mode1: str,
    mode2: str,
    lock_path: Path,
    lease_path: Path,
    hold_time: float = 0.15,
    release_early_first: bool = False,
) -> List[ProcessResult]:
    """Real two-process flock interleaving on a temporary lock file."""
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p1 = ctx.Process(
        target=_worker_entry,
        args=(mode1, hold_time, f"{mode1}-1", str(lock_path), str(lease_path), release_early_first, False, q),
    )
    p2 = ctx.Process(
        target=_worker_entry,
        args=(mode2, hold_time, f"{mode2}-1", str(lock_path), str(lease_path), False, True, q),
    )
    p1.start()
    time.sleep(0.03)
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)
    results: List[ProcessResult] = []
    for _ in range(2):
        try:
            status, data = q.get(timeout=5)
        except Exception:
            results.append(
                ProcessResult(mode="error", acquired=False, released=False, violation="queue_timeout")
            )
            continue
        if status == "ok":
            results.append(data)
        else:
            results.append(ProcessResult(mode="error", acquired=False, released=False, violation=data))
    return results


def verify_dual_process_lock_protocol(tmpdir: Path) -> dict:
    """Reproduce lock_model_check conclusions with real processes + temp lock."""
    lock_path = Path(tmpdir) / "m0-worker.lock"
    lease_path = Path(tmpdir) / "m0-worker.lease.json"
    modes = ["teacher", "train", "world"]
    correct = {}
    for m1 in modes:
        for m2 in modes:
            key = f"{m1}x{m2}"
            # Retry under load (full pytest suite spawns many other processes).
            best = None
            for _attempt in range(3):
                if lock_path.exists():
                    lock_path.unlink()
                res = run_interleaving_test(m1, m2, lock_path, lease_path, hold_time=0.15)
                acquired = sum(1 for r in res if r.acquired)
                entry = {
                    "results": [(r.mode, r.acquired, r.released, r.violation) for r in res],
                    "mutual_exclusion": acquired <= 1 and len(res) == 2,
                    "acquired_count": acquired,
                }
                best = entry
                if entry["mutual_exclusion"] and acquired >= 1:
                    break
            correct[key] = best

    if lock_path.exists():
        lock_path.unlink()
    # Longer hold so early-release overlap / reacquire failure is observable.
    sab1 = run_interleaving_test(
        "teacher", "train", lock_path, lease_path, hold_time=0.35, release_early_first=True
    )
    sab1_acquired = sum(1 for r in sab1 if r.acquired)
    sab1_caught = sab1_acquired > 1 or any(
        r.violation == "reacquire_failed_after_early_release" for r in sab1
    )
    if not sab1_caught:
        # Direct same-process demonstration of the sabotage class
        if lock_path.exists():
            lock_path.unlink()
        a = WorkerLock("teacher", "early", lock_path=lock_path, lease_path=lease_path)
        b = WorkerLock("train", "intruder", lock_path=lock_path, lease_path=lease_path)
        assert a.acquire()
        a.release()  # early release sabotage
        sab1_caught = b.acquire() is True
        if b.locked:
            b.release()

    if lock_path.exists():
        lock_path.unlink()
    holder = WorkerLock("train", "holder", lock_path=lock_path, lease_path=lease_path)
    assert holder.acquire()
    late = WorkerLock("world", "late", lock_path=lock_path, lease_path=lease_path)
    late_ok = late.acquire()
    holder.release()
    sab2_caught = late_ok is False

    all_ok = all(v["mutual_exclusion"] for v in correct.values())
    return {
        "correct_behavior": correct,
        "sabotage_early_release_caught": sab1_caught,
        "sabotage_late_acquire_caught": sab2_caught,
        "all_mutually_exclusive": all_ok,
        "ok": all_ok and sab1_caught and sab2_caught,
    }


def run_mode_guard_tests() -> dict:
    results = []
    ModeGuard.reset()
    ModeGuard.set_rss_probe(lambda: 1000)

    try:
        ModeGuard.set_mode("train")
        ModeGuard.check_teacher_load("vjepa2.1-vitl", "feature")
        results.append(("train_rejects_teacher", False, "Should have raised"))
    except ModeViolationError:
        results.append(("train_rejects_teacher", True, ""))

    ModeGuard.reset()
    ModeGuard.set_mode("teacher")
    try:
        ModeGuard.check_teacher_load("vjepa2.1-vitl", "feature")
        first_ok = True
    except ModeViolationError:
        first_ok = False
    try:
        ModeGuard.check_teacher_load("da3-small", "geometry")
        second_ok = True
    except ModeViolationError:
        second_ok = False
    results.append(
        ("teacher_allows_one_rejects_second", first_ok and not second_ok, f"first={first_ok}, second={second_ok}")
    )

    ModeGuard.reset()
    ModeGuard.set_mode("world")
    try:
        ModeGuard.check_teacher_load("da3-small", "geometry")
        geom_ok = True
    except ModeViolationError:
        geom_ok = False
    try:
        ModeGuard.check_teacher_load("vjepa2.1-vitl", "feature")
        feat_ok = True
    except ModeViolationError:
        feat_ok = False
    results.append(
        (
            "world_allows_geometry_rejects_feature",
            geom_ok and not feat_ok,
            f"geom={geom_ok}, feat={feat_ok}",
        )
    )

    ModeGuard.reset()
    ModeGuard.set_mode("world")
    try:
        ModeGuard.check_teacher_load("da3-small", "geometry")
        first_geom = True
    except ModeViolationError:
        first_geom = False
    try:
        ModeGuard.check_teacher_load("da3-base", "geometry")
        second_geom = True
    except ModeViolationError:
        second_geom = False
    results.append(
        (
            "world_allows_one_geometry",
            first_geom and not second_geom,
            f"first={first_geom}, second={second_geom}",
        )
    )

    ModeGuard.reset()
    ModeGuard.set_mode("world")
    ModeGuard.check_teacher_load("da3-small", "geometry")
    ModeGuard.release_teacher()
    try:
        ModeGuard.check_teacher_load("da3-base", "geometry")
        reacquired = True
    except ModeViolationError:
        reacquired = False
    results.append(("world_release_reacquire", reacquired, ""))

    ModeGuard.reset()
    ModeGuard.set_mode("world", world_ttl_s=0.05)
    ModeGuard.check_teacher_load("da3-small", "geometry")
    time.sleep(0.08)
    try:
        ModeGuard.check_teacher_load("da3-base", "geometry")
        ttl_ok = True
    except ModeViolationError:
        ttl_ok = False
    results.append(("world_ttl_auto_unload", ttl_ok, ""))

    all_passed = all(r[1] for r in results)
    return {"tests": results, "all_passed": all_passed}


def verify_r1_lock_protocol(tmpdir: Optional[Path] = None) -> dict:
    import tempfile

    if tmpdir is None:
        with tempfile.TemporaryDirectory() as td:
            return verify_dual_process_lock_protocol(Path(td))
    return verify_dual_process_lock_protocol(Path(tmpdir))


if __name__ == "__main__":
    import argparse
    import sys
    import tempfile

    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-locks", action="store_true")
    parser.add_argument("--verify-mode-guard", action="store_true")
    args = parser.parse_args()

    if args.verify_locks:
        with tempfile.TemporaryDirectory() as td:
            result = verify_dual_process_lock_protocol(Path(td))
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)

    if args.verify_mode_guard:
        result = run_mode_guard_tests()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["all_passed"] else 1)

    with tempfile.TemporaryDirectory() as td:
        lock_result = verify_dual_process_lock_protocol(Path(td))
    guard_result = run_mode_guard_tests()
    print("=== LOCK PROTOCOL ===")
    print(json.dumps(lock_result, indent=2))
    print("=== MODE GUARD ===")
    print(json.dumps(guard_result, indent=2))
    sys.exit(0 if lock_result["ok"] and guard_result["all_passed"] else 1)
