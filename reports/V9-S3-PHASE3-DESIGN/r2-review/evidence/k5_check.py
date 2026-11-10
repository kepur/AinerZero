"""复算 r2 的 K5 带宽：用 r1 复核的每世界波动（k5_band.json），计入预期数自身的估计误差，求 4 倍标准差，以及误判失败与检出概率（正态近似）。"""
import json, math, sys
b = json.load(open(sys.argv[1])); band = {"fast": 0.07, "decoy_stable": 0.13, "relocated": 0.21}
def phi(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))
out = {}
for k, exp, sd in zip(b["keys"], b["expected_200"], b["sd_200"]):
    sd_diff = math.sqrt(2) * sd  # final 的波动 + 由 200 个世界估出的预期数的误差
    rel = sd_diff / exp
    w = band[k]
    out[k] = {"sd_diff_rel": round(rel, 4), "four_sd": round(4 * rel, 4), "registered_band": w, "band_in_sd": round(w / rel, 2),
              "p_false_fail": 2 * (1 - phi(w / rel)),
              **{f"p_detect_loss_{int(l*100)}": round(phi((l - w) / rel), 4) for l in (0.05, 0.10, 0.15, 0.20, 0.25)},
              "five_pct_in_sd": round(0.05 / rel, 2)}
out["p_false_fail_any"] = 1 - math.prod(1 - v["p_false_fail"] for v in out.values() if isinstance(v, dict))
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1); print(json.dumps(out, ensure_ascii=False))
