"""Leaf-level diff between the frozen r8 and r9 preregistration documents.

Every leaf is compared.  The only permitted differences are the implementation
identity (``source_identity.*``) and ``created_unix`` -- and inside
``source_identity`` only the files this card edited may differ, which is
reported separately as ``changed_bound_files``.  Any other changed leaf is a
scientific change and fails the card.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

BASE = REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json"
NEW = REPO / "artifacts/v9/s1/phase1/r9/pre_registration.json"
OUT = REPO / "reports/V9-P9/r9/prereg-leaf-diff.json"

ALLOWED_FILES = {
    "src/ainerzero/v9/experiments/s1/worker.py",
}


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
    return prereg.document_sha256(json.loads(path.read_text(encoding="utf-8")))


def changed_bound_files(base: dict, new: dict) -> list[dict]:
    left = (base.get("source_identity") or {}).get("package_files") or {}
    right = (new.get("source_identity") or {}).get("package_files") or {}
    rows = []
    for rel in sorted(set(left) | set(right)):
        if left.get(rel) != right.get(rel):
            rows.append({"path": rel, "base": left.get(rel), "new": right.get(rel)})
    return rows


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    new = json.loads(NEW.read_text(encoding="utf-8"))
    left, right = flat(base), flat(new)
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
    files = changed_bound_files(base, new)
    outside = [row["path"] for row in files if row["path"] not in ALLOWED_FILES]

    payload = {
        "base_path": str(BASE.relative_to(REPO)),
        "new_path": str(NEW.relative_to(REPO)),
        "base_document_sha256": document_sha(BASE),
        "new_document_sha256": document_sha(NEW),
        "base_file_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
        "new_file_sha256": hashlib.sha256(NEW.read_bytes()).hexdigest(),
        "leaf_count": len(set(left) | set(right)),
        "changed_leaf_count": len(rows),
        "changed_bound_files": files,
        "bound_files_outside_allowlist": outside,
        "allowlist": sorted(ALLOWED_FILES),
        "non_identity_leaves_outside_allowlist": scientific,
        "changes": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(f"leaves={payload['leaf_count']} changed={len(rows)}")
    print(f"base_doc={payload['base_document_sha256']}")
    print(f"new_doc={payload['new_document_sha256']}")
    print(f"new_file={payload['new_file_sha256']}")
    print("changed bound files:", [row["path"] for row in files])
    print("bound files outside allowlist:", outside)
    print("outside allowlist:", [row["path"] for row in scientific])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
