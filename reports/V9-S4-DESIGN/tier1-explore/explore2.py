"""S4 第一阶段一级摸底第二轮：动力学进入滤波器（集合卡尔曼），不是只管隐藏期间的外推。

未登记，只用来定设计，不作结论。纯 CPU、只用 NumPy，不训练。只用命名空间 s4x-explore。

依据 r0 复核必修 1：r0 的跟踪器用最小二乘单独估速度，动力学只外推隐藏轨迹，交互的价值被速度误差吃掉。
这一轮：
  - 物理改成按集合成员批量计算的向量化版本，世界生成和滤波器的「真实物理」用同一个函数，D-P 就是生成器；
  - 接触日志由物理函数直接给出（法向速度反转的盘对），「隐藏期间有碰撞」只看 a < s < b；
  - 跟踪器是集合卡尔曼滤波：每条轨迹 M 个成员，过程模型把全部轨迹的成员 m 一起往前推，
    观测更新用扰动观测；关联用马氏距离加匈牙利算法，门限按卡方；
  - 过程模型：E-CV 常速度、E-B 常速度加反弹（懂墙和柱，不懂盘与盘）、E-P 真实物理；
  - 诊断上限 S-P：检测分到轨迹时把轨迹状态换成真值，过程模型用真实物理（读真值，只作诊断）。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

NS = "s4x-explore"
OUT = Path(__file__).resolve().parent
T0 = time.monotonic()
L, R, DT, SUB = 10.0, 0.3, 0.1, 4
SIGMA, P_MISS = 0.05, 0.05
M = 32                      # ensemble members
Q_POS, Q_VEL = 0.01, 0.05   # process noise per step (std)
CHI2 = 13.82                # 2 dof, 99.9%
ASSOC = "maha"              # 'maha' or 'eucl' (r0 gate: 0.6 + 1.5 * seconds hidden)
INFLATE = 1.0               # multiplicative ensemble inflation per step


def say(*a):
    print(f"[{time.monotonic() - T0:7.1f}s]", *a, flush=True)


def seed_of(*keys) -> int:
    return int(hashlib.sha256((NS + ":" + ":".join(map(str, keys))).encode()).hexdigest()[:16], 16) & 0x7FFFFFFF


# --- batched physics: p, v are [B, N, 2] -------------------------------------------------
def physics(p, v, pillars, *, disks=True, valid=None):
    """One step for B independent copies; returns (p, v, contacts) with contacts a set of (i, j) for copy 0."""
    p, v = p.copy(), v.copy()
    B, N, _ = p.shape
    h = DT / SUB
    contacts = set()
    pil = np.array([[a, b] for a, b, _ in pillars]) if pillars else np.zeros((0, 2))
    pr = np.array([r for _, _, r in pillars]) if pillars else np.zeros(0)
    for _ in range(SUB):
        p += v * h
        for d in range(2):
            lo, hi = p[..., d] < R, p[..., d] > L - R
            v[..., d] = np.where(lo, np.abs(v[..., d]), np.where(hi, -np.abs(v[..., d]), v[..., d]))
            p[..., d] = np.clip(p[..., d], R, L - R)
        for c, cr in zip(pil, pr):
            dvec = p - c
            dist = np.linalg.norm(dvec, axis=-1, keepdims=True)
            nrm = dvec / np.maximum(dist, 1e-9)
            hit = dist < cr + R
            vn = (v * nrm).sum(-1, keepdims=True)
            v = np.where(hit & (vn < 0), v - 2 * vn * nrm, v)
            p = np.where(hit, c + nrm * (cr + R), p)
        if disks and N > 1:
            d = p[:, None, :, :] - p[:, :, None, :]          # [B, i, j, 2] = p_j - p_i
            dist = np.linalg.norm(d, axis=-1)
            nrm = d / np.maximum(dist, 1e-9)[..., None]
            rel = ((v[:, :, None, :] - v[:, None, :, :]) * nrm).sum(-1)  # (v_i - v_j) . n_ij
            iu = np.triu(np.ones((N, N), bool), 1)
            ok = iu[None] & (dist < 2 * R) & (dist > 1e-9)
            if valid is not None:
                ok &= valid[None, :, None] & valid[None, None, :]
            app = ok & (rel > 0)
            if app[0].any():
                contacts |= {(int(i), int(j)) for i, j in zip(*np.nonzero(app[0]))}
            dv = np.where(app[..., None], rel[..., None] * nrm, 0.0)       # impulse on pair (i, j)
            v = v - dv.sum(2) + dv.sum(1)
            ov = np.where(ok, 2 * R - dist, 0.0)[..., None] * nrm / 2
            p = p - ov.sum(2) + ov.sum(1)
    return p, v, contacts


def make_world(w, *, n_disks, n_pillars):
    rng = np.random.default_rng(seed_of("world", w))
    pillars = []
    while len(pillars) < n_pillars:
        c = rng.uniform(2, L - 2, 2)
        r = rng.uniform(0.4, 0.8)
        if all(math.hypot(c[0] - a, c[1] - b) > r + rr + 1.2 for a, b, rr in pillars):
            pillars.append((float(c[0]), float(c[1]), float(r)))
    p = []
    while len(p) < n_disks:
        c = rng.uniform(R + 0.1, L - R - 0.1, 2)
        if all(math.hypot(*(c - q)) > 2 * R + 0.2 for q in p) and all(math.hypot(c[0] - a, c[1] - b) > rr + R + 0.2 for a, b, rr in pillars):
            p.append(c)
    ang = rng.uniform(0, 2 * math.pi, n_disks)
    spd = rng.uniform(0.6, 1.4, n_disks)
    return pillars, np.array(p), np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)


def blocked(a, b, pillars):
    ab = b - a
    lab = ab @ ab
    for (cx, cy, cr) in pillars:
        c = np.array([cx, cy])
        t = 0.0 if lab == 0 else max(0.0, min(1.0, ((c - a) @ ab) / lab))
        if np.linalg.norm(a + t * ab - c) < cr:
            return True
    return False


def episode(w, *, n_disks, n_pillars, T, fov, rng_):
    pillars, p, v = make_world(w, n_disks=n_disks, n_pillars=n_pillars)
    rng = np.random.default_rng(seed_of("agent", w))
    ag, head, goal = rng.uniform(1, L - 1, 2), rng.uniform(0, 2 * math.pi), rng.uniform(1, L - 1, 2)
    states, vis, dets, contacts = [], [], [], []
    for t in range(T):
        to = goal - ag
        if np.linalg.norm(to) < 0.5:
            goal = rng.uniform(1, L - 1, 2)
            to = goal - ag
        dh = (math.atan2(to[1], to[0]) - head + math.pi) % (2 * math.pi) - math.pi
        head += max(-0.3, min(0.3, dh))
        ag = np.clip(ag + 0.15 * np.array([math.cos(head), math.sin(head)]), 0.5, L - 0.5)
        seen = []
        for i in range(n_disks):
            d = p[i] - ag
            ang = abs((math.atan2(d[1], d[0]) - head + math.pi) % (2 * math.pi) - math.pi)
            seen.append(bool(math.hypot(*d) <= rng_ and ang <= fov / 2 and not blocked(ag, p[i], pillars)))
        det = [(i, p[i] + rng.normal(0, SIGMA, 2)) for i in range(n_disks) if seen[i] and rng.random() > P_MISS]
        rng.shuffle(det)
        states.append((p.copy(), v.copy()))
        vis.append(seen)
        dets.append(det)
        pp, vv, cont = physics(p[None], v[None], pillars)
        p, v = pp[0], vv[0]
        contacts.append(cont)  # contacts during the step t -> t+1
    return pillars, states, np.array(vis), dets, contacts


# --- association ------------------------------------------------------------------------
def hungarian(cost):
    cost = np.asarray(cost, float)
    nr, nc = cost.shape
    n = max(nr, nc)
    c = np.full((n, n), (cost.max() + 1) if cost.size else 1.0)
    c[:nr, :nc] = cost
    u, vv = np.zeros(n + 1), np.zeros(n + 1)
    pp, way = np.zeros(n + 1, int), np.zeros(n + 1, int)
    for i in range(1, n + 1):
        pp[0], j0 = i, 0
        minv, used = np.full(n + 1, np.inf), np.zeros(n + 1, bool)
        while True:
            used[j0] = True
            i0, delta, j1 = pp[j0], np.inf, -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = c[i0 - 1, j - 1] - u[i0] - vv[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[pp[j]] += delta; vv[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if pp[j0] == 0:
                break
        while True:
            j1 = way[j0]; pp[j0] = pp[j1]; j0 = j1
            if j0 == 0:
                break
    return [(pp[j] - 1, j - 1) for j in range(1, n + 1) if pp[j] and pp[j] - 1 < nr and j - 1 < nc]


# --- ensemble Kalman tracker ----------------------------------------------------------------
def enkf(pillars, dets, kind, rng, *, states=None):
    """kind: 'CV', 'B', 'P' (process model) or 'SP' (diagnostic: true state on assignment, true physics)."""
    P = np.zeros((M, 0, 2)); V = np.zeros((M, 0, 2))
    last = []
    out = []
    for t, det in enumerate(dets):
        if P.shape[1]:
            if kind == "CV":
                P = P + V * DT
            else:
                P, V, _ = physics(P, V, pillars, disks=kind in ("P", "SP"))
            if INFLATE != 1.0:
                P = P.mean(0) + (P - P.mean(0)) * INFLATE
                V = V.mean(0) + (V - V.mean(0)) * INFLATE
            P = P + rng.normal(0, Q_POS, P.shape)
            V = V + rng.normal(0, Q_VEL, V.shape)
        pos = [d[1] for d in det]
        assign = {}
        n_tr = P.shape[1]
        if n_tr and pos:
            mu = P.mean(0)                                     # [n, 2]
            dP = P - mu
            cov = np.einsum("mni,mnj->nij", dP, dP) / (M - 1) + np.eye(2) * SIGMA ** 2
            inv = np.linalg.inv(cov)
            z = np.array(pos)
            diff = z[:, None, :] - mu[None]                    # [d, n, 2]
            if ASSOC == "maha":
                maha = np.einsum("dni,nij,dnj->dn", diff, inv, diff)
                for r, c in hungarian(maha):
                    if maha[r, c] <= CHI2:
                        assign[r] = c
            else:
                eu = np.linalg.norm(diff, axis=-1)
                for r, c in hungarian(eu):
                    if eu[r, c] <= 0.6 + 1.5 * DT * (t - last[c]):
                        assign[r] = c
        row = []
        for r, (truth, q) in enumerate(det):
            if r in assign:
                k = assign[r]
                if kind == "SP":
                    p_true, v_true = states[t]
                    P[:, k] = p_true[truth]; V[:, k] = v_true[truth]
                else:
                    X = np.concatenate([P[:, k], V[:, k]], 1)  # [M, 4]
                    Xm = X.mean(0)
                    A = X - Xm
                    Pxz = A.T @ (P[:, k] - P[:, k].mean(0)) / (M - 1)   # [4, 2]
                    Pzz = np.cov(P[:, k].T) + np.eye(2) * SIGMA ** 2
                    K = Pxz @ np.linalg.inv(Pzz)
                    zp = q + rng.normal(0, SIGMA, (M, 2))
                    X = X + (zp - P[:, k]) @ K.T
                    P[:, k], V[:, k] = X[:, :2], X[:, 2:]
                last[k] = t
                row.append((truth, k))
            else:
                newP = q + rng.normal(0, SIGMA, (M, 1, 2))
                ang = rng.uniform(0, 2 * math.pi, M)
                spd = rng.uniform(0.6, 1.4, M)
                newV = np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)[:, None, :]
                if kind == "SP":
                    p_true, v_true = states[t]
                    newP = np.broadcast_to(p_true[truth], (M, 1, 2)).copy()
                    newV = np.broadcast_to(v_true[truth], (M, 1, 2)).copy()
                P = np.concatenate([P, newP], 1); V = np.concatenate([V, newV], 1)
                last.append(t)
                row.append((truth, P.shape[1] - 1))
        out.append(row)
    return out, P.shape[1]


def reappearances(vis, contacts):
    T, N = vis.shape
    ev = []
    for k in range(N):
        last = None
        for t in range(T):
            if vis[t, k]:
                if last is not None and t - last > 1:
                    # contacts in the steps last -> last+1, ..., t-1 -> t that involve k, strictly after a
                    coll = any(k in pair for s in range(last + 1, t) for pair in contacts[s])
                    ev.append({"k": k, "a": last, "b": t, "gap": t - last - 1, "collision": coll})
                last = t
    return ev


def score(events, out):
    at = [{truth: trk for truth, trk in row} for row in out]
    res = []
    for e in events:
        ta, tb = at[e["a"]].get(e["k"]), at[e["b"]].get(e["k"])
        if ta is not None and tb is not None:
            res.append(dict(e, correct=int(ta == tb)))
    return res


def run(cfg, n_worlds, kinds=("CV", "B", "P", "SP")):
    say("cfg", cfg)
    rows = {k: [] for k in kinds}
    n_tracks = {k: [] for k in kinds}
    meta = {"events": 0, "collision_events": 0, "vis": []}
    for w in range(n_worlds):
        pillars, states, vis, dets, contacts = episode(w, **cfg)
        ev = reappearances(vis, contacts)
        meta["events"] += len(ev)
        meta["collision_events"] += sum(e["collision"] for e in ev)
        meta["vis"].append(float(vis.mean()))
        for kind in kinds:
            out, nt = enkf(pillars, dets, kind, np.random.default_rng(seed_of("filter", w, kind)), states=states)
            rows[kind] += score(ev, out)
            n_tracks[kind].append(nt)
        if (w + 1) % 10 == 0:
            say("world", w + 1)
    res = {"cfg": {k: (round(math.degrees(v)) if k == "fov" else v) for k, v in cfg.items()}, "n_worlds": n_worlds,
           "events": meta["events"], "collision_events": meta["collision_events"], "visible_frac": float(np.mean(meta["vis"])), "acc": {},
           "tracks_mean": {k: float(np.mean(v)) for k, v in n_tracks.items()}}
    for kind, rs in rows.items():
        for name, sel in (("all", lambda r: True), ("collision", lambda r: r["collision"]), ("no_collision", lambda r: not r["collision"]),
                          ("gap>=10", lambda r: r["gap"] >= 10)):
            s = [r["correct"] for r in rs if sel(r)]
            res["acc"][f"{kind}/{name}"] = [round(float(np.mean(s)), 4) if s else None, len(s)]
    return res


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    grid = [dict(n_disks=6, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0),
            dict(n_disks=10, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0)]
    res = [run(c, n) for c in grid]
    (OUT / "results2-enkf.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r["cfg"]["n_disks"], "events", r["events"], "collision", r["collision_events"], "vis", round(r["visible_frac"], 3), "tracks", r["tracks_mean"])
        for name in ("all", "collision", "no_collision", "gap>=10"):
            print("   ", name, {k: r["acc"][f"{k}/{name}"] for k in ("CV", "B", "P", "SP")})
    say("done")
