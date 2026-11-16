"""Unified S1 phase-1 completion protocol (S1-R8-DECISION F1).

Why this module exists
----------------------
r7 checked the frozen per-run deadline only inside ``_train`` before it
returned.  The final metadata IO, the completion receipt and -- above all --
the ledger's terminal ``completed`` commit (which can wait for a SQLite write
lock and fsync for an unbounded time) were outside that check, so an over-budget
run could still be returned and consumed as ``completed`` (P21 F1).

The protocol below owns one monotonic timer for the whole bounded run.  The
success path is:

1. ``check`` before the terminal commit (covers everything up to here);
2. run the commit *monitored*: a watchdog thread records whether the deadline
   was crossed while the commit was in flight (SQL wait / fsync / receipt IO);
3. ``check`` again after the commit (covers a commit that returned late, or a
   slow post-commit step).

If the deadline is crossed before the commit, the run is finished as ``failed``
and never becomes ``completed``.  If it is crossed *inside or after* the commit,
the terminal row may already say ``completed`` -- the ledger is append-only and
this adapter must never force a terminal row back (F1: no retroactive
``completed -> stopped``, no deleted failure, no refund).  In that case the
protocol writes an immutable ``completion_invalid.json`` marker next to the
artifacts, the report is returned as a failure, and every consumer
(``worker._bind_completed_run`` and the eval entry) refuses a run carrying that
marker or a self-declared invalid receipt.  The technical boundary is therefore:
*this adapter cannot revoke an already-committed SQLite row; it can and does
refuse to report it, and refuses to let any consumer accept it.*

No MLX, no model work, no new budget: this is bookkeeping.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA = "ainerzero.v9.s1.completion_protocol.v1"
INVALID_MARKER = "completion_invalid.json"

# Explicit, internal test seam.  It is never reachable from the CLI, the frozen
# document or an environment variable: tests monkeypatch this module attribute
# so a delay can be injected inside the commit window (F1 counterexample).
TEST_SEAM: Callable[[str, float], None] | None = None


class CompletionError(RuntimeError):
    """Base class for completion-protocol refusals."""


class CompletionDeadlineExceeded(CompletionError, TimeoutError):
    """The frozen per-run deadline was crossed during the completion protocol."""


class CompletionUncertain(CompletionError):
    """A terminal commit was attempted but its outcome cannot be trusted."""


def _seam(phase: str, elapsed: float) -> None:
    hook = TEST_SEAM
    if hook is not None:
        hook(phase, elapsed)


class CompletionProtocol:
    """One timer, one deadline, checked before / during / after the commit."""

    def __init__(
        self,
        *,
        deadline_seconds: float,
        started: float | None = None,
        clock: Callable[[], float] | None = None,
        watchdog_interval_seconds: float = 0.05,
    ) -> None:
        deadline = float(deadline_seconds)
        if not (deadline > 0):
            raise CompletionError(f"deadline_seconds must be positive, got {deadline!r}")
        self.deadline_seconds = deadline
        self._clock = clock or time.perf_counter
        self.started = self._clock() if started is None else float(started)
        self.watchdog_interval_seconds = max(0.001, float(watchdog_interval_seconds))
        self.events: list[dict[str, Any]] = []
        self.expired_in_flight = False
        self._in_flight_peak = 0.0

    # -- time ---------------------------------------------------------
    def elapsed(self) -> float:
        return self._clock() - self.started

    def remaining(self) -> float:
        return self.deadline_seconds - self.elapsed()

    # -- checks -------------------------------------------------------
    def check(self, phase: str) -> dict[str, Any]:
        """Record and enforce one deadline check; raise when already over."""
        elapsed = self.elapsed()
        event = {
            "phase": phase,
            "elapsed_seconds": elapsed,
            "remaining_seconds": self.deadline_seconds - elapsed,
            "deadline_seconds": self.deadline_seconds,
            "expired": elapsed > self.deadline_seconds,
        }
        self.events.append(event)
        _seam(phase, elapsed)
        if event["expired"]:
            raise CompletionDeadlineExceeded(
                f"phase {phase}: elapsed {elapsed:.6f}s exceeds the frozen deadline "
                f"{self.deadline_seconds:.6f}s"
            )
        return event

    def run_monitored(self, phase: str, action: Callable[[], Any]) -> Any:
        """Run ``action`` under the same timer; detect an in-flight overrun."""
        self.check(f"{phase}:before")
        stop = threading.Event()
        peak = [self.elapsed()]

        def _watch() -> None:
            while not stop.wait(self.watchdog_interval_seconds):
                current = self.elapsed()
                if current > peak[0]:
                    peak[0] = current
                if current > self.deadline_seconds:
                    self.expired_in_flight = True

        watcher = threading.Thread(target=_watch, name="s1-completion-watchdog", daemon=True)
        watcher.start()
        try:
            result = action()
        finally:
            current = self.elapsed()
            peak[0] = max(peak[0], current)
            stop.set()
            watcher.join(timeout=2.0)
            self._in_flight_peak = peak[0]
            if current > self.deadline_seconds:
                self.expired_in_flight = True
        self.check(f"{phase}:after")
        return result

    # -- evidence -----------------------------------------------------
    def record(self, *, phase: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "phase": phase,
            "clock": "time.perf_counter",
            "started_monotonic": self.started,
            "deadline_seconds": self.deadline_seconds,
            "elapsed_at_record_seconds": self.elapsed(),
            "remaining_at_record_seconds": self.remaining(),
            "expired_in_flight": self.expired_in_flight,
            "in_flight_peak_seconds": self._in_flight_peak,
            "events": list(self.events),
        }


def _exclusive_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write an immutable JSON file; never overwrite an existing marker."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path
    if candidate.exists():
        stem, suffix = path.stem, path.suffix
        index = 2
        while candidate.exists():
            candidate = path.with_name(f"{stem}-{index}{suffix}")
            index += 1
    with open(candidate, "x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=1)
        handle.write("\n")
    try:
        candidate.chmod(0o444)
    except OSError:
        pass
    return candidate


def write_invalid_marker(
    run_dir: Path,
    *,
    protocol: CompletionProtocol,
    phase: str,
    reason: str,
    ledger_state: str | None,
    detail: str,
) -> Path:
    payload = {
        "schema": SCHEMA,
        "status": "invalid",
        "phase": phase,
        "reason": reason,
        "detail": detail,
        "ledger_state_at_invalidation": ledger_state,
        "rolled_back": False,
        "rollback_note": "the terminal ledger row is append-only; this adapter never rewrites a "
        "committed terminal state. The marker invalidates the run for every consumer instead.",
        "protocol": protocol.record(phase=phase),
    }
    return _exclusive_json(Path(run_dir) / INVALID_MARKER, payload)


def invalid_markers(run_dir: Path) -> list[Path]:
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return []
    return sorted(run_dir.glob("completion_invalid*.json"))
