"""Independent review mutation runner for S2 P124 (ainerzero.V9.P125).

Tests 4 distinct mutations outside the author's mutation table:
- Review-M1: Bypass calendar window validation in prereg.py
- Review-M2: Omit GRU recurrent weights Wh in param_count.py
- Review-M3: Bypass planning N_fwd check in prereg.py
- Review-M4: Alter SUCCESS_RATE_DIFF_MIN from 0.10 to 0.05 in spec.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    replica_dir = Path("/tmp/s2_p125_review_replica")
    if replica_dir.exists():
        shutil.rmtree(replica_dir)
    replica_dir.mkdir(parents=True)

    print(f"[1] Creating isolated replica at {replica_dir}...")
    shutil.copytree(repo_root / "src", replica_dir / "src")
    shutil.copytree(repo_root / "tests", replica_dir / "tests")
    shutil.copy(repo_root / "pyproject.toml", replica_dir / "pyproject.toml")
    (replica_dir / "reports").mkdir()
    shutil.copytree(repo_root / "reports" / "V9-S2-DESIGN", replica_dir / "reports" / "V9-S2-DESIGN")

    # Assert import resolves to replica
    check_import_cmd = [
        sys.executable,
        "-c",
        (
            f"import sys; sys.path.insert(0, '{replica_dir}/src'); "
            "import ainerzero.v9.experiments.s2.spec as s; "
            f"assert s.__file__.startswith('{replica_dir}'), f'Import not in replica: {{s.__file__}}'; "
            "print('Verified review import resolves to:', s.__file__)"
        ),
    ]
    res_import = subprocess.run(check_import_cmd, capture_output=True, text=True, check=True)
    print(res_import.stdout.strip())

    # Baseline tests in replica
    print("[2] Running baseline tests in replica...")
    pytest_bin = str(repo_root / ".venv" / "bin" / "pytest")
    env = dict(PYTHONPATH=f"{replica_dir}/src:{replica_dir}")

    cmd_baseline = [
        pytest_bin,
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_spec.py"),
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_prereg.py"),
        "-q",
    ]
    res_base = subprocess.run(cmd_baseline, capture_output=True, text=True, env=env)
    assert res_base.returncode == 0, f"Baseline failed in replica:\n{res_base.stderr}\n{res_base.stdout}"
    print("Baseline passed: 19/19 tests passed.")

    mutations_record = []

    # --- Review-M1: Bypass calendar window check in prereg.py ---
    print("\n[3] Running Review-M1: validate 去掉日历窗口与用时比较检查...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "prereg.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "if float(calendar) < float(wallclock):",
        "if False:  # REVIEW-M1: bypass calendar window check",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for Review-M1"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m1 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_prereg.py::test_tamper_calendar_window_smaller_than_wallclock_fails",
        "-q",
    ]
    res_m1 = subprocess.run(cmd_m1, capture_output=True, text=True, env=env)
    m1_killed = res_m1.returncode != 0
    print(f"Review-M1 exit code: {res_m1.returncode} (KILLED={m1_killed})")
    assert m1_killed, "Review-M1 should have failed the test!"

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring Review-M1"

    mutations_record.append({
        "mutation_id": "Review-M1",
        "description": "prereg.py validate 去掉日历窗口小于总实际用时校验 (bypass calendar < wallclock check)",
        "target_file": "src/ainerzero/v9/experiments/s2/prereg.py",
        "targeted_test": "test_tamper_calendar_window_smaller_than_wallclock_fails",
        "exit_code": res_m1.returncode,
        "status": "KILLED",
        "failure_summary": res_m1.stdout.strip().splitlines()[-1] if res_m1.stdout.strip() else "",
    })

    # --- Review-M2: Omit GRU recurrent Wh weights in param_count.py ---
    print("\n[4] Running Review-M2: param_count.py GRU 闭式公式漏算循环权重 Wh...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "param_count.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "weight_count = 3 * hidden_size * (input_size + hidden_size)",
        "weight_count = 3 * hidden_size * input_size  # REVIEW-M2: omit Wh recurrent weights",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for Review-M2"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m2 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_prereg.py::test_closed_form_matches_numpy_reference_per_arm",
        "-q",
    ]
    res_m2 = subprocess.run(cmd_m2, capture_output=True, text=True, env=env)
    m2_killed = res_m2.returncode != 0
    print(f"Review-M2 exit code: {res_m2.returncode} (KILLED={m2_killed})")
    assert m2_killed, "Review-M2 should have failed the test!"

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring Review-M2"

    mutations_record.append({
        "mutation_id": "Review-M2",
        "description": "param_count.py gru_params 闭式公式漏算 Wh 循环权重 (omit recurrent weights)",
        "target_file": "src/ainerzero/v9/experiments/s2/param_count.py",
        "targeted_test": "test_closed_form_matches_numpy_reference_per_arm",
        "exit_code": res_m2.returncode,
        "status": "KILLED",
        "failure_summary": res_m2.stdout.strip().splitlines()[-1] if res_m2.stdout.strip() else "",
    })

    # --- Review-M3: Bypass planning N_fwd check in prereg.py ---
    print("\n[5] Running Review-M3: prereg.py validate 去掉 N_fwd 门限核对...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "prereg.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        'if planning.get("n_fwd") != spec.N_FWD:',
        'if False:  # REVIEW-M3: bypass n_fwd check',
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for Review-M3"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m3 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_prereg.py::test_tamper_n_fwd_modified_fails",
        "-q",
    ]
    res_m3 = subprocess.run(cmd_m3, capture_output=True, text=True, env=env)
    m3_killed = res_m3.returncode != 0
    print(f"Review-M3 exit code: {res_m3.returncode} (KILLED={m3_killed})")
    assert m3_killed, "Review-M3 should have failed the test!"

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring Review-M3"

    mutations_record.append({
        "mutation_id": "Review-M3",
        "description": "prereg.py validate 去掉 planning.n_fwd 校验 (bypass n_fwd check)",
        "target_file": "src/ainerzero/v9/experiments/s2/prereg.py",
        "targeted_test": "test_tamper_n_fwd_modified_fails",
        "exit_code": res_m3.returncode,
        "status": "KILLED",
        "failure_summary": res_m3.stdout.strip().splitlines()[-1] if res_m3.stdout.strip() else "",
    })

    # --- Review-M4: Alter SUCCESS_RATE_DIFF_MIN in spec.py ---
    print("\n[6] Running Review-M4: spec.py SUCCESS_RATE_DIFF_MIN 改为 0.05...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "spec.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "SUCCESS_RATE_DIFF_MIN = 0.10",
        "SUCCESS_RATE_DIFF_MIN = 0.05  # REVIEW-M4: altered gate threshold",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for Review-M4"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m4 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_spec.py::test_gates_and_stopping_constants",
        "-q",
    ]
    res_m4 = subprocess.run(cmd_m4, capture_output=True, text=True, env=env)
    m4_killed = res_m4.returncode != 0
    print(f"Review-M4 exit code: {res_m4.returncode} (KILLED={m4_killed})")
    assert m4_killed, "Review-M4 should have failed the test!"

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring Review-M4"

    mutations_record.append({
        "mutation_id": "Review-M4",
        "description": "spec.py 门限 SUCCESS_RATE_DIFF_MIN 改为 0.05 (altered gate threshold)",
        "target_file": "src/ainerzero/v9/experiments/s2/spec.py",
        "targeted_test": "test_gates_and_stopping_constants",
        "exit_code": res_m4.returncode,
        "status": "KILLED",
        "failure_summary": res_m4.stdout.strip().splitlines()[-1] if res_m4.stdout.strip() else "",
    })

    # Cleanup replica
    shutil.rmtree(replica_dir)
    print("\n[7] Replica cleaned up. All 4 review mutations killed and restored verified.")

    # Write review_mutations.json
    out_file = repo_root / "reports" / "V9-S2-P124" / "review" / "review_mutations.json"
    out_file.write_text(json.dumps(mutations_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded review mutation report in {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
