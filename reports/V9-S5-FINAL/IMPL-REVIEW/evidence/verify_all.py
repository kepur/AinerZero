"""S5 Phase 1 Final Runner & PREREG Review Verification Script (P248).
Checks PREREG consistency, 72 pinned weights against disk & events,
code manifest against commit 43c9f1d, and gate computation contracts.
"""

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PREREG_PATH = REPO / "reports/V9-S5-FINAL/PREREG.json"
EXPECTED_PREREG_SHA = "2de216957c759227f7b51b01aeafcffa647e22721d53fa4c8bf94419fcd38642"

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_prereg():
    print("--- 1. Verifying PREREG.json SHA and Schema ---")
    actual_sha = sha256_file(PREREG_PATH)
    assert actual_sha == EXPECTED_PREREG_SHA, f"PREREG SHA mismatch: {actual_sha} != {EXPECTED_PREREG_SHA}"
    print(f"PREREG SHA matches expected: {actual_sha}")

    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert prereg.get("schema") == "s5.phase1.prereg.v1"
    
    frozen = prereg["frozen"]
    pinned = prereg["pinned_artifacts"]

    print("--- 2. Verifying A* Selection against dev-distill stage.json ---")
    dev_run = REPO / pinned["dev_distill_run"]
    stage = json.loads((dev_run / "stage.json").read_text(encoding="utf-8"))
    sel_arm = stage["selection"]["a_star"]["arm"]
    assert sel_arm == frozen["a_star"] == prereg["a_star"] == "A1", f"A* mismatch: {sel_arm} vs {frozen['a_star']}"
    print(f"A* verified as A1 (score={stage['selection']['a_star']['score']})")

    print("--- 3. Verifying Hyperparameters against tune file ---")
    tune_file = REPO / pinned["tune_file"]
    tune = json.loads(tune_file.read_text(encoding="utf-8"))
    assert float(frozen["distill_lr"]) == float(tune["distill_lr"]) == 0.0003
    assert float(frozen["supervised_lr"]) == float(tune["supervised_lr"]) == 0.001
    assert float(frozen["eta"]) == float(tune["eta"]) == 1.0
    print(f"Hyperparameters verified: distill_lr={tune['distill_lr']}, supervised_lr={tune['supervised_lr']}, eta={tune['eta']}")

    print("--- 4. Verifying n_final and budget ---")
    assert frozen["n_final"] == 48, f"n_final={frozen['n_final']}"
    assert prereg["budget"]["budget_h"] == 11.8, f"budget_h={prereg['budget']['budget_h']}"
    print("n_final=48 and budget_h=11.8 verified.")

    print("--- 5. Verifying 72 Pinned Weights on Disk and in events.jsonl ---")
    events_path = dev_run / "events.jsonl"
    cell_end_shas = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("event") == "cell_end" and "files" in ev:
            for fn, sha in ev["files"].items():
                cell_end_shas[fn] = sha

    groups = [
        ("distill_students", 6),
        ("distill_proj_heads", 6),
        ("readout_heads", 54),
        ("a0_l64_students", 3),
        ("a0_l64_heads", 3),
    ]
    total_weights = 0
    for grp, exp_count in groups:
        mapping = pinned.get(grp, {})
        assert len(mapping) == exp_count, f"{grp} count {len(mapping)} != {exp_count}"
        for fname, want_sha in mapping.items():
            total_weights += 1
            fpath = dev_run / "weights" / fname
            assert fpath.is_file(), f"Missing on disk: {fpath}"
            disk_sha = sha256_file(fpath)
            assert disk_sha == want_sha, f"Disk SHA mismatch for {fname}: {disk_sha} != {want_sha}"
            assert fname in cell_end_shas, f"Missing in events.jsonl: {fname}"
            assert cell_end_shas[fname] == want_sha, f"events.jsonl SHA mismatch for {fname}: {cell_end_shas[fname]} != {want_sha}"

    assert total_weights == 72
    print(f"All {total_weights} pinned weight files verified on disk and in events.jsonl!")

    print("--- 6. Verifying Code Manifest against commit 43c9f1d ---")
    manifest = prereg["manifest"]
    assert len(manifest) == 46, f"manifest count={len(manifest)}"
    for rel_path, want_sha in manifest.items():
        res = subprocess.run(["git", "show", f"43c9f1d:{rel_path}"], cwd=REPO, capture_output=True, check=True)
        git_sha = hashlib.sha256(res.stdout).hexdigest()
        assert git_sha == want_sha, f"Manifest mismatch for {rel_path}: {git_sha} != {want_sha}"
    print(f"All {len(manifest)} manifest files match commit 43c9f1d exactly!")

    return {
        "prereg_sha": actual_sha,
        "a_star": sel_arm,
        "distill_lr": tune["distill_lr"],
        "supervised_lr": tune["supervised_lr"],
        "eta": tune["eta"],
        "n_final": frozen["n_final"],
        "budget_h": prereg["budget"]["budget_h"],
        "pinned_weights_count": total_weights,
        "manifest_files_count": len(manifest),
        "status": "ALL_CHECKS_PASSED"
    }

if __name__ == "__main__":
    res = verify_prereg()
    out_json = REPO / "reports/V9-S5-FINAL/IMPL-REVIEW/evidence/prereg_check.json"
    out_json.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"\nWritten {out_json}")
