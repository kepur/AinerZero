"""Emit SHA256 lines for the r11 report (script output pasted verbatim)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "reports/V9-P9/r11/evidence/sha256sums.txt"

PATHS = [
    "src/ainerzero/v9/experiments/s1/spec.py",
    "src/ainerzero/v9/experiments/s1/prereg.py",
    "src/ainerzero/v9/experiments/s1/worker.py",
    "src/ainerzero/v9/experiments/s1/commands.py",
    "tests/v9/experiments/test_s1_r11_registration.py",
    "tests/v9/experiments/test_s1_prereg.py",
    "tests/v9/experiments/test_s1_r8_completion.py",
    "tests/v9/experiments/test_s1_r8_d_budget.py",
    "artifacts/v9/s1/phase1/r11/draft_preregistration.json",
    "artifacts/v9/s1/phase1/r11/pre_registration.json",
    "artifacts/v9/s1/phase1/r11/pre_registration.json.sha256",
    "artifacts/v9/s1/phase1/r11/dataset_ref.json",
    "artifacts/v9/s1/phase1/r10/pre_registration.json",
    "reports/V9-S1/metrics.json",
    "reports/V9-P9/r1-archive/smoke_metrics.json",
]


def main() -> int:
    lines = []
    for rel in PATHS:
        path = REPO / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}")
    # document sha (canonical)
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from ainerzero.v9.experiments.s1 import prereg

    doc = json.loads((REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json").read_text())
    lines.append(f"{prereg.document_sha256(doc)}  DOCUMENT_SHA256(artifacts/v9/s1/phase1/r11/pre_registration.json)")
    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
