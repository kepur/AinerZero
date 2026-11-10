"""S3 第三阶段 r0：H1 的负对照、学生可见路由、起点查询、认地方并列。复核者自写。

用法：adv2.py <副本根> <命名空间> <世界数> <输出 json>。只用 s3p3x-explore 或 s3p3x-rv1109。
"""
import collections
import json
import random
import sys
import time

import numpy as np

COPY, NS, NW, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
assert NS in ("s3p3x-explore", "s3p3x-rv1109"), NS
sys.path.insert(0, COPY + "/reports/V9-S3-PHASE3-DESIGN/tier1-explore")
import explore as X  # noqa: E402
import explore2 as X2  # noqa: E402

X.NS = NS
spec = X.spec
CFG = dict(P=4, MV=4, E=12, q=0.3, reloc_at=6, reloc_p=0.5, match_d=5.0, match_sim=1.0, window=3)
TOK = list(spec.F1_TOKENS)
T0 = time.monotonic()
TIES = collections.Counter()


class TieItems(X2.Items):
    def match(self, xy, ter, prefer_slow=False):
        j = super().match(xy, ter, prefer_slow)
        if j is not None:
            axy = np.array(self.anchor_xy); ater = np.array(self.anchor_ter)
            d = np.abs(axy - xy).sum(1); sim = (ater == ter).mean(1)
            ok = (d <= self.D) & (sim >= self.S)
            if prefer_slow:
                ok &= np.array([s is not None for s in self.slow])
            sc = np.where(ok, sim * X.SCALE * X.LAM - d, -1e18)
            TIES["match_calls_" + ("query" if prefer_slow else "absorb")] += 1
            TIES["match_ties_" + ("query" if prefer_slow else "absorb")] += int((sc == sc.max()).sum() > 1)
        return j


rows = []
for w in range(NW):
    layout, pcells, relocated, eps = X.world_sequence(w, **CFG)
    allrec = []
    for e, ep in enumerate(eps):
        allrec += X.records_of(ep["raw"], e)
    A = X.arrays(allrec)
    start = {e: int(np.flatnonzero(A["ep"] == e)[0]) for e in range(len(eps))}
    gtime = A["ep"] * spec.T + A["t"]
    G = TieItems(CFG["match_d"], CFG["match_sim"], rollback=True)
    perm_rng = random.Random(f"rv1109-perm-{NS}-{w}")
    perm = dict(zip(TOK, perm_rng.sample(TOK, len(TOK))))  # 每个世界一个固定的随机置换：内容与真值无关
    rnd = random.Random(f"rv1109-rand-{NS}-{w}")
    obs_past = []
    for e, ep in enumerate(eps):
        pos = [(int(s["truth"]["x"]), int(s["truth"]["y"])) for s in ep["raw"]["steps"]]
        if e > 0:
            for c in pcells:
                hits = [t for t, p in enumerate(pos) if p == c]
                if not hits:
                    continue
                t = hits[0]
                qi = start[e] + t
                answer = ep["regime"][c]
                shown = int(A["tok"][qi])
                post = e >= CFG["reloc_at"]
                per = "post_reloc" if post and c in relocated else ("post_kept" if post else "pre")
                kind = "decoy" if ep["decoy"][c] else "clean"
                op = np.array(obs_past, dtype=np.int64)
                latest = shown
                if len(op):
                    d = np.abs(A["xy"][op] - A["xy"][qi]).sum(1)
                    sim = (A["ter"][op] == A["ter"][qi]).mean(1)
                    m = op[(d <= CFG["match_d"]) & (sim >= CFG["match_sim"])]
                    if len(m):
                        latest = int(A["tok"][m[np.argmax(gtime[m])]])
                j = G.match(A["xy"][qi], A["ter"][qi], prefer_slow=True)
                g = G.slow[j] if j is not None else latest
                # 学生可见路由：当前回合若已有过门槛的记录（t ≤ 查询 − 5），就按 FAST 回答
                cur = np.flatnonzero((A["ep"] == e) & (A["t"] <= t - 5))
                fast_hit, fast_pred = False, None
                if len(cur):
                    s, d2, sim2 = X.score(A, cur, A["xy"][qi], A["ter"][qi])
                    ok = (d2 <= CFG["match_d"]) & (sim2 >= CFG["match_sim"])
                    if ok.any():
                        fast_hit = True
                        b = cur[np.argmax(np.where(ok, s, -1e18) + 1e-6 * gtime[cur])]
                        fast_pred = int(A["tok"][b])
                preds = {"C": shown, "G": g, "G_perm": perm[g] if g in perm else g,
                         "RAND_NE_SHOWN": rnd.choice([k for k in TOK if k != shown]), "RAND": rnd.choice(TOK),
                         "G_router_fastfirst": fast_pred if fast_hit else g}
                r = {"w": w, "e": e, "kind": kind, "per": per, "t0": int(t == 0), "fast_hit": int(fast_hit)}
                for nm, p in preds.items():
                    r[nm] = int(p == answer)
                rows.append(r)
        G.absorb_episode(A, e)
        obs_past += X2.dwell_observations(A, e)
    if (w + 1) % 25 == 0:
        print(f"[{time.monotonic() - T0:6.1f}s] world {w + 1}", flush=True)


