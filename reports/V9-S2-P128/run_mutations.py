"""Mutation runner for S2 P128 bad controls under isolated replica directory."""

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
    replica_dir = Path("/tmp/s2_p128_mutation_replica")
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
            "print('Verified import resolves to:', s.__file__)"
        ),
    ]
    res_import = subprocess.run(check_import_cmd, capture_output=True, text=True, check=True)
    print(res_import.stdout.strip())

    # Baseline tests in replica
    print("[2] Running baseline static tests in replica...")
    pytest_bin = str(repo_root / ".venv" / "bin" / "pytest")
    env = dict(PYTHONPATH=f"{replica_dir}/src:{replica_dir}")

    cmd_baseline = [
        pytest_bin,
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_arms_static.py"),
        "-q",
    ]
    res_base = subprocess.run(cmd_baseline, capture_output=True, text=True, env=env)
    assert res_base.returncode == 0, f"Baseline failed in replica:\n{res_base.stderr}\n{res_base.stdout}"
    print("Baseline passed: 4/4 static tests passed.")

    mutations_record = []

    # --- Mutation P128-M1 ---
    # 在 arms_mlx.py 里写死一个 nn.Linear(205, 256) -> 静态宽度用例必须变红
    print("\n[3] Running P128-M1: 在 arms_mlx.py 里写死 nn.Linear(205, 256)...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "self.fc1 = nn.Linear(e1_in, e1_h)",
        "self.fc1 = nn.Linear(205, 256)  # MUTATION P128-M1: hardcoded dimensions",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for M1"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m1 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_arms_static.py::test_no_hardcoded_integer_widths_in_layer_constructors",
        "-q",
    ]
    res_m1 = subprocess.run(cmd_m1, capture_output=True, text=True, env=env)
    m1_killed = res_m1.returncode != 0
    print(f"P128-M1 exit code: {res_m1.returncode} (KILLED={m1_killed})")
    assert m1_killed, "P128-M1 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M1"

    mutations_record.append({
        "mutation_id": "P128-M1",
        "description": "在 arms_mlx.py 里写死 nn.Linear(205, 256) (hardcoded layer dimensions)",
        "target_file": "src/ainerzero/v9/experiments/s2/arms_mlx.py",
        "targeted_test": "test_no_hardcoded_integer_widths_in_layer_constructors",
        "exit_code": res_m1.returncode,
        "status": "KILLED",
        "failure_output": res_m1.stdout.strip().splitlines()[-1] if res_m1.stdout.strip() else "",
    })

    # --- Mutation P128-M2 ---
    # 在 s2/__init__.py 里加 from . import arms_mlx -> 纯 CPU 用例必须变红
    print("\n[4] Running P128-M2: 在 s2/__init__.py 里导入 arms_mlx...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "__init__.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8") + "\nfrom . import arms_mlx  # MUTATION P128-M2\n"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m2 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_arms_static.py::test_s2_package_init_does_not_import_arms_mlx",
        "-q",
    ]
    res_m2 = subprocess.run(cmd_m2, capture_output=True, text=True, env=env)
    m2_killed = res_m2.returncode != 0
    print(f"P128-M2 exit code: {res_m2.returncode} (KILLED={m2_killed})")
    assert m2_killed, "P128-M2 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M2"

    mutations_record.append({
        "mutation_id": "P128-M2",
        "description": "在 s2/__init__.py 里导入 arms_mlx (pollutes pure CPU s2 package with MLX)",
        "target_file": "src/ainerzero/v9/experiments/s2/__init__.py",
        "targeted_test": "test_s2_package_init_does_not_import_arms_mlx",
        "exit_code": res_m2.returncode,
        "status": "KILLED",
        "failure_output": res_m2.stdout.strip().splitlines()[-1] if res_m2.stdout.strip() else "",
    })

    # --- Mutation P128-M3 ---
    # 从 NATIVE_MODULES 删掉登记 -> 登记用例必须变红
    print("\n[5] Running P128-M3: 从 NATIVE_MODULES 删掉 test_s2_arms_mlx_native.py 登记...")
    target_file = replica_dir / "tests" / "conftest.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        '"test_s2_arms_mlx_native.py": "module-level import mlx.core/mlx.nn (S2 arms)",',
        '# MUTATION P128-M3: deleted registration',
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for M3"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m3 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_arms_static.py::test_native_module_registered_in_conftest_and_excluded_from_collection",
        "-q",
    ]
    res_m3 = subprocess.run(cmd_m3, capture_output=True, text=True, env=env)
    m3_killed = res_m3.returncode != 0
    print(f"P128-M3 exit code: {res_m3.returncode} (KILLED={m3_killed})")
    assert m3_killed, "P128-M3 should have failed the test!"

    # Restore byte-for-byte
    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring M3"

    mutations_record.append({
        "mutation_id": "P128-M3",
        "description": "从 NATIVE_MODULES 删掉 test_s2_arms_mlx_native.py 登记 (native test unisolated)",
        "target_file": "tests/conftest.py",
        "targeted_test": "test_native_module_registered_in_conftest_and_excluded_from_collection",
        "exit_code": res_m3.returncode,
        "status": "KILLED",
        "failure_output": res_m3.stdout.strip().splitlines()[-1] if res_m3.stdout.strip() else "",
    })

    # Cleanup replica
    shutil.rmtree(replica_dir)
    print("\n[6] Replica cleaned up. All 3 mutations killed and restored verified.")

    # Write mutations.json
    out_file = repo_root / "reports" / "V9-S2-P128" / "mutations.json"
    out_file.write_text(json.dumps(mutations_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded mutation report in {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
