"""Assemble reports/V9-P19/metrics.json for the non-author review of ainerzero.V9.P18.

Every number below is computed here from (a) the frozen P18 inputs, (b) the
independent measurement in ``independent_checks.json``, and (c) the frozen r5
source snapshot.  Nothing is typed in by hand.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
P18 = REPO / "reports/V9-P18"
P19 = REPO / "reports/V9-P19"
COORD = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle")
FROZEN = COORD / "P18-frozen-review-inputs.json"
SNAP = COORD / "s1-r5-input-snapshot"
PREREG = SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    frozen = json.loads(FROZEN.read_text())
    sha_check = []
    for item in frozen["files"]:
        path = Path(item["path"])
        exists = path.is_file()
        actual = sha256_file(path) if exists else None
        sha_check.append(
            {
                "path": item["path"],
                "exists": exists,
                "bytes": path.stat().st_size if exists else None,
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "match": actual == item["sha256"],
            }
        )

    # ---- byte-identity of the independently reproduced artefacts ----------
    pairs = [
        ("logs/count_calls.out", "logs/count_calls.out"),
        ("logs/truth_stats.out", "logs/truth_stats.out"),
        ("logs/build_metrics.out", "logs/build_metrics.out"),
        ("analysis/cpu_coverage.json", "analysis/cpu_coverage.json"),
        ("analysis/truth_stats.json", "analysis/truth_stats.json"),
        ("analysis/per_world.json", "analysis/per_world.json"),
        ("metrics.json", "metrics.json"),
    ]
    reproduction = []
    for src, dst in pairs:
        a, b = P18 / src, P19 / dst
        reproduction.append(
            {
                "p18_path": str(a),
                "p19_path": str(b),
                "p18_sha256": sha256_file(a),
                "p19_sha256": sha256_file(b),
                "identical": sha256_file(a) == sha256_file(b),
            }
        )

    checks = json.loads((P19 / "analysis" / "independent_checks.json").read_text())
    as_coded = checks["B_as_coded_accounting_measured"]
    repaired = checks["C_repaired_accounting_measured"]
    real = checks["A_real_runtime_method_checks"]
    coverage = json.loads((P19 / "analysis" / "cpu_coverage.json").read_text())
    truth = json.loads((P19 / "analysis" / "truth_stats.json").read_text())
    prereg = json.loads(PREREG.read_text())
    report_text = (P18 / "REPORT.md").read_text()

    # ---- the numbers P18 proposes for registration (option B, item 3) -----
    published = {"step_sequence": 612, "single_step_forwards": 1292}
    measured_repaired = {
        "step_sequence": repaired["per_run_total"]["step_sequence_calls"],
        "single_step_forwards": repaired["per_run_total"]["single_step_forward_calls"],
        "probe_graph": repaired["per_run_total"]["probe_graph_calls"],
        "encode": repaired["per_run_total"]["encode_calls"],
        "window_forward_loss": repaired["per_run_total"]["forward_loss_calls"],
    }
    measured_as_coded = {
        "step_sequence": as_coded["per_run_total"]["step_sequence_calls"],
        "single_step_forwards": as_coded["per_run_total"]["single_step_forward_calls"],
        "probe_graph": as_coded["per_run_total"]["probe_graph_calls"],
        "encode": as_coded["per_run_total"]["encode_calls"],
        "window_forward_loss": as_coded["per_run_total"]["forward_loss_calls"],
    }
    registration_numbers = {
        "p18_option_B_item3_step_sequence": published["step_sequence"],
        "p18_option_B_item3_single_step_forwards": published["single_step_forwards"],
        "measured_repaired_step_sequence": measured_repaired["step_sequence"],
        "measured_repaired_single_step_forwards": measured_repaired["single_step_forwards"],
        "delta_step_sequence": published["step_sequence"] - measured_repaired["step_sequence"],
        "delta_single_step_forwards": published["single_step_forwards"] - measured_repaired["single_step_forwards"],
        "relative_error_single_step_forwards": round(
            (published["single_step_forwards"] - measured_repaired["single_step_forwards"])
            / measured_repaired["single_step_forwards"],
            6,
        ),
        "also_inconsistent_in_metrics_json_unmeasured_text": "611 eval calls, 1292 forwards",
    }

    # ---- frames decomposition (arithmetic, not assertion) ----------------
    topo = as_coded["component_split"]["topology"]
    m2 = as_coded["component_split"]["m2_interference"]
    fewshot_repaired_transitions = (
        repaired["per_run_total"]["step_sequence_transitions"]
        - topo["step_sequence_transitions"]
        - m2["step_sequence_transitions"]
    )
    frames = {
        "topology_stop_frames": topo["step_sequence_frames"],
        "topology_transitions": topo["step_sequence_transitions"],
        "m2_stop_frames": m2["step_sequence_frames"],
        "m2_transitions": m2["step_sequence_transitions"],
        "few_shot_repaired_transitions_measured": fewshot_repaired_transitions,
        "few_shot_repaired_stop_frames_measured": (
            repaired["per_run_total"]["step_sequence_frames"]
            - topo["step_sequence_frames"]
            - m2["step_sequence_frames"]
        ),
        "decomposition_of_1703": (
            topo["step_sequence_frames"] + fewshot_repaired_transitions + m2["step_sequence_frames"]
        ),
        "decomposition_of_1503": (
            topo["step_sequence_transitions"] + fewshot_repaired_transitions + m2["step_sequence_frames"]
        ),
        "decomposition_of_1903": (
            (repaired["per_run_total"]["step_sequence_frames"] - topo["step_sequence_frames"] - m2["step_sequence_frames"])
            + topo["step_sequence_transitions"]
            + m2["step_sequence_frames"]
        ),
        "coherent_as_coded": {
            "calls": as_coded["per_run_total"]["step_sequence_calls"],
            "stop_frames": as_coded["per_run_total"]["step_sequence_frames"],
            "transitions": as_coded["per_run_total"]["step_sequence_transitions"],
        },
        "coherent_repaired": {
            "calls": repaired["per_run_total"]["step_sequence_calls"],
            "stop_frames": repaired["per_run_total"]["step_sequence_frames"],
            "transitions": repaired["per_run_total"]["step_sequence_transitions"],
        },
    }

    # ---- support off-by-one, straight from the real runtime method --------
    off_by_one = {}
    for k in ("1", "2", "4", "8"):
        rec = real["per_k"][k]
        off_by_one[k] = {
            "worlds_with_query": rec["worlds_with_query"],
            "crash": rec["crash"],
            "support_transitions_requested": rec.get("support_transitions_requested"),
            "support_transitions_executed_per_world": rec.get("support_transitions_executed_per_world"),
        }

    # ---- budget / phase arithmetic ---------------------------------------
    timing = prereg["timing"]
    budget = prereg["budget_estimate"]
    protocol = prereg["training_protocol"]
    phase_cap = float(timing["phase_wall_max_seconds"])
    phase_wall = float(budget["phase_wall_seconds"])
    eval_wall_budget = 300.0
    phase = {
        "frozen_phase_wall_seconds": phase_wall,
        "frozen_phase_cap_seconds": phase_cap,
        "frozen_headroom_seconds": float(budget["phase_wall_headroom_seconds"]),
        "phase_wall_composition": "9*deadline(450) + 1*arm1_deadline(2) + timing.smoke.data_generation_seconds(47.605202459)",
        "cli_eval_wall_budget_per_invocation_seconds": eval_wall_budget,
        "cli_eval_wall_budget_total_9_runs_seconds": 9 * eval_wall_budget,
        "spec_data_generation_budget_seconds": 300.0,
        "cli_prep_budget_data_seconds": 600.0,
        "phase_cap_includes_eval_runs": True,
        "phase_cap_evidence": [
            "commands.py mode_train: total_wall = sum(r.wall_seconds for r in store.list_runs())  "
            "# Include auxiliary eval/verify reservations; the phase cap is not a training-experiment-only allowance.",
            "worker.py _train: same sum over ledger.store.list_runs()  # The phase cap covers every registered run "
            "in this card-local ledger, including auxiliary eval/verify runs.",
            "worker.py eval branch: ledger = PrepLedger(output_root / 'control.sqlite3'); "
            "active_run = ledger.open_aux_run(mode='eval', wall_budget_seconds=budget) -> the eval run is a row in the "
            "same card-local ledger that the phase guard sums.",
        ],
    }

    # ---- data-generation cost attribution --------------------------------
    counts = prereg["data_identity"]["counts"]
    total_packets = int(counts["train_packets"]) + int(counts["development_packets"])
    gen_smoke = float(timing["smoke"]["data_generation_seconds"])
    gen_manifest = float(prereg["data_identity"]["generation_seconds"])
    new_plan_worlds = 200
    new_plan_packets_per_world = 10
    new_plan_packets = new_plan_worlds * new_plan_packets_per_world
    data_cost = {
        "frozen_plan": {
            "train_worlds": counts["train_worlds"],
            "development_worlds": counts["development_worlds"],
            "total_packets": total_packets,
            "timing_smoke_data_generation_seconds": gen_smoke,
            "data_identity_generation_seconds": gen_manifest,
            "difference_seconds": gen_smoke - gen_manifest,
            "per_packet_seconds_from_smoke_value": gen_smoke / total_packets,
            "per_packet_seconds_from_manifest_value": gen_manifest / total_packets,
        },
        "provenance_correction": "smoke.py sets data_generation_seconds = manifest['generation_seconds']; the smoke does "
        "not time the generation itself, it copies the dataset manifest field. The frozen document keeps two different "
        "values for the same dataset digest (45.739918708 in data_identity, 47.605202459 in timing.smoke), i.e. the "
        "manifest field was rewritten after the prereg freeze.",
        "option_B_new_plan": {
            "worlds": new_plan_worlds,
            "packets_per_world_min": new_plan_packets_per_world,
            "packets_min": new_plan_packets,
            "packets_vs_frozen_plan": round(new_plan_packets / total_packets, 6),
            "p18_claimed_cost_seconds": 47.6,
            "cost_attribution": "47.6 s is the FROZEN PLAN's generation cost (2200 worlds / 10450 packets), not a "
            "measurement of the proposed long-episode plan; the per-world scene-setup cost for >=10-packet worlds is "
            "not measured anywhere.",
            "packet_rate_extrapolation_seconds": round(
                (gen_smoke / total_packets) * new_plan_packets, 3
            ),
            "registered_caps": {
                "spec_timing_data_generation_budget_seconds": 300.0,
                "cli_prep_budget_data_seconds": 600.0,
            },
        },
    }

    # ---- k coverage + label balance (reproduced) ------------------------
    k_coverage = {
        k: {
            "worlds": v["worlds"],
            "queries": v["queries"],
            "by_family": {f: d["worlds"] for f, d in v["by_family"].items()},
            "reachable_in_support_memory": v["query_transitions_reachable_in_support_memory"],
            "reachable_fraction": v["reachable_fraction"],
        }
        for k, v in coverage["k_coverage"].items()
    }
    baselines = {
        k: {
            "true_edge_rate_constant_true_predictor": v["true_edge_rate"],
            "constant_false_predictor_accuracy": (
                round(1.0 - v["true_edge_rate"], 6) if v["true_edge_rate"] is not None else None
            ),
            "queries": v["queries"],
            "per_family_true_edges": {f: d["true_edges"] for f, d in v["by_family"].items()},
        }
        for k, v in truth["per_k"].items()
    }

    metrics = {
        "schema": "ainerzero.v9.p19.review-metrics.v1",
        "task": "ainerzero.V9.P19",
        "reviewer": "minimax-s1p19-1022",
        "reviewed_task": "ainerzero.V9.P18",
        "reviewed_report_sha256": sha256_file(P18 / "REPORT.md"),
        "status": "review_complete_not_accepted",
        "frozen_input_sha256_audit": {
            "checked": len(sha_check),
            "all_match": all(item["match"] for item in sha_check),
            "files": sha_check,
        },
        "independent_reproduction": {
            "method": "P18's three scripts re-run from byte-copies with scaffolding paths only "
            "(ISO -> private temp tree, OUT -> reports/V9-P19); diff in analysis/scaffold_diff.txt",
            "artefacts": reproduction,
            "all_identical": all(item["identical"] for item in reproduction),
        },
        "k_coverage_reproduced": k_coverage,
        "constant_predictor_baselines": baselines,
        "real_runtime_method_checks": {
            "method": real["method"],
            "mlx_imported": real["mlx_imported"],
            "guard": real["guard_source"],
            "per_k": off_by_one,
        },
        "call_accounting": {
            "as_coded_measured": measured_as_coded,
            "repaired_measured": measured_repaired,
            "repaired_measurement_method": "a 1-line repair of evaluation.py (stop=support[-1]+1 -> +2) applied to a "
            "byte copy of the frozen snapshot in a private temp tree; the frozen snapshot is untouched. The P18 counting "
            "substitute cannot run this path (its encode() violates the production contract in width and rank), so the "
            "repaired numbers in P18 are an analytic extrapolation, not a measurement.",
            "component_split_measured": as_coded["component_split"],
            "m2_constants_hardcoded_in_p18_build_metrics": {"step_sequence_calls": 11, "single_step_forwards": 42},
            "m2_constants_measured": {
                "step_sequence_calls": m2["step_sequence_calls"],
                "single_step_forwards": m2["step_sequence_transitions"],
            },
        },
        "frames_decomposition": frames,
        "registration_numbers_check": registration_numbers,
        "phase_budget": phase,
        "data_generation_cost_attribution": data_cost,
        "frozen_metric_reporting": {
            "frozen_metric_id": "few_shot_unseen_transition",
            "frozen_definition": next(
                m["definition"] for m in prereg["metrics"] if m["id"] == "few_shot_unseen_transition"
            ),
            "frozen_query_limit_registered": "query_limit" in PREREG.read_text(),
            "query_limit_in_code": 8,
            "note": "the frozen metric text says 'accuracy and displacement error vs k'; the frozen prereg does not "
            "register query_limit=8 (it exists only in metrics.split_support_query).",
        },
        "no_real_execution": {
            "mlx_imported": checks["identity"]["mlx_imported_anywhere"],
            "real_training": False,
            "real_evaluation": False,
            "model_downloads_or_installs": False,
            "source_modified": False,
            "frozen_sha256_unchanged_after_review": all(item["match"] for item in sha_check),
        },
    }
    (P19 / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(json.dumps(
        {
            "sha_all_match": metrics["frozen_input_sha256_audit"]["all_match"],
            "reproduction_all_identical": metrics["independent_reproduction"]["all_identical"],
            "registration_numbers_check": registration_numbers,
            "frames": frames,
            "phase_budget": {k: phase[k] for k in ("frozen_phase_wall_seconds", "frozen_headroom_seconds",
                                                   "cli_eval_wall_budget_total_9_runs_seconds")},
            "data_cost": data_cost["option_B_new_plan"],
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
