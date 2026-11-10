"""S4 第一阶段 r1：部分碰撞知识的代用模型（每步每对每个成员只决定一次，跳过时冲量和位置修正一起跳过）。
基于 adv_s4r1.py。S4 第一阶段 r1 的对抗检查（复核者自写，不改被审文件）。只用 NumPy，不训练，不导入 MLX。

复用隔离副本 explore2.py 的世界、物理、匈牙利、事件与评分；集合卡尔曼改成可传参：
  q       过程噪声倍数（登记 1 = 位置 0.01、速度 0.05）
  gate    欧氏门限 (基础, 每秒增长)（登记 0.6, 1.5；敏感性档 0.4/1.0、0.8/2.0）
  p_coll  过程模型里盘与盘碰撞生效的概率（1 = E-P，0 = E-B；0.5 = 只懂一半碰撞的代用模型）
另做：碰撞窗口（a→a+1 那一步的接触被排除了多少）；评测时过程模型输入的误差（对照训练增强）；每世界事件数。
用法：adv_s4r1.py <explore2 目录> <命名空间> <世界数> <输出 json> <盘数 逗号分隔>
"""
import collections, json, math, sys, time
import numpy as np

sys.path.insert(0, sys.argv[1])
import explore2 as X  # noqa: E402

NS, NW, OUT = sys.argv[2], int(sys.argv[3]), sys.argv[4]
DISKS = [int(x) for x in sys.argv[5].split(",")]
assert NS in ("s4x-explore", "s4x-rv1110"), NS
X.NS = NS
T0 = time.monotonic()


def physics(p, v, pillars, *, disks=True, p_coll=1.0, rng=None):
    """explore2.physics 的副本；p_coll < 1 时，每个成员的每次盘盘碰撞以 p_coll 的概率生效。"""
    p, v = p.copy(), v.copy()
    B, N, _ = p.shape
    h = X.DT / X.SUB
    pil = np.array([[a, b] for a, b, _ in pillars]) if pillars else np.zeros((0, 2))
    pr = np.array([r for _, _, r in pillars]) if pillars else np.zeros(0)
    keep = (rng.random((B, N, N)) < p_coll) if (p_coll < 1.0 and disks and N > 1) else None
    for _ in range(X.SUB):
        p += v * h
        for d in range(2):
            lo, hi = p[..., d] < X.R, p[..., d] > X.L - X.R
            v[..., d] = np.where(lo, np.abs(v[..., d]), np.where(hi, -np.abs(v[..., d]), v[..., d]))
            p[..., d] = np.clip(p[..., d], X.R, X.L - X.R)
        for c, cr in zip(pil, pr):
            dvec = p - c; dist = np.linalg.norm(dvec, axis=-1, keepdims=True); nrm = dvec / np.maximum(dist, 1e-9)
            hit = dist < cr + X.R; vn = (v * nrm).sum(-1, keepdims=True)
            v = np.where(hit & (vn < 0), v - 2 * vn * nrm, v); p = np.where(hit, c + nrm * (cr + X.R), p)
        if disks and N > 1:
            d = p[:, None, :, :] - p[:, :, None, :]; dist = np.linalg.norm(d, axis=-1); nrm = d / np.maximum(dist, 1e-9)[..., None]
            rel = ((v[:, :, None, :] - v[:, None, :, :]) * nrm).sum(-1)
            iu = np.triu(np.ones((N, N), bool), 1)
            ok = iu[None] & (dist < 2 * X.R) & (dist > 1e-9)
            if keep is not None:
                ok = ok & keep
            app = ok & (rel > 0)
            dv = np.where(app[..., None], rel[..., None] * nrm, 0.0)
            v = v - dv.sum(2) + dv.sum(1)
            ov = np.where(ok, 2 * X.R - dist, 0.0)[..., None] * nrm / 2
            p = p - ov.sum(2) + ov.sum(1)
    return p, v


