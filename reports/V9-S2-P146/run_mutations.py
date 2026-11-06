#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 arms and planner (P146).

Executes 5 adversarial mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P146-M1: GELU -> ReLU in arms_mlx.py (killed by test_activations_use_gelu_and_no_relu)
2. P146-M2: Remove free bits floor in arm_a_loss_mlx (killed by test_arm_a_loss_free_bits_floor)
3. P146-M3: Remove latent overshooting loop in arm_a_loss_mlx (killed by test_arm_a_loss_overshooting_loop_and_horizon_bound)
4. P146-M4: Remove stop_gradient on IDM targets in arms_mlx.py (killed by test_idm_targets_explicit_stop_gradient)
5. P146-M5: Bypass ForwardCounter in custom planner cost_fn (killed by test_flat_cem_cost_fn_forward_counter_and_custom_cost)

Each mutation is verified RED (returncode != 0), byte-restored, and SHA-verified.
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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P146"
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


def run_test_in_sandbox(sandbox: Path, test_file: str, test_filter: str | None = None) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / test_file),
        "-v",
    ]
    if test_filter:
        cmd.extend(["-k", test_filter])

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== P146 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p146_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        arms_mlx_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
        planner_test_file = sandbox / "tests" / "v9" / "experiments" / "test_s2_planner.py"

        orig_arms_mlx_content = arms_mlx_file.read_text(encoding="utf-8")
        orig_arms_mlx_sha = hashlib.sha256(orig_arms_mlx_content.encode("utf-8")).hexdigest()

        orig_planner_test_content = planner_test_file.read_text(encoding="utf-8")
        orig_planner_test_sha = hashlib.sha256(orig_planner_test_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass both static arms test and planner test
        ret_clean_arms, out_clean_arms = run_test_in_sandbox(sandbox, "tests/v9/experiments/test_s2_arms_static.py")
        ret_clean_plan, out_clean_plan = run_test_in_sandbox(sandbox, "tests/v9/experiments/test_s2_planner.py")
        if ret_clean_arms != 0 or ret_clean_plan != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean_arms, out_clean_plan)
            return 1
        print("[PASS] Clean sandbox passed all static arms and planner tests")

        # -------------------------------------------------------------------------
        # Mutation 1: P146-M1 GELU -> ReLU in arms_mlx.py
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P146-M1 (GELU -> ReLU) ---")
        mut1_content = orig_arms_mlx_content.replace("nn.gelu", "nn.relu")
        assert mut1_content != orig_arms_mlx_content, "Mutation 1 replace failed"
        arms_mlx_file.write_text(mut1_content, encoding="utf-8")

        ret1, out1 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_arms_static.py",
            "test_activations_use_gelu_and_no_relu",
        )
        killed1 = ret1 != 0
        status1 = "KILLED (RED)" if killed1 else "SURVIVED (GREEN)"
        print(f"P146-M1 Status: {status1} (rc={ret1})")
        log_lines.append(f"=== P146-M1: GELU -> ReLU ===\nExit code: {ret1} ({status1})\nOutput:\n{out1}\n")

        # Restore
        arms_mlx_file.write_text(orig_arms_mlx_content, encoding="utf-8")
        restored_sha1 = sha256_file(arms_mlx_file)
        assert restored_sha1 == orig_arms_mlx_sha, f"SHA mismatch after restore M1: {restored_sha1} vs {orig_arms_mlx_sha}"

        results.append({
            "id": "P146-M1",
            "description": "Replace nn.gelu with nn.relu in arms_mlx.py",
            "test_targeted": "test_activations_use_gelu_and_no_relu",
            "exit_code": ret1,
            "killed": killed1,
            "status": status1,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 2: P146-M2 Remove free bits floor in arm_a_loss_mlx
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P146-M2 (Remove free bits floor) ---")
        target_m2 = "kl_penalized = mx.maximum(mean_kl, free_bits)"
        replacement_m2 = "kl_penalized = mean_kl"
        assert target_m2 in orig_arms_mlx_content, "Mutation 2 target string not found"
        mut2_content = orig_arms_mlx_content.replace(target_m2, replacement_m2)
        arms_mlx_file.write_text(mut2_content, encoding="utf-8")

        ret2, out2 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_arms_static.py",
            "test_arm_a_loss_free_bits_floor",
        )
        killed2 = ret2 != 0
        status2 = "KILLED (RED)" if killed2 else "SURVIVED (GREEN)"
        print(f"P146-M2 Status: {status2} (rc={ret2})")
        log_lines.append(f"=== P146-M2: Remove free bits floor ===\nExit code: {ret2} ({status2})\nOutput:\n{out2}\n")

        # Restore
        arms_mlx_file.write_text(orig_arms_mlx_content, encoding="utf-8")
        restored_sha2 = sha256_file(arms_mlx_file)
        assert restored_sha2 == orig_arms_mlx_sha, f"SHA mismatch after restore M2: {restored_sha2} vs {orig_arms_mlx_sha}"

        results.append({
            "id": "P146-M2",
            "description": "Omit free bits floor mx.maximum in arm_a_loss_mlx",
            "test_targeted": "test_arm_a_loss_free_bits_floor",
            "exit_code": ret2,
            "killed": killed2,
            "status": status2,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 3: P146-M3 Remove latent overshooting loop in arm_a_loss_mlx
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P146-M3 (Remove latent overshooting loop) ---")
        target_m3 = "for tau in range(1, max_overshoot_steps + 1):"
        replacement_m3 = "for dummy_loop in range(0):"
        assert target_m3 in orig_arms_mlx_content, "Mutation 3 target string not found"
        mut3_content = orig_arms_mlx_content.replace(target_m3, replacement_m3)
        arms_mlx_file.write_text(mut3_content, encoding="utf-8")

        ret3, out3 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_arms_static.py",
            "test_arm_a_loss_overshooting_loop_and_horizon_bound",
        )
        killed3 = ret3 != 0
        status3 = "KILLED (RED)" if killed3 else "SURVIVED (GREEN)"
        print(f"P146-M3 Status: {status3} (rc={ret3})")
        log_lines.append(f"=== P146-M3: Remove overshooting loop ===\nExit code: {ret3} ({status3})\nOutput:\n{out3}\n")

        # Restore
        arms_mlx_file.write_text(orig_arms_mlx_content, encoding="utf-8")
        restored_sha3 = sha256_file(arms_mlx_file)
        assert restored_sha3 == orig_arms_mlx_sha, f"SHA mismatch after restore M3: {restored_sha3} vs {orig_arms_mlx_sha}"

        results.append({
            "id": "P146-M3",
            "description": "Remove overshooting loop in arm_a_loss_mlx",
            "test_targeted": "test_arm_a_loss_overshooting_loop_and_horizon_bound",
            "exit_code": ret3,
            "killed": killed3,
            "status": status3,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 4: P146-M4 Remove stop_gradient on IDM targets in arms_mlx.py
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P146-M4 (Remove stop_gradient on IDM targets) ---")
        target_m4_a = "target_actions = mx.stop_gradient(target_actions)"
        target_m4_b = "target_7d = mx.stop_gradient(target_7d)"
        target_m4_c = "target = mx.stop_gradient(target)"
        target_m4_d = "target_hist = mx.stop_gradient(target_hist)"
        assert target_m4_a in orig_arms_mlx_content and target_m4_b in orig_arms_mlx_content
        mut4_content = (
            orig_arms_mlx_content
            .replace(target_m4_a, "# pass target_actions")
            .replace(target_m4_b, "# pass target_7d")
            .replace(target_m4_c, "# pass target")
            .replace(target_m4_d, "# pass target_hist")
        )
        arms_mlx_file.write_text(mut4_content, encoding="utf-8")

        ret4, out4 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_arms_static.py",
            "test_idm_targets_explicit_stop_gradient",
        )
        killed4 = ret4 != 0
        status4 = "KILLED (RED)" if killed4 else "SURVIVED (GREEN)"
        print(f"P146-M4 Status: {status4} (rc={ret4})")
        log_lines.append(f"=== P146-M4: Remove stop_gradient on IDM targets ===\nExit code: {ret4} ({status4})\nOutput:\n{out4}\n")

        # Restore
        arms_mlx_file.write_text(orig_arms_mlx_content, encoding="utf-8")
        restored_sha4 = sha256_file(arms_mlx_file)
        assert restored_sha4 == orig_arms_mlx_sha, f"SHA mismatch after restore M4: {restored_sha4} vs {orig_arms_mlx_sha}"

        results.append({
            "id": "P146-M4",
            "description": "Omit mx.stop_gradient on IDM targets in arms_mlx.py",
            "test_targeted": "test_idm_targets_explicit_stop_gradient",
            "exit_code": ret4,
            "killed": killed4,
            "status": status4,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 5: P146-M5 Bypass ForwardCounter in planner cost_fn
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P146-M5 (Bypass ForwardCounter in planner cost_fn) ---")
        target_m5 = "dec = wrapped_decoder(z_T)"
        replacement_m5 = "dec = mocked_decoder(z_T)  # bypass ForwardCounter"
        assert target_m5 in orig_planner_test_content, "Mutation 5 target string not found"
        mut5_content = orig_planner_test_content.replace(target_m5, replacement_m5)
        planner_test_file.write_text(mut5_content, encoding="utf-8")

        ret5, out5 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_planner.py",
            "test_flat_cem_cost_fn_forward_counter_and_custom_cost",
        )
        killed5 = ret5 != 0
        status5 = "KILLED (RED)" if killed5 else "SURVIVED (GREEN)"
        print(f"P146-M5 Status: {status5} (rc={ret5})")
        log_lines.append(f"=== P146-M5: Bypass ForwardCounter in planner cost_fn ===\nExit code: {ret5} ({status5})\nOutput:\n{out5}\n")

        # Restore
        planner_test_file.write_text(orig_planner_test_content, encoding="utf-8")
        restored_sha5 = sha256_file(planner_test_file)
        assert restored_sha5 == orig_planner_test_sha, f"SHA mismatch after restore M5: {restored_sha5} vs {orig_planner_test_sha}"

        results.append({
            "id": "P146-M5",
            "description": "Bypass ForwardCounter charge in custom planner cost_fn",
            "test_targeted": "test_flat_cem_cost_fn_forward_counter_and_custom_cost",
            "exit_code": ret5,
            "killed": killed5,
            "status": status5,
            "restored_sha_matched": True,
        })

    # Save outputs
    summary = {
        "task_id": "ainerzero.V9.P146",
        "total_mutations": len(results),
        "killed_mutations": sum(1 for r in results if r["killed"]),
        "survived_mutations": sum(1 for r in results if not r["killed"]),
        "all_killed": all(r["killed"] for r in results),
        "mutations": results,
    }

    summary_file = REPORT_DIR / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nWrote mutation summary to {summary_file}")
    print(f"Wrote mutation log to {log_file}")

    if summary["all_killed"]:
        print("ALL 5 MUTATIONS SUCCESSFULLY KILLED (5/5 RED -> RESTORED).")
        return 0
    else:
        print("SOME MUTATIONS SURVIVED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
