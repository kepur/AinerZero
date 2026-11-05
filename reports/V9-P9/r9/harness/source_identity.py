"""r9 source identity: the r9 frozen document against the files on disk.

Writes ``reports/V9-P9/r9/source-identity.json`` with the same shape as r8:
every bound file's hash as recorded in the frozen document, its hash now, the
document/file digests and a pass/fail status.  Read-only over the sources.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

DOC = REPO / "artifacts/v9/s1/phase1/r9/pre_registration.json"
OUT = REPO / "reports/V9-P9/r9/source-identity.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    document = json.loads(DOC.read_text(encoding="utf-8"))
    bound = document["source_identity"]["package_files"]
    rows = {}
    drift = []
    for rel, recorded in sorted(bound.items()):
        path = REPO / rel
        actual = sha256(path) if path.is_file() else None
        rows[rel] = actual
        if actual != recorded:
            drift.append(rel)
    payload = {
        "schema": "ainerzero.v9.s1.r9.source_identity.v1",
        "status": "passed" if not drift else "drift",
        "drift_files": drift,
        "bound_file_count": len(bound),
        "bound_files": rows,
        "document_sha256": prereg.document_sha256(document),
        "file_sha256": sha256(DOC),
        "package_map_digest": document["source_identity"]["package_map_digest"],
        "frozen_document": str(DOC.relative_to(REPO)),
        "frozen_status": document.get("status"),
        "updates": document["training_protocol"]["updates"],
        "timing": {
            key: document["timing"][key]
            for key in (
                "deadline_seconds",
                "arm1_deadline_seconds",
                "per_run_wall_max_seconds",
                "phase_wall_max_seconds",
            )
        },
        "seeds": document["training_protocol"].get("seeds"),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "bound_files": len(bound),
                "drift": drift,
                "document_sha256": payload["document_sha256"],
                "file_sha256": payload["file_sha256"],
            },
            indent=1,
        )
    )
    return 0 if not drift else 7


if __name__ == "__main__":
    raise SystemExit(main())
