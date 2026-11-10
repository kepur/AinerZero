"""as_pad_small 与 fi_gate_strict 是否等价：在隔离副本上逐一比较原版与变异版。"""
import itertools, json, sys, types
import numpy as np
COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src")
from ainerzero.v9.experiments.s4 import assign as A, filter as F, world as W
assert A.__file__.startswith(COPY)
src = open(A.__file__).read(); assert src.count("cost.max() + 1.0") == 1
mut = types.ModuleType("assign_mut"); exec(compile(src.replace("cost.max() + 1.0", "0.0"), "assign_mut", "exec"), mut.__dict__)
rng = np.random.default_rng(20261110)
res = {"random": 0, "diff_pairs": 0, "diff_cost": 0, "brute_checked": 0, "brute_wrong_orig": 0, "brute_wrong_mut": 0, "ties": {"n": 0, "diff_pairs": 0}}
for _ in range(20000):
    nr, nc = (int(x) for x in rng.integers(1, 9, 2))
    c = rng.uniform(0, 5, (nr, nc)) * rng.choice([1e-3, 1, 1e3])
    a, b = sorted(A.hungarian(c)), sorted(mut.hungarian(c)); res["random"] += 1
    if a != b:
        res["diff_pairs"] += 1
        if abs(sum(c[i, j] for i, j in a) - sum(c[i, j] for i, j in b)) > 1e-9: res["diff_cost"] += 1
    if nr <= 6 and nc <= 6 and res["brute_checked"] < 3000:
        # 穷举：对较小一侧的每个元素枚举另一侧的选择
        if nr <= nc: best = min(sum(c[i, p[i]] for i in range(nr)) for p in itertools.permutations(range(nc), nr))
        else: best = min(sum(c[p[j], j] for j in range(nc)) for p in itertools.permutations(range(nr), nc))
        res["brute_checked"] += 1
        res["brute_wrong_orig"] += int(abs(sum(c[i, j] for i, j in a) - best) > 1e-9 * max(1, best))
        res["brute_wrong_mut"] += int(abs(sum(c[i, j] for i, j in b) - best) > 1e-9 * max(1, best))
# 有平局的整数矩阵：平局时哪组配对被选中可能不同（总代价相同）
for _ in range(5000):
    nr, nc = (int(x) for x in rng.integers(1, 7, 2)); c = rng.integers(0, 3, (nr, nc)).astype(float)
    a, b = sorted(A.hungarian(c)), sorted(mut.hungarian(c)); res["ties"]["n"] += 1; res["ties"]["diff_pairs"] += int(a != b)
# fi_gate_strict：门边界上恰好相等的距离。构造 dist == gate_base + gate_grow*DT*(t-last)
cfg = F.FilterConfig(); g = cfg.gate_base + cfg.gate_grow * W.DT * 3
P = np.zeros((cfg.members, 1, 2)); z = np.array([[g, 0.0]]); last = np.array([7]); t = 10
d = float(np.linalg.norm(z[0] - P.mean(0)[0]))
res["gate_boundary"] = {"gate": g, "dist": d, "dist_equals_gate": d == cfg.gate_base + cfg.gate_grow * W.DT * (t - last[0]),
                        "orig_associates": F._associate(P, z, last, t, cfg)}
fsrc = open(F.__file__).read(); old = "if dist[r, c] <= cfg.gate_base"; assert fsrc.count(old) == 1
fm = types.ModuleType("filter_mut"); sys.modules["filter_mut"] = fm
exec(compile(fsrc.replace(old, "if dist[r, c] < cfg.gate_base").replace("from . import", "from ainerzero.v9.experiments.s4 import").replace("from .", "from ainerzero.v9.experiments.s4."), "filter_mut", "exec"), fm.__dict__)
res["gate_boundary"]["mut_associates"] = fm._associate(P, z, last, t, fm.FilterConfig())
# 实际评测里距离恰等于门的频率：在 s4x-explore 的 20 个世界上用 E-P 跑滤波器，统计 |dist - gate| < 1e-12 的次数
import ainerzero.v9.experiments.s4.models as Mo
cnt = {"pairs": 0, "exact_ties": 0, "within_1e-9": 0}
orig_assoc = F._associate
def spy(P_, z_, last_, t_, cfg_):
    if P_.shape[1] and len(z_):
        mu = P_.mean(0); dd = np.linalg.norm(z_[:, None] - mu[None], axis=-1)
        for r, c in A.hungarian(dd):
            gg = cfg_.gate_base + cfg_.gate_grow * W.DT * (t_ - last_[c]); cnt["pairs"] += 1
            cnt["exact_ties"] += int(dd[r, c] == gg); cnt["within_1e-9"] += int(abs(dd[r, c] - gg) < 1e-9)
    return orig_assoc(P_, z_, last_, t_, cfg_)
F._associate = spy
for w in range(20):
    ep = W.generate_episode("s4x-explore", w, 6)
    F.track([s.detections for s in ep.steps], ep.pillars, Mo.HAND_MODELS["E-P"], np.random.default_rng(w))
res["gate_ties_in_tracking"] = cnt
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1, default=str); print(json.dumps(res, default=str))
