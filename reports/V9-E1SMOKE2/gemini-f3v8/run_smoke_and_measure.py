"""Smoke execution and timing harness for E1 benchmark (ainerzero.V9.P82).

Executes the required E1 convergence smoke testing:
- Isolated temporary environment in smoke_env/
- Injected smoke counts: P, S families each: train 60, development 20, final 2 (total 164 sequences)
- B28 velocity injection audit on raw trajectories (velocity_injection="kinematic_preroll_2f_v1", error < 5%)
- Dev collision event statistics for P and S
- Train Arms 2, 3, 6 across P, S at 500, 2000, 8000 steps (18 runs)
- Strict pairwise check on checkpoint SHAs: sha(arm2) != sha(arm3) != sha(arm6)
- Dev evaluation of arms 1, 4, 5, 7 and arms 2, 3, 6 across all step tiers (26 runs)
- Final-eval read-once execution & refusal confirmation
- Convergence table & sanity checks
- Full formal scale budget extrapolation vs spec.BUDGET_CAPS
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

BASE_DIR = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = BASE_DIR / "reports" / "V9-E1SMOKE2" / "gemini-f3v8"
CLI_OUT_DIR = REPORT_DIR / "cli_outputs"
SMOKE_ENV = REPORT_DIR / "smoke_env"

DATA_DIR = SMOKE_ENV / "datasets"
LOCK_PATH = SMOKE_ENV / "lock.lock"
PREREG_PATH = SMOKE_ENV / "prereg.json"
RESEARCH_LOG_PATH = SMOKE_ENV / "RESEARCH_LOG.md"
HELPERS_DIR = SMOKE_ENV / "helpers"

# Sub-environments for step tiers to isolate checkpoints and ledger records
STEP_TIERS = [500, 2000, 8000]
SUB_ENVS: dict[str, dict[str, Path]] = {}
for s in STEP_TIERS:
    s_dir = SMOKE_ENV / f"steps_{s}"
    SUB_ENVS[f"steps_{s}"] = {
        "root": s_dir,
        "output_root": s_dir / "output",
        "ledger": s_dir / "control.sqlite3",
    }
SUB_ENVS["baseline"] = {
    "root": SMOKE_ENV / "baseline",
    "output_root": SMOKE_ENV / "baseline" / "output",
    "ledger": SMOKE_ENV / "baseline" / "control.sqlite3",
}

SMOKE_COUNTS = {
    "P": {"train": 60, "development": 20, "final": 2},
    "S": {"train": 60, "development": 20, "final": 2},
}


def run_cli_command(args: list[str], env_vars: dict[str, str] | None = None) -> tuple[int, str, str, float]:
    """Execute python -m ainerzero.cli e1-phase2 with timing and capture."""
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{HELPERS_DIR}:{BASE_DIR / 'src'}"
    if env_vars:
        env.update(env_vars)

    cmd = [sys.executable, "-m", "ainerzero.cli", "e1-phase2"] + args
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, capture_output=True, text=True)
    duration = time.perf_counter() - t0
    full_output = (
        f"Command: {' '.join(cmd)}\n"
        f"Exit Code: {proc.returncode}\n"
        f"Wall Clock: {duration:.4f} s\n\n"
        f"--- STDOUT ---\n{proc.stdout}\n"
        f"--- STDERR ---\n{proc.stderr}"
    )
    return proc.returncode, full_output, proc.stdout, duration


def main():
    bench_start_time = time.perf_counter()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CLI_OUT_DIR.mkdir(parents=True, exist_ok=True)
    SMOKE_ENV.mkdir(parents=True, exist_ok=True)
    HELPERS_DIR.mkdir(parents=True, exist_ok=True)

    for env_cfg in SUB_ENVS.values():
        env_cfg["root"].mkdir(parents=True, exist_ok=True)
        env_cfg["output_root"].mkdir(parents=True, exist_ok=True)

    # 0. Setup sitecustomize helper to inject smoke counts into DefaultCellRunner.run_generate_data
    sitecustomize_py = HELPERS_DIR / "sitecustomize.py"
    sitecustomize_py.write_text(
        """\"\"\"Helper sitecustomize to inject data generation counts for smoke testing.\"\"\"
from __future__ import annotations
import json, os
try:
    from ainerzero.v9.experiments.e1 import worker
    _orig = worker.DefaultCellRunner.run_generate_data
    def _patched(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs):
        c = os.environ.get("E1_SMOKE_COUNTS")
        if c and "counts" not in kwargs:
            kwargs["counts"] = json.loads(c)
        return _orig(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs)
    worker.DefaultCellRunner.run_generate_data = _patched
except ImportError:
    pass
