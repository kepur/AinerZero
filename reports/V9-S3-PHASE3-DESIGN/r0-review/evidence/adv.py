"""S3 第三阶段 r0 设计的对抗检查（复核者自写，不改被审文件）。

只导入隔离副本里的 explore.py / explore2.py 复用世界序列和 R2 条目；纯 CPU，不导入 MLX。
用法：adv.py <副本根> <命名空间> <世界数> <输出 json>
命名空间只用 s3p3x-explore 或复核者自起的 s3p3x-rv1109。
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
_SEEN = collections.Counter()
_orig_seed = X.derive_seed


def _audit_seed(ns, *keys):
    _SEEN[ns] += 1
    return _orig_seed(ns, *keys)


X.derive_seed = _audit_seed
spec = X.spec
CFG = dict(P=4, MV=4, E=12, q=0.3, reloc_at=6, reloc_p=0.5, match_d=5.0, match_sim=1.0, window=3)
ALPHAS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
OFFS = [0, 1, 2, 3, 5]
T0 = time.monotonic()


def r2_update(votes, slow, rollback):
    """explore2.Items.absorb_episode 里单个条目的 R2 更新，逐字照抄。"""
    toks = [k for _, k in votes]
    if slow is None:
        cnt = collections.Counter(toks)
        best = [k for k, n in cnt.items() if n >= 2]
        if best:
            return max(best, key=lambda k: (cnt[k], -toks[::-1].index(k))), True
    elif rollback:
        k = slow
        last_k = max(i for i, x in enumerate(toks) if x == k) if k in toks else -1
        after = collections.Counter(toks[last_k + 1:])
        best = [x for x, n in after.items() if n >= 2 and x != k]
        if best:
            return max(best, key=lambda x: (after[x], -toks[::-1].index(x))), True
    return slow, False


class StatItems(X2.Items):
    """与 explore2.Items 相同，另记歧义统计。每回合与原版逐条核对。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.obs_cells = []  # per item: Counter of truth cells of its observations
        self.st = collections.Counter()

    def absorb_episode(self, A, e):
        per = collections.defaultdict(collections.Counter)
        for i in X2.dwell_observations(A, e):
            j = self.match(A["xy"][i], A["ter"][i])
            if j is None:
                self.anchor_xy.append(A["xy"][i].copy())
                self.anchor_ter.append(A["ter"][i].copy())
                self.votes.append([])
                self.slow.append(None)
                self.cell.append(tuple(A["cell"][i]))
                self.obs_cells.append(collections.Counter())
                j = len(self.slow) - 1
            per[j][int(A["tok"][i])] += 1
            self.obs_cells[j][tuple(A["cell"][i])] += 1
        changed = False
        for j, c in per.items():
            mc = c.most_common()
            self.st["item_episode_votes"] += 1
            if len(mc) > 1:
                self.st["item_episode_multi_token"] += 1
                if mc[0][1] == mc[1][1]:
                    self.st["item_episode_vote_tie"] += 1
            v = c.most_common(1)[0][0]
            self.votes[j].append((e, v))
            new, ch = r2_update(self.votes[j], self.slow[j], self.rollback)
            self.slow[j] = new
            changed |= ch
        if changed:
            self.versions.append(tuple((j, s) for j, s in enumerate(self.slow) if s is not None))


class TruthItems:
    """诊断：用真值格子认地方，规则仍是 R2。"""

    def __init__(self, rollback):
        self.rollback = rollback
        self.votes = collections.defaultdict(list)
        self.slow = {}

    def absorb_episode(self, A, e):
        per = collections.defaultdict(collections.Counter)
        for i in X2.dwell_observations(A, e):
            per[tuple(A["cell"][i])][int(A["tok"][i])] += 1
        for c, cnt in per.items():
            self.votes[c].append((e, cnt.most_common(1)[0][0]))
            self.slow[c], _ = r2_update(self.votes[c], self.slow.get(c), self.rollback)


def offset_arrays(A, w, k):
    if k == 0:
        return A
    B = dict(A)
    rng = random.Random(f"rv1109-offset-{NS}-{w}-{k}")
    xy = A["xy"].copy()
    for e in np.unique(A["ep"]):
        dx, dy = rng.randint(-k, k), rng.randint(-k, k)
        xy[A["ep"] == e] += (dx, dy)
    B["xy"] = xy
    return B


def mode_latest(votes):
    toks = [k for _, k in votes]
    cnt = collections.Counter(toks)
    return max(cnt, key=lambda k: (cnt[k], -toks[::-1].index(k))), toks[-1]


FAST = []   # rows: dict per within-episode event
PERS = []   # rows: dict per persistent-cell query
STAT = collections.Counter()
VERS = []

