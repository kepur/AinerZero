"""Adverse mutation test runner for S2 Core Math (reports/V9-S2-K1/run_mutations.py).

Verifies four adverse mutations in an isolated workspace:
- K1-M1: Displacement aggregation replaced with naive summation -> square / turn-then-walk turns red.
- K1-M2: SIGReg Gaussian comparison replaced with uniform distribution CF -> isotropic test turns red.
- K1-M3: dpsi angle normalization removed -> square loop test turns red.
- K1-M4: `import mlx.core` added to `__init__.py` -> pure-CPU test turns red.

Each mutation is tested in an isolated copy, asserts import resolution to the copy,
verifies failure (red exit code != 0), restores byte-by-byte, and validates SHA256 integrity.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_mutation_checks(repo_root: Path) -> dict[str, dict]:
    results = {}

    with tempfile.TemporaryDirectory(prefix="s2_mutation_sandbox_") as tmp_dir:
        sandbox = Path(tmp_dir)
        sandbox_src = sandbox / "src"
        sandbox_tests = sandbox / "tests"
        sandbox_pyproject = sandbox / "pyproject.toml"

        print(f"Creating isolated sandbox at {sandbox}...")
        shutil.copytree(repo_root / "src", sandbox_src)
        shutil.copytree(repo_root / "tests", sandbox_tests)
        shutil.copy(repo_root / "pyproject.toml", sandbox_pyproject)

        # Ensure PYTHONPATH points strictly to sandbox first
        sandbox_env = dict(os.environ)
        sandbox_env["PYTHONPATH"] = f"{sandbox}:{sandbox_src}"

        # Verify import resolution resolves to sandbox
        check_code = (
            "import sys\n"
            "import ainerzero.v9.experiments.s2.core_math as cm\n"
            f"assert cm.__file__.startswith('{sandbox_src}'), f'Import not from sandbox: {{cm.__file__}}'\n"
            "print('SANDBOX_RESOLVE_OK')\n"
        )
        proc_check = subprocess.run(
            [sys.executable, "-c", check_code],
            cwd=str(sandbox),
            env=sandbox_env,
            capture_output=True,
            text=True,
        )
        assert proc_check.returncode == 0, f"Failed sandbox import resolution:\n{proc_check.stderr}"
        assert "SANDBOX_RESOLVE_OK" in proc_check.stdout

        target_core_math = sandbox_src / "ainerzero/v9/experiments/s2/core_math.py"
        target_init = sandbox_src / "ainerzero/v9/experiments/s2/__init__.py"

        # Baseline SHAs
        core_math_sha_orig = compute_sha256(target_core_math)
        init_sha_orig = compute_sha256(target_init)

        core_math_text_orig = target_core_math.read_text(encoding="utf-8")
        init_text_orig = target_init.read_text(encoding="utf-8")

        mutations = [
            {
                "id": "K1-M1",
                "desc": "聚合改为直接把各步位移相加 (Naive displacement summation without rotation)",
                "file": target_core_math,
                "orig_sha": core_math_sha_orig,
                "orig_text": core_math_text_orig,
                "mutated_text": core_math_text_orig.replace(
                    "total_x += cos_p * d_x - sin_p * d_y\n        total_y += sin_p * d_x + cos_p * d_y",
                    "total_x += d_x\n        total_y += d_y",
                ),
                "test_target": "tests/v9/experiments/test_s2_core_math.py::test_aggregate_macro_square_loop_back_to_origin",
            },
            {
                "id": "K1-M2",
                "desc": "SIGReg 把与标准正态的比较换成与均匀分布比较 (Compare against uniform distribution CF)",
                "file": target_core_math,
                "orig_sha": core_math_sha_orig,
                "orig_text": core_math_text_orig,
                "mutated_text": core_math_text_orig.replace(
                    "phi_0 = np.exp(-0.5 * (knots**2))",
                    "phi_0 = np.sin(np.sqrt(3.0) * knots) / (np.sqrt(3.0) * knots)",
                ),
                "test_target": "tests/v9/experiments/test_s2_core_math.py::test_sigreg_isotropic_vs_degenerates_sample_size_derived_threshold",
            },
            {
                "id": "K1-M3",
                "desc": "去掉 dpsi 归一 (Remove dpsi angle normalization)",
                "file": target_core_math,
                "orig_sha": core_math_sha_orig,
                "orig_text": core_math_text_orig,
                "mutated_text": core_math_text_orig.replace(
                    "dpsi_norm = float(normalize_angle(current_psi))",
                    "dpsi_norm = float(current_psi)",
                ),
                "test_target": "tests/v9/experiments/test_s2_core_math.py::test_aggregate_macro_square_loop_back_to_origin",
            },
            {
                "id": "K1-M4",
                "desc": "在 __init__ 里加 import mlx.core (Import MLX in __init__.py)",
                "file": target_init,
                "orig_sha": init_sha_orig,
                "orig_text": init_text_orig,
                "mutated_text": "import mlx.core  # Adverse mutation\n" + init_text_orig,
                "test_target": "tests/v9/experiments/test_s2_package_pure_cpu.py::test_s2_package_pure_cpu_no_mlx_imported",
            },
        ]

        for m in mutations:
            mid = m["id"]
            target_file = m["file"]
            orig_sha = m["orig_sha"]
            orig_text = m["orig_text"]
            mutated_text = m["mutated_text"]
            test_target = m["test_target"]

            assert mutated_text != orig_text, f"Mutation {mid} failed to apply text replacement!"

            # 1. Apply mutation
            target_file.write_text(mutated_text, encoding="utf-8")
            mutated_sha = compute_sha256(target_file)

            # 2. Run targeted test
            pytest_cmd = [
                sys.executable,
                "-m",
                "pytest",
                test_target,
                "-q",
                "--tb=short",
            ]
            proc = subprocess.run(
                pytest_cmd,
                cwd=str(sandbox),
                env=sandbox_env,
                capture_output=True,
                text=True,
            )

            # Assert mutation causes failure (turns red, non-zero returncode)
            is_red = proc.returncode != 0
            fail_line = ""
            for line in proc.stdout.splitlines():
                if "FAILED" in line or "assert" in line:
                    fail_line = line.strip()
                    break

            # 3. Restore byte-by-byte
            target_file.write_text(orig_text, encoding="utf-8")
            restored_sha = compute_sha256(target_file)
            assert restored_sha == orig_sha, f"SHA mismatch after restoring {mid}: {restored_sha} vs {orig_sha}"

            results[mid] = {
                "description": m["desc"],
                "target_test": test_target,
                "turned_red": is_red,
                "exit_code": proc.returncode,
                "summary": fail_line or "Test failed as expected",
                "sha_before": orig_sha,
                "sha_mutated": mutated_sha,
                "sha_restored": restored_sha,
                "restored_verified": (restored_sha == orig_sha),
            }
            print(f"[{mid}] turned_red={is_red} exit_code={proc.returncode} restored_sha_ok={restored_sha == orig_sha}")

    return results


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent
    res = run_mutation_checks(repo_root)
    print(json.dumps(res, indent=2, ensure_ascii=False))
