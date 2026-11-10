"""S4 第一阶段 r2 的对抗检查（复核者自写，不改被审文件）。只用 NumPy，不训练，不导入 MLX。只用 s4x-explore。

A 世界模块与 explore2 逐世界比对（位置、速度、可见、检测、盘盘接触）。
B HD 的代用模型（从精确真值出发一步，碰撞步当事盘的速度误差）：
   过度触发（距离 < 2R + δ 且相向就交换法向速度）、冲量打折（×(1−ε)）、整速度交换、只懂 75%；
   另量「擦过未碰」步（本步末两盘距离 < 2R + 0.3，但接触日志没有这一对）上的速度误差，HD 不看这些步。
C HC：均值取真实物理在带噪输入上的输出（完美的 L-int），σ 取常数，看 90% 区域覆盖率。
用法：adv_s4r2.py <副本根> <输出 json>
"""
import collections, json, math, sys, time
import numpy as np

COPY, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, COPY + "/src")
sys.path.insert(0, COPY + "/reports/V9-S4-DESIGN/tier1-explore")
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
import explore2 as X2  # noqa: E402
import explore3 as X3  # noqa: E402

NS = "s4x-explore"
assert X2.NS == NS and X3.NS == NS
T0 = time.monotonic()
R2 = 2 * W.RADIUS
res = {}

# ---------- A：世界模块 = explore2 ----------
eq = collections.Counter()
for nd in (6, 10):
    for w in range(40):
        pil, states, vis, dets, contacts = X2.episode(w, n_disks=nd, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0)
        ep = W.generate_episode(NS, w, nd)
        ok = tuple(pil) == ep.pillars
        for t, s in enumerate(ep.steps):
            ok &= np.array_equal(states[t][0], s.positions) and np.array_equal(states[t][1], s.velocities) and np.array_equal(vis[t], s.visible)
            ok &= [i for i, _ in dets[t]] == s.truth_ids.tolist() and np.array_equal(np.array([q for _, q in dets[t]]).reshape(-1, 2), s.detections)
            ok &= contacts[t] == {(i, j) for kind, i, j in s.contacts if kind == "disk"}
        eq[f"{nd}_identical"] += int(ok); eq[f"{nd}_worlds"] += 1
res["A_world_equals_explore2"] = dict(eq)
print("A", dict(eq), flush=True)


# ---------- B：HD 的代用模型 ----------
def variant(p, v, pillars, *, delta=0.0, scale=1.0, swap=False):
    """真实物理的变体：盘盘碰撞在距离 < 2R + delta 时触发；冲量乘 scale；swap 时整速度交换。"""
    p, v = p.copy(), v.copy()
    h = W.DT / W.SUBSTEPS
    for _ in range(W.SUBSTEPS):
        p += v * h
        for d in range(2):
            lo, hi = p[..., d] < W.RADIUS, p[..., d] > W.ARENA - W.RADIUS
            v[..., d] = np.where(lo, np.abs(v[..., d]), np.where(hi, -np.abs(v[..., d]), v[..., d]))
            p[..., d] = np.clip(p[..., d], W.RADIUS, W.ARENA - W.RADIUS)
        for cx, cy, cr in pillars:
            c = np.array([cx, cy]); dvec = p - c; dist = np.linalg.norm(dvec, axis=-1, keepdims=True); nrm = dvec / np.maximum(dist, 1e-9)
            hit = dist < cr + W.RADIUS; vn = (v * nrm).sum(-1, keepdims=True)
            v = np.where(hit & (vn < 0), v - 2 * vn * nrm, v); p = np.where(hit, c + nrm * (cr + W.RADIUS), p)
        n = p.shape[1]
        d = p[:, None] - p[:, :, None]; dist = np.linalg.norm(d, axis=-1); nrm = d / np.maximum(dist, 1e-9)[..., None]
        rel = ((v[:, :, None] - v[:, None]) * nrm).sum(-1)
        upper = np.triu(np.ones((n, n), bool), 1)[None]
        trig = upper & (dist < R2 + delta) & (dist > 1e-9) & (rel > 0)
        if swap:
            for i, j in zip(*np.nonzero(trig[0])):
                v[0, i], v[0, j] = v[0, j].copy(), v[0, i].copy()
        else:
            dv = np.where(trig[..., None], scale * rel[..., None] * nrm, 0.0)
            v = v - dv.sum(2) + dv.sum(1)
        ok = upper & (dist < R2) & (dist > 1e-9)
        push = np.where(ok, R2 - dist, 0.0)[..., None] * nrm / 2
        p = p - push.sum(2) + push.sum(1)
    return p, v


MODELS = {
    "E-B": lambda p, v, pil, rng: W.physics(p, v, pil, disks=False)[:2],
    "E-P": lambda p, v, pil, rng: W.physics(p, v, pil)[:2],
    "p75": lambda p, v, pil, rng: X3.partial_physics(p, v, pil, 0.75, rng),
    "early_0.15": lambda p, v, pil, rng: variant(p, v, pil, delta=0.15),
    "early_0.30": lambda p, v, pil, rng: variant(p, v, pil, delta=0.30),
    "impulse_x0.8": lambda p, v, pil, rng: variant(p, v, pil, scale=0.8),
    "impulse_x0.6": lambda p, v, pil, rng: variant(p, v, pil, scale=0.6),
    "swap_full_velocity": lambda p, v, pil, rng: variant(p, v, pil, swap=True),
}


