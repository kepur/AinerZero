"""第 4 项：用合成记录找「缺数据默认通过」路径。复用副本里测试的 _synthetic；BOOT_N 降到 500 只为快。"""
import copy, json, sys, traceback
import numpy as np
COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src"); sys.path.insert(0, COPY + "/tests/v9/experiments")
from ainerzero.v9.experiments.s4 import analysis as A, metrics as Me
assert A.__file__.startswith(COPY)
import test_s4_analysis as T
Me.BOOT_N = 500
def run(main, extrap, **kw):
    args = dict(n_main=len(main), labels_ok=True, student_ok=True, replay_ok=True) | kw
    try:
        r = A.evaluate(main, extrap, **args)
        return {"valid": r["valid"], "neg": r["negative_control"]["passed"], "gates": {k: v["passed"] for k, v in r["gates"].items()},
                "legality": {k: v["passed"] for k, v in r["legality"].items()}}
    except Exception as e:
        return {"raised": f"{type(e).__name__}: {e}"[:200]}
good = lambda seed=0, n=40, **o: T._synthetic(n, T.GOOD_ACC | o.get("acc", {}), T.GOOD_DYN | o.get("dyn", {}), events_per_world=13, coll_share=0.5, seed=seed)
ext = lambda **o: T._synthetic(20, T.GOOD_ACC | o.get("acc", {}), T.GOOD_DYN | o.get("dyn", {}), seed=1)
R = {}
R["a_good"] = run(good(), ext())
R["b_extrap_empty"] = run(good(), [])
m = good(); [r["reid"].pop(k) for r in m for k in list(r["reid"]) if k.startswith("L-ind")]
R["c_main_no_L-ind_reid"] = run(m, ext())
m = good(); [r["dyn"].__setitem__(k, dict(r["dyn"][k], coll=float("nan"))) for r in m for k in list(r["dyn"]) if k.startswith("L-ind")]
R["d_L-ind_dyn_nan"] = run(m, ext())
R["e_EP_equals_EB_acc"] = run(good(acc={"E-P": 0.4}), ext())
# f: 分母 p - b 在一部分世界里为负（E-P 比 E-B 差），总体仍为正：上轮应修 4 的触发
m = good()
T._set_reid(m[:12], "E-P", [0] * 12); T._set_reid(m[:12], "E-B", [1] * 12); T._set_reid(m[:12], "L-int", [1] * 12)
for r in m[:12]:
    for s in A.SEEDS:
        for v in A.variants():
            if v != "base":
                continue
R["f_denominator_sign_flips"] = run(m, ext())
from ainerzero.v9.experiments.s4 import metrics as Mx
x, b, p = A.acc_sums(m, "L-int"), A.acc_sums(m, "E-B"), A.acc_sums(m, "E-P")
idx = np.random.default_rng(0).integers(0, len(m), (2000, len(m)))
den = (p[idx] - b[idx]).sum(1)
R["f_denominator_sign_flips"]["share_resamples_den_le_0"] = float((den <= 0).mean())
R["f_denominator_sign_flips"]["C_L-int"] = {k: v for k, v in A.C_of(m, "L-int").items() if k in ("value", "ci_low", "ci_high")}
R["g_labels_false"] = run(good(), ext(), labels_ok=False)
R["g2_replay_false"] = run(good(), ext(), replay_ok=False)
R["h_drop_20pct_worlds_n_main_registered"] = run(good()[:32], ext(), n_main=40)
R["h2_drop_50pct_worlds"] = run(good()[:20], ext(), n_main=40)
m = good(); [r["dyn"].__setitem__(k, dict(r["dyn"][k], n_graze=0, graze=0.0)) for r in m for k in list(r["dyn"]) if k.startswith("L-int")]
R["i_no_graze_steps"] = run(m, ext())
m = good(); [r.__setitem__("events", []) or [r["reid"].__setitem__(k, []) for k in r["reid"]] for r in m]
R["j_no_events"] = run(m, ext())
m = good(); [r["dyn"].__setitem__(k, dict(r["dyn"][k], coll=0.0)) for r in m for k in list(r["dyn"]) if k == "E-B" or k.startswith("L-int")]
R["k_EB_coll_zero"] = run(m, ext())
m = good(); [r["dyn"].__setitem__(k, dict(r["dyn"][k], coll=float("inf"))) for r in m[:1] for k in list(r["dyn"]) if k.startswith("L-int")]
R["l_one_world_inf"] = run(m, ext())
R["m_neg_control_good_Lind"] = run(good(acc={"L-ind": 0.75}, dyn={"L-ind": (0.1, 0.03)}), ext())
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1); print(json.dumps(R, ensure_ascii=False, indent=0))
