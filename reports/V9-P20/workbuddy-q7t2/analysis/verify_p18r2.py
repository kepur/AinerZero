"""P20 non-author read-only audit of ainerzero.V9.P18 r2.

Pure Python; no s1 import, no MLX, no model, no writes outside
reports/V9-P20/analysis/verification.json.  It recomputes the k coverage
independently from the frozen development truth sidecar, recomputes the
frozen budget arithmetic, and records the source-level facts that P18 r2's
claims depend on (300/350/120, phase guard location, generation_seconds
timeline, script output paths, hand-typed constants, B2 digest binding).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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
P18R2 = P18R1 / "r2"
P19 = REPO / "reports/V9-P19"
OUT = REPO / "reports/V9-P20/workbuddy-q7t2/analysis/verification.json"
K_VALUES = (0, 1, 2, 4, 8)
QUERY_LIMIT = 8


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_cells(row: dict) -> list[tuple[int, int]]:
    poses = [
        (float(s["agent_world_pose"]["position"][0]), float(s["agent_world_pose"]["position"][2]))
        for s in row["steps"]
    ]
    if not poses:
        return []
    ox, oz = int(round(poses[0][0])), int(round(poses[0][1]))
    return [(int(round(x)) - ox, int(round(z)) - oz) for x, z in poses]


def free_edges(row: dict, cells: list[tuple[int, int]]) -> set:
    pos = row["steps"][0]["agent_world_pose"]["position"]
    ox, oz = int(round(float(pos[0]))), int(round(float(pos[2])))
    world = row.get("world") or {}
    width, height = int(world["width"]), int(world["height"])
    blocked = {(int(x), int(z)) for x, z in world.get("blocked", [])}
    visited = set(cells)
    edges = set()
    for x, z in visited:
        for nx, nz in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if (nx, nz) not in visited:
                continue
            ax, az = x + ox, z + oz
            bx, bz = nx + ox, nz + oz
            if not (0 <= bx < width and 0 <= bz < height):
                continue
            if (ax, az) in blocked or (bx, bz) in blocked:
                continue
            edges.add(tuple(sorted(((x, z), (nx, nz)))))
    return edges


def split(n_transitions: int, k: int):
    total = int(n_transitions)
    support = min(max(int(k), 0), total)
    if support < int(k) or total - support < 1:
        return [], []
    return list(range(support)), list(range(support, min(total, support + QUERY_LIMIT)))


def main() -> int:
    result = {}

    # ---- 1. sealed-input SHA audit (before) ----
    sealed = json.loads(
        (Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-morning")
         / "P18-r2-review-inputs.json").read_text()
    )
    sha_rows = []
    for entry in sealed["files"]:
        path = Path(entry["path"])
        actual = sha(path) if path.is_file() else None
        sha_rows.append({"path": str(path), "expected": entry["sha256"], "actual": actual,
                         "match": actual == entry["sha256"]})
    r1_frozen = json.loads((CYCLE / "P18-frozen-review-inputs.json").read_text())
    r1_rows = []
    for entry in r1_frozen["files"]:
        path = Path(entry["path"])
        actual = sha(path) if path.is_file() else None
        r1_rows.append({"path": str(path), "match": actual == entry["sha256"]})
    result["sha_audit"] = {
        "sealed_inputs_total": len(sha_rows),
        "sealed_inputs_all_match": all(r["match"] for r in sha_rows),
        "r1_frozen_total": len(r1_rows),
        "r1_frozen_all_match": all(r["match"] for r in r1_rows),
    }

    # ---- 2. independent k coverage from frozen truth ----
    rows = []
    with (DATASET / "truth/development.jsonl").open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    fam = defaultdict(lambda: {"worlds": 0, "steps": Counter(), "transitions": 0,
                               "distinct_cells": 0, "stay": 0, "adjacent": 0, "non_adjacent": 0})
    for row in rows:
        cells = rel_cells(row)
        slot = fam[row.get("family") or "unknown"]
        slot["worlds"] += 1
        slot["steps"][len(row["steps"])] += 1
        slot["transitions"] += max(len(row["steps"]) - 1, 0)
        slot["distinct_cells"] += len(set(cells))
        for a, b in zip(cells, cells[1:]):
            if a == b:
                slot["stay"] += 1
            elif abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:
                slot["adjacent"] += 1
            else:
                slot["non_adjacent"] += 1

    per_k = {}
    for k in K_VALUES:
        worlds = queries = reachable = 0
        by_family = {}
        for row in rows:
            cells = rel_cells(row)
            edges = free_edges(row, cells)
            support, query = split(max(len(row["steps"]) - 1, 0), k)
            if not query:
                continue
            worlds += 1
            family = row.get("family") or "unknown"
            slot = by_family.setdefault(family, {"worlds": 0, "queries": 0, "true_edges": 0})
            slot["worlds"] += 1
            support_cells = set(cells[: len(support) + 1]) if support else set()
            for index in query:
                queries += 1
                slot["queries"] += 1
                edge = tuple(sorted((cells[index], cells[index + 1])))
                if edge in edges:
                    slot["true_edges"] += 1
                if cells[index + 1] in support_cells:
                    reachable += 1
        true_edges = sum(s["true_edges"] for s in by_family.values())
        per_k[str(k)] = {
            "worlds": worlds,
            "queries": queries,
            "true_edges": true_edges,
            "constant_true_accuracy": round(true_edges / queries, 6) if queries else None,
            "reachable": reachable,
            "by_family": dict(sorted(by_family.items())),
        }
    result["independent_k_coverage"] = per_k
    result["family_summary"] = {
        name: {"worlds": s["worlds"], "steps": dict(sorted(s["steps"].items())),
               "transitions": s["transitions"], "distinct_cells": s["distinct_cells"],
               "stay": s["stay"], "adjacent": s["adjacent"], "non_adjacent": s["non_adjacent"]}
        for name, s in sorted(fam.items())
    }

    r2_truth = json.loads((P18R2 / "analysis/independent_truth_check.json").read_text())
    p19_metrics = json.loads((P19 / "metrics.json").read_text())
    p19_checks = json.loads((P19 / "analysis/independent_checks.json").read_text())
    result["k_coverage_cross_check"] = {
        "matches_r2_truth_check": all(
            per_k[k]["worlds"] == r2_truth["k_coverage"][k]["worlds"]
            and per_k[k]["queries"] == r2_truth["k_coverage"][k]["queries"]
            for k in per_k
        ),
        "matches_p19_reproduced": all(
            per_k[k]["worlds"] == p19_metrics["k_coverage_reproduced"][k]["worlds"]
            and per_k[k]["queries"] == p19_metrics["k_coverage_reproduced"][k]["queries"]
            for k in per_k
        ),
    }

    # ---- 3. frozen budget arithmetic ----
    doc = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
    proto = doc["training_protocol"]
    timing = doc["timing"]
    budget = doc["budget_estimate"]
    spec_src = (SNAP / "src/ainerzero/v9/experiments/s1/spec.py").read_text()
    overhead = float(re.search(r'"estimate_eval_overhead_factor":\s*([0-9.]+)', spec_src).group(1))
    updates = int(proto["updates"])
    step = float(budget["measured_forward_loss_step_seconds"])
    d_step = float(budget["arm1_step_seconds"])
    duty = float(doc["resource_limits"]["training_duty_cycle"])
    update_cost = 3.0 * step
    eval_cost = int(proto["eval_batches"]) * step * len(proto["checkpoint_fractions"])
    raw_updates = int((360.0 * duty / overhead - eval_cost) // update_cost)
    estimate = (updates * update_cost + eval_cost) / duty * overhead
    deadline = int(-(-estimate * 1.25 // 1))
    arm1_active = int(proto["eval_batches"]) * d_step * len(proto["checkpoint_fractions"])
    arm1_estimate = (arm1_active / duty) * overhead
    arm1_deadline = int(-(-arm1_estimate * 1.25 // 1))
    phase_wall = 9 * deadline + arm1_deadline + float(timing["smoke"]["data_generation_seconds"])
    phase_cap = float(timing["phase_wall_max_seconds"])
    result["budget_recompute"] = {
        "raw_updates": raw_updates,
        "estimate_seconds": estimate,
        "deadline_seconds": deadline,
        "arm1_estimate_seconds": arm1_estimate,
        "arm1_deadline_seconds": arm1_deadline,
        "phase_wall_seconds": phase_wall,
        "phase_cap_seconds": phase_cap,
        "headroom_seconds": phase_cap - phase_wall,
        "matches_frozen": {
            "updates": raw_updates == updates,
            "estimate": estimate == float(budget["estimate_seconds"]),
            "deadline": deadline == int(budget["deadline_seconds"]),
            "arm1": arm1_estimate == float(budget["arm1_estimate_seconds"]),
            "arm1_deadline": arm1_deadline == int(budget["arm1_deadline_seconds"]),
            "phase_wall": phase_wall == float(budget["phase_wall_seconds"]),
            "headroom": (phase_cap - phase_wall) == float(budget["phase_wall_headroom_seconds"]),
        },
    }

    # ---- 4. component arithmetic from measured counts ----
    k_worlds = {k: per_k[str(k)]["worlds"] for k in K_VALUES}
    k_queries = {k: per_k[str(k)]["queries"] for k in K_VALUES}
    few_step = sum(k_worlds[k] for k in (1, 2, 4, 8))
    few_trans = sum(k_worlds[k] * k for k in (1, 2, 4))
    few_probe = sum(k_worlds.values())
    few_encode = 2 * sum(k_queries.values())
    comp = {
        "step_sequence_total": 200 + few_step + 11,
        "single_step_total": 750 + few_trans + 42,
        "probe_graph_total": 200 + few_probe,
        "encode_total": few_encode,
        "few_shot_step_sequence": few_step,
        "few_shot_transitions": few_trans,
        "few_shot_probe_graph": few_probe,
        "few_shot_encode": few_encode,
        "window_batches": 5 * ((550 + 15) // 16),
        "window_frame_slots": 5 * 550 * 3,
    }
    repaired = p19_checks["C_repaired_accounting_measured"]["per_run_total"]
    comp["matches_p19_measured"] = {
        "step_sequence": comp["step_sequence_total"] == int(repaired["step_sequence_calls"]),
        "single_step": comp["single_step_total"] == int(repaired["single_step_forward_calls"]),
        "probe_graph": comp["probe_graph_total"] == int(repaired["probe_graph_calls"]),
        "encode": comp["encode_total"] == int(repaired["encode_calls"]),
        "window_batches": comp["window_batches"] == int(repaired["forward_loss_calls"]),
        "window_frame_slots": comp["window_frame_slots"] == int(repaired["forward_loss_frames"]),
    }
    comp["p19_measured"] = {
        "step_sequence_calls": int(repaired["step_sequence_calls"]),
        "single_step_forwards": int(repaired["single_step_forward_calls"]),
        "probe_graph_calls": int(repaired["probe_graph_calls"]),
        "encode_calls": int(repaired["encode_calls"]),
        "forward_loss_calls": int(repaired["forward_loss_calls"]),
        "forward_loss_frames": int(repaired["forward_loss_frames"]),
    }
    result["component_arithmetic"] = comp

    # ---- 5. source-level facts for the 300/350/120 claim ----
    commands_src = (SNAP / "src/ainerzero/v9/experiments/s1/commands.py").read_text()
    worker_src = (SNAP / "src/ainerzero/v9/experiments/s1/worker.py").read_text()
    prep_line = next((i + 1, l.strip()) for i, l in enumerate(commands_src.splitlines())
                     if "PREP_BUDGET" in l and "eval" in l)
    sup_line = next((i + 1, l.strip()) for i, l in enumerate(spec_src.splitlines())
                    if "supervision_extra_seconds" in l)
    supervisor_line = next((i + 1, l.strip()) for i, l in enumerate(commands_src.splitlines())
                           if "supervision_seconds = budget + spec.TIMING" in l)
    reserve_line = next((i + 1, l.strip()) for i, l in enumerate(worker_src.splitlines())
                        if "ledger.reserve(active_run" in l)
    eval_phase_guard = "phase_budget_exceeded" in worker_src.split('if mode == "eval":', 1)[-1]
    result["eval_wall_sources"] = {
        "PREP_BUDGET_line": prep_line,
        "supervision_extra_seconds_line": sup_line,
        "supervisor_timeout_line": supervisor_line,
        "ledger_reserve_line": reserve_line,
        "eval_branch_has_phase_guard": eval_phase_guard,
        "nominal_budget_seconds": 300.0,
        "supervision_timeout_seconds": 300.0 + float(
            re.search(r'"supervision_extra_seconds":\s*([0-9.]+)', spec_src).group(1)
        ),
        "ledger_reserve_seconds": min(120.0, max(10.0, 0.5 * 300.0)),
        "phase_wall_plus_9x_supervision": phase_wall + 9 * (300.0 + 50.0),
    }

    # ---- 6. generation_seconds timeline ----
    manifest = json.loads((DATASET / "dataset_manifest.json").read_text())
    result["generation_seconds"] = {
        "manifest_value": manifest.get("generation_seconds"),
        "manifest_created_unix": manifest.get("created_unix"),
        "prereg_created_unix": doc.get("created_unix"),
        "data_identity_generation_seconds": doc["data_identity"].get("generation_seconds"),
        "timing_smoke_data_generation_seconds": timing["smoke"].get("data_generation_seconds"),
        "timing_smoke_created_unix": timing["smoke"].get("created_unix"),
        "manifest_value_equals_data_identity": manifest.get("generation_seconds")
        == doc["data_identity"].get("generation_seconds"),
        "manifest_created_before_prereg": float(manifest.get("created_unix", 0))
        < float(doc.get("created_unix", 0)),
    }

    # ---- 7. script output paths / hand-typed constants / B2 binding ----
    build_src = (P18R2 / "analysis/build_r2_metrics.py").read_text()
    truth_src = (P18R2 / "analysis/independent_truth_check.py").read_text()
    result["script_static_facts"] = {
        "build_r2_metrics_reads_V9P18R2_OUT": "V9P18R2_OUT" in build_src,
        "build_r2_metrics_OUT_line": next(l.strip() for l in build_src.splitlines()
                                         if l.strip().startswith("OUT = Path")),
        "independent_truth_check_reads_V9P18R2_OUT": "V9P18R2_OUT" in truth_src,
        "m2_literals_in_build_script": {
            "line_258": "200 + few_shot_step_sequence + 11" in build_src,
            "line_262": "750 + few_shot_transitions + 42" in build_src,
            "line_329_330_hardcoded": '"step_sequence_calls": 11' in build_src
            and '"single_step_forwards": 42' in build_src,
        },
        "few_shot_repaired_stop_frames_literal_1100": '"few_shot_repaired_stop_frames": 1100' in build_src,
        "topology_literals_200_750": "200 + few_shot_step_sequence" in build_src
        and "750 + few_shot_transitions" in build_src,
    }
    r2_metrics = json.loads((P18R2 / "metrics.json").read_text())
    b2 = next(item for item in r2_metrics["option_B"]["items"] if item["id"] == "B2")
    result["b2_binding"] = {
        "b2": b2,
        "b2_mentions_dataset_digest": "digest" in json.dumps(b2, ensure_ascii=False).lower(),
        "b2_mentions_current_dataset": "8234f2f3" in json.dumps(b2, ensure_ascii=False),
    }

    # ---- 8. exact locations of the r1 1292 text ----
    r1_metrics_text = (P18R1 / "metrics.json").read_text().splitlines()
    r1_build_text = (P18R1 / "analysis/build_metrics.py").read_text().splitlines()
    result["r1_1292_locations"] = {
        "r1_metrics_json_lines": [i + 1 for i, l in enumerate(r1_metrics_text) if "1292" in l],
        "r1_build_metrics_lines": [i + 1 for i, l in enumerate(r1_build_text) if "1292" in l],
        "r2_report_lines_claiming_metrics_ok": [
            i + 1 for i, l in enumerate((P18R2 / "REPORT.md").read_text().splitlines())
            if "metrics.json 早已存的是 611/1492/800" in l
        ],
        "r2_report_lines_300_hard_wall": [
            i + 1 for i, l in enumerate((P18R2 / "REPORT.md").read_text().splitlines())
            if "300 s" in l and ("硬" in l or "hard" in l)
        ],
        "r2_metrics_300_hard_wall_paths": [],
    }
    for path, value in [
        ("phase.eval_wall_nominal_per_invocation_seconds", r2_metrics["phase"].get("eval_wall_nominal_per_invocation_seconds")),
    ]:
        result["r1_1292_locations"]["r2_metrics_300_hard_wall_paths"].append({path: value})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in (
        "sha_audit", "k_coverage_cross_check", "budget_recompute",
        "eval_wall_sources", "generation_seconds", "script_static_facts", "b2_binding")},
        indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
