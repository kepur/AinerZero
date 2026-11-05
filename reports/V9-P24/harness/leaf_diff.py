#!/usr/bin/env python3
"""P24 independent r7 -> r8 leaf diff.

Written from the S1-R8-DECISION rule, not from the author's script: leaves are
computed with this file's own flattener (empty containers count as leaves), the
allowlist is spelled out here, and every leaf outside the allowlist must be
identical.  Also re-checks the 21 bound files in source_identity.package_files
against the bytes on disk and the document/file digests.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

R7 = REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
R8 = REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json"
OUT = REPO / "reports/V9-P24/evidence/prereg-leaf-diff.json"

# Leaves the decision allows to move: implementation/source binding, generation
# time, and derived spec/package digests.  No scientific field is listed.
ALLOWED_EXACT = {"created_unix", "source_identity.package_map_digest"}
ALLOWED_PREFIXES = ("source_identity.package_files.", "source_identity.spec.sha256")


def flat(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = "<empty-dict>"
        for key in obj:
            flat(obj[key], f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = "<empty-list>"
        for index, value in enumerate(obj):
            flat(value, f"{prefix}[{index}]", out)
    else:
        out[prefix] = obj
    return out


def allowed(path: str) -> bool:
    return path in ALLOWED_EXACT or any(path.startswith(p) for p in ALLOWED_PREFIXES)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    r7 = json.loads(R7.read_text(encoding="utf-8"))
    r8 = json.loads(R8.read_text(encoding="utf-8"))
    left, right = flat(r7), flat(r8)
    rows = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            rows.append({"path": key, "change": "added", "new": right[key]})
        elif key not in right:
            rows.append({"path": key, "change": "removed", "base": left[key]})
        elif left[key] != right[key]:
            rows.append({"path": key, "change": "changed", "base": left[key], "new": right[key]})
    outside = [row for row in rows if not allowed(row["path"])]

    bound = r8["source_identity"]["package_files"]
    bindings = {}
    for rel, expected in sorted(bound.items()):
        path = REPO / rel
        actual = sha256_file(path) if path.is_file() else None
        bindings[rel] = {
            "present": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "expected": expected,
            "actual": actual,
            "match": actual == expected,
        }

    doc_sha = prereg.document_sha256(r8)
    file_sha = sha256_file(R8)
    sidecar_line = (REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json.sha256").read_text(
        encoding="utf-8"
    ).strip()
    sidecar = sidecar_line.split()[0]
    spec_rel = r8["source_identity"]["spec"]["path"]
    spec_sha = sha256_file(REPO / spec_rel)

    checks = {
        "r7_leaves": len(left),
        "r8_leaves": len(right),
        "changed_leaves": len(rows),
        "changed_paths": [row["path"] for row in rows],
        "outside_allowlist": outside,
        "outside_allowlist_empty": not outside,
        "scientific_fields_equal": not any(
            not row["path"].startswith("source_identity.") for row in rows
            if row["path"] != "created_unix"
        ),
        "document_sha256": doc_sha,
        "document_sha_matches_decision": doc_sha
        == "2082e2a3c36cd648fb1608727a7f8ea0fc9afcc38e29af527c48d62f5d477175",
        "file_sha256": file_sha,
        "file_sha_matches_decision": file_sha
        == "e8cfa2390624fdf6e82829a658942e11bc012043ae8fba5602d76d9189c8114a",
        "sidecar": sidecar,
        "sidecar_matches_document": sidecar == doc_sha,
        "status": r8["status"],
        "status_is_awaiting": r8["status"] == "awaiting_coordinator_approval",
        "bound_files": len(bound),
        "bound_files_all_match": all(v["match"] for v in bindings.values()),
        "spec_sha": spec_sha,
        "spec_sha_matches": spec_sha == r8["source_identity"]["spec"]["sha256"],
        "r7_document_sha256": prereg.document_sha256(r7),
    }
    checks["passed"] = all(
        [
            checks["outside_allowlist_empty"],
            checks["scientific_fields_equal"],
            checks["document_sha_matches_decision"],
            checks["file_sha_matches_decision"],
            checks["sidecar_matches_document"],
            checks["status_is_awaiting"],
            checks["bound_files"] == 21,
            checks["bound_files_all_match"],
            checks["spec_sha_matches"],
        ]
    )
    payload = {
        "tool": "reports/V9-P24/harness/leaf_diff.py",
        "r7": str(R7.relative_to(REPO)),
        "r8": str(R8.relative_to(REPO)),
        "rule": "only created_unix, source_identity.package_files.*, "
        "source_identity.package_map_digest and source_identity.spec.sha256 may move",
        "checks": checks,
        "rows": rows,
        "bindings": bindings,
    }
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: checks[k] for k in (
        "passed", "r7_leaves", "r8_leaves", "changed_leaves", "outside_allowlist_empty",
        "scientific_fields_equal", "document_sha256", "file_sha256", "status",
        "bound_files", "bound_files_all_match", "spec_sha_matches")}, indent=1))
    print("changed_paths:", json.dumps(checks["changed_paths"], indent=1))
    return 0 if checks["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
