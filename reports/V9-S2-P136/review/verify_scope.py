#!/usr/bin/env python3
"""Scope and diff verification for V9.P136 review.

Verifies:
1. Current worker.py sha256 matches P136 delivery.
2. Reconstructed P126 worker.py matches P126 delivery sha256.
3. Ast function comparison proves only ledger_read_snapshot is changed.
"""

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
P126_SHA_FILE = REPO_ROOT / "reports" / "V9-S2-P126" / "sha256.json"
P136_SHA_FILE = REPO_ROOT / "reports" / "V9-S2-P136" / "sha256.json"
P136_DIFF_FILE = REPO_ROOT / "reports" / "V9-S2-P136" / "worker.diff"
WORKER_FILE = REPO_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "worker.py"


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def get_top_level_definitions(code: str) -> dict[str, str]:
    tree = ast.parse(code)
    lines = code.splitlines(keepends=True)
    defs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            end = node.end_lineno
            defs[node.name] = "".join(lines[start:end])
    return defs


def main() -> int:
    print("=== Scope & Diff Verification for V9.P136 ===")
    
    with open(P126_SHA_FILE, "r") as f:
        p126_shas = json.load(f)
    with open(P136_SHA_FILE, "r") as f:
        p136_shas = json.load(f)
        
    expected_p126_worker_sha = p126_shas["src/ainerzero/v9/experiments/s2/worker.py"]
    expected_p136_worker_sha = p136_shas["src/ainerzero/v9/experiments/s2/worker.py"]
    
    actual_p136_worker_code = WORKER_FILE.read_text(encoding="utf-8")
    actual_p136_worker_sha = sha256(actual_p136_worker_code)
    
    print(f"P136 expected worker SHA: {expected_p136_worker_sha}")
    print(f"P136 actual worker SHA:   {actual_p136_worker_sha}")
    assert actual_p136_worker_sha == expected_p136_worker_sha, "P136 worker SHA256 mismatch!"
    print("[PASS] Current worker.py matches P136 delivery SHA256.")

    # Reconstruct P126 via reverse patch
    with tempfile.TemporaryDirectory() as td:
        tmp_worker = Path(td) / "worker.py"
        tmp_worker.write_text(actual_p136_worker_code, encoding="utf-8")
        res = subprocess.run(
            ["patch", "-R", str(tmp_worker), str(P136_DIFF_FILE)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"[FAIL] Reverse patch failed:\n{res.stdout}\n{res.stderr}")
            return 1
            
        p126_reconstructed_code = tmp_worker.read_text(encoding="utf-8")
        p126_reconstructed_sha = sha256(p126_reconstructed_code)
        
    print(f"P126 expected worker SHA:      {expected_p126_worker_sha}")
    print(f"P126 reconstructed worker SHA: {p126_reconstructed_sha}")
    assert p126_reconstructed_sha == expected_p126_worker_sha, "P126 reconstructed worker SHA256 mismatch!"
    print("[PASS] Reverse patch perfectly reproduces P126 delivered worker.py.")

    # AST comparison
    defs_p126 = get_top_level_definitions(p126_reconstructed_code)
    defs_p136 = get_top_level_definitions(actual_p136_worker_code)
    
    assert defs_p126.keys() == defs_p136.keys(), f"Top-level keys mismatch: {defs_p126.keys()} vs {defs_p136.keys()}"
    
    changed = []
    unchanged = []
    for name in defs_p126:
        if defs_p126[name] != defs_p136[name]:
            changed.append(name)
        else:
            unchanged.append(name)
            
    print(f"Unchanged definitions ({len(unchanged)}): {unchanged}")
    print(f"Changed definitions ({len(changed)}): {changed}")
    
    if changed != ["ledger_read_snapshot"]:
        print(f"[FAIL] Expected only ledger_read_snapshot to change, got: {changed}")
        return 1
        
    print("[PASS] Scope strictly verified: ONLY ledger_read_snapshot was changed.")
    
    result = {
        "status": "PASS",
        "p136_worker_sha256": actual_p136_worker_sha,
        "p126_worker_sha256": expected_p126_worker_sha,
        "reconstructed_matches_p126": True,
        "unchanged_definitions": unchanged,
        "changed_definitions": changed,
        "scope_strictly_single_function": True,
    }
    
    out_json = REPO_ROOT / "reports" / "V9-S2-P136" / "review" / "scope_verification.json"
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved scope verification to {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
