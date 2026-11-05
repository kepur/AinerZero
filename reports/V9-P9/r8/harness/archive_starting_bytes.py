"""r8 start-of-work byte archive (S1-R8-DECISION: archive r7 bytes/sources first).

Read-only over the previously delivered r7 evidence: this writes only the r8
report directory.  Two inventories are produced:

* ``STARTING-BYTES.json`` -- the exact sha256 of every file the previous
  delivery (r7) reported as frozen, so any drift is visible before the first
  write of this cycle;
* ``STARTING-IMPLEMENTATION.json`` -- the extra implementation sources the r8
  decision adds to the freeze trust chain (generic RunStore lifecycle, D
  candidate loader modules, A2 manifest bytes) plus the real central ledger and
  the approval log bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r8/provenance"

PREVIOUS = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-resume-1200/"
    "P15-r7-review-inputs-live-check.json"
)

IMPLEMENTATION_SOURCES = (
    "src/ainerzero/runtime/lifecycle.py",
    "src/ainerzero/core/pilot.py",
    "src/ainerzero/learning/pilot_model.py",
    "src/ainerzero/runtime/checkpoints.py",
    "reports/V9-baseline/r3/baseline_manifest.json",
    "RESEARCH_LOG.md",
    "artifacts/v9/s1/phase1/control.sqlite3",
    "artifacts/locks/m0-worker.lock",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(paths) -> dict:
    rows = {}
    for rel in paths:
        path = REPO / rel
        rows[rel] = {
            "present": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
        }
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    rows = {}
    drift = []
    for entry in previous:
        path = Path(entry["path"])
        rel = str(path.relative_to(REPO)) if str(path).startswith(str(REPO)) else str(path)
        actual = sha256(path) if path.is_file() else None
        match = actual == entry["sha256"]
        rows[rel] = {"expected": entry["sha256"], "actual": actual, "match": match}
        if not match:
            drift.append(rel)
    starting = {
        "schema": "ainerzero.v9.s1.r8.starting_bytes.v1",
        "source_inventory": str(PREVIOUS),
        "entries": len(rows),
        "files": rows,
        "drift": drift,
        "implementation_sources": inventory(IMPLEMENTATION_SOURCES),
    }
    (OUT / "STARTING-BYTES.json").write_text(
        json.dumps(starting, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "entries": len(rows),
                "drift": drift,
                "out": str((OUT / "STARTING-BYTES.json").resolve()),
            },
            indent=1,
        )
    )
    return 0 if not drift else 7


if __name__ == "__main__":
    sys.exit(main())
