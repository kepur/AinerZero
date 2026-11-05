"""Smoke execution, measurement, and reporting harness for E1 benchmark (ainerzero.V9.P92).

Executes the required E1 convergence smoke testing under Revision r3:
- Isolated temporary environment in smoke_env/
- Injected smoke counts: P, S families each: train 200, development 40, final 2 (total 484 sequences)
- B28 velocity injection audit on raw trajectories (velocity_injection="kinematic_preroll_2f_v1", relative error < 5%)
- Dev collision event statistics for P and S
- Train Arms 2, 3, 6 across P, S at 2000, 8000, 32000 steps (18 runs total)
- Strict pairwise check on checkpoint SHAs: sha(arm2) != sha(arm3) != sha(arm6)
- Dev evaluation of baseline arms 1, 4, 5, 7 and trained arms 2, 3, 6 across all step tiers (26 runs)
- P92 Check 1: Verify net arms 2, 3, 6 e_1 across steps are NOT all identical
- P92 Check 2: Cross-run comparison table between P90 and P92 (e_1, e_10)
- P92 Check 3: Arm 4 treated as true parameter diagnosis (真参数诊断) rather than upper bound
- Final-eval read-once execution & refusal confirmation
- Convergence Table: e_10 across 2000, 8000, 32000 and % delta vs 32000; plus e_1, e_5, e_30 and available episode counts
- Step Selection Rule recommendation (min steps within 5% of 32000)
- Residual Diagnostics:
  * e_1 for Arm 3 vs Arm 1, and Arm 6 vs Arm 5 across families and step tiers
  * e_k error compounding trajectory across k in {1, 5, 10, 30}
- Sanity Checks:
  1. Arm 1 resting box step 1 position error mean < 1 cm (0.01 m)
  2. Arm 5 vs Arm 1 divergence ratio (>1e-6) and identified_subspace_dim distribution
  3. Arm 4 true parameter diagnosis vs Arm 1 and Arm 5
- Extrapolate formal scale budget vs spec.BUDGET_CAPS using recommended steps
- Periodic Relay heartbeat execution
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

AGENT_ID = "gemini-h2x5"
TASK_ID = "ainerzero.V9.P92"

BASE_DIR = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = BASE_DIR / "reports" / "V9-E1SMOKE5" / AGENT_ID
CLI_OUT_DIR = REPORT_DIR / "cli_outputs"
SMOKE_ENV = REPORT_DIR / "smoke_env"

DATA_DIR = SMOKE_ENV / "datasets"
LOCK_PATH = SMOKE_ENV / "lock.lock"
PREREG_PATH = SMOKE_ENV / "prereg.json"
RESEARCH_LOG_PATH = SMOKE_ENV / "RESEARCH_LOG.md"
HELPERS_DIR = SMOKE_ENV / "helpers"

P90_METRICS_PATH = BASE_DIR / "reports" / "V9-E1SMOKE4" / "gemini-q8m2" / "metrics.json"

STEP_TIERS = [2000, 8000, 32000]
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
    "P": {"train": 200, "development": 40, "final": 2},
    "S": {"train": 200, "development": 40, "final": 2},
}


def send_relay_heartbeat(msg: str) -> None:
    """Send heartbeat to AinerRelay."""
    try:
        cmd = [
            "python3",
            "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay",
            "heartbeat",
            TASK_ID,
            "--agent",
            AGENT_ID,
            "--msg",
            msg,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        print(f"  [Heartbeat] {msg} -> Exit {res.returncode}: {res.stdout.strip()}")
    except Exception as exc:
        print(f"  [Heartbeat Error] Failed to send heartbeat: {exc}")


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

    # 0. Setup sitecustomize helper:
    # (a) inject smoke counts into DefaultCellRunner.run_generate_data
    # (b) record identified_subspace_dim in evaluate_episode for Arm 5
    sitecustomize_py = HELPERS_DIR / "sitecustomize.py"
    sitecustomize_py.write_text(
        """\"\"\"Helper sitecustomize to inject data generation counts & capture metadata.\"\"\"
from __future__ import annotations
import json, os

try:
    from ainerzero.v9.experiments.e1 import worker
    _orig_gen = worker.DefaultCellRunner.run_generate_data
    def _patched_gen(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs):
        c = os.environ.get("E1_SMOKE_COUNTS")
        if c and "counts" not in kwargs:
            kwargs["counts"] = json.loads(c)
        return _orig_gen(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs)
    worker.DefaultCellRunner.run_generate_data = _patched_gen
except ImportError:
    pass

