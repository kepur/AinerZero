"""Leaf-level diff between the frozen r7 and r8 preregistration documents."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402
R5 = REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
R6 = REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json"
OUT = REPO / "reports/V9-P9/r8/prereg-leaf-diff.json"


def flat(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = obj
        for key in sorted(obj):
            out.update(flat(obj[key], f"{prefix}.{key}" if prefix else key))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = obj
        for index, value in enumerate(obj):
            out.update(flat(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = obj
    return out


def document_sha(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return prereg.document_sha256(data)


def main() -> int:
    r5 = json.loads(R5.read_text(encoding="utf-8"))
    r6 = json.loads(R6.read_text(encoding="utf-8"))
    left, right = flat(r5), flat(r6)
    rows = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            rows.append({"path": key, "change": "added", "new": right[key]})
        elif key not in right:
            rows.append({"path": key, "change": "removed", "base": left[key]})
        elif left[key] != right[key]:
            rows.append({"path": key, "change": "changed", "base": left[key], "new": right[key]})
    scientific = [
        row
        for row in rows
        if not (
            row["path"].startswith("source_identity.")
            or row["path"] in ("created_unix", "timing.smoke_recheck")
            or row["path"].startswith("timing.smoke_recheck.")
        )
    ]
    payload = {
        "base_path": str(R5.relative_to(REPO)),
        "new_path": str(R6.relative_to(REPO)),
        "base_document_sha256": document_sha(R5),
        "new_document_sha256": document_sha(R6),
        "base_file_sha256": hashlib.sha256(R5.read_bytes()).hexdigest(),
        "new_file_sha256": hashlib.sha256(R6.read_bytes()).hexdigest(),
        "leaf_count": len(set(left) | set(right)),
        "changed_leaf_count": len(rows),
        "non_identity_leaves_outside_allowlist": scientific,
        "changes": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(f"leaves={payload['leaf_count']} changed={len(rows)}")
    print(f"base_doc={payload['base_document_sha256']}")
    print(f"new_doc={payload['new_document_sha256']}")
    print(f"new_file={payload['new_file_sha256']}")
    for row in rows:
        print(row["change"], row["path"])
    print("outside allowlist:", [row["path"] for row in scientific])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
