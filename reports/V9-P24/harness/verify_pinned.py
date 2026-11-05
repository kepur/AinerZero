#!/usr/bin/env python3
"""P24 independent recompute of the 72 pinned review inputs and 21 bound files.

Nothing here trusts the author's JSON: every digest is recomputed from the
bytes on disk with hashlib.  Output is JSON (machine) + a deterministic text
table so the report can paste raw script output.

Usage:
  .venv/bin/python reports/V9-P24/harness/verify_pinned.py \
      [--inputs PATH] [--json OUT] [--text OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/"
    "claude-20261022-e32/P15-r8-review-inputs.json"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_one(rel: str, declared: dict) -> dict:
    path = REPO / rel
    row = {"path": rel, "declared_sha256": declared.get("sha256")}
    if not path.is_file():
        row.update({"status": "MISSING", "actual_sha256": None, "actual_bytes": None})
        return row
    actual = sha256(path)
    size = path.stat().st_size
    ok_sha = actual == row["declared_sha256"]
    ok_bytes = "bytes" not in declared or int(declared["bytes"]) == size
    row.update(
        {
            "status": "MATCH" if (ok_sha and ok_bytes) else "MISMATCH",
            "actual_sha256": actual,
            "actual_bytes": size,
            "declared_bytes": declared.get("bytes"),
            "sha_match": ok_sha,
            "bytes_match": ok_bytes,
        }
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default=str(DEFAULT_INPUTS))
    ap.add_argument("--json", default=str(REPO / "reports/V9-P24/evidence/pinned-sha-recompute.json"))
    ap.add_argument("--text", default=str(REPO / "reports/V9-P24/logs/pinned-sha-recompute.txt"))
    ns = ap.parse_args()

    inputs = json.loads(Path(ns.inputs).read_text(encoding="utf-8"))
    files = inputs["files"]
    rows = [check_one(rel, declared) for rel, declared in sorted(files.items())]
    matched = sum(1 for r in rows if r["status"] == "MATCH")
    mismatched = [r["path"] for r in rows if r["status"] != "MATCH"]

    identity_path = REPO / inputs["author_source_identity_file"]
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    bound = identity["bound_files"]
    bound_rows = []
    for rel, declared in sorted(bound.items()):
        actual = sha256(REPO / rel) if (REPO / rel).is_file() else None
        bound_rows.append(
            {
                "path": rel,
                "declared_sha256": declared,
                "actual_sha256": actual,
                "match": actual == declared,
            }
        )
    bound_bad = [r["path"] for r in bound_rows if not r["match"]]

    frozen_rel = identity["frozen_document"]
    frozen_file_actual = sha256(REPO / frozen_rel)
    frozen_doc_digest_line = (REPO / (frozen_rel + ".sha256")).read_text(encoding="utf-8").strip()
    doc_field = identity["document_sha256"].split()[0]

    payload = {
        "tool": "reports/V9-P24/harness/verify_pinned.py",
        "inputs": ns.inputs,
        "pinned_file_count": len(rows),
        "matched": matched,
        "mismatched": mismatched,
        "pinned_present_and_equal_to_declared": matched == len(rows),
        "author_identity_path": inputs["author_source_identity_file"],
        "author_identity_sha256": sha256(identity_path),
        "bound_file_count_declared": identity["bound_file_count"],
        "bound_file_count_actual": len(bound_rows),
        "bound_files_mismatched": bound_bad,
        "bound_files_all_match": not bound_bad,
        "frozen_document": frozen_rel,
        "frozen_document_file_sha256_actual": frozen_file_actual,
        "frozen_document_file_sha256_declared": identity["file_sha256"],
        "frozen_document_file_sha256_match": frozen_file_actual == identity["file_sha256"],
        "frozen_document_sha256_field_actual": doc_field,
        "frozen_document_sha256_sidecar": frozen_doc_digest_line.split()[0],
        "frozen_status": json.loads((REPO / frozen_rel).read_text(encoding="utf-8"))["status"],
        "rows": rows,
        "bound_rows": bound_rows,
    }
    Path(ns.json).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    lines = []
    lines.append("== pinned review inputs (independent sha256 recompute) ==")
    lines.append(f"inputs: {ns.inputs}")
    lines.append(f"count: {len(rows)}  matched: {matched}  mismatched: {len(mismatched)}")
    for r in rows:
        lines.append(f"{r['status']:8s} {r.get('actual_sha256') or '-':64s} {r['path']}")
    lines.append("")
    lines.append("== author-declared bound files (independent recompute) ==")
    lines.append(f"declared count: {identity['bound_file_count']}  recomputed: {len(bound_rows)}  mismatched: {len(bound_bad)}")
    for r in bound_rows:
        lines.append(f"{'MATCH' if r['match'] else 'MISMATCH':8s} {r.get('actual_sha256') or '-':64s} {r['path']}")
    lines.append("")
    lines.append("== frozen r8 document ==")
    lines.append(f"file_sha256 actual   : {frozen_file_actual}")
    lines.append(f"file_sha256 declared : {identity['file_sha256']}")
    lines.append(f"doc_sha256  declared : {doc_field}")
    lines.append(f"doc_sha256  sidecar  : {frozen_doc_digest_line.split()[0]}")
    lines.append(f"status               : {payload['frozen_status']}")
    lines.append(f"pinned_all_match     : {payload['pinned_present_and_equal_to_declared']}")
    lines.append(f"bound_all_match      : {payload['bound_files_all_match']}")
    Path(ns.text).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if payload["pinned_present_and_equal_to_declared"] and not bound_bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
