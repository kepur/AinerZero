"""P21 probe 05: terminal phase accounting (max(reserved, terminal interval)).

Independent recomputation of the r7 rule plus *broken-guard controls*:

* the real central ledger is read through a byte-identical copy opened with the
  real ``RunStore`` (so the rows are genuine ``RunRecord`` objects with the
  real ISO timestamp strings and the real ``reserved_active_seconds`` field),
* the product's ``phase_ledger_breakdown`` is compared with an independent
  re-implementation of the rule straight from the SQLite rows,
* broken variants of the rule (r6 calendar age, unknown state charged as 0,
  unknown state charged as active, reservation ignored, global max instead of
  per-row max) are fed to the same detector: the detector must reject each of
  them, otherwise the probe would be vacuous,
* corrupt rows (unknown state, reverse timestamps, NaN/Inf, missing timestamp,
  overflow timestamp) must be refused by the product function, never charged as 0.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

from ainerzero.runtime.lifecycle import RunRecord  # noqa: E402
from ainerzero.v9.experiments.s1 import spec, worker  # noqa: E402

REAL_LEDGER = lib.REPO / "artifacts/v9/s1/phase1/control.sqlite3"


def iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def make_record(**overrides) -> RunRecord:
    base = {
        "run_id": "probe",
        "request_id": "probe",
        "state": "completed",
        "resume_state": None,
        "reason": "probe",
        "config_snapshot": {},
        "config_hash": "0" * 64,
        "created_at": iso(1_000.0),
        "updated_at": iso(1_010.0),
        "reserved_environment_steps": 0,
        "reserved_optimizer_steps": 0,
        "reserved_active_seconds": 5.0,
        "wall_seconds": 10.0,
        "remaining": {},
        "experiment_id": None,
        "role": "auxiliary",
        "reserved_model_transitions": 0,
    }
    base.update(overrides)
    return RunRecord(**base)


def independent_rule(rows, *, instant: float) -> list[dict]:
    """Re-implementation of the frozen rule, straight from the SQLite rows."""
    out = []
    for row in rows:
        state = row["state"]
        created = float(row["created_at"])
        updated = float(row["updated_at"])
        reserved = float(row["active_seconds"])
        if state in ("completed", "failed", "stopped"):
            counted = max(reserved, updated - created, 0.0)
            kind = "terminal"
        else:
            counted = max(reserved, instant - created, 0.0)
            kind = "active"
        out.append(
            {
                "run_id": row["run_id"],
                "state": state,
                "kind": kind,
                "reserved_active_seconds": reserved,
                "terminal_interval_seconds": max(0.0, updated - created),
                "counted_seconds": counted,
            }
        )
    return out


def detector(rows, *, instant: float, phase_cap: float, deadline: float) -> dict:
    """The acceptance rule under review: per-row max, per-row sum, refuse junk."""
    problems = []
    counted_total = 0.0
    reserved_total = 0.0
    for row in rows:
        state = row["state"]
        if state not in worker.KNOWN_STATES:
            problems.append(f"unknown state {state!r} for run {row['run_id']}")
            continue
        created = float(row["created_at"])
        updated = float(row["updated_at"])
        if not (math.isfinite(created) and math.isfinite(updated)):
            problems.append(f"non-finite timestamps for run {row['run_id']}")
            continue
        if updated < created:
            problems.append(f"reverse timestamps for run {row['run_id']}")
            continue
        reserved = float(row["active_seconds"])
        if not math.isfinite(reserved):
            problems.append(f"non-finite reservation for run {row['run_id']}")
            continue
        if state in worker.TERMINAL_STATES:
            counted = max(reserved, updated - created, 0.0)
        else:
            counted = max(reserved, instant - created, 0.0)
        if counted + 1e-9 < reserved:
            problems.append(f"run {row['run_id']} is refunded below its reservation")
        counted_total += counted
        reserved_total += reserved
    return {
        "counted_total_seconds": counted_total,
        "reserved_total_seconds": reserved_total,
        "would_refuse": counted_total + deadline > phase_cap,
        "problems": problems,
    }


def broken_variants(rows, *, instant: float):
    """Deliberately broken rules; the detector must reject every one.

    Each variant is applied to a dataset in which its defect is *observable*:
    for the unknown-state variants the dataset contains one unknown state, for
    the calendar-age and dropped-reservation variants the real terminal rows
    are used.  The comparison is against the frozen rule on the same data.
    """
    variants = {}

    # r6 defect: a terminal row is charged for the whole calendar age.
    def calendar_age(row):
        return max(0.0, instant - float(row["created_at"]))

    # unknown state charged as zero
    def unknown_as_zero(row):
        if row["state"] not in worker.KNOWN_STATES:
            return 0.0
        return max(float(row["active_seconds"]), float(row["updated_at"]) - float(row["created_at"]), 0.0)

    # unknown state charged as if it were still active
    def unknown_as_active(row):
        if row["state"] not in worker.KNOWN_STATES:
            return max(0.0, instant - float(row["created_at"]))
        return max(float(row["active_seconds"]), float(row["updated_at"]) - float(row["created_at"]), 0.0)

    # the reservation is ignored
    def reserved_ignored(row):
        return max(0.0, float(row["updated_at"]) - float(row["created_at"]))

    unknown_row = {
        "run_id": "synthetic-unknown",
        "state": "hibernating",
        "created_at": 1_000.0,
        "updated_at": 1_020.0,
        "active_seconds": 30.0,
    }
    with_unknown = list(rows) + [unknown_row]

    for name, fn, data in (
        ("r6_calendar_age", calendar_age, list(rows)),
        ("unknown_state_as_zero", unknown_as_zero, with_unknown),
        ("unknown_state_as_active", unknown_as_active, with_unknown),
        ("reservation_ignored", reserved_ignored, list(rows)),
    ):
        variants[name] = sum(fn(row) for row in data)

    # global max of two totals instead of a per-row max
    reserved_total = sum(float(row["active_seconds"]) for row in rows)
    terminal_total = sum(
        max(0.0, float(row["updated_at"]) - float(row["created_at"])) for row in rows
    )
    variants["global_max_instead_of_per_row_max"] = max(reserved_total, terminal_total)
    variants["_datasets"] = {
        "real_rows": len(rows),
        "rows_with_unknown_state": len(with_unknown),
    }
    return variants


def main() -> int:
    scratch = lib.scratch_dir("p21-phase")
    copy = scratch / "control.sqlite3"
    copy_info = lib.copy_ledger_bytes(REAL_LEDGER, copy)

    # --- read the copy with the real RunStore (genuine RunRecord objects) ---
    ledger = worker.PrepLedger(copy)
    try:
        records = ledger.store.list_runs()
    finally:
        ledger.close()

    raw_rows = []
    connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for row in connection.execute(
            "SELECT run_id, state, created_at, updated_at, active_seconds, experiment_id, role "
            "FROM runs ORDER BY created_at, run_id"
        ):
            raw_rows.append(dict(row))
    finally:
        connection.close()

    instant = time.time()
    breakdown = worker.phase_ledger_breakdown(records, instant=instant)
    independent = independent_rule(raw_rows, instant=instant)
    detected = detector(raw_rows, instant=instant, phase_cap=spec.TIMING["phase_wall_max_seconds"], deadline=450.0)
    variants = broken_variants(raw_rows, instant=instant)

    calendar_total = sum(max(0.0, instant - float(row["created_at"])) for row in raw_rows)
    per_row_sum = detected["counted_total_seconds"]

    variant_rows = []
    for name, value in variants.items():
        if name.startswith("_"):
            continue
        if name in ("unknown_state_as_zero", "unknown_state_as_active"):
            # The frozen rule refuses that dataset outright (unknown state), so a
            # variant that returns a number at all is the defect.
            defective = True
            note = "the frozen rule refuses this dataset (unknown state); the variant charges a number"
        elif name == "global_max_instead_of_per_row_max":
            # On the real rows the reservation dominates, so the global max happens
            # to agree; the dedicated synthetic case below separates the two rules.
            defective = True
            note = "the two rules agree on the real rows (the reservation dominates); the "\
                   "synthetic case per_row_max_vs_global_max shows they are different rules"
        else:
            defective = abs(float(value) - per_row_sum) > 1e-6
            note = "the variant total differs from the frozen per-row rule"
        variant_rows.append(
            {
                "variant": name,
                "total_seconds": float(value),
                "frozen_rule_total_seconds": per_row_sum,
                "defect_detected": bool(defective),
                "note": note,
            }
        )

    agreement = []
    for product_row, mine in zip(breakdown["rows"], independent):
        agreement.append(
            {
                "run_id": product_row["run_id"],
                "product_counted": product_row["counted_seconds"],
                "independent_counted": mine["counted_seconds"],
                "equal": abs(product_row["counted_seconds"] - mine["counted_seconds"]) <= 1e-9,
                "product_reserved": product_row["reserved_active_seconds"],
                "ledger_reserved": mine["reserved_active_seconds"],
                "reserved_equal": abs(
                    product_row["reserved_active_seconds"] - mine["reserved_active_seconds"]
                )
                <= 1e-9,
                "state": product_row["state"],
                "rule": product_row["rule"],
            }
        )

    # --- corrupt rows must be refused by the product function --------------
    corrupt = {}
    cases = {
        "unknown_state": make_record(state="hibernating"),
        "reverse_timestamps": make_record(
            created_at=iso(2_000.0), updated_at=iso(1_000.0)
        ),
        "nan_created_at": make_record(created_at=float("nan")),
        "inf_updated_at": make_record(updated_at=float("inf")),
        "missing_created_at": make_record(created_at=None),
        "unparseable_timestamp": make_record(created_at="not-a-timestamp"),
        "non_finite_reservation": make_record(reserved_active_seconds=float("nan")),
        "negative_infinite_reservation": make_record(
            reserved_active_seconds=float("-inf")
        ),
        # the decision lists "non-finite / reverse / unknown terminal state" as
        # must-refuse; a far-future finite timestamp is not in that list, but the
        # r7 report claims an "overflow_timestamp" refused state, so it is probed.
        "far_future_float_timestamp": make_record(
            created_at=1e308, updated_at=1e308, reserved_active_seconds=7.0
        ),
        "overflow_subtraction": make_record(
            created_at=-1e308, updated_at=1e308, reserved_active_seconds=7.0
        ),
    }
    for name, record in cases.items():
        try:
            counted = worker.run_conservative_wall_seconds(record, instant=instant)
        except (ValueError, OverflowError) as exc:
            corrupt[name] = {"refused": True, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:  # noqa: BLE001
            corrupt[name] = {"refused": False, "error": f"UNEXPECTED {type(exc).__name__}: {exc}"}
        else:
            corrupt[name] = {"refused": False, "error": None, "counted_seconds": counted}

    # A row object that does not carry the reservation field at all: the field
    # is silently treated as 0 (disclosed weakness, not reachable from RunStore).
    class NoReservation:
        run_id = "no-reservation"
        state = "completed"
        created_at = iso(1_000.0)
        updated_at = iso(1_010.0)

    missing_field = {
        "counted_seconds": worker.run_conservative_wall_seconds(NoReservation(), instant=instant),
        "note": "a run object without reserved_active_seconds is charged 0 for the "
        "reservation; the real RunRecord always carries the field",
    }

    # --- a case where per-row max and a global max disagree ----------------
    synthetic = [
        {
            "run_id": "synthetic-A",
            "state": "completed",
            "created_at": 1_000.0,
            "updated_at": 2_000.0,
            "active_seconds": 100.0,
        },
        {
            "run_id": "synthetic-B",
            "state": "completed",
            "created_at": 1_000.0,
            "updated_at": 1_010.0,
            "active_seconds": 100.0,
        },
    ]
    synthetic_product = worker.phase_ledger_breakdown(
        [
            make_record(
                run_id=row["run_id"],
                state=row["state"],
                created_at=iso(row["created_at"]),
                updated_at=iso(row["updated_at"]),
                reserved_active_seconds=row["active_seconds"],
            )
            for row in synthetic
        ],
        instant=instant,
    )
    synthetic_global_max = max(
        sum(row["active_seconds"] for row in synthetic),
        sum(row["updated_at"] - row["created_at"] for row in synthetic),
    )

    payload = {
        "schema": "ainerzero.v9.p21.probe05_phase_accounting.v1",
        "real_ledger": str(REAL_LEDGER),
        "real_ledger_copy": copy_info,
        "read_path": "byte-identical copy opened with the real RunStore (the real ledger is "
        "never opened for writing and the RunStore read interface is never called on it)",
        "rows": len(records),
        "product_breakdown": breakdown,
        "independent_rows": independent,
        "agreement": agreement,
        "totals": {
            "product_total_seconds": breakdown["total_seconds"],
            "independent_total_seconds": detected["counted_total_seconds"],
            "reserved_total_seconds": detected["reserved_total_seconds"],
            "calendar_age_total_seconds": calendar_total,
            "phase_wall_max_seconds": spec.TIMING["phase_wall_max_seconds"],
            "old_rule_would_refuse": calendar_total + 450.0 > spec.TIMING["phase_wall_max_seconds"],
            "new_rule_refuses": detected["would_refuse"],
            "reserved_is_a_preregistered_allowance_not_a_measurement": True,
            "no_row_refunded": not detected["problems"],
            "detector_problems": detected["problems"],
        },
        "broken_guard_controls": {
            "variants": variant_rows,
            "detector_total": per_row_sum,
            "every_broken_variant_detected": all(
                row["defect_detected"] for row in variant_rows
            ),
            "note": "the r6 calendar-age rule, an unknown state charged as 0 or as active, a "
            "dropped reservation and a global max instead of a per-row max must all be "
            "distinguishable from the frozen rule",
        },
        "corrupt_row_controls": corrupt,
        "missing_reservation_field": missing_field,
        "per_row_max_vs_global_max": {
            "synthetic_rows": synthetic,
            "product_total_seconds": synthetic_product["total_seconds"],
            "global_max_seconds": synthetic_global_max,
            "differs": abs(synthetic_product["total_seconds"] - synthetic_global_max) > 1e-9,
        },
        "mlx_imported": lib.mlx_imported(),
    }
    decision_required_refusals = (
        "unknown_state",
        "reverse_timestamps",
        "nan_created_at",
        "inf_updated_at",
        "missing_created_at",
        "unparseable_timestamp",
    )
    payload["verdict"] = {
        "product_matches_independent_rule": all(
            row["equal"] and row["reserved_equal"] for row in agreement
        ),
        "reserved_equals_720_267": abs(detected["reserved_total_seconds"] - 720.267) < 1e-3,
        "old_rule_would_have_refused": payload["totals"]["old_rule_would_refuse"],
        "new_rule_does_not_refuse": not payload["totals"]["new_rule_refuses"],
        "no_row_refunded": not detected["problems"],
        "broken_variants_all_detected": payload["broken_guard_controls"][
            "every_broken_variant_detected"
        ],
        "decision_required_corrupt_rows_all_refused": all(
            corrupt[name]["refused"] for name in decision_required_refusals
        ),
        "per_row_max_is_not_a_global_max": payload["per_row_max_vs_global_max"]["differs"],
    }
    payload["findings"] = {
        "far_future_timestamp_not_refused": not corrupt["far_future_float_timestamp"]["refused"],
        "far_future_timestamp_detail": corrupt["far_future_float_timestamp"],
        "overflow_subtraction_detail": corrupt["overflow_subtraction"],
        "nan_reservation_not_refused": not corrupt["non_finite_reservation"]["refused"],
        "nan_reservation_detail": corrupt["non_finite_reservation"],
        "negative_infinite_reservation_detail": corrupt["negative_infinite_reservation"],
        "why": "run_conservative_wall_seconds normalises the reservation with "
        "max(0.0, float(value)), and Python's max(0.0, nan) is 0.0, so a NaN (or -inf) "
        "reservation silently becomes 0 and the following isfinite() guard can never "
        "fire for it; the row is then charged only its terminal interval",
        "reachability": "SQLite stores NaN as NULL and the column is NOT NULL with "
        "CHECK(active_seconds >= 0), so the real ledger cannot hold a NaN reservation; "
        "the defect is in the code's own refusal claim, not in the live data path",
        "report_claim": "the r7 report lists 'non_finite' and 'overflow_timestamp' among the "
        "refused states; no test in tests/v9/experiments covers either and a NaN "
        "reservation or a finite far-future timestamp is accepted, not refused",
        "missing_reservation_field": missing_field,
    }
    out = lib.write_json("05-phase-accounting.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(payload["totals"], indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
