"""S4 第一阶段 r0 的对抗检查（复核者自写，不改被审文件）。只用 NumPy，不训练，不导入 MLX。

复用隔离副本里 explore.py 的世界、物理、匈牙利算法、事件与评分；跟踪器改成可变：
  min_pts      速度最小二乘至少要几个点（原稿 2）
  gate         (基础, 每秒增长)（原稿 0.6, 1.5）
  neg          负信息：预测落在视野内（留 0.5 边距）却连续 2 步没被检测到，就删掉这条轨迹
  truth_state  诊断：检测被分给轨迹时，把轨迹状态换成该物体的真值（读真值，只作拆解）
用法：adv_s4.py <explore 目录> <命名空间> <世界数> <输出 json>
"""
import collections, json, math, sys, time
import numpy as np

sys.path.insert(0, sys.argv[1])
import explore as X  # noqa: E402

NS, NW, OUT = sys.argv[2], int(sys.argv[3]), sys.argv[4]
assert NS in ("s4x-explore", "s4x-rv1110"), NS
X.NS = NS
X.FOV, X.RANGE = math.radians(180), 7.0
T0 = time.monotonic()


def episode2(w, *, n_disks, n_pillars, T):
    """explore.episode 的逐行副本，另外返回智能体每步的位姿（学生可见的真值输入）。"""
    pillars, p, v = X.make_world(w, n_disks=n_disks, n_pillars=n_pillars)
    rng = np.random.default_rng(X.seed_of("agent", w))
    ag = rng.uniform(1, X.L - 1, 2); head = rng.uniform(0, 2 * math.pi); goal = rng.uniform(1, X.L - 1, 2)
    states, vis, dets, poses = [], [], [], []
    for t in range(T):
        to = goal - ag
        if np.linalg.norm(to) < 0.5:
            goal = rng.uniform(1, X.L - 1, 2); to = goal - ag
        want = math.atan2(to[1], to[0])
        dh = (want - head + math.pi) % (2 * math.pi) - math.pi
        head += max(-0.3, min(0.3, dh))
        ag = np.clip(ag + 0.15 * np.array([math.cos(head), math.sin(head)]), 0.5, X.L - 0.5)
        seen = []
        for i in range(n_disks):
            d = p[i] - ag; dist = math.hypot(*d)
            ang = abs((math.atan2(d[1], d[0]) - head + math.pi) % (2 * math.pi) - math.pi)
            seen.append(bool(dist <= X.RANGE and ang <= X.FOV / 2 and not X.blocked(ag, p[i], pillars)))
        det = [(i, p[i] + rng.normal(0, X.SIGMA, 2)) for i in range(n_disks) if seen[i] and rng.random() > X.P_MISS]
        rng.shuffle(det)
        states.append((p.copy(), v.copy())); vis.append(seen); dets.append(det); poses.append((ag.copy(), head))
        p, v = X.step_physics(p, v, pillars)
    return pillars, states, np.array(vis), dets, poses


def in_view(q, pose, pillars, margin=0.5):
    ag, head = pose
    d = q - ag; dist = math.hypot(*d)
    ang = abs((math.atan2(d[1], d[0]) - head + math.pi) % (2 * math.pi) - math.pi)
    return dist <= X.RANGE - margin and ang <= X.FOV / 2 - margin / max(dist, 1e-6) and not X.blocked(ag, q, pillars)


