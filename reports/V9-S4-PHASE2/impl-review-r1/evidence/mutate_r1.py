#!/usr/bin/env python3
"""Mutation testing for S4 phase 2 r1 code changes (c5387d8..50f9edf).
Runs against the isolated workspace (/tmp/s4p2_r1_isolated).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/s4p2_r1_isolated")
PY = sys.executable

GATED = "src/ainerzero/v9/experiments/s4/gated.py"
ANALYSIS = "src/ainerzero/v9/experiments/s4/analysis_p2.py"
REPLAY = "reports/V9-S4-PHASE2/verify_replay_p2.py"

TEST_GATED = "tests/v9/experiments/test_s4_gated.py"
TEST_ANALYSIS = "tests/v9/experiments/test_s4_analysis_p2.py"
TEST_RUNNER = "tests/v9/experiments/test_s4p2_runner_native.py"

# (name, file_rel, old_str, new_str, test_file, test_args, requires_mlx)
MUTANTS = [
    # 1. 散射不保速率 (Required)
    (
        "scatter_speed_not_preserved",
        GATED,
        "return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)",
        "return 1.5 * np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)",
        TEST_GATED,
        ["-k", "test_scatter_response_turns_eb_velocity_keeps_speed_and_eb_position"],
        True,
    ),
    # 2. 散射在门关处也改速度 (Required)
    (
        "scatter_alters_vel_when_closed",
        GATED,
        'return pb, np.where(g[..., None], scatter_velocity(vb, theta), vb)',
        'return pb, scatter_velocity(vb, theta)',
        TEST_GATED,
        ["-k", "test_scatter_response_turns_eb_velocity_keeps_speed_and_eb_position"],
        True,
    ),
    # 3. 跟踪与动力学共用同一个种子 (Required)
    (
        "track_and_dyn_share_seed",
        ANALYSIS,
        'reseed_if_stochastic(m, rng_seed(ns, ep.world_index, int(name.split("#")[1]), name.split("#")[0], "dyn"))',
        'reseed_if_stochastic(m, rng_seed(ns, ep.world_index, int(name.split("#")[1]), name.split("#")[0], "track"))',
        TEST_ANALYSIS,
        ["-k", "test_stochastic_arms_are_reseeded_per_world_seed_arm_and_pass"],
        False,
    ),
    # 4. 重放不重设种子 (Required)
    (
        "replay_does_not_reseed",
        REPLAY,
        'P2.reseed_if_stochastic(m, P2.rng_seed(rep["ns"], w["world"], s, arm, "track"))',
        '# P2.reseed_if_stochastic(m, P2.rng_seed(rep["ns"], w["world"], s, arm, "track"))',
        TEST_RUNNER,
        ["-k", "test_smoke_runs_end_to_end_and_records_its_files"],
        True,
    ),
    # 5. GR 下界改成 ≥ (Required)
    (
        "gr_lower_bound_ge",
        ANALYSIS,
        '"GR": _ge(st["GR"], "value", T["GR"]["diff"]) and _gt(st["GR"], "bonf_low", T["GR"]["diff_low"]),',
        '"GR": _ge(st["GR"], "value", T["GR"]["diff"]) and _ge(st["GR"], "bonf_low", T["GR"]["diff_low"]),',
        TEST_ANALYSIS,
        ["-k", "test_decide_fails_each_gate_at_its_boundary and GR"],
        False,
    ),
    # 6. 负对照改回 95% 上界 (Required)
    (
        "neg_control_95_percent",
        ANALYSIS,
        'neg = (_lt(st["neg_C"], "bonf_high", T["negative_control"]["C_high_below"])\n           and _lt(st["neg_D"], "bonf_high", T["negative_control"]["D_high_below"]))',
        'neg = (_lt(st["neg_C"], "ci_high", T["negative_control"]["C_high_below"])\n           and _lt(st["neg_D"], "ci_high", T["negative_control"]["D_high_below"]))',
        TEST_ANALYSIS,
        ["-k", "test_negative_control_reads_the_bonferroni_upper_bound"],
        False,
    ),
    # 7. 随机门比例不是 2% (Extra)
    (
        "rand_rate_not_002",
        ANALYSIS,
        "RAND_RATE = 0.02",
        "RAND_RATE = 0.05",
        TEST_ANALYSIS,
        ["-k", "test_registered_constants"],
        False,
    ),
    # 8. Bonferroni 比较次数 m 不是 12 (Extra)
    (
        "bonferroni_m_not_12",
        ANALYSIS,
        "N_COMPARISONS = 12",
        "N_COMPARISONS = 11",
        TEST_ANALYSIS,
        ["-k", "test_bonferroni_is_twelve_comparisons or test_registered_constants"],
        False,
    ),
    # 9. 散射对照臂门与主臂不一致 (Extra)
    (
        "scatter_arm_gate_mismatch",
        ANALYSIS,
        '"L-sc-g": ("L-int", 0.5, "scatter")',
        '"L-sc-g": ("L-int", "geo", "scatter")',
        TEST_ANALYSIS,
        ["-k", "test_registered_constants"],
        False,
    ),
    # 10. 随机臂未重设种子时不报错 (Extra)
    (
        "stochastic_run_without_reseed",
        GATED,
        'if self.stochastic and self._rng is None:\n            raise RuntimeError("a stochastic gated arm needs reseed() before it runs")',
        '# check removed',
        TEST_GATED,
        ["-k", "test_stochastic_arms_need_a_seed_and_repeat_with_it"],
        True,
    ),
]


def run_one_mutant(name, file_rel, old_str, new_str, test_file, test_args, requires_mlx, lock_wrapper=None):
    target_path = ROOT / file_rel
    orig_content = target_path.read_text(encoding="utf-8")
    if orig_content.count(old_str) != 1:
        return {
            "name": name,
            "status": "ERROR",
            "reason": f"Expected exactly 1 occurrence of old_str, found {orig_content.count(old_str)}",
        }

    mutated_content = orig_content.replace(old_str, new_str, 1)
    target_path.write_text(mutated_content, encoding="utf-8")
    try:
        cmd = []
        if requires_mlx and lock_wrapper:
            cmd.extend(lock_wrapper)
        cmd.extend([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"])
        if requires_mlx:
            cmd.append("--native-mlx")
        cmd.append(test_file)
        cmd.extend(test_args)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        res = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        killed = res.returncode != 0
        last_line = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
        if not last_line and res.stderr.strip():
            last_line = res.stderr.strip().splitlines()[-1]

        return {
            "name": name,
            "file": file_rel,
            "status": "KILLED" if killed else "SURVIVED",
            "returncode": res.returncode,
            "output_summary": last_line,
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
    except Exception as e:
        return {
            "name": name,
            "file": file_rel,
            "status": "ERROR",
            "reason": str(e),
        }
    finally:
        target_path.write_text(orig_content, encoding="utf-8")


def main():
    lock_py = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
    lock_file = "/Users/mac/AinerWorkFlow/AinerZero/artifacts/locks/m0-worker.lock"
    lock_wrapper = [PY, lock_py, lock_file]

    results = []
    print(f"Running {len(MUTANTS)} mutations on isolated copy {ROOT}...")
    for idx, item in enumerate(MUTANTS, 1):
        name, file_rel, old_str, new_str, test_file, test_args, requires_mlx = item
        print(f"[{idx}/{len(MUTANTS)}] Running mutant: {name} (MLX={requires_mlx})...", end=" ", flush=True)
        r = run_one_mutant(name, file_rel, old_str, new_str, test_file, test_args, requires_mlx, lock_wrapper)
        print(f"{r['status']} (code={r.get('returncode')})")
        results.append(r)

    summary_file = Path("reports/V9-S4-PHASE2/impl-review-r1/evidence/mutants_summary.json")
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    out_txt = Path("reports/V9-S4-PHASE2/impl-review-r1/evidence/mutants_output.txt")
    with out_txt.open("w", encoding="utf-8") as f:
        f.write(f"S4 Phase 2 r1 Mutation Results ({len(results)} mutants)\n")
        f.write("=" * 60 + "\n\n")
        for r in results:
            f.write(f"Mutant: {r['name']}\n")
            f.write(f"File: {r.get('file')}\n")
            f.write(f"Status: {r['status']}\n")
            f.write(f"Summary: {r.get('output_summary')}\n")
            f.write("-" * 40 + "\n")
            if r.get("stdout"):
                f.write("Stdout:\n" + r["stdout"] + "\n")
            if r.get("stderr"):
                f.write("Stderr:\n" + r["stderr"] + "\n")
            f.write("\n" + "=" * 60 + "\n\n")

    killed = sum(1 for r in results if r["status"] == "KILLED")
    survived = sum(1 for r in results if r["status"] == "SURVIVED")
    print(f"\nDone: {killed}/{len(results)} killed, {survived} survived.")


if __name__ == "__main__":
    main()
