"""r7 phase-accounting evidence: byte-isolated copy of the real ledger.

The real RunStore is opened read-only; a byte copy is the only thing measured.
Two quantities are reported per row so the old defect and the r7 rule are both
visible:

* ``calendar_age``  -- now - created_at for every row (the r6 behaviour, which
  charged a finished run for the days after it ended);
* ``conservative``  -- max(reserved_active, terminal_interval) for terminal
  rows, max(reserved_active, now - created_at) for active rows (r7).

Nothing under artifacts/ is written.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import spec, worker  # noqa: E402

OUT = REPO / "reports/V9-P9/r7/evidence/phase-accounting.json"


def main() -> int:
    real = Path(spec.REGISTERED_HOST_LEDGER)
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    tmp = Path(tempfile.mkdtemp(prefix="s1-r7-phase-copy-"))
    copy = tmp / "control.sqlite3"
    shutil.copyfile(real, copy)
    copy_digest_before = hashlib.sha256(copy.read_bytes()).hexdigest()

    connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        raw = list(
            connection.execute(
                "SELECT run_id, state, created_at, updated_at, active_seconds, experiment_id "
                "FROM runs ORDER BY created_at"
            )
        )
    finally:
        connection.close()

    from types import SimpleNamespace

    runs = [
        SimpleNamespace(
            run_id=run_id,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            reserved_active_seconds=active_seconds,
        )
        for run_id, state, created_at, updated_at, active_seconds, _exp in raw
    ]
    now = time.time()
    breakdown = worker.phase_ledger_breakdown(runs, instant=now)
    ages = [
        {
            "run_id": row.run_id,
            "state": row.state,
            "calendar_age_seconds": max(
                0.0, now - worker._parse_timestamp(row.created_at)
            ),
        }
        for row in runs
    ]
    payload = {
        "schema": "ainerzero.v9.s1.r7.phase_accounting.v1",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "real_ledger": str(real),
        "real_ledger_sha256_before": before,
        "real_ledger_sha256_after": hashlib.sha256(real.read_bytes()).hexdigest(),
        "copy": str(copy),
        "copy_sha256_before": copy_digest_before,
        "copy_sha256_after": hashlib.sha256(copy.read_bytes()).hexdigest(),
        "rows": breakdown["rows"],
        "calendar_age_rows": ages,
        "calendar_age_total_seconds": sum(r["calendar_age_seconds"] for r in ages),
        "reserved_active_total_seconds": sum(
            r["reserved_active_seconds"] for r in breakdown["rows"]
        ),
        "conservative_total_seconds": breakdown["total_seconds"],
        "phase_wall_max_seconds": spec.TIMING["phase_wall_max_seconds"],
        "calendar_age_would_refuse": (
            sum(r["calendar_age_seconds"] for r in ages)
            + float(spec.TIMING["per_run_wall_max_seconds"]) * 0
            > spec.TIMING["phase_wall_max_seconds"]
        ),
        "limitations": [
            "reserved_active_seconds is the pre-registered allowance, not a measured activity time",
            "the copy is measured read-only; no repair, migration or re-freeze is performed on it",
            "the real ledger digest is recorded before and after; no zero-write assertion is made "
            "for processes that were already running",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(f"rows={len(runs)}")
    print(f"calendar_age_total={payload['calendar_age_total_seconds']:.3f}")
    print(f"reserved_total={payload['reserved_active_total_seconds']:.3f}")
    print(f"conservative_total={payload['conservative_total_seconds']:.3f}")
    print(f"real_unchanged={before == payload['real_ledger_sha256_after']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