def enkf(pillars, dets, kind, rng, *, states, q=1.0, gate=(0.6, 1.5), p_coll=1.0, diag=None):
    """explore2.enkf（欧氏关联、不膨胀）的副本，参数可调。kind: CV/B/P/SP。diag 收集过程模型输入的误差。"""
    M = X.M
    P = np.zeros((M, 0, 2)); V = np.zeros((M, 0, 2)); last, ident, born = [], [], []
    out = []
    for t, det in enumerate(dets):
        if P.shape[1]:
            if diag is not None:  # 过程模型此刻的输入：成员相对真值的误差（读真值，只作诊断）
                pt, vt = states[t - 1]
                for k in range(P.shape[1]):
                    if ident[k] is None:
                        continue
                    ep = np.linalg.norm(P[:, k] - pt[ident[k]], axis=-1); evv = np.linalg.norm(V[:, k] - vt[ident[k]], axis=-1)
                    tag = "visible" if last[k] == t - 1 else "hidden"
                    if t - 1 - born[k] < 3:
                        tag = "new_track"
                    diag[f"pos_err/{tag}"].append(float(np.median(ep))); diag[f"vel_err/{tag}"].append(float(np.median(evv)))
                ids = [i for i in ident if i is not None]
                diag["duplicate_tracks"].append(len(ids) - len(set(ids))); diag["tracks"].append(P.shape[1])
                diag["disks_without_track"].append(len(pt) - len(set(ids)))
            if kind == "CV":
                P = P + V * X.DT
            else:
                P, V = physics(P, V, pillars, disks=kind in ("P", "SP"), p_coll=p_coll, rng=rng)
            P = P + rng.normal(0, X.Q_POS * q, P.shape); V = V + rng.normal(0, X.Q_VEL * q, V.shape)
        pos = [d[1] for d in det]
        assign = {}
        if P.shape[1] and pos:
            mu = P.mean(0); z = np.array(pos)
            eu = np.linalg.norm(z[:, None, :] - mu[None], axis=-1)
            for r, c in X.hungarian(eu):
                if eu[r, c] <= gate[0] + gate[1] * X.DT * (t - last[c]):
                    assign[r] = c
        row = []
        for r, (truth, qd) in enumerate(det):
            if r in assign:
                k = assign[r]
                if kind == "SP":
                    p_true, v_true = states[t]; P[:, k] = p_true[truth]; V[:, k] = v_true[truth]
                else:
                    Xs = np.concatenate([P[:, k], V[:, k]], 1); A = Xs - Xs.mean(0)
                    Pxz = A.T @ (P[:, k] - P[:, k].mean(0)) / (M - 1); Pzz = np.cov(P[:, k].T) + np.eye(2) * X.SIGMA ** 2
                    K = Pxz @ np.linalg.inv(Pzz); zp = qd + rng.normal(0, X.SIGMA, (M, 2))
                    Xs = Xs + (zp - P[:, k]) @ K.T; P[:, k], V[:, k] = Xs[:, :2], Xs[:, 2:]
                last[k] = t; ident[k] = truth
                row.append((truth, k))
            else:
                newP = qd + rng.normal(0, X.SIGMA, (M, 1, 2))
                ang = rng.uniform(0, 2 * math.pi, M); spd = rng.uniform(0.6, 1.4, M)
                newV = np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)[:, None, :]
                if kind == "SP":
                    p_true, v_true = states[t]
                    newP = np.broadcast_to(p_true[truth], (M, 1, 2)).copy(); newV = np.broadcast_to(v_true[truth], (M, 1, 2)).copy()
                P = np.concatenate([P, newP], 1); V = np.concatenate([V, newV], 1)
                last.append(t); ident.append(truth); born.append(t)
                row.append((truth, P.shape[1] - 1))
        out.append(row)
    return out, P.shape[1]


