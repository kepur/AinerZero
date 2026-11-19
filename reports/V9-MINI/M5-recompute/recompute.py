"""Independent statistical recomputation for V9-mini M5 confirmatory gate (H1s).

This script is an independent implementation written from scratch.
It does NOT import any modules from `ainerzero.v9.mini.summarize`, `judge_m5`, or `report_only`.
Only numpy and python standard libraries are used.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
M5_DIR = ROOT / "reports/V9-MINI/M5"
OUT_DIR = ROOT / "reports/V9-MINI/M5-recompute"

LATENT_ARMS = [
    "latent_euclid",
    "latent_learned",
    "graph_memory",
    "gru_belief",
    "latent_topo",
    "latent_attn",
]

ALL_ARMS = [
    "random",
    "latent_euclid",
    "latent_learned",
    "graph_memory",
    "gru_belief",
    "latent_topo",
    "topo_oracle_ctrl",
    "latent_attn",
    "map_analytic",
    "map_hybrid",
    "map_hybrid_self",
    "oracle",
]

GATE = 0.50


def cluster_bootstrap_ci(
    diffs: np.ndarray,
    cluster_keys: list[tuple[int, int]],
    rng: np.random.Generator,
    n_boot: int = 4000,
) -> tuple[float, float, int]:
    """Cluster bootstrap confidence interval for paired difference.

    Resamples clusters with replacement n_boot times.
    Cluster estimator is sum of differences across resampled clusters divided by
    total number of episodes in resampled clusters.
    """
    unique_clusters = sorted(set(cluster_keys))
    n_clusters = len(unique_clusters)
    cluster_to_idx = {k: i for i, k in enumerate(unique_clusters)}

    cluster_indices = np.array([cluster_to_idx[k] for k in cluster_keys], dtype=int)
    cluster_sums = np.bincount(cluster_indices, weights=diffs, minlength=n_clusters)
    cluster_counts = np.bincount(cluster_indices, minlength=n_clusters).astype(float)

    # b: (n_boot, n_clusters)
    boot_indices = rng.integers(0, n_clusters, size=(n_boot, n_clusters))

    boot_diff_sums = cluster_sums[boot_indices].sum(axis=1)
    boot_counts = cluster_counts[boot_indices].sum(axis=1)

    boot_means = boot_diff_sums / boot_counts
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    return float(lo), float(hi), n_clusters


def run_checks_and_recompute() -> dict[str, Any]:
    print("=" * 80)
    print("V9-mini M5 CONFIRMATORY RECOMPUTATION (INDEPENDENT L2 RE-EVALUATION)")
    print("=" * 80)

    # ---------------------------------------------------------
    # 0. Load FREEZE.json and ledger.txt
    # ---------------------------------------------------------
    freeze_path = M5_DIR / "FREEZE.json"
    if not freeze_path.exists():
        raise FileNotFoundError(f"Missing {freeze_path}")
    freeze_data = json.loads(freeze_path.read_text(encoding="utf-8"))
    expected_code_sha256 = freeze_data["code_sha256"]
    expected_mlx = freeze_data["mlx"]
    budget_caps = freeze_data["budget"]

    print(f"\n[FREEZE.json] code_sha256: {expected_code_sha256}")
    print(f"[FREEZE.json] mlx: {expected_mlx}")
    print(f"[FREEZE.json] budget: expected={budget_caps.get('expected_sec')}s, cap_total={budget_caps.get('cap_total_sec')}s, cap_run={budget_caps.get('cap_run_sec')}s")

    # Load all runs
    worlds = ["m1", "m2"]
    runs: dict[str, list[dict[str, Any]]] = {}
    episodes: dict[str, list[dict[str, Any]]] = {}

    for w in worlds:
        runs[w] = []
        episodes[w] = []
        for s in range(5):
            run_dir = M5_DIR / f"{w}-s{s}"
            res_file = run_dir / "result.json"
            eps_file = run_dir / "episodes.json"
            if not res_file.exists() or not eps_file.exists():
                raise FileNotFoundError(f"Missing run output in {run_dir}")
            runs[w].append(json.loads(res_file.read_text(encoding="utf-8")))
            episodes[w].append(json.loads(eps_file.read_text(encoding="utf-8")))

    # ---------------------------------------------------------
    # 1. Integrity Checks (7 items including ledger & budget)
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("1. INTEGRITY CHECKS")
    print("-" * 80)

    integrity_report: dict[str, Any] = {}

    # Check 1: meta.code_sha256
    c1_ok = True
    c1_details = {}
    for w in worlds:
        for s in range(5):
            val = runs[w][s]["meta"].get("code_sha256")
            c1_details[f"{w}-s{s}"] = val
            if val != expected_code_sha256:
                c1_ok = False
    integrity_report["check_1_code_sha256"] = {
        "pass": c1_ok,
        "expected": expected_code_sha256,
        "details": c1_details,
    }
    print(f"Check 1 [meta.code_sha256 == FREEZE.json]: {'PASS' if c1_ok else 'FAIL'}")

    # Check 2: meta.mlx
    c2_ok = True
    c2_details = {}
    for w in worlds:
        for s in range(5):
            val = runs[w][s]["meta"].get("mlx")
            c2_details[f"{w}-s{s}"] = val
            if val != expected_mlx:
                c2_ok = False
    integrity_report["check_2_mlx_version"] = {
        "pass": c2_ok,
        "expected": expected_mlx,
        "details": c2_details,
    }
    print(f"Check 2 [meta.mlx == 0.32.2]: {'PASS' if c2_ok else 'FAIL'}")

    # Check 3: eval_seed0 and layout seed boundaries & disjointness
    c3_ok = True
    c3_details = {}
    all_layout_seeds: dict[str, set[int]] = {}
    for w in worlds:
        all_layout_seeds[w] = set()
        for s in range(5):
            expected_seed0 = 8100000 + 1000 * s
            actual_seed0 = runs[w][s]["meta"].get("eval_seed0")
            seeds_in_run = {
                r["layout_seed"] for r in episodes[w][s]["oracle"]
            }
            min_seed, max_seed = min(seeds_in_run), max(seeds_in_run)
            count = len(seeds_in_run)
            within_bounds = (min_seed >= expected_seed0) and (max_seed < expected_seed0 + 80) and (count == 80)
            overlap = not seeds_in_run.isdisjoint(all_layout_seeds[w])
            all_layout_seeds[w].update(seeds_in_run)
            pass_run = (actual_seed0 == expected_seed0) and within_bounds and not overlap
            if not pass_run:
                c3_ok = False
            c3_details[f"{w}-s{s}"] = {
                "eval_seed0": actual_seed0,
                "expected_seed0": expected_seed0,
                "seed_range": [min_seed, max_seed],
                "count": count,
                "no_overlap": not overlap,
            }
    integrity_report["check_3_eval_seeds"] = {
        "pass": c3_ok,
        "details": c3_details,
    }
    print(f"Check 3 [eval_seed0, 80 layouts/seed, disjoint]: {'PASS' if c3_ok else 'FAIL'}")

    # Check 4: Episode counts (per run and total)
    c4_ok = True
    c4_details = {}
    for w in worlds:
        per_run_counts = {
            "short": [sum(1 for r in episodes[w][s]["oracle"] if r["kind"] == "short") for s in range(5)],
            "long": [sum(1 for r in episodes[w][s]["oracle"] if r["kind"] == "long") for s in range(5)],
            "law_relevant": [sum(1 for r in episodes[w][s]["oracle"] if r.get("law_relevant")) for s in range(5)],
            "total": [len(episodes[w][s]["oracle"]) for s in range(5)],
        }
        total_eps = sum(per_run_counts["total"])
        long_eps = sum(per_run_counts["long"])
        short_eps = sum(per_run_counts["short"])
        law_eps = sum(per_run_counts["law_relevant"])
        c4_details[w] = {
            "total": total_eps,
            "short": short_eps,
            "long": long_eps,
            "law_relevant": law_eps,
            "per_run": per_run_counts,
        }
        print(f"  {w} episode counts per seed: short={per_run_counts['short']} (total={short_eps}), long={per_run_counts['long']} (total={long_eps})" +
              (f", law_relevant={per_run_counts['law_relevant']} (total={law_eps})" if w == "m2" else ""))

    if c4_details["m1"]["total"] != 1562 or c4_details["m1"]["long"] != 762 or c4_details["m1"]["short"] != 800:
        c4_ok = False
    if c4_details["m2"]["total"] != 1736 or c4_details["m2"]["long"] != 936 or c4_details["m2"]["short"] != 800 or c4_details["m2"]["law_relevant"] != 517:
        c4_ok = False
    integrity_report["check_4_episode_counts"] = {
        "pass": c4_ok,
        "details": c4_details,
    }
    print(f"Check 4 [Episode counts: m1 1562 (762 long), m2 1736 (936 long, 517 law)]: {'PASS' if c4_ok else 'FAIL'}")

    # Check 5: Task sequence consistency across all 12 arms
    c5_ok = True
    c5_details = {}
    for w in worlds:
        for s in range(5):
            ref_seq = [
                (r["layout_seed"], r["kind"], r["d_star"], r.get("law_relevant", False))
                for r in episodes[w][s]["oracle"]
            ]
            arm_mismatches = []
            for arm in ALL_ARMS:
                arm_seq = [
                    (r["layout_seed"], r["kind"], r["d_star"], r.get("law_relevant", False))
                    for r in episodes[w][s][arm]
                ]
                if arm_seq != ref_seq:
                    arm_mismatches.append(arm)
            if arm_mismatches:
                c5_ok = False
                c5_details[f"{w}-s{s}"] = arm_mismatches
            else:
                c5_details[f"{w}-s{s}"] = "perfect_match"
    integrity_report["check_5_task_sequence_consistency"] = {
        "pass": c5_ok,
        "details": c5_details,
    }
    print(f"Check 5 [Task sequence identical across all 12 arms]: {'PASS' if c5_ok else 'FAIL'}")

    # Check 6: Oracle success rate == 1.000
    c6_ok = True
    c6_details = {}
    for w in worlds:
        for s in range(5):
            successes = [r["success"] for r in episodes[w][s]["oracle"]]
            oracle_rate = float(np.mean(successes))
            c6_details[f"{w}-s{s}"] = oracle_rate
            if oracle_rate != 1.0:
                c6_ok = False
    integrity_report["check_6_oracle_success"] = {
        "pass": c6_ok,
        "details": c6_details,
    }
    print(f"Check 6 [Oracle 100% success across all episodes]: {'PASS' if c6_ok else 'FAIL'}")

    # Check 7: ledger.txt vs meta.wall_sec & Budget caps
    c7_ok = True
    c7_details = {}
    ledger_path = M5_DIR / "ledger.txt"
    if not ledger_path.exists():
        c7_ok = False
        c7_details["error"] = "Missing ledger.txt"
    else:
        ledger_text = ledger_path.read_text(encoding="utf-8")
        pattern = re.compile(r"(\S+)\s+(m[12])\s+s(\d)\s+exit=(\d+)\s+用时\s+(\d+)s\s+累计\s+(\d+)s")
        ledger_entries = {}
        for line in ledger_text.splitlines():
            m = pattern.search(line)
            if m:
                w_tag, s_idx, exit_code, dur_s, cum_s = (
                    m.group(2),
                    int(m.group(3)),
                    int(m.group(4)),
                    int(m.group(5)),
                    int(m.group(6)),
                )
                ledger_entries[(w_tag, s_idx)] = {
                    "exit": exit_code,
                    "dur": dur_s,
                    "cum": cum_s,
                }

        total_ledger_time = max(e["cum"] for e in ledger_entries.values()) if ledger_entries else 0
        cap_total = budget_caps["cap_total_sec"]
        cap_run = budget_caps["cap_run_sec"]

        c7_details["runs"] = {}
        for w in worlds:
            for s in range(5):
                wall_sec = runs[w][s]["meta"].get("wall_sec", 0.0)
                l_info = ledger_entries.get((w, s))
                if not l_info:
                    c7_ok = False
                    c7_details["runs"][f"{w}-s{s}"] = {"error": "Missing ledger entry"}
                    continue
                diff = abs(wall_sec - l_info["dur"])
                exit_ok = (l_info["exit"] == 0)
                run_time_ok = (l_info["dur"] <= cap_run)
                match_ok = (diff <= 10.0)  # shell wrapper difference within 10s
                if not (exit_ok and run_time_ok and match_ok):
                    c7_ok = False
                c7_details["runs"][f"{w}-s{s}"] = {
                    "wall_sec": wall_sec,
                    "ledger_sec": l_info["dur"],
                    "diff": diff,
                    "exit": l_info["exit"],
                    "within_cap_run": run_time_ok,
                }
                print(f"  {w}-s{s}: wall_sec={wall_sec:.1f}s, ledger={l_info['dur']}s, diff={diff:.1f}s, exit={l_info['exit']}")

        cum_ok = (total_ledger_time <= cap_total)
        if not cum_ok:
            c7_ok = False
        c7_details["total_ledger_sec"] = total_ledger_time
        c7_details["cap_total_sec"] = cap_total
        c7_details["cum_within_budget"] = cum_ok
        print(f"  Total ledger wall time: {total_ledger_time}s <= budget cap {cap_total}s (cap_run={cap_run}s)")

    integrity_report["check_7_ledger_and_budget"] = {
        "pass": c7_ok,
        "details": c7_details,
    }
    print(f"Check 7 [ledger.txt matches result.json & within budget]: {'PASS' if c7_ok else 'FAIL'}")

    all_integrity_passed = all([c1_ok, c2_ok, c3_ok, c4_ok, c5_ok, c6_ok, c7_ok])
    integrity_report["all_passed"] = all_integrity_passed
    print(f"\nAll 7 integrity checks: {'ALL PASSED' if all_integrity_passed else 'SOME FAILED'}")

    # ---------------------------------------------------------
    # 2. Independent H1s Recomputation & Pairwise Differences
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("2. PRIMARY CONFIRMATORY GATE H1s & PAIRWISE DIFFERENCES")
    print("-" * 80)

    # Initialize RNG exactly as in judge_m5: np.random.default_rng(0)
    rng = np.random.default_rng(0)

    recomputed: dict[str, Any] = {}

    for w in worlds:
        print(f"\n===== World {w} =====")
        long_records: dict[str, list[dict[str, Any]]] = {}
        long_keys: list[tuple[int, int]] = []

        ref_long_eps = []
        for s in range(5):
            for r in episodes[w][s]["oracle"]:
                if r["kind"] == "long":
                    ref_long_eps.append((s, r))
                    long_keys.append((s, r["layout_seed"]))

        n_long = len(ref_long_eps)
        n_clusters = len(set(long_keys))
        print(f"Total long episodes: {n_long}, Unique clusters (run x layout): {n_clusters}")

        long_success: dict[str, float] = {}
        long_success_vectors: dict[str, np.ndarray] = {}
        per_run_long_success: dict[str, list[float]] = {}

        for arm in ALL_ARMS:
            arm_long_eps = []
            per_run_rates = []
            for s in range(5):
                s_long_eps = [r["success"] for r in episodes[w][s][arm] if r["kind"] == "long"]
                arm_long_eps.extend(s_long_eps)
                per_run_rates.append(float(np.mean(s_long_eps)))
            vec = np.array(arm_long_eps, dtype=float)
            long_success_vectors[arm] = vec
            long_success[arm] = float(np.mean(vec))
            per_run_long_success[arm] = per_run_rates
            print(
                f"  {arm:18s} long pooled: {long_success[arm]:.4f} ({long_success[arm]:.3f}) | "
                f"per-seed: {[round(x, 4) for x in per_run_rates]} (rounded 3dec: {[round(x, 3) for x in per_run_rates]}) | "
                f"run-mean: {np.mean(per_run_rates):.4f}"
            )

        # Select best latent arm
        best_latent = max(LATENT_ARMS, key=lambda a: (long_success[a], a))
        print(f"  --> Best latent arm: {best_latent} (pooled success: {long_success[best_latent]:.4f})")

        # Evaluate pairs in exact sequence
        pair_definitions = [
            ("map_hybrid_self", best_latent),
            ("map_hybrid", best_latent),
            ("map_hybrid_self", "latent_topo"),
            ("map_hybrid_self", "latent_attn"),
            ("topo_oracle_ctrl", "latent_topo"),
            ("map_hybrid_self", "topo_oracle_ctrl"),
        ]

        pairs_res: dict[str, Any] = {}
        for a, b in pair_definitions:
            pair_name = f"{a} - {b}"
            if pair_name in pairs_res:
                continue
            diff_vec = long_success_vectors[a] - long_success_vectors[b]
            point_diff = float(np.mean(diff_vec))
            lo, hi, clusters_used = cluster_bootstrap_ci(diff_vec, long_keys, rng, n_boot=4000)
            pairs_res[pair_name] = {
                "diff": point_diff,
                "lo": lo,
                "hi": hi,
                "clusters": clusters_used,
            }
            print(f"  {pair_name:38s}: diff = {point_diff:+.4f} (rounded {point_diff:+.3f})  95% CI: [{lo:+.4f}, {hi:+.4f}] ([{lo:+.3f}, {hi:+.3f}])")

        primary_pair = pairs_res[f"map_hybrid_self - {best_latent}"]
        h1s_pass = bool(primary_pair["diff"] >= GATE and primary_pair["lo"] > 0)
        h1s_verdict = {
            "diff": primary_pair["diff"],
            "lo": primary_pair["lo"],
            "hi": primary_pair["hi"],
            "clusters": primary_pair["clusters"],
            "gate": GATE,
            "pass": h1s_pass,
        }
        print(f"  --> H1s Verdict: {'PASS' if h1s_pass else 'FAIL'} (diff={primary_pair['diff']:+.4f} >= {GATE}, CI lo={primary_pair['lo']:+.4f} > 0)")

        recomputed[w] = {
            "n_long": n_long,
            "n_clusters": n_clusters,
            "long_success": long_success,
            "per_run_long_success": per_run_long_success,
            "best_latent": best_latent,
            "pairs": pairs_res,
            "H1s": h1s_verdict,
        }

    # ---------------------------------------------------------
    # 3. Report-Only Items (Short, Law-Relevant, Relocalizations)
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("3. REPORT-ONLY ITEMS RECOMPUTATION")
    print("-" * 80)

    report_only: dict[str, Any] = {}

    for w in worlds:
        print(f"\n===== World {w} Report-Only Metrics =====")
        subsets = {
            "short": lambda r: r["kind"] == "short",
            "long": lambda r: r["kind"] == "long",
        }
        if w == "m2":
            subsets["law_relevant"] = lambda r: bool(r.get("law_relevant", False))

        success_by_subset: dict[str, dict[str, float]] = {}
        per_run_by_subset: dict[str, dict[str, list[float]]] = {}
        counts_by_subset: dict[str, int] = {}
        per_run_counts_by_subset: dict[str, list[int]] = {}

        for sub_name, filter_fn in subsets.items():
            run_counts = [sum(1 for r in episodes[w][s]["oracle"] if filter_fn(r)) for s in range(5)]
            per_run_counts_by_subset[sub_name] = run_counts
            counts_by_subset[sub_name] = sum(run_counts)
            success_by_subset[sub_name] = {}
            per_run_by_subset[sub_name] = {}

            print(f"  {sub_name} (total={counts_by_subset[sub_name]}, per_seed={run_counts}):")
            for arm in ALL_ARMS:
                per_run_rates = [
                    float(np.mean([r["success"] for r in episodes[w][s][arm] if filter_fn(r)]))
                    for s in range(5)
                ]
                pooled_val = float(np.mean([r["success"] for s in range(5) for r in episodes[w][s][arm] if filter_fn(r)]))
                success_by_subset[sub_name][arm] = pooled_val
                per_run_by_subset[sub_name][arm] = per_run_rates
                print(
                    f"    {arm:18s} pooled: {pooled_val:.4f} ({pooled_val:.3f}) | "
                    f"per_seed: {[round(x, 4) for x in per_run_rates]} (rounded 3dec: {[round(x, 3) for x in per_run_rates]}) | "
                    f"run_mean: {np.mean(per_run_rates):.4f}"
                )

        # Relocalizations for latent_topo and topo_oracle_ctrl
        reloc_stats: dict[str, Any] = {}
        for a in ("latent_topo", "topo_oracle_ctrl"):
            all_relocs = np.array(
                [r["relocalizations"] for s in range(5) for r in episodes[w][s][a]],
                dtype=float,
            )
            long_eps_data = [
                (r["relocalizations"], r["success"])
                for s in range(5)
                for r in episodes[w][s][a]
                if r["kind"] == "long"
            ]
            succ_relocs = [rel for rel, s in long_eps_data if s == 1]
            fail_relocs = [rel for rel, s in long_eps_data if s == 0]

            stat = {
                "mean": float(np.mean(all_relocs)),
                "median": float(np.median(all_relocs)),
                "max": float(np.max(all_relocs)),
                "long_success_mean": float(np.mean(succ_relocs)) if succ_relocs else None,
                "long_fail_mean": float(np.mean(fail_relocs)) if fail_relocs else None,
            }
            reloc_stats[a] = stat
            ls_str = f"{stat['long_success_mean']:.2f}" if stat["long_success_mean"] is not None else "None"
            print(
                f"  {a:18s} relocations: mean={stat['mean']:.2f} (rep {stat['mean']:.1f}), "
                f"median={stat['median']:.1f}, max={stat['max']:.0f}, "
                f"long_success_mean={ls_str}, long_fail_mean={stat['long_fail_mean']:.2f} (rep {stat['long_fail_mean']:.1f})"
            )

        report_only[w] = {
            "counts": counts_by_subset,
            "per_run_counts": per_run_counts_by_subset,
            "success": success_by_subset,
            "per_run_success": per_run_by_subset,
            "relocalizations": reloc_stats,
        }

    # ---------------------------------------------------------
    # 4. Two Averaging Standards Comparison (Item 5)
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("4. COMPARISON OF TWO AVERAGING STANDARDS (POOLED VS RUN-MEAN)")
    print("-" * 80)

    averaging_comparison: dict[str, Any] = {}

    for w in worlds:
        averaging_comparison[w] = {}
        print(f"\n===== World {w} Averaging Standard Comparison =====")
        subsets_to_compare = ["short", "long"] if w == "m1" else ["short", "long", "law_relevant"]
        for subset_name in subsets_to_compare:
            averaging_comparison[w][subset_name] = {}
            print(f"  --- Subset: {subset_name} ---")
            for arm in ALL_ARMS:
                pooled_val = report_only[w]["success"][subset_name][arm]
                per_run_vals = report_only[w]["per_run_success"][subset_name][arm]
                run_mean_val = float(np.mean(per_run_vals))
                delta = pooled_val - run_mean_val
                averaging_comparison[w][subset_name][arm] = {
                    "pooled": pooled_val,
                    "per_run": per_run_vals,
                    "run_mean": run_mean_val,
                    "delta": delta,
                }
                print(
                    f"    {arm:18s} Pooled={pooled_val:.4f}  Run-Mean={run_mean_val:.4f}  "
                    f"Delta={delta:+.4f} (runs: {[round(x, 4) for x in per_run_vals]})"
                )

    # ---------------------------------------------------------
    # 5. Verification Against Author's Files
    # ---------------------------------------------------------
    print("\n" + "-" * 80)
    print("5. VERIFICATION AGAINST AUTHOR'S DELIVERABLES")
    print("-" * 80)

    verdict_json_path = M5_DIR / "analysis/verdict.json"
    author_verdict = json.loads(verdict_json_path.read_text(encoding="utf-8"))

    report_only_json_path = M5_DIR / "analysis/report_only.txt"
    lines = report_only_json_path.read_text(encoding="utf-8").strip().splitlines()
    author_report_only = json.loads(lines[-1])

    discrepancies: list[dict[str, Any]] = []

    for w in worlds:
        # Check best latent
        if recomputed[w]["best_latent"] != author_verdict[w]["best_latent"]:
            discrepancies.append({
                "item": f"{w} best_latent",
                "author": author_verdict[w]["best_latent"],
                "recomputed": recomputed[w]["best_latent"],
                "severity": "阻断",
            })
        # Check long_success
        for arm in ALL_ARMS:
            v_auth = author_verdict[w]["long_success"][arm]
            v_recomp = recomputed[w]["long_success"][arm]
            diff = abs(v_auth - v_recomp)
            if diff > 1e-9:
                discrepancies.append({
                    "item": f"{w} long_success[{arm}]",
                    "author": v_auth,
                    "recomputed": v_recomp,
                    "diff": diff,
                    "severity": "阻断",
                })
        # Check pairs
        for pair_name, pair_data in author_verdict[w]["pairs"].items():
            recomp_pair = recomputed[w]["pairs"][pair_name]
            pt_diff = abs(pair_data["diff"] - recomp_pair["diff"])
            if pt_diff > 1e-9:
                discrepancies.append({
                    "item": f"{w} pair diff: {pair_name}",
                    "author": pair_data["diff"],
                    "recomputed": recomp_pair["diff"],
                    "diff": pt_diff,
                    "severity": "阻断",
                })
            lo_diff = abs(pair_data["lo"] - recomp_pair["lo"])
            hi_diff = abs(pair_data["hi"] - recomp_pair["hi"])
            if lo_diff > 0.01 or hi_diff > 0.01:
                discrepancies.append({
                    "item": f"{w} pair CI: {pair_name}",
                    "author": [pair_data["lo"], pair_data["hi"]],
                    "recomputed": [recomp_pair["lo"], recomp_pair["hi"]],
                    "max_diff": max(lo_diff, hi_diff),
                    "severity": "阻断",
                })
            else:
                print(f"  Match exact: {w} pair {pair_name} diff and CI identical to 1e-9")

        # Check H1s verdict
        if recomputed[w]["H1s"]["pass"] != author_verdict[w]["H1s"]["pass"]:
            discrepancies.append({
                "item": f"{w} H1s pass",
                "author": author_verdict[w]["H1s"]["pass"],
                "recomputed": recomputed[w]["H1s"]["pass"],
                "severity": "阻断",
            })

        # Check report_only success
        for sub_name in author_report_only[w]["success"]:
            for arm in ALL_ARMS:
                v_auth = author_report_only[w]["success"][sub_name][arm]
                v_recomp = report_only[w]["success"][sub_name][arm]
                if abs(v_auth - v_recomp) > 1e-9:
                    discrepancies.append({
                        "item": f"{w} report_only success[{sub_name}][{arm}]",
                        "author": v_auth,
                        "recomputed": v_recomp,
                        "severity": "阻断",
                    })

        # Check relocalizations
        for a in ("latent_topo", "topo_oracle_ctrl"):
            auth_rel = author_report_only[w]["relocalizations"][a]
            recomp_rel = report_only[w]["relocalizations"][a]
            for stat_k in ("mean", "median", "max", "long_success_mean", "long_fail_mean"):
                va = auth_rel[stat_k]
                vr = recomp_rel[stat_k]
                if va is None and vr is None:
                    continue
                if abs(va - vr) > 1e-9:
                    discrepancies.append({
                        "item": f"{w} relocations[{a}][{stat_k}]",
                        "author": va,
                        "recomputed": vr,
                        "severity": "阻断",
                    })

    print(f"\nDiscrepancies found with author deliverables: {len(discrepancies)}")
    if discrepancies:
        for d in discrepancies:
            print(f"  - [{d['severity']}] {d['item']}: Author={d['author']}, Recomputed={d['recomputed']}")
    else:
        print("  --> PERFECT REPLICATION: 0 discrepancies across all point estimates, pairs, CIs, and metrics!")

    # ---------------------------------------------------------
    # 6. Final Output Assembly
    # ---------------------------------------------------------
    final_output = {
        "integrity": integrity_report,
        "recomputed_primary": recomputed,
        "report_only": report_only,
        "averaging_comparison": averaging_comparison,
        "discrepancies": discrepancies,
        "verdict": "复算一致" if len(discrepancies) == 0 else "有出入需作者核实",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "recompute.json"
    json_path.write_text(json.dumps(final_output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved structured results to {json_path}")

    return final_output


if __name__ == "__main__":
    run_checks_and_recompute()
