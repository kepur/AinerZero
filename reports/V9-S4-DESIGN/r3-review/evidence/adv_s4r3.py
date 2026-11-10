"""S4 第一阶段 r3 的对抗检查（复核者自写，不改被审文件）。只用 NumPy，不训练，不导入 MLX。只用 s4x-explore。

HF：提前触发的距离余量 δ 从 0.05 到 0.9（2R + 0.9 = 1.5，正是 L-int 的消息半径）。每个 δ 量：
    D（碰撞步）；HF 擦边集（本步末距离 < 2R + 0.3、无接触）的误差与比值；
    交互半径集（本步开始时与另一盘距离 < 1.5、本步无接触）的误差；自由步（既不碰撞也不擦边）的误差。
HC：与 explore4.velocity_nll 同一套数据（世界 2000+，种子 0，可见轨迹噪声），三种基线：
    const_all  在 train 半的全部步上拟合常数 σ（作者的基线）；
    const_sub  在 train 半的碰撞 + 擦边步上拟合常数 σ（与评测同类步）；
    binned     作者的「先知」：按当前带噪输入里与最近盘的距离分 8 箱（学生可见，不是先知）；
    two_bins   只分两箱：最近距离 < 0.8 与否。
用法：adv_s4r3.py <副本根> <输出 json>
"""
import json, math, sys, time
import numpy as np

COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src")
sys.path.insert(0, COPY + "/reports/V9-S4-DESIGN/tier1-explore")
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
import explore4 as X4  # noqa: E402

NS = "s4x-explore"
assert X4.NS == NS
T0 = time.monotonic()
R2 = 2 * W.RADIUS
res = {"HF": {}, "HC": {}}


def boot_mean_ratio(num_w, den_w, B=4000, seed=20261110):
    a, b = np.array(num_w), np.array(den_w)
    idx = np.random.default_rng(seed).integers(0, len(a), size=(B, len(a)))
    r = a[idx].sum(1) / b[idx].sum(1)
    return float(a.sum() / b.sum()), float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


DELTAS = (0.05, 0.15, 0.3, 0.5, 0.7, 0.9)
for nd in (6, 10):
    acc = {}
    errB_coll_w = np.zeros(40); n_coll_w = np.zeros(40)
    per = {d: {k: np.zeros(40) for k in ("coll", "graze", "radius", "free", "radius_gt", "free_gt")} for d in DELTAS}
    cnt = {k: np.zeros(40) for k in ("coll", "graze", "radius", "free")}
    for w in range(40):
        ep = W.generate_episode(NS, 1000 + w, nd)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(nd) * 99
            d0 = np.linalg.norm(s.positions[:, None] - s.positions[None], axis=-1) + np.eye(nd) * 99
            graze = {i for i in range(nd) if dn[i].min() < R2 + X4.GRAZE} - coll
            radius = {i for i in range(nd) if d0[i].min() < 1.5} - coll
            free = set(range(nd)) - coll - graze
            p0, v0 = s.positions[None], s.velocities[None]
            eB = np.linalg.norm(W.physics(p0, v0, ep.pillars, disks=False)[1][0] - nxt.velocities, axis=1)
            errB_coll_w[w] += eB[sorted(coll)].sum(); n_coll_w[w] += len(coll)
            for k, sset in (("coll", coll), ("graze", graze), ("radius", radius), ("free", free)):
                cnt[k][w] += len(sset)
            for d in DELTAS:
                vv = X4.early_physics(p0, v0, ep.pillars, d)[1]
                e = np.linalg.norm(vv[0] - nxt.velocities, axis=1)
                for k, sset in (("coll", coll), ("graze", graze), ("radius", radius), ("free", free)):
                    per[d][k][w] += e[sorted(sset)].sum()
                per[d]["radius_gt"][w] += int((e[sorted(radius)] > 0.1).sum()); per[d]["free_gt"][w] += int((e[sorted(free)] > 0.1).sum())
    eb = errB_coll_w.sum() / n_coll_w.sum()
    out = {"err_B_collision": round(eb, 4), "counts": {k: int(v.sum()) for k, v in cnt.items()}}
    for d in DELTAS:
        D, Dlo, Dhi = boot_mean_ratio(per[d]["coll"], errB_coll_w)
        g, glo, ghi = boot_mean_ratio(per[d]["graze"], cnt["graze"])
        out[f"delta_{d}"] = {"D": round(1 - D, 4), "D_lo": round(1 - Dhi, 4), "D_hi": round(1 - Dlo, 4),
                             "HF_ratio": round(g / eb, 4), "HF_ratio_hi": round(ghi / eb, 4),
                             "passes_HD": bool(1 - D >= 0.8 and 1 - Dhi > 0.7), "passes_HF": bool(g / eb <= 0.1 and ghi / eb <= 0.15),
                             "radius_set_mean_err": round(per[d]["radius"].sum() / cnt["radius"].sum(), 4),
                             "radius_set_frac_gt_0.1": round(per[d]["radius_gt"].sum() / cnt["radius"].sum(), 4),
                             "free_set_mean_err": round(per[d]["free"].sum() / cnt["free"].sum(), 4),
                             "free_set_frac_gt_0.1": round(per[d]["free_gt"].sum() / cnt["free"].sum(), 4)}
    res["HF"][nd] = out
    print("HF", nd, json.dumps(out), flush=True)