def boot(rows, a, b, sel, B=10000, seed=20261110):
    rows = [r for r in rows if sel(r)]
    ws = sorted({r["w"] for r in rows}); wi = {w: i for i, w in enumerate(ws)}
    diff = np.zeros(len(ws)); n = np.zeros(len(ws))
    for r in rows:
        diff[wi[r["w"]]] += r[a] - (r[b] if isinstance(b, str) else b); n[wi[r["w"]]] += 1
    idx = np.random.default_rng(seed).integers(0, len(ws), size=(B, len(ws)))
    est = diff[idx].sum(1) / n[idx].sum(1)
    return {"delta": round(float(diff.sum() / n.sum()), 4), "lo": round(float(np.percentile(est, 2.5)), 4),
            "hi": round(float(np.percentile(est, 97.5)), 4), "n_ev": int(n.sum()), "n_w": len(ws)}


def acc(key, sel):
    v = [r[key] for r in rows if sel(r)]
    return [round(float(np.mean(v)), 4), len(v)] if v else None


decoy = lambda r: r["kind"] == "decoy"
stable_decoy = lambda r: decoy(r) and r["per"] in ("pre", "post_kept")
res = {"ns": NS, "n_worlds": NW, "seconds": round(time.monotonic() - T0, 1)}
res["H1_as_registered_G_minus_C"] = boot(rows, "G", "C", decoy)
res["H1_negative_controls_minus_C"] = {k: boot(rows, k, "C", decoy) for k in ("G_perm", "RAND_NE_SHOWN", "RAND")}
res["H1_G_minus_G_perm"] = boot(rows, "G", "G_perm", decoy)
res["router"] = {"fast_hit_rate_all_queries": acc("fast_hit", lambda r: True),
                 "fast_hit_rate_decoy": acc("fast_hit", decoy),
                 "G_decoy": acc("G", decoy), "G_router_fastfirst_decoy": acc("G_router_fastfirst", decoy),
                 "G_stable_decoy": acc("G", stable_decoy), "G_router_fastfirst_stable_decoy": acc("G_router_fastfirst", stable_decoy),
                 "G_all": acc("G", lambda r: True), "G_router_fastfirst_all": acc("G_router_fastfirst", lambda r: True)}
res["start_cell_queries"] = {"frac_t0_all": acc("t0", lambda r: True), "frac_t0_stable_decoy": acc("t0", stable_decoy),
                             "G_stable_decoy_t0": acc("G", lambda r: stable_decoy(r) and r["t0"]),
                             "G_stable_decoy_not_t0": acc("G", lambda r: stable_decoy(r) and not r["t0"])}
res["match_ties"] = dict(TIES)
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
