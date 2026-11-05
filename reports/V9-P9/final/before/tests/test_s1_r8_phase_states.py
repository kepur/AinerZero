"""r8 F2/F5: the phase ledger covers every legal lifecycle state, and a field
contract that never charges an invalid value as zero.

P21 F2: r7's ``ACTIVE_STATES`` omitted ``collecting``/``validating``/``stopping``,
which the product itself writes (prep data -> collecting, prep smoke/verify and
every eval -> validating, stop -> stopping), so a legitimate row was reported as
"unknown" and the reason blamed the timestamps.

P21 F5: r7 normalised the raw reservation with ``max(0.0, float(value) or 0.0)``.
``max(0.0, nan)`` is ``0.0`` in Python, so a NaN reservation was silently charged
as zero and the following ``isfinite`` guard could never fire; an extreme but
finite future timestamp was accepted and its interval charged as zero.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import worker


def _run(
    state: str,
    *,
    reserved: float = 10.0,
    created: float | str = 1_000.0,
    updated: float | str = 1_100.0,
    run_id: str = "run-fixture",
):
    return SimpleNamespace(
        run_id=run_id,
        state=state,
        reserved_active_seconds=reserved,
        created_at=created,
        updated_at=updated,
    )


# --- F2: every state the lifecycle can persist is accounted ----------------
@pytest.mark.parametrize(
    "state", ["created", "initializing", "collecting", "training", "validating", "pausing", "paused", "stopping"]
)
def test_every_non_terminal_lifecycle_state_is_accepted_and_charged_as_active(state):
    run = _run(state, reserved=5.0, created=1_000.0, updated=1_050.0)
    counted = worker.run_conservative_wall_seconds(run, instant=1_200.0)
    assert counted == pytest.approx(200.0), "max(reserved, now-created) for an open row"


@pytest.mark.parametrize("state", ["completed", "stopped", "failed"])
def test_every_terminal_state_is_charged_its_terminal_interval(state):
    run = _run(state, reserved=5.0, created=1_000.0, updated=1_100.0)
    counted = worker.run_conservative_wall_seconds(run, instant=9_999.0)
    assert counted == pytest.approx(100.0), "a terminal row is never charged its calendar age"


def test_the_product_written_prep_and_eval_states_are_not_reported_as_unknown():
    """The exact regression P21 F2 reported: collecting/validating/stopping."""
    runs = [
        _run("collecting", reserved=60.0, created=1_000.0, updated=1_060.0, run_id="prep-data"),
        _run("validating", reserved=20.0, created=1_100.0, updated=1_120.0, run_id="prep-verify"),
        _run("stopping", reserved=10.0, created=1_200.0, updated=1_210.0, run_id="stopped-eval"),
        _run("completed", reserved=450.0, created=1_300.0, updated=1_750.0, run_id="train"),
    ]
    total = worker.phase_total_wall_seconds(runs, instant=2_000.0)
    # Open rows are charged max(reserved, now-created) -- conservative, never the
    # smaller of the two -- and the terminal row keeps max(reserved, interval).
    assert total == pytest.approx(1_000.0 + 900.0 + 800.0 + 450.0)
    breakdown = worker.phase_ledger_breakdown(runs, instant=2_000.0)
    assert {row["state"] for row in breakdown["rows"]} == {
        "collecting",
        "validating",
        "stopping",
        "completed",
    }


def test_a_foreign_state_is_refused_as_a_state_error_not_a_timestamp_error():
    with pytest.raises(worker.LedgerStateInvalid) as excinfo:
        worker.run_conservative_wall_seconds(_run("quarantined"), instant=2_000.0)
    assert not isinstance(excinfo.value, worker.LedgerTimestampInvalid)
    assert "unknown state" in str(excinfo.value)


def test_reverse_timestamps_are_refused_as_a_timestamp_error_not_a_state_error():
    run = _run("completed", created=2_000.0, updated=1_000.0)
    with pytest.raises(worker.LedgerTimestampInvalid) as excinfo:
        worker.run_conservative_wall_seconds(run, instant=3_000.0)
    assert not isinstance(excinfo.value, worker.LedgerStateInvalid)
    assert "reverse" in str(excinfo.value)


# --- F5: raw reservation validated before any max -------------------------
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_a_non_finite_or_negative_reservation_is_refused_not_charged_as_zero(bad):
    """``max(0.0, nan) == 0.0`` is exactly the silent-zero bug."""
    run = _run("training", reserved=bad, created=1_000.0, updated=1_100.0)
    with pytest.raises(worker.LedgerStateInvalid) as excinfo:
        worker.run_conservative_wall_seconds(run, instant=1_200.0)
    assert "reserved_active_seconds" in str(excinfo.value)


@pytest.mark.parametrize("bad", [None, "10.0", True])
def test_a_missing_or_non_numeric_reservation_is_refused(bad):
    run = _run("training", reserved=bad, created=1_000.0, updated=1_100.0)
    with pytest.raises(worker.LedgerStateInvalid):
        worker.run_conservative_wall_seconds(run, instant=1_200.0)


def test_a_run_without_the_reserved_field_is_refused():
    run = SimpleNamespace(
        run_id="legacy", state="completed", created_at=1_000.0, updated_at=1_100.0
    )
    with pytest.raises(worker.LedgerStateInvalid):
        worker.run_conservative_wall_seconds(run, instant=1_200.0)


def test_a_zero_reservation_is_still_a_legal_value():
    run = _run("training", reserved=0.0, created=1_000.0, updated=1_000.0)
    assert worker.run_conservative_wall_seconds(run, instant=1_000.0) == pytest.approx(0.0)


# --- F5: timestamps must be representable, finite and ordered -------------
@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), 1e308, -1e308, None, "not-a-timestamp"],
)
def test_an_unusable_timestamp_is_refused(bad):
    run = _run("completed", created=bad, updated=1_100.0)
    with pytest.raises(worker.LedgerTimestampInvalid):
        worker.run_conservative_wall_seconds(run, instant=1_200.0)


def test_a_non_finite_accounting_instant_is_refused():
    run = _run("training", created=1_000.0, updated=1_100.0)
    with pytest.raises(worker.LedgerTimestampInvalid):
        worker.run_conservative_wall_seconds(run, instant=float("nan"))


def test_a_legitimate_future_clock_high_water_is_not_refused():
    """The RunStore keeps a clock high-water; a future ``created_at`` is legal.

    A row created "in the future" relative to ``now`` has a negative age, which
    is a real zero -- refusing it would contradict the store's own semantics.
    """
    run = _run("training", reserved=7.0, created=2_000.0, updated=2_000.0)
    assert worker.run_conservative_wall_seconds(run, instant=1_900.0) == pytest.approx(7.0)


def test_iso_timestamps_are_parsed_like_the_ledger_writes_them():
    run = _run(
        "completed",
        reserved=5.0,
        created="2026-10-22T00:00:00+00:00",
        updated="2026-10-22T00:01:40+00:00",
    )
    assert worker.run_conservative_wall_seconds(run) == pytest.approx(100.0)
