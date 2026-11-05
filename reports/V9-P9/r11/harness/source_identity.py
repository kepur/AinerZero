"""r11 source identity: frozen document against files on disk."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

DOC = REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json"
OUT = REPO / "reports/V9-P9/r11/source-identity.json"


def main() -> int:
    document = json.loads(DOC.read_text(encoding="utf-8"))
    binding = prereg.source_binding_state(document)
    files = []
    for rel, row in sorted((binding.get("files") or {}).items()):
        path = REPO / rel
        files.append(
            {
                "path": rel,
                "expected": row.get("expected"),
                "actual": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                "match": row.get("match"),
                "present": row.get("present"),
            }
        )
    payload = {
        "schema": "ainerzero.v9.s1.r11.source_identity.v1",
        "document_path": str(DOC.relative_to(REPO)),
        "document_sha256": prereg.document_sha256(document),
        "file_sha256": hashlib.sha256(DOC.read_bytes()).hexdigest(),
        "binding_status": binding.get("status"),
        "drifted": binding.get("drifted") or [],
        "bound_files": files,
        "package_map_digest": (document.get("source_identity") or {}).get("package_map_digest"),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({k: payload[k] for k in ("document_sha256", "file_sha256", "binding_status", "drifted")}, indent=1))
    return 0 if binding.get("status") == "passed" else 7


if __name__ == "__main__":
    raise SystemExit(main())
