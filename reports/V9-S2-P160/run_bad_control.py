#!/usr/bin/env python3
"""Isolated bad control experiments for V9.P160."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REPO_ROOT / "reports" / "V9-S2-P160"
SANDBOX = Path("/tmp/ainerzero_p160_bad_control")


def sha256_of_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== S2 Pre-Freeze Cleanup Bad Control Experiment (P160) ===")
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    print(f"Creating isolated sandbox copy in {SANDBOX}...")
    shutil.copytree(REPO_ROOT / "src", SANDBOX / "src")
    shutil.copytree(REPO_ROOT / "tests", SANDBOX / "tests")
    shutil.copy2(REPO_ROOT / "pyproject.toml", SANDBOX / "pyproject.toml")
    (SANDBOX / "reports" / "V9-S2-DESIGN").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "reports" / "V9-S2-DESIGN" / "DESIGN-r2.md", SANDBOX / "reports" / "V9-S2-DESIGN" / "DESIGN-r2.md")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SANDBOX / 'src'}:{SANDBOX}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python_bin = str(REPO_ROOT / ".venv" / "bin" / "python")

    # Verify import isolation
    check_import_cmd = [
        python_bin, "-c",
        "import ainerzero; print('Resolved ainerzero:', ainerzero.__file__)"
    ]
    p_imp = subprocess.run(check_import_cmd, cwd=str(SANDBOX), env=env, capture_output=True, text=True)
    print(p_imp.stdout.strip())
    assert str(SANDBOX / "src") in p_imp.stdout, f"Import did not resolve to sandbox! {p_imp.stdout}"

    smoke_path = SANDBOX / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke.py"
    smoke_checks_path = SANDBOX / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke_checks.py"

    initial_smoke_sha = sha256_of_file(smoke_path)
    initial_smoke_checks_sha = sha256_of_file(smoke_checks_path)

    results = {}

    # --- P160-M1: 恢复一处 getattr 默认值 ---
    print("\n--- Running P160-M1: 恢复一处 getattr 默认值 ---")
    smoke_text = smoke_path.read_text(encoding="utf-8")
    assert "total_short_steps = spec.SMOKE_SHORT_TRAIN_STEPS" in smoke_text
    m1_smoke_text = smoke_text.replace(
        "total_short_steps = spec.SMOKE_SHORT_TRAIN_STEPS",
        'total_short_steps = getattr(spec, "SMOKE_SHORT_STEPS", 200)'
    )
    smoke_path.write_text(m1_smoke_text, encoding="utf-8")

    m1_cmd = [
        python_bin, "-m", "pytest",
        "tests/v9/experiments/test_s2_wiring.py::test_no_getattr_spec_with_default_in_s2_package",
        "-v"
    ]
    p_m1 = subprocess.run(m1_cmd, cwd=str(SANDBOX), env=env, capture_output=True, text=True)
    print(f"P160-M1 returncode: {p_m1.returncode} (expected non-zero / RED)")
    print(p_m1.stdout.strip())

    smoke_path.write_text(smoke_text, encoding="utf-8")
    restored_smoke_sha = sha256_of_file(smoke_path)
    assert restored_smoke_sha == initial_smoke_sha, "smoke.py SHA mismatch on restore!"
    print("smoke.py restored and verified.")

    results["P160-M1"] = {
        "description": "恢复一处 getattr(spec, 'SMOKE_SHORT_STEPS', 200) 默认值",
        "exit_code": p_m1.returncode,
        "status": "RED (CONFIRMED)" if p_m1.returncode != 0 else "FAIL_TO_CATCH",
        "output_summary": [l for l in p_m1.stdout.splitlines() if "FAILED" in l or "ERROR" in l]
    }

    # --- P160-M2: 恢复 bfs_distance 默认 40 ---
    print("\n--- Running P160-M2: 恢复 bfs_distance 默认 40 ---")
    checks_text = smoke_checks_path.read_text(encoding="utf-8")
    target_block = (
        '        bfs_dist_raw = spec_data.get("bfs_distance") if isinstance(spec_data, Mapping) else getattr(spec_data, "bfs_distance", None)\n'
        '        if bfs_dist_raw is None:\n'
        '            raise ValueError(f"Missing bfs_distance in episode spec {idx}")\n'
        '        bfs_dist = int(bfs_dist_raw)'
    )
    assert target_block in checks_text, "Target bfs_distance check block not found in smoke_checks.py"
    reverted_block = (
        '        bfs_dist = int(spec_data.get("bfs_distance", 40) if isinstance(spec_data, Mapping) else getattr(spec_data, "bfs_distance", 40))'
    )
    m2_checks_text = checks_text.replace(target_block, reverted_block)
    smoke_checks_path.write_text(m2_checks_text, encoding="utf-8")

    m2_cmd = [
        python_bin, "-m", "pytest",
        "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_missing_bfs_distance_raises",
        "-v"
    ]
    p_m2 = subprocess.run(m2_cmd, cwd=str(SANDBOX), env=env, capture_output=True, text=True)
    print(f"P160-M2 returncode: {p_m2.returncode} (expected non-zero / RED)")
    print(p_m2.stdout.strip())

    smoke_checks_path.write_text(checks_text, encoding="utf-8")
    restored_checks_sha = sha256_of_file(smoke_checks_path)
    assert restored_checks_sha == initial_smoke_checks_sha, "smoke_checks.py SHA mismatch on restore!"
    print("smoke_checks.py restored and verified.")

    results["P160-M2"] = {
        "description": "恢复 bfs_distance 默认 40（缺字段不再报错）",
        "exit_code": p_m2.returncode,
        "status": "RED (CONFIRMED)" if p_m2.returncode != 0 else "FAIL_TO_CATCH",
        "output_summary": [l for l in p_m2.stdout.splitlines() if "FAILED" in l or "ERROR" in l]
    }

    # Clean up sandbox
    shutil.rmtree(SANDBOX)

    summary_file = REPORT_DIR / "bad_control_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved bad control summary to {summary_file}")


if __name__ == "__main__":
    main()