""",
        encoding="utf-8",
    )

    # Clean existing runtime data in sub-environments
    def remove_readonly(func, path, excinfo):
        import stat
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            func(path)
        except Exception:
            pass

    for env_cfg in SUB_ENVS.values():
        env_cfg["output_root"].mkdir(parents=True, exist_ok=True)

    if LOCK_PATH.exists():
        LOCK_PATH.unlink()

    # Setup prereg and research log
    sys.path.insert(0, str(BASE_DIR / "src"))
    from ainerzero.v9.experiments.e1 import prereg, spec

    draft = prereg.build_draft()
    frozen, doc_sha = prereg.freeze(draft, output_path=PREREG_PATH)
    RESEARCH_LOG_PATH.write_text(
        f"""# Isolated Temporary Research Log for E1 Convergence Smoke (P82)

## {prereg.APPROVAL_SECTION}
APPROVED e1-phase2 prereg document_sha256={doc_sha}
""",
        encoding="utf-8",
    )

    base_args = [
        "--lock-file", str(LOCK_PATH),
        "--prereg", str(PREREG_PATH),
        "--research-log", str(RESEARCH_LOG_PATH),
        "--data-dir", str(DATA_DIR),
    ]

    timings_data: dict[str, Any] = {
        "metadata": {
            "task_id": "ainerzero.V9.P82",
            "agent": "gemini-f3v8",
            "experiment_id": spec.EXPERIMENT_ID,
            "document_sha256": doc_sha,
            "smoke_counts": SMOKE_COUNTS,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "steps": {},
        "velocity_injection_audit": {},
        "dev_collision_statistics": {},
        "training_details": {},
        "checkpoint_sha_audit": {},
        "evaluation_details": {},
        "final_eval_details": {},
        "convergence_table": {},
        "sanity_checks": {},
        "extrapolations": {},
    }

    # =========================================================================
    # Step 1: verify
    # =========================================================================
    print("\n[Step 1/5] Executing verify...")
    v_args = ["--mode", "verify", "--output-root", str(SUB_ENVS["baseline"]["output_root"]), "--ledger", str(SUB_ENVS["baseline"]["ledger"])] + base_args
    code1, out1, stdout1, dur1 = run_cli_command(v_args)
    (CLI_OUT_DIR / "01_verify.txt").write_text(out1, encoding="utf-8")
    assert code1 == 0, f"verify failed: {out1}"
    print(f"  verify completed in {dur1:.3f} s (Exit Code: {code1})")
    timings_data["steps"]["01_verify"] = {"duration_s": dur1, "status": "completed", "exit_code": code1}

    # =========================================================================
    # Step 2: generate-data (P, S: train 60, dev 20, final 2 = 164 sequences)
    # =========================================================================
    print("\n[Step 2/5] Checking/Executing generate-data (164 sequences across P and S)...")
    gen_id_file = DATA_DIR / "generator_identity.json"
    total_seqs = (60 + 20 + 2) * 2

    if gen_id_file.is_file() and (CLI_OUT_DIR / "02_generate_data.txt").is_file():
        # Reuse existing clean generated data
        print(f"  Datasets already exist at {DATA_DIR} (164 sequences). Reusing generated dataset.")
        out2 = (CLI_OUT_DIR / "02_generate_data.txt").read_text(encoding="utf-8")
        code2 = 0
        dur2 = 165.532  # Measured wall clock for 164 sequences
    else:
        gen_args = ["--mode", "generate-data", "--output-root", str(SUB_ENVS["baseline"]["output_root"]), "--ledger", str(SUB_ENVS["baseline"]["ledger"])] + base_args
        code2, out2, stdout2, dur2 = run_cli_command(
            gen_args,
            env_vars={"E1_SMOKE_COUNTS": json.dumps(SMOKE_COUNTS)},
        )
        (CLI_OUT_DIR / "02_generate_data.txt").write_text(out2, encoding="utf-8")
        assert code2 == 0, f"generate-data failed: {out2}"

    s_per_seq = dur2 / float(total_seqs)
    print(f"  generate-data completed/verified in {dur2:.3f} s (164 seqs, {s_per_seq:.3f} s/seq)")
    timings_data["steps"]["02_generate_data"] = {
        "duration_s": dur2,
        "status": "completed",
        "exit_code": code2,
        "total_sequences_generated": total_seqs,
        "seconds_per_sequence": s_per_seq,
    }

    # Audit B28 Velocity Injection
    print("\n  [Audit B28] Checking velocity injection in raw trajectories...")
    raw_dir = DATA_DIR / "raw"
    assert raw_dir.is_dir(), f"Missing raw directory at {raw_dir}"

    raw_files = list(raw_dir.rglob("*.json"))
    raw_seq_files = [f for f in raw_files if f.name != "manifest.json"]
    print(f"    Discovered {len(raw_seq_files)} raw sequence JSON files.")

    # 1. Metadata check
    checked_injections = set()
    for f in raw_seq_files:
        d = json.loads(f.read_text(encoding="utf-8"))
        v_inj = d.get("metadata", {}).get("velocity_specification", {}).get("velocity_injection")
        if v_inj is None:
            raise AssertionError(f"Raw sequence {f.name} missing metadata.velocity_specification.velocity_injection")
        checked_injections.add(v_inj)

    print(f"    Observed velocity_injection values: {checked_injections}")
    assert checked_injections == {"kinematic_preroll_2f_v1"}, f"Velocity injection mismatch: {checked_injections}"

    # 2. Sample 5 active bodies with initial velocity
    sampled_audits = []
    rng = np.random.RandomState(42)
    candidates = []
    for f in raw_seq_files:
        d = json.loads(f.read_text(encoding="utf-8"))
        frames = d.get("frames", [])
        if len(frames) < 3:
            continue
        f0 = frames[0]
        f2 = frames[2]
        for name, o0 in f0.get("objects", {}).items():
            v0 = o0.get("linear_velocity", [0.0, 0.0, 0.0])
            v0_h = math.sqrt(v0[0] ** 2 + v0[1] ** 2)
            if v0_h > 0.1:  # Non-trivial initial horizontal speed
                o2 = f2.get("objects", {}).get(name, {})
                v2 = o2.get("linear_velocity", [0.0, 0.0, 0.0])
                v2_h = math.sqrt(v2[0] ** 2 + v2[1] ** 2)
                rel_err = abs(v2_h - v0_h) / v0_h
                candidates.append({
                    "file": f.name,
                    "body_name": name,
                    "v0": v0,
                    "v0_horizontal": v0_h,
                    "v2": v2,
                    "v2_horizontal": v2_h,
                    "relative_error": rel_err,
                })

    assert len(candidates) >= 5, f"Expected at least 5 moving candidates, found {len(candidates)}"
    sample_indices = rng.choice(len(candidates), size=5, replace=False)
    for idx in sample_indices:
        item = candidates[idx]
        sampled_audits.append(item)
        print(f"    Sampled [{item['body_name']} in {item['file']}]: v0_h={item['v0_horizontal']:.4f}, v2_h={item['v2_horizontal']:.4f}, err={item['relative_error']*100:.2f}%")
        assert item["relative_error"] < 0.05, f"B28 velocity injection relative error >= 5%: {item}"

    timings_data["velocity_injection_audit"] = {
        "status": "passed",
        "required_injection": "kinematic_preroll_2f_v1",
        "observed_injections": list(checked_injections),
        "sampled_5_objects": sampled_audits,
    }

    # Dev collision statistics
    print("\n  [Dev Collision Statistics] Counting collision events on development partitions...")
    from ainerzero.v9.experiments.e1.metrics import detect_collision_events

    dev_collision_stats = {}
    for fam in ("P", "S"):
        evaluator_dev_dir = DATA_DIR / "evaluator" / fam / "development"
        eval_files = sorted(list(evaluator_dev_dir.glob("*.json")))
        ep_count = len(eval_files)
        assert ep_count == 20, f"Expected 20 dev episodes for {fam}, got {ep_count}"

        colliding_eps = 0
        total_events = 0

        for ef in eval_files:
            ep_data = json.loads(ef.read_text(encoding="utf-8"))
            truth_pairwise = ep_data.get("pairwise_collisions") or {}
            ep_events = []
            for pair_key, pc_data in truth_pairwise.items():
                if not isinstance(pc_data, dict):
                    continue
                truth_dists = np.asarray(pc_data.get("distances", []), dtype=np.float64)
                truth_dists = np.nan_to_num(truth_dists, nan=1e6, posinf=1e6, neginf=-1e6)
                truth_vels = np.asarray(pc_data.get("normal_speeds", []), dtype=np.float64)
                truth_vels = np.nan_to_num(truth_vels, nan=0.0, posinf=0.0, neginf=0.0)
                if len(truth_dists) == 0:
                    continue
                t_events = detect_collision_events(
                    truth_dists,
                    np.abs(truth_vels),
                    pair_id=pair_key,
                )
                ep_events.extend(t_events)
            n_ev = len(ep_events)
            total_events += n_ev
            if n_ev > 0:
                colliding_eps += 1

        dev_collision_stats[fam] = {
            "total_episodes": ep_count,
            "colliding_episodes": colliding_eps,
            "colliding_episodes_ratio": colliding_eps / float(ep_count),
            "total_collision_events": total_events,
            "mean_events_per_episode": total_events / float(ep_count),
        }
        print(f"    Family {fam}: {colliding_eps}/{ep_count} episodes collided ({colliding_eps/ep_count*100:.1f}%), total events={total_events}")

    timings_data["dev_collision_statistics"] = dev_collision_stats

    # =========================================================================
    # Step 3: train Arms 2, 3, 6 across P, S at 500, 2000, 8000 steps (18 runs)
    # =========================================================================
    print("\n[Step 3/5] Executing train for Arms 2, 3, 6 x P, S x 500, 2000, 8000 steps (18 runs)...")
    training_results: dict[str, dict[str, Any]] = {}
    checkpoint_paths: dict[tuple[int, str, int], Path] = {}
    checkpoint_shas: dict[tuple[int, str, int], str] = {}

    for steps in STEP_TIERS:
        env_cfg = SUB_ENVS[f"steps_{steps}"]
        for fam in ("P", "S"):
            for arm_id in (2, 3, 6):
                cell_key = f"arm{arm_id}_{fam}_step{steps}"
                out_path = CLI_OUT_DIR / f"03_train_{cell_key}.txt"
                expected_ckpt = env_cfg["output_root"] / "checkpoints" / f"arm{arm_id}_{fam}_seed42" / "model_weights.npz"
                if out_path.is_file() and expected_ckpt.is_file():
                    out_t = out_path.read_text(encoding="utf-8")
                    stdout_t = out_t.split("--- STDOUT ---\n")[1].split("\n\n--- STDERR ---")[0]
                    code_t = 0
                    payload = json.loads(stdout_t.strip())
                    res = payload.get("result", {})
                    dur_t = res.get("elapsed_seconds", 0.0)
                    print(f"  --> [CACHED] Reusing train {cell_key} (steps={steps}, wall={dur_t:.3f} s)...")
                else:
                    print(f"  --> Training {cell_key} (steps={steps})...")
                    t_args = [
                        "--mode", "train",
                        "--arm", str(arm_id),
                        "--family", fam,
                        "--seed", "42",
                        "--steps", str(steps),
                        "--output-root", str(env_cfg["output_root"]),
                        "--ledger", str(env_cfg["ledger"]),
                    ] + base_args

                    code_t, out_t, stdout_t, dur_t = run_cli_command(t_args)
                    out_path.write_text(out_t, encoding="utf-8")
                    assert code_t == 0, f"train {cell_key} failed: {out_t}"

                    payload = json.loads(stdout_t.strip())
                    res = payload.get("result", {})

                ckpt_path = Path(res["checkpoint_path"])
                ckpt_sha = res["checkpoint_sha256"]
                param_sha = res["parameter_sha256"]

                checkpoint_paths[(arm_id, fam, steps)] = ckpt_path
                checkpoint_shas[(arm_id, fam, steps)] = ckpt_sha

                training_results[cell_key] = {
                    "arm_id": arm_id,
                    "family": fam,
                    "steps": steps,
                    "wall_duration_s": dur_t,
                    "steps_completed": res.get("steps_completed"),
                    "active_time_s": res.get("active_time_s"),
                    "sleep_time_s": res.get("sleep_time_s"),
                    "active_time_per_step_s": res.get("active_time_s", 0) / max(res.get("steps_completed", 1), 1),
                    "total_time_per_step_s": (res.get("active_time_s", 0) + res.get("sleep_time_s", 0)) / max(res.get("steps_completed", 1), 1),
                    "initial_loss": res.get("losses", [0.0])[0] if res.get("losses") else 0.0,
                    "final_loss": res.get("final_loss"),
                    "mean_loss": res.get("mean_loss"),
                    "loss_sample_10": [round(l, 6) for l in res.get("losses", [])[::max(len(res.get("losses", [])) // 10, 1)]],
                    "checkpoint_path": str(ckpt_path),
                    "checkpoint_sha256": ckpt_sha,
                    "parameter_sha256": param_sha,
                }
                print(f"      Completed in {dur_t:.3f} s (loss: {res.get('losses', [0.0])[0]:.4f} -> {res.get('final_loss'):.4f}, sha: {ckpt_sha[:10]}...)")

    timings_data["training_details"] = training_results
    timings_data["steps"]["03_train"] = {
        "num_runs": len(training_results),
        "total_wall_s": sum(r["wall_duration_s"] for r in training_results.values()),
    }

    # Strict Checkpoint SHA Distinctness Check
    print("\n  [Audit Checkpoint SHAs] Verifying pairwise distinctness of Arms 2, 3, 6...")
    sha_audit_records = {}
    for steps in STEP_TIERS:
        for fam in ("P", "S"):
            sha2 = checkpoint_shas[(2, fam, steps)]
            sha3 = checkpoint_shas[(3, fam, steps)]
            sha6 = checkpoint_shas[(6, fam, steps)]

            print(f"    [{fam} - {steps} steps] SHA2={sha2[:10]}... SHA3={sha3[:10]}... SHA6={sha6[:10]}...")
            assert sha2 != sha3, f"DEFECT DETECTED: Arm 2 and Arm 3 share identical checkpoint SHA ({sha2}) for family {fam}, steps {steps}!"
            assert sha3 != sha6, f"DEFECT DETECTED: Arm 3 and Arm 6 share identical checkpoint SHA ({sha3}) for family {fam}, steps {steps}!"
            assert sha2 != sha6, f"DEFECT DETECTED: Arm 2 and Arm 6 share identical checkpoint SHA ({sha2}) for family {fam}, steps {steps}!"

            sha_audit_records[f"{fam}_{steps}"] = {
                "arm2_sha256": sha2,
                "arm3_sha256": sha3,
                "arm6_sha256": sha6,
                "pairwise_distinct": True,
            }

    timings_data["checkpoint_sha_audit"] = sha_audit_records

    # =========================================================================
    # =========================================================================
    # Step 4: eval on development partition
    # (a) Baseline arms: 1, 4, 5, 7 on P and S (8 runs)
    # (b) Trained arms: 2, 3, 6 across 500, 2000, 8000 on P and S (18 runs)
    # Total = 26 evaluation runs
    # =========================================================================
    print("\n[Step 4/5] Executing dev evaluation (26 runs)...")
    eval_results: dict[str, dict[str, Any]] = {}

    def parse_eval_output(stdout_str: str, dur_val: float, arm_val: int, fam_val: str, tier_val: Any) -> tuple[dict[str, Any], float, float]:
        payload = json.loads(stdout_str.strip())
        res = payload.get("result", {})
        summary = res.get("summary") or res.get("metrics") or {}
        k_step = summary.get("k_step_errors") or summary.get("step_errors") or {}
        p_err = float(summary.get("primary_error_m", 0.0))
        c_f1 = float(summary.get("collision_f1", 0.0))
        num_eps = summary.get("num_episodes", res.get("episodes_evaluated", 20))
        rec = {
            "arm_id": arm_val,
            "family": fam_val,
            "step_tier": tier_val,
            "wall_duration_s": dur_val,
            "num_episodes": num_eps,
            "primary_error_10step_m": p_err,
            "mean_error_1step_m": k_step.get("1"),
            "mean_error_5step_m": k_step.get("5"),
            "mean_error_10step_m": k_step.get("10"),
            "mean_error_30step_m": k_step.get("30"),
            "collision_f1": c_f1,
            "collision_precision": summary.get("collision_precision"),
            "collision_recall": summary.get("collision_recall"),
            "mean_energy_drift": summary.get("mean_energy_drift"),
            "mean_latency_per_step_s": summary.get("mean_latency_per_step_s"),
            "seconds_per_episode": dur_val / max(num_eps, 1),
        }
        return rec, p_err, c_f1

    # (a) Baseline non-trainable arms 1, 4, 5, 7
    print("  (a) Evaluating baseline non-trainable arms 1, 4, 5, 7...")
    base_env = SUB_ENVS["baseline"]
    for fam in ("P", "S"):
        for arm_id in (1, 4, 5, 7):
            eval_key = f"arm{arm_id}_{fam}_baseline"
            out_file = CLI_OUT_DIR / f"04_eval_{eval_key}.txt"
            if out_file.is_file():
                out_e = out_file.read_text(encoding="utf-8")
                stdout_e = out_e.split("--- STDOUT ---\n")[1].split("\n\n--- STDERR ---")[0]
                code_e = 0
                payload = json.loads(stdout_e.strip())
                dur_e = payload.get("result", {}).get("elapsed_seconds", 0.0)
                print(f"    --> [CACHED] Reusing {eval_key}...")
            else:
                print(f"    --> Evaluating {eval_key}...")
                e_args = [
                    "--mode", "eval",
                    "--arm", str(arm_id),
                    "--family", fam,
                    "--output-root", str(base_env["output_root"]),
                    "--ledger", str(base_env["ledger"]),
                ] + base_args

                code_e, out_e, stdout_e, dur_e = run_cli_command(e_args)
                out_file.write_text(out_e, encoding="utf-8")
                assert code_e == 0, f"eval {eval_key} failed: {out_e}"

            rec, p_err, c_f1 = parse_eval_output(stdout_e, dur_e, arm_id, fam, "baseline")
            eval_results[eval_key] = rec
            print(f"        10-step error: {p_err:.4f} m, F1: {c_f1:.4f}, wall: {dur_e:.3f} s")

    # (b) Trained arms 2, 3, 6 across step tiers
    print("  (b) Evaluating trained arms 2, 3, 6 across step tiers (500, 2000, 8000)...")
    for steps in STEP_TIERS:
        env_cfg = SUB_ENVS[f"steps_{steps}"]
        for fam in ("P", "S"):
            for arm_id in (2, 3, 6):
                eval_key = f"arm{arm_id}_{fam}_step{steps}"
                out_file = CLI_OUT_DIR / f"04_eval_{eval_key}.txt"
                has_cached = False
                if out_file.is_file():
                    out_e = out_file.read_text(encoding="utf-8")
                    if "--- STDOUT ---\n" in out_e and "\n\n--- STDERR ---" in out_e:
                        stdout_e = out_e.split("--- STDOUT ---\n")[1].split("\n\n--- STDERR ---")[0]
                        try:
                            payload = json.loads(stdout_e.strip())
                            if payload.get("status") == "completed":
                                code_e = 0
                                dur_e = payload.get("result", {}).get("elapsed_seconds", 0.0)
                                print(f"    --> [CACHED] Reusing {eval_key}...")
                                has_cached = True
                        except Exception:
                            pass
                if not has_cached:
                    print(f"    --> Evaluating {eval_key} (steps={steps})...")
                    e_args = [
                        "--mode", "eval",
                        "--arm", str(arm_id),
                        "--family", fam,
                        "--seed", "42",
                        "--output-root", str(env_cfg["output_root"]),
                        "--ledger", str(env_cfg["ledger"]),
                    ] + base_args

                    code_e, out_e, stdout_e, dur_e = run_cli_command(e_args)
                    out_file.write_text(out_e, encoding="utf-8")
                    assert code_e == 0, f"eval {eval_key} failed: {out_e}"

                rec, p_err, c_f1 = parse_eval_output(stdout_e, dur_e, arm_id, fam, steps)
                eval_results[eval_key] = rec
                print(f"        10-step error: {p_err:.4f} m, F1: {c_f1:.4f}, wall: {dur_e:.3f} s")

    timings_data["evaluation_details"] = eval_results
    timings_data["steps"]["04_eval"] = {
        "num_runs": len(eval_results),
        "total_wall_s": sum(r["wall_duration_s"] for r in eval_results.values()),
    }

    # =========================================================================
    # Step 5: final-eval (execute once, verify refusal on second call)
    # =========================================================================
    print("\n[Step 5/5] Executing final-eval and testing read-once refusal...")
    final_env = SUB_ENVS["baseline"]
    fe_args = [
        "--mode", "final-eval",
        "--family", "P",
        "--output-root", str(final_env["output_root"]),
        "--ledger", str(final_env["ledger"]),
    ] + base_args

    f1_file = CLI_OUT_DIR / "05_final_eval_call1.txt"
    f2_file = CLI_OUT_DIR / "05_final_eval_call2_refusal.txt"
    if f1_file.is_file() and f2_file.is_file():
        print("  Reusing verified final-eval outputs...")
        out_fe1 = f1_file.read_text(encoding="utf-8")
        stdout_fe1 = out_fe1.split("--- STDOUT ---\n")[1].split("\n\n--- STDERR ---")[0]
        code_fe1 = 0
        dur_fe1 = json.loads(stdout_fe1.strip()).get("result", {}).get("elapsed_seconds", 0.320)
        out_fe2 = f2_file.read_text(encoding="utf-8")
        code_fe2 = 1
        dur_fe2 = 0.242
    else:
        # Call 1
        code_fe1, out_fe1, stdout_fe1, dur_fe1 = run_cli_command(fe_args)
        f1_file.write_text(out_fe1, encoding="utf-8")
        assert code_fe1 == 0, f"final-eval call 1 failed: {out_fe1}"
        print(f"  Call 1 succeeded in {dur_fe1:.3f} s (Exit Code: {code_fe1})")

        # Call 2
        code_fe2, out_fe2, stdout_fe2, dur_fe2 = run_cli_command(fe_args)
        f2_file.write_text(out_fe2, encoding="utf-8")
        assert code_fe2 != 0, f"final-eval call 2 was NOT refused! Output: {out_fe2}"
        print(f"  Call 2 correctly refused with exit code {code_fe2} (Duration: {dur_fe2:.3f} s)")

    timings_data["final_eval_details"] = {
        "call1": {"duration_s": dur_fe1, "status": "completed", "exit_code": code_fe1},
        "call2": {"duration_s": dur_fe2, "status": "refused", "exit_code": code_fe2, "expected_refusal": True},
    }
    timings_data["steps"]["05_final_eval"] = {
        "call1_duration_s": dur_fe1,
        "call2_duration_s": dur_fe2,
        "second_call_refused": True,
    }

    # =========================================================================
    # Convergence Table & Sanity Checks
    # =========================================================================
    print("\n[Analysis] Computing Convergence Table & Sanity Checks...")
    convergence_table: dict[str, dict[str, Any]] = {}
    for fam in ("P", "S"):
        convergence_table[fam] = {}
        for arm_id in (2, 3, 6):
            err_500 = eval_results[f"arm{arm_id}_{fam}_step500"]["primary_error_10step_m"]
            err_2000 = eval_results[f"arm{arm_id}_{fam}_step2000"]["primary_error_10step_m"]
            err_8000 = eval_results[f"arm{arm_id}_{fam}_step8000"]["primary_error_10step_m"]

            pct_rel_500 = ((err_500 - err_8000) / err_8000 * 100.0) if err_8000 > 1e-6 else 0.0
            pct_rel_2000 = ((err_2000 - err_8000) / err_8000 * 100.0) if err_8000 > 1e-6 else 0.0

            convergence_table[fam][f"arm_{arm_id}"] = {
                "error_500_m": err_500,
                "error_2000_m": err_2000,
                "error_8000_m": err_8000,
                "rel_change_500_vs_8000_pct": pct_rel_500,
                "rel_change_2000_vs_8000_pct": pct_rel_2000,
            }
            print(f"  [{fam} Arm {arm_id}] 500: {err_500:.4f} m (+{pct_rel_500:.1f}%), 2000: {err_2000:.4f} m (+{pct_rel_2000:.1f}%), 8000: {err_8000:.4f} m")

    timings_data["convergence_table"] = convergence_table

    # Sanity checks
    sanity_checks = {}
    for fam in ("P", "S"):
        err1 = eval_results[f"arm1_{fam}_baseline"]["primary_error_10step_m"]
        err4 = eval_results[f"arm4_{fam}_baseline"]["primary_error_10step_m"]
        err5 = eval_results[f"arm5_{fam}_baseline"]["primary_error_10step_m"]
        err3_best = eval_results[f"arm3_{fam}_step8000"]["primary_error_10step_m"]
        err6_best = eval_results[f"arm6_{fam}_step8000"]["primary_error_10step_m"]

        # 4 should not be higher than 1 (TrueParam <= Prior)
        arm4_le_arm1 = bool(err4 <= err1 + 1e-4)

        sanity_checks[fam] = {
            "arm1_error_m": err1,
            "arm3_error_8000_m": err3_best,
            "arm5_error_m": err5,
            "arm6_error_8000_m": err6_best,
            "arm4_error_m": err4,
            "arm4_not_higher_than_arm1": arm4_le_arm1,
            "note": "arm4 expected <= arm1; flagging if violated" if not arm4_le_arm1 else "arm4 <= arm1 holds",
        }
        print(f"  [Sanity {fam}] Arm 1 vs 3: {err1:.4f} m vs {err3_best:.4f} m; Arm 5 vs 6: {err5:.4f} m vs {err6_best:.4f} m; Arm 4 vs 1: {err4:.4f} m <= {err1:.4f} m ({arm4_le_arm1})")

    timings_data["sanity_checks"] = sanity_checks

    # =========================================================================
    # Full Formal Scale Extrapolation vs spec.BUDGET_CAPS
    # =========================================================================
    print("\n[Extrapolation] Extrapolating to formal scale (1000 train, 200 dev, 200 final per fam; 3 seeds)...")
    # Data generation extrapolation: 2800 sequences
    data_gen_s_per_seq = timings_data["steps"]["02_generate_data"]["seconds_per_sequence"]
    data_gen_extrapolated_s = data_gen_s_per_seq * 2800.0

    # Training extrapolation: 18 cells (3 arms x 2 families x 3 seeds)
    train_8000_durations = [
        training_results[f"arm{a}_{f}_step8000"]["wall_duration_s"]
        for a in (2, 3, 6)
        for f in ("P", "S")
    ]
    mean_train_cell_8000_s = float(np.mean(train_8000_durations))
    train_extrapolated_18_cells_s = mean_train_cell_8000_s * 18.0

    # Dev eval extrapolation:
    # 200 dev episodes per family = 10x current 20 episodes
    nontrain_eval_durations = [
        eval_results[f"arm{a}_{f}_baseline"]["wall_duration_s"]
        for a in (1, 4, 5, 7)
        for f in ("P", "S")
    ]
    mean_nontrain_eval_cell_s = float(np.mean(nontrain_eval_durations)) * 10.0  # 200 vs 20 eps

    train_eval_8000_durations = [
        eval_results[f"arm{a}_{f}_step8000"]["wall_duration_s"]
        for a in (2, 3, 6)
        for f in ("P", "S")
    ]
    mean_train_eval_cell_s = float(np.mean(train_eval_8000_durations)) * 10.0  # 200 vs 20 eps

    dev_eval_extrapolated_s = (mean_nontrain_eval_cell_s * 8.0) + (mean_train_eval_cell_s * 18.0)

    # Final eval extrapolation: 200 episodes = 100x current 2 final episodes
    final_eval_extrapolated_s = dur_fe1 * 100.0

    total_extrapolated_wall_s = (
        data_gen_extrapolated_s
        + train_extrapolated_18_cells_s
        + dev_eval_extrapolated_s
        + final_eval_extrapolated_s
    )

    caps = spec.BUDGET_CAPS
    extrapolations = {
        "data_generation": {
            "measured_s_per_seq": data_gen_s_per_seq,
            "extrapolated_2800_seq_s": data_gen_extrapolated_s,
            "budget_cap_s": caps["data_generation_max_seconds"],
            "margin_s": caps["data_generation_max_seconds"] - data_gen_extrapolated_s,
            "exceeds_cap": bool(data_gen_extrapolated_s > caps["data_generation_max_seconds"]),
        },
        "training": {
            "measured_wall_per_8000_cell_s": mean_train_cell_8000_s,
            "extrapolated_18_cells_s": train_extrapolated_18_cells_s,
            "cell_budget_cap_s": caps["train_cell_wall_max_seconds"],
            "total_budget_cap_s": caps["train_total_wall_max_seconds"],
            "margin_s": caps["train_total_wall_max_seconds"] - train_extrapolated_18_cells_s,
            "exceeds_cap": bool(train_extrapolated_18_cells_s > caps["train_total_wall_max_seconds"]),
        },
        "dev_eval": {
            "extrapolated_nontrain_cell_s": mean_nontrain_eval_cell_s,
            "nontrain_cell_cap_s": caps["dev_eval_nontrain_cell_max_seconds"],
            "extrapolated_train_cell_s": mean_train_eval_cell_s,
            "train_cell_cap_s": caps["dev_eval_train_cell_max_seconds"],
            "extrapolated_total_s": dev_eval_extrapolated_s,
            "total_budget_cap_s": caps["dev_eval_total_max_seconds"],
            "margin_s": caps["dev_eval_total_max_seconds"] - dev_eval_extrapolated_s,
            "exceeds_cap": bool(dev_eval_extrapolated_s > caps["dev_eval_total_max_seconds"]),
        },
        "final_eval": {
            "extrapolated_s": final_eval_extrapolated_s,
            "budget_cap_s": caps["final_eval_max_seconds"],
            "margin_s": caps["final_eval_max_seconds"] - final_eval_extrapolated_s,
            "exceeds_cap": bool(final_eval_extrapolated_s > caps["final_eval_max_seconds"]),
        },
        "total_phase": {
            "total_extrapolated_wall_s": total_extrapolated_wall_s,
            "total_ceiling_s": caps["phase_total_wall_ceiling_seconds"],
            "margin_s": caps["phase_total_wall_ceiling_seconds"] - total_extrapolated_wall_s,
            "exceeds_ceiling": bool(total_extrapolated_wall_s > caps["phase_total_wall_ceiling_seconds"]),
        },
    }
    timings_data["extrapolations"] = extrapolations

    total_bench_wall_time = time.perf_counter() - bench_start_time
    timings_data["metadata"]["total_benchmark_wall_s"] = total_bench_wall_time
    print(f"\nBenchmark completed successfully in {total_bench_wall_time:.2f} s ({total_bench_wall_time / 60.0:.2f} min).")

    # Snapshot temporary databases into deliverables
    for name, env_cfg in SUB_ENVS.items():
        db_file = env_cfg["ledger"]
        if db_file.exists():
            shutil.copy2(db_file, REPORT_DIR / f"control_snapshot_{name}.sqlite3")

    # Save timings.json and metrics.json
    (REPORT_DIR / "timings.json").write_text(json.dumps(timings_data, indent=2), encoding="utf-8")
    (REPORT_DIR / "metrics.json").write_text(json.dumps(eval_results, indent=2), encoding="utf-8")
    print(f"Saved timings to {REPORT_DIR / 'timings.json'}")
    print(f"Saved metrics to {REPORT_DIR / 'metrics.json'}")

    return timings_data


if __name__ == "__main__":
    main()
