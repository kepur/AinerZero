#!/usr/bin/env python3
"""S4 Phase 1 Final Review: Pure NumPy Recomputation of all Gates and Legality Checks.
DOES NOT import ainerzero, runner, or any project code. Only standard library + numpy.

Loads:
- artifacts/v9/s4/phase1/final-final/worlds.jsonl
- reports/V9-S4-PHASE1/PREREG-r1.json
- reports/V9-S4-PHASE1/final/final.json (for bit-for-bit assertion)
"""
import json
import sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[4]

def ratio(num, den):
    num, den = np.asarray(num, dtype=np.float64), np.asarray(den, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)

def stat_D(x_coll, b_coll, **_):
    return 1 - ratio(x_coll, b_coll)

def stat_HF(x_graze, n_graze, b_coll, n_coll, **_):
    return ratio(ratio(x_graze, n_graze), ratio(b_coll, n_coll))

def stat_C(x, b, p, **_):
    return ratio(x - b, p - b)

def stat_diff(x, y, n, **_):
    return ratio(x - y, n)

def run_bootstrap(stat_fn, sums_dict, n_boot, seed, level, m=1):
    names = list(sums_dict.keys())
    arr = np.stack([np.asarray(sums_dict[k], dtype=np.float64) for k in names])
    n_w = arr.shape[1]
    with np.errstate(divide="ignore", invalid="ignore"):
        point = float(stat_fn(**dict(zip(names, arr.sum(1)))))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_w, size=(n_boot, n_w))
    tot = arr[:, draws].sum(-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        boot = np.array(stat_fn(**dict(zip(names, tot))), dtype=np.float64)
    boot = boot[np.isfinite(boot)]
    tail = (1 - level) / 2
    lo, hi = np.quantile(boot, [tail, 1 - tail])
    blo, bhi = np.quantile(boot, [tail / m, 1 - tail / m])
    return {
        "value": point,
        "ci_low": float(lo),
        "ci_high": float(hi),
        "bonf_low": float(blo),
        "bonf_high": float(bhi),
        "n_worlds": int(n_w),
        "n_boot_finite": int(len(boot))
    }

def main():
    print("=== S4 Phase 1 Final: Pure NumPy Recomputation ===")
    prereg = json.loads((REPO / "reports/V9-S4-PHASE1/PREREG-r1.json").read_text(encoding="utf-8"))
    final_json = json.loads((REPO / "reports/V9-S4-PHASE1/final/final.json").read_text(encoding="utf-8"))
    final_res = final_json["result"]

    stats_cfg = prereg["statistics"]
    boot_cfg = stats_cfg["bootstrap"]
    n_boot = boot_cfg["n"]       # 10000
    boot_seed = boot_cfg["seed"] # 20261110
    boot_level = boot_cfg["level"] # 0.95
    m_bonf = stats_cfg["bonferroni_m"] # 7
    thresholds = prereg["gates"]

    print(f"Bootstrap config: n={n_boot}, seed={boot_seed}, level={boot_level}, bonferroni_m={m_bonf}")

    worlds_path = REPO / "artifacts/v9/s4/phase1/final-final/worlds.jsonl"
    records = [json.loads(line) for line in worlds_path.read_text(encoding="utf-8").splitlines()]
    main_r = [r for r in records if r["kind"] == "main"]
    extrap_r = [r for r in records if r["kind"] == "extrap"]
    print(f"Loaded records: {len(main_r)} main worlds, {len(extrap_r)} extrap worlds.")

    seeds = (1, 2, 3)

    def get_acc_sums(recs, arm, variant="base", collision=True):
        out = []
        for r in recs:
            mask = np.array([e[3] == 1 if collision else True for e in r["events"]], dtype=bool)
            if r["events"]:
                per = np.mean([np.asarray(r["reid"][f"{arm}#{s}@{variant}"], dtype=np.float64) for s in seeds], axis=0)
                out.append(float(per[mask].sum()) if len(per) else 0.0)
            else:
                out.append(0.0)
        return np.array(out, dtype=np.float64)

    def get_n_events(recs, collision=True):
        return np.array([float(sum(1 for e in recs[i]["events"] if (e[3] == 1 or not collision))) for i in range(len(recs))], dtype=np.float64)

    def get_dyn_world(recs, arm, field, is_learned=True):
        if not is_learned:
            return np.array([r["dyn"][arm][field] for r in recs], dtype=np.float64)
        return np.array([np.mean([r["dyn"][f"{arm}#{s}"][field] for s in seeds]) for r in recs], dtype=np.float64)

    # 1. Gates
    # HD: D_of(main, "L-int")
    hd = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-int", "coll"),
                                "b_coll": get_dyn_world(main_r, "E-B", "coll", False)},
                       n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    hd_pass = hd["value"] >= thresholds["HD"]["D"] and hd["ci_low"] > thresholds["HD"]["D_low"]

    # HF: HF_of(main, "L-int")
    hf = run_bootstrap(stat_HF, {
        "x_graze": get_dyn_world(main_r, "L-int", "graze"),
        "n_graze": get_dyn_world(main_r, "L-int", "n_graze"),
        "b_coll": get_dyn_world(main_r, "E-B", "coll", False),
        "n_coll": get_dyn_world(main_r, "E-B", "n_coll", False)
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    hf_pass = hf["value"] <= thresholds["HF"]["ratio"] and hf["ci_high"] <= thresholds["HF"]["ratio_high"]

    # HD-x: D_of(extrap, "L-int") & HF_of(extrap, "L-int")
    hdx_d = run_bootstrap(stat_D, {"x_coll": get_dyn_world(extrap_r, "L-int", "coll"),
                                  "b_coll": get_dyn_world(extrap_r, "E-B", "coll", False)},
                          n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    hdx_ratio = run_bootstrap(stat_HF, {
        "x_graze": get_dyn_world(extrap_r, "L-int", "graze"),
        "n_graze": get_dyn_world(extrap_r, "L-int", "n_graze"),
        "b_coll": get_dyn_world(extrap_r, "E-B", "coll", False),
        "n_coll": get_dyn_world(extrap_r, "E-B", "n_coll", False)
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    hdx_pass = (hdx_d["value"] >= thresholds["HD-x"]["D"] and hdx_d["ci_low"] > thresholds["HD-x"]["D_low"] and
                hdx_ratio["value"] <= thresholds["HD-x"]["ratio"])

    # H1: C_of(main, "L-int")
    h1 = run_bootstrap(stat_C, {
        "x": get_acc_sums(main_r, "L-int"),
        "b": get_acc_sums(main_r, "E-B"),
        "p": get_acc_sums(main_r, "E-P")
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    h1_pass = h1["value"] >= thresholds["H1"]["C"] and h1["ci_low"] > thresholds["H1"]["C_low"]

    # H2: diff_of(main, "L-int", "L-ind")
    h2 = run_bootstrap(stat_diff, {
        "x": get_acc_sums(main_r, "L-int"),
        "y": get_acc_sums(main_r, "L-ind"),
        "n": get_n_events(main_r)
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    h2_pass = h2["value"] >= thresholds["H2"]["diff"] and h2["ci_low"] > thresholds["H2"]["diff_low"]

    # H3: C_of(extrap, "L-int")
    h3 = run_bootstrap(stat_C, {
        "x": get_acc_sums(extrap_r, "L-int"),
        "b": get_acc_sums(extrap_r, "E-B"),
        "p": get_acc_sums(extrap_r, "E-P")
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    h3_pass = h3["value"] >= thresholds["H3"]["C"] and h3["ci_low"] > thresholds["H3"]["C_low"]

    # Negative control: D(L-ind) and C(L-ind)
    d_ind = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-ind", "coll"),
                                  "b_coll": get_dyn_world(main_r, "E-B", "coll", False)},
                          n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    c_ind = run_bootstrap(stat_C, {
        "x": get_acc_sums(main_r, "L-ind"),
        "b": get_acc_sums(main_r, "E-B"),
        "p": get_acc_sums(main_r, "E-P")
    }, n_boot=n_boot, seed=boot_seed, level=boot_level, m=m_bonf)
    neg_pass = (d_ind["ci_low"] < thresholds["negative_control"]["D_low_below"] and
                c_ind["ci_low"] < thresholds["negative_control"]["C_low_below"])

    # Legality
    # Floor
    floor_ecv = run_bootstrap(stat_diff, {"x": get_acc_sums(main_r, "E-CV"), "y": np.zeros(len(main_r)), "n": get_n_events(main_r)}, n_boot=1, seed=0, level=0.95, m=1)["value"]
    floor_eb = run_bootstrap(stat_diff, {"x": get_acc_sums(main_r, "E-B"), "y": np.zeros(len(main_r)), "n": get_n_events(main_r)}, n_boot=1, seed=0, level=0.95, m=1)["value"]
    floor_ep = run_bootstrap(stat_diff, {"x": get_acc_sums(main_r, "E-P"), "y": np.zeros(len(main_r)), "n": get_n_events(main_r)}, n_boot=1, seed=0, level=0.95, m=1)["value"]
    floor_pass = floor_ecv < floor_eb < floor_ep

    # Samples
    n_coll_events = int(get_n_events(main_r).sum())
    leg_cfg = prereg["legality"]
    expected_coll_events = leg_cfg["expected_collision_events_per_40"] * len(main_r) / 40 # 261 * 5 = 1305.0
    n_coll_steps = int(get_dyn_world(main_r, "E-B", "n_coll", False).sum())
    expected_dyn_steps = leg_cfg["expected_collision_disk_steps_per_40"] * len(main_r) / 40 # 552 * 5 = 2760.0
    samples_pass = (abs(n_coll_events - expected_coll_events) <= leg_cfg["sample_band"] * expected_coll_events and
                    n_coll_steps >= leg_cfg["dyn_floor"] * expected_dyn_steps)

    # Complete
    sizes = prereg["namespaces"] # registered sizes
    complete_pass = (len(main_r) == prereg["world"]["main"]["worlds"] and
                     len(extrap_r) == prereg["world"]["extrapolation"]["worlds"])

    # Bit-for-bit assertion table
    print("\n--- Gate Recomputation vs final.json ---")
    comparisons = [
        ("HD (D)", hd, final_res["gates"]["HD"]["D"], hd_pass, thresholds["HD"]),
        ("HF (ratio)", hf, final_res["gates"]["HF"]["ratio"], hf_pass, thresholds["HF"]),
        ("HD-x (D)", hdx_d, final_res["gates"]["HD-x"]["D"], hdx_pass, thresholds["HD-x"]),
        ("HD-x (ratio)", hdx_ratio, final_res["gates"]["HD-x"]["ratio"], hdx_pass, thresholds["HD-x"]),
        ("H1 (C)", h1, final_res["gates"]["H1"]["C"], h1_pass, thresholds["H1"]),
        ("H2 (diff)", h2, final_res["gates"]["H2"]["diff"], h2_pass, thresholds["H2"]),
        ("H3 (C)", h3, final_res["gates"]["H3"]["C"], h3_pass, thresholds["H3"]),
        ("NegCtrl D_L-ind", d_ind, final_res["negative_control"]["D_L-ind"], neg_pass, thresholds["negative_control"]),
        ("NegCtrl C_L-ind", c_ind, final_res["negative_control"]["C_L-ind"], neg_pass, thresholds["negative_control"])
    ]

    for name, calc, recorded, passed, th in comparisons:
        val_match = (calc["value"] == recorded["value"])
        lo_match = (calc["ci_low"] == recorded["ci_low"])
        hi_match = (calc["ci_high"] == recorded["ci_high"])
        blo_match = (calc["bonf_low"] == recorded["bonf_low"])
        bhi_match = (calc["bonf_high"] == recorded["bonf_high"])
        assert val_match and lo_match and hi_match and blo_match and bhi_match, f"Mismatch in {name}!"
        print(f"{name:16}: value={calc['value']:.6f}, 95%=[{calc['ci_low']:.6f}, {calc['ci_high']:.6f}], Bonf=[{calc['bonf_low']:.6f}, {calc['bonf_high']:.6f}] | Pass={passed} (Bit-for-bit MATCH)")

    print("\n--- Legality Recomputation vs final.json ---")
    print(f"Floor accuracies: E-CV={floor_ecv:.6f}, E-B={floor_eb:.6f}, E-P={floor_ep:.6f} | Monotonic={floor_pass}")
    assert floor_ecv == final_res["legality"]["floor"]["acc"]["E-CV"]
    assert floor_eb == final_res["legality"]["floor"]["acc"]["E-B"]
    assert floor_ep == final_res["legality"]["floor"]["acc"]["E-P"]

    print(f"Samples: collision_events={n_coll_events} (exp={expected_coll_events}), collision_disk_steps={n_coll_steps} (exp_floor={leg_cfg['dyn_floor']*expected_dyn_steps}) | Pass={samples_pass}")
    assert n_coll_events == final_res["legality"]["samples"]["collision_events"]
    assert expected_coll_events == final_res["legality"]["samples"]["expected"]
    assert n_coll_steps == final_res["legality"]["samples"]["collision_disk_steps"]
    assert expected_dyn_steps == final_res["legality"]["samples"]["dyn_expected"]

    print(f"Complete: main={len(main_r)}, extrap={len(extrap_r)} | Pass={complete_pass}")
    assert len(main_r) == final_res["legality"]["complete"]["main"]
    assert len(extrap_r) == final_res["legality"]["complete"]["extrap"]

    all_gates_pass = all(v["passed"] for v in final_res["gates"].values())
    print(f"\nALL 6 GATES PASS: {all_gates_pass}")
    print("=== PURE NUMPY RECOMPUTATION: 100% BIT-FOR-BIT IDENTICAL ===")

if __name__ == "__main__":
    main()
