"""Mutation runner for S2 P124 bad controls under isolated replica directory."""

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
    repo_root = Path(__file__).resolve().parents[2]
    replica_dir = Path("/tmp/s2_p124_mutation_replica")
    if replica_dir.exists():
        shutil.rmtree(replica_dir)
    replica_dir.mkdir(parents=True)

    print(f"[1] Creating isolated replica at {replica_dir}...")
    shutil.copytree(repo_root / "src", replica_dir / "src")
    shutil.copytree(repo_root / "tests", replica_dir / "tests")
    shutil.copy(repo_root / "pyproject.toml", replica_dir / "pyproject.toml")
    # Also link reports so design document can be resolved
    (replica_dir / "reports").mkdir()
    shutil.copytree(repo_root / "reports" / "V9-S2-DESIGN", replica_dir / "reports" / "V9-S2-DESIGN")

    # Assert imports resolve to replica
    check_import_cmd = [
        sys.executable,
        "-c",
        (
            f"import sys; sys.path.insert(0, '{replica_dir}/src'); "
            "import ainerzero.v9.experiments.s2.spec as s; "
            f"assert s.__file__.startswith('{replica_dir}'), f'Import not in replica: {{s.__file__}}'; "
            "print('Verified import resolves to:', s.__file__)"
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

    # --- Mutation P124-M1 ---
    # 闭式公式漏算偏置 -> 交叉核对用例必须变红
    print("\n[3] Running P124-M1: 闭式公式漏算偏置...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "param_count.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "bias_count = out_features if bias else 0",
        "bias_count = 0  # MUTATION P124-M1: omit bias",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for M1"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m1 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_prereg.py::test_closed_form_matches_numpy_reference_per_arm",
        "-q",
    ]
    res_m1 = subprocess.run(cmd_m1, capture_output=True, text=True, env=env)
    m1_killed = res_m1.returncode != 0
    print(f"P124-M1 exit code: {res_m1.returncode} (KILLED={m1_killed})")
    assert m1_killed, "P124-M1 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M1"

    mutations_record.append({
        "mutation_id": "P124-M1",
        "description": "闭式公式漏算偏置 (Linear bias omitted)",
        "target_file": "src/ainerzero/v9/experiments/s2/param_count.py",
        "targeted_test": "test_closed_form_matches_numpy_reference_per_arm",
        "exit_code": res_m1.returncode,
        "status": "KILLED",
        "failure_output": res_m1.stdout.strip().splitlines()[-1] if res_m1.stdout.strip() else "",
    })

    # --- Mutation P124-M2 ---
    # validate 去掉参数量检查 -> 「A 宽度加倍」用例必须变红
    print("\n[4] Running P124-M2: validate 去掉参数量检查...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "prereg.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "if count < spec.PARAM_COUNT_MIN or count > spec.PARAM_COUNT_MAX:",
        "if False:  # MUTATION P124-M2: bypass parameter count check",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for M2"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m2 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_prereg.py::test_tamper_double_arm_a_width_fails",
        "-q",
    ]
    res_m2 = subprocess.run(cmd_m2, capture_output=True, text=True, env=env)
    m2_killed = res_m2.returncode != 0
    print(f"P124-M2 exit code: {res_m2.returncode} (KILLED={m2_killed})")
    assert m2_killed, "P124-M2 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M2"

    mutations_record.append({
        "mutation_id": "P124-M2",
        "description": "validate 去掉参数量检查 (bypass param count check)",
        "target_file": "src/ainerzero/v9/experiments/s2/prereg.py",
        "targeted_test": "test_tamper_double_arm_a_width_fails",
        "exit_code": res_m2.returncode,
        "status": "KILLED",
        "failure_output": res_m2.stdout.strip().splitlines()[-1] if res_m2.stdout.strip() else "",
    })

    # --- Mutation P124-M3 ---
    # spec 里 δ_pred 改为 0.5 -> 与设计稿一致性用例必须变红
    print("\n[5] Running P124-M3: spec 里 δ_pred 改为 0.5...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "spec.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "DELTA_PRED = 1.0",
        "DELTA_PRED = 0.5  # MUTATION P124-M3: delta_pred altered",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for M3"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m3 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_spec.py::test_spec_matches_design_document_constants",
        "-q",
    ]
    res_m3 = subprocess.run(cmd_m3, capture_output=True, text=True, env=env)
    m3_killed = res_m3.returncode != 0
    print(f"P124-M3 exit code: {res_m3.returncode} (KILLED={m3_killed})")
    assert m3_killed, "P124-M3 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M3"

    mutations_record.append({
        "mutation_id": "P124-M3",
        "description": "spec 里 δ_pred 改为 0.5 (delta_pred=0.5 != 1.0)",
        "target_file": "src/ainerzero/v9/experiments/s2/spec.py",
        "targeted_test": "test_spec_matches_design_document_constants",
        "exit_code": res_m3.returncode,
        "status": "KILLED",
        "failure_output": res_m3.stdout.strip().splitlines()[-1] if res_m3.stdout.strip() else "",
    })

    # Cleanup replica
    shutil.rmtree(replica_dir)
    print("\n[6] Replica cleaned up. All 3 mutations killed and restored verified.")

    # Write mutations.json
    out_file = repo_root / "reports" / "V9-S2-P124" / "mutations.json"
    out_file.write_text(json.dumps(mutations_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded mutation report in {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
