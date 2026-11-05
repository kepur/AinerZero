"""S1 phase-1 final-partition analysis addendum (ainerzero.V9.P61): read-only, P57 method.

Inputs : ../final-eval-stdout.json (the one final-eval report; SHA recorded, checked against
         ../SHA256SUMS.txt), the final frozen preregistration (metric directions) and the accepted
         development analysis reports/V9-S1-phase1-analysis/analysis.json (side by side only).
Outputs: analysis-final.json and tables-final.md next to this file.  Nothing else is written.

Same rules as P57: no statistical test and no gate were preregistered, so arms are ranked by the
three-seed mean in the registered direction and "disjoint" means the three-seed min-max ranges do
not overlap -- descriptive only, no significance claim, no capability promotion.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REPORT = HERE.parent / "final-eval-stdout.json"
SUMS = HERE.parent / "SHA256SUMS.txt"
PREREG = REPO / "artifacts/v9/s1/phase1/final/pre_registration.json"
DEV = REPO / "reports/V9-S1-phase1-analysis/analysis.json"
ARMS = ("arm2", "arm3", "arm4")
SEEDS = (0, 1, 2)
FAMILIES = ("e3_identity", "navigation", "relation", "time")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def listed_sha(name: str) -> str | None:
    for line in SUMS.read_text().splitlines():
        digest, listed = line.split(maxsplit=1)
        if listed.strip() == name:
            return digest
    return None


def get(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def summary(values):
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    if len(vals) != len(values) or not vals:
        return {"n": len(vals), "values": values, "mean": None, "min": None, "max": None}
    return {"n": len(vals), "values": vals, "mean": statistics.fmean(vals), "min": min(vals), "max": max(vals)}


# identical to P57's SCALARS (metric id, path inside a cell, label)
SCALARS = [
    ("localization_error", ("localization_error", "localization_error", "translation_mean_m"), "translation error, mean (m)"),
    ("localization_error", ("localization_error", "localization_error", "translation_median_m"), "translation error, median (m)"),
    ("localization_error", ("localization_error", "localization_error", "yaw_mean_deg"), "yaw error, mean (deg)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "prediction_nll_mean"), "next-observation NLL, mean (nats)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "prediction_nll_median"), "next-observation NLL, median (nats)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "translation_mean_m"), "unseen-map translation error, mean (m)"),
    ("topology_recovery", ("topology_recovery", "f1"), "edge F1 (degenerate, see notes)"),
    ("sample_efficiency", ("sample_efficiency", "nll_curve", "normalised_area"), "NLL curve, normalised area"),
    ("sample_efficiency", ("sample_efficiency", "nll_curve", "last"), "NLL at the final checkpoint"),
    ("sample_efficiency", ("sample_efficiency", "localization_curve", "normalised_area"), "localization curve, normalised area"),
    ("m2_memory_interference", ("m2_memory_interference", "worst_retention_delta"), "worst retention delta"),
]


def rank(per_arm: dict, direction: str):
    means = {a: v["mean"] for a, v in per_arm.items() if v["mean"] is not None}
    order = sorted(means, key=lambda a: means[a], reverse=direction == "higher_is_better")
    disjoint = {}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            disjoint[f"{a}_vs_{b}"] = bool(per_arm[a]["max"] < per_arm[b]["min"] or per_arm[b]["max"] < per_arm[a]["min"])
    constant = len({round(v, 12) for arm in ARMS for v in per_arm[arm]["values"] if isinstance(v, float)}) == 1
    if constant:
        return ["tie (identical in every cell; no ranking)"], {}, True
    return order, disjoint, False


def main() -> int:
    report_sha = sha256(REPORT)
    if listed_sha(REPORT.name) != report_sha:
        raise SystemExit(f"{REPORT.name} SHA {report_sha} does not match SHA256SUMS.txt")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if report.get("status") != "completed" or report.get("mode") != "final-eval":
        raise SystemExit("not a completed final-eval report")
    top = report["details"]
    cells = top["cells"]
    if top.get("error_cells") or top.get("completed_cells") != 10:
        raise SystemExit(f"final-eval cells incomplete: {top.get('error_cells')}")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    directions = {m["id"]: m["direction"] for m in prereg["metrics"]}
    dev = json.loads(DEV.read_text(encoding="utf-8"))
    dev_rows = {(r["label"].replace("development ", ""), tuple(r["path"])): r for r in dev["scalars"]}
    details = {(arm, s): cells[f"{arm}-seed{s}"] for arm in ARMS for s in SEEDS}
    for (arm, s), d in details.items():
        if d.get("partition") != "final" or d.get("status") != "completed":
            raise SystemExit(f"{arm}-seed{s} is not a completed final-partition cell")

    inventory = [{"arm": arm, "seed": s, "status": d.get("status"), "partition": d.get("partition"),
                  "run_id": get(d, "run_binding", "run_id"),
                  "source_experiment": get(d, "run_binding", "inherited", "source_experiment_id"),
                  "params_sha256": get(d, "run_binding", "final_checkpoint_sha256")}
                 for (arm, s), d in sorted(details.items())]

    scalars = []
    for metric, path, label in SCALARS:
        per_arm = {arm: summary([get(details[(arm, s)], *path) for s in SEEDS]) for arm in ARMS}
        order, disjoint, constant = rank(per_arm, directions[metric])
        d = dev_rows.get((label, path))
        scalars.append({
            "metric": metric, "label": label, "path": list(path), "direction": directions[metric],
            "per_arm": per_arm, "rank_by_mean": order, "seed_ranges_disjoint": disjoint,
            "constant_across_all_cells": constant,
            "development": None if d is None else {
                "per_arm_mean": {a: d["per_arm"][a]["mean"] for a in ARMS}, "rank_by_mean": d["rank_by_mean"],
                "disjoint_pairs": sorted(k for k, v in d["seed_ranges_disjoint"].items() if v)},
            "rank_same_as_development": None if d is None else order == d["rank_by_mean"],
        })

    by_family = {fam: {key: {arm: summary([get(details[(arm, s)], "unseen_map_generalization", "by_family", fam, key)
                                           for s in SEEDS]) for arm in ARMS}
                       for key in ("prediction_nll_mean", "translation_mean_m")} for fam in FAMILIES}

    few_shot = {}
    for k in ("0", "1", "2", "4", "8"):
        few_shot[k] = {}
        for arm in ARMS:
            rows = [get(details[(arm, s)], "few_shot_unseen_transition", "curve", k) or {} for s in SEEDS]
            few_shot[k][arm] = {"worlds": [r.get("worlds") for r in rows],
                                "accuracy": summary([r.get("accuracy") for r in rows]),
                                "balanced_accuracy": summary([r.get("balanced_accuracy") for r in rows]),
                                "displacement_mae_m": summary([r.get("displacement_mae_m") for r in rows])}
        unavailable = get(details[("arm2", 0)], "few_shot_unseen_transition", "unavailable", k)
        if unavailable:
            few_shot[k]["unavailable"] = unavailable

    arm1 = cells["arm1"]
    dev_arm1 = dev.get("arm1_d_candidate") or {}
    analysis = {
        "task": "ainerzero.V9.P61 (final-partition addendum, P57 method)",
        "input": {"path": str(REPORT.relative_to(REPO)), "sha256": report_sha, "run_id": report.get("run_id"),
                  "sealed_dataset_digest": top.get("sealed_dataset_digest"), "call_plan": top.get("call_plan")},
        "preregistration": {"path": str(PREREG.relative_to(REPO)), "file_sha256": sha256(PREREG)},
        "development_reference": {"path": str(DEV.relative_to(REPO)), "sha256": sha256(DEV)},
        "scope": "final partition, read once; ranks by seed mean, 'disjoint' = three-seed min-max ranges do not "
                 "overlap (descriptive only); no statistical test or gate was preregistered; no capability promotion",
        "inventory": inventory,
        "scalars": scalars,
        "unseen_map_by_family": by_family,
        "few_shot_pooled_over_families": few_shot,
        "few_shot_reporting_gap": "as in P57: the registered output pools few-shot curves over families",
        "arm1_d_candidate": {"status": arm1.get("status"), "incomparable": arm1.get("incomparable"),
                             "c0_metrics": arm1.get("d_candidate_c0_metrics"),
                             "c0_metrics_equal_to_development": arm1.get("d_candidate_c0_metrics") == dev_arm1.get("c0_metrics")},
    }
    (HERE / "analysis-final.json").write_text(json.dumps(analysis, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def fmt(x, nd=4):
        return "—" if x is None else (f"{x:.{nd}g}" if abs(x) < 1e-3 and x != 0 else f"{x:.{nd}f}")

    lines = ["| 指标 | 方向 | arm2 均值 [min, max] | arm3 均值 [min, max] | arm4 均值 [min, max] | final 按均值排序 | 范围不重叠的对 | dev 排序 | 与 dev 同序 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in scalars:
        cells_txt = [f"{fmt(row['per_arm'][a]['mean'])} [{fmt(row['per_arm'][a]['min'])}, {fmt(row['per_arm'][a]['max'])}]" for a in ARMS]
        dis = ", ".join(k for k, v in row["seed_ranges_disjoint"].items() if v) or "无"
        flag = "（全格相同）" if row["constant_across_all_cells"] else ""
        dev_rank = " > ".join(row["development"]["rank_by_mean"]) if row["development"] else "—"
        same = {True: "是", False: "否", None: "—"}[row["rank_same_as_development"]]
        lines.append(f"| {row['label']}{flag} | {row['direction']} | " + " | ".join(cells_txt)
                     + f" | {' > '.join(row['rank_by_mean'])} | {dis} | {dev_rank} | {same} |")
    lines += ["", "| 族 | NLL arm2 | NLL arm3 | NLL arm4 | 平移 arm2 (m) | 平移 arm3 | 平移 arm4 |", "|---|---|---|---|---|---|---|"]
    for fam, v in by_family.items():
        lines.append(f"| {fam} | " + " | ".join([fmt(v["prediction_nll_mean"][a]["mean"]) for a in ARMS]
                                                + [fmt(v["translation_mean_m"][a]["mean"]) for a in ARMS]) + " |")
    lines += ["", "| k | worlds (arm2 s0) | arm2 acc / bal | arm3 acc / bal | arm4 acc / bal |", "|---|---|---|---|---|"]
    for k, v in few_shot.items():
        if "unavailable" in v:
            lines.append(f"| {k} | 0 | insufficient_data | insufficient_data | insufficient_data |")
            continue
        lines.append(f"| {k} | {v['arm2']['worlds'][0]} | " + " | ".join(
            f"{fmt(v[a]['accuracy']['mean'])} / {fmt(v[a]['balanced_accuracy']['mean'])}" for a in ARMS) + " |")
    (HERE / "tables-final.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("arm1 C0 equal to development:", analysis["arm1_d_candidate"]["c0_metrics_equal_to_development"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
