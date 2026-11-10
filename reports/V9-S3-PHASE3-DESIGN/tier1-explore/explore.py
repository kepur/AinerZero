"""S3 第三阶段设计前的一级可行性摸底。未登记，只用来定设计，不作任何结论。

纯 CPU，不导入 MLX，不训练。只用专用命名空间 s3p3x-explore，
以后登记的 train/dev/final/probe 一律用别的名字。不改任何冻结文件。

问四件事：
  1. 同一世界连续多回合时，各类事件够不够：长间隔已换的回合内事件、
     固定格的首次到达、其中被临时遮盖（诱饵）的、换代后被改的。
  2. 跨回合时里程计漂移多大：同一格在不同回合的估计位姿差多少。
  3. 用完美读出（直接取记录看到的 token），几种晋升规则在诱饵事件和
     换代事件上能到多少：不用记忆、最近一次、门控晋升、门控不回滚、
     真值定位的门控（拆开定位误差和规则误差）。
  4. 把往回合的记录放进同一个检索池，手工线索对回合内读回的干扰有多大。
"""
from __future__ import annotations

import collections
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s2.world import make_layout
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import ContentState
from ainerzero.v9.experiments.s3.data import derive_seed
from ainerzero.v9.experiments.s3.store import parse_student_step
from ainerzero.v9.experiments.s3.tour import run_tour
from ainerzero.v9.experiments.s3.world import get_connected_free_cells

NS = "s3p3x-explore"
OUT = Path(__file__).resolve().parent
NEVER = 10**9
LAM, SCALE = 1.0, 49.0
T0 = time.monotonic()


def say(*x):
    print(f"[{time.monotonic() - T0:7.1f}s]", *x, flush=True)


def separated(cells, m, rng, banned=(), min_dist=4):
    pool = [c for c in cells if c not in banned]
    rng.shuffle(pool)
    chosen = []
    for c in pool:
        if all(abs(c[0] - x[0]) + abs(c[1] - x[1]) >= min_dist for x in list(chosen) + list(banned)):
            chosen.append(c)
            if len(chosen) == m:
                return chosen
    for c in pool:
        if c not in chosen:
            chosen.append(c)
            if len(chosen) == m:
                break
    return chosen


def world_sequence(w, *, P, MV, E, q, reloc_at, reloc_p, **_):
    layout = make_layout(derive_seed(NS, "world", w))
    free = get_connected_free_cells(layout)
    wr = random.Random(derive_seed(NS, "persist", w))
    pcells = separated(free, P, wr)
    tok0 = {c: wr.choice(spec.F1_TOKENS) for c in pcells}
    tok1 = dict(tok0)
    relocated = set()
    for c in pcells:
        if wr.random() < reloc_p:
            tok1[c] = wr.choice([k for k in spec.F1_TOKENS if k != tok0[c]])
            relocated.add(c)
    eps = []
    for e in range(E):
        er = random.Random(derive_seed(NS, "ep", w, e))
        regime = tok1 if e >= reloc_at else tok0
        vcells = separated(free, MV, er, banned=pcells)
        shown, swap, new = {}, {}, {}
        decoy = {}
        for c in pcells:
            d = er.random() < q
            decoy[c] = d
            shown[c] = er.choice([k for k in spec.F1_TOKENS if k != regime[c]]) if d else regime[c]
            swap[c] = NEVER
            new[c] = [k for k in spec.F1_TOKENS if k != shown[c]][0]
        for c in vcells:
            shown[c] = er.choice(spec.F1_TOKENS)
            new[c] = er.choice([k for k in spec.F1_TOKENS if k != shown[c]])
            swap[c] = er.randint(130, 220)
        cells = list(pcells) + list(vcells)
        er.shuffle(cells)
        cs = ContentState(tuple(cells), shown, swap, new, "F1")
        raw = run_tour(layout, cs, er, t_max=spec.T, p_slip=spec.P_SLIP, noise=spec.NOISE)
        eps.append({"raw": raw, "regime": dict(regime), "decoy": decoy, "vcells": set(vcells)})
    return layout, pcells, relocated, eps


def records_of(raw, e):
    out = []
    for s in raw["steps"]:
        r = parse_student_step(s)
        out.append((e, r.t, r.est_pose[0], r.est_pose[1], r.world_terrain.reshape(-1).copy(), r.observed_token,
                    int(s["truth"]["x"]), int(s["truth"]["y"])))
    return out


def arrays(recs):
    return {
        "ep": np.array([r[0] for r in recs], dtype=np.int32),
        "t": np.array([r[1] for r in recs], dtype=np.int32),
        "xy": np.array([(r[2], r[3]) for r in recs], dtype=np.float64),
        "ter": np.stack([r[4] for r in recs]).astype(np.int8),
        "tok": np.array([r[5] for r in recs], dtype=np.int32),
        "cell": np.array([(r[6], r[7]) for r in recs], dtype=np.int32),
    }


def score(A, idx, qxy, qter):
    d = np.abs(A["xy"][idx] - qxy).sum(1)
    sim = (A["ter"][idx] == qter).mean(1)
    return sim * SCALE * LAM - d, d, sim


def votes_by_episode(eps_of, toks):
    """One vote per episode: the most common non-zero token that episode showed at the place."""
    per = collections.defaultdict(collections.Counter)
    for e, k in zip(eps_of, toks):
        if k:
            per[int(e)][int(k)] += 1
    return {e: c.most_common(1)[0][0] for e, c in per.items()}


