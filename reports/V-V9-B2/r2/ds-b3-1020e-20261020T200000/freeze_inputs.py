#!/usr/bin/env python3
"""Read-only identity freeze for the independent r2 review of ainerzero.V9.B2.

Computes SHA-256 over every input this review relies on, compares the B2-owned
files with the author's own ``source-sha256.json``, and writes a timestamped
manifest.  It never writes outside its own run directory.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
AWZ = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")
HERE = Path(__file__).resolve().parent
OUT = HERE / "sha256-inputs-before.json"
AUTHOR = ROOT / "reports/V9-B2/r1-mimo-5fb1-20261020/source-sha256.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"refusing to overwrite existing manifest: {OUT}")
    targets: list[Path] = []
    for pattern in (
        "src/ainerzero/v9/__init__.py",
        "src/ainerzero/v9/interfaces/*.py",
        "src/ainerzero/v9/fakes/*.py",
        "tests/v9/contracts/*.py",
        "tests/v9/teachers/test_cache.py",
        "tests/v9/teachers/test_mode.py",
        "reports/V-V9-B2/*.py",
        "reports/V-V9-B2/*.json",
        "reports/V-V9-B2/*.md",
        "reports/V9-B2/r1-mimo-5fb1-20261020/*",
        "AGENTS.md",
        "README.md",
        "COORDINATION.md",
        "AGENT_TASKS.md",
        "RESEARCH_LOG.md",
        "docs/v9/TEACHERS_AND_CACHE.md",
    ):
        targets.extend(sorted(ROOT.glob(pattern)))
    targets.extend(
        [
            Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261020-evening/DECISIONS.md"),
            AWZ / "contracts/v9/observation_leak_rules.v1_1.json",
            AWZ / "contracts/v9/observation_packet.v1_1.schema.json",
        ]
    )
    records = {}
    for path in targets:
        if path.is_file():
            records[str(path)] = sha(path)
    author = json.loads(AUTHOR.read_text())
    owned = author.get("owned_files", {})
    mismatches = []
    for rel, expected in owned.items():
        current = records.get(str(ROOT / rel))
        if current is None:
            mismatches.append({"file": rel, "reason": "missing_from_review_manifest", "author": expected})
        elif current != expected:
            mismatches.append({"file": rel, "reason": "sha_mismatch", "author": expected, "current": current})
    awz_author = author.get("awz_inputs", {})
    awz_mismatches = []
    for abs_path, expected in awz_author.items():
        current = records.get(abs_path)
        if current is None:
            awz_mismatches.append({"file": abs_path, "reason": "missing_input", "author": expected})
        elif current != expected:
            awz_mismatches.append({"file": abs_path, "reason": "sha_mismatch", "author": expected, "current": current})
    doc = {
        "task": "ainerzero.V9.B3",
        "review_round": "r2",
        "agent": "ds-b3-1020e",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version,
        "platform": platform.platform(),
        "inputs": records,
        "author_manifest": str(AUTHOR),
        "author_manifest_sha256": sha(AUTHOR),
        "author_owned_file_mismatches": mismatches,
        "author_awz_input_mismatches": awz_mismatches,
        "all_author_owned_match": not mismatches,
        "all_author_awz_match": not awz_mismatches,
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in (
        "author_owned_file_mismatches", "author_awz_input_mismatches",
        "all_author_owned_match", "all_author_awz_match", "author_manifest_sha256")}, indent=2))
    return 0 if not mismatches and not awz_mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