def boot_ratio(per_world_num, per_world_den, B=4000, seed=20261110):
    """D = 1 − Σerr_X / Σerr_B，按世界重采样。"""
    a, b = np.array(per_world_num), np.array(per_world_den)
    idx = np.random.default_rng(seed).integers(0, len(a), size=(B, len(a)))
    d = 1 - a[idx].sum(1) / b[idx].sum(1)
    return round(float(1 - a.sum() / b.sum()), 4), round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)


B = {}
for nd in (6, 10):
    rng = np.random.default_rng(0)
    coll = {m: collections.defaultdict(float) for m in MODELS}; collB = collections.defaultdict(float)
    near = {m: [] for m in MODELS}; n_coll = n_near = 0
    for w in range(40):
        ep = W.generate_episode(NS, 1000 + w, nd)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            pairs = {(i, j) for kind, i, j in s.contacts if kind == "disk"}
            inv = sorted({i for p_ in pairs for i in p_})
            dd = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1)
            nm = sorted({i for i in range(nd) for j in range(nd) if i < j and dd[i, j] < R2 + 0.3 and (i, j) not in pairs and i not in inv and j not in inv}
                        | {j for i in range(nd) for j in range(nd) if i < j and dd[i, j] < R2 + 0.3 and (i, j) not in pairs and i not in inv and j not in inv})
            p0, v0 = s.positions[None], s.velocities[None]
            for m, f in MODELS.items():
                pp, vv = f(p0, v0, ep.pillars, rng)
                e = np.linalg.norm(vv[0] - nxt.velocities, axis=1)
                if inv:
                    coll[m][w] += float(e[inv].sum())
                if nm:
                    near[m] += e[nm].tolist()
            n_coll += len(inv); n_near += len(nm)
    ws = list(range(40))
    B[nd] = {"collision_disk_steps": n_coll, "near_miss_disk_steps": n_near}
    for m in MODELS:
        Dpt, lo, hi = boot_ratio([coll[m][w] for w in ws], [coll["E-B"][w] for w in ws])
        B[nd][m] = {"D": Dpt, "D_lo": lo, "D_hi": hi, "near_miss_vel_err_mean": round(float(np.mean(near[m])), 4) if near[m] else None,
                    "near_miss_err_frac_gt_0.1": round(float(np.mean(np.array(near[m]) > 0.1)), 4) if near[m] else None}
    print("B", nd, json.dumps(B[nd]), flush=True)
res["B_HD_standins"] = B

# ---------- C：HC 用常数 σ ----------
CHI2_90 = 4.605  # 2 自由度
C = {}
for nd in (6, 10):
    rng = np.random.default_rng(1)
    rows = {"fit": [], "test": [], "test_collision": [], "test_hidden_noise": []}
    for w in range(40):
        ep = W.generate_episode(NS, 1000 + w, nd)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            inv = sorted({i for kind, i, j in s.contacts if kind == "disk"} | {j for kind, i, j in s.contacts if kind == "disk"})
            for tag, (sp, sv) in (("vis", (0.05, 0.2)), ("hid", (0.7, 0.6))):
                if tag == "hid" and s.t % 5:
                    continue
                p0 = s.positions + rng.normal(0, sp, s.positions.shape); v0 = s.velocities + rng.normal(0, sv, s.velocities.shape)
                pp, _ = W.physics(p0[None], v0[None], ep.pillars)[:2]
                r = nxt.positions - pp[0]
                if tag == "hid":
                    rows["test_hidden_noise"] += r.tolist(); continue
                (rows["fit"] if w < 20 else rows["test"]).extend(r.tolist())
                if w >= 20 and inv:
                    rows["test_collision"] += r[inv].tolist()
    fit = np.array(rows["fit"]); sig = fit.std(0)
    cov = lambda r: round(float(((np.array(r) / sig) ** 2).sum(1).__le__(CHI2_90).mean()), 4)
    analytic = math.sqrt(0.05 ** 2 + (0.2 * W.DT) ** 2)
    cov_a = lambda r: round(float(((np.array(r) / analytic) ** 2).sum(1).__le__(CHI2_90).mean()), 4)
    C[nd] = {"sigma_fit": sig.round(4).tolist(), "sigma_analytic": round(analytic, 4),
             "coverage_constant_sigma_fit": {k: cov(v) for k, v in rows.items() if k != "fit"},
             "coverage_constant_sigma_analytic": {k: cov_a(v) for k, v in rows.items() if k != "fit"},
             "n": {k: len(v) for k, v in rows.items()}}
    print("C", nd, json.dumps(C[nd]), flush=True)
res["C_HC_constant_sigma"] = C
res["seconds"] = round(time.monotonic() - T0, 1)
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", res["seconds"], flush=True)
