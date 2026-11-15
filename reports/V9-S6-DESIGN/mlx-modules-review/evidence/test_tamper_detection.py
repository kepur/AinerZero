#!/usr/bin/env python3
"""Evidence 2: Test tamper detection during replay & retraining before reading test partition.

Tests three forms of tampering on the smoke set in an isolated throwaway fake repo:
1. Weight tampering: alter a byte in a cell's safetensors weight file.
2. Selection tampering: change the recorded picks in cell.json.
3. Candidate pool tampering: alter pool digest / pool seed in pools.json.

Asserts that in all 3 cases, eval detects the tampering during independent_verify
and halts immediately without reading the test partition (no errors.npz created).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
HERE = "reports/V9-S6-PHASE1"
FILES = (f"{HERE}/run_s6p1.py", f"{HERE}/verify_s6p1.py")


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def make_clean_smoke_repo(tmp: Path) -> Path:
    r = tmp / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (r / HERE).mkdir(parents=True)
    for f in FILES:
        shutil.copy2(REPO / f, r / f)
    (r / "artifacts/locks").mkdir(parents=True)
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "fake")
    return r


def run_cmd(root, *args, check=True):
    r = subprocess.run([sys.executable, "-I", str(root / HERE / "run_s6p1.py"), *args], cwd=root,
                       capture_output=True, text=True, timeout=1800)
    if check and r.returncode != 0:
        raise AssertionError(f"Command failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def main():
    tmp_base = Path("/tmp/s6_tamper_test")
    if tmp_base.exists():
        shutil.rmtree(tmp_base)
    tmp_base.mkdir(parents=True)

    print("Step 1: Setting up isolated repo and running baseline smoke train...")
    root = make_clean_smoke_repo(tmp_base / "base")
    run_cmd(root, "train", "--set", "smoke")
    print("Baseline smoke training completed.")

    # 1. Weight tampering
    print("\n--- Test 2.1: Weight tampering ---")
    clone_wt = tmp_base / "tamper_wt"
    shutil.copytree(root, clone_wt)
    target_wt = clone_wt / "artifacts/v9/s6/phase1/smoke/cells/E-r0/r0-n1.safetensors"
    data = bytearray(target_wt.read_bytes())
    data[-1] ^= 0x01
    target_wt.write_bytes(data)

    rep1 = clone_wt / "report_wt.json"
    r1 = run_cmd(clone_wt, "eval", "--set", "smoke", "--report", str(rep1), check=False)
    print(f"Eval exit code: {r1.returncode}")
    print(f"Eval output stderr/stdout excerpt: {(r1.stderr or r1.stdout)[-300:].strip()}")
    assert r1.returncode != 0, "Eval should have failed on weight tampering!"
    test_errs1 = clone_wt / "artifacts/v9/s6/phase1/smoke/eval-s6t-smoke-test/errors.npz"
    assert not test_errs1.exists(), "Test partition errors.npz must NOT be created!"
    print("OK: Weight tampering stopped evaluation before test partition was touched.")

    # 2. Selection tampering
    print("\n--- Test 2.2: Selection tampering ---")
    clone_sel = tmp_base / "tamper_sel"
    shutil.copytree(root, clone_sel)
    rec_path = clone_sel / "artifacts/v9/s6/phase1/smoke/cells/E-r0/cell.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    # Reverse picks of round 1
    rec["tracks"][0]["picks"][1] = rec["tracks"][0]["picks"][1][::-1]
    rec["tracks"][0]["reveal_log"][1]["ids"] = rec["tracks"][0]["picks"][1]
    rec["tracks"][0]["revealed"] = [i for p in rec["tracks"][0]["picks"] for i in p]
    # Update files_sha256 of cell.json itself isn't in files_sha256 (only safetensors are),
    # but recompute the sha dict if needed
    rec_path.write_text(json.dumps(rec, sort_keys=True), encoding="utf-8")

    rep2 = clone_sel / "report_sel.json"
    r2 = run_cmd(clone_sel, "eval", "--set", "smoke", "--report", str(rep2), check=False)
    print(f"Eval exit code: {r2.returncode}")
    assert rep2.is_file(), "Report file should be generated with failure status"
    R2 = json.loads(rep2.read_text(encoding="utf-8"))
    print("Verification result:", R2.get("verify", {}).get("passed"))
    print("E-r0 replay result:", R2.get("verify", {}).get("replay", {}).get("E-r0", {}).get("passed"))
    assert not R2["verify"]["passed"], "Replay verification must fail on tampered selection!"
    assert not R2["verify"]["replay"]["E-r0"]["passed"]
    assert R2["result"]["valid"] is False
    test_errs2 = clone_sel / "artifacts/v9/s6/phase1/smoke/eval-s6t-smoke-test/errors.npz"
    assert not test_errs2.exists(), "Test partition errors.npz must NOT be created!"
    print("OK: Selection tampering caught by replay; eval halted before test partition.")

    # 3. Candidate pool tampering
    print("\n--- Test 2.3: Candidate pool tampering ---")
    clone_pool = tmp_base / "tamper_pool"
    shutil.copytree(root, clone_pool)
    pools_path = clone_pool / "artifacts/v9/s6/phase1/smoke/pools.json"
    pools = json.loads(pools_path.read_text(encoding="utf-8"))
    # Corrupt digest for replicate 0
    pools["0"] = "deadbeef" * 8
    pools_path.write_text(json.dumps(pools, indent=1), encoding="utf-8")

    rep3 = clone_pool / "report_pool.json"
    r3 = run_cmd(clone_pool, "eval", "--set", "smoke", "--report", str(rep3), check=False)
    print(f"Eval exit code: {r3.returncode}")
    assert rep3.is_file(), "Report file should be generated with failure status"
    R3 = json.loads(rep3.read_text(encoding="utf-8"))
    print("Pools verification result:", R3.get("verify", {}).get("pools_ok"))
    assert not R3["verify"]["passed"], "Pools verification must fail on tampered pool digest!"
    assert R3["verify"]["pools_ok"]["0"] is False
    assert R3["result"]["valid"] is False
    test_errs3 = clone_pool / "artifacts/v9/s6/phase1/smoke/eval-s6t-smoke-test/errors.npz"
    assert not test_errs3.exists(), "Test partition errors.npz must NOT be created!"
    print("OK: Pool digest tampering caught; eval halted before test partition.")

    print("\nALL TAMPER DETECTION TESTS PASSED!")


if __name__ == "__main__":
    main()
