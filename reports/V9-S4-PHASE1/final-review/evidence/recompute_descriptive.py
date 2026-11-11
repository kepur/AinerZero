#!/usr/bin/env python3
"""S4 Phase 1 Final Review: Descriptive Metrics Recomputation.
Recomputes 3 descriptive metrics from artifacts/v9/s4/phase1/final-final/worlds.jsonl:
1. Velocity Calibration NLL and 90% Coverage (main and extrap, all step kinds)
2. canonical_minus_plain (L-int-c vs L-int, full data and 1/8 data, D gap and acc_collision difference)
3. kstep_position_error (1, 5, 10, 30 step position errors for all process models)

Compares with reports/V9-S4-PHASE1/final/final.json descriptive block for bit-for-bit match.
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

def stat_diff(x, y, n, **_):
    return ratio(x - y, n)

def run_bootstrap(stat_fn, sums_dict, n_boot=10000, seed=20261110, level=0.95, m=1):
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
    print("=== S4 Phase 1 Final: Descriptive Metrics Recomputation ===")
    final_json = json.loads((REPO / "reports/V9-S4-PHASE1/final/final.json").read_text(encoding="utf-8"))
    exp_desc = final_json["descriptive"]

    worlds_path = REPO / "artifacts/v9/s4/phase1/final-final/worlds.jsonl"
    records = [json.loads(line) for line in worlds_path.read_text(encoding="utf-8").splitlines()]
    main_r = [r for r in records if r["kind"] == "main"]
    extrap_r = [r for r in records if r["kind"] == "extrap"]

    seeds = (1, 2, 3)

    # 1. Calibration
    CALIB_KINDS = ("collision", "graze", "free", "collision+graze")
    CALIB_NAMES = ("L-int-s", "constant", "binned", "oracle")

    def calc_calib(recs):
        parts = [p for r in recs for p in r["descriptive"]["calibration"].values()]
        out = {}
        for k in CALIB_KINDS:
            n = sum(p[k]["L-int-s"][2] for p in parts)
            out[k] = {"n": int(n)}
            for name in CALIB_NAMES:
                a = sum(p[k][name][0] for p in parts)
                b = sum(p[k][name][1] for p in parts)
                out[k][name] = {"nll": a / n if n else None, "cov90": b / n if n else None}
        return out

    recomp_calib = {"main": calc_calib(main_r), "extrap": calc_calib(extrap_r)}
    assert recomp_calib == exp_desc["calibration"], "Calibration mismatch!"
    print("1. Calibration: 100% bit-for-bit identical with final.json.")
    print("   Main collision:     L-int-s NLL = {:.4f}, cov90 = {:.4f} (n={})".format(
        recomp_calib["main"]["collision"]["L-int-s"]["nll"],
        recomp_calib["main"]["collision"]["L-int-s"]["cov90"],
        recomp_calib["main"]["collision"]["n"]))
    print("   Main graze:         L-int-s NLL = {:.4f}, cov90 = {:.4f} (n={})".format(
        recomp_calib["main"]["graze"]["L-int-s"]["nll"],
        recomp_calib["main"]["graze"]["L-int-s"]["cov90"],
        recomp_calib["main"]["graze"]["n"]))
    print("   Main free:          L-int-s NLL = {:.4f}, cov90 = {:.4f} (n={})".format(
        recomp_calib["main"]["free"]["L-int-s"]["nll"],
        recomp_calib["main"]["free"]["L-int-s"]["cov90"],
        recomp_calib["main"]["free"]["n"]))

    # 2. kstep_position_error
    ks = {}
    for r in main_r:
        for name, sums in r["descriptive"]["kstep"].items():
            arm = name.split("#")[0]
            for k, (s, n) in sums.items():
                acc = ks.setdefault(arm, {}).setdefault(k, [0.0, 0])
                acc[0] += s; acc[1] += n
    recomp_kstep = {a: {k: v[0] / v[1] for k, v in d.items()} for a, d in ks.items()}
    assert recomp_kstep == exp_desc["kstep_position_error"], "kstep mismatch!"
    print("\n2. kstep_position_error: 100% bit-for-bit identical with final.json.")
    for arm in ["E-B", "L-int", "L-int-c", "L-ind"]:
        print(f"   {arm:8}: 1-step={recomp_kstep[arm]['1']:.6f}, 5-step={recomp_kstep[arm]['5']:.6f}, 10-step={recomp_kstep[arm]['10']:.6f}, 30-step={recomp_kstep[arm]['30']:.6f}")

    # 3. canonical_minus_plain
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

    b_coll = get_dyn_world(main_r, "E-B", "coll", False)
    D_lint = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-int", "coll"), "b_coll": b_coll}, m=1)["value"]
    D_lint_c = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-int-c", "coll"), "b_coll": b_coll}, m=1)["value"]
    D_lint_e8 = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-int-e8", "coll"), "b_coll": b_coll}, m=1)["value"]
    D_lint_c_e8 = run_bootstrap(stat_D, {"x_coll": get_dyn_world(main_r, "L-int-c-e8", "coll"), "b_coll": b_coll}, m=1)["value"]

    gap_plain = D_lint_c - D_lint
    gap_e8 = D_lint_c_e8 - D_lint_e8

    diff_plain = run_bootstrap(stat_diff, {"x": get_acc_sums(main_r, "L-int-c"), "y": get_acc_sums(main_r, "L-int"), "n": get_n_events(main_r)}, m=1)
    diff_e8 = run_bootstrap(stat_diff, {"x": get_acc_sums(main_r, "L-int-c-e8"), "y": get_acc_sums(main_r, "L-int-e8"), "n": get_n_events(main_r)}, m=1)

    recomp_cmp = {
        "": {"D": gap_plain, "acc_collision": diff_plain},
        "-e8": {"D": gap_e8, "acc_collision": diff_e8}
    }

    assert recomp_cmp == exp_desc["canonical_minus_plain"], "canonical_minus_plain mismatch!"
    print("\n3. canonical_minus_plain: 100% bit-for-bit identical with final.json.")
    print("   Full data: ΔD = {:.6f}, Δacc_collision = {:.6f} [{:.6f}, {:.6f}]".format(
        gap_plain, diff_plain["value"], diff_plain["ci_low"], diff_plain["ci_high"]))
    print("   1/8 data:  ΔD = {:.6f}, Δacc_collision = {:.6f} [{:.6f}, {:.6f}]".format(
        gap_e8, diff_e8["value"], diff_e8["ci_low"], diff_e8["ci_high"]))

    print("\n=== ALL DESCRIPTIVE SPOT-CHECKS PASSED 100% ===")

if __name__ == "__main__":
    main()
