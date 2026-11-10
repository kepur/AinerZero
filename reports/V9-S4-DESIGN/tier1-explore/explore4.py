"""S4 第一阶段一级摸底第四轮：擦边步的误报，以及方差头能否胜过常数 σ。

未登记，只用来定设计，不作结论。纯 CPU、只用 NumPy，不训练。只用命名空间 s4x-explore。
依据 r2 复核：
  - 必修 1：HD 只看真碰撞步，提前触发的模型不受罚。量擦边步（本步末两盘距离 < 2R + 0.3、没有接触）上
    各代用模型的速度误差，给误报门定门槛；
  - 必修 2：常数 σ 就能过 HC。量「按与最近盘的距离分箱的先知 σ」比常数 σ 在碰撞步与擦边步上的 NLL 好多少，
    这是方差头能达到的上限的一个下界参考。输入是可见轨迹量级噪声（位置 0.05、速度 0.2）加在真值上，
    均值用真实物理在带噪输入上的输出（相当于完美的均值模型）。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
import explore3 as X3  # noqa: E402

NS = "s4x-explore"
OUT = Path(__file__).resolve().parent
GRAZE = 0.3


def early_physics(p, v, pillars, margin):
    """Reviewer's early-trigger stand-in: disks within 2R + margin that approach exchange normal velocity."""
    p, v = p.copy(), v.copy()
    h = W.DT / W.SUBSTEPS
    R = W.RADIUS
    _, n, _ = p.shape
    for _ in range(W.SUBSTEPS):
        p += v * h
        for d in range(2):
            lo, hi = p[..., d] < R, p[..., d] > W.ARENA - R
            v[..., d] = np.where(lo, np.abs(v[..., d]), np.where(hi, -np.abs(v[..., d]), v[..., d]))
            p[..., d] = np.clip(p[..., d], R, W.ARENA - R)
        for cx, cy, cr in pillars:
            c = np.array([cx, cy])
            dvec = p - c
            dist = np.linalg.norm(dvec, axis=-1, keepdims=True)
            nrm = dvec / np.maximum(dist, 1e-9)
            hit = dist < cr + R
            vn = (v * nrm).sum(-1, keepdims=True)
            v = np.where(hit & (vn < 0), v - 2 * vn * nrm, v)
            p = np.where(hit, c + nrm * (cr + R), p)
        d = p[:, None] - p[:, :, None]
        dist = np.linalg.norm(d, axis=-1)
        nrm = d / np.maximum(dist, 1e-9)[..., None]
        rel = ((v[:, :, None] - v[:, None]) * nrm).sum(-1)
        upper = np.triu(np.ones((n, n), bool), 1)[None]
        app = upper & (dist < 2 * R + margin) & (dist > 1e-9) & (rel > 0)
        dv = np.where(app[..., None], rel[..., None] * nrm, 0.0)
        v = v - dv.sum(2) + dv.sum(1)
        ok = upper & (dist < 2 * R) & (dist > 1e-9)
        push = np.where(ok, 2 * R - dist, 0.0)[..., None] * nrm / 2
        p = p - push.sum(2) + push.sum(1)
    return p, v


def graze_and_collision(n_worlds, n_disks, seed=0):
    rng = np.random.default_rng(seed)
    models = ("B", "P", "p75", "early15", "early30")
    err = {m: {"coll": [], "graze": []} for m in models}
    for w in range(n_worlds):
        ep = W.generate_episode(NS, 1000 + w, n_disks)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            d = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(n_disks) * 99
            near = {i for i in range(n_disks) if d[i].min() < 2 * W.RADIUS + GRAZE}
            graze = sorted(near - coll)
            if not coll and not graze:
                continue
            p0, v0 = s.positions[None], s.velocities[None]
            preds = {"B": W.physics(p0, v0, ep.pillars, disks=False)[1], "P": W.physics(p0, v0, ep.pillars)[1],
                     "p75": X3.partial_physics(p0, v0, ep.pillars, 0.75, rng)[1],
                     "early15": early_physics(p0, v0, ep.pillars, 0.15)[1], "early30": early_physics(p0, v0, ep.pillars, 0.30)[1]}
            for m, vv in preds.items():
                e = np.linalg.norm(vv[0] - nxt.velocities, axis=1)
                err[m]["coll"] += e[sorted(coll)].tolist()
                err[m]["graze"] += e[graze].tolist()
    out = {"n_worlds": n_worlds, "n_disks": n_disks, "n_coll": len(err["P"]["coll"]), "n_graze": len(err["P"]["graze"])}
    eb = float(np.mean(err["B"]["coll"]))
    for m in models:
        c, g = np.array(err[m]["coll"]), np.array(err[m]["graze"])
        out[m] = {"D": 1 - c.mean() / eb, "graze_mean": float(g.mean()), "graze_frac_gt_0.1": float((g > 0.1).mean())}
    return out


