"""第 1 项的纯 CPU 触发：上轮应修 1（学生视角检查）与应修 4（自助法分母变号）。
student_check 从副本的 run_s4p1.py 用 ast 抽出原样执行；L 用桩代替（as_process_model 返回 E-P），不导入 MLX。"""
import ast, json, sys, types
import numpy as np
COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src"); sys.path.insert(0, COPY + "/tests/v9/experiments")
from ainerzero.v9.experiments.s4 import analysis as A, filter as F, metrics as Me, models as Mo, world as W
assert A.__file__.startswith(COPY) and "mlx" not in sys.modules
src = open(COPY + "/reports/V9-S4-PHASE1/run_s4p1.py").read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "student_check")
ns = {"W": W, "A": A, "F": F, "Mo": Mo, "np": np, "STUDENT_WORLDS": 2, "STUDENT_CUT": 150,
      "L": types.SimpleNamespace(as_process_model=lambda net: Mo.true_physics)}
exec(compile(ast.Module([fn], []), "student_check", "exec"), ns)
check = ns["student_check"]
eps = [W.generate_episode("s4x-explore", w, 6) for w in (0, 1)]
R = {"student": {}}
R["student"]["honest"] = {k: v for k, v in check(eps, {"L-int#1": None}).items() if k != "rows"}
real_track = F.track
def lookahead(dets, pillars, model, rng, cfg=F.FilterConfig(), **kw):
    """读下一步的检测：在每步末尾追加下一步检测的均值作为一个额外的「检测」，再删掉它对应的 id。"""
    aug = [np.concatenate([d, dets[t + 1][:1]]) if t + 1 < len(dets) and len(dets[t + 1]) else d for t, d in enumerate(dets)]
    ids, n = real_track(aug, pillars, model, rng, cfg, **kw)
    return [i[: len(d)] for i, d in zip(ids, dets)], n
def ignores_input(dets, pillars, model, rng, cfg=F.FilterConfig(), **kw):
    """只读第一次调用时的检测（模拟从别处取观测、不读传进来的列表）。"""
    if not hasattr(ignores_input, "first"):
        ignores_input.first = [d.copy() for d in dets]
    src_ = ignores_input.first
    ids, n = real_track(src_, pillars, model, rng, cfg, **kw)
    return [i[: len(d)] if len(i) >= len(d) else np.concatenate([i, -np.ones(len(d) - len(i), int)]) for i, d in zip(ids, dets)], n
for name, f in (("lookahead_tracker", lookahead), ("tracker_ignores_input", ignores_input)):
    F.track = f
    if hasattr(ignores_input, "first"): del ignores_input.first
    out = check(eps, {"L-int#1": None})
    R["student"][name] = {"passed": out["passed"], "rows": out["rows"]}
F.track = real_track
# 白名单：给学生视角加一个字段，A.student_detections 必须拒绝
orig_sv = W.student_view
W.student_view = lambda s: dict(orig_sv(s), truth_ids=s.truth_ids)
try:
    A.student_detections(eps[0]); R["student"]["extra_field"] = "NOT refused"
except RuntimeError as e:
    R["student"]["extra_field"] = f"refused: {e}"
W.student_view = orig_sv
# 应修 4：分母 p − b 的点估计为正、地板门通过，但有一部分重采样里 ≤ 0
import test_s4_analysis as T
Me.BOOT_N = 2000
best = None
for ep_acc in (0.43, 0.44, 0.45, 0.47, 0.5):
    for seed in range(6):
        m = T._synthetic(40, T.GOOD_ACC | {"E-P": ep_acc, "L-int": ep_acc - 0.01}, T.GOOD_DYN, events_per_world=13, coll_share=0.5, seed=seed)
        b, p = A.acc_sums(m, "E-B"), A.acc_sums(m, "E-P")
        idx = np.random.default_rng(Me.BOOT_SEED).integers(0, 40, (Me.BOOT_N, 40))
        share = float(((p[idx] - b[idx]).sum(1) <= 0).mean())
        if 0 < share < 0.5:
            lg = A.legality(m, n_main=40, labels_ok=True, student_ok=True, replay_ok=True)
            if lg["floor"]["passed"]:
                c = A.C_of(m, "L-int")
                best = {"E-P_acc": ep_acc, "seed": seed, "share_den_le_0": share, "floor_passed": True, "C": {k: c.get(k) for k in ("value", "ci_low", "ci_high")}}
                break
    if best: break
R["bootstrap_sign_flip"] = best
# 直接对 metrics.bootstrap：一个重采样分母为 0 → 整体无区间
x = np.array([1.0, 1.0, 1.0]); b0 = np.array([0.0, 0.0, 0.0]); p0 = np.array([1.0, 0.0, -1.0])
R["bootstrap_direct"] = {k: v for k, v in Me.bootstrap(Me.stat_C, {"x": x, "b": b0, "p": p0}, m=1).items() if k in ("value", "ci_low", "ci_high")}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: (v if k != "student" else {a: {kk: vv for kk, vv in b.items() if kk != "rows"} if isinstance(b, dict) else b for a, b in v.items()}) for k, v in R.items()}, ensure_ascii=False, default=str))
for name in ("lookahead_tracker", "tracker_ignores_input"):
    print(name, [{k: r[k] for k in ("model", "prefix_equal", "consumed", "suffix_changed")} for r in R["student"][name]["rows"]])
