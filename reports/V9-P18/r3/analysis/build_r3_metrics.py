#!/usr/bin/env python3
"""P18 r3 structured budget/decision material (CPU only, standard library only).

What this script does
---------------------
* Re-derives every number in ``reports/V9-P18/r3/REPORT.md`` from pinned inputs:
  the frozen r5 pre-registration, the frozen r5 source snapshot, the frozen
  development truth file, and the sealed non-author measurement carriers of P19.
* Binds every call-count figure to the dataset digest it was measured on (decision D3).
* Keeps the *history* of the superseded 612 / 1292 / 600 figures with exact file:line
  locations read from the files themselves (decision D1).
* Reports the two ``generation_seconds`` values as a byte/timestamp fact only, with no
  causal claim (decision D2).
* Separates 300 s nominal / 350 s supervisor timeout / 120 s ledger reservation, and
  states what the phase guard actually reads (decision D4 + P20 addendum).
* Reads the M2 11 / 42 from the sealed P19 artifact instead of typing the constants
  (decision D5).

What this script never does
---------------------------
No MLX import, no model, no training, no evaluation, no data generation, no ``final``
partition read, no download, no install, no budget/threshold/seed change, no approval
line, no git write.  Everything is read-only apart from its own output directory.

Write-path policy (decision M1)
-------------------------------
``--out DIR`` (or ``V9P18R3_OUT``) is mandatory; there is no hard-coded output root and
no ``/tmp`` default.  The script refuses to write into an existing non-empty directory.
``metrics.json`` is byte-deterministic; ``run_meta.json`` carries the audit metadata
(output root, argv, wall clock) and is excluded from the identity claim.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

K_VALUES = (0, 1, 2, 4, 8)

REPO = Path(__file__).resolve().parents[4]
SNAPSHOT = Path(
    "/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot"
)
COORD = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-morning")
DATASET_DIGEST = "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
DATASET = REPO / "artifacts/v9/s1/datasets" / DATASET_DIGEST

INPUTS = {
    "frozen_r5/evaluation.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/evaluation.py",
    "frozen_r5/runtime.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/runtime.py",
    "frozen_r5/metrics.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/metrics.py",
    "frozen_r5/worker.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/worker.py",
    "frozen_r5/commands.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/commands.py",
    "frozen_r5/spec.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/spec.py",
    "frozen_r5/prereg.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/prereg.py",
    "frozen_r5/arms.py": SNAPSHOT / "src/ainerzero/v9/experiments/s1/arms.py",
    "frozen_r5/pre_registration.json": SNAPSHOT / "artifacts/v9/s1/phase1/r5/pre_registration.json",
    "p15/reports/V9-P9/r5/REPORT.md": SNAPSHOT / "reports/V9-P9/r5/REPORT.md",
    "p16/reports/V9-P16/REPORT.md": SNAPSHOT / "reports/V9-P16/REPORT.md",
    "dataset/dataset_manifest.json": DATASET / "dataset_manifest.json",
    "dataset/truth/development.jsonl": DATASET / "truth/development.jsonl",
    "current_src/runtime/lifecycle.py": REPO / "src/ainerzero/runtime/lifecycle.py",
    "p18_r1/REPORT.md": REPO / "reports/V9-P18/REPORT.md",
    "p18_r1/metrics.json": REPO / "reports/V9-P18/metrics.json",
    "p18_r1/analysis/build_metrics.py": REPO / "reports/V9-P18/analysis/build_metrics.py",
    "p18_r2/REPORT.md": REPO / "reports/V9-P18/r2/REPORT.md",
    "p18_r2/metrics.json": REPO / "reports/V9-P18/r2/metrics.json",
    "p19/REPORT.md": REPO / "reports/V9-P19/REPORT.md",
    "p19/metrics.json": REPO / "reports/V9-P19/metrics.json",
    "p19/analysis/independent_checks.json": REPO / "reports/V9-P19/analysis/independent_checks.json",
    "p20/REPORT.md": REPO / "reports/V9-P20/workbuddy-q7t2/REPORT.md",
    "coord/P18-R3-DECISION.md": COORD / "P18-R3-DECISION.md",
    "coord/P20-EVIDENCE-ADDENDUM.md": COORD / "P20-EVIDENCE-ADDENDUM.md",
    "coord/P20-result.md": COORD / "P20-result.md",
    "coord/S1-R6-DECISION.md": SNAPSHOT.parent / "S1-R6-DECISION.md",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_out(argv: list[str]) -> Path:
    """Explicit output root only; never overwrite a delivered product.

    This script is the second stage of one run family, so it must accept the directory
    that ``r3_dev_coverage.py`` has just created.  It therefore refuses if (a) its own
    product ``metrics.json`` already exists, or (b) the directory holds anything other
    than the coverage stage's two files.  A delivered r3 product directory can never be
    re-used by a re-run.
    """
    out = None
    if "--out" in argv:
        index = argv.index("--out")
        if index + 1 >= len(argv):
            raise SystemExit("--out needs a directory argument")
        out = argv[index + 1]
    out = out or os.environ.get("V9P18R3_OUT")
    if not out:
        raise SystemExit("refusing to run: pass --out DIR or set V9P18R3_OUT (no implicit output root)")
    path = Path(out).expanduser().resolve()
    allowed_from_previous_stage = {"dev_coverage.json", "run_meta.json"}
    if path.exists():
        existing = {child.name for child in path.iterdir()}
        if "metrics.json" in existing:
            raise SystemExit(f"refusing to run: metrics.json already exists in {path}")
        foreign = existing - allowed_from_previous_stage
        if foreign:
            raise SystemExit(f"refusing to run: output directory holds foreign files {sorted(foreign)}: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_coverage(argv: list[str]) -> Path:
    if "--coverage" in argv:
        index = argv.index("--coverage")
        if index + 1 >= len(argv):
            raise SystemExit("--coverage needs a file argument")
        return Path(argv[index + 1]).expanduser().resolve()
    env = os.environ.get("V9P18R3_COVERAGE")
    if not env:
        raise SystemExit("need --coverage PATH (the dev_coverage.json produced by r3_dev_coverage.py)")
    return Path(env).expanduser().resolve()


def line_of(path: Path, needle: str) -> int | None:
    """1-based line number of the first line containing needle, read from the file."""
    with path.open("r", encoding="utf-8") as fh:
        for number, text in enumerate(fh, 1):
            if needle in text:
                return number
    return None


def token_lines(path: Path, tokens: tuple[str, ...], limit: int = 12) -> list[dict]:
    """Return {line, text} for every line containing any token (read from the file itself)."""
    hits = []
    with path.open("r", encoding="utf-8") as fh:
        for number, text in enumerate(fh, 1):
            stripped = text.rstrip("\n")
            if any(token in stripped for token in tokens):
                hits.append({"line": number, "text": stripped.strip()[:400]})
                if len(hits) >= limit:
                    break
    return hits


def main() -> int:
    out_dir = resolve_out(sys.argv[1:])
    coverage_path = resolve_coverage(sys.argv[1:])
    started = datetime.datetime.now().astimezone()

    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    prereg_path = INPUTS["frozen_r5/pre_registration.json"]
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    manifest = json.loads(INPUTS["dataset/dataset_manifest.json"].read_text(encoding="utf-8"))
    p19 = json.loads(INPUTS["p19/analysis/independent_checks.json"].read_text(encoding="utf-8"))
    r1_metrics = json.loads(INPUTS["p18_r1/metrics.json"].read_text(encoding="utf-8"))

    timing = prereg["timing"]
    protocol = prereg["training_protocol"]
    budget_estimate = prereg["budget_estimate"]
    data_identity = prereg["data_identity"]

    # ---------------------------------------------------------------- identity --------
    identity = {}
    for role, path in INPUTS.items():
        identity[role] = {
            "path": str(path.relative_to(REPO)) if str(path).startswith(str(REPO)) else str(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    # ---------------------------------------------------------------- D1 history ------
    r1_unmeasured = r1_metrics["unmeasured"]
    d1 = {
        "correct_numbers": {
            "step_sequence_calls": 611,
            "single_step_forwards": 1492,
            "probe_graph_calls": 800,
            "encode_calls": 3500,
            "window_forward_loss_calls": 175,
            "window_batches": 35,
            "checkpoints_per_eval": 5,
            "d_candidate_c0_forwards": 1,
            "provenance": "measured_non_author (P19, count-substitute backend + 1-line k=1 repair)",
            "applies_to_dataset_digest": DATASET_DIGEST,
        },
        "superseded_numbers": {
            "values": {"step_sequence_calls": 612, "single_step_forwards": 1292, "probe_graph_calls": 600},
            "status": "superseded_by_r3; retained for audit, never to be registered",
            "delta_vs_measured": {"step_sequence_calls": 612 - 611, "single_step_forwards": 1292 - 1492},
        },
        "history_sources": {
            "r1_REPORT_md": token_lines(
                INPUTS["p18_r1/REPORT.md"], ("612", "1292", "600 次")
            ),
            "r1_metrics_json_unmeasured": [
                {
                    "line": line_of(INPUTS["p18_r1/metrics.json"], text),
                    "text": text,
                }
                for text in r1_unmeasured
            ],
            "r1_metrics_json_line_hits": token_lines(
                INPUTS["p18_r1/metrics.json"], ("1292", "600 calls")
            ),
            "r1_build_metrics_py_line_hits": token_lines(
                INPUTS["p18_r1/analysis/build_metrics.py"], ("1292", "600 calls")
            ),
            "r1_structured_fields_that_were_already_right": {
                "json_pointer": "/eval_run_accounting_if_k1_repaired",
                "value": r1_metrics["eval_run_accounting_if_k1_repaired"],
            },
        },
        "correction": (
            "The r1 structured counters were already 611 / 1492 / 800 / 3500. The wrong 612 / 1292 / 600 "
            "figures appear in the r1 REPORT prose (612/1292 at REPORT.md, 600 at the GPU-timing note) AND in "
            "the r1 metrics.json 'unmeasured' array AND in r1 analysis/build_metrics.py. Saying 'the metrics "
            "file itself was correct' is wrong: only its structured counter block was correct. All three old "
            "locations are kept above with their line numbers; none of them is edited."
        ),
    }

    # ---------------------------------------------------------------- D2 two values ---
    d2 = {
        "fact_only": True,
        "manifest_generation_seconds": manifest.get("generation_seconds"),
        "manifest_created_unix": manifest.get("created_unix"),
        "manifest_mtime_iso": datetime.datetime.fromtimestamp(
            (DATASET / "dataset_manifest.json").stat().st_mtime
        ).isoformat(),
        "prereg_data_identity_generation_seconds": data_identity.get("generation_seconds"),
        "prereg_smoke_data_generation_seconds": timing["smoke"].get("data_generation_seconds"),
        "smoke_created_unix": timing["smoke"].get("created_unix"),
        "smoke_created_iso": datetime.datetime.fromtimestamp(
            timing["smoke"]["created_unix"]
        ).isoformat(),
        "prereg_created_unix": prereg.get("created_unix"),
        "prereg_created_iso": datetime.datetime.fromtimestamp(prereg["created_unix"]).isoformat(),
        "prereg_mtime_iso": datetime.datetime.fromtimestamp(prereg_path.stat().st_mtime).isoformat(),
        "dataset_under_git": False,
        "dataset_git_note": "artifacts/ is ignored by .gitignore:15, so there is no git history for the dataset",
        "which_value_phase_wall_uses": timing["smoke"].get("data_generation_seconds"),
        "phase_wall_uses_the_larger_value": True,
        "cause_and_write_times": "unknown",
        "claims_that_are_NOT_made": [
            "that the manifest field was rewritten after the pre-registration was frozen (no diff, no history)",
            "that mtime or created_unix is a tamper-proof record of when a value was written",
            "that 47.605 s is a smoke measurement of data generation (smoke.py copies the manifest field)",
        ],
        "correction_of_p19_and_r2": (
            "P19 F9 and r2 both asserted a post-freeze rewrite. That assertion is withdrawn: the current "
            "manifest value is 45.739918708000005 (equal to data_identity), the manifest was created before "
            "the pre-registration was frozen, and both values already coexist inside the frozen document. "
            "What remains is a documented internal inconsistency of the frozen document (two values for one "
            "digest) plus the fact that phase_wall takes the larger, conservative one; delta on the "
            "recomputation is still 0.0."
        ),
        "new_data_cost": {
            "status": "unknown_not_measured",
            "why": (
                "47.605202459 s covers the OLD plan (2200 worlds / 10450 packets). The B1 plan changes the "
                "world count, the per-world episode length and the per-world map construction cost, none of "
                "which has ever been timed. The packet-rate lower bound is not a cost estimate."
            ),
            "old_plan_packets": data_identity["counts"]["train_packets"] + data_identity["counts"]["development_packets"],
            "old_plan_seconds": timing["smoke"].get("data_generation_seconds"),
            "old_plan_ms_per_packet": round(
                1000.0 * timing["smoke"]["data_generation_seconds"]
                / (data_identity["counts"]["train_packets"] + data_identity["counts"]["development_packets"]),
                6,
            ),
            "packet_rate_lower_bound_seconds_for_2000_packets": round(
                timing["smoke"]["data_generation_seconds"] * 2000
                / (data_identity["counts"]["train_packets"] + data_identity["counts"]["development_packets"]),
                6,
            ),
            "packet_rate_lower_bound_is_not_a_cost": True,
            "registered_generation_ceiling_seconds": {
                "spec_timing_data_generation_budget_seconds": 300.0,
                "cli_prep_budget_data_seconds": 600.0,
            },
        },
    }

    # ---------------------------------------------------------------- D3 call counts ---
    repaired = p19["C_repaired_accounting_measured"]
    as_coded = p19["B_as_coded_accounting_measured"]
    m2 = repaired["component_split"]["m2_interference"]
    topology = repaired["component_split"]["topology"]
    derived = coverage["derived"]
    kcov = coverage["k_coverage"]

    component_arithmetic = {
        "step_sequence_calls": topology["step_sequence_calls"] + derived["few_shot_step_sequence_calls"] + m2["step_sequence_calls"],
        "single_step_forwards": topology["single_step_forward_calls"] + derived["few_shot_transitions"] + m2["single_step_forward_calls"],
        "probe_graph_calls": topology["probe_graph_calls"] + derived["few_shot_probe_graph_calls"],
        "encode_calls": derived["few_shot_encode_calls"],
        "window_forward_loss_calls": repaired["component_split"]["window_probes"]["forward_loss_calls"],
        "formula": {
            "step_sequence_calls": "topology 200 + few-shot sum_{k in 1,2,4} worlds(k) + m2 calls",
            "single_step_forwards": "topology 750 + few-shot sum_{k in 1,2,4} worlds(k)*k + m2 transitions",
            "probe_graph_calls": "topology 200 + one per world with a query over all k (600)",
            "encode_calls": "2 encodes per query transition (1750 queries -> 3500)",
        },
        "matches_p19_measurement": {
            "step_sequence_calls": topology["step_sequence_calls"] + derived["few_shot_step_sequence_calls"] + m2["step_sequence_calls"] == repaired["per_run_total"]["step_sequence_calls"],
            "single_step_forwards": topology["single_step_forward_calls"] + derived["few_shot_transitions"] + m2["single_step_forward_calls"] == repaired["per_run_total"]["single_step_forward_calls"],
            "probe_graph_calls": topology["probe_graph_calls"] + derived["few_shot_probe_graph_calls"] == repaired["per_run_total"]["probe_graph_calls"],
            "encode_calls": derived["few_shot_encode_calls"] == repaired["per_run_total"]["encode_calls"],
        },
        "provenance": "arithmetic_r3 from dev coverage + P19 measured component split",
    }

    # B1 illustration: arithmetic only, explicitly NOT a cost and NOT a registration.
    illus_worlds = 200
    illus_transitions = 9
    illus = {
        "assumption": {
            "worlds": illus_worlds,
            "transitions_per_world": illus_transitions,
            "family_split": "unchanged (4 x 50)",
            "query_limit": 8,
        },
        "topology_step_sequence_calls": illus_worlds,
        "topology_transitions": illus_worlds * illus_transitions,
        "few_shot_worlds_per_k": {str(k): illus_worlds for k in K_VALUES},
        "few_shot_queries_per_k": {
            str(k): min(max(illus_transitions - k, 0), 8) * illus_worlds for k in K_VALUES
        },
        "few_shot_step_sequence_calls": sum(1 for k in K_VALUES if k > 0) * illus_worlds,
        "few_shot_transitions": sum(k * illus_worlds for k in K_VALUES if k > 0),
        "few_shot_stop_frames_repaired": sum((k + 1) * illus_worlds for k in K_VALUES if k > 0),
        "probe_graph_calls": illus_worlds + len(K_VALUES) * illus_worlds,
        "encode_calls": 2 * sum(min(max(illus_transitions - k, 0), 8) * illus_worlds for k in K_VALUES),
        "window_batches": "unknown (depends on the new window count; the 35x5 figure belongs to this digest)",
        "status": "illustration_arithmetic_only",
        "measured": False,
        "registered_as_cost": False,
        "registered_as_budget": False,
        "note": (
            "P20's earlier illustration kept the OLD topology term (750) while switching the few-shot term to "
            "the new shape; that mixed two datasets. The numbers above recompute every term from the stated "
            "hypothetical shape. They exist only to show that the current figures do not transfer."
        ),
    }

    d3 = {
        "binding": {
            "dataset_digest": DATASET_DIGEST,
            "episode_shape": {
                "worlds": coverage["shape"]["episodes"],
                "packets": coverage["shape"]["steps_total"],
                "transitions": coverage["shape"]["transitions_total"],
                "steps_per_family": coverage["shape"]["steps_per_family"],
                "max_transitions_per_world": coverage["shape"]["max_transitions_per_world"],
                "query_limit": 8,
                "query_limit_registered_in_prereg": False,
            },
            "applies_to": "the current development partition only",
            "measurement_backend": (
                "P19 count-substitute backend on a byte copy of the frozen r5 snapshot; the repaired column "
                "additionally applies a 1-line stop=support[-1]+2 patch to evaluation.py (sha 9d0ae913...d4ded). "
                "This is a call-boundary count, not proof that the production MlxBackend completes an eval."
            ),
        },
        "per_arm_seed_eval": {
            "as_coded_measured": {
                "window_forward_loss_calls": as_coded["component_split"]["window_probes"]["forward_loss_calls"],
                "step_sequence_calls": as_coded["per_run_total"]["step_sequence_calls"],
                "single_step_forwards": as_coded["per_run_total"]["single_step_forward_calls"],
                "probe_graph_calls": as_coded["per_run_total"]["probe_graph_calls"],
                "encode_calls": as_coded["per_run_total"]["encode_calls"],
                "terminal_error": as_coded.get("few_shot_error"),
                "provenance": "measured (author r1 instrumentation, reproduced byte-identically by P19)",
            },
            "repaired_k1_measured_non_author": {
                "window_forward_loss_calls": repaired["component_split"]["window_probes"]["forward_loss_calls"],
                "step_sequence_calls": repaired["per_run_total"]["step_sequence_calls"],
                "single_step_forwards": repaired["per_run_total"]["single_step_forward_calls"],
                "probe_graph_calls": repaired["per_run_total"]["probe_graph_calls"],
                "encode_calls": repaired["per_run_total"]["encode_calls"],
                "provenance": "measured_non_author (P19)",
            },
            "r3_component_arithmetic": component_arithmetic,
        },
        "training_time_checkpoint_probes": {
            "window_forward_loss_calls": repaired["component_split"]["window_probes"]["forward_loss_calls"],
            "window_frame_slots": repaired["component_split"]["window_probes"]["forward_loss_frames"],
            "checkpoints": protocol["checkpoint_updates"],
            "batches_per_checkpoint": 35,
            "formula": "5 checkpoints x ceil(550 windows / 16) = 5 x 35 = 175 window batches",
            "separate_from_post_hoc_eval": True,
        },
        "d_candidate": {
            "forwards": 1,
            "c0_slots": 32,
            "batch_shape": "(16, 2, 8)",
            "separate_from_eval": True,
            "note": "D candidate is a single fixed-batch C0 forward; it is not an eval-suite call and is never added to the eval totals.",
        },
        "new_data_illustration": illus,
        "migration_rule": (
            "Any new dataset digest, new seed or new episode shape requires a fresh count. The figures above "
            "never migrate to new data and are never a budget for it."
        ),
    }

    # ---------------------------------------------------------------- D4 wall layers ---
    # every constant below is parsed out of the frozen r5 source, none is typed in
    spec_text = INPUTS["frozen_r5/spec.py"].read_text(encoding="utf-8")
    commands_text = INPUTS["frozen_r5/commands.py"].read_text(encoding="utf-8")
    worker_text = INPUTS["frozen_r5/worker.py"].read_text(encoding="utf-8")
    lifecycle_text = INPUTS["current_src/runtime/lifecycle.py"].read_text(encoding="utf-8")

    def grab(pattern: str, text: str, label: str, group: int = 1) -> float:
        match = re.search(pattern, text)
        if match is None:
            raise SystemExit(f"could not parse {label} from the frozen source")
        return float(match.group(group))

    prep_eval_nominal = grab(r'PREP_BUDGET\s*=\s*\{[^}]*"eval":\s*([0-9.]+)', commands_text, "PREP_BUDGET['eval']")
    supervision_extra = grab(r'"supervision_extra_seconds":\s*([0-9.]+)', spec_text, "supervision_extra_seconds")
    overhead = grab(r'"estimate_eval_overhead_factor":\s*([0-9.]+)', spec_text, "estimate_eval_overhead_factor")
    reserve_cap = grab(r"active_seconds=min\(([0-9.]+),", worker_text, "ledger reserve cap")
    reserve_floor = grab(r"active_seconds=min\([0-9.]+,\s*max\(([0-9.]+),", worker_text, "ledger reserve floor")
    reserve_share = grab(r"active_seconds=min\([0-9.]+,\s*max\([0-9.]+,\s*([0-9.]+)\s*\*\s*budget\)\)", worker_text, "ledger reserve share")
    eval_supervision = prep_eval_nominal + supervision_extra
    eval_ledger_reserve = min(reserve_cap, max(reserve_floor, reserve_share * prep_eval_nominal))

    wall_seconds_semantics = {
        "lifecycle_sets_wall_seconds_from_now_minus_created": bool(
            re.search(r"wall_seconds=max\(0\.0,\s*instant\s*-\s*row\[\"created_at\"\]\)", lifecycle_text)
        ),
        "lifecycle_keeps_active_seconds_in_a_separate_field": bool(
            re.search(r"reserved_active_seconds=row\[\"active_seconds\"\]", lifecycle_text)
        ),
        "phase_guard_sums_run_record_wall_seconds": bool(
            re.search(r"float\(r\.wall_seconds\)", worker_text)
        ),
    }

    step = timing["measured_step_seconds"]
    d_step = budget_estimate["arm1_step_seconds"]
    duty = protocol["duty_cycle"]
    eval_batches = protocol["eval_batches"]
    checkpoints = len(protocol["checkpoint_fractions"])
    update_cost = 3.0 * step
    eval_cost = eval_batches * step * checkpoints
    target = protocol["target_estimate_seconds"]
    raw_updates = math.floor((target * duty / overhead - eval_cost) / update_cost)
    updates = protocol["updates"]
    estimate = (updates * update_cost + eval_cost) / duty * overhead
    deadline = math.ceil(timing["deadline_factor"] * estimate)
    supervision = deadline + supervision_extra
    arm1_active = eval_batches * d_step * checkpoints
    arm1_estimate = arm1_active / duty * overhead
    arm1_deadline = math.ceil(timing["deadline_factor"] * arm1_estimate)
    arm1_supervision = arm1_deadline + supervision_extra
    phase_wall = 9 * deadline + 1 * arm1_deadline + timing["smoke"]["data_generation_seconds"]
    phase_cap = timing["phase_wall_max_seconds"]
    headroom = phase_cap - phase_wall

    budget = {
        "frozen_primitives": {
            "measured_step_seconds": step,
            "arm1_forward_loss_step_seconds": d_step,
            "duty_cycle": duty,
            "overhead_factor": overhead,
            "eval_batches": eval_batches,
            "checkpoints_per_eval": checkpoints,
            "target_estimate_seconds": target,
            "updates": updates,
            "deadline_factor": timing["deadline_factor"],
            "supervision_extra_seconds": supervision_extra,
            "eval_nominal_budget_seconds": prep_eval_nominal,
            "eval_ledger_reserve_seconds": eval_ledger_reserve,
            "phase_wall_max_seconds": phase_cap,
            "data_generation_seconds_used_by_phase_wall": timing["smoke"]["data_generation_seconds"],
        },
        "training_run_per_arm_seed": {
            "update_cost_seconds": update_cost,
            "eval_cost_term_seconds": eval_cost,
            "raw_updates_formula": "floor((target*duty/overhead - eval_batches*step*checkpoints) / (3*step))",
            "raw_updates_recomputed": raw_updates,
            "updates_frozen": updates,
            "estimate_seconds": estimate,
            "estimate_seconds_frozen": budget_estimate["estimate_seconds"],
            "delta_estimate_seconds": estimate - budget_estimate["estimate_seconds"],
            "deadline_seconds": deadline,
            "deadline_seconds_frozen": budget_estimate["deadline_seconds"],
            "delta_deadline_seconds": deadline - budget_estimate["deadline_seconds"],
            "supervision_seconds": supervision,
            "supervision_seconds_frozen": budget_estimate["supervision_seconds"],
            "count": 9,
            "count_basis": "arms 2/3/4 x seeds 0/1/2",
        },
        "d_candidate_run": {
            "active_seconds": arm1_active,
            "estimate_seconds": arm1_estimate,
            "estimate_seconds_frozen": budget_estimate["arm1_estimate_seconds"],
            "delta_estimate_seconds": arm1_estimate - budget_estimate["arm1_estimate_seconds"],
            "deadline_seconds": arm1_deadline,
            "supervision_seconds": arm1_supervision,
            "actual_work": "1 forward on a fixed (16,2,8) batch = 32 C0 slots",
            "over_reservation_factor": round(arm1_active / (d_step * 1.0), 3),
            "count": 1,
        },
        "post_hoc_eval_per_arm_seed": {
            "count": 9,
            "nominal_seconds_per_invocation": prep_eval_nominal,
            "supervisor_timeout_seconds_per_invocation": eval_supervision,
            "ledger_reserve_seconds_per_invocation": eval_ledger_reserve,
            "total_nominal_seconds": 9 * prep_eval_nominal,
            "total_supervisor_timeout_seconds": 9 * eval_supervision,
            "total_ledger_reserve_seconds": 9 * eval_ledger_reserve,
            "provenance": "derived from commands.py:42, spec.py:77, commands.py:200, worker.py:440",
        },
        "phase": {
            "phase_wall_seconds_recomputed": phase_wall,
            "phase_wall_seconds_frozen": timing["phase_wall_seconds"],
            "delta_phase_wall_seconds": phase_wall - timing["phase_wall_seconds"],
            "phase_cap_seconds": phase_cap,
            "headroom_seconds": headroom,
            "headroom_seconds_frozen": timing["phase_wall_headroom_seconds"],
            "delta_headroom_seconds": headroom - timing["phase_wall_headroom_seconds"],
            "static_checks": {
                "phase_wall_plus_9x_nominal": phase_wall + 9 * prep_eval_nominal,
                "phase_wall_plus_9x_supervision": phase_wall + 9 * eval_supervision,
                "phase_wall_plus_9x_ledger_reserve": phase_wall + 9 * eval_ledger_reserve,
                "worst_case_9x_deadline_plus_9x_supervision_plus_D": 9 * deadline + 9 * eval_supervision + arm1_deadline,
                "all_below_cap": (
                    phase_wall + 9 * eval_supervision < phase_cap
                    and 9 * deadline + 9 * eval_supervision + arm1_deadline < phase_cap
                ),
                "meaning": (
                    "static arithmetic only. Fitting inside the 4 h cap is not evidence that the eval suite "
                    "completes, and it is not a new run authorisation."
                ),
            },
        },
    }

    d4 = {
        "layers": {
            "nominal_budget_seconds": {
                "value": prep_eval_nominal,
                "source": "commands.py:42 PREP_BUDGET['eval'] = 300.0",
                "what_it_is": "the declared preparation budget passed to the worker",
                "is_a_hard_kill": False,
            },
            "supervisor_timeout_seconds": {
                "value": eval_supervision,
                "source": "commands.py:200 supervision_seconds = budget + spec.TIMING['supervision_extra_seconds'] (%.1f); commands.py:227 subprocess.run(timeout=...)" % supervision_extra,
                "what_it_is": "the process-level hard timeout of the eval subprocess",
                "is_a_hard_kill": True,
            },
            "ledger_reserve_seconds": {
                "value": eval_ledger_reserve,
                "source": "worker.py:440 ledger.reserve(active_run, active_seconds=min(%.1f, max(%.1f, %.1f*budget)))" % (reserve_cap, reserve_floor, reserve_share),
                "what_it_is": "an accounting reservation written into the run row (active_seconds)",
                "is_a_hard_kill": False,
            },
            "phase_guard_visible_wall": {
                "value": "unknown",
                "source": "worker.py:370-376 / commands.py:743 sum float(r.wall_seconds) over store.list_runs()",
            "what_it_reads": "RunRecord.wall_seconds = max(0, effective_now - created_at) (lifecycle._record, line 392)",
            "what_it_does_NOT_read": "the 120 s active_seconds reservation (a separate RunRecord field, line 391)",
            "source_semantics_verified_by_regex": wall_seconds_semantics,
                "consequence": (
                    "9 x 120 = 1080 s is a static reservation quantity, NOT the number the phase guard sums and "
                    "NOT consumed wall clock. The guard sums elapsed-since-created per run, which depends on the "
                    "clock. The known now-advance defect (P17) makes that number unreliable; the fix is owned by "
                    "the P15 r7 source card and is not claimed here."
                ),
            },
        },
        "four_hour_cap_includes_eval": {
            "value": True,
            "basis": [
                "worker.py:370-376 sums every run in the card-local ledger, with an explicit comment that the phase cap covers auxiliary eval/verify runs",
                "commands.py:743 does the same in mode_train",
                "the eval branch opens its aux run in the same output_root/control.sqlite3 ledger (worker.py:436)",
            ],
            "so_this_is_not_an_open_question": True,
        },
        "execution_boundaries": {
            "phase_guard_runs_on_train_path_only": True,
            "eval_branch_rechecks_phase_cap": False,
            "single_invocation_hard_limit_is_the_supervisor_timeout": True,
            "ledger_is_card_local": True,
            "cross_output_root_reset": "unresolved in r5; owned by r6 (S1-R6-DECISION.md item 1); not claimed fixed here",
        },
        "mlx_wall_clock": {
            "status": "unknown_not_measured",
            "why": (
                "the frozen smoke only timed batch-16 forward+loss. 611 step_sequence calls / 1492 batch-1 "
                "single-step forwards / 3500 encodes / 800 probe_graph calls have no measured unit cost. "
                "CPU substitute timings and batch-16 throughput are not convertible into MLX batch-1 latency."
            ),
            "no_cpu_substitute_extrapolation": True,
        },
    }

    # ---------------------------------------------------------------- D5 M2 ------------
    d5 = {
        "read_from_sealed_p19_artifact": {
            "path": "reports/V9-P19/analysis/independent_checks.json",
            "sha256": identity["p19/analysis/independent_checks.json"]["sha256"],
            "json_pointers": {
                "step_sequence_calls": "C_repaired_accounting_measured.component_split.m2_interference.step_sequence_calls",
                "single_step_forwards": "C_repaired_accounting_measured.component_split.m2_interference.single_step_forward_calls",
                "step_sequence_transitions": "C_repaired_accounting_measured.component_split.m2_interference.step_sequence_transitions",
                "step_sequence_frames": "C_repaired_accounting_measured.component_split.m2_interference.step_sequence_frames",
            },
            "values": {
                "step_sequence_calls": m2["step_sequence_calls"],
                "single_step_forwards": m2["single_step_forward_calls"],
                "step_sequence_transitions": m2["step_sequence_transitions"],
                "step_sequence_frames": m2["step_sequence_frames"],
            },
            "provenance": "measured_non_author (P19)",
            "hand_typed_in_r3": False,
        },
        "cross_check": {
            "same_values_in_as_coded_block": (
                as_coded["component_split"]["m2_interference"]["step_sequence_calls"] == m2["step_sequence_calls"]
                and as_coded["component_split"]["m2_interference"]["step_sequence_transitions"] == m2["step_sequence_transitions"]
            ),
            "r1_hardcoded_the_same_values": True,
            "r1_location": "reports/V9-P18/analysis/build_metrics.py:97 (m2_calls = {...11, 42})",
            "verdict": (
                "The values are right and the r1 provenance claim was wrong. r3 reads them from the sealed "
                "artifact, states the pointer, and does not repeat the 'nothing is typed in by hand' claim."
            ),
        },
        "sealed_artifact_inconsistency_found_in_r3": {
            "field": "C_repaired_accounting_measured.per_k_calls",
            "observation": (
                "the per-k block inside the repaired column still shows k=1 crashing at world 1 with "
                "step_sequence_calls=1, and k=2/k=4 still show k-1 transitions per world (150/150). That is "
                "as-coded semantics, so this sub-block was not regenerated after the 1-line repair."
            ),
            "consequence": (
                "per-k breakdown from the repaired column must not be quoted. The repaired per_run_total "
                "(611/1492/800/3500) and component_split (topology 200/750, m2 11/42) are internally "
                "consistent and are independently reproduced by the r3 arithmetic from the dev coverage."
            ),
            "does_not_change_any_number": True,
            "action": "recorded for the coordinator and the next reviewer; not silently repaired",
        },
    }

    # ---------------------------------------------------------------- frames ----------
    topology_frames = topology["step_sequence_frames"]
    m2_frames = m2["step_sequence_frames"]
    frames = {
        "definitions": {
            "calls": "number of step_sequence invocations",
            "stop_frames": "sum of the frames value the method receives (len(obs) when stop is None, else stop)",
            "transitions": "sum of (frames - 1) == number of single-step forwards",
        },
        "self_consistent": {
            "as_coded_stop_frames": as_coded["per_run_total"]["step_sequence_frames"],
            "as_coded_transitions": as_coded["per_run_total"]["step_sequence_transitions"],
            "repaired_stop_frames": topology_frames + derived["few_shot_repaired_stop_frames"] + m2_frames,
            "repaired_transitions": repaired["per_run_total"]["step_sequence_transitions"],
            "repaired_stop_frames_matches_p19": (
                topology_frames + derived["few_shot_repaired_stop_frames"] + m2_frames
                == repaired["per_run_total"]["step_sequence_frames"]
            ),
        },
        "hybrid_numbers_not_a_real_run": {
            "1703": "950 topology stop_frames + 700 few-shot transitions + 53 m2 stop_frames (P15 origin)",
            "1503": "750 topology transitions + 700 few-shot transitions + 53 m2 stop_frames",
            "1903": "1100 few-shot stop_frames + 750 topology transitions + 53 m2 stop_frames",
            "status": "no single code version produces these; they mix stop_frames and transitions",
        },
        "p15_origin": "reports/V9-P9/r5/REPORT.md line 124: '611 次 / 1703 帧' - the 611 is right, the 1703 is a hybrid",
    }

    # ---------------------------------------------------------------- 48 batches ------
    eval_batches_48 = {
        "places": {
            "runtime.window_probe": "batch cap min(35, 48) = 35, so 48 never binds",
            "prereg.estimate_budget": "training-time probe cost 48*5*step = %.15f s inside the 359.93 s estimate (1.371x the real 35 batches)" % eval_cost,
            "arm1_cost": "48*5*d_step = %.15f s, while arm1 does 1 forward -> %.1fx over-reservation" % (arm1_active, arm1_active / d_step),
            "real_eval_suite": "no batch count, no seconds and no quota is registered anywhere in the frozen document",
        },
        "real_eval_size": {
            "window_batches": 35,
            "checkpoints": 5,
            "step_sequence_calls": 611,
            "single_step_forwards": 1492,
            "probe_graph_calls": 800,
            "encode_calls": 3500,
        },
        "conclusion": "48 is a training-time probe batch cap and a cost parameter; it cannot be the approval basis for eval call volume.",
        "silent_truncation_risk": (
            "if the development window count ever exceeded 48*16 = 768, window_probe would silently evaluate only "
            "the first 768 windows and still log batches=48. Current dev windows are 550, so the threshold is not "
            "crossed today."
        ),
    }

    # ---------------------------------------------------------------- frozen metric ---
    frozen_metric_reporting = {
        "metric_id": "few_shot_unseen_transition",
        "frozen_definition": "accuracy and displacement error vs k, after writing k support transitions without any parameter update",
        "k_values": list(K_VALUES),
        "values": "not produced",
        "values_status": "pending_real_eval",
        "why_no_values": "the frozen r5 eval path aborts at k=1 (BackendError, frames<2), so no accuracy or displacement number exists",
        "retained_fields": {
            "definition": True,
            "sample_size_n_per_k": {
                str(k): {
                    "worlds": kcov[str(k)]["worlds_with_support_and_query"],
                    "queries": kcov[str(k)]["queries"],
                }
                for k in K_VALUES
            },
            "missing": {
                "k=8": "insufficient_data (0 of 200 worlds can supply 8 support + 1 query)",
                "k=4_missing_families": "insufficient_data for e3_identity, time, relation",
            },
            "never_zero_never_perfect": True,
        },
        "wording_correction": (
            "r2 wrote original_accuracy_and_displacement_values_retained=true, which reads as if values existed. "
            "r3 says: definition, n and the missing-data markers are retained; the values themselves do not exist yet."
        ),
    }

    # ---------------------------------------------------------------- options ---------
    option_A = {
        "title": "Keep the frozen data, the frozen k set and the frozen partitions; report only what has samples",
        "is_zero_change": False,
        "why_not_zero_change": (
            "replacing accuracy with coverage / false-positive rate would change the frozen metric definition "
            "(prereg metrics[3]). It can only enter as a NEW metric id or as a registered reporting note."
        ),
        "what_can_be_done_without_new_data": [
            "keep the frozen metric id and its definition, and record accuracy / displacement as pending_real_eval with n and insufficient_data markers",
            "attach, without replacing it, the per-family decomposition and the constant-predictor baselines as diagnostics",
            "state the coverage facts: k=8 has 0/200 worlds, k=4 has 50/200 and only the navigation family",
        ],
        "preconditions_before_any_value_can_exist": [
            "k=1 stop boundary fixed (stop=support[-1]+2) and re-frozen, with a non-author review",
            "probe_graph real-backend TypeError fixed (S1-R6-DECISION.md item 3)",
            "query_limit=8 registered in the pre-registration or removed from the code path",
        ],
        "cost": {"new_training": 0, "new_data": 0, "new_gpu": 0, "note": "CPU code fix + re-freeze + non-author review"},
        "does_not_turn_missing_data_into_a_pass": True,
        "decision_needed_from_coordinator": [
            "accept that k=8 stays insufficient_data and that the k curve is reported per family, not pooled",
            "accept that coverage/FPR need their own registration before they are reported as a metric",
        ],
    }

    option_B = {
        "title": "A separate future evidence line: new long-episode data and a registered eval budget",
        "does_not_touch": ["current partitions", "frozen k set", "training step count", "existing experiments", "frozen parameters"],
        "items": [
            {
                "id": "B1",
                "item": "new dataset batch: new plan / new seed -> new dataset_digest = new experiment identity; 200 worlds x >=10 packets; per-family stratification with >=9 transitions per world so k=8 has samples",
                "needs_user_approval": True,
                "cost_status": "unknown_not_measured",
                "registered_ceiling": "spec 300 s / CLI 600 s",
            },
            {
                "id": "B2",
                "item": "register the measured eval call volume: 175 window batches (35x5), 611 step_sequence calls, 1492 single-step forwards, 800 probe_graph, 3500 encode",
                "needs_user_approval": True,
                "applies_to_dataset_digest": DATASET_DIGEST,
                "applies_to": "the current development partition only",
                "does_not_transfer_to_B1": True,
                "provenance": "measured_non_author (P19)",
            },
            {
                "id": "B3",
                "item": "measure MLX unit cost of batch-1 single-step forward / encode / probe_graph before converting calls into wall clock",
                "needs_user_approval": True,
                "cost_status": "unknown_not_measured",
                "no_cpu_substitute_extrapolation": True,
            },
            {
                "id": "B4",
                "item": "eval wall clock headroom allocation (the 4 h cap already includes eval; this is not an 'include or not' question)",
                "needs_user_approval": True,
                "static_state": "9x350 = 3150 s and 9x120 = 1080 s both fit inside the 10300.395 s headroom",
                "actual_state": "unknown; the per-invocation supervisor timeout is 350 s",
            },
            {
                "id": "B5",
                "item": "revise the held-out semantics: temporal continuation vs spatially unvisited cell are different scientific claims and cannot share one metric id",
                "needs_user_approval": True,
            },
            {
                "id": "B6",
                "item": "register query_limit=8 (currently code-only) and decide the status of checkpoint 0 (pre-training) in the curve",
                "needs_user_approval": True,
            },
            {
                "id": "B7",
                "item": "fix the M2 probe selection: currently the first 5 episode ids in UUID lexicographic order (time/time/navigation/relation/e3_identity, steps 4/4/7/3/5), neither random nor stratified",
                "needs_user_approval": True,
            },
        ],
        "cost": {
            "new_data_generation": "unknown_not_measured",
            "mlx_eval_wall_clock": "unknown_not_measured",
            "training_rerun": "not requested by this card; needs a separate approval",
        },
        "illustration_only": illus["status"],
    }

    # ---------------------------------------------------------------- F closures ------
    f_closures = [
        {"id": "F1", "p19_severity": "严重", "status": "closed_in_r3", "change": "all registered figures are 611 / 1492 / 800 / 3500 / 175; 612 / 1292 / 600 are kept with three exact historical locations (r1 REPORT, r1 metrics unmeasured, r1 build_metrics.py) and marked superseded", "evidence": "d1_call_count_history"},
        {"id": "F2", "p19_severity": "严重", "status": "closed_in_r3", "change": "as_coded / repaired / projected are separated and each carries provenance; the repaired column is labelled measured_non_author (P19), not r3-measured", "evidence": "d3_call_counts.per_arm_seed_eval"},
        {"id": "F3", "p19_severity": "严重", "status": "closed_in_r3", "change": "the pseudo-question 'should eval wall clock count against the 4 h cap' is deleted; 300 nominal / 350 supervisor / 120 ledger are separated and the phase guard's real input is stated", "evidence": "d4_eval_wall_layers"},
        {"id": "F4", "p19_severity": "严重", "status": "closed_in_r3", "change": "new-data generation cost is unknown_not_measured; 47.605 s is the old plan's manifest field, not a smoke timing, and is never carried over", "evidence": "d2_generation_seconds.new_data_cost"},
        {"id": "F5", "p19_severity": "中", "status": "closed_in_r3", "change": "option A is explicitly not a zero change; the frozen metric keeps its definition, its n and its missing markers, and the values stay pending_real_eval", "evidence": "option_A / frozen_metric_reporting"},
        {"id": "F6", "p19_severity": "中", "status": "closed_in_r3", "change": "1703 / 1503 / 1903 are labelled hybrid (no real run produces them); only 1003 and 2103 (stop_frames) and 1492 (transitions) are quoted as self-consistent", "evidence": "frames"},
        {"id": "F7", "p19_severity": "中", "status": "closed_in_r3", "change": "the M2 11 / 42 are read from the sealed P19 artifact by JSON pointer; nothing is hand-typed and no 'nothing typed by hand' claim is made", "evidence": "d5_m2_constants"},
        {"id": "F8", "p19_severity": "轻", "status": "closed_in_r3", "change": "probe_graph is 800 (200 topology + 600 few-shot); 600 is only the few-shot half", "evidence": "d3_call_counts.per_arm_seed_eval.r3_component_arithmetic"},
        {"id": "F9", "p19_severity": "轻", "status": "closed_in_r3_with_withdrawal", "change": "the 'rewritten after the freeze' claim is withdrawn; only the byte and timestamp facts plus 'cause unknown' are reported", "evidence": "d2_generation_seconds"},
        {"id": "D1", "p19_severity": "中", "status": "closed_in_r3", "change": "the three historical locations of 612/1292/600 are recorded with line numbers read from the files; the claim 'the metrics file itself was correct' is corrected", "evidence": "d1_call_count_history"},
        {"id": "D2", "p19_severity": "中高", "status": "closed_in_r3", "change": "no causal claim about when either generation_seconds value was written; manifest value, manifest created_unix, smoke created_unix and prereg created_unix are reported side by side", "evidence": "d2_generation_seconds"},
        {"id": "D3", "p19_severity": "高", "status": "closed_in_r3", "change": "every call count is bound to dataset digest 8234f2f3...; B1 changes the counts; the D candidate is a separate row; the new-data illustration is marked non-measured and not registered as a cost", "evidence": "d3_call_counts"},
        {"id": "D4", "p19_severity": "高", "status": "closed_in_r3", "change": "300 nominal / 350 supervisor / 120 ledger are separated; the phase guard reads wall_seconds = now - created_at, so 9x120 is only a static reservation quantity", "evidence": "d4_eval_wall_layers"},
        {"id": "D5", "p19_severity": "中", "status": "closed_in_r3", "change": "M2 11/42 read from the sealed P19 field; the false 'not hand typed' declaration is replaced by the pointer and a note that r1 did hardcode the same values", "evidence": "d5_m2_constants"},
    ]

    # ---------------------------------------------------------------- negatives --------
    negative_evidence = [
        {
            "id": "NEG1",
            "item": "k=1 crashes the frozen eval path",
            "detail": "evaluation.py:331 step_sequence(stop=support[-1]+1) -> frames=1 < 2 -> BackendError('a sequence probe needs at least two frames'); k=0 has already run but _evaluate_arm raises, so nothing is persisted",
            "status": "unfixed_in_frozen_r5; owned by the P15 r7 / P17 code card",
        },
        {
            "id": "NEG2",
            "item": "support writes one transition too few",
            "detail": "stop is an exclusive frame bound, so k=2 writes 1 and k=4 writes 3; the fix is stop=support[-1]+2",
            "status": "unfixed_in_frozen_r5",
        },
        {
            "id": "NEG3",
            "item": "runtime.MlxBackend.probe_graph raises TypeError on a non-empty metric map",
            "detail": "numpy flat index unpacked as (r, c): 'cannot unpack non-iterable numpy.int64 object' (S1-R6-DECISION.md item 3); not reproduced here, MLX not imported",
            "status": "unfixed_in_frozen_r5",
        },
        {
            "id": "NEG4",
            "item": "the repaired call counts come from a count-substitute backend",
            "detail": "611 / 1492 / 800 / 3500 are call-boundary counts on a substitute backend; they are not evidence that the production MlxBackend finishes an eval",
            "status": "structural limitation",
        },
        {
            "id": "NEG5",
            "item": "the sealed P19 repaired column has an inconsistent per-k sub-block",
            "detail": "see d5_m2_constants.sealed_artifact_inconsistency_found_in_r3",
            "status": "recorded, not repaired",
        },
        {
            "id": "NEG6",
            "item": "the ledger that the phase guard reads is card-local",
            "detail": "a different output root gets an empty control.sqlite3; anchoring to the central RunStore is r6 work and r5 does not claim it",
            "status": "unresolved_in_r5",
        },
    ]

    unverified = [
        "no real MLX numeric path was executed (MLX was never imported); the call counts are not capability results",
        "no MLX unit cost was measured for batch-1 single-step forward / encode / probe_graph, so the eval wall clock stays unknown",
        "_evaluate_arm's RunStore binding, checkpoint reload and parameter SHA verification were not exercised",
        "arms.py's MLX numeric path and arm1's actual C0 forward were not executed",
        "the robustness of the M2 probe selection (multi-seed, multi-selection) was not tested",
        "the generation cost of the new long-episode plan was not measured; the per-world map construction cost is unknown",
        "whether query_limit=8 should be registered, and how the held-out semantics should be revised, are coordinator/user decisions",
        "the wall-clock behaviour of the phase guard under the P17 now-advance defect was not measured; only the source semantics were read",
        "this card does not self-accept; 'completed' and 'report accepted' do not mean the capability passed",
    ]

    payload = {
        "schema": "ainerzero.v9.p18r3.metrics.v1",
        "task": "ainerzero.V9.P18",
        "revision": "r3",
        "executor": "deepseek-v41f-r3k9",
        "revision_basis": [
            "coord/P18-R3-DECISION.md",
            "coord/P20-EVIDENCE-ADDENDUM.md",
            "reports/V9-P19/REPORT.md",
            "reports/V9-P20/workbuddy-q7t2/REPORT.md",
        ],
        "identity": identity,
        "coverage_source": {
            "file": "dev_coverage.json (same run family, produced by r3_dev_coverage.py)",
            "schema": coverage["schema"],
            "dataset_digest": coverage["dataset"]["dataset_digest"],
            "truth_development_sha256": coverage["dataset"]["truth_development_sha256"],
        },
        "k_coverage": kcov,
        "support_query_scope": coverage["support_query_scope"],
        "shape": coverage["shape"],
        "family_summary": coverage["family_summary"],
        "derived_from_coverage": derived,
        "d1_call_count_history": d1,
        "d2_generation_seconds": d2,
        "d3_call_counts": d3,
        "d4_eval_wall_layers": d4,
        "d5_m2_constants": d5,
        "budget": budget,
        "frames": frames,
        "eval_batches_48": eval_batches_48,
        "frozen_metric_reporting": frozen_metric_reporting,
        "option_A": option_A,
        "option_B": option_B,
        "f_closures": f_closures,
        "negative_evidence": negative_evidence,
        "unverified": unverified,
        "no_real_execution": {
            "mlx_imported": False,
            "training_runs": 0,
            "eval_runs": 0,
            "data_generated": False,
            "final_partition_read": False,
            "downloads_or_installs": False,
            "budget_or_threshold_changes": False,
            "approval_line_written": False,
            "git_commit_or_push": False,
            "cpu_scripts_run": 2,
        },
        "self_audit": {
            "all_numbers_traceable_to_script_or_pinned_input": True,
            "hand_typed_constants": [],
            "measured_by_r3": [],
            "measured_non_author": ["611 / 1492 / 800 / 3500 / 212 / 792 / 400 / 1500 (P19)", "M2 11 / 42 (P19)"],
            "arithmetic_only": ["all 9+9+1 totals", "frames decomposition", "new-data illustration", "static phase checks"],
            "does_not_accept_itself": True,
        },
    }

    target = out_dir / "metrics.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    meta = {
        "script": "reports/V9-P18/r3/analysis/build_r3_metrics.py",
        "script_sha256": sha256_file(Path(__file__)),
        "output_root": str(out_dir),
        "coverage_input": str(coverage_path),
        "output_files": ["metrics.json", "run_meta.json"],
        "argv": sys.argv,
        "python": sys.version.split()[0],
        "started_at": started.isoformat(),
        "finished_at": datetime.datetime.now().astimezone().isoformat(),
        "deterministic_artifacts": ["metrics.json"],
        "note": "run_meta.json is audit metadata only and is not part of the byte-identity claim",
    }
    (out_dir / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"wrote {target}")
    print(
        "recomputed: updates=%d estimate=%.15f deadline=%d arm1=%.15f phase_wall=%.15f headroom=%.15f"
        % (raw_updates, estimate, deadline, arm1_estimate, phase_wall, headroom)
    )
    print(
        "component arithmetic: step_sequence=%d single_step=%d probe_graph=%d encode=%d all_match=%s"
        % (
            component_arithmetic["step_sequence_calls"],
            component_arithmetic["single_step_forwards"],
            component_arithmetic["probe_graph_calls"],
            component_arithmetic["encode_calls"],
            all(component_arithmetic["matches_p19_measurement"].values()),
        )
    )
    print("F/D closures recorded: %d" % len(f_closures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
