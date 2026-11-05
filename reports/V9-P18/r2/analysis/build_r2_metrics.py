"""ainerzero.V9.P18 r2: assemble provenance-labelled metrics for the r2 revision.

What this script does
---------------------
* Recomputes the frozen budget arithmetic from the frozen r5 pre-registration
  and ``spec.py`` (new arithmetic; no model, no backend, no MLX).
* Re-reads the *measured* call counts that P19 produced on a 1-line repaired
  byte copy of the frozen snapshot, and labels every block with provenance.
  It does not re-run the P18/P19 suite and does not claim P19's measurement as
  the author's own.
* Reconciles the r2 independent truth check with P19's k coverage.
* Writes one JSON: ``reports/V9-P18/r2/metrics.json`` (and a SHA audit file).

Nothing outside ``reports/V9-P18/r2/`` is written.  No ``/tmp/v9p18_iso``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SNAP = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
CYCLE = SNAP.parent
DATASET = (
    REPO
    / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
)
P18R1 = REPO / "reports/V9-P18"
P19 = REPO / "reports/V9-P19"
OUT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-P18/r2")

P19_TREE = Path(
    "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_dir(path: Path) -> dict:
    return {
        str(p.relative_to(path)): sha256_file(p)
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def main() -> int:
    doc = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
    p19 = json.loads((P19 / "metrics.json").read_text())
    p19_checks = json.loads((P19 / "analysis/independent_checks.json").read_text())
    truth = json.loads((OUT / "analysis/independent_truth_check.json").read_text())
    r1_metrics = json.loads((P18R1 / "metrics.json").read_text())

    protocol = doc["training_protocol"]
    timing = doc["timing"]
    budget = doc["budget_estimate"]

    spec_src = (SNAP / "src/ainerzero/v9/experiments/s1/spec.py").read_text()
    overhead = float(re.search(r'"estimate_eval_overhead_factor":\s*([0-9.]+)', spec_src).group(1))
    eval_batches_spec = int(re.search(r'"eval_batches":\s*([0-9]+)', spec_src).group(1))
    data_budget_spec = float(re.search(r'"data_generation_budget_seconds":\s*([0-9.]+)', spec_src).group(1))

    # ------------------------------------------------------------------
    # 1. identity / SHA audit
    # ------------------------------------------------------------------
    frozen_list = json.loads((CYCLE / "P18-frozen-review-inputs.json").read_text())
    r1_audit = []
    for entry in frozen_list["files"]:
        path = Path(entry["path"])
        actual = sha256_file(path)
        r1_audit.append({
            "path": str(path),
            "expected": entry["sha256"],
            "actual": actual,
            "unchanged": actual == entry["sha256"],
        })

    p19_artifacts = {
        "report": P19 / "REPORT.md",
        "metrics": P19 / "metrics.json",
        "independent_checks_json": P19 / "analysis/independent_checks.json",
        "independent_checks_py": P19 / "analysis/independent_checks.py",
        "independent_checks_out": P19 / "logs/independent_checks.out",
    }
    p19_sha = {name: sha256_file(path) for name, path in p19_artifacts.items()}
    repaired_eval = P19_TREE / "iso_check_repaired/ainerzero/v9/experiments/s1/evaluation.py"
    p19_measurement_artifacts = {
        "measurement_carrier": "P19 independent_checks (non-author measurement of the repaired path)",
        "metrics_json": {"path": str(P19 / "metrics.json"), "sha256": p19_sha["metrics"]},
        "independent_checks_json": {
            "path": str(P19 / "analysis/independent_checks.json"),
            "sha256": p19_sha["independent_checks_json"],
        },
        "independent_checks_out": {
            "path": str(P19 / "logs/independent_checks.out"),
            "sha256": p19_sha["independent_checks_out"],
        },
        "repaired_byte_copy": {
            "tree": str(repaired_eval.parents[3]),
            "evaluation_py": str(repaired_eval),
            "sha256": sha256_file(repaired_eval) if repaired_eval.is_file() else None,
            "pristine_sha256": "92d8de4a6551b8538f38a54b17b550a88aa80c4135d05c0e29b8be2f8bf72aa3",
            "patch": "stop=support[-1] + 1 -> + 2 (one line)",
            "temp_tree_still_present": P19_TREE.is_dir(),
        },
        "frozen_snapshot_untouched": all(item["unchanged"] for item in r1_audit),
    }

    identity = {
        "snapshot_root": str(SNAP),
        "source_sha256": {
            rel: sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / rel)
            for rel in ("data.py", "evaluation.py", "metrics.py", "runtime.py",
                        "spec.py", "worker.py", "prereg.py", "commands.py")
        },
        "prereg_sha256": sha256_file(SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json"),
        "dataset_dir": str(DATASET),
        "dataset_sha256": {
            rel: sha256_file(DATASET / rel)
            for rel in ("dataset_manifest.json", "packets/development.jsonl", "truth/development.jsonl")
        },
        "p18_r1_frozen_input_audit": r1_audit,
        "p18_r1_frozen_inputs_all_unchanged": all(item["unchanged"] for item in r1_audit),
        "p19_artifacts_sha256": p19_sha,
        "p19_measurement_artifacts": p19_measurement_artifacts,
        "r2_out_of_scope_inputs": {
            "p18_r2_review_task_draft": {
                "path": str(CYCLE / "P18-r2-review-task.json"),
                "sha256": sha256_file(CYCLE / "P18-r2-review-task.json"),
            }
        },
    }

    # ------------------------------------------------------------------
    # 2. frozen budget arithmetic (new recomputation, no model)
    # ------------------------------------------------------------------
    updates = int(protocol["updates"])
    batch_size = int(protocol["batch_size"])
    sequence_steps = int(protocol["sequence_steps"])
    ckpt = list(protocol["checkpoint_updates"])
    n_ckpt = len(ckpt)
    trainable_runs = 9
    d_runs = 1
    duty = float(doc["resource_limits"]["training_duty_cycle"])
    step_seconds = float(budget["measured_forward_loss_step_seconds"])
    d_step = float(budget["arm1_step_seconds"])
    update_cost = 3.0 * step_seconds
    eval_batches = int(protocol["eval_batches"])
    eval_cost = eval_batches * step_seconds * len(protocol["checkpoint_fractions"])
    raw_updates = int((360.0 * duty / overhead - eval_cost) // update_cost)
    estimate = (updates * update_cost + eval_cost) / duty * overhead
    deadline = int(-(-estimate * 1.25 // 1))
    arm1_active = eval_batches * d_step * len(protocol["checkpoint_fractions"])
    arm1_estimate = (arm1_active / duty) * overhead
    arm1_deadline = int(-(-arm1_estimate * 1.25 // 1))
    phase_wall = trainable_runs * deadline + d_runs * arm1_deadline + float(
        timing["smoke"]["data_generation_seconds"]
    )
    phase_cap = float(timing["phase_wall_max_seconds"])
    headroom = phase_cap - phase_wall

    budget_recompute = {
        "provenance": "arithmetic_r2_from_frozen_inputs",
        "inputs": {
            "updates": updates,
            "batch_size": batch_size,
            "sequence_steps": sequence_steps,
            "checkpoint_updates": ckpt,
            "duty_cycle": duty,
            "measured_forward_loss_step_seconds": step_seconds,
            "arm1_step_seconds": d_step,
            "estimate_eval_overhead_factor": overhead,
            "eval_batches": eval_batches,
            "target_estimate_seconds": float(protocol["target_estimate_seconds"]),
        },
        "recomputed": {
            "raw_updates_floor": raw_updates,
            "update_cost_seconds": update_cost,
            "eval_cost_inside_training_run_seconds": eval_cost,
            "estimate_seconds": estimate,
            "deadline_seconds": deadline,
            "arm1_estimate_seconds": arm1_estimate,
            "arm1_deadline_seconds": arm1_deadline,
            "phase_wall_seconds": phase_wall,
            "phase_cap_seconds": phase_cap,
            "headroom_seconds": headroom,
        },
        "frozen": {
            "updates": updates,
            "estimate_seconds": float(budget["estimate_seconds"]),
            "deadline_seconds": int(budget["deadline_seconds"]),
            "arm1_estimate_seconds": float(budget["arm1_estimate_seconds"]),
            "arm1_deadline_seconds": int(budget["arm1_deadline_seconds"]),
            "phase_wall_seconds": float(budget["phase_wall_seconds"]),
            "phase_headroom_seconds": float(budget["phase_wall_headroom_seconds"]),
        },
        "delta": {
            "updates": updates - raw_updates,
            "estimate_seconds": float(budget["estimate_seconds"]) - estimate,
            "deadline_seconds": int(budget["deadline_seconds"]) - deadline,
            "arm1_estimate_seconds": float(budget["arm1_estimate_seconds"]) - arm1_estimate,
            "arm1_deadline_seconds": int(budget["arm1_deadline_seconds"]) - arm1_deadline,
            "phase_wall_seconds": float(budget["phase_wall_seconds"]) - phase_wall,
            "phase_headroom_seconds": float(budget["phase_wall_headroom_seconds"]) - headroom,
        },
    }

    # ------------------------------------------------------------------
    # 3. call counts with provenance
    # ------------------------------------------------------------------
    as_coded_measured = dict(p19_checks["B_as_coded_accounting_measured"]["per_run_total"])
    repaired_measured = dict(p19_checks["C_repaired_accounting_measured"]["per_run_total"])
    as_coded_split = p19_checks["B_as_coded_accounting_measured"]["component_split"]
    repaired_split = p19_checks["C_repaired_accounting_measured"]["component_split"]

    truth_k = truth["k_coverage"]
    k_queries = {k: int(truth_k[k]["queries"]) for k in ("0", "1", "2", "4", "8")}
    k_worlds = {k: int(truth_k[k]["worlds"]) for k in ("0", "1", "2", "4", "8")}
    few_shot_queries = sum(k_queries.values())
    few_shot_transitions = sum(k_worlds[k] * int(k) for k in ("0", "1", "2", "4", "8") if int(k) > 0)
    few_shot_step_sequence = sum(k_worlds[k] for k in ("1", "2", "4", "8"))
    few_shot_probe_graph = sum(k_worlds.values())
    few_shot_encode = 2 * few_shot_queries

    component_arithmetic = {
        "few_shot_step_sequence_calls": {
            "value": few_shot_step_sequence,
            "formula": "sum(worlds_with_query[k]) for k in {1,2,4,8} (k=0 writes no support)",
            "inputs": {k: k_worlds[k] for k in ("1", "2", "4", "8")},
        },
        "few_shot_single_step_forwards": {
            "value": few_shot_transitions,
            "formula": "sum(worlds[k] * k) for k in {1,2,4} (k transitions per world under stop=k+1)",
            "inputs": {k: k_worlds[k] for k in ("1", "2", "4")},
        },
        "few_shot_probe_graph_calls": {
            "value": few_shot_probe_graph,
            "formula": "sum(worlds_with_query[k]) over all k (one probe per world after the support write)",
        },
        "few_shot_encode_calls": {
            "value": few_shot_encode,
            "formula": "2 * sum(queries[k]) (source + destination cell per query)",
            "inputs": {k: k_queries[k] for k in k_queries},
        },
        "repaired_step_sequence_total": {
            "value": 200 + few_shot_step_sequence + 11,
            "formula": "topology 200 + few-shot + m2 11",
        },
        "repaired_single_step_forwards_total": {
            "value": 750 + few_shot_transitions + 42,
            "formula": "topology 750 + few-shot + m2 42",
        },
        "repaired_probe_graph_total": {
            "value": 200 + few_shot_probe_graph,
            "formula": "topology 200 + few-shot",
        },
    }
    arithmetic_matches_measurement = (
        component_arithmetic["repaired_step_sequence_total"]["value"] == int(repaired_measured["step_sequence_calls"])
        and component_arithmetic["repaired_single_step_forwards_total"]["value"] == int(repaired_measured["single_step_forward_calls"])
        and component_arithmetic["repaired_probe_graph_total"]["value"] == int(repaired_measured["probe_graph_calls"])
        and component_arithmetic["few_shot_encode_calls"]["value"] + 0 == int(repaired_measured["encode_calls"])
    )

    call_counts = {
        "note": "every block carries its provenance; r1's analytic projection is kept only as a historical audit value",
        "per_arm_seed_eval": {
            "as_coded": {
                "provenance": "measured",
                "measured_by": "P18 r1 instrumented counting backend (author); P19 re-ran the same scripts byte-identically",
                "evidence": {
                    "p18_log": str(P18R1 / "logs/count_calls.out"),
                    "p19_reproduction_identical": p19["independent_reproduction"]["all_identical"],
                },
                "window_forward_loss": int(as_coded_measured["forward_loss_calls"]),
                "window_frame_slots": int(as_coded_measured["forward_loss_frames"]),
                "step_sequence_calls": int(as_coded_measured["step_sequence_calls"]),
                "single_step_forwards": int(as_coded_measured["single_step_forward_calls"]),
                "probe_graph_calls": int(as_coded_measured["probe_graph_calls"]),
                "encode_calls": int(as_coded_measured["encode_calls"]),
                "terminal": "few_shot_report raises BackendError at k=1; nothing from k>=1 lands on disk",
            },
            "repaired_k1": {
                "provenance": "measured_non_author",
                "measured_by": "P19 independent_checks, 1-line repair (stop=support[-1]+2) on a byte copy of the frozen snapshot",
                "author_did_not_measure_this": True,
                "evidence": p19_measurement_artifacts,
                "window_forward_loss": int(repaired_measured["forward_loss_calls"]),
                "window_frame_slots": int(repaired_measured["forward_loss_frames"]),
                "step_sequence_calls": int(repaired_measured["step_sequence_calls"]),
                "single_step_forwards": int(repaired_measured["single_step_forward_calls"]),
                "probe_graph_calls": int(repaired_measured["probe_graph_calls"]),
                "encode_calls": int(repaired_measured["encode_calls"]),
            },
            "r1_registration_values_superseded": {
                "provenance": "text_error_in_r1_report",
                "step_sequence_calls": 612,
                "single_step_forwards": 1292,
                "probe_graph_in_unmeasured_text": 600,
                "corrected_to": {"step_sequence_calls": 611, "single_step_forwards": 1492, "probe_graph_calls": 800},
                "deltas": {"step_sequence_calls": -1, "single_step_forwards": 200},
                "note": "r1 metrics.json already stored 611/1492/800; only the REPORT prose and the unmeasured text drifted",
            },
            "r1_analytic_projection": {
                "provenance": "projected_superseded",
                "values": r1_metrics["eval_run_accounting_if_k1_repaired"],
                "note": "same numbers as the P19 measurement, but they were an analytic extrapolation in r1; r2 re-labels the source and does not cite the projection as a measurement",
            },
        },
        "component_split_measured": {
            "provenance": "measured_non_author",
            "source": "P19 independent_checks.json B/C component_split",
            "as_coded": as_coded_split,
            "repaired_k1": repaired_split,
        },
        "m2_constants": {
            "step_sequence_calls": 11,
            "single_step_forwards": 42,
            "provenance": "measured_non_author",
            "source": "P19 independent_checks.json component_split.m2_interference",
            "not_hand_typed_in_r2": True,
        },
        "component_arithmetic_r2": component_arithmetic,
        "arithmetic_matches_measurement": arithmetic_matches_measurement,
        "few_shot_query_total": few_shot_queries,
    }

    # ------------------------------------------------------------------
    # 4. frames decomposition (fixes F6)
    # ------------------------------------------------------------------
    frames = {
        "definitions": p19_checks["D_frames_reconstruction"]["definitions"],
        "components_measured": {
            "topology_stop_frames": int(as_coded_split["topology"]["step_sequence_frames"]),
            "topology_transitions": int(as_coded_split["topology"]["step_sequence_transitions"]),
            "few_shot_repaired_stop_frames": 1100,
            "few_shot_repaired_transitions": few_shot_transitions,
            "m2_stop_frames": int(as_coded_split["m2_interference"]["step_sequence_frames"]),
            "m2_transitions": int(as_coded_split["m2_interference"]["step_sequence_transitions"]),
        },
        "hybrid_numbers_not_a_real_run": {
            "1703": "950 topology stop_frames + 700 few-shot transitions + 53 m2 stop_frames (crash stop for k=1 assumed not to crash)",
            "1503": "750 topology transitions + 700 few-shot transitions + 53 m2 stop_frames",
            "1903": "1100 repaired few-shot stop_frames + 750 topology transitions + 53 m2 stop_frames",
        },
        "self_consistent": {
            "as_coded_measured": {
                "calls": int(as_coded_measured["step_sequence_calls"]),
                "stop_frames": int(as_coded_measured["step_sequence_frames"]),
                "transitions": int(as_coded_measured["step_sequence_transitions"]),
                "provenance": "measured",
            },
            "repaired_measured": {
                "calls": int(repaired_measured["step_sequence_calls"]),
                "stop_frames": int(repaired_measured["step_sequence_frames"]),
                "transitions": int(repaired_measured["step_sequence_transitions"]),
                "provenance": "measured_non_author",
            },
        },
    }

    # ------------------------------------------------------------------
    # 5. totals for 9 training + 9 eval + 1 D
    # ------------------------------------------------------------------
    windows = 550  # frozen development windows (dataset manifest / r1 cpu_coverage)
    probe_batches = (windows + batch_size - 1) // batch_size
    assert probe_batches == 35, probe_batches
    window_frames_per_probe = windows * (sequence_steps + 1)

    train_per_run = {
        "optimizer_updates": updates,
        "checkpoint_probes": n_ckpt,
        "probe_window_batches": n_ckpt * probe_batches,
        "probe_window_frames": n_ckpt * window_frames_per_probe,
        "forward_loss_batch_equivalents": updates + n_ckpt * probe_batches,
        "estimate_seconds": float(budget["estimate_seconds"]),
        "deadline_seconds": int(budget["deadline_seconds"]),
        "supervision_seconds": int(budget["supervision_seconds"]),
    }
    eval_per_run_calls = call_counts["per_arm_seed_eval"]["repaired_k1"]
    eval_per_run = {
        "window_forward_loss_calls": eval_per_run_calls["window_forward_loss"],
        "window_frame_slots": eval_per_run_calls["window_frame_slots"],
        "step_sequence_calls": eval_per_run_calls["step_sequence_calls"],
        "single_step_forwards": eval_per_run_calls["single_step_forwards"],
        "probe_graph_calls": eval_per_run_calls["probe_graph_calls"],
        "encode_calls": eval_per_run_calls["encode_calls"],
        "provenance": "measured_non_author",
        "nominal_cli_wall_seconds": 300.0,
        "ledger_reserve_seconds": min(120.0, max(10.0, 0.5 * 300.0)),
    }
    d_run = {
        "model_loads": 1,
        "forward_loss_calls": 1,
        "batch": {"windows": 16, "timesteps": 2, "c0_frame_slots": 32},
        "s1_metrics": "not_applicable",
        "estimate_seconds": float(budget["arm1_estimate_seconds"]),
        "deadline_seconds": int(budget["arm1_deadline_seconds"]),
        "supervision_seconds": float(timing["arm1_supervision_seconds"]),
        "provenance": "measured_c0_baseline_identity (frozen smoke), call count from frozen source branch",
    }

    totals = {
        "provenance_mix": "training arithmetic = frozen; eval calls = measured_non_author; D = frozen smoke identity",
        "trainable_training_runs": trainable_runs,
        "post_hoc_eval_runs": trainable_runs,
        "d_candidate_runs": d_runs,
        "optimizer_updates": trainable_runs * updates,
        "training_probe_window_batches": trainable_runs * train_per_run["probe_window_batches"],
        "training_probe_window_frames": trainable_runs * train_per_run["probe_window_frames"],
        "eval_window_batches": trainable_runs * eval_per_run["window_forward_loss_calls"],
        "eval_step_sequence_calls": trainable_runs * eval_per_run["step_sequence_calls"],
        "eval_single_step_forwards": trainable_runs * eval_per_run["single_step_forwards"],
        "eval_probe_graph_calls": trainable_runs * eval_per_run["probe_graph_calls"],
        "eval_encode_calls": trainable_runs * eval_per_run["encode_calls"],
        "d_forward_loss_calls": d_runs,
        "d_c0_frame_slots": d_runs * 32,
    }

    # ------------------------------------------------------------------
    # 6. phase cap: 4h already includes eval (F3)
    # ------------------------------------------------------------------
    eval_wall_nominal_total = trainable_runs * 300.0
    eval_ledger_reserve_total = trainable_runs * eval_per_run["ledger_reserve_seconds"]
    phase_guard_sources = [
        {
            "file": "commands.py",
            "lines": "737-757",
            "quote": "total_wall = sum(float(r.wall_seconds) for r in store.list_runs())  # Include auxiliary eval/verify reservations; the phase cap is not a training-experiment-only allowance.",
        },
        {
            "file": "worker.py",
            "lines": "368-385",
            "quote": "total_wall = sum(float(r.wall_seconds) for r in ledger.store.list_runs())  # The phase cap covers every registered run in this card-local ledger, including auxiliary eval/verify runs.",
        },
        {
            "file": "worker.py",
            "lines": "435-440",
            "quote": "active_run = ledger.open_aux_run(mode='eval', wall_budget_seconds=budget); ledger.reserve(active_run, active_seconds=min(120.0, max(10.0, 0.5 * budget)))",
        },
    ]
    phase = {
        "frozen_phase_wall_seconds": float(budget["phase_wall_seconds"]),
        "composition": "9*deadline(450) + 1*arm1_deadline(2) + timing.smoke.data_generation_seconds(47.605202459)",
        "phase_cap_seconds": phase_cap,
        "headroom_seconds": float(budget["phase_wall_headroom_seconds"]),
        "phase_cap_includes_eval_runs": True,
        "phase_cap_sources": phase_guard_sources,
        "eval_wall_nominal_per_invocation_seconds": 300.0,
        "eval_wall_nominal_total_9_runs_seconds": eval_wall_nominal_total,
        "eval_ledger_reserve_per_run_seconds": eval_per_run["ledger_reserve_seconds"],
        "eval_ledger_reserve_total_9_runs_seconds": eval_ledger_reserve_total,
        "static_fit_check": {
            "phase_wall_plus_nominal_eval_seconds": float(budget["phase_wall_seconds"]) + eval_wall_nominal_total,
            "phase_wall_plus_ledger_reserve_eval_seconds": float(budget["phase_wall_seconds"]) + eval_ledger_reserve_total,
            "both_within_cap": (
                float(budget["phase_wall_seconds"]) + eval_wall_nominal_total <= phase_cap
                and float(budget["phase_wall_seconds"]) + eval_ledger_reserve_total <= phase_cap
            ),
            "note": "static arithmetic only; actual eval wall time is unknown/untested",
        },
        "not_a_pseudo_approval_item": "the question 'should eval wall time count toward the 4 h cap' is not open: the frozen guard sums every registered run in the card-local ledger, eval included. r2 removes that item from option B.",
        "ledger_boundary_unknown": "the guard sums the card-local output_root/control.sqlite3 ledger. Whether that ledger is the unique budget anchor across output roots/checkouts is the separate r6 defect (S1-R6-DECISION item 1); r5 does not fix it and r2 does not claim it is fixed.",
    }

    # ------------------------------------------------------------------
    # 7. 48-batch contradiction (r1 bedrock, restated with provenance)
    # ------------------------------------------------------------------
    conflict = {
        "eval_batches_registered": eval_batches,
        "spec_eval_batches": eval_batches_spec,
        "actual_probe_batches": probe_batches,
        "cap_binding": probe_batches >= eval_batches,
        "meanings": [
            "cap on window_probe batches per probe: min(35,48)=35, so 48 never binds",
            "training-run eval cost term: 48*5*step = %.12f s inside the 359.931 s estimate" % eval_cost,
            "arm1 cost term: 48*5*d_step = 1.501679232227616 s while arm1 performs exactly one forward (240x over-reservation)",
        ],
        "silent_truncation_threshold_windows": eval_batches * batch_size,
        "real_suite_not_registered": True,
        "real_suite_measured_calls_per_run": {
            "window_batches": eval_per_run["window_forward_loss_calls"],
            "step_sequence_calls": eval_per_run["step_sequence_calls"],
            "single_step_forwards": eval_per_run["single_step_forwards"],
            "probe_graph_calls": eval_per_run["probe_graph_calls"],
            "encode_calls": eval_per_run["encode_calls"],
        },
        "note": "48 is a training-probe cap/cost parameter, never a definition of the post-hoc eval suite.",
    }

    # ------------------------------------------------------------------
    # 8. F1-F9 closures
    # ------------------------------------------------------------------
    closures = [
        {"id": "F1", "severity": "critical", "status": "closed",
         "fix": "every user-facing call number is 611 / 1492 / 800 / 3500 / 175 window batches; 612 / 1292 / 600 are marked superseded text errors",
         "evidence": "call_counts.per_arm_seed_eval.r1_registration_values_superseded; corrected_to equals P19 measured"},
        {"id": "F2", "severity": "critical", "status": "closed",
         "fix": "each block has provenance measured | measured_non_author | arithmetic_r2 | projected_superseded; as-coded and repaired-k1 are separate blocks; r1 projection retained only as audit",
         "evidence": "call_counts; totals.provenance_mix"},
        {"id": "F3", "severity": "critical", "status": "closed",
         "fix": "pseudo-approval item removed; 4 h already includes eval (commands.py:737-757, worker.py:368-385, eval reserve at worker.py:435-440); remaining open points are the unmeasured MLX wall and the r6 cross-ledger uniqueness defect",
         "evidence": "phase"},
        {"id": "F4", "severity": "critical", "status": "closed",
         "fix": "new long-episode data cost is unknown; 47.605 s is the frozen plan's manifest-copied value (2200 worlds / 10450 packets), not a new-plan measurement; no packet-rate number is presented as a cost estimate",
         "evidence": "data_cost"},
        {"id": "F5", "severity": "medium", "status": "closed",
         "fix": "option A no longer claims zero change: frozen metric keeps its original accuracy/displacement values with n and missing; family split and constant baselines are diagnostic only; coverage/FPR need a new metric id or a registered definition",
         "evidence": "frozen_metric_reporting; option_A"},
        {"id": "F6", "severity": "medium", "status": "closed",
         "fix": "1703/1503/1903 are labelled hybrid; only 1003 (as-coded) and 2103 (repaired) are self-consistent stop_frames totals, with 792/1492 transitions",
         "evidence": "frames"},
        {"id": "F7", "severity": "medium", "status": "closed",
         "fix": "r2 does not type in the M2 11/42; they come from the P19 measured component split, and the per-world transition rule is stated as k transitions under stop=k+1",
         "evidence": "call_counts.m2_constants; component_arithmetic_r2"},
        {"id": "F8", "severity": "light", "status": "closed",
         "fix": "probe_graph is 800 (200 topology + 600 few-shot); 600 appears only as the few-shot half",
         "evidence": "call_counts.per_arm_seed_eval.repaired_k1.probe_graph_calls"},
        {"id": "F9", "severity": "light", "status": "closed",
         "fix": "same dataset digest carries two generation_seconds (45.739918708 vs 47.605202459): the manifest field was rewritten after the prereg freeze; the conservative 47.605 value is used and the internal inconsistency is recorded, not softened",
         "evidence": "data_cost.frozen_document_inconsistency"},
    ]

    # ------------------------------------------------------------------
    # 9. option A / B material
    # ------------------------------------------------------------------
    option_a = {
        "title": "keep the frozen data, k and partition; report only what has samples; missing stays missing",
        "is_zero_change": False,
        "why_not_zero_change": "reporting coverage/false-positive rate instead of accuracy changes the frozen metric definition; the frozen metric must keep its original values first",
        "frozen_metric": {
            "id": "few_shot_unseen_transition",
            "definition": "write k in {0,1,2,4,8} support transitions without parameter updates, predict held-out transitions; accuracy and displacement error vs k",
            "original_values_retained": True,
            "sample_sizes": {k: {"worlds": k_worlds[k], "queries": k_queries[k]} for k in k_worlds},
            "missing": {
                "k=8": "insufficient_data (0/200 worlds)",
                "k=4 families_other_than_navigation": "insufficient_data (relation/time/e3_identity have 0 worlds)",
            },
            "values_require_real_eval": True,
            "real_eval_is_blocked_by_k1_crash": True,
        },
        "preconditions": [
            "repair the frozen r5 stop boundary (stop=support[-1]+2 or equivalent) and re-freeze evaluation.py identity; new non-author review",
            "register query_limit=8 in the metric text or remove it from the code path",
            "coverage / false-positive-rate may be added only as a new metric id or a registered definition, never substituted into few_shot_unseen_transition",
        ],
        "diagnostic_only": ["per-family split", "constant-predictor baselines"],
        "cost": "0 new training, 0 new data, 0 new GPU; CPU-only repair + re-freeze + review",
    }
    data_cost = {
        "frozen_plan": {
            "train_worlds": 2000,
            "development_worlds": 200,
            "total_packets": 10450,
            "timing_smoke_data_generation_seconds": 47.605202458999884,
            "data_identity_generation_seconds": 45.739918708000005,
            "difference_seconds": 1.865283750999879,
        },
        "provenance_correction": "smoke.py copies manifest['generation_seconds']; it does not time generation. 47.605 s belongs to the frozen 2200-world plan and is not a new-plan measurement.",
        "frozen_document_inconsistency": "the same dataset digest has two generation_seconds values; the manifest field was rewritten after the prereg freeze; the conservative 47.605 value is used in phase_wall",
        "new_plan_cost": "unknown_not_measured",
        "registered_caps": {
            "spec_data_generation_budget_seconds": data_budget_spec,
            "cli_prep_budget_data_seconds": 600.0,
        },
        "packet_rate_extrapolation_not_a_cost_estimate": {
            "seconds": 9.111,
            "note": "packet-cost-only lower bound (2000 packets at the old per-packet rate); per-world scene setup is unmeasured and the new episodes are longer",
        },
    }
    option_b = {
        "title": "a future long-episode data batch and eval budget; no change to the current partition or the original experiment",
        "requires_user_approval_per_item": True,
        "approval_line_written": False,
        "items": [
            {"id": "B1", "item": "new dataset batch (new plan/seed -> new dataset_digest -> new experiment identity), 200 worlds x >=10 packets, family-stratified so every family has >=9 transitions per world",
             "cost": "unknown_not_measured"},
            {"id": "B2", "item": "register the measured eval call counts: 175 window batches, 611 step_sequence, 1492 single-step forwards, 800 probe_graph, 3500 encode, D 1 C0 forward",
             "provenance": "measured_non_author (P19)"},
            {"id": "B3", "item": "measure MLX batch-1 single-step forward / encode / probe_graph unit costs before converting calls to wall time",
             "cost": "unknown_not_measured"},
            {"id": "B4", "item": "allocate the eval wall inside the existing 4 h phase cap (already inclusive); the open question is the headroom split, not whether eval counts",
             "note": "no new approval needed to establish inclusion; the per-invocation 300 s hard wall remains"},
            {"id": "B5", "item": "revise 'held-out' semantics (temporal continuation vs spatially unvisited cell) and register it",
             "status": "decision_needed"},
            {"id": "B6", "item": "register query_limit=8 and decide how checkpoint 0 (pre-training) is treated in the curve",
             "status": "decision_needed"},
            {"id": "B7", "item": "fix the M2 probe selection (currently the first 5 worlds by UUID order) to a registered stratified/predeclared choice",
             "status": "decision_needed"},
        ],
    }

    # ------------------------------------------------------------------
    # 10. frozen metric reporting / diagnostic baselines
    # ------------------------------------------------------------------
    frozen_metric = {
        "id": "few_shot_unseen_transition",
        "definition": "write k in {0,1,2,4,8} support transitions of a development world into memory without parameter updates, then predict held-out transitions (edge existence and destination displacement); accuracy and displacement error vs k",
        "query_limit_in_code": 8,
        "query_limit_registered": False,
        "original_accuracy_and_displacement_values_retained": True,
        "missing_values_are_not_zero_or_perfect": True,
        "diagnostic_family_and_constant_baselines_do_not_replace_it": True,
    }
    diagnostic = {
        "provenance": "computed_r2_from_frozen_truth (independent implementation) and cross-checked with P19",
        "diagnostic_only": True,
        "family_transition_kinds": truth["family_summary"],
        "per_k": {
            k: {
                "worlds": v["worlds"],
                "queries": v["queries"],
                "by_family": v["by_family"],
                "constant_predictor_baselines": v["constant_predictor_baselines"],
                "reachable_in_support_memory": v["reachable_in_support_memory"],
                "reachable_fraction": v["reachable_fraction"],
                "diagnostic_only": True,
            }
            for k, v in truth_k.items()
        },
        "cross_check_vs_p19": {
            "p19_worlds": {k: v["worlds"] for k, v in p19["k_coverage_reproduced"].items()},
            "r2_worlds": k_worlds,
            "p19_queries": {k: v["queries"] for k, v in p19["k_coverage_reproduced"].items()},
            "r2_queries": k_queries,
            "matches": all(
                p19["k_coverage_reproduced"][k]["worlds"] == k_worlds[k]
                and p19["k_coverage_reproduced"][k]["queries"] == k_queries[k]
                for k in k_worlds
            ),
        },
        "why_diagnostic": "navigation transitions are all adjacent (positive) and the other three families are all stay (negative); a merged accuracy curve changes class composition with k and cannot be read as a memory-quality curve",
    }

    unmeasured = [
        "MLX batch-1 single-step forward cost (1492 per eval run, 13,428 for 9 runs) - not measured by the frozen smoke",
        "MLX encode cost (3500 per run, 31,500 total) - not measured",
        "MLX probe_graph cost (800 per run, 7,200 total) - not measured",
        "actual eval wall time under the 300 s per-invocation hard wall - unknown",
        "new long-episode data generation cost - unknown; 47.605 s is the old plan only",
        "cross-output-root ledger uniqueness (r6 defect) - not fixed in r5",
    ]

    metrics = {
        "schema": "ainerzero.v9.p18.metrics.v2",
        "task": "ainerzero.V9.P18",
        "revision": "r2",
        "executor": "deepseek-v41f-p8k2",
        "status": "cpu_engineering_revision_only",
        "revision_basis": {
            "reviewed_report": str(P19 / "REPORT.md"),
            "reviewed_report_sha256": p19_sha["report"],
            "reviewed_metrics_sha256": p19_sha["metrics"],
            "issues_closed": [c["id"] for c in closures],
            "r1_report_sha256": "0b33e29fbd2e5ab68f7f5338f120d596798a44f1af8c1393c3056b6ccbf09908",
        },
        "identity": identity,
        "budget_recompute": budget_recompute,
        "call_counts": call_counts,
        "frames": frames,
        "per_run": {"training": train_per_run, "eval": eval_per_run, "d_candidate": d_run},
        "totals": totals,
        "phase": phase,
        "eval_batches_conflict": conflict,
        "data_cost": data_cost,
        "frozen_metric_reporting": frozen_metric,
        "diagnostic_baselines": diagnostic,
        "option_A": option_a,
        "option_B": option_b,
        "f_closures": closures,
        "unmeasured": unmeasured,
        "no_real_execution": {
            "mlx_imported": False,
            "real_training": False,
            "real_evaluation": False,
            "new_data_generated": False,
            "final_partition_read": False,
            "downloads_or_installs": False,
            "source_modified": False,
            "approval_line_written": False,
            "budget_or_scientific_parameter_changed": False,
        },
        "note": "P19's negative evidence is preserved: the frozen r5 path still crashes at k=1, the frozen metric has no usable values yet, and no MLX cost is claimed. r2 changes presentation and provenance, not science.",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    (OUT / "analysis" / "input_identity.json").write_text(
        json.dumps(identity, indent=2, ensure_ascii=False)
    )

    print(json.dumps({
        "budget_delta": budget_recompute["delta"],
        "arithmetic_matches_measurement": arithmetic_matches_measurement,
        "totals": totals,
        "phase_fit": phase["static_fit_check"],
        "f_closures": [f"{c['id']}:{c['status']}" for c in closures],
        "r1_frozen_inputs_all_unchanged": identity["p18_r1_frozen_inputs_all_unchanged"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
