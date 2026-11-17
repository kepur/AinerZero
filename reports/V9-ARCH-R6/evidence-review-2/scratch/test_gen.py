#!/usr/bin/env python3
"""自动化构建 claims.json 的生成器，并直接校验。"""
import json
import hashlib
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
CAND = ROOT / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
OUT = ROOT / "reports" / "V9-ARCH-R6" / "evidence-review-2" / "claims.json"

cand_text = CAND.read_text(encoding="utf-8")
cand_sha = hashlib.sha256(cand_text.encode("utf-8")).hexdigest()

def line_of(p_rel, n):
    p = (ROOT / p_rel).resolve()
    lines = p.read_text(encoding="utf-8").split("\n")
    return lines[n - 1].strip()

def make_ev(p_rel, n):
    return {"file": p_rel, "line": n, "text": line_of(p_rel, n)}

print("Script template ready")