for w in range(NW):
    layout, pcells, relocated, eps = X.world_sequence(w, **CFG)
    allrec = []
    for e, ep in enumerate(eps):
        allrec += X.records_of(ep["raw"], e)
    A0 = X.arrays(allrec)
    start = {e: int(np.flatnonzero(A0["ep"] == e)[0]) for e in range(len(eps))}
    gtime = A0["ep"] * spec.T + A0["t"]
    for k in OFFS:
        A = offset_arrays(A0, w, k)
        # ---------- within-episode readout ----------
        for e, ep in enumerate(eps):
            for ev in ep["raw"]["events"]:
                if ev["bucket"] != spec.BUCKET_LONG or not ev["swapped"]:
                    continue
                qi = start[e] + ev["t"]
                qxy, qter = A["xy"][qi], A["ter"][qi]
                cur = np.flatnonzero((A["ep"] == e) & (A["t"] <= ev["t"] - 5))
                uni = np.flatnonzero((A["ep"] < e) | ((A["ep"] == e) & (A["t"] <= ev["t"] - 5)))
                row = {"w": w, "e": e, "k": k}

                def pick(idx, extra=0.0):
                    s, d, sim = X.score(A, idx, qxy, qter)
                    return idx[np.argmax(s + extra + 1e-6 * gtime[idx])], d, sim

                b, _, _ = pick(cur)
                row["C"] = int(A["tok"][b] == ev["answer"])
                b, d, sim = pick(uni)
                row["U0"] = int(A["tok"][b] == ev["answer"])
                if k == 0:
                    age = (e - A["ep"][uni]).astype(float)
                    for a in ALPHAS:
                        b, _, _ = pick(uni, extra=-a * age)
                        row[f"U_rec{a}"] = int(A["tok"][b] == ev["answer"])
                    for nm, idx in (("C_thr_latest", cur), ("U_thr_latest", uni)):
                        s, d, sim = X.score(A, idx, qxy, qter)
                        ok = idx[(d <= CFG["match_d"]) & (sim >= CFG["match_sim"])]
                        bb = ok[np.argmax(gtime[ok])] if len(ok) else idx[np.argmax(s + 1e-6 * gtime[idx])]
                        row[nm] = int(A["tok"][bb] == ev["answer"])
                    # 统一池里，往回合记录是否赢过当前回合正确记录
                    row["U0_won_by_past"] = int(A["ep"][pick(uni)[0]] < e)
                FAST.append(row)
        # ---------- persistent-cell queries ----------
        G = StatItems(CFG["match_d"], CFG["match_sim"], rollback=True) if k == 0 else X2.Items(CFG["match_d"], CFG["match_sim"], rollback=True)
        G4 = X2.Items(CFG["match_d"], CFG["match_sim"], rollback=False)
        Gref = X2.Items(CFG["match_d"], CFG["match_sim"], rollback=True) if k == 0 else None
        GT, GT4 = TruthItems(True), TruthItems(False)
        obs_past = []
        for e, ep in enumerate(eps):
            pos = [(int(s["truth"]["x"]), int(s["truth"]["y"])) for s in ep["raw"]["steps"]]
            if e > 0:
                for c in pcells:
                    hits = [t for t, p in enumerate(pos) if p == c]
                    if not hits:
                        continue
                    t_first = hits[0]
                    qi = start[e] + t_first
                    answer = ep["regime"][c]
                    shown = int(A["tok"][qi])
                    post = e >= CFG["reloc_at"]
                    per = "post_reloc" if post and c in relocated else ("post_kept" if post else "pre")
                    kind = "decoy" if ep["decoy"][c] else "clean"
                    op = np.array(obs_past, dtype=np.int64)
                    latest, latest_t = shown, shown
                    if len(op):
                        d = np.abs(A["xy"][op] - A["xy"][qi]).sum(1)
                        sim = (A["ter"][op] == A["ter"][qi]).mean(1)
                        m = op[(d <= CFG["match_d"]) & (sim >= CFG["match_sim"])]
                        if len(m):
                            latest = int(A["tok"][m[np.argmax(gtime[m])]])
                        mt = op[(A["cell"][op] == np.array(c)).all(1)]
                        if len(mt):
                            latest_t = int(A["tok"][mt[np.argmax(gtime[mt])]])
                    j = G.match(A["xy"][qi], A["ter"][qi], prefer_slow=True)
                    j4 = G4.match(A["xy"][qi], A["ter"][qi], prefer_slow=True)
                    preds = {"C": shown, "L": latest,
                             "G": G.slow[j] if j is not None else latest,
                             "GNR": G4.slow[j4] if j4 is not None else latest,
                             "LT": latest_t,
                             "GT": GT.slow.get(c) if GT.slow.get(c) is not None else latest_t,
                             "GNRT": GT4.slow.get(c) if GT4.slow.get(c) is not None else latest_t}
                    row = {"w": w, "e": e, "k": k, "kind": kind, "per": per, "ans": answer}
                    if k == 0:
                        ja = G.match(A["xy"][qi], A["ter"][qi], prefer_slow=False)
                        if ja is None:
                            preds["MODE"] = preds["LAST_ITEM"] = preds["G_any"] = latest
                        else:
                            preds["MODE"], preds["LAST_ITEM"] = mode_latest(G.votes[ja])
                            preds["G_any"] = G.slow[ja] if G.slow[ja] is not None else latest
                        row["any_ne_slow"] = int(ja is not None and j is not None and ja != j)
                        row["slow_hit"] = int(j is not None)
                        row["slow_right_cell"] = int(j is not None and G.cell[j] == c)
                        # 时间维度的独立推导：本格在回合 0 的固定值是否等于答案
                        row["answer_eq_ep0_value"] = int(answer == eps[0]["regime"][c])
                        # 同一个格子：若查询改用最后一次到达
                        tl = hits[-1]
                        row["C_last_arrival"] = int(int(A["tok"][start[e] + tl]) == answer)
                    for nm, p in preds.items():
                        row[nm] = int(p == answer)
                    PERS.append(row)
            if k == 0:
                G.absorb_episode(A, e)
                Gref.absorb_episode(A, e)
                assert G.slow == Gref.slow and G.versions == Gref.versions, ("StatItems diverged", w, e)
            else:
                G.absorb_episode(A, e)
            G4.absorb_episode(A, e)
            GT.absorb_episode(A, e)
            GT4.absorb_episode(A, e)
            obs_past += X2.dwell_observations(A, e)
        if k == 0:
            STAT.update(G.st)
            STAT["items"] += len(G.slow)
            STAT["items_multi_cell"] += sum(len(oc) > 1 for oc in G.obs_cells)
            STAT["obs_total"] += sum(sum(oc.values()) for oc in G.obs_cells)
            STAT["obs_off_anchor_cell"] += sum(sum(n for cc, n in oc.items() if cc != G.cell[j]) for j, oc in enumerate(G.obs_cells))
            for c in pcells:
                n_items = sum(1 for oc in G.obs_cells if c in oc)
                STAT["pcell_items_total"] += n_items
                STAT["pcell_count"] += 1
                STAT[f"pcell_items_{min(n_items, 4)}"] += 1
            slow_final = [(j, s) for j, s in enumerate(G.slow) if s is not None]
            STAT["slow_final"] += len(slow_final)
            STAT["slow_final_on_pcell"] += sum(G.cell[j] in pcells for j, _ in slow_final)
            VERS.append(len(G.versions) - 1)
    if (w + 1) % 25 == 0:
        print(f"[{time.monotonic() - T0:6.1f}s] world {w + 1}", flush=True)


