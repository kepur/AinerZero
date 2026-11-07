#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 Phase 1 wiring and smoke r3 (P148).

Executes 5 adversarial mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P148-M1: verify does not call identity verification (killed by test_verify_case_tampered_byte_fails_and_names_file)
2. P148-M2: smoke circuit breaker threshold changed to 0.5 (killed by test_smoke_logic_circuit_breaker_when_all_arms_below_floor)
3. P148-M3: training steps rule takes max instead of min (killed by test_smoke_timing_and_training_steps_minimum_rule)
4. P148-M4: commands imports adapters_mlx at module level (killed by test_pure_cpu_isolation_commands_and_smoke_do_not_import_mlx)
5. P148-M5: smoke step 3 restores constant metrics (killed by test_smoke_step3_step4_unimplemented_must_fail)

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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P148" / "r3"
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
    print("=== P148 r3 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p148_r3_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        commands_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "commands.py"
        smoke_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke.py"

        orig_commands_content = commands_file.read_text(encoding="utf-8")
        orig_commands_sha = hashlib.sha256(orig_commands_content.encode("utf-8")).hexdigest()

        orig_smoke_content = smoke_file.read_text(encoding="utf-8")
        orig_smoke_sha = hashlib.sha256(orig_smoke_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass all 16 wiring tests
        ret_clean, out_clean = run_test_in_sandbox(sandbox, "tests/v9/experiments/test_s2_wiring.py")
        if ret_clean != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean)
            return 1
        print("[PASS] Clean sandbox passed all 16 wiring tests")

        # -------------------------------------------------------------------------
        # Mutation 1: P148-M1 verify does not call identity verification
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P148-M1 (verify skips identity check) ---")
        target_m1 = "verif_res = identity.verify_frozen_identity(prereg_file, repo_root=paths[\"repo_root\"])"
        replacement_m1 = "verif_res = {'status': 'passed', 'bypassed': True}"
        assert target_m1 in orig_commands_content, "Target string for M1 not found"
        mut1_content = orig_commands_content.replace(target_m1, replacement_m1)
        commands_file.write_text(mut1_content, encoding="utf-8")

        ret1, out1 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_wiring.py",
            "test_verify_case_tampered_byte_fails_and_names_file",
        )
        killed1 = ret1 != 0
        status1 = "KILLED (RED)" if killed1 else "SURVIVED (GREEN)"
        print(f"P148-M1 Status: {status1} (rc={ret1})")
        log_lines.append(f"=== P148-M1: verify skips identity check ===\nExit code: {ret1} ({status1})\nOutput:\n{out1}\n")

        # Restore
        commands_file.write_text(orig_commands_content, encoding="utf-8")
        restored_sha1 = sha256_file(commands_file)
        assert restored_sha1 == orig_commands_sha, f"SHA mismatch after restore M1: {restored_sha1} vs {orig_commands_sha}"

        results.append({
            "id": "P148-M1",
            "description": "verify mode omits call to identity.verify_frozen_identity",
            "test_targeted": "test_verify_case_tampered_byte_fails_and_names_file",
            "exit_code": ret1,
            "killed": killed1,
            "status": status1,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 2: P148-M2 smoke circuit breaker threshold changed from 0.05 to 0.5
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P148-M2 (circuit breaker threshold changed to 0.5) ---")
        target_m2 = "SMOKE_CIRCUIT_BREAKER_THRESHOLD: float = float(spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD)"
        replacement_m2 = "SMOKE_CIRCUIT_BREAKER_THRESHOLD: float = 0.5"
        assert target_m2 in orig_smoke_content, "Target string for M2 not found"
        mut2_content = orig_smoke_content.replace(target_m2, replacement_m2)
        smoke_file.write_text(mut2_content, encoding="utf-8")

        ret2, out2 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_wiring.py",
            "test_smoke_logic_circuit_breaker_when_all_arms_below_floor",
        )
        killed2 = ret2 != 0
        status2 = "KILLED (RED)" if killed2 else "SURVIVED (GREEN)"
        print(f"P148-M2 Status: {status2} (rc={ret2})")
        log_lines.append(f"=== P148-M2: circuit breaker threshold = 0.5 ===\nExit code: {ret2} ({status2})\nOutput:\n{out2}\n")

        # Restore
        smoke_file.write_text(orig_smoke_content, encoding="utf-8")
        restored_sha2 = sha256_file(smoke_file)
        assert restored_sha2 == orig_smoke_sha, f"SHA mismatch after restore M2: {restored_sha2} vs {orig_smoke_sha}"

        results.append({
            "id": "P148-M2",
            "description": "Change smoke circuit breaker threshold from 0.05 to 0.5",
            "test_targeted": "test_smoke_logic_circuit_breaker_when_all_arms_below_floor",
            "exit_code": ret2,
            "killed": killed2,
            "status": status2,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 3: P148-M3 compute_training_steps takes max instead of min
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P148-M3 (compute_training_steps takes max) ---")
        target_m3 = "shared_steps = min(per_arm_steps.values())"
        replacement_m3 = "shared_steps = max(per_arm_steps.values())"
        assert target_m3 in orig_smoke_content, "Target string for M3 not found"
        mut3_content = orig_smoke_content.replace(target_m3, replacement_m3)
        smoke_file.write_text(mut3_content, encoding="utf-8")

        ret3, out3 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_wiring.py",
            "test_smoke_timing_and_training_steps_minimum_rule",
        )
        killed3 = ret3 != 0
        status3 = "KILLED (RED)" if killed3 else "SURVIVED (GREEN)"
        print(f"P148-M3 Status: {status3} (rc={ret3})")
        log_lines.append(f"=== P148-M3: training steps takes max ===\nExit code: {ret3} ({status3})\nOutput:\n{out3}\n")

        # Restore
        smoke_file.write_text(orig_smoke_content, encoding="utf-8")
        restored_sha3 = sha256_file(smoke_file)
        assert restored_sha3 == orig_smoke_sha, f"SHA mismatch after restore M3: {restored_sha3} vs {orig_smoke_sha}"

        results.append({
            "id": "P148-M3",
            "description": "Calculate shared training steps using max() instead of min()",
            "test_targeted": "test_smoke_timing_and_training_steps_minimum_rule",
            "exit_code": ret3,
            "killed": killed3,
            "status": status3,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 4: P148-M4 commands top-level import adapters_mlx
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P148-M4 (commands top-level imports adapters_mlx) ---")
        mut4_content = "import ainerzero.v9.experiments.s2.adapters_mlx\n" + orig_commands_content
        commands_file.write_text(mut4_content, encoding="utf-8")

        ret4, out4 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_wiring.py",
            "test_pure_cpu_isolation_commands_and_smoke_do_not_import_mlx",
        )
        killed4 = ret4 != 0
        status4 = "KILLED (RED)" if killed4 else "SURVIVED (GREEN)"
        print(f"P148-M4 Status: {status4} (rc={ret4})")
        log_lines.append(f"=== P148-M4: commands top-level import adapters_mlx ===\nExit code: {ret4} ({status4})\nOutput:\n{out4}\n")

        # Restore
        commands_file.write_text(orig_commands_content, encoding="utf-8")
        restored_sha4 = sha256_file(commands_file)
        assert restored_sha4 == orig_commands_sha, f"SHA mismatch after restore M4: {restored_sha4} vs {orig_commands_sha}"

        results.append({
            "id": "P148-M4",
            "description": "Import adapters_mlx at module level in commands.py (leaking MLX into CPU suite)",
            "test_targeted": "test_pure_cpu_isolation_commands_and_smoke_do_not_import_mlx",
            "exit_code": ret4,
            "killed": killed4,
            "status": status4,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 5: P148-M5 stuff back constant metrics in step 3
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation P148-M5 (smoke step 3 restores constant metrics) ---")
        target_m5 = (
            '        # (c) Step 3 (short-training sanity) and Step 4 (oracle feasibility circuit breaker)\n'
            '        # Not implemented in P148 (deferred to P152). Absolutely NO constant metrics!\n'
            '        preconditions_metrics = {\n'
            '            "status": "not_implemented",\n'
            '            "step_3_short_train": {"status": "not_implemented"},\n'
            '            "step_4_feasibility": {"status": "not_implemented"},\n'
            '        }\n'
            '        reasons.append("短训健全性与可行性熔断待 P152 实现")'
        )
        assert target_m5 in orig_smoke_content, "Target string for M5 not found"
        replacement_m5 = (
            '        # (c) Injected constant metrics (bad mutation)\n'
            '        preconditions_metrics = {\n'
            '            "status": "completed",\n'
            '            "step_3_short_train": {"status": "completed", "delta_sigreg": -0.01},\n'
            '            "step_4_feasibility": {"status": "completed", "long_goal_success_rates": {"arm_a": 0.20}},\n'
            '        }'
        )
        mut5_content = orig_smoke_content.replace(target_m5, replacement_m5)
        smoke_file.write_text(mut5_content, encoding="utf-8")

        ret5, out5 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_wiring.py",
            "test_smoke_step3_step4_unimplemented_must_fail",
        )
        killed5 = ret5 != 0
        status5 = "KILLED (RED)" if killed5 else "SURVIVED (GREEN)"
        print(f"P148-M5 Status: {status5} (rc={ret5})")
        log_lines.append(f"=== P148-M5: smoke step 3 restores constant metrics ===\nExit code: {ret5} ({status5})\nOutput:\n{out5}\n")

        # Restore
        smoke_file.write_text(orig_smoke_content, encoding="utf-8")
        restored_sha5 = sha256_file(smoke_file)
        assert restored_sha5 == orig_smoke_sha, f"SHA mismatch after restore M5: {restored_sha5} vs {orig_smoke_sha}"

        results.append({
            "id": "P148-M5",
            "description": "smoke step 3 restores constant metrics instead of failing closed as not_implemented",
            "test_targeted": "test_smoke_step3_step4_unimplemented_must_fail",
            "exit_code": ret5,
            "killed": killed5,
            "status": status5,
            "restored_sha_matched": True,
        })

    # Save summary
    summary = {
        "task_id": "ainerzero.V9.P148",
        "round": "r3",
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

    print(f"\nWrote r3 mutation summary to {summary_file}")
    print(f"Wrote r3 mutation log to {log_file}")

    if summary["all_killed"]:
        print("ALL 5 MUTATIONS SUCCESSFULLY KILLED (5/5 RED -> RESTORED).")
        return 0
    else:
        print("SOME MUTATIONS SURVIVED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
