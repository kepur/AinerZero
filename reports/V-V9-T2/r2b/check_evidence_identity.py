#!/usr/bin/env python3
"""Check evidence identity and SHA256 consistency for ainerzero.V9.T2 r2."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    metrics_path = ROOT / "reports/V9-T2/metrics.json"
    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics_data = json.load(f)

    registered_shas = metrics_data.get("source_sha256", {})
    results = {}
    all_match = True

    for rel_path, expected_sha in registered_shas.items():
        abs_path = ROOT / rel_path
        exists = abs_path.exists()
        disk_sha = sha256_file(abs_path) if exists else None
        match = (disk_sha == expected_sha)
        if not match:
            all_match = False
        results[rel_path] = {
            "exists": exists,
            "registered_sha256": expected_sha,
            "disk_sha256": disk_sha,
            "match": match,
        }

    # Verify r1-archive
    r1_archive_dir = ROOT / "reports/V9-T2/r1-archive"
    r1_files = {
        "LATE_OVERWRITE_NOTE.md": (r1_archive_dir / "LATE_OVERWRITE_NOTE.md").exists(),
        "REPORT.md": (r1_archive_dir / "REPORT.md").exists(),
        "metrics.json": (r1_archive_dir / "metrics.json").exists(),
        "disk_sha256_at_r2_claim.txt": (r1_archive_dir / "disk_sha256_at_r2_claim.txt").exists(),
    }
    r1_archive_ok = all(r1_files.values())

    # Check git diff of docs/v9/TEACHERS_AND_CACHE.md
    git_diff_doc = subprocess.run(
        ["git", "diff", "HEAD", "--", "docs/v9/TEACHERS_AND_CACHE.md"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    ).stdout

    # Check git diff of contracts/v9/teacher_cache.v2.schema.json
    git_diff_schema = subprocess.run(
        ["git", "diff", "HEAD", "--", "contracts/v9/teacher_cache.v2.schema.json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    ).stdout

    added_lines = [
        line for line in git_diff_doc.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]

    out = {
        "all_source_shas_match": all_match,
        "shas": results,
        "r1_archive_exists": r1_archive_ok,
        "r1_archive_files": r1_files,
        "v2_schema_clean_vs_head": len(git_diff_schema.strip()) == 0,
        "doc_diff_added_line_count": len(added_lines),
        "doc_diff_added_lines": added_lines,
        "overall_identity_ok": all_match and r1_archive_ok and (len(git_diff_schema.strip()) == 0),
    }

    out_path = ROOT / "reports/V-V9-T2/r2b/evidence_identity.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["overall_identity_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