# ---------------- HC ----------------
for nd in (6, 10):
    rng = np.random.default_rng(0)
    rows = []
    for w in range(40):
        ep = W.generate_episode(NS, 2000 + w, nd)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            p0 = s.positions + rng.normal(0, 0.05, s.positions.shape); v0 = s.velocities + rng.normal(0, 0.2, s.velocities.shape)
            _, vv, _ = W.physics(p0[None], v0[None], ep.pillars)
            r = vv[0] - nxt.velocities
            d0 = np.linalg.norm(p0[:, None] - p0[None], axis=-1) + np.eye(nd) * 99
            dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(nd) * 99
            for i in range(nd):
                kind = "coll" if i in coll else ("graze" if dn[i].min() < R2 + X4.GRAZE else "free")
                rows.append((w, d0[i].min(), r[i, 0] ** 2 + r[i, 1] ** 2, kind))
    wid = np.array([x[0] for x in rows]); dmin = np.array([x[1] for x in rows]); se = np.array([x[2] for x in rows]); kind = np.array([x[3] for x in rows])
    half = len(rows) // 2
    tr = np.zeros(len(rows), bool); tr[:half] = True
    sub = (kind == "coll") | (kind == "graze")
    nll = lambda s2, e: np.log(2 * math.pi * s2) + e / (2 * s2)
    s2_all = se[tr].mean() / 2
    s2_sub = se[tr & sub].mean() / 2
    bins8 = np.array([0, 0.6, 0.65, 0.7, 0.8, 1.0, 1.3, 2.0, 99])
    def binned(bins):
        idx = np.clip(np.digitize(dmin, bins) - 1, 0, len(bins) - 2)
        s2 = np.array([se[tr & (idx == b)].mean() / 2 if (tr & (idx == b)).any() else s2_all for b in range(len(bins) - 1)])
        return s2[idx]
    s2_b8 = binned(bins8); s2_b2 = binned(np.array([0, 0.8, 99]))
    ev = ~tr & sub
    base = nll(s2_all, se[ev])
    cands = {"const_sub": nll(s2_sub, se[ev]), "binned_8": nll(s2_b8[ev], se[ev]), "two_bins": nll(s2_b2[ev], se[ev])}
    ws = sorted(set(wid[ev].tolist())); wi = {w: i for i, w in enumerate(ws)}
    def gain_ci(a, b):
        d = a - b; s = np.zeros(len(ws)); n = np.zeros(len(ws))
        np.add.at(s, [wi[x] for x in wid[ev]], d); np.add.at(n, [wi[x] for x in wid[ev]], 1)
        idx = np.random.default_rng(20261110).integers(0, len(ws), size=(4000, len(ws)))
        g = s[idx].sum(1) / n[idx].sum(1)
        return round(float(d.mean()), 4), round(float(np.percentile(g, 2.5)), 4), round(float(np.percentile(g, 97.5)), 4)
    out = {"n_eval": int(ev.sum()), "eval_worlds": len(ws), "sigma_all": round(math.sqrt(s2_all), 4), "sigma_sub": round(math.sqrt(s2_sub), 4),
           "gain_vs_const_all": {k: gain_ci(base, v) for k, v in cands.items()},
           "gain_vs_const_sub": {k: gain_ci(cands["const_sub"], v) for k, v in cands.items() if k != "const_sub"},
           "cov90": {k: round(float((se[ev] <= -2 * (s2 if np.ndim(s2) == 0 else s2[ev]) * math.log(0.1)).mean()), 4)
                     for k, s2 in (("const_all", s2_all), ("const_sub", s2_sub), ("binned_8", s2_b8), ("two_bins", s2_b2))}}
    res["HC"][nd] = out
    print("HC", nd, json.dumps(out), flush=True)
res["seconds"] = round(time.monotonic() - T0, 1)
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", res["seconds"], flush=True)
