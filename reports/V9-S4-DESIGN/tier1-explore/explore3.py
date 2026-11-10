"""S4 第一阶段一级摸底第三轮：直接量动力学，碰撞之后一步的速度误差。

未登记，只用来定设计，不作结论。纯 CPU、只用 NumPy，不训练。只用命名空间 s4x-explore。
依据 r1 复核必修 2：比例门 C 会饱和，只懂一半碰撞的模型也能过。这里量一个直接的动力学指标：
  从加噪真值出发预测一步，盘与盘碰撞的那一步，两个当事盘的速度误差；
比较 E-B（不懂盘与盘）、E-P（真实物理）、只懂比例 p 的碰撞的代用模型（每步每对以概率 p 处理碰撞），
看这个指标能否把「懂多少碰撞」分开。输入噪声取 r1 复核量到的两档：可见轨迹（位置 0.05、速度 0.2）
和隐藏轨迹（位置 0.7、速度 0.6）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

NS = "s4x-explore"
OUT = Path(__file__).resolve().parent


def partial_physics(p, v, pillars, p_know, rng):
    """Like W.physics, but each disk pair's collisions are handled only with probability p_know (per step)."""
    p, v = p.copy(), v.copy()
    _, n, _ = p.shape
    know = np.triu(rng.random((n, n)) < p_know, 1)
    h = W.DT / W.SUBSTEPS
    R = W.RADIUS
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
        ok = know[None] & (dist < 2 * R) & (dist > 1e-9)
        app = ok & (rel > 0)
        dv = np.where(app[..., None], rel[..., None] * nrm, 0.0)
        v = v - dv.sum(2) + dv.sum(1)
        push = np.where(ok, 2 * R - dist, 0.0)[..., None] * nrm / 2
        p = p - push.sum(2) + push.sum(1)
    return p, v


def run(n_worlds, n_disks, noise, seed=0):
    rng = np.random.default_rng(seed)
    sp, sv = noise
    err = {k: [] for k in ("CV", "B", "P", "p25", "p50", "p75")}
    err_free = {k: [] for k in err}
    for w in range(n_worlds):
        ep = W.generate_episode(NS, 1000 + w, n_disks)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            pair = [(i, j) for kind, i, j in s.contacts if kind == "disk"]
            involved = sorted({i for i, j in pair} | {j for i, j in pair})
            p0 = (s.positions + rng.normal(0, sp, s.positions.shape))[None]
            v0 = (s.velocities + rng.normal(0, sv, s.velocities.shape))[None]
            preds = {"CV": (p0 + v0 * W.DT, v0), "B": W.physics(p0, v0, ep.pillars, disks=False)[:2], "P": W.physics(p0, v0, ep.pillars)[:2]}
            for name, pk in (("p25", 0.25), ("p50", 0.5), ("p75", 0.75)):
                preds[name] = partial_physics(p0, v0, ep.pillars, pk, rng)
            free = [i for i in range(n_disks) if i not in involved]
            for name, (pp, vv) in preds.items():
                e = np.linalg.norm(vv[0] - nxt.velocities, axis=1)
                err[name] += e[involved].tolist()
                if free and s.t % 10 == 0:
                    err_free[name] += e[free].tolist()
    out = {"n_worlds": n_worlds, "n_disks": n_disks, "noise": list(noise), "n_collision_disk_steps": len(err["P"])}
    for k in err:
        a = np.array(err[k])
        out[k] = {"median": float(np.median(a)), "mean": float(a.mean()), "free_median": float(np.median(err_free[k]))}
    eb, ep_ = out["B"]["mean"], out["P"]["mean"]
    for k in err:
        out[k]["closure_mean"] = (eb - out[k]["mean"]) / (eb - ep_)
    return out


if __name__ == "__main__":
    res = []
    for nd in (6, 10):
        for noise in ((0.05, 0.2), (0.7, 0.6)):
            r = run(40, nd, noise)
            res.append(r)
            print(nd, noise, "n", r["n_collision_disk_steps"], {k: (round(r[k]["mean"], 3), round(r[k]["closure_mean"], 2)) for k in ("CV", "B", "P", "p25", "p50", "p75")})
    (OUT / "results3-dynamics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