def track(pillars, dets, kind, *, min_pts=2, gate=(0.6, 1.5), neg=False, poses=None, truth_state=None, vel_log=None):
    tracks, out = [], []
    for t, det in enumerate(dets):
        live = [k for k, tr in enumerate(tracks) if tr["alive"]]
        if live:
            P = np.array([tracks[k]["p"] for k in live]); V = np.array([tracks[k]["v"] for k in live])
            if kind == "T1":
                P2, V2 = P, V * 0
            elif kind == "T2":
                P2, V2 = P + V * X.DT, V
            elif kind == "T3":
                P2, V2 = X.step_physics(P, V, pillars, disk_collisions=False)
            else:
                P2, V2 = X.step_physics(P, V, pillars, disk_collisions=True)
            for i, k in enumerate(live):
                tracks[k]["p"], tracks[k]["v"] = P2[i], V2[i]
        pos = [d[1] for d in det]
        assign = {}
        if live and pos:
            cost = np.array([[np.linalg.norm(q - tracks[k]["p"]) for k in live] for q in pos])
            for r, c in X.hungarian(cost):
                k = live[c]
                if cost[r, c] <= gate[0] + gate[1] * X.DT * (t - tracks[k]["last_t"]):
                    assign[r] = k
        row = []
        for r, (truth, q) in enumerate(det):
            if r in assign:
                tr = tracks[assign[r]]; gap = t - tr["last_t"]
                tr["hist"] = tr["hist"] + [(t, q)] if gap == 1 else [(t, q)]
                tr["hist"] = tr["hist"][-6:]
                if kind != "T1" and len(tr["hist"]) >= min_pts:
                    ts = np.array([h[0] for h in tr["hist"]], float) * X.DT; qs = np.array([h[1] for h in tr["hist"]])
                    tc = ts - ts.mean()
                    tr["v"] = (tc[:, None] * (qs - qs.mean(0))).sum(0) / (tc @ tc)
                    tr["p"] = qs.mean(0) + tr["v"] * (ts[-1] - ts.mean())
                else:
                    tr["p"] = q
                if truth_state is not None:  # 诊断：读真值
                    tr["p"], tr["v"] = truth_state[t][0][truth].copy(), truth_state[t][1][truth].copy()
                tr["obs"], tr["last_t"], tr["miss_in_view"] = q, t, 0
                row.append((truth, assign[r]))
                if vel_log is not None:
                    vel_log.append((t, truth, tr["v"].copy(), len(tr["hist"])))
            else:
                tracks.append({"p": q, "v": np.zeros(2), "obs": q, "last_t": t, "hist": [(t, q)], "alive": True, "miss_in_view": 0})
                row.append((truth, len(tracks) - 1))
        if neg:
            for k in live:
                tr = tracks[k]
                if tr["last_t"] != t and in_view(tr["p"], poses[t], pillars):
                    tr["miss_in_view"] += 1
                    if tr["miss_in_view"] >= 2:
                        tr["alive"] = False
                elif tr["last_t"] != t:
                    tr["miss_in_view"] = 0
        out.append(row)
    return out, tracks


def boot(rows_a, rows_b, sel, B=4000, seed=20261110):
    """按世界配对 bootstrap：rows 是 [(world, event_key, correct)]，a 与 b 同一事件集。"""
    ka = {(w, k): c for w, k, c, e in rows_a if sel(e)}
    kb = {(w, k): c for w, k, c, e in rows_b if sel(e)}
    keys = sorted(set(ka) & set(kb))
    if not keys:
        return None
    ws = sorted({w for w, _ in keys}); wi = {w: i for i, w in enumerate(ws)}
    d = np.zeros(len(ws)); n = np.zeros(len(ws))
    for key in keys:
        d[wi[key[0]]] += ka[key] - kb[key]; n[wi[key[0]]] += 1
    idx = np.random.default_rng(seed).integers(0, len(ws), size=(B, len(ws)))
    est = d[idx].sum(1) / n[idx].sum(1)
    return {"delta": round(float(d.sum() / n.sum()), 4), "lo": round(float(np.percentile(est, 2.5)), 4), "hi": round(float(np.percentile(est, 97.5)), 4), "n": int(n.sum()), "worlds": len(ws)}