# ---------------- statistics ----------------
def boot(rows, a, b, sel, B=10000, seed=20261110):
    rows = [r for r in rows if sel(r)]
    if not rows:
        return None
    ws = sorted({r["w"] for r in rows})
    wi = {w: i for i, w in enumerate(ws)}
    diff = np.zeros(len(ws)); n = np.zeros(len(ws))
    for r in rows:
        diff[wi[r["w"]]] += r[a] - (r[b] if isinstance(b, str) else b)
        n[wi[r["w"]]] += 1
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ws), size=(B, len(ws)))
    est = diff[idx].sum(1) / n[idx].sum(1)
    return {"delta": round(float(diff.sum() / n.sum()), 4), "lo": round(float(np.percentile(est, 2.5)), 4),
            "hi": round(float(np.percentile(est, 97.5)), 4), "n_ev": int(n.sum()), "n_w": len(ws)}


def acc(rows, key, sel):
    v = [r[key] for r in rows if sel(r)]
    return [round(float(np.mean(v)), 4), len(v)] if v else None


F0 = [r for r in FAST if r["k"] == 0]
P0 = [r for r in PERS if r["k"] == 0]
stable_decoy = lambda r: r["kind"] == "decoy" and r["per"] in ("pre", "post_kept")
decoy = lambda r: r["kind"] == "decoy"
reloc = lambda r: r["per"] == "post_reloc"
clean = lambda r: r["kind"] == "clean"
allq = lambda r: True
res = {"ns": NS, "n_worlds": NW, "cfg": CFG, "seconds": round(time.monotonic() - T0, 1),
       "namespaces_seen": dict(_SEEN), "mlx_loaded": "mlx" in sys.modules}
