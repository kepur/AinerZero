#!/usr/bin/env python3
"""Isolated bad control experiments for V9.P158."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REPO_ROOT / "reports" / "V9-S2-P158"
SANDBOX = Path("/tmp/ainerzero_p158_bad_control")


def sha256_of_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== S2 Pre-Registration Bad Control Experiment (P158) ===")
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

    spec_path = SANDBOX / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "spec.py"
    prereg_path = SANDBOX / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "prereg.py"

    initial_spec_sha = sha256_of_file(spec_path)
    initial_prereg_sha = sha256_of_file(prereg_path)

    results = {}

    # --- P158-M1: dev 与 final 命名空间相同 ---
    print("\n--- Running P158-M1: dev 与 final 命名空间相同 ---")
    spec_text = spec_path.read_text(encoding="utf-8")
    assert '"final": "s2p1-final-v1"' in spec_text
    m1_spec_text = spec_text.replace('"final": "s2p1-final-v1"', '"final": "s2p1-dev-v1"')
    spec_path.write_text(m1_spec_text, encoding="utf-8")

    m1_cmd = [
        python_bin, "-m", "pytest",
        "tests/v9/experiments/test_s2_prereg.py::test_build_draft_and_validate_clean",
        "tests/v9/experiments/test_s2_spec.py::test_appendix_c_constants_match_design_document",
        "-v"
    ]
    p_m1 = subprocess.run(m1_cmd, cwd=str(SANDBOX), env=env, capture_output=True, text=True)
    print(f"P158-M1 returncode: {p_m1.returncode} (expected non-zero / RED)")
    print(p_m1.stdout.strip())

    spec_path.write_text(spec_text, encoding="utf-8")
    restored_spec_sha = sha256_of_file(spec_path)
    assert restored_spec_sha == initial_spec_sha, "Spec SHA mismatch on restore!"
    print("Spec restored and verified.")

    results["P158-M1"] = {
        "description": "dev 与 final 命名空间相同（spec.SEED_NAMESPACES['final'] = 's2p1-dev-v1'）",
        "exit_code": p_m1.returncode,
        "status": "RED (CONFIRMED)" if p_m1.returncode != 0 else "FAIL_TO_CATCH",
        "output_summary": [l for l in p_m1.stdout.splitlines() if "FAILED" in l or "ERROR" in l]
    }

    # --- P158-M2: validate 去掉数据预算估算 ---
    print("\n--- Running P158-M2: validate 去掉数据预算估算 ---")
    prereg_text = prereg_path.read_text(encoding="utf-8")
    target_budget_block = (
        "    estimated_data_seconds = train_n_worlds * train_episodes_per_world * float(est_sec)\n"
        "    data_budget_seconds = spec.BUDGET_DATA_MAX_SECONDS\n"
        "    if estimated_data_seconds > data_budget_seconds:\n"
        "        raise SpecValidationError(\n"
        '            f"Estimated train data generation time ({estimated_data_seconds:.1f} s) "\n'
        '            f"exceeds data budget ({data_budget_seconds} s)"\n'
        "        )"
    )
    assert target_budget_block in prereg_text, "Target budget block not found in prereg.py"
    m2_prereg_text = prereg_text.replace(target_budget_block, "    pass  # P158-M2: omitted data budget check")
    prereg_path.write_text(m2_prereg_text, encoding="utf-8")

    m2_cmd = [
        python_bin, "-m", "pytest",
        "tests/v9/experiments/test_s2_prereg.py::test_tamper_train_scale_exceeds_data_budget_fails",
        "-v"
    ]
    p_m2 = subprocess.run(m2_cmd, cwd=str(SANDBOX), env=env, capture_output=True, text=True)
    print(f"P158-M2 returncode: {p_m2.returncode} (expected non-zero / RED)")
    print(p_m2.stdout.strip())

    prereg_path.write_text(prereg_text, encoding="utf-8")
    restored_prereg_sha = sha256_of_file(prereg_path)
    assert restored_prereg_sha == initial_prereg_sha, "Prereg SHA mismatch on restore!"
    print("Prereg restored and verified.")

    results["P158-M2"] = {
        "description": "validate 去掉数据预算估算（注释掉 estimated_data_seconds > data_budget_seconds 抛错）",
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