VARIANTS = {
    "base": {},
    "minpts4": {"min_pts": 4},
    "neg": {"neg": True},
    "neg_minpts4": {"neg": True, "min_pts": 4},
    "gate_0.6_0.75": {"gate": (0.6, 0.75)},
    "gate_0.6_3.0": {"gate": (0.6, 3.0)},
    "gate_0.3_1.5": {"gate": (0.3, 1.5)},
    "gate_1.2_1.5": {"gate": (1.2, 1.5)},
    "truth_state": {"truth": True},
}
res = {"ns": NS, "n_worlds": NW, "fov_deg": 180, "range": 7.0, "configs": {}}
for nd in (6, 10):
    cfg = dict(n_disks=nd, n_pillars=3, T=300)
    rows = collections.defaultdict(list)
    anat = collections.Counter(); verr = collections.defaultdict(list); t5err = []; ntracks = collections.defaultdict(list)
    for w in range(NW):
        pillars, states, vis, dets, poses = episode2(w, **cfg)
        ev = X.reappearances(vis, states, pillars)
        for e in ev:  # 碰撞事件的构成
            if not e["collision"]:
                continue
            k, a, b = e["k"], e["a"], e["b"]
            first = next(s for s in range(a, b) if any(j != k and np.linalg.norm(states[s][0][j] - states[s][0][k]) < 2 * X.R + 0.05 for j in range(nd)))
            anat["collision_events"] += 1
            anat["contact_at_a"] += int(first == a)
            anat["contact_within_2_of_a"] += int(first <= a + 2)
            vchg = np.linalg.norm(states[b - 1][1][k] - states[a][1][k]) > 1e-6
            anat["velocity_changed_a_to_b"] += int(vchg)
            # 只算真正的盘盘碰撞：隐藏期间 k 的速度在非墙非柱处改变
        for kind in ("T2", "T3", "T4"):
            for vn, kw in VARIANTS.items():
                if vn != "base" and kind == "T2":
                    continue
                vlog = [] if (vn == "base" and kind in ("T3", "T4")) else None
                out, trks = track(pillars, dets, kind, min_pts=kw.get("min_pts", 2), gate=kw.get("gate", (0.6, 1.5)), neg=kw.get("neg", False),
                                  poses=poses, truth_state=states if kw.get("truth") else None, vel_log=vlog)
                ntracks[f"{kind}/{vn}"].append(len(trks))
                for r in X.score(ev, out):
                    rows[f"{kind}/{vn}"].append((w, (r["k"], r["a"], r["b"]), r["correct"], r))
                if vlog is not None:  # 事件 a 时刻的速度误差，按当时可见段长度分组
                    byt = {(t, i): (v, n) for t, i, v, n in vlog}
                    for e in ev:
                        if (e["a"], e["k"]) in byt:
                            v, n = byt[(e["a"], e["k"])]
                            verr[f"{kind}/n={min(n, 6)}"].append(float(np.linalg.norm(v - states[e["a"]][1][e["k"]])))
        for r in X.oracle(states, ev, pillars):
            t5err.append(r["err"])
        if (w + 1) % 10 == 0:
            print(f"[{time.monotonic() - T0:6.1f}s] {nd} disks world {w + 1}", flush=True)
    C = {}
    allsel, coll, nocoll = (lambda e: True), (lambda e: e["collision"]), (lambda e: not e["collision"])
    C["acc"] = {k: {"all": round(float(np.mean([c for *_, c, e in v])), 4), "collision": round(float(np.mean([c for *_, c, e in v if e["collision"]])), 4),
                    "n_all": len(v), "n_coll": sum(e["collision"] for *_, e in v)} for k, v in rows.items()}
    C["T4_minus_T3_collision"] = {vn: boot(rows[f"T4/{vn}"], rows[f"T3/{vn}"], coll) for vn in VARIANTS}
    C["T4_minus_T3_all"] = {vn: boot(rows[f"T4/{vn}"], rows[f"T3/{vn}"], allsel) for vn in VARIANTS}
    C["H2_standin_T4_minus_T3_all"] = boot(rows["T4/base"], rows["T3/base"], allsel)
    C["H2_standin_T4_minus_T2_all"] = boot(rows["T4/base"], rows["T2/base"], allsel)
    C["velocity_error_at_a"] = {k: [round(float(np.median(v)), 3), round(float(np.mean(v)), 3), len(v)] for k, v in sorted(verr.items())}
    C["collision_anatomy"] = dict(anat)
    C["T5_err"] = {"max": float(np.max(t5err)), "n_nonzero": int(np.sum(np.array(t5err) > 1e-9)), "n": len(t5err)}
    C["tracks_created_mean"] = {k: round(float(np.mean(v)), 1) for k, v in ntracks.items()}
    res["configs"][nd] = C
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({nd: {k: C[k] for k in ("T4_minus_T3_collision", "H2_standin_T4_minus_T3_all", "collision_anatomy", "T5_err")}}, ensure_ascii=False), flush=True)
res["seconds"] = round(time.monotonic() - T0, 1)
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", res["seconds"], flush=True)
