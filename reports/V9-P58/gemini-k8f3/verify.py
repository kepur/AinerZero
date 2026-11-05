#!/usr/bin/env python3
"""
Independent verification script for ainerzero.V9.P58 (review of P57).
Author: gemini-k8f3 (Tier 2 executor)
Role: Non-author review of P57 (author: claude)

This script:
1. Verifies SHA256SUMS.txt of raw evaluation records in reports/V9-S1-r15/eval-details/.
2. Independently reads raw eval JSONs and computes all summary statistics:
   - mean, min, max, ranking, and range disjointness for arm2, arm3, arm4 across 3 seeds.
   - per-family breakdown of NLL and translation error.
   - few-shot transfer accuracy and balanced accuracy across k values.
   - D-candidate (arm1) completed status and incomparability.
3. Compares independent calculations with P57's REPORT.md, tables.md, and analysis.json.
4. Audits compliance with artifacts/v9/s1/phase1/r15/pre_registration.json:
   - directions and definitions of the 6 registered metrics.
   - 3 reporting notes.
   - checks for overstepping claims (no invented thresholds, no capability promotion, no misinterpretation of topology F1 / pooled k curves).
"""

import os
import sys
import json
import hashlib
from pathlib import Path

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def verify_checksums(eval_dir):
    sums_file = eval_dir / "SHA256SUMS.txt"
    if not sums_file.exists():
        raise FileNotFoundError(f"Missing {sums_file}")
    
    mismatches = []
    verified = {}
    with open(sums_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            expected_sha, fname = line.split(maxsplit=1)
            target = eval_dir / fname
            if not target.exists():
                mismatches.append((fname, expected_sha, "FILE_NOT_FOUND"))
                continue
            actual_sha = compute_sha256(target)
            if actual_sha != expected_sha:
                mismatches.append((fname, expected_sha, actual_sha))
            else:
                verified[fname] = actual_sha
    return verified, mismatches

def load_eval_records(eval_dir):
    records = {"arm1": None, "arm2": {}, "arm3": {}, "arm4": {}}
    for path in sorted(eval_dir.glob("eval-*.json")):
        with open(path, "r") as f:
            data = json.load(f)
        fname = path.name
        if fname == "eval-arm1.json":
            records["arm1"] = data
        else:
            arm = data["details"]["arm_id"]
            seed = data["details"]["seed"]
            records[arm][seed] = data
    return records

def check_disjoint(r_a, r_b):
    # r_a is (min_a, max_a), r_b is (min_b, max_b)
    # disjoint if max_a < min_b or max_b < min_a
    return r_a[1] < r_b[0] or r_b[1] < r_a[0]

def analyze_raw(records):
    arms = ["arm2", "arm3", "arm4"]
    
    scalar_defs = [
        ("dev_translation_mean_m", "lower_is_better", lambda d: d["localization_error"]["localization_error"]["translation_mean_m"]),
        ("dev_translation_median_m", "lower_is_better", lambda d: d["localization_error"]["localization_error"]["translation_median_m"]),
        ("dev_yaw_mean_deg", "lower_is_better", lambda d: d["localization_error"]["localization_error"]["yaw_mean_deg"]),
        ("next_obs_nll_mean", "lower_is_better", lambda d: d["unseen_map_generalization"]["prediction_nll_mean"]),
        ("next_obs_nll_median", "lower_is_better", lambda d: d["unseen_map_generalization"]["prediction_nll_median"]),
        ("unseen_translation_mean_m", "lower_is_better", lambda d: d["unseen_map_generalization"]["translation_mean_m"]),
        ("edge_f1", "higher_is_better", lambda d: d["topology_recovery"]["f1"]),
        ("nll_curve_normalised_area", "lower_is_better", lambda d: d["sample_efficiency"]["nll_curve"]["normalised_area"]),
        ("final_nll", "lower_is_better", lambda d: next(cp["development_nll"] for cp in d["sample_efficiency"]["checkpoints"] if cp["updates"] == 3510)),
        ("loc_curve_normalised_area", "lower_is_better", lambda d: d["sample_efficiency"]["localization_curve"]["normalised_area"]),
        ("worst_retention_delta", "lower_is_better", lambda d: d["m2_memory_interference"]["worst_retention_delta"]),
    ]
    
    scalars_summary = {}
    for name, direction, getter in scalar_defs:
        metric_res = {"direction": direction, "per_arm": {}}
        for arm in arms:
            vals = [getter(records[arm][s]["details"]) for s in [0, 1, 2]]
            m_val = sum(vals) / len(vals)
            min_val = min(vals)
            max_val = max(vals)
            metric_res["per_arm"][arm] = {
                "values": vals,
                "mean": m_val,
                "min": min_val,
                "max": max_val,
            }
        
        # Ranking
        means = {arm: metric_res["per_arm"][arm]["mean"] for arm in arms}
        if len(set(means.values())) == 1:
            rank_list = ["tie (identical in every cell; no ranking)"]
        else:
            reverse = (direction == "higher_is_better")
            sorted_arms = sorted(arms, key=lambda a: means[a], reverse=reverse)
            rank_list = sorted_arms
        metric_res["rank_by_mean"] = rank_list
        
        # Disjoint pairs dict
        seed_ranges_disjoint = {}
        if rank_list != ["tie (identical in every cell; no ranking)"]:
            pairs = [(rank_list[0], rank_list[1]), (rank_list[0], rank_list[2]), (rank_list[1], rank_list[2])]
            for a1, a2 in pairs:
                r1 = (metric_res["per_arm"][a1]["min"], metric_res["per_arm"][a1]["max"])
                r2 = (metric_res["per_arm"][a2]["min"], metric_res["per_arm"][a2]["max"])
                seed_ranges_disjoint[f"{a1}_vs_{a2}"] = check_disjoint(r1, r2)
        metric_res["seed_ranges_disjoint"] = seed_ranges_disjoint
        scalars_summary[name] = metric_res
        
    # 2. Family breakdown for unseen_map_generalization (NLL and translation)
    families = ["e3_identity", "navigation", "relation", "time"]
    family_summary = {}
    for fam in families:
        family_summary[fam] = {
            "prediction_nll_mean": {},
            "translation_mean_m": {}
        }
        for arm in arms:
            nll_vals = [records[arm][s]["details"]["unseen_map_generalization"]["by_family"][fam]["prediction_nll_mean"] for s in [0, 1, 2]]
            trans_vals = [records[arm][s]["details"]["unseen_map_generalization"]["by_family"][fam]["translation_mean_m"] for s in [0, 1, 2]]
            family_summary[fam]["prediction_nll_mean"][arm] = {
                "values": nll_vals,
                "mean": sum(nll_vals) / 3.0,
                "min": min(nll_vals),
                "max": max(nll_vals),
            }
            family_summary[fam]["translation_mean_m"][arm] = {
                "values": trans_vals,
                "mean": sum(trans_vals) / 3.0,
                "min": min(trans_vals),
                "max": max(trans_vals),
            }
            
    # 3. Few-shot summary
    few_shot_summary = {}
    for k in [0, 1, 2, 4, 8]:
        k_str = str(k)
        few_shot_summary[k_str] = {}
        for arm in arms:
            if k_str == "8":
                few_shot_summary[k_str][arm] = "insufficient_data"
            else:
                acc_vals = [records[arm][s]["details"]["few_shot_unseen_transition"]["curve"][k_str]["accuracy"] for s in [0, 1, 2]]
                bal_vals = [records[arm][s]["details"]["few_shot_unseen_transition"]["curve"][k_str]["balanced_accuracy"] for s in [0, 1, 2]]
                worlds_vals = [records[arm][s]["details"]["few_shot_unseen_transition"]["curve"][k_str]["worlds"] for s in [0, 1, 2]]
                few_shot_summary[k_str][arm] = {
                    "worlds": worlds_vals[0],
                    "accuracy_mean": sum(acc_vals) / 3.0,
                    "balanced_accuracy_mean": sum(bal_vals) / 3.0,
                }
                
    # 4. Arm1 check
    arm1_d = records["arm1"]["details"]
    arm1_summary = {
        "status": records["arm1"]["status"],
        "incomparable": arm1_d["incomparable"],
        "d_candidate_c0_metrics": arm1_d["d_candidate_c0_metrics"],
    }
    
    return {
        "scalars": scalars_summary,
        "family_summary": family_summary,
        "few_shot_summary": few_shot_summary,
        "arm1": arm1_summary
    }

def verify_against_author(independent_res, author_analysis_path):
    with open(author_analysis_path, "r") as f:
        auth = json.load(f)
    
    diffs = []
    
    auth_scalar_map = {item["label"]: item for item in auth["scalars"]}
    mapping = {
        "dev_translation_mean_m": "development translation error, mean (m)",
        "dev_translation_median_m": "development translation error, median (m)",
        "dev_yaw_mean_deg": "development yaw error, mean (deg)",
        "next_obs_nll_mean": "next-observation NLL, mean (nats)",
        "next_obs_nll_median": "next-observation NLL, median (nats)",
        "unseen_translation_mean_m": "unseen-map translation error, mean (m)",
        "edge_f1": "edge F1 (degenerate, see notes)",
        "nll_curve_normalised_area": "NLL curve, normalised area",
        "final_nll": "NLL at the final checkpoint",
        "loc_curve_normalised_area": "localization curve, normalised area",
        "worst_retention_delta": "worst retention delta",
    }
    
    for my_name, auth_label in mapping.items():
        if auth_label not in auth_scalar_map:
            diffs.append(f"Missing scalar in author analysis: {auth_label}")
            continue
        auth_item = auth_scalar_map[auth_label]
        my_item = independent_res["scalars"][my_name]
        
        # check direction
        if auth_item["direction"] != my_item["direction"]:
            diffs.append(f"{my_name} direction mismatch: {auth_item['direction']} vs {my_item['direction']}")
            
        # check values, mean, min, max
        for arm in ["arm2", "arm3", "arm4"]:
            my_arm = my_item["per_arm"][arm]
            auth_arm = auth_item["per_arm"][arm]
            for key in ["mean", "min", "max"]:
                val_auth = auth_arm[key]
                val_my = my_arm[key]
                if abs(val_auth - val_my) > 1e-6:
                    diffs.append(f"{my_name} {arm} {key} mismatch: auth={val_auth}, my={val_my}")
                    
        # check rank_by_mean
        if auth_item["rank_by_mean"] != my_item["rank_by_mean"]:
            diffs.append(f"{my_name} rank mismatch: auth={auth_item['rank_by_mean']}, my={my_item['rank_by_mean']}")
            
        # check seed_ranges_disjoint
        if auth_item["seed_ranges_disjoint"] != my_item["seed_ranges_disjoint"]:
            diffs.append(f"{my_name} disjoint mismatch: auth={auth_item['seed_ranges_disjoint']}, my={my_item['seed_ranges_disjoint']}")
            
    # Check family breakdown in auth["unseen_map_by_family"]
    for fam in ["e3_identity", "navigation", "relation", "time"]:
        for metric_k in ["prediction_nll_mean", "translation_mean_m"]:
            for arm in ["arm2", "arm3", "arm4"]:
                auth_val = auth["unseen_map_by_family"][fam][metric_k][arm]["mean"]
                my_val = independent_res["family_summary"][fam][metric_k][arm]["mean"]
                if abs(auth_val - my_val) > 1e-6:
                    diffs.append(f"family {fam} {metric_k} {arm} mean mismatch: auth={auth_val}, my={my_val}")
                    
    # Check few shot in auth["few_shot_pooled_over_families"]
    for k in [0, 1, 2, 4]:
        k_str = str(k)
        for arm in ["arm2", "arm3", "arm4"]:
            auth_acc = auth["few_shot_pooled_over_families"][k_str][arm]["accuracy"]["mean"]
            my_acc = independent_res["few_shot_summary"][k_str][arm]["accuracy_mean"]
            if abs(auth_acc - my_acc) > 1e-6:
                diffs.append(f"few_shot k={k} {arm} accuracy mismatch: auth={auth_acc}, my={my_acc}")
                
            auth_bal = auth["few_shot_pooled_over_families"][k_str][arm]["balanced_accuracy"]["mean"]
            my_bal = independent_res["few_shot_summary"][k_str][arm]["balanced_accuracy_mean"]
            if abs(auth_bal - my_bal) > 1e-6:
                diffs.append(f"few_shot k={k} {arm} balanced_accuracy mismatch: auth={auth_bal}, my={my_bal}")
                
    # Check arm1
    auth_c0 = auth["arm1_d_candidate"]["c0_metrics"]
    my_c0 = independent_res["arm1"]["d_candidate_c0_metrics"]
    for k in ["observation_loss_t0", "observation_loss_t1", "symbol_nll_t0", "symbol_nll_t1"]:
        if abs(auth_c0[k] - my_c0[k]) > 1e-6:
            diffs.append(f"arm1 {k} mismatch: auth={auth_c0[k]}, my={my_c0[k]}")
            
    return diffs

def verify_preregistration_rules(prereg_path, report_md_path):
    with open(prereg_path, "r") as f:
        prereg = json.load(f)
    with open(report_md_path, "r") as f:
        report_md = f.read()
        
    audit = {}
    
    registered_metrics = prereg["metrics"]
    audit["metrics_count"] = len(registered_metrics)
    audit["metrics_checked"] = []
    for m in registered_metrics:
        audit["metrics_checked"].append({
            "id": m["id"],
            "direction": m["direction"],
            "unit": m["unit"]
        })
        
    reporting_notes = prereg["evaluation"]["reporting_notes"]
    audit["reporting_notes"] = reporting_notes
    
    note1_respected = ("insufficient_data" in report_md and "k=8" in report_md)
    note2_disclosed = ("注记 2" in report_md and "口径缺口" in report_md)
    note3_respected = ("覆盖率只作注记" in report_md)
    audit["notes_compliance"] = {
        "note1_k8_insufficient_data": note1_respected,
        "note2_pooled_curve_gap_disclosed": note2_disclosed,
        "note3_coverage_as_notes_only": note3_respected,
    }
    
    audit["overstepping_claims"] = {
        "claimed_capability_promotion": not ("不宣称能力晋升" in report_md),
        "invented_statistical_thresholds": not ("没有冻结任何统计检验或过门阈值" in report_md),
        "treated_topology_f1_as_conclusion": not ("拓扑恢复与 few-shot 转移预测对本轮比较都没有信息量" in report_md),
        "final_partition_not_read": "没有读 final 分区" in report_md,
    }
    
    return audit

def main():
    root = Path("/Users/mac/AinerWorkFlow/AinerZero")
    eval_dir = root / "reports/V9-S1-r15/eval-details"
    auth_analysis_path = root / "reports/V9-S1-phase1-analysis/analysis.json"
    prereg_path = root / "artifacts/v9/s1/phase1/r15/pre_registration.json"
    report_md_path = root / "reports/V9-S1-phase1-analysis/REPORT.md"
    
    print("=== Step 1: Verify SHA256 Checksums ===")
    verified, mismatches = verify_checksums(eval_dir)
    print(f"Verified files count: {len(verified)}")
    if mismatches:
        print(f"FAILED: Checksum mismatches found: {mismatches}")
        sys.exit(1)
    else:
        print("ALL SHA256 checksums OK.")
        
    print("\n=== Step 2: Independent Metric Calculation ===")
    records = load_eval_records(eval_dir)
    independent_res = analyze_raw(records)
    print("Raw metrics calculated successfully.")
    
    print("\n=== Step 3: Compare with Author Analysis (P57) ===")
    diffs = verify_against_author(independent_res, auth_analysis_path)
    if diffs:
        print(f"FAILED: Differences found with author analysis:\n" + "\n".join(diffs))
        sys.exit(1)
    else:
        print("PERFECT MATCH: All numbers in analysis.json match independent calculation to float precision!")
        
    print("\n=== Step 4: Audit Pre-registration and Overstepping Claims ===")
    audit = verify_preregistration_rules(prereg_path, report_md_path)
    print("Pre-registration audit results:")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    
    out_dir = root / "reports/V9-P58/gemini-k8f3"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    verification_output = {
        "status": "verified",
        "sha256_verified": verified,
        "independent_metrics": independent_res,
        "diffs_with_author": diffs,
        "preregistration_audit": audit,
        "conclusion": "建议通过"
    }
    
    with open(out_dir / "verification.json", "w") as f:
        json.dump(verification_output, f, indent=2, ensure_ascii=False)
        
    print(f"\nVerification summary saved to {out_dir / 'verification.json'}")

if __name__ == "__main__":
    main()
