#!/usr/bin/env python3
"""Comprehensive independent verification script for P148 r3 (ainerzero.V9.P149).

Author: gemini-7k2q (Tier 2 Execution Agent, independent reviewer)
Target: ainerzero.V9.P148 (authored by gemini-m8d2)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P148" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def check_scope() -> dict[str, Any]:
    print("1. Checking Scope & Files...")
    # git diff --name-only HEAD src/
    res = subprocess.run(["git", "diff", "--name-only", "HEAD", "src/"], cwd=REPO_ROOT, capture_output=True, text=True)
    modified_src = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    return {
        "modified_src_files": modified_src,
        "src_diff_against_head_clean_except_cli": (modified_src == ["src/ainerzero/cli.py"]),
    }


def check_pure_cpu() -> dict[str, Any]:
    print("2. Checking Pure CPU Isolation (-I subprocess)...")
    cmd = [
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        "-I",
        "-c",
        "import sys; from ainerzero.v9.experiments import s2; from ainerzero.v9.experiments.s2 import commands, smoke; assert 'mlx' not in sys.modules; print('OK')",
    ]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    passed = (res.returncode == 0 and "OK" in res.stdout)
    return {
        "passed": passed,
        "exit_code": res.returncode,
        "output": res.stdout.strip(),
    }


def check_verify_tamper() -> dict[str, Any]:
    print("3. Checking Verify Mode Byte Tamper...")
    from ainerzero.v9.experiments.s2 import commands, freeze, prereg

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        draft = prereg.build_draft(repo_root=REPO_ROOT)
        frozen_dir = tmp_path / "frozen"
        doc_sha = freeze.freeze(draft, frozen_dir, repo_root=REPO_ROOT)
        prereg_path = frozen_dir / "prereg.json"

        log_path = tmp_path / "RESEARCH_LOG.md"
        log_path.write_text(f"## R20261106-S2-approval\nAPPROVED s2-phase1 prereg document_sha256={doc_sha}\n", encoding="utf-8")

        class Args:
            repo_root = REPO_ROOT
            output_root = frozen_dir
            prereg = prereg_path
            research_log = log_path
            mode = "verify"

        # 1. Unmodified
        rep1, code1 = commands.s2_phase1_command(Args())

        # 2. Tampered
        target_file = "src/ainerzero/v9/experiments/s2/spec.py"
        doc_json = json.loads(prereg_path.read_text(encoding="utf-8"))
        doc_json["source_digests"][target_file] = "0" * 64
        new_bytes = json.dumps(doc_json, indent=2, sort_keys=True).encode("utf-8")
        prereg_path.write_bytes(new_bytes)
        tampered_sha = hashlib.sha256(new_bytes).hexdigest()
        (frozen_dir / "prereg.json.sha256").write_text(f"{tampered_sha}  prereg.json\n", encoding="utf-8")
        log_path.write_text(f"## R20261106-S2-approval\nAPPROVED s2-phase1 prereg document_sha256={tampered_sha}\n", encoding="utf-8")

        rep2, code2 = commands.s2_phase1_command(Args())

        passed = (code1 == 0 and code2 != 0 and rep2.get("stage") == "identity_mismatch" and target_file in str(rep2.get("mismatches")))
        return {
            "unmodified_exit_code": code1,
            "tampered_exit_code": code2,
            "tampered_stage": rep2.get("stage"),
            "tampered_names_file": target_file in str(rep2.get("mismatches")),
            "passed": passed,
        }


def check_smoke_logic() -> dict[str, Any]:
    print("4. Checking Smoke Logic (4 Failures + 1 Normal)...")
    from ainerzero.v9.experiments.s2 import smoke

    norm = {
        "delta_sigreg": -0.05,
        "action_sensitivity": 0.12,
        "subgoal_shuffle_drop": 0.18,
        "long_goal_success_rates": {"arm_a": 0.2, "arm_b": 0.25, "arm_c": 0.35},
    }
    r_norm = smoke.check_smoke_preconditions(norm)["passed"]

    r_f1 = not smoke.check_smoke_preconditions(dict(norm, delta_sigreg=0.01))["passed"]
    r_f2 = not smoke.check_smoke_preconditions(dict(norm, action_sensitivity=0.02))["passed"]
    r_f3 = not smoke.check_smoke_preconditions(dict(norm, subgoal_shuffle_drop=0.04))["passed"]
    r_f4 = not smoke.check_smoke_preconditions(dict(norm, long_goal_success_rates={"a": 0.01, "b": 0.02, "c": 0.03}))["passed"]

    # Hand calculation
    step_times = {"arm_a": 0.02, "arm_b": 0.03, "arm_c": 0.05}
    calc = smoke.compute_training_steps(step_times)
    hand_min = min(math.floor(960 / 0.02), math.floor(960 / 0.03), math.floor(960 / 0.05))
    calc_ok = (calc["shared_train_steps"] == hand_min == 19200)

    # Namespace
    ns_rejected = False
    try:
        smoke.check_smoke_seed_namespace("train_seed")
    except ValueError:
        ns_rejected = True

    return {
        "normal_passed": r_norm,
        "fail1_sigreg_caught": r_f1,
        "fail2_action_sens_caught": r_f2,
        "fail3_shuffle_drop_caught": r_f3,
        "fail4_circuit_breaker_caught": r_f4,
        "hand_calc_matched": calc_ok,
        "namespace_disjointness_enforced": ns_rejected,
    }


def main() -> int:
    scope_res = check_scope()
    cpu_res = check_pure_cpu()
    verify_res = check_verify_tamper()
    smoke_res = check_smoke_logic()

    all_ok = (
        scope_res["src_diff_against_head_clean_except_cli"]
        and cpu_res["passed"]
        and verify_res["passed"]
        and all(smoke_res.values())
    )

    print(f"Overall verify_all result: {'PASSED' if all_ok else 'FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
