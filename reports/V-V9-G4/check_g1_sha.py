#!/usr/bin/env python3
"""Confirm G1 accepted sources vs registry / git HEAD / working tree (G4)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "reports/V9-G1/r1-codex-20261016/source-sha256.json"
G3_METRICS = ROOT / "reports/V9-G3/r1-deepseek-flash-20261020/metrics.json"
G3_SRC = ROOT / "reports/V9-G3/r1-deepseek-flash-20261020/source-sha256.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_head_bytes(rel: str) -> bytes:
    return subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    expected = json.loads(REGISTRY.read_text())
    checks = {}
    head_all_match = True
    wt_all_match = True
    for rel, want in expected.items():
        head_h = sha256_bytes(git_head_bytes(rel))
        wt_h = sha256_file(ROOT / rel)
        head_ok = head_h == want
        wt_ok = wt_h == want
        head_all_match = head_all_match and head_ok
        wt_all_match = wt_all_match and wt_ok
        checks[rel] = {
            "expected": want,
            "git_head": head_h,
            "working_tree": wt_h,
            "head_matches_registry": head_ok,
            "working_tree_matches_registry": wt_ok,
            "working_tree_matches_head": wt_h == head_h,
        }
        status = "HEAD=OK"
        if not head_ok:
            status = "HEAD_DRIFT"
        if not wt_ok:
            status += "+WT_DRIFT"
        print(f"{status}  {rel}")

    g3 = json.loads(G3_METRICS.read_text())
    g3_claim_matches_registry = True
    for rel, info in g3.get("g1_source_checks", {}).items():
        if info.get("expected") != expected.get(rel):
            g3_claim_matches_registry = False
            print(f"G3_EXPECTED_MISMATCH  {rel}")
        # Author claimed actual==expected at delivery; re-validate against HEAD now.
        if info.get("actual") != checks[rel]["git_head"]:
            # If WT drifted after G3, author's recorded actual still equals HEAD.
            if info.get("actual") != expected.get(rel):
                g3_claim_matches_registry = False
                print(f"G3_ACTUAL_MISMATCH  {rel}")

    g3_src = json.loads(G3_SRC.read_text())
    new_ok = True
    new_checks = {}
    for rel, want in g3_src.items():
        actual = sha256_file(ROOT / rel)
        match = actual == want
        new_checks[rel] = {"expected": want, "actual": actual, "match": match}
        new_ok = new_ok and match
        print(f"{'OK' if match else 'DRIFT'}  G3:{rel}")

    # Pass criterion for G3 authorship: git HEAD still byte-identical to G1 registry.
    # Working-tree-only edits (e.g. queued G5 F1/F2 patches) are reported but do not
    # by themselves falsify G3's "did not modify G1" claim.
    g3_did_not_change_g1 = head_all_match
    out = {
        "g1_registry": str(REGISTRY.relative_to(ROOT)),
        "git_head_matches_g1_registry": head_all_match,
        "working_tree_matches_g1_registry": wt_all_match,
        "g3_did_not_change_committed_g1": g3_did_not_change_g1,
        "g3_author_expected_hashes_match_registry": g3_claim_matches_registry,
        "working_tree_uncommitted_drift": not wt_all_match,
        "g1_checks": checks,
        "g3_new_sources_match_registry": new_ok,
        "g3_new_checks": new_checks,
        "pass": bool(g3_did_not_change_g1 and g3_claim_matches_registry and new_ok),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in (
        "git_head_matches_g1_registry",
        "working_tree_matches_g1_registry",
        "g3_did_not_change_committed_g1",
        "working_tree_uncommitted_drift",
        "pass",
    )}, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