res["within_episode"] = {k: acc(F0, k, allq) for k in F0[0] if k not in ("w", "e", "k")}
res["within_episode_e_ge_1"] = {k: acc(F0, k, lambda r: r["e"] >= 1) for k in ("C", "U0", "U_rec0.5", "U_rec1.0", "U_rec2.0")}
res["H2_C_minus_U"] = {u: boot(F0, "C", u, allq) for u in ["U0"] + [f"U_rec{a}" for a in ALPHAS] + ["U_thr_latest"]}
res["H2_by_episode"] = {e: {"C": acc(F0, "C", lambda r, e=e: r["e"] == e), "U0": acc(F0, "U0", lambda r, e=e: r["e"] == e)} for e in range(CFG["E"])}
keys = ["C", "L", "G", "GNR", "MODE", "LAST_ITEM", "G_any", "LT", "GT", "GNRT", "C_last_arrival"]
res["persistent_acc"] = {g: {k: acc(P0, k, s) for k in keys} for g, s in
                         (("stable_decoy", stable_decoy), ("all_decoy", decoy), ("relocated", reloc), ("clean", clean), ("all", allq))}
res["gates"] = {
    "H1_G_minus_C_decoy": boot(P0, "G", "C", decoy),
    "H3_G_minus_L_stable_decoy": boot(P0, "G", "L", stable_decoy),
    "H4_G_minus_GNR_relocated": boot(P0, "G", "GNR", reloc),
    "cost_L_minus_G_relocated": boot(P0, "L", "G", reloc),
    "cost_C_minus_G_clean": boot(P0, "C", "G", clean),
    "G_minus_C_all_queries": boot(P0, "G", "C", allq),
    "G_minus_MODE_stable_decoy": boot(P0, "G", "MODE", stable_decoy),
    "G_minus_MODE_relocated": boot(P0, "G", "MODE", reloc),
    "G_minus_GNR_stable_decoy": boot(P0, "G", "GNR", stable_decoy),
}
res["anchor_offset"] = {}
for k in OFFS:
    Pk = [r for r in PERS if r["k"] == k]
    Fk = [r for r in FAST if r["k"] == k]
    res["anchor_offset"][k] = {"G_stable_decoy": acc(Pk, "G", stable_decoy), "L_stable_decoy": acc(Pk, "L", stable_decoy),
                               "H3": boot(Pk, "G", "L", stable_decoy, B=2000), "H4": boot(Pk, "G", "GNR", reloc, B=2000),
                               "G_relocated": acc(Pk, "G", reloc), "C_minus_U0": boot(Fk, "C", "U0", allq, B=2000)}
# ---- 合法性门「事件标签」能抓到什么 ----
lab = {}
lab["C_on_decoy"] = acc(P0, "C", decoy); lab["C_on_clean"] = acc(P0, "C", clean)
lab["C_last_arrival_on_decoy"] = acc(P0, "C_last_arrival", decoy); lab["C_last_arrival_on_clean"] = acc(P0, "C_last_arrival", clean)
# 时期标签错一位：把第 6 回合当成换代前
shift = [dict(r, per=("pre" if r["e"] == CFG["reloc_at"] else r["per"])) for r in P0]
lab["offbyone_C_on_decoy"] = acc(shift, "C", decoy); lab["offbyone_C_on_clean"] = acc(shift, "C", clean)
lab["offbyone_H3"] = boot(shift, "G", "L", stable_decoy); lab["offbyone_H4"] = boot(shift, "G", "GNR", reloc)
lab["time_dim_consistency"] = {"stable_answer_eq_ep0": acc(P0, "answer_eq_ep0_value", lambda r: r["per"] in ("pre", "post_kept")),
                               "relocated_answer_eq_ep0": acc(P0, "answer_eq_ep0_value", reloc)}
res["label_gate_probe"] = lab
res["r2_ambiguity"] = dict(STAT)
res["r2_ambiguity"]["query_any_item_ne_best_promoted"] = acc(P0, "any_ne_slow", allq)
res["r2_ambiguity"]["slow_hit_right_cell"] = [sum(r["slow_right_cell"] for r in P0), sum(r["slow_hit"] for r in P0)]
res["versions_per_world"] = {"mean": float(np.mean(VERS)), "max": int(max(VERS))}
res["relocated_by_episode"] = {e: {p: acc(P0, p, lambda r, e=e: reloc(r) and r["e"] == e) for p in ("C", "L", "G", "GNR", "MODE")}
                               for e in range(CFG["reloc_at"], CFG["E"])}
res["slow_answered_frac"] = acc(P0, "slow_hit", allq)
res["counts"] = {"within_episode": len(F0), "stable_decoy": sum(map(stable_decoy, P0)), "relocated": sum(map(reloc, P0)),
                 "all_decoy": sum(map(decoy, P0)), "clean": sum(map(clean, P0))}
json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: res[k] for k in ("counts", "gates")}, ensure_ascii=False, indent=1))
print("done", res["seconds"], flush=True)