def gated(votes, *, window, rollback):
    """Replay the promotion rule episode by episode; return the SLOW value after the last vote."""
    slow = None
    hist = []
    for e in sorted(votes):
        hist.append(votes[e])
        recent = collections.Counter(hist[-window:])
        best = [k for k, n in recent.items() if n >= 2]
        if slow is None:
            if best:
                slow = max(best, key=lambda k: (recent[k], -hist[::-1].index(k)))
        elif rollback and slow not in best and best:
            slow = max(best, key=lambda k: (recent[k], -hist[::-1].index(k)))
    return slow


def run(cfg, n_worlds):
    say("cfg", cfg)
    acc = collections.defaultdict(list)
    counts = collections.Counter()
    drift = []
    cover = []
    for w in range(n_worlds):
        layout, pcells, relocated, eps = world_sequence(w, **cfg)
        allrec = []
        for e, ep in enumerate(eps):
            allrec += records_of(ep["raw"], e)
        A = arrays(allrec)
        start = {e: int(np.flatnonzero(A["ep"] == e)[0]) for e in range(len(eps))}
        for e, ep in enumerate(eps):
            raw = ep["raw"]
            pos = [(int(s["truth"]["x"]), int(s["truth"]["y"])) for s in raw["steps"]]
            cover.append(np.mean([c in pos for c in pcells]))
            # --- within-episode readout events (FAST) ---
            for ev in raw["events"]:
                if ev["bucket"] != spec.BUCKET_LONG or not ev["swapped"]:
                    continue
                counts["fast_long_swapped"] += 1
                qi = start[e] + ev["t"]
                qxy, qter = A["xy"][qi], A["ter"][qi]
                cur = np.flatnonzero((A["ep"] == e) & (A["t"] <= ev["t"] - 5))
                uni = np.flatnonzero((A["ep"] < e) | ((A["ep"] == e) & (A["t"] <= ev["t"] - 5)))
                for name, idx in (("fast_only", cur), ("unified", uni)):
                    s, _, _ = score(A, idx, qxy, qter)
                    gtime = A["ep"][idx] * spec.T + A["t"][idx]
                    best = idx[np.argmax(s + 1e-6 * gtime)]
                    acc[f"fast/{name}"].append(int(A["tok"][best] == ev["answer"]))
            # --- persistent-cell first arrivals (cross-episode) ---
            if e == 0:
                continue
            for c in pcells:
                hits = [t for t, p in enumerate(pos) if p == c]
                if not hits:
                    continue
                t = hits[0]
                qi = start[e] + t
                answer = ep["regime"][c]
                shown = int(A["tok"][qi])
                kind = "decoy" if ep["decoy"][c] else "clean"
                post = e >= cfg["reloc_at"]
                tag = kind + ("/post_reloc" if post and c in relocated else ("/post_kept" if post else "/pre"))
                counts[tag] += 1
                past = np.flatnonzero((A["ep"] < e) & (A["tok"] > 0))
                truth_past = past[(A["cell"][past] == np.array(c)).all(1)]
                if len(truth_past):
                    same = A["xy"][truth_past] - A["xy"][qi]
                    drift.extend(np.abs(same).sum(1).tolist())
                s, d, sim = score(A, past, A["xy"][qi], A["ter"][qi])
                match = past[(d <= cfg["match_d"]) & (sim >= cfg["match_sim"])]
                if len(truth_past):
                    counts["has_truth_history"] += 1
                if len(match):
                    counts["has_est_match"] += 1
                    counts["est_match_pure"] += int((A["cell"][match] == np.array(c)).all(1).all())
                preds = {"P0_copy": shown, "O_truth": answer}
                for keyname, pool in (("est", match), ("truthcell", truth_past)):
                    if len(pool) == 0:
                        preds[f"P1_latest/{keyname}"] = shown
                        preds[f"P2_gated/{keyname}"] = shown
                        preds[f"P4_norollback/{keyname}"] = shown
                        continue
                    gt = A["ep"][pool] * spec.T + A["t"][pool]
                    preds[f"P1_latest/{keyname}"] = int(A["tok"][pool[np.argmax(gt)]])
                    v = votes_by_episode(A["ep"][pool], A["tok"][pool])
                    for nm, rb in (("P2_gated", True), ("P4_norollback", False)):
                        sv = gated(v, window=cfg["window"], rollback=rb)
                        preds[f"{nm}/{keyname}"] = sv if sv is not None else preds[f"P1_latest/{keyname}"]
                    seq = [v[x] for x in sorted(v)]
                    cnt = collections.Counter(seq)
                    preds[f"P5_mode/{keyname}"] = max(cnt, key=lambda k: (cnt[k], -seq[::-1].index(k)))
                for k, p in preds.items():
                    acc[f"{tag}/{k}"].append(int(p == answer))
        if (w + 1) % 25 == 0:
            say("world", w + 1)
    res = {"cfg": cfg, "n_worlds": n_worlds, "counts": dict(counts),
           "persistent_coverage_per_episode": float(np.mean(cover)),
           "cross_episode_pose_error": {
               "median": float(np.median(drift)), "p90": float(np.percentile(drift, 90)),
               "frac_le_1": float(np.mean(np.array(drift) <= 1)), "frac_le_3": float(np.mean(np.array(drift) <= 3))},
           "acc": {k: [round(float(np.mean(v)), 4), len(v)] for k, v in sorted(acc.items())}}
    return res


if __name__ == "__main__":
    base = dict(P=4, MV=8, E=12, q=0.3, reloc_at=6, reloc_p=0.5, match_d=3.0, match_sim=1.0, window=3)
    grid = [dict(base), dict(base, MV=4), dict(base, MV=4, match_d=5.0), dict(base, MV=4, match_d=8.0),
            dict(base, MV=4, match_d=5.0, match_sim=0.88), dict(base, MV=4, match_d=5.0, window=5)]
    results = [run(c, 100) for c in grid]
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    say("done")