try:
    from ainerzero.v9.experiments.e1 import arms_nonnet, eval_runner

    _orig_arm5_predict = arms_nonnet.IdentifyArm.predict
    def _patched_arm5_predict(self, observed_prefix, static_env, n_future, **kwargs):
        res = _orig_arm5_predict(self, observed_prefix, static_env, n_future, **kwargs)
        self.last_identified_subspace_dim = getattr(res, "identified_subspace_dim", None)
        return res
    arms_nonnet.IdentifyArm.predict = _patched_arm5_predict

    _orig_eval_ep = eval_runner.evaluate_episode
    def _patched_eval_ep(arm, student_ep, truth_ep, arm_name=None):
        res = _orig_eval_ep(arm, student_ep, truth_ep, arm_name=arm_name)
        if hasattr(arm, "last_identified_subspace_dim") and arm.last_identified_subspace_dim is not None:
            res["identified_subspace_dim"] = arm.last_identified_subspace_dim
        return res
    eval_runner.evaluate_episode = _patched_eval_ep
except ImportError:
    pass
""",
        encoding="utf-8",
    )

    if LOCK_PATH.exists():
        LOCK_PATH.unlink()

    # Setup prereg and research log
    sys.path.insert(0, str(BASE_DIR / "src"))
    from ainerzero.v9.experiments.e1 import prereg, spec

    draft = prereg.build_draft()
    frozen, doc_sha = prereg.freeze(draft, output_path=PREREG_PATH)
    RESEARCH_LOG_PATH.write_text(
        f"""# Isolated Temporary Research Log for E1 Convergence Smoke (P92)

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
            "task_id": TASK_ID,
            "agent": AGENT_ID,
            "experiment_id": spec.EXPERIMENT_ID,
            "document_sha256": doc_sha,
            "smoke_counts": SMOKE_COUNTS,
            "step_tiers": STEP_TIERS,
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
        "step_selection": {},
        "residual_diagnostics": {},
        "sanity_checks": {},
        "net_arms_e1_distinctness_audit": {},
        "p90_vs_p92_comparison": {},
        "extrapolations": {},
    }

    send_relay_heartbeat("Step 1: Starting verify")

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

    send_relay_heartbeat("Step 2: Starting generate-data (484 sequences)")

    # =========================================================================
    # Step 2: generate-data (P, S: train 200, dev 40, final 2 = 484 sequences)
    # =========================================================================
    print("\n[Step 2/5] Executing generate-data (484 sequences across P and S)...")
    total_seqs = (200 + 40 + 2) * 2

    gen_args = ["--mode", "generate-data", "--output-root", str(SUB_ENVS["baseline"]["output_root"]), "--ledger", str(SUB_ENVS["baseline"]["ledger"])] + base_args
    code2, out2, stdout2, dur2 = run_cli_command(
        gen_args,
        env_vars={"E1_SMOKE_COUNTS": json.dumps(SMOKE_COUNTS)},
    )
    (CLI_OUT_DIR / "02_generate_data.txt").write_text(out2, encoding="utf-8")
    assert code2 == 0, f"generate-data failed: {out2}"

    s_per_seq = dur2 / float(total_seqs)
    print(f"  generate-data completed in {dur2:.3f} s (484 seqs, {s_per_seq:.3f} s/seq)")
    timings_data["steps"]["02_generate_data"] = {
        "duration_s": dur2,
        "status": "completed",
        "exit_code": code2,
        "total_sequences_generated": total_seqs,
        "seconds_per_sequence": s_per_seq,
    }

    send_relay_heartbeat(f"Step 2: Data generated in {dur2:.1f}s. Auditing B28 velocity injection.")

    # Audit B28 Velocity Injection
    print("\n  [Audit B28] Checking velocity injection in raw trajectories...")
    raw_dir = DATA_DIR / "raw"
    assert raw_dir.is_dir(), f"Missing raw directory at {raw_dir}"

    raw_files = list(raw_dir.rglob("*.json"))
    raw_seq_files = [f for f in raw_files if f.name != "manifest.json"]
    print(f"    Discovered {len(raw_seq_files)} raw sequence JSON files.")
    assert len(raw_seq_files) == total_seqs, f"Expected {total_seqs} sequence files, found {len(raw_seq_files)}"

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
    print("\n  [Dev Collision Statistics] Counting collision events on development partitions (40 eps/fam)...")
    from ainerzero.v9.experiments.e1.metrics import detect_collision_events

    dev_collision_stats = {}
    for fam in ("P", "S"):
        evaluator_dev_dir = DATA_DIR / "evaluator" / fam / "development"
        eval_files = sorted(list(evaluator_dev_dir.glob("*.json")))
        ep_count = len(eval_files)
        assert ep_count == 40, f"Expected 40 dev episodes for {fam}, got {ep_count}"

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
    # Step 3: train Arms 2, 3, 6 across P, S at 2000, 8000, 32000 steps (18 runs)
    # =========================================================================
    print("\n[Step 3/5] Executing train for Arms 2, 3, 6 x P, S x 2000, 8000, 32000 steps (18 runs)...")
    training_results: dict[str, dict[str, Any]] = {}
    checkpoint_paths: dict[tuple[int, str, int], Path] = {}
    checkpoint_shas: dict[tuple[int, str, int], str] = {}

    for steps in STEP_TIERS:
        send_relay_heartbeat(f"Step 3: Starting training tier steps={steps}")
        env_cfg = SUB_ENVS[f"steps_{steps}"]
        for fam in ("P", "S"):
            for arm_id in (2, 3, 6):
                cell_key = f"arm{arm_id}_{fam}_step{steps}"
                out_path = CLI_OUT_DIR / f"03_train_{cell_key}.txt"

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
                send_relay_heartbeat(f"Step 3: Completed {cell_key} in {dur_t:.1f}s")

    timings_data["training_details"] = training_results
    timings_data["steps"]["03_train"] = {
        "num_runs": len(training_results),
        "total_wall_s": sum(r["wall_duration_s"] for r in training_results.values()),
    }

    send_relay_heartbeat(f"Step 3: Training complete ({len(training_results)} runs). Auditing checkpoint SHAs.")

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
    # Step 4: eval on development partition (26 runs)
    # (a) Baseline non-trainable arms: 1, 4, 5, 7 on P and S (8 runs)
    # (b) Trained arms: 2, 3, 6 across 2000, 8000, 32000 on P and S (18 runs)
    # =========================================================================
    print("\n[Step 4/5] Executing dev evaluation (26 runs)...")
    send_relay_heartbeat("Step 4: Starting dev evaluation (26 runs)")
    eval_results: dict[str, dict[str, Any]] = {}
    raw_eval_jsons: dict[str, dict[str, Any]] = {}

    def parse_eval_output(stdout_str: str, dur_val: float, arm_val: int, fam_val: str, tier_val: Any) -> tuple[dict[str, Any], float, float]:
        payload = json.loads(stdout_str.strip())
        res = payload.get("result", {})
        summary = res.get("summary") or res.get("metrics") or {}
        k_step = summary.get("k_step_errors") or {}
        k_avail = summary.get("k_step_n_available") or {}
        p_err = float(summary.get("primary_error_m", 0.0))
        c_f1 = float(summary.get("collision_f1", 0.0))
        num_eps = summary.get("num_episodes", res.get("episodes_evaluated", 40))
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
            "k_step_errors": k_step,
            "k_step_n_available": k_avail,
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

            eval_json_file = base_env["output_root"] / "eval" / f"eval_arm{arm_id}_{fam}_none.json"
            if eval_json_file.is_file():
                raw_eval_jsons[eval_key] = json.loads(eval_json_file.read_text(encoding="utf-8"))

            print(f"        10-step error: {p_err:.4f} m, F1: {c_f1:.4f}, wall: {dur_e:.3f} s")

    # (b) Trained arms 2, 3, 6 across step tiers
    print("  (b) Evaluating trained arms 2, 3, 6 across step tiers (2000, 8000, 32000)...")
    for steps in STEP_TIERS:
        send_relay_heartbeat(f"Step 4: Evaluating trained arms at steps={steps}")
        env_cfg = SUB_ENVS[f"steps_{steps}"]
        for fam in ("P", "S"):
            for arm_id in (2, 3, 6):
                eval_key = f"arm{arm_id}_{fam}_step{steps}"
                out_file = CLI_OUT_DIR / f"04_eval_{eval_key}.txt"

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

                eval_json_file = env_cfg["output_root"] / "eval" / f"eval_arm{arm_id}_{fam}_42.json"
                if eval_json_file.is_file():
                    raw_eval_jsons[eval_key] = json.loads(eval_json_file.read_text(encoding="utf-8"))

                print(f"        10-step error: {p_err:.4f} m, F1: {c_f1:.4f}, wall: {dur_e:.3f} s")

    timings_data["evaluation_details"] = eval_results
    timings_data["steps"]["04_eval"] = {
        "num_runs": len(eval_results),
        "total_wall_s": sum(r["wall_duration_s"] for r in eval_results.values()),
    }

    # =========================================================================
    # P92 New Check 1: ②③⑥ in each step tier e_1 must NOT be all identical
    # =========================================================================
    print("\n[P92 Check 1] Verifying that net arms ②③⑥ e_1 across steps are NOT all identical...")
    e1_p_vals = [eval_results[f"arm{a}_P_step{s}"]["mean_error_1step_m"] for a in (2, 3, 6) for s in STEP_TIERS]
    e1_s_vals = [eval_results[f"arm{a}_S_step{s}"]["mean_error_1step_m"] for a in (2, 3, 6) for s in STEP_TIERS]

    distinct_e1_p = len(set(round(float(x), 6) for x in e1_p_vals))
    distinct_e1_s = len(set(round(float(x), 6) for x in e1_s_vals))

    print(f"  Family P: distinct e_1 count = {distinct_e1_p} / {len(e1_p_vals)} (Values: {[round(x, 5) for x in e1_p_vals]})")
    print(f"  Family S: distinct e_1 count = {distinct_e1_s} / {len(e1_s_vals)} (Values: {[round(x, 5) for x in e1_s_vals]})")

    assert distinct_e1_p > 1, f"DEFECT DETECTED: All net arms in Family P have identical e_1 ({e1_p_vals[0]})! Revision r3 offset bug may still be present!"
    assert distinct_e1_s > 1, f"DEFECT DETECTED: All net arms in Family S have identical e_1 ({e1_s_vals[0]})! Revision r3 offset bug may still be present!"

    timings_data["net_arms_e1_distinctness_audit"] = {
        "passed": True,
        "family_P_distinct_count": distinct_e1_p,
        "family_S_distinct_count": distinct_e1_s,
        "family_P_e1_sample": [round(float(x), 6) for x in e1_p_vals],
        "family_S_e1_sample": [round(float(x), 6) for x in e1_s_vals],
        "summary": f"Net arms exhibit {distinct_e1_p} distinct e_1 values in P and {distinct_e1_s} in S (non-identical). Defect resolved.",
    }

    # =========================================================================
    # Step 5: final-eval (execute once, verify refusal on second call)
    # =========================================================================
    print("\n[Step 5/5] Executing final-eval and testing read-once refusal...")
    send_relay_heartbeat("Step 5: Testing final-eval read-once gate")
    final_env = SUB_ENVS["baseline"]
    fe_args = [
        "--mode", "final-eval",
        "--family", "P",
        "--output-root", str(final_env["output_root"]),
        "--ledger", str(final_env["ledger"]),
    ] + base_args

    f1_file = CLI_OUT_DIR / "05_final_eval_call1.txt"
    f2_file = CLI_OUT_DIR / "05_final_eval_call2_refusal.txt"

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
    # Convergence Table & Step Selection Rule (P92)
    # =========================================================================
    print("\n[Analysis] Computing Convergence Table (2000, 8000, 32000 steps)...")
    convergence_table: dict[str, dict[str, Any]] = {}
    
    for fam in ("P", "S"):
        convergence_table[fam] = {}
        for arm_id in (2, 3, 6):
            res_2k = eval_results[f"arm{arm_id}_{fam}_step2000"]
            res_8k = eval_results[f"arm{arm_id}_{fam}_step8000"]
            res_32k = eval_results[f"arm{arm_id}_{fam}_step32000"]

            err_2k = res_2k["primary_error_10step_m"]
            err_8k = res_8k["primary_error_10step_m"]
            err_32k = res_32k["primary_error_10step_m"]

            pct_rel_2k = ((err_2k - err_32k) / err_32k * 100.0) if err_32k > 1e-6 else 0.0
            pct_rel_8k = ((err_8k - err_32k) / err_32k * 100.0) if err_32k > 1e-6 else 0.0

            convergence_table[fam][f"arm_{arm_id}"] = {
                "e_10": {
                    "2000": err_2k,
                    "8000": err_8k,
                    "32000": err_32k,
                },
                "delta_vs_32000_pct": {
                    "2000": pct_rel_2k,
                    "8000": pct_rel_8k,
                    "32000": 0.0,
                },
                "e_1": {
                    "2000": res_2k["mean_error_1step_m"],
                    "8000": res_8k["mean_error_1step_m"],
                    "32000": res_32k["mean_error_1step_m"],
                },
                "e_5": {
                    "2000": res_2k["mean_error_5step_m"],
                    "8000": res_8k["mean_error_5step_m"],
                    "32000": res_32k["mean_error_5step_m"],
                },
                "e_30": {
                    "2000": res_2k["mean_error_30step_m"],
                    "8000": res_8k["mean_error_30step_m"],
                    "32000": res_32k["mean_error_30step_m"],
                },
                "n_available": {
                    "2000": res_2k["k_step_n_available"],
                    "8000": res_8k["k_step_n_available"],
                    "32000": res_32k["k_step_n_available"],
                },
            }
            print(f"  [{fam} Arm {arm_id}] e_10: 2000={err_2k:.4f}m ({pct_rel_2k:+.1f}%), 8000={err_8k:.4f}m ({pct_rel_8k:+.1f}%), 32000={err_32k:.4f}m")

    timings_data["convergence_table"] = convergence_table

    # Step Selection Rule:
    steps_within_5pct = []
    for cand_s in (2000, 8000, 32000):
        all_within = True
        for fam in ("P", "S"):
            for arm_id in (2, 3, 6):
                d_pct = abs(convergence_table[fam][f"arm_{arm_id}"]["delta_vs_32000_pct"][str(cand_s)])
                if d_pct > 5.0:
                    all_within = False
        if all_within:
            steps_within_5pct.append(cand_s)

    any_improved_over_5pct = False
    improvement_details = {}
    for fam in ("P", "S"):
        for arm_id in (2, 3, 6):
            err_8k = convergence_table[fam][f"arm_{arm_id}"]["e_10"]["8000"]
            err_32k = convergence_table[fam][f"arm_{arm_id}"]["e_10"]["32000"]
            rel_improv = (err_8k - err_32k) / err_8k * 100.0 if err_8k > 1e-6 else 0.0
            improvement_details[f"{fam}_arm{arm_id}"] = rel_improv
            if rel_improv > 5.0:
                any_improved_over_5pct = True

    if 8000 in steps_within_5pct and not any_improved_over_5pct:
        recommended_steps = 8000
        convergence_status = "fully_confirmed_at_8000"
        recommendation_note = "8000 steps achieves <= 5% difference from 32000 across all arms and families without further >5% gains."
    else:
        recommended_steps = 32000
        convergence_status = "suggest_32000_convergence_not_fully_confirmed"
        recommendation_note = (
            "8000->32000 steps still yields > 5% improvement on at least one arm/family "
            "(or 8000 steps exceeds 5% error margin). Recommend 32000 steps, with convergence not fully confirmed."
        )

    print(f"\n  [Step Selection Recommendation]: {recommended_steps} steps ({convergence_status})")
    print(f"    Note: {recommendation_note}")
    timings_data["step_selection"] = {
        "candidate_steps": [2000, 8000, 32000],
        "steps_within_5pct_of_32000": steps_within_5pct,
        "improvement_8k_to_32k_pct": improvement_details,
        "any_improved_over_5pct": any_improved_over_5pct,
        "recommended_steps": recommended_steps,
        "convergence_status": convergence_status,
        "recommendation_note": recommendation_note,
    }

    # =========================================================================
    # Residual Diagnostics (P92)
    # =========================================================================
    print("\n[Residual Diagnostics] Evaluating e_1 single-step and horizon compounding...")
    res_diag: dict[str, Any] = {
        "single_step_e1_comparison": {},
        "error_compounding_trajectory": {},
    }

    # (a) Compare e_1 for Arm 3 vs Arm 1, and Arm 6 vs Arm 5
    for fam in ("P", "S"):
        e1_arm1 = eval_results[f"arm1_{fam}_baseline"]["mean_error_1step_m"]
        e1_arm5 = eval_results[f"arm5_{fam}_baseline"]["mean_error_1step_m"]

        diag_fam = {
            "arm1_baseline_e1": e1_arm1,
            "arm5_baseline_e1": e1_arm5,
            "arm3_vs_arm1": {},
            "arm6_vs_arm5": {},
        }
        for steps in STEP_TIERS:
            e1_arm3 = eval_results[f"arm3_{fam}_step{steps}"]["mean_error_1step_m"]
            e1_arm6 = eval_results[f"arm6_{fam}_step{steps}"]["mean_error_1step_m"]

            diag_fam["arm3_vs_arm1"][str(steps)] = {
                "arm3_e1": e1_arm3,
                "arm1_e1": e1_arm1,
                "diff_m": e1_arm3 - e1_arm1,
                "arm3_lower": bool(e1_arm3 < e1_arm1),
            }
            diag_fam["arm6_vs_arm5"][str(steps)] = {
                "arm6_e1": e1_arm6,
                "arm5_e1": e1_arm5,
                "diff_m": e1_arm6 - e1_arm5,
                "arm6_lower": bool(e1_arm6 < e1_arm5),
            }

        res_diag["single_step_e1_comparison"][fam] = diag_fam

    # (b) Error trajectory across k in {1, 5, 10, 30} for all arms
    for fam in ("P", "S"):
        traj_fam: dict[str, Any] = {}
        for arm_id in (1, 4, 5, 7):
            rec = eval_results[f"arm{arm_id}_{fam}_baseline"]
            traj_fam[f"arm_{arm_id}_baseline"] = {
                "e_1": rec["mean_error_1step_m"],
                "e_5": rec["mean_error_5step_m"],
                "e_10": rec["mean_error_10step_m"],
                "e_30": rec["mean_error_30step_m"],
            }
        for arm_id in (2, 3, 6):
            for steps in STEP_TIERS:
                rec = eval_results[f"arm{arm_id}_{fam}_step{steps}"]
                traj_fam[f"arm_{arm_id}_step{steps}"] = {
                    "e_1": rec["mean_error_1step_m"],
                    "e_5": rec["mean_error_5step_m"],
                    "e_10": rec["mean_error_10step_m"],
                    "e_30": rec["mean_error_30step_m"],
                }
        res_diag["error_compounding_trajectory"][fam] = traj_fam

    timings_data["residual_diagnostics"] = res_diag

    # =========================================================================
    # Sanity Checks & Diagnoses (P92)
    # 1. Arm 1 Resting Box physics step 1 error < 1 cm (0.01 m)
    # 2. Arm 5 vs Arm 1 divergence (>1e-6) and identified_subspace_dim distribution
    # 3. Arm 4 True Parameter Diagnosis (真参数诊断, 不再按上界判定)
    # =========================================================================
    print("\n[Sanity Checks & Diagnoses] Evaluating required items...")
    sanity_p92: dict[str, Any] = {}

    # Check 1: Resting box step 1 position error under Arm 1
    resting_box_step1_errors = []
    resting_box_details = []

    for fam in ("P", "S"):
        eval_arm1_data = raw_eval_jsons.get(f"arm1_{fam}_baseline", {})
        student_dir = DATA_DIR / "student" / fam / "development"

        for ep_rec in eval_arm1_data.get("episodes", []):
            sid = ep_rec.get("sequence_id")
            s_file = student_dir / f"student_{sid}.json"
            if not s_file.is_file():
                s_cand = list(student_dir.glob(f"*{sid}*.json"))
                if s_cand:
                    s_file = s_cand[0]
            if not s_file.is_file():
                continue

            s_data = json.loads(s_file.read_text(encoding="utf-8"))
            active_bodies = s_data.get("active_bodies", {})
            frames = s_data.get("frames", [])
            if len(frames) < 11:
                continue

            pred_pos = ep_rec.get("pred_positions", {})

            for b_name, b_info in active_bodies.items():
                shape = b_info.get("shape", "").upper()
                if shape != "BOX":
                    continue

                f0_obj = frames[0].get("objects", {}).get(b_name, {})
                v0 = f0_obj.get("linear_velocity", [0.0, 0.0, 0.0])
                speed0 = float(np.linalg.norm(v0))

                if speed0 < 1e-3:  # Resting box
                    if b_name in pred_pos and len(pred_pos[b_name]) > 0:
                        pred_step1 = np.asarray(pred_pos[b_name][0], dtype=np.float64)
                        truth_step1 = np.asarray(frames[10]["objects"][b_name]["position"], dtype=np.float64)
                        err_step1 = float(np.linalg.norm(pred_step1 - truth_step1))
                        resting_box_step1_errors.append(err_step1)
                        resting_box_details.append({
                            "family": fam,
                            "sequence_id": sid,
                            "body_name": b_name,
                            "initial_speed": speed0,
                            "step1_error_m": err_step1,
                        })

    mean_resting_box_step1_err = float(np.mean(resting_box_step1_errors)) if resting_box_step1_errors else 0.0
    check1_passed = bool(mean_resting_box_step1_err < 0.01)  # < 1 cm

    print(f"  [Check 1] Arm 1 Resting Box Step 1 Error: {mean_resting_box_step1_err * 100:.3f} cm ({mean_resting_box_step1_err:.6f} m) across {len(resting_box_step1_errors)} resting boxes.")
    print(f"            Requirement (< 1 cm / 0.01 m): {'PASS' if check1_passed else 'VIOLATION (FLAGGED)'} (P82 baseline was 0.905 m)")

    sanity_p92["check1_arm1_resting_box_step1"] = {
        "num_resting_boxes_audited": len(resting_box_step1_errors),
        "mean_step1_error_m": mean_resting_box_step1_err,
        "mean_step1_error_cm": mean_resting_box_step1_err * 100.0,
        "p82_reference_m": 0.905,
        "threshold_m": 0.01,
        "passed": check1_passed,
        "details_sample": resting_box_details[:5],
    }

    # Check 2: Arm 5 vs Arm 1 prediction difference & identified_subspace_dim distribution
    diff_episodes_count = 0
    total_compared_episodes = 0
    max_diffs_per_ep = []
    subspace_dim_counts: dict[int, int] = {}
    total_bodies_identified = 0

    for fam in ("P", "S"):
        arm1_eps = {ep["sequence_id"]: ep for ep in raw_eval_jsons.get(f"arm1_{fam}_baseline", {}).get("episodes", [])}
        arm5_eps = {ep["sequence_id"]: ep for ep in raw_eval_jsons.get(f"arm5_{fam}_baseline", {}).get("episodes", [])}

        for sid, ep5 in arm5_eps.items():
            if sid not in arm1_eps:
                continue
            ep1 = arm1_eps[sid]
            total_compared_episodes += 1

            sub_dim_map = ep5.get("identified_subspace_dim", {})
            for b_name, k_val in sub_dim_map.items():
                k_int = int(k_val)
                subspace_dim_counts[k_int] = subspace_dim_counts.get(k_int, 0) + 1
                total_bodies_identified += 1

            pred1_pos = ep1.get("pred_positions", {})
            pred5_pos = ep5.get("pred_positions", {})

            max_ep_diff = 0.0
            for b_name in pred5_pos:
                if b_name in pred1_pos:
                    p1_arr = np.asarray(pred1_pos[b_name], dtype=np.float64)
                    p5_arr = np.asarray(pred5_pos[b_name], dtype=np.float64)
                    min_len = min(len(p1_arr), len(p5_arr))
                    if min_len > 0:
                        diffs = np.linalg.norm(p5_arr[:min_len] - p1_arr[:min_len], axis=-1)
                        max_ep_diff = max(max_ep_diff, float(np.max(diffs)))

            max_diffs_per_ep.append({"sequence_id": sid, "family": fam, "max_diff": max_ep_diff})
            if max_ep_diff > 1e-6:
                diff_episodes_count += 1

    diff_ratio = (diff_episodes_count / float(total_compared_episodes)) if total_compared_episodes > 0 else 0.0
    check2_passed = bool(diff_episodes_count > 0)

    print(f"  [Check 2] Arm 5 vs Arm 1 Predictions Differ (>1e-6): {diff_episodes_count}/{total_compared_episodes} episodes ({diff_ratio*100:.1f}%).")
    print(f"            Subspace Dim Distribution: {subspace_dim_counts} (Total bodies: {total_bodies_identified}).")
    print(f"            Requirement (Arm 5 differs on >= 1 episode): {'PASS' if check2_passed else 'VIOLATION (FLAGGED)'}")

    sanity_p92["check2_arm5_vs_arm1"] = {
        "total_episodes_compared": total_compared_episodes,
        "episodes_differing_count": diff_episodes_count,
        "episodes_differing_ratio": diff_ratio,
        "identified_subspace_dim_distribution": {str(k): cnt for k, cnt in sorted(subspace_dim_counts.items())},
        "total_active_bodies": total_bodies_identified,
        "passed": check2_passed,
        "max_diff_sample": max_diffs_per_ep[:5],
    }

    # Diagnosis 3: Arm 4 True Parameter Diagnosis (真参数诊断, 不再作为上界检查)
    err1_p = eval_results["arm1_P_baseline"]["primary_error_10step_m"]
    err4_p = eval_results["arm4_P_baseline"]["primary_error_10step_m"]
    err5_p = eval_results["arm5_P_baseline"]["primary_error_10step_m"]
    err1_s = eval_results["arm1_S_baseline"]["primary_error_10step_m"]
    err4_s = eval_results["arm4_S_baseline"]["primary_error_10step_m"]
    err5_s = eval_results["arm5_S_baseline"]["primary_error_10step_m"]

    print(f"  [Diagnosis] Arm 4 True Parameter Diagnosis (真参数诊断):")
    print(f"              Family P: Arm 4 = {err4_p:.4f} m, Arm 1 = {err1_p:.4f} m, Arm 5 = {err5_p:.4f} m")
    print(f"              Family S: Arm 4 = {err4_s:.4f} m, Arm 1 = {err1_s:.4f} m, Arm 5 = {err5_s:.4f} m")

    sanity_p92["diagnosis_arm4_true_param"] = {
        "family_P": {"arm4_error_m": err4_p, "arm1_error_m": err1_p, "arm5_error_m": err5_p},
        "family_S": {"arm4_error_m": err4_s, "arm1_error_m": err1_s, "arm5_error_m": err5_s},
        "note": "Per P92 instruction, Arm 4 is evaluated strictly as true parameter diagnosis, not an upper-bound check.",
    }

    timings_data["sanity_checks"] = sanity_p92

    # =========================================================================
    # P92 New Check 2: Cross-Run Comparison Table (P90 vs P92)
    # =========================================================================
    print("\n[P92 Check 2] Generating P90 -> P92 e_1 and e_10 comparison table...")
    p90_metrics = {}
    if P90_METRICS_PATH.is_file():
        p90_metrics = json.loads(P90_METRICS_PATH.read_text(encoding="utf-8"))

    p90_comparison: dict[str, Any] = {}
    for cell_key, p92_rec in sorted(eval_results.items()):
        p90_rec = p90_metrics.get(cell_key, {})
        p90_e1 = float(p90_rec.get("mean_error_1step_m", 0.0))
        p90_e10 = float(p90_rec.get("primary_error_10step_m", 0.0))
        p92_e1 = float(p92_rec.get("mean_error_1step_m", 0.0))
        p92_e10 = float(p92_rec.get("primary_error_10step_m", 0.0))

        fam = p92_rec["family"]
        arm_id = p92_rec["arm_id"]
        tier = p92_rec["step_tier"]
        arm_desc = f"Arm {arm_id} ({tier})"

        p90_comparison[cell_key] = {
            "family": fam,
            "arm_desc": arm_desc,
            "p90_e1": p90_e1,
            "p92_e1": p92_e1,
            "diff_e1": p92_e1 - p90_e1,
            "p90_e10": p90_e10,
            "p92_e10": p92_e10,
            "diff_e10": p92_e10 - p90_e10,
        }

    timings_data["p90_vs_p92_comparison"] = p90_comparison

    # =========================================================================
    # Full Formal Scale Extrapolation vs spec.BUDGET_CAPS
    # Formal scale: 2800 sequences (1000 train, 200 dev, 200 final per fam; 3 seeds)
    # 18 training cells at recommended_steps
    # =========================================================================
    print(f"\n[Extrapolation] Extrapolating formal budget using recommended steps = {recommended_steps}...")
    data_gen_s_per_seq = timings_data["steps"]["02_generate_data"]["seconds_per_sequence"]
    data_gen_extrapolated_s = data_gen_s_per_seq * 2800.0

    train_step_durations = [
        training_results[f"arm{a}_{f}_step{recommended_steps}"]["wall_duration_s"]
        for a in (2, 3, 6)
        for f in ("P", "S")
    ]
    mean_train_cell_s = float(np.mean(train_step_durations))
    train_extrapolated_18_cells_s = mean_train_cell_s * 18.0

    nontrain_eval_durations = [
        eval_results[f"arm{a}_{f}_baseline"]["wall_duration_s"]
        for a in (1, 4, 5, 7)
        for f in ("P", "S")
    ]
    mean_nontrain_eval_cell_s = float(np.mean(nontrain_eval_durations)) * (200.0 / 40.0)  # 200 vs 40 eps = 5x

    train_eval_durations = [
        eval_results[f"arm{a}_{f}_step{recommended_steps}"]["wall_duration_s"]
        for a in (2, 3, 6)
        for f in ("P", "S")
    ]
    mean_train_eval_cell_s = float(np.mean(train_eval_durations)) * (200.0 / 40.0)  # 200 vs 40 eps = 5x

    dev_eval_extrapolated_s = (mean_nontrain_eval_cell_s * 8.0) + (mean_train_eval_cell_s * 18.0)
    final_eval_extrapolated_s = dur_fe1 * (200.0 / 2.0)  # 200 vs 2 eps = 100x

    total_extrapolated_wall_s = (
        data_gen_extrapolated_s
        + train_extrapolated_18_cells_s
        + dev_eval_extrapolated_s
        + final_eval_extrapolated_s
    )

    caps = spec.BUDGET_CAPS
    extrapolations = {
        "recommended_steps": recommended_steps,
        "data_generation": {
            "measured_s_per_seq": data_gen_s_per_seq,
            "extrapolated_2800_seq_s": data_gen_extrapolated_s,
            "budget_cap_s": caps["data_generation_max_seconds"],
            "margin_s": caps["data_generation_max_seconds"] - data_gen_extrapolated_s,
            "exceeds_cap": bool(data_gen_extrapolated_s > caps["data_generation_max_seconds"]),
        },
        "training": {
            "recommended_steps": recommended_steps,
            "measured_wall_per_cell_s": mean_train_cell_s,
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

    # Generate REPORT.md and SHA256SUMS.txt
    sys.path.insert(0, str(REPORT_DIR))
    from generate_report import generate_report_md, compute_sha256sums
    rep_md = generate_report_md(timings_data, eval_results)
    (REPORT_DIR / "REPORT.md").write_text(rep_md, encoding="utf-8")
    compute_sha256sums()
    print("REPORT.md and SHA256SUMS.txt generated.")

    send_relay_heartbeat(f"Run completed in {total_bench_wall_time/60.0:.1f} min. Deliverables sealed.")


if __name__ == "__main__":
    main()
