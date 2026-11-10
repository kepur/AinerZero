"""S4 第一阶段设计前的一级摸底。未登记，只用来定设计，不作结论。

纯 CPU、只用 NumPy，不训练。专用命名空间 s4x-explore，以后登记的分区一律用别的名字。
问一件事：在同外观圆盘会互相碰撞的连续二维世界里，物体被遮挡或出视野期间若发生碰撞，
「懂交互的物理」比「只懂常速度和反弹」的跟踪器在重新出现时认回身份能好多少。
如果差距很小，学一个交互模型就没有提升空间，S4 第一阶段要换问题。

世界：10×10 方形场地，圆柱障碍挡视线也挡运动；N 个同外观圆盘，弹性碰撞（盘—盘、盘—墙、盘—柱）。
智能体：已知自身位姿（声明为真值输入），沿随机路标巡游，90° 视锥、半径 5，被柱子挡住的看不到。
观察：匿名检测（世界坐标，噪声 σ = 0.05，漏检 5%），没有身份。
跟踪器（都不学习，共用同一套关联：匈牙利算法加门限，未匹配就新建轨迹）：
  T1 最后位置：隐藏的轨迹停在最后看到的位置
  T2 常速度：直线外推，不反弹
  T3 常速度加反弹：知道墙和柱，不知道盘与盘的碰撞
  T4 完整物理：在估计状态上跑真实模拟器（含盘与盘碰撞）
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
L = 10.0          # arena side
R = 0.3           # disk radius
DT = 0.1          # step
SUB = 4           # physics substeps per step
FOV = math.radians(90)
RANGE = 5.0
SIGMA = 0.05
P_MISS = 0.05


def say(*a):
    print(f"[{time.monotonic() - T0:7.1f}s]", *a, flush=True)


def seed_of(*keys) -> int:
    return int(hashlib.sha256((NS + ":" + ":".join(map(str, keys))).encode()).hexdigest()[:16], 16) & 0x7FFFFFFF


# --- physics ---------------------------------------------------------------------------
def step_physics(p, v, pillars, *, disk_collisions=True, walls=True):
    """Advance positions p [N,2] and velocities v [N,2] by DT with SUB substeps (in place copies returned)."""
    p, v = p.copy(), v.copy()
    h = DT / SUB
    n = len(p)
    for _ in range(SUB):
        p += v * h
        if walls:
            for d in range(2):
                lo, hi = p[:, d] < R, p[:, d] > L - R
                v[lo, d] = np.abs(v[lo, d]); p[lo, d] = R
                v[hi, d] = -np.abs(v[hi, d]); p[hi, d] = L - R
            for (cx, cy, cr) in pillars:
                d = p - np.array([cx, cy])
                dist = np.linalg.norm(d, axis=1)
                hit = dist < cr + R
                for i in np.flatnonzero(hit):
                    nrm = d[i] / max(dist[i], 1e-9)
                    vn = v[i] @ nrm
                    if vn < 0:
                        v[i] -= 2 * vn * nrm
                    p[i] = np.array([cx, cy]) + nrm * (cr + R)
        if disk_collisions and n > 1:
            for i in range(n):
                for j in range(i + 1, n):
                    d = p[j] - p[i]
                    dist = math.hypot(d[0], d[1])
                    if dist < 2 * R and dist > 1e-9:
                        nrm = d / dist
                        rel = (v[i] - v[j]) @ nrm
                        if rel > 0:  # approaching: equal masses exchange normal components
                            v[i] -= rel * nrm
                            v[j] += rel * nrm
                        overlap = 2 * R - dist
                        p[i] -= nrm * overlap / 2
                        p[j] += nrm * overlap / 2
    return p, v


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
    p = np.array(p)
    ang = rng.uniform(0, 2 * math.pi, n_disks)
    spd = rng.uniform(0.6, 1.4, n_disks)
    v = np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)
    return pillars, p, v


def blocked(a, b, pillars):
    """Line of sight from a to b crosses a pillar."""
    ab = b - a
    lab = ab @ ab
    for (cx, cy, cr) in pillars:
        c = np.array([cx, cy])
        t = 0.0 if lab == 0 else max(0.0, min(1.0, ((c - a) @ ab) / lab))
        if np.linalg.norm(a + t * ab - c) < cr:
            return True
    return False


def episode(w, *, n_disks, n_pillars, T):
    pillars, p, v = make_world(w, n_disks=n_disks, n_pillars=n_pillars)
    rng = np.random.default_rng(seed_of("agent", w))
    ag = rng.uniform(1, L - 1, 2)
    head = rng.uniform(0, 2 * math.pi)
    goal = rng.uniform(1, L - 1, 2)
    states, vis, dets = [], [], []
    for t in range(T):
        # agent: turn toward the goal, move 0.15/step
        to = goal - ag
        if np.linalg.norm(to) < 0.5:
            goal = rng.uniform(1, L - 1, 2)
            to = goal - ag
        want = math.atan2(to[1], to[0])
        dh = (want - head + math.pi) % (2 * math.pi) - math.pi
        head += max(-0.3, min(0.3, dh))
        ag = np.clip(ag + 0.15 * np.array([math.cos(head), math.sin(head)]), 0.5, L - 0.5)
        seen = []
        for i in range(n_disks):
            d = p[i] - ag
            dist = math.hypot(*d)
            ang = abs((math.atan2(d[1], d[0]) - head + math.pi) % (2 * math.pi) - math.pi)
            seen.append(bool(dist <= RANGE and ang <= FOV / 2 and not blocked(ag, p[i], pillars)))
        det = [(i, p[i] + rng.normal(0, SIGMA, 2)) for i in range(n_disks) if seen[i] and rng.random() > P_MISS]
        rng.shuffle(det)
        states.append((p.copy(), v.copy()))
        vis.append(seen)
        dets.append(det)  # (truth id, noisy position); trackers never read the truth id
        p, v = step_physics(p, v, pillars)
    return pillars, states, np.array(vis), dets


# --- association --------------------------------------------------------------------
def hungarian(cost):
    """Min-cost assignment for a rectangular matrix; returns list of (row, col)."""
    cost = np.asarray(cost, dtype=float)
    nr, nc = cost.shape
    n = max(nr, nc)
    big = cost.max() + 1 if cost.size else 1.0
    c = np.full((n, n), big)
    c[:nr, :nc] = cost
    u, vv = np.zeros(n + 1), np.zeros(n + 1)
    pp, way = np.zeros(n + 1, dtype=int), np.zeros(n + 1, dtype=int)
    for i in range(1, n + 1):
        pp[0] = i
        j0 = 0
        minv = np.full(n + 1, np.inf)
        used = np.zeros(n + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = pp[j0]
            delta, j1 = np.inf, -1
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
            j1 = way[j0]
            pp[j0] = pp[j1]
            j0 = j1
            if j0 == 0:
                break
    out = []
    for j in range(1, n + 1):
        if pp[j] and pp[j] - 1 < nr and j - 1 < nc:
            out.append((pp[j] - 1, j - 1))
    return out


GATE_BASE, GATE_GROW = 0.6, 1.5  # gate radius = base + grow * seconds hidden


def track(pillars, dets, kind):
    """Run one tracker; returns per step the list of (truth id, track id) for detections."""
    tracks = []  # dict: p, v, last_t
    out = []
    for t, det in enumerate(dets):
        # predict
        if tracks:
            P = np.array([tr["p"] for tr in tracks])
            V = np.array([tr["v"] for tr in tracks])
            if kind == "T1":
                P2, V2 = P, V * 0
            elif kind == "T2":
                P2, V2 = P + V * DT, V
            elif kind == "T3":
                P2, V2 = step_physics(P, V, pillars, disk_collisions=False)
            else:
                P2, V2 = step_physics(P, V, pillars, disk_collisions=True)
            for k, tr in enumerate(tracks):
                tr["p"], tr["v"] = P2[k], V2[k]
        pos = [d[1] for d in det]
        assign = {}
        if tracks and pos:
            cost = np.array([[np.linalg.norm(q - tr["p"]) for tr in tracks] for q in pos])
            for r, c in hungarian(cost):
                gate = GATE_BASE + GATE_GROW * DT * (t - tracks[c]["last_t"])
                if cost[r, c] <= gate:
                    assign[r] = c
        row = []
        for r, (truth, q) in enumerate(det):
            if r in assign:
                tr = tracks[assign[r]]
                gap = t - tr["last_t"]
                if gap == 1:
                    tr["hist"].append((t, q))
                else:
                    tr["hist"] = [(t, q)]  # a new visible run: velocity from this run only
                tr["hist"] = tr["hist"][-6:]
                if kind != "T1" and len(tr["hist"]) >= 2:
                    ts = np.array([h[0] for h in tr["hist"]], float) * DT
                    qs = np.array([h[1] for h in tr["hist"]])
                    tc = ts - ts.mean()
                    tr["v"] = (tc[:, None] * (qs - qs.mean(0))).sum(0) / (tc @ tc)
                    tr["p"] = qs.mean(0) + tr["v"] * (ts[-1] - ts.mean())
                elif gap > 1:
                    tr["p"] = q  # keep the propagated velocity across a gap until a new run gives one
                else:
                    tr["p"] = q
                tr["obs"], tr["last_t"] = q, t
                row.append((truth, assign[r]))
            else:
                tracks.append({"p": q, "v": np.zeros(2), "obs": q, "last_t": t, "hist": [(t, q)]})
                row.append((truth, len(tracks) - 1))
        out.append(row)
    return out


def reappearances(vis, states, pillars):
    """Events: object k visible at a, hidden a+1..b-1, visible at b. Flags a disk collision while hidden."""
    T, N = vis.shape
    ev = []
    for k in range(N):
        last = None
        for t in range(T):
            if vis[t, k]:
                if last is not None and t - last > 1:
                    # collision while hidden: velocity of k changed by something other than a wall/pillar?
                    coll = False
                    for s in range(last, t):
                        pa = states[s][0]
                        for j in range(N):
                            if j != k and np.linalg.norm(pa[j] - pa[k]) < 2 * R + 0.05:
                                coll = True
                    ev.append({"k": k, "a": last, "b": t, "gap": t - last - 1, "collision": coll})
                last = t
    return ev


def score(events, out):
    """Re-identification at re-appearance: the track at b is the track at a (both must be detected)."""
    at = [{truth: trk for truth, trk in row} for row in out]
    res = []
    for e in events:
        ta, tb = at[e["a"]].get(e["k"]), at[e["b"]].get(e["k"])
        if ta is None or tb is None:
            continue
        res.append(dict(e, correct=int(ta == tb)))
    return res


def oracle(states, events, pillars):
    """T5 diagnostic: true state of every object at the last sighting, true physics; reads the truth.

    Correct when, at b, the true position of k is closer to the rollout of k than to the rollout of any
    other object that is also hidden at that moment (the ambiguity a perfect predictor still faces)."""
    res = []
    for e in events:
        p, v = states[e["a"]]
        for _ in range(e["b"] - e["a"]):
            p, v = step_physics(p, v, pillars)
        truth = states[e["b"]][0][e["k"]]
        d = np.linalg.norm(p - truth, axis=1)
        res.append(dict(e, correct=int(np.argmin(d) == e["k"]), err=float(d[e["k"]])))
    return res


def run(cfg, n_worlds):
    say("cfg", cfg)
    rows = {k: [] for k in ("T1", "T2", "T3", "T4", "T5")}
    stats = {"events": 0, "collision_events": 0, "visible_frac": [], "gaps": []}
    for w in range(n_worlds):
        pillars, states, vis, dets = episode(w, **cfg)
        ev = reappearances(vis, states, pillars)
        stats["events"] += len(ev)
        stats["collision_events"] += sum(e["collision"] for e in ev)
        stats["visible_frac"].append(float(vis.mean()))
        stats["gaps"] += [e["gap"] for e in ev]
        for kind in ("T1", "T2", "T3", "T4"):
            rows[kind] += score(ev, track(pillars, dets, kind))
        rows["T5"] += oracle(states, ev, pillars)
        if (w + 1) % 10 == 0:
            say("world", w + 1)
    out = {"cfg": cfg, "n_worlds": n_worlds, "events": stats["events"], "collision_events": stats["collision_events"],
           "visible_frac": float(np.mean(stats["visible_frac"])),
           "gap_median": float(np.median(stats["gaps"])) if stats["gaps"] else None,
           "gap_p90": float(np.percentile(stats["gaps"], 90)) if stats["gaps"] else None, "acc": {}}
    for kind, rs in rows.items():
        for name, sel in (("all", lambda r: True), ("collision", lambda r: r["collision"]), ("no_collision", lambda r: not r["collision"]),
                          ("gap>=10", lambda r: r["gap"] >= 10), ("gap>=10_collision", lambda r: r["gap"] >= 10 and r["collision"])):
            s = [r["correct"] for r in rs if sel(r)]
            out["acc"][f"{kind}/{name}"] = [round(float(np.mean(s)), 4) if s else None, len(s)]
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    grid = [dict(n_disks=6, n_pillars=3, T=300), dict(n_disks=10, n_pillars=3, T=300)]
    res = [run(c, n) for c in grid]
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r["cfg"], "events", r["events"], "collision", r["collision_events"], "vis", round(r["visible_frac"], 3), "gap", r["gap_median"], r["gap_p90"])
        for k, v in r["acc"].items():
            print("  ", k, v)
    say("done")