def paired(rows, a, b, sel, base=None, top=None, B=4000, seed=20261110):
    """a − b 的差（按世界 bootstrap）；给了 base、top 时另算 C = (a − base)/(top − base)，分子分母同一次抽样。"""
    keyed = {n: {(w, e["k"], e["a"], e["b"]): (w, c) for w, e, c in rows[n] if sel(e)} for n in {a, b} | ({base, top} - {None})}
    keys = sorted(set.intersection(*[set(v) for v in keyed.values()]))
    ws = sorted({k[0] for k in keys}); wi = {w: i for i, w in enumerate(ws)}
    def sums(n):
        s = np.zeros(len(ws)); m = np.zeros(len(ws))
        for k in keys:
            s[wi[k[0]]] += keyed[n][k][1]; m[wi[k[0]]] += 1
        return s, m
    idx = np.random.default_rng(seed).integers(0, len(ws), size=(B, len(ws)))
    sa, m = sums(a); sb, _ = sums(b)
    out = {"n": int(m.sum()), "worlds": len(ws), "acc_a": round(float(sa.sum() / m.sum()), 4), "acc_b": round(float(sb.sum() / m.sum()), 4)}
    d = (sa[idx].sum(1) - sb[idx].sum(1)) / m[idx].sum(1)
    out.update(delta=round(float((sa.sum() - sb.sum()) / m.sum()), 4), lo=round(float(np.percentile(d, 2.5)), 4), hi=round(float(np.percentile(d, 97.5)), 4))
    if base is not None:
        s0, _ = sums(base); s1, _ = sums(top)
        num = sa[idx].sum(1) - s0[idx].sum(1); den = s1[idx].sum(1) - s0[idx].sum(1)
        C = num / den
        out.update(C=round(float((sa.sum() - s0.sum()) / (s1.sum() - s0.sum())), 4), C_lo=round(float(np.percentile(C, 2.5)), 4), C_hi=round(float(np.percentile(C, 97.5)), 4),
                   den=round(float((s1.sum() - s0.sum()) / m.sum()), 4))
    return out


ARMS = {"B": ("B", {}), "P": ("P", {}), "P_step50": ("P", {"p_coll": 0.5}), "P_step25": ("P", {"p_coll": 0.25})}
res = {"ns": NS, "n_worlds": NW, "configs": {}}
for nd in DISKS:
    cfg = dict(n_disks=nd, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0)
    rows = collections.defaultdict(list); diag = collections.defaultdict(list)
    per_world = []; window = collections.Counter(); ntr = collections.defaultdict(list)
    for w in range(NW):
        pillars, states, vis, dets, contacts = X.episode(w, **cfg)
        ev = X.reappearances(vis, contacts)
        n_coll_scored = 0
        for e in ev:
            k, a, b = e["k"], e["a"], e["b"]
            first_step = any(k in pair for pair in contacts[a])            # 接触发生在 a→a+1 这一步
            later = e["collision"]
            window["events"] += 1; window["collision_registered"] += int(later)
            window["contact_only_in_step_a"] += int(first_step and not later)
        for name, (kind, kw) in ARMS.items():
            out, nt = enkf(pillars, dets, kind, np.random.default_rng(X.seed_of("filter", w, kind)), states=states,
                           diag=diag if name == "P" else None, **kw)
            sc = X.score(ev, out)
            rows[name] += [(w, r, r["correct"]) for r in sc]
            ntr[name].append(nt)
            if name == "P":
                n_coll_scored = sum(r["collision"] for r in sc)
        per_world.append(n_coll_scored)
        if (w + 1) % 10 == 0:
            print(f"[{time.monotonic() - T0:6.1f}s] {nd} disks world {w + 1}", flush=True)
    coll, allsel = (lambda e: e["collision"]), (lambda e: True)
    Cf = {}
    Cf["acc"] = {n: {"all": round(float(np.mean([c for _, _, c in v])), 4), "collision": round(float(np.mean([c for _, e, c in v if e["collision"]])), 4),
                     "n_coll": sum(e["collision"] for _, e, _ in v)} for n, v in rows.items()}
    Cf["C_standins"] = {n: paired(rows, n, "B", coll, base="B", top="P") for n in ("P_step50", "P_step25")}
    Cf["collision_window"] = dict(window)
    pw = np.array(per_world, float)
    Cf["collision_events_per_world"] = {"mean": round(float(pw.mean()), 2), "sd": round(float(pw.std(ddof=1)), 2), "n_worlds": len(pw)}
    Cf["eval_inputs_under_P"] = {k: [round(float(np.median(v)), 3), round(float(np.percentile(v, 90)), 3), len(v)] for k, v in sorted(diag.items())}
    Cf["tracks_mean"] = {n: round(float(np.mean(v)), 2) for n, v in ntr.items()}
    res["configs"][nd] = Cf
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({nd: Cf["C_standins"]}, ensure_ascii=False), flush=True)
res["seconds"] = round(time.monotonic() - T0, 1)
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print("done", res["seconds"], flush=True)
