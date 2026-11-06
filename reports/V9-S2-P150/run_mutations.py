#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 Arm A loss return overshooting static assertion (ainerzero.V9.P150).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P150-M1: Omit mean_overshoot in return expression (return mean_recon + kl_penalized).
   Target: test_arm_a_loss_return_includes_overshooting_and_mean_from_losses -> MUST FAIL (RED / KILLED)
2. P150-M2: mean_overshoot is set to constant 0 unconditionally (not derived from overshoot_losses loop).
   Target: test_arm_a_loss_return_includes_overshooting_and_mean_from_losses -> MUST FAIL (RED / KILLED)
3. P150-M3: Return expression is not an addition BinOp (e.g. tuple of terms).
   Target: test_arm_a_loss_return_includes_overshooting_and_mean_from_losses -> MUST FAIL (RED / KILLED)

Each mutation is verified RED, restored byte-for-byte, and checked with SHA256.
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

REAL_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P150"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def setup_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    shutil.copytree(REAL_ROOT / "src", sandbox / "src", symlinks=True)
    shutil.copytree(REAL_ROOT / "tests", sandbox / "tests", symlinks=True)
    shutil.copy2(REAL_ROOT / "pyproject.toml", sandbox / "pyproject.toml")

    return sandbox


def run_test_in_sandbox(sandbox: Path, test_name: str) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_arms_static.py"),
        "-k",
        test_name,
        "-v",
    ]

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== P150 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p150_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        arms_mlx_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
        orig_content = arms_mlx_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # Pre-check: clean baseline test must pass
        tname = "test_arm_a_loss_return_includes_overshooting_and_mean_from_losses"
        ret_clean, out_clean = run_test_in_sandbox(sandbox, tname)
        if ret_clean != 0:
            print(f"[ERROR] Clean sandbox test failed:\n{out_clean}")
            return 1
        print(f"[PASS] Clean sandbox passed baseline {tname}")

        # -------------------------------------------------------------------------
        # Mutation 1: P150-M1 Omit mean_overshoot in return expression
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P150-M1: Omit mean_overshoot in return expression ---")
        m1_target = "return mean_recon + kl_penalized + mean_overshoot"
        m1_replacement = "return mean_recon + kl_penalized"
        assert m1_target in orig_content, "m1_target not found in arms_mlx.py"
        arms_mlx_file.write_text(orig_content.replace(m1_target, m1_replacement, 1), encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(sandbox, tname)
        is_red_m1 = ret_m1 != 0
        print(f"P150-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== P150-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        arms_mlx_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m1 = sha256_file(arms_mlx_file)
        assert restored_sha_m1 == orig_sha, "File SHA mismatch after M1 restore!"

        results.append({
            "id": "P150-M1",
            "name": "omit_mean_overshoot_in_return",
            "description": "Omit mean_overshoot from arm_a_loss_mlx return addition expression",
            "target_test": tname,
            "returncode": ret_m1,
            "status": "KILLED" if is_red_m1 else "SURVIVED",
            "is_red": is_red_m1,
            "restored_sha256": restored_sha_m1,
        })

        # -------------------------------------------------------------------------
        # Mutation 2: P150-M2 mean_overshoot is constant 0 unconditionally
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P150-M2: mean_overshoot constant 0 (not from overshoot_losses) ---")
        m2_target = """    if overshoot_losses:
        mean_overshoot = mx.mean(mx.stack(overshoot_losses))
    else:
        mean_overshoot = mx.array(0.0)"""
        m2_replacement = """    mean_overshoot = mx.array(0.0)"""
        assert m2_target in orig_content, "m2_target not found in arms_mlx.py"
        arms_mlx_file.write_text(orig_content.replace(m2_target, m2_replacement, 1), encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(sandbox, tname)
        is_red_m2 = ret_m2 != 0
        print(f"P150-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== P150-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        arms_mlx_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m2 = sha256_file(arms_mlx_file)
        assert restored_sha_m2 == orig_sha, "File SHA mismatch after M2 restore!"

        results.append({
            "id": "P150-M2",
            "name": "mean_overshoot_constant_zero",
            "description": "Set mean_overshoot to constant 0 unconditionally without averaging overshoot_losses",
            "target_test": tname,
            "returncode": ret_m2,
            "status": "KILLED" if is_red_m2 else "SURVIVED",
            "is_red": is_red_m2,
            "restored_sha256": restored_sha_m2,
        })

        # -------------------------------------------------------------------------
        # Mutation 3: P150-M3 Return value is not an addition BinOp (e.g. tuple)
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P150-M3: Return expression is a tuple instead of addition ---")
        m3_target = "return mean_recon + kl_penalized + mean_overshoot"
        m3_replacement = "return (mean_recon, kl_penalized, mean_overshoot)"
        assert m3_target in orig_content, "m3_target not found in arms_mlx.py"
        arms_mlx_file.write_text(orig_content.replace(m3_target, m3_replacement, 1), encoding="utf-8")

        ret_m3, out_m3 = run_test_in_sandbox(sandbox, tname)
        is_red_m3 = ret_m3 != 0
        print(f"P150-M3 Result: returncode={ret_m3}, is_red={is_red_m3}")
        log_lines.append(f"=== P150-M3 Output ===\nReturnCode: {ret_m3}\n{out_m3}\n")

        # Restore
        arms_mlx_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m3 = sha256_file(arms_mlx_file)
        assert restored_sha_m3 == orig_sha, "File SHA mismatch after M3 restore!"

        results.append({
            "id": "P150-M3",
            "name": "return_not_addition",
            "description": "Change arm_a_loss_mlx return to a tuple instead of an addition BinOp (+)",
            "target_test": tname,
            "returncode": ret_m3,
            "status": "KILLED" if is_red_m3 else "SURVIVED",
            "is_red": is_red_m3,
            "restored_sha256": restored_sha_m3,
        })

    # Summary
    summary_file = REPORT_DIR / "mutation_summary.json"
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved mutation summary to {summary_file}")

    log_file = REPORT_DIR / "mutation_log.txt"
    log_file.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"Saved mutation log to {log_file}")

    all_killed = all(r["is_red"] for r in results)
    print(f"\nAll mutations KILLED (RED): {all_killed}")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())
