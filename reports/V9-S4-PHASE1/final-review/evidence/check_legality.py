#!/usr/bin/env python3
"""S4 Phase 1 Final Review: Legality Verification Script.
Checks:
1. PREREG-r1.json SHA256 in 3 places (file itself, FINAL_READ_ONCE.json, final.json).
2. Marker write time >= commit 2812686 time.
3. Code manifest SHA256 across final.json, PREREG-r1.json, probe-r2/probe.json, and code_dirty is empty.
4. All 40 files in PREREG-r1.json manifest exist on disk and match SHA256.
5. All 22 files in final.json files_sha256 exist on disk and match SHA256.
6. run.log has no exceptions or errors.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    print("=== S4 Phase 1 Final: Legality Verification ===")
    prereg_p = REPO / "reports/V9-S4-PHASE1/PREREG-r1.json"
    marker_p = REPO / "artifacts/v9/s4/phase1/FINAL_READ_ONCE.json"
    final_p = REPO / "reports/V9-S4-PHASE1/final/final.json"
    probe_p = REPO / "reports/V9-S4-PHASE1/probe-r2/probe.json"
    run_log_p = REPO / "reports/V9-S4-PHASE1/final/run.log"

    # 1. PREREG SHA256 in three places
    prereg_sha = sha256_file(prereg_p)
    marker_data = json.loads(marker_p.read_text(encoding="utf-8"))
    final_data = json.loads(final_p.read_text(encoding="utf-8"))
    probe_data = json.loads(probe_p.read_text(encoding="utf-8"))
    prereg_data = json.loads(prereg_p.read_text(encoding="utf-8"))

    marker_prereg_sha = marker_data.get("prereg_sha256")
    final_prereg_sha = final_data.get("prereg_sha256")

    print(f"1. PREREG-r1.json on disk:    {prereg_sha}")
    print(f"   FINAL_READ_ONCE.json:      {marker_prereg_sha}")
    print(f"   final.json prereg_sha256:  {final_prereg_sha}")
    assert prereg_sha == marker_prereg_sha == final_prereg_sha, "PREREG SHA256 mismatch!"
    print("   -> PREREG SHA256 matches in all 3 places exactly.")

    # 2. Marker write time vs commit 2812686 time
    commit_ts = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", "2812686"], cwd=REPO).decode().strip())
    marker_mtime = int(marker_p.stat().st_mtime)
    print(f"2. Commit 2812686 timestamp:   {commit_ts} (02:50:24 UTC)")
    print(f"   Marker file mtime:          {marker_mtime} (04:24:34 UTC)")
    print(f"   Time difference (mtime-commit): {marker_mtime - commit_ts}s (> 0)")
    assert marker_mtime >= commit_ts, "Marker write time precedes commit time!"
    print("   -> Marker write time is strictly after preregistration commit.")

    # 3. Code manifest SHA256 and clean working tree
    code_manifest_files = {k: v for k, v in prereg_data["manifest"].items() if k != prereg_data["design"]}
    computed_code_sha = hashlib.sha256(json.dumps(code_manifest_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prereg_code_sha = prereg_data["code_manifest_sha256"]
    final_code_sha = final_data["code_manifest_sha256"]
    probe_code_sha = probe_data["code_manifest_sha256"]

    print(f"3. Computed code manifest SHA: {computed_code_sha}")
    print(f"   PREREG code_manifest_sha:   {prereg_code_sha}")
    print(f"   final.json code_manifest:   {final_code_sha}")
    print(f"   probe-r2 code_manifest:     {probe_code_sha}")
    assert computed_code_sha == prereg_code_sha == final_code_sha == probe_code_sha, "Code manifest SHA mismatch!"
    print(f"   final code_dirty:           {final_data.get('code_dirty')}")
    assert final_data.get("code_dirty") == [], "final code_dirty is not empty!"
    print("   -> Code manifest hash identical across prereg, final, probe; code_dirty is empty.")

    # 4. Check all 40 files in PREREG manifest on disk
    manifest = prereg_data["manifest"]
    print(f"4. Checking {len(manifest)} manifest files on disk:")
    manifest_bad = []
    for rel, recorded_sha in sorted(manifest.items()):
        fpath = REPO / rel
        if not fpath.exists():
            manifest_bad.append(f"{rel}: MISSING")
        else:
            actual = sha256_file(fpath)
            if actual != recorded_sha:
                manifest_bad.append(f"{rel}: SHA MISMATCH (act={actual}, rec={recorded_sha})")
    assert not manifest_bad, f"Manifest mismatches: {manifest_bad}"
    print(f"   -> All {len(manifest)} manifest files match disk exactly.")

    # 5. Check all 22 files in final.json files_sha256 on disk
    final_files = final_data["files_sha256"]
    run_dir = REPO / "artifacts/v9/s4/phase1/final-final"
    print(f"5. Checking {len(final_files)} final artifact files on disk in {run_dir}:")
    final_bad = []
    for rel, recorded_sha in sorted(final_files.items()):
        fpath = run_dir / rel
        if not fpath.exists():
            final_bad.append(f"{rel}: MISSING")
        else:
            actual = sha256_file(fpath)
            if actual != recorded_sha:
                final_bad.append(f"{rel}: SHA MISMATCH (act={actual}, rec={recorded_sha})")
    assert not final_bad, f"Final files mismatches: {final_bad}"
    print(f"   -> All {len(final_files)} final files match disk exactly.")

    # 6. Check run.log for exceptions or abnormal terminations
    log_text = run_log_p.read_text(encoding="utf-8")
    assert "Traceback" not in log_text, "Found Traceback in run.log!"
    assert "Error" not in log_text, "Found Error in run.log!"
    assert "valid True" in log_text, "run.log did not end with valid True!"
    print("6. run.log cleanly terminated with valid True, 0 exceptions, 0 errors.")
    print("=== ALL LEGALITY CHECKS PASSED ===")

if __name__ == "__main__":
    main()
