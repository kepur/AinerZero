"""r9 start-of-work byte archive (P15-R8-DECISION: archive r8 bytes before any write).

Read-only over the delivered r8 evidence.  Two inventories are written into the
r9 report directory only:

* ``bound_files`` -- the 21 files the r8 frozen document bound, re-hashed now, so
  a drift between the r8 delivery and the r9 starting point is visible before the
  first write of this cycle;
* ``r8_artifacts`` / ``r8_reports`` -- every byte of the r8 freeze and the r8
  report, so "r8 原件一字不动" is checkable after this cycle.

No model, no MLX, no ledger write, no approval line.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r9/provenance"
R8_SOURCE_IDENTITY = REPO / "reports/V9-P9/r8/source-identity.json"
R8_ARTIFACTS = REPO / "artifacts/v9/s1/phase1/r8"
R8_REPORTS = REPO / "reports/V9-P9/r8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_inventory(root: Path) -> dict:
    rows = {}
    if not root.is_dir():
        return rows
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows[str(path.relative_to(REPO))] = {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    identity = json.loads(R8_SOURCE_IDENTITY.read_text(encoding="utf-8"))
    bound = identity["bound_files"]

    rows = {}
    drift = []
    for rel, expected in sorted(bound.items()):
        path = REPO / rel
        actual = sha256(path) if path.is_file() else None
        match = actual == expected
        rows[rel] = {"expected": expected, "actual": actual, "match": match}
        if not match:
            drift.append(rel)

    payload = {
        "schema": "ainerzero.v9.s1.r9.starting_bytes.v1",
        "cycle": "r9",
        "r8_source_identity": str(R8_SOURCE_IDENTITY.relative_to(REPO)),
        "r8_document_sha256": identity.get("document_sha256"),
        "bound_file_count": len(bound),
        "bound_files": rows,
        "bound_file_drift": drift,
        "r8_artifacts": tree_inventory(R8_ARTIFACTS),
        "r8_reports": tree_inventory(R8_REPORTS),
        "note": "read-only archive of the r8 delivery; r8 files are never modified by r9",
    }
    target = OUT / "STARTING-BYTES.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "bound_files": len(bound),
                "bound_file_drift": drift,
                "r8_artifacts": len(payload["r8_artifacts"]),
                "r8_reports": len(payload["r8_reports"]),
                "out": str(target.resolve()),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
