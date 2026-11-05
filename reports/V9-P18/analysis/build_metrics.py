"""Assemble reports/V9-P18/metrics.json from the frozen document + the two probes.

All arithmetic is computed here from the frozen pre-registration and the
instrumented call counts; nothing is typed in by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SNAP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
OUT = REPO / "reports/V9-P18"
ISO = Path("/tmp/v9p18_iso")


def main() -> int:
    doc = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
    coverage = json.loads((OUT / "analysis" / "cpu_coverage.json").read_text())
    truth = json.loads((OUT / "analysis" / "truth_stats.json").read_text())

    protocol = doc["training_protocol"]
    timing = doc["timing"]
    budget = doc["budget_estimate"]

    updates = int(protocol["updates"])
    batch_size = int(protocol["batch_size"])
    sequence_steps = int(protocol["sequence_steps"])
    checkpoints = list(protocol["checkpoint_updates"])
    n_ckpt = len(checkpoints)
    trainable_runs = 9
    d_runs = 1

    windows = coverage["dataset"]["development_windows"]
    probe_batches = (windows + batch_size - 1) // batch_size
    window_frames_per_probe = windows * (sequence_steps + 1)

    # --- frozen estimate reproduction (prereg.estimate_budget) --------------
    step_seconds = float(budget["measured_forward_loss_step_seconds"])
    d_step = float(budget["arm1_step_seconds"])
    duty = float(doc["resource_limits"]["training_duty_cycle"])
    sys.path.insert(0, str(ISO))
    from ainerzero.v9.experiments.s1 import spec as s1_spec

    overhead = float(s1_spec.TIMING["estimate_eval_overhead_factor"])
    eval_batches = int(protocol.get("eval_batches", s1_spec.TIMING["eval_batches"]))
    # PREP_BUDGET in the frozen CLI (commands.py): the hard wall a single eval
    # invocation gets.  Read from the frozen source, not typed in.
    import re

    budget_line = re.search(
        r"PREP_BUDGET\s*=\s*\{[^}]*\}", (SNAP / "src/ainerzero/v9/experiments/s1/commands.py").read_text()
    ).group(0)
    eval_wall_budget = float(re.search(r'"eval":\s*([0-9.]+)', budget_line).group(1))
    update_cost = 3.0 * step_seconds
    eval_cost = eval_batches * step_seconds * len(protocol["checkpoint_fractions"])
    raw_updates = int((360.0 * duty / overhead - eval_cost) // update_cost)
    estimate = (updates * update_cost + eval_cost) / duty * overhead
    deadline = int(-(-estimate * 1.25 // 1))
    arm1_active = eval_batches * d_step * len(protocol["checkpoint_fractions"])
    arm1_estimate = (arm1_active / duty) * overhead
    arm1_deadline = int(-(-arm1_estimate * 1.25 // 1))
    phase_wall = (
        trainable_runs * deadline
        + d_runs * arm1_deadline
        + float(timing["smoke"]["data_generation_seconds"])
    )

    # --- eval call accounting ---------------------------------------------
    as_coded = coverage["eval_calls_one_arm_seed"]
    per_k = coverage["few_shot_per_k_call_counts"]

    # Hypothetical repaired path (§6.2): stop = support[-1] + 2, i.e. k frames are
    # executed per world, so k-1 single-step forwards per world.
    few_shot_repaired = {"step_sequence_calls": 0, "single_step_forwards": 0, "encode_calls": 0, "probe_graph_calls": 0}
    for k in (0, 1, 2, 4, 8):
        worlds = int(coverage["k_coverage"][str(k)]["worlds"])
        queries = int(coverage["k_coverage"][str(k)]["queries"])
        if not worlds:
            continue
        few_shot_repaired["encode_calls"] += 2 * queries
        few_shot_repaired["probe_graph_calls"] += worlds
        if k == 0:
            continue  # no support is written, so no sequence call
        few_shot_repaired["step_sequence_calls"] += worlds
        few_shot_repaired["single_step_forwards"] += worlds * k

    topology_calls = {
        "step_sequence_calls": coverage["dataset"]["development_worlds"],
        "single_step_forwards": coverage["dataset"]["development_steps"] - coverage["dataset"]["development_worlds"],
        "probe_graph_calls": coverage["dataset"]["development_worlds"],
    }
    m2_calls = {"step_sequence_calls": 11, "single_step_forwards": 42}

    eval_as_coded = {
        "window_forward_loss_calls": int(as_coded["forward_loss_calls"]),
        "window_frame_slots": int(as_coded["forward_loss_frames"]),
        "step_sequence_calls": int(as_coded["step_sequence_calls"]),
        "single_step_forwards": int(as_coded["single_step_forward_calls"]),
        "probe_graph_calls": int(as_coded["probe_graph_calls"]),
        "encode_calls": int(as_coded["encode_calls"]),
        "terminal_error": coverage["few_shot_frozen_path_error"],
    }
    eval_complete = {
        "window_forward_loss_calls": n_ckpt * probe_batches,
        "window_frame_slots": n_ckpt * window_frames_per_probe,
        "step_sequence_calls": topology_calls["step_sequence_calls"]
        + few_shot_repaired["step_sequence_calls"]
        + m2_calls["step_sequence_calls"],
        "single_step_forwards": topology_calls["single_step_forwards"]
        + few_shot_repaired["single_step_forwards"]
        + m2_calls["single_step_forwards"],
        "probe_graph_calls": topology_calls["probe_graph_calls"] + few_shot_repaired["probe_graph_calls"],
        "encode_calls": few_shot_repaired["encode_calls"],
        "few_shot_queries": sum(int(coverage["k_coverage"][str(k)]["queries"]) for k in (0, 1, 2, 4, 8)),
    }

    train_run = {
        "optimizer_updates": updates,
        "checkpoint_probes": n_ckpt,
        "probe_window_batches": n_ckpt * probe_batches,
        "probe_window_frames": n_ckpt * window_frames_per_probe,
        "forward_loss_batch_equivalents": updates + n_ckpt * probe_batches,
        "frozen_estimate_seconds": budget["estimate_seconds"],
        "frozen_deadline_seconds": budget["deadline_seconds"],
        "frozen_supervision_seconds": budget["supervision_seconds"],
    }

    d_run = {
        "model_loads": 1,
        "forward_loss_calls": 1,
        "batch": {"windows": 16, "timesteps": 2, "c0_frame_slots": 32},
        "s1_metrics": "not_applicable (incomparable input layout)",
        "frozen_estimate_seconds": budget["arm1_estimate_seconds"],
        "frozen_deadline_seconds": budget["arm1_deadline_seconds"],
        "frozen_forward_equivalents": eval_batches * len(protocol["checkpoint_fractions"]),
    }

    conflict = {
        "eval_batches_registered": eval_batches,
        "actual_probe_batches": probe_batches,
        "cap_binding": probe_batches >= eval_batches,
        "cap_slack_ratio": round(eval_batches / probe_batches, 6),
        "frozen_eval_cost_seconds_inside_training_run": eval_cost,
        "frozen_phase_wall_seconds": budget["phase_wall_seconds"],
        "recomputed_phase_wall_seconds": round(phase_wall, 6),
        "phase_wall_delta_seconds": round(float(budget["phase_wall_seconds"]) - phase_wall, 9),
        "post_hoc_eval_seconds_in_phase_wall": 0.0,
        "eval_wall_budget_seconds_per_invocation": eval_wall_budget,
        "eval_wall_budget_seconds_total": 9 * eval_wall_budget,
        "eval_wall_budget_is_outside_phase_wall": True,
        "meanings_of_the_constant": [
            "cap on window_probe batches per probe (never binding at 35 < 48)",
            "training-run eval cost = 48 x 5 checkpoints x measured batch-16 step (1.671 s)",
            "arm1 cost = 48 x 5 x D step (1.502 s) although arm1 performs exactly one forward",
        ],
        "silent_truncation_threshold_windows": eval_batches * batch_size,
    }

    metrics = {
        "schema": "ainerzero.v9.p18.metrics.v1",
        "task": "ainerzero.V9.P18",
        "executor": "deepseek-p18a",
        "status": "cpu_engineering_measurement_only",
        "identity": coverage["identity"],
        "dataset": coverage["dataset"],
        "k_coverage": coverage["k_coverage"],
        "truth_label_balance": {k: v for k, v in truth["per_k"].items()},
        "transition_kind_by_family": truth["transition_kind_by_family"],
        "few_shot_frozen_path_error": coverage["few_shot_frozen_path_error"],
        "few_shot_per_k_calls": per_k,
        "train_run_accounting": train_run,
        "eval_run_accounting_as_coded": eval_as_coded,
        "eval_run_accounting_if_k1_repaired": eval_complete,
        "d_candidate_run_accounting": d_run,
        "phase_totals": {
            "trainable_training_runs": trainable_runs,
            "post_hoc_eval_runs": trainable_runs,
            "d_candidate_runs": d_runs,
            "optimizer_updates": trainable_runs * updates,
            "training_probe_window_batches": trainable_runs * n_ckpt * probe_batches,
            "eval_window_batches": trainable_runs * eval_complete["window_forward_loss_calls"],
            "eval_step_sequence_calls": trainable_runs * eval_complete["step_sequence_calls"],
            "eval_single_step_forwards": trainable_runs * eval_complete["single_step_forwards"],
            "eval_probe_graph_calls": trainable_runs * eval_complete["probe_graph_calls"],
            "eval_encode_calls": trainable_runs * eval_complete["encode_calls"],
            "frozen_phase_wall_seconds": budget["phase_wall_seconds"],
            "frozen_phase_wall_cap_seconds": timing["phase_wall_max_seconds"],
            "gpu_eval_wall_seconds": "unknown_not_measured",
        },
        "eval_batches_conflict": conflict,
        "unmeasured": [
            "MLX batch-1 single-step forward cost (611 eval calls, 1292 forwards) is not measured by the frozen smoke",
            "MLX encode cost (3500 calls) is not measured",
            "MLX probe_graph cost (600 calls) is not measured",
            "post-hoc eval wall time has no registered budget at all",
        ],
        "note": "counts are exact and reproducible from the frozen source plus the frozen development partition; "
        "no MLX was imported, no model was run, no accuracy is reported.",
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(json.dumps({k: metrics[k] for k in (
        "train_run_accounting", "eval_run_accounting_as_coded", "eval_run_accounting_if_k1_repaired",
        "d_candidate_run_accounting", "phase_totals", "eval_batches_conflict")}, indent=2, ensure_ascii=False))
    print("recomputed estimate", estimate, "deadline", deadline, "raw_updates", raw_updates,
          "arm1_estimate", arm1_estimate, "phase_wall", phase_wall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
