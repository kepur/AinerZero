"""S1 phase-1 formal analysis (ainerzero.V9.P57): four arms, development partition, read-only.

Inputs : reports/V9-S1-r15/eval-details/*.json (verified against its SHA256SUMS.txt) and the
         r15 frozen preregistration (metric definitions/directions, reporting notes).
Outputs: analysis.json and tables.md next to this file.  Nothing else is written.

The preregistration froze six metric definitions and their directions, three reporting notes
and the conclusion scope ("relative merits of the four arms; no capability promotion").  It froze
no statistical test and no gate threshold, so this script ranks arms by the seed mean in the
registered direction and states, descriptively, whether the three-seed ranges of two arms are
disjoint.  Nothing here is a significance claim.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
INPUTS = REPO / "reports/V9-S1-r15/eval-details"
PREREG = REPO / "artifacts/v9/s1/phase1/r15/pre_registration.json"
ARMS = ("arm2", "arm3", "arm4")
SEEDS = (0, 1, 2)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs() -> dict:
    listed = {}
    for line in (INPUTS / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name.strip()] = digest
    actual = {p.name: sha256(p) for p in INPUTS.glob("*.json")}
    if listed != actual:
        raise SystemExit(f"input SHA mismatch: listed={listed} actual={actual}")
    return actual


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


# (metric id from the preregistration, path inside details, label)
SCALARS = [
    ("localization_error", ("localization_error", "localization_error", "translation_mean_m"), "development translation error, mean (m)"),
    ("localization_error", ("localization_error", "localization_error", "translation_median_m"), "development translation error, median (m)"),
    ("localization_error", ("localization_error", "localization_error", "yaw_mean_deg"), "development yaw error, mean (deg)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "prediction_nll_mean"), "next-observation NLL, mean (nats)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "prediction_nll_median"), "next-observation NLL, median (nats)"),
    ("unseen_map_generalization", ("unseen_map_generalization", "translation_mean_m"), "unseen-map translation error, mean (m)"),
    ("topology_recovery", ("topology_recovery", "f1"), "edge F1 (degenerate, see notes)"),
    ("sample_efficiency", ("sample_efficiency", "nll_curve", "normalised_area"), "NLL curve, normalised area"),
    ("sample_efficiency", ("sample_efficiency", "nll_curve", "last"), "NLL at the final checkpoint"),
    ("sample_efficiency", ("sample_efficiency", "localization_curve", "normalised_area"), "localization curve, normalised area"),
    ("m2_memory_interference", ("m2_memory_interference", "worst_retention_delta"), "worst retention delta"),
]


def main() -> int:
    hashes = verify_inputs()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    directions = {m["id"]: m["direction"] for m in prereg["metrics"]}
    details = {}
    for arm in ARMS:
        for seed in SEEDS:
            payload = json.loads((INPUTS / f"eval-{arm}-seed{seed}.json").read_text(encoding="utf-8"))
            details[(arm, seed)] = payload["details"]
    arm1 = json.loads((INPUTS / "eval-arm1.json").read_text(encoding="utf-8"))["details"]

    inventory = []
    for (arm, seed), d in sorted(details.items()):
        rb = d.get("run_binding") or {}
        inventory.append({
            "arm": arm, "seed": seed, "status": d.get("status"), "run_id": rb.get("run_id"),
            "source_experiment": (rb.get("inherited") or {}).get("source_experiment_id") or "s1-phase1-20261028-r15",
            "params_sha256": rb.get("final_checkpoint_sha256"), "incomparable": d.get("incomparable"),
        })

    scalars = []
    for metric, path, label in SCALARS:
        per_arm = {arm: summary([get(details[(arm, s)], *path) for s in SEEDS]) for arm in ARMS}
        direction = directions[metric]
        means = {a: v["mean"] for a, v in per_arm.items() if v["mean"] is not None}
        reverse = direction == "higher_is_better"
        order = sorted(means, key=lambda a: means[a], reverse=reverse)
        disjoint = {}
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                lo_a, hi_a = per_arm[a]["min"], per_arm[a]["max"]
                lo_b, hi_b = per_arm[b]["min"], per_arm[b]["max"]
                disjoint[f"{a}_vs_{b}"] = bool(hi_a < lo_b or hi_b < lo_a)
        constant = len({round(v, 12) for arm in ARMS for v in per_arm[arm]["values"] if isinstance(v, float)}) == 1
        if constant:
            order = ["tie (identical in every cell; no ranking)"]
            disjoint = {}
        scalars.append({"metric": metric, "label": label, "path": list(path), "direction": direction,
                        "per_arm": per_arm, "rank_by_mean": order, "seed_ranges_disjoint": disjoint,
                        "constant_across_all_cells": constant})

    by_family = {}
    for fam in ("e3_identity", "navigation", "relation", "time"):
        by_family[fam] = {}
        for key in ("prediction_nll_mean", "translation_mean_m"):
            by_family[fam][key] = {arm: summary([get(details[(arm, s)], "unseen_map_generalization", "by_family", fam, key) for s in SEEDS]) for arm in ARMS}

    few_shot = {}
    for k in ("0", "1", "2", "4", "8"):
        few_shot[k] = {}
        for arm in ARMS:
            rows = [get(details[(arm, s)], "few_shot_unseen_transition", "curve", k) or {} for s in SEEDS]
            few_shot[k][arm] = {
                "worlds": [r.get("worlds") for r in rows],
                "accuracy": summary([r.get("accuracy") for r in rows]),
                "balanced_accuracy": summary([r.get("balanced_accuracy") for r in rows]),
                "displacement_mae_m": summary([r.get("displacement_mae_m") for r in rows]),
            }
        unavailable = get(details[("arm2", 0)], "few_shot_unseen_transition", "unavailable", k)
        if unavailable:
            few_shot[k]["unavailable"] = unavailable

    analysis = {
        "task": "ainerzero.V9.P57",
        "inputs_sha256": hashes,
        "preregistration": {"path": str(PREREG.relative_to(REPO)), "file_sha256": sha256(PREREG)},
        "scope": "development partition only; final partition not read; no statistical test or gate was "
        "preregistered, so ranks are by seed mean and 'disjoint' means the three-seed min-max ranges do "
        "not overlap (descriptive only); no capability promotion",
        "inventory": inventory,
        "scalars": scalars,
        "unseen_map_by_family": by_family,
        "few_shot_pooled_over_families": few_shot,
        "few_shot_reporting_gap": "the registered eval output stores few-shot curves pooled over families; "
        "the per-family breakdown required by reporting note 2 is not recoverable from it without re-running "
        "evaluation, which this card does not do",
        "arm1_d_candidate": {"incomparable": arm1.get("incomparable"), "status": arm1.get("status"),
                             "c0_metrics": arm1.get("d_candidate_c0_metrics")},
    }
    (HERE / "analysis.json").write_text(json.dumps(analysis, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def fmt(x, nd=4):
        return "—" if x is None else (f"{x:.{nd}g}" if abs(x) < 1e-3 and x != 0 else f"{x:.{nd}f}")

    lines = ["| 指标 | 方向 | arm2 均值 [min, max] | arm3 均值 [min, max] | arm4 均值 [min, max] | 按均值排序 | 范围不重叠的对 |", "|---|---|---|---|---|---|---|"]
    for row in scalars:
        cells = []
        for arm in ARMS:
            v = row["per_arm"][arm]
            cells.append(f"{fmt(v['mean'])} [{fmt(v['min'])}, {fmt(v['max'])}]")
        dis = ", ".join(k for k, v in row["seed_ranges_disjoint"].items() if v) or "无"
        flag = "（全格相同）" if row["constant_across_all_cells"] else ""
        lines.append(f"| {row['label']}{flag} | {row['direction']} | " + " | ".join(cells) + f" | {' > '.join(row['rank_by_mean'])} | {dis} |")
    lines += ["", "| 族 | NLL arm2 | NLL arm3 | NLL arm4 | 平移 arm2 (m) | 平移 arm3 | 平移 arm4 |", "|---|---|---|---|---|---|---|"]
    for fam, v in by_family.items():
        n = [fmt(v["prediction_nll_mean"][a]["mean"]) for a in ARMS]
        t = [fmt(v["translation_mean_m"][a]["mean"]) for a in ARMS]
        lines.append(f"| {fam} | " + " | ".join(n + t) + " |")
    lines += ["", "| k | worlds (arm2 s0) | arm2 acc / bal | arm3 acc / bal | arm4 acc / bal |", "|---|---|---|---|---|"]
    for k, v in few_shot.items():
        if "unavailable" in v:
            lines.append(f"| {k} | 0 | insufficient_data | insufficient_data | insufficient_data |")
            continue
        cells = [f"{fmt(v[a]['accuracy']['mean'])} / {fmt(v[a]['balanced_accuracy']['mean'])}" for a in ARMS]
        lines.append(f"| {k} | {v['arm2']['worlds'][0]} | " + " | ".join(cells) + " |")
    (HERE / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
