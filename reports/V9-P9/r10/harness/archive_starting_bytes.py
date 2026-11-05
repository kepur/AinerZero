"""Archive starting bytes of the r9 freeze and currently bound sources (read-only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r10/provenance/STARTING-BYTES.json"
R9 = REPO / "artifacts/v9/s1/phase1/r9"
R9_REPORT = REPO / "reports/V9-P9/r9"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = {}
    for path in sorted(R9.glob("*")):
        if path.is_file():
            rows[f"artifacts/v9/s1/phase1/r9/{path.name}"] = {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
    doc = json.loads((R9 / "pre_registration.json").read_text(encoding="utf-8"))
    bound = {}
    for rel in sorted((doc.get("source_identity") or {}).get("package_files") or {}):
        path = REPO / rel
        bound[rel] = {
            "recorded": doc["source_identity"]["package_files"][rel],
            "actual": sha256(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
        }
    payload = {
        "schema": "ainerzero.v9.s1.r10.starting_bytes.v1",
        "r9_freeze_files": rows,
        "r9_bound_sources_at_claim": bound,
        "r9_document_sha256_prefix": "6abce031",
        "r9_report_exists": R9_REPORT.is_dir(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({"r9_files": len(rows), "bound": len(bound)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
