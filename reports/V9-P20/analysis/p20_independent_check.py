"""ainerzero.V9.P20 independent re-verification of P18 r2 (non-author reviewer).

Read-only on every frozen input; the only writes are under reports/V9-P20/.
Imports no MLX (asserted). No model, no training, no real eval, no new data.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SNAP = Path("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot")
CYCLE = SNAP.parent
DATASET = REPO / "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
OUT = REPO / "reports/V9-P20"
ISO = OUT / "analysis" / "iso"

results = {}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_iso() -> Path:
    if ISO.exists():
        shutil.rmtree(ISO)
    pkg = ISO / "ainerzero"
    (pkg / "v9" / "experiments").mkdir(parents=True)
    for p in (pkg / "__init__.py", pkg / "v9" / "__init__.py", pkg / "v9" / "experiments" / "__init__.py"):
        p.write_text("")
    shutil.copytree(SNAP / "src/ainerzero/v9/experiments/s1", pkg / "v9" / "experiments" / "s1",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(REPO / "src/ainerzero/v9/interfaces", pkg / "v9" / "interfaces",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return ISO


def close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


# ---------------------------------------------------------------- iso build
iso = build_iso()
fidelity = {}
for rel in ("evaluation.py", "runtime.py", "metrics.py", "spec.py", "data.py", "worker.py", "commands.py", "prereg.py"):
    a = sha256_file(SNAP / "src/ainerzero/v9/experiments/s1" / rel)
    b = sha256_file(iso / "ainerzero/v9/experiments/s1" / rel)
    fidelity[rel] = {"snapshot": a, "iso_copy": b, "identical": a == b}
results["iso_copy_fidelity_all_identical"] = all(v["identical"] for v in fidelity.values())

sys.path.insert(0, str(iso))
from ainerzero.v9.experiments.s1 import data as s1_data          # noqa: E402
from ainerzero.v9.experiments.s1 import metrics as s1_metrics    # noqa: E402
from ainerzero.v9.experiments.s1 import spec as s1_spec          # noqa: E402

results["mlx_imported"] = "mlx" in sys.modules

# ------------------------------------------------- A. k coverage (production functions)
truth = s1_data.load_truth_view(DATASET, "development")
K_VALUES = (0, 1, 2, 4, 8)
k_cov = {}
def step_cells(ep):
    out = []
    for st in ep.steps:
        pos = st["agent_world_pose"]["position"]
        out.append((int(round(float(pos[0]))), int(round(float(pos[2])))))
    return out


for k in K_VALUES:
    worlds = queries = reachable = 0
    for ep in truth:
        support, query = s1_metrics.split_support_query(len(ep.steps) - 1, k)
        if not query:
            continue
        worlds += 1
        cells = step_cells(ep)
        support_cells = set(cells[: len(support) + 1]) if support else set()
        for idx in query:
            queries += 1
            if idx + 1 < len(cells) and cells[idx + 1] in support_cells:
                reachable += 1
    k_cov[str(k)] = {"worlds": worlds, "queries": queries, "reachable_in_support_memory": reachable}
results["k_coverage_production_functions"] = k_cov

# family stats from production truth helpers
fam = {}
for ep in truth:
    name = ep.family
    slot = fam.setdefault(name, {"worlds": 0, "steps": {}, "transitions": 0, "stay": 0, "adjacent": 0, "non_adjacent": 0})
    cells = step_cells(ep)
    slot["worlds"] += 1
    n = len(ep.steps)
    slot["steps"][str(n)] = slot["steps"].get(str(n), 0) + 1
    slot["transitions"] += n - 1
    for a, b in zip(cells, cells[1:]):
        if a == b:
            slot["stay"] += 1
        elif abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:
            slot["adjacent"] += 1
        else:
            slot["non_adjacent"] += 1
results["family_stats_production_functions"] = fam

# ------------------------------------------------- B. 550 windows / 175 batches
windows = s1_data.load_development_windows(DATASET)
n_win = len(windows["windows"])
batches = (n_win + 15) // 16
results["development_windows"] = {"windows": n_win, "batch_size": 16, "batches": batches,
                                  "window_batches_per_eval_run": 5 * batches}

# ------------------------------------------------- C. component arithmetic vs P19 measured
kw = {k: k_cov[str(k)]["worlds"] for k in K_VALUES}
kq = {k: k_cov[str(k)]["queries"] for k in K_VALUES}
few_shot_ss = sum(kw[k] for k in (1, 2, 4, 8))
few_shot_fwd = sum(kw[k] * k for k in (1, 2, 4))
few_shot_pg = sum(kw.values())
few_shot_enc = 2 * sum(kq.values())
arith = {
    "repaired_step_sequence_total": 200 + few_shot_ss + 11,
    "repaired_single_step_forwards_total": 750 + few_shot_fwd + 42,
    "repaired_probe_graph_total": 200 + few_shot_pg,
    "repaired_encode_total": few_shot_enc,
    "window_batches": 5 * batches,
    "as_coded_stop_frames": 950 + 0 + 53,
    "repaired_few_shot_stop_frames": sum(kw[k] * (k + 1) for k in (1, 2, 4)),
    "repaired_stop_frames_total": 950 + sum(kw[k] * (k + 1) for k in (1, 2, 4)) + 53,
    "as_coded_transitions_total": 792,
    "repaired_transitions_total": 750 + few_shot_fwd + 42,
    "hybrid_1703": 950 + 700 + 53,
    "hybrid_1503": 750 + 700 + 53,
    "hybrid_1903": sum(kw[k] * (k + 1) for k in (1, 2, 4)) + 750 + 53,
}
results["component_arithmetic_p20"] = arith

p19_checks = json.loads((REPO / "reports/V9-P19/analysis/independent_checks.json").read_text())
p19_rep = p19_checks["C_repaired_accounting_measured"]["per_run_total"]
p19_asc = p19_checks["B_as_coded_accounting_measured"]["per_run_total"]
results["p19_measured_repaired"] = {k: p19_rep[k] for k in
                                    ("step_sequence_calls", "single_step_forward_calls", "probe_graph_calls",
                                     "encode_calls", "forward_loss_calls", "step_sequence_frames", "step_sequence_transitions")}
results["p19_measured_as_coded"] = {k: p19_asc[k] for k in
                                   ("step_sequence_calls", "single_step_forward_calls", "probe_graph_calls",
                                    "encode_calls", "forward_loss_calls", "step_sequence_frames", "step_sequence_transitions")}
results["arithmetic_matches_p19_measurement"] = {
    "step_sequence": arith["repaired_step_sequence_total"] == p19_rep["step_sequence_calls"],
    "single_step_forwards": arith["repaired_single_step_forwards_total"] == p19_rep["single_step_forward_calls"],
    "probe_graph": arith["repaired_probe_graph_total"] == p19_rep["probe_graph_calls"],
    "encode": arith["repaired_encode_total"] == p19_rep["encode_calls"],
    "window_batches": arith["window_batches"] == p19_rep["forward_loss_calls"],
    "repaired_stop_frames": arith["repaired_stop_frames_total"] == p19_rep["step_sequence_frames"],
    "repaired_transitions": arith["repaired_transitions_total"] == p19_rep["step_sequence_transitions"],
    "as_coded_stop_frames": arith["as_coded_stop_frames"] == p19_asc["step_sequence_frames"],
    "as_coded_transitions": arith["as_coded_transitions_total"] == p19_asc["step_sequence_transitions"],
}
# P19 C per_k_calls staleness: repaired tree should execute k transitions per world
c_per_k = p19_checks["C_repaired_accounting_measured"]["per_k_calls"]
results["p19_C_per_k_calls_staleness"] = {
    "k2_transitions_reported": c_per_k["2"]["calls"].get("step_sequence_transitions"),
    "k2_transitions_expected_repaired": 150 * 2,
    "k4_transitions_reported": c_per_k["4"]["calls"].get("step_sequence_transitions"),
    "k4_transitions_expected_repaired": 50 * 4,
    "k1_error_reported": c_per_k["1"].get("error"),
    "note": "C per_k_calls appears copied from the as-coded (B) block; it contradicts C's own per_run_total (611/1492). The per_run_total and component_split are the consistent carriers and match r2's cited numbers.",
}

# ------------------------------------------------- D. budget arithmetic from frozen prereg
doc = json.loads((SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json").read_text())
protocol, timing, budget = doc["training_protocol"], doc["timing"], doc["budget_estimate"]
duty = float(doc["resource_limits"]["training_duty_cycle"])
step = float(budget["measured_forward_loss_step_seconds"])
d_step = float(budget["arm1_step_seconds"])
overhead = float(s1_spec.TIMING["estimate_eval_overhead_factor"])
eval_batches = int(protocol["eval_batches"])
update_cost = 3.0 * step
eval_cost = eval_batches * step * len(protocol["checkpoint_fractions"])
raw_updates = int((360.0 * duty / overhead - eval_cost) // update_cost)
estimate = (raw_updates * update_cost + eval_cost) / duty * overhead
deadline = -(-int(estimate * 1.25 * 1000) // 1000)
import math
deadline = math.ceil(estimate * 1.25)
arm1_active = eval_batches * d_step * len(protocol["checkpoint_fractions"])
arm1_est = (arm1_active / duty) * overhead
arm1_deadline = math.ceil(arm1_est * 1.25)
phase_wall = 9 * deadline + 1 * arm1_deadline + float(timing["smoke"]["data_generation_seconds"])
phase_cap = float(timing["phase_wall_max_seconds"])
budget_recomputed = {
    "raw_updates": raw_updates, "update_cost": update_cost, "eval_cost": eval_cost,
    "estimate": estimate, "deadline": deadline, "arm1_estimate": arm1_est,
    "arm1_deadline": arm1_deadline, "phase_wall": phase_wall, "headroom": phase_cap - phase_wall,
}
budget_frozen = {
    "updates": int(protocol["updates"]), "estimate": float(budget["estimate_seconds"]),
    "deadline": int(budget["deadline_seconds"]), "arm1_estimate": float(budget["arm1_estimate_seconds"]),
    "arm1_deadline": int(budget["arm1_deadline_seconds"]), "phase_wall": float(budget["phase_wall_seconds"]),
    "headroom": float(budget["phase_wall_headroom_seconds"]),
}
results["budget_recompute_p20"] = {
    "recomputed": budget_recomputed, "frozen_registered": budget_frozen,
    "matches": {
        "updates": raw_updates == budget_frozen["updates"],
        "estimate": close(estimate, budget_frozen["estimate"]),
        "deadline": deadline == budget_frozen["deadline"],
        "arm1_estimate": close(arm1_est, budget_frozen["arm1_estimate"]),
        "arm1_deadline": arm1_deadline == budget_frozen["arm1_deadline"],
        "phase_wall": close(phase_wall, budget_frozen["phase_wall"]),
        "headroom": close(phase_cap - phase_wall, budget_frozen["headroom"]),
    },
    "supervision_seconds_frozen": float(timing.get("supervision_seconds", float("nan"))),
    "arm1_supervision_seconds_frozen": float(timing.get("arm1_supervision_seconds", float("nan"))),
}

# ------------------------------------------------- E. frozen source-line assertions
S1 = SNAP / "src/ainerzero/v9/experiments/s1"
src = {rel: (S1 / rel).read_text() for rel in
       ("commands.py", "worker.py", "spec.py", "smoke.py", "evaluation.py", "runtime.py", "prereg.py", "metrics.py")}

def has(rel, needle):
    return needle in src[rel]

src_checks = {
    "commands_PREP_BUDGET_eval_300": has("commands.py", 'PREP_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0, "eval": 300.0}'),
    "spec_supervision_extra_50": has("spec.py", '"supervision_extra_seconds": 50.0'),
    "commands_mode_eval_supervision_budget_plus_extra": has("commands.py", "supervision_seconds=budget + spec.TIMING[\"supervision_extra_seconds\"]"),
    "worker_phase_guard_comment": has("worker.py", "including auxiliary eval/verify runs"),
    "worker_eval_reserve_120": has("worker.py", "min(120.0, max(10.0, 0.5 * budget))"),
    "commands_phase_guard_comment": has("commands.py", "Include auxiliary eval/verify reservations"),
    "evaluation_stop_plus_1": has("evaluation.py", "stop=support[-1] + 1"),
    "runtime_frames_guard": has("runtime.py", 'raise BackendError("a sequence probe needs at least two frames")'),
    "smoke_copies_manifest_generation_seconds": has("smoke.py", 'float(manifest.get("generation_seconds") or 0.0)'),
    "prereg_doc_metrics3_few_shot": doc["metrics"][3]["id"] == "few_shot_unseen_transition",
    "prereg_doc_metrics3_accuracy_and_displacement": "accuracy and displacement error" in doc["metrics"][3]["definition"],
    "prereg_doc_metrics3_k_values": doc["metrics"][3]["definition"].count("{0,1,2,4,8}") == 1,
}
# the phase guard must live only in the train path of commands.py
train_span = src["commands.py"]
mode_eval_start = train_span.index("def mode_eval(")
mode_train_start = train_span.index("def mode_train(")
mode_eval_body = train_span[mode_eval_start:]
src_checks["commands_phase_guard_not_in_mode_eval"] = "phase_budget_exceeded" not in mode_eval_body
src_checks["commands_phase_guard_in_mode_train"] = "phase_budget_exceeded" in train_span[mode_train_start:mode_eval_start]
results["frozen_source_assertions"] = src_checks

eval_wall = {
    "nominal_prep_budget_seconds": 300.0,
    "actual_supervisor_timeout_seconds": 300.0 + float(s1_spec.TIMING["supervision_extra_seconds"]),
    "ledger_reserve_seconds": min(120.0, max(10.0, 0.5 * 300.0)),
    "note": "PREP_BUDGET['eval']=300 is the nominal worker budget; the supervisor subprocess timeout is budget+supervision_extra_seconds=350; the ledger reserve is 120. The r2 report labels 300 s as the per-invocation hard wall / subprocess hard timeout.",
}
results["single_eval_wall_three_numbers"] = eval_wall

# ------------------------------------------------- F. r1 error locations (history preservation)
r1_report = (REPO / "reports/V9-P18/REPORT.md").read_text()
r1_metrics = json.loads((REPO / "reports/V9-P18/metrics.json").read_text())
r1_facts = {
    "r1_report_has_612": "612" in r1_report,
    "r1_report_has_1292": "1292" in r1_report,
    "r1_report_has_600_probe_graph_text": "600 次 `probe_graph`" in r1_report or "600 次 probe_graph" in r1_report,
    "r1_metrics_values": r1_metrics["eval_run_accounting_if_k1_repaired"],
    "r1_metrics_unmeasured_text_has_1292": "1292" in json.dumps(r1_metrics["unmeasured"], ensure_ascii=False),
    "r1_metrics_unmeasured_text_has_600": "600" in json.dumps(r1_metrics["unmeasured"], ensure_ascii=False),
}
results["r1_error_locations"] = r1_facts

# ------------------------------------------------- G. F9 byte facts
prereg_copies = {
    "frozen_r5_snapshot": SNAP / "artifacts/v9/s1/phase1/r5/pre_registration.json",
    "repo_r5": REPO / "artifacts/v9/s1/phase1/r5/pre_registration.json",
    "repo_r6": REPO / "artifacts/v9/s1/phase1/r6/pre_registration.json",
    "repo_top": REPO / "artifacts/v9/s1/phase1/pre_registration.json",
}
f9 = {}
for name, path in prereg_copies.items():
    d = json.loads(path.read_text())
    f9[name] = {
        "sha256": sha256_file(path),
        "data_identity_generation_seconds": d.get("data_identity", {}).get("generation_seconds"),
        "timing_smoke_data_generation_seconds": d.get("timing", {}).get("smoke", {}).get("data_generation_seconds"),
        "dataset_digest": d.get("data_identity", {}).get("dataset_digest"),
    }
manifest = json.loads((DATASET / "dataset_manifest.json").read_text())
f9["dataset_manifest"] = {
    "sha256": sha256_file(DATASET / "dataset_manifest.json"),
    "generation_seconds": manifest.get("generation_seconds"),
    "counts": manifest.get("counts"),
}
f9["historical_diff_evidence_found"] = False
f9["search_evidence"] = ("all four pre_registration.json copies carry BOTH values for the same digest; "
                         "the dataset manifest carries only 45.739918708 (matching data_identity); "
                         "no earlier copy with a single value exists in the repo or the coordination snapshots")
results["f9_generation_seconds_byte_facts"] = f9

# ------------------------------------------------- H. r2 metrics.json cross-check
r2 = json.loads((REPO / "reports/V9-P18/r2/metrics.json").read_text())
p19_metrics = json.loads((REPO / "reports/V9-P19/metrics.json").read_text())
rk = r2["call_counts"]["per_arm_seed_eval"]
r2_cross = {
    "as_coded_values_match_p19_B": all(
        rk["as_coded"][key] == p19_asc[p19_key] for key, p19_key in
        (("step_sequence_calls", "step_sequence_calls"), ("single_step_forwards", "single_step_forward_calls"),
         ("probe_graph_calls", "probe_graph_calls"), ("encode_calls", "encode_calls"),
         ("window_forward_loss", "forward_loss_calls"))),
    "repaired_values_match_p19_C": all(
        rk["repaired_k1"][key] == p19_rep[p19_key] for key, p19_key in
        (("step_sequence_calls", "step_sequence_calls"), ("single_step_forwards", "single_step_forward_calls"),
         ("probe_graph_calls", "probe_graph_calls"), ("encode_calls", "encode_calls"),
         ("window_forward_loss", "forward_loss_calls"))),
    "r2_totals_eval": r2["totals"],
    "r2_phase": {k: r2["phase"][k] for k in ("frozen_phase_wall_seconds", "phase_cap_seconds", "headroom_seconds")},
    "r2_arithmetic_matches_measurement": r2["call_counts"]["arithmetic_matches_measurement"],
    "r2_cross_check_vs_p19_matches": r2["diagnostic_baselines"]["cross_check_vs_p19"]["matches"],
    "r2_f_closures_all_closed": all(c["status"] == "closed" for c in r2["f_closures"]),
    "r2_option_B_approval_line_written": r2["option_B"]["approval_line_written"],
    "r2_option_A_is_zero_change": r2["option_A"]["is_zero_change"],
    "r2_p19_k_coverage_reproduced": p19_metrics.get("k_coverage_reproduced"),
    "r2_p20_k_coverage": k_cov,
    "r2_k_coverage_matches_p20": all(
        p19_metrics["k_coverage_reproduced"][k]["worlds"] == k_cov[k]["worlds"]
        and p19_metrics["k_coverage_reproduced"][k]["queries"] == k_cov[k]["queries"] for k in k_cov),
}
results["r2_metrics_cross_check"] = r2_cross

# ------------------------------------------------- I. B2 data-binding check
b2 = [i for i in r2["option_B"]["items"] if i["id"] == "B2"][0]
results["option_B_data_binding"] = {
    "B2_item_text": b2["item"],
    "B2_mentions_dataset_or_data_summary": any(w in b2["item"].lower() for w in ("dataset", "world", "dev", "data")),
    "B1_cost": [i for i in r2["option_B"]["items"] if i["id"] == "B1"][0]["cost"],
    "note": ("B2 registers 611/1492/800/3500 measured on the CURRENT frozen dev set (200 worlds, 750/550/350/100 queries). "
             "A B1 long-episode dataset (>=10 packets, >=9 transitions per world) would change queries and per-world "
             "transitions, so its call counts are unknown until measured. The r2 option B does not state this binding."),
}

# ------------------------------------------------- J. summary + write
summary = {
    "iso_fidelity": results["iso_copy_fidelity_all_identical"],
    "mlx_imported": results["mlx_imported"],
    "k_coverage_p20": k_cov,
    "family_stats": fam,
    "windows": results["development_windows"],
    "component_arithmetic": arith,
    "arithmetic_matches_p19": results["arithmetic_matches_p19_measurement"],
    "budget_matches": results["budget_recompute_p20"]["matches"],
    "source_assertions": src_checks,
    "eval_wall": eval_wall,
    "r1_error_locations": r1_facts,
    "r2_cross": {k: v for k, v in r2_cross.items() if not isinstance(v, (dict, list)) or k in ("r2_totals_eval",)},
}
(OUT / "analysis").mkdir(parents=True, exist_ok=True)
(OUT / "analysis" / "p20_independent_check.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(json.dumps(summary, indent=2, ensure_ascii=False))
print("ALL_OK" if (results["iso_copy_fidelity_all_identical"] and not results["mlx_imported"]
                   and all(results["arithmetic_matches_p19_measurement"].values())
                   and all(results["budget_recompute_p20"]["matches"].values())
                   and all(src_checks.values())) else "CHECK_FAILURES_PRESENT")
