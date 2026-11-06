#!/usr/bin/env python3
"""Reviewer independent adversarial mutation runner for P152 (ainerzero.V9.P153).

Executes 4 independent mutations strictly outside author's mutation list (P152-M1..M3).
Sandbox copies:
- src/
- tests/
- pyproject.toml

Mutations tested:
1. REV-M1: Invert loss decrease check (mean_last < mean_first -> mean_last >= mean_first)
   Targeted test: test_short_train_sanity_decreasing_loss_passes
2. REV-M2: Bypass SIGReg stability check (sigreg_stable = True unconditionally)
   Targeted test: test_short_train_sanity_sigreg_increase_fails
3. REV-M3: Corrupt action sensitivity normalization (mean_pairwise / mean_norm -> mean_pairwise * 1.5)
   Targeted test: test_action_sensitivity_hand_calculated_analytic
4. REV-M4: Truncate oracle max_steps (bfs_dist * 3 -> 1)
   Targeted test: test_oracle_feasibility_on_gridlab_two_worlds
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
REVIEW_DIR = REAL_ROOT / "reports" / "V9-S2-P152" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


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
    print("=== P153 Reviewer Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p153_rev_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        target_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke_checks.py"
        orig_content = target_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # Clean baseline check
        ret_clean, out_clean = run_test_in_sandbox(sandbox, "tests/v9/experiments/test_s2_smoke_checks.py")
        if ret_clean != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean)
            return 1
        print("[PASS] Clean sandbox passed all 13 smoke checks tests")

        # -------------------------------------------------------------------------
        # Mutation 1: REV-M1 Invert loss decrease check
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation REV-M1 (invert loss decrease condition) ---")
        target_m1 = "loss_decreased = bool(mean_last < mean_first)"
        assert target_m1 in orig_content, "Target string for REV-M1 not found"
        replacement_m1 = "loss_decreased = bool(mean_last >= mean_first)"
        mut1_content = orig_content.replace(target_m1, replacement_m1)
        target_file.write_text(mut1_content, encoding="utf-8")

        ret1, out1 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_smoke_checks.py",
            "test_short_train_sanity_decreasing_loss_passes",
        )
        killed1 = ret1 != 0
        status1 = "KILLED (RED)" if killed1 else "SURVIVED (GREEN)"
        print(f"REV-M1 Status: {status1} (rc={ret1})")
        log_lines.append(f"=== REV-M1: invert loss decrease ===\nExit code: {ret1} ({status1})\nOutput:\n{out1}\n")

        # Restore
        target_file.write_text(orig_content, encoding="utf-8")
        restored_sha1 = sha256_file(target_file)
        assert restored_sha1 == orig_sha, f"SHA mismatch after restore REV-M1: {restored_sha1} vs {orig_sha}"

        results.append({
            "id": "REV-M1",
            "description": "Invert loss decrease check (mean_last < mean_first -> mean_last >= mean_first)",
            "test_targeted": "test_short_train_sanity_decreasing_loss_passes",
            "exit_code": ret1,
            "killed": killed1,
            "status": status1,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 2: REV-M2 Bypass SIGReg stability check
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation REV-M2 (bypass SIGReg 1.1x check) ---")
        target_m2 = "sigreg_stable = bool(final_sigreg <= max_allowed + 1e-9)"
        assert target_m2 in orig_content, "Target string for REV-M2 not found"
        replacement_m2 = "sigreg_stable = True"
        mut2_content = orig_content.replace(target_m2, replacement_m2)
        target_file.write_text(mut2_content, encoding="utf-8")

        ret2, out2 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_smoke_checks.py",
            "test_short_train_sanity_sigreg_increase_fails",
        )
        killed2 = ret2 != 0
        status2 = "KILLED (RED)" if killed2 else "SURVIVED (GREEN)"
        print(f"REV-M2 Status: {status2} (rc={ret2})")
        log_lines.append(f"=== REV-M2: bypass SIGReg check ===\nExit code: {ret2} ({status2})\nOutput:\n{out2}\n")

        # Restore
        target_file.write_text(orig_content, encoding="utf-8")
        restored_sha2 = sha256_file(target_file)
        assert restored_sha2 == orig_sha, f"SHA mismatch after restore REV-M2: {restored_sha2} vs {orig_sha}"

        results.append({
            "id": "REV-M2",
            "description": "Bypass SIGReg 1.1x bound check (unconditionally mark sigreg_stable = True)",
            "test_targeted": "test_short_train_sanity_sigreg_increase_fails",
            "exit_code": ret2,
            "killed": killed2,
            "status": status2,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 3: REV-M3 Corrupt action sensitivity normalization
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation REV-M3 (corrupt action sensitivity formula) ---")
        target_m3 = "sensitivity = mean_pairwise / mean_norm"
        assert target_m3 in orig_content, "Target string for REV-M3 not found"
        replacement_m3 = "sensitivity = mean_pairwise * 1.5"
        mut3_content = orig_content.replace(target_m3, replacement_m3)
        target_file.write_text(mut3_content, encoding="utf-8")

        ret3, out3 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_smoke_checks.py",
            "test_action_sensitivity_hand_calculated_analytic",
        )
        killed3 = ret3 != 0
        status3 = "KILLED (RED)" if killed3 else "SURVIVED (GREEN)"
        print(f"REV-M3 Status: {status3} (rc={ret3})")
        log_lines.append(f"=== REV-M3: corrupt sensitivity formula ===\nExit code: {ret3} ({status3})\nOutput:\n{out3}\n")

        # Restore
        target_file.write_text(orig_content, encoding="utf-8")
        restored_sha3 = sha256_file(target_file)
        assert restored_sha3 == orig_sha, f"SHA mismatch after restore REV-M3: {restored_sha3} vs {orig_sha}"

        results.append({
            "id": "REV-M3",
            "description": "Corrupt action sensitivity normalization (mean_pairwise / mean_norm -> mean_pairwise * 1.5)",
            "test_targeted": "test_action_sensitivity_hand_calculated_analytic",
            "exit_code": ret3,
            "killed": killed3,
            "status": status3,
            "restored_sha_matched": True,
        })

        # -------------------------------------------------------------------------
        # Mutation 4: REV-M4 Truncate oracle max_steps
        # -------------------------------------------------------------------------
        print("\n--- Running Mutation REV-M4 (truncate oracle max_steps) ---")
        target_m4 = "max_steps = int(bfs_dist * 3)"
        assert target_m4 in orig_content, "Target string for REV-M4 not found"
        replacement_m4 = "max_steps = 1"
        mut4_content = orig_content.replace(target_m4, replacement_m4)
        target_file.write_text(mut4_content, encoding="utf-8")

        ret4, out4 = run_test_in_sandbox(
            sandbox,
            "tests/v9/experiments/test_s2_smoke_checks.py",
            "test_oracle_feasibility_on_gridlab_two_worlds",
        )
        killed4 = ret4 != 0
        status4 = "KILLED (RED)" if killed4 else "SURVIVED (GREEN)"
        print(f"REV-M4 Status: {status4} (rc={ret4})")
        log_lines.append(f"=== REV-M4: truncate oracle max_steps ===\nExit code: {ret4} ({status4})\nOutput:\n{out4}\n")

        # Restore
        target_file.write_text(orig_content, encoding="utf-8")
        restored_sha4 = sha256_file(target_file)
        assert restored_sha4 == orig_sha, f"SHA mismatch after restore REV-M4: {restored_sha4} vs {orig_sha}"

        results.append({
            "id": "REV-M4",
            "description": "Truncate oracle max_steps (bfs_dist * 3 -> 1)",
            "test_targeted": "test_oracle_feasibility_on_gridlab_two_worlds",
            "exit_code": ret4,
            "killed": killed4,
            "status": status4,
            "restored_sha_matched": True,
        })

    summary = {
        "task_id": "ainerzero.V9.P153",
        "verifying_task": "ainerzero.V9.P152",
        "total_reviewer_mutations": len(results),
        "killed": sum(1 for r in results if r["killed"]),
        "survived": sum(1 for r in results if not r["killed"]),
        "all_killed": all(r["killed"] for r in results),
        "mutations": results,
    }

    summary_file = REVIEW_DIR / "reviewer_mutations.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    log_file = REVIEW_DIR / "reviewer_mutations.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nWrote reviewer mutation summary to {summary_file}")
    if summary["all_killed"]:
        print("ALL 4 REVIEWER MUTATIONS SUCCESSFULLY KILLED (4/4 RED -> RESTORED).")
        return 0
    else:
        print("SOME REVIEWER MUTATIONS SURVIVED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