def nll_constant_vs_binned(n_worlds, n_disks, seed=0):
    """Per disk-step 2D Gaussian NLL of the true next position, mean = physics on noisy input."""
    rng = np.random.default_rng(seed)
    rows = []  # (min distance to another disk at t, squared error x, y, kind)
    for w in range(n_worlds):
        ep = W.generate_episode(NS, 2000 + w, n_disks)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            p0 = s.positions + rng.normal(0, 0.05, s.positions.shape)
            v0 = s.velocities + rng.normal(0, 0.2, s.velocities.shape)
            pp, _, _ = W.physics(p0[None], v0[None], ep.pillars)
            r = pp[0] - nxt.positions
            d0 = np.linalg.norm(p0[:, None] - p0[None], axis=-1) + np.eye(n_disks) * 99
            dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(n_disks) * 99
            for i in range(n_disks):
                kind = "coll" if i in coll else ("graze" if dn[i].min() < 2 * W.RADIUS + GRAZE else "free")
                rows.append((d0[i].min(), r[i, 0] ** 2 + r[i, 1] ** 2, kind))
    dmin = np.array([r[0] for r in rows]); se = np.array([r[1] for r in rows]); kind = np.array([r[2] for r in rows])
    half = len(rows) // 2  # fit on the first half, evaluate on the second
    fit, ev = slice(0, half), slice(half, None)
    s2_const = se[fit].mean() / 2  # per-axis variance
    bins = np.array([0, 0.6, 0.7, 0.8, 1.0, 1.3, 2.0, 99])
    idx = np.clip(np.digitize(dmin, bins) - 1, 0, len(bins) - 2)
    s2_bin = np.array([se[fit][idx[fit] == b].mean() / 2 if (idx[fit] == b).any() else s2_const for b in range(len(bins) - 1)])

    def nll(s2, se_):
        return np.log(2 * math.pi * s2) + se_ / (2 * s2)

    out = {"n_disks": n_disks, "n_rows": len(rows), "sigma_const": float(math.sqrt(s2_const)), "sigma_bins": [float(math.sqrt(x)) for x in s2_bin]}
    for sel_name in ("coll", "graze", "free", "coll+graze", "all"):
        m = np.zeros(len(rows), bool)
        m[ev] = True
        if sel_name == "coll+graze":
            m &= (kind == "coll") | (kind == "graze")
        elif sel_name != "all":
            m &= kind == sel_name
        a = nll(s2_const, se[m]).mean()
        b = nll(s2_bin[idx[m]], se[m]).mean()
        cov_c = float((se[m] <= -2 * s2_const * math.log(0.1)).mean())
        cov_b = float((se[m] <= -2 * s2_bin[idx[m]] * math.log(0.1)).mean())
        out[sel_name] = {"n": int(m.sum()), "nll_const": float(a), "nll_binned": float(b), "gain": float(a - b), "cov90_const": cov_c, "cov90_binned": cov_b}
    return out


def velocity_nll(n_worlds, n_disks, seed=0):
    """Same as nll_constant_vs_binned, but on the next-step velocity (residual of physics on the noisy input).

    First run inline on 2026-11-10 and folded in here unchanged; results4-graze-nll.json["velocity_nll"]."""
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(n_worlds):
        ep = W.generate_episode(NS, 2000 + w, n_disks)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            p0 = s.positions + rng.normal(0, 0.05, s.positions.shape)
            v0 = s.velocities + rng.normal(0, 0.2, s.velocities.shape)
            _, vv, _ = W.physics(p0[None], v0[None], ep.pillars)
            r = vv[0] - nxt.velocities
            d0 = np.linalg.norm(p0[:, None] - p0[None], axis=-1) + np.eye(n_disks) * 99
            dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(n_disks) * 99
            for i in range(n_disks):
                kind = "coll" if i in coll else ("graze" if dn[i].min() < 2 * W.RADIUS + GRAZE else "free")
                rows.append((d0[i].min(), r[i, 0] ** 2 + r[i, 1] ** 2, kind))
    dmin = np.array([x[0] for x in rows]); se = np.array([x[1] for x in rows]); kind = np.array([x[2] for x in rows])
    half = len(rows) // 2
    s2c = se[:half].mean() / 2
    bins = np.array([0, 0.6, 0.65, 0.7, 0.8, 1.0, 1.3, 2.0, 99])
    idx = np.clip(np.digitize(dmin, bins) - 1, 0, len(bins) - 2)
    s2b = np.array([se[:half][idx[:half] == b].mean() / 2 if (idx[:half] == b).any() else s2c for b in range(len(bins) - 1)])

    def nll(s2, e):
        return np.log(2 * math.pi * s2) + e / (2 * s2)

    out = {"n_disks": n_disks, "sigma_const": math.sqrt(s2c), "sigma_bins": [math.sqrt(x) for x in s2b]}
    for name in ("coll", "graze", "coll+graze", "free", "all"):
        m = np.zeros(len(rows), bool)
        m[half:] = True
        if name == "coll+graze":
            m &= (kind == "coll") | (kind == "graze")
        elif name != "all":
            m &= kind == name
        a, b = nll(s2c, se[m]).mean(), nll(s2b[idx[m]], se[m]).mean()
        out[name] = {"n": int(m.sum()), "nll_const": float(a), "nll_binned": float(b), "gain": float(a - b),
                     "cov90_const": float((se[m] <= -2 * s2c * math.log(0.1)).mean()),
                     "cov90_binned": float((se[m] <= -2 * s2b[idx[m]] * math.log(0.1)).mean())}
    return out


if __name__ == "__main__":
    res = {"graze": [graze_and_collision(40, nd) for nd in (6, 10)], "nll": [nll_constant_vs_binned(40, nd) for nd in (6, 10)],
           "velocity_nll": [velocity_nll(40, nd) for nd in (6, 10)]}
    (OUT / "results4-graze-nll.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res["graze"]:
        print(r["n_disks"], "coll", r["n_coll"], "graze", r["n_graze"], {m: (round(r[m]["D"], 2), round(r[m]["graze_mean"], 3)) for m in ("B", "P", "p75", "early15", "early30")})
    for r in res["nll"]:
        print(r["n_disks"], "sigma", round(r["sigma_const"], 4), [round(x, 3) for x in r["sigma_bins"]])
        for k in ("coll", "graze", "coll+graze", "free", "all"):
            print("   ", k, {x: round(y, 3) if isinstance(y, float) else y for x, y in r[k].items()})
