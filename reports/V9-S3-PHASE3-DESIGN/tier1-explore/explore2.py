"""S3 第三阶段一级摸底第二轮：显式条目、版本与回滚规则。未登记，不作结论。

只用 s3p3x-explore。纯 CPU，不训练。复用 explore.py 的世界序列生成。
规则 R2（每个条目一票/回合）：
  - 空条目：某个 token 累计 ≥ 2 票（两个不同回合）就晋升。
  - 已晋升 k：在 k 最近一票之后，另一个 token k' 累计 ≥ 2 票，就回滚 k、晋升 k'。
  - 不回滚的对照：晋升后不再改。
查询：最佳匹配的已晋升条目给答案；没有就退回最近一次匹配的观察；再没有就照抄当前。
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import explore as X  # noqa: E402

spec = X.spec
T0 = time.monotonic()


def say(*a):
    print(f"[{time.monotonic() - T0:7.1f}s]", *a, flush=True)


def dwell_observations(A, e):
    """One observation per dwell on a token-bearing cell (by estimated pose)."""
    idx = np.flatnonzero(A["ep"] == e)
    out = []
    prev = None
    for i in idx:
        key = (A["xy"][i][0], A["xy"][i][1], A["tok"][i])
        if A["tok"][i] > 0 and key != prev:
            out.append(i)
        prev = key if A["tok"][i] > 0 else None
    return out


class Items:
    def __init__(self, D, S, rollback):
        self.D, self.S, self.rollback = D, S, rollback
        self.anchor_xy, self.anchor_ter = [], []
        self.votes = []      # per item: list of (episode, token)
        self.slow = []       # per item: token or None
        self.cell = []       # truth cell of the anchor (diagnostic only)
        self.versions = [()]  # tuple of (item, token) snapshots

    def match(self, xy, ter, prefer_slow=False):
        if not self.anchor_xy:
            return None
        axy = np.array(self.anchor_xy)
        ater = np.array(self.anchor_ter)
        d = np.abs(axy - xy).sum(1)
        sim = (ater == ter).mean(1)
        ok = (d <= self.D) & (sim >= self.S)
        if prefer_slow:
            ok &= np.array([s is not None for s in self.slow])
        if not ok.any():
            return None
        sc = np.where(ok, sim * X.SCALE * X.LAM - d, -1e18)
        return int(np.argmax(sc))

    def absorb_episode(self, A, e):
        per = collections.defaultdict(collections.Counter)
        for i in dwell_observations(A, e):
            j = self.match(A["xy"][i], A["ter"][i])
            if j is None:
                self.anchor_xy.append(A["xy"][i].copy())
                self.anchor_ter.append(A["ter"][i].copy())
                self.votes.append([])
                self.slow.append(None)
                self.cell.append(tuple(A["cell"][i]))
                j = len(self.slow) - 1
            per[j][int(A["tok"][i])] += 1
        changed = False
        for j, c in per.items():
            v = c.most_common(1)[0][0]
            self.votes[j].append((e, v))
            toks = [k for _, k in self.votes[j]]
            if self.slow[j] is None:
                cnt = collections.Counter(toks)
                best = [k for k, n in cnt.items() if n >= 2]
                if best:
                    self.slow[j] = max(best, key=lambda k: (cnt[k], -toks[::-1].index(k)))
                    changed = True
            elif self.rollback:
                k = self.slow[j]
                last_k = max(i for i, x in enumerate(toks) if x == k) if k in toks else -1
                after = collections.Counter(toks[last_k + 1:])
                best = [x for x, n in after.items() if n >= 2 and x != k]
                if best:
                    self.slow[j] = max(best, key=lambda x: (after[x], -toks[::-1].index(x)))
                    changed = True
        if changed:
            self.versions.append(tuple((j, s) for j, s in enumerate(self.slow) if s is not None))


def run(cfg, n_worlds):
    say("cfg", cfg)
    acc = collections.defaultdict(list)
    counts = collections.Counter()
    for w in range(n_worlds):
        layout, pcells, relocated, eps = X.world_sequence(w, **cfg)
        allrec = []
        for e, ep in enumerate(eps):
            allrec += X.records_of(ep["raw"], e)
        A = X.arrays(allrec)
        start = {e: int(np.flatnonzero(A["ep"] == e)[0]) for e in range(len(eps))}
        G = Items(cfg["match_d"], cfg["match_sim"], rollback=True)
        G4 = Items(cfg["match_d"], cfg["match_sim"], rollback=False)
        obs_past = []
        for e, ep in enumerate(eps):
            pos = [(int(s["truth"]["x"]), int(s["truth"]["y"])) for s in ep["raw"]["steps"]]
            if e > 0:
                for c in pcells:
                    hits = [t for t, p in enumerate(pos) if p == c]
                    if not hits:
                        continue
                    qi = start[e] + hits[0]
                    answer = ep["regime"][c]
                    shown = int(A["tok"][qi])
                    post = e >= cfg["reloc_at"]
                    tag = ("decoy" if ep["decoy"][c] else "clean") + (
                        "/post_reloc" if post and c in relocated else ("/post_kept" if post else "/pre"))
                    counts[tag] += 1
                    op = np.array(obs_past, dtype=np.int64)
                    latest = shown
                    if len(op):
                        d = np.abs(A["xy"][op] - A["xy"][qi]).sum(1)
                        sim = (A["ter"][op] == A["ter"][qi]).mean(1)
                        m = op[(d <= cfg["match_d"]) & (sim >= cfg["match_sim"])]
                        if len(m):
                            latest = int(A["tok"][m[np.argmax(A["ep"][m] * spec.T + A["t"][m])]])
                    preds = {"P0_copy": shown, "P1_latest": latest, "O": answer}
                    for nm, items in (("P2_gated", G), ("P4_norollback", G4)):
                        j = items.match(A["xy"][qi], A["ter"][qi], prefer_slow=True)
                        preds[nm] = items.slow[j] if j is not None else latest
                        if nm == "P2_gated":
                            counts["p2_slow_hit"] += int(j is not None)
                            counts["p2_slow_hit_rightcell"] += int(j is not None and G.cell[j] == c)
                    for k, p in preds.items():
                        acc[f"{tag}/{k}"].append(int(p == answer))
            G.absorb_episode(A, e)
            G4.absorb_episode(A, e)
            obs_past += dwell_observations(A, e)
        counts["items_total"] += len(G.slow)
        counts["items_slow_final"] += sum(s is not None for s in G.slow)
        counts["versions_total"] += len(G.versions) - 1
        counts["slow_items_on_persistent_cells"] += sum(
            s is not None and G.cell[j] in pcells for j, s in enumerate(G.slow))
    groups = {
        "decoy_stable": ["decoy/pre", "decoy/post_kept"],
        "decoy_all": ["decoy/pre", "decoy/post_kept", "decoy/post_reloc"],
        "reloc_post": ["clean/post_reloc", "decoy/post_reloc"],
    }
    out = {"cfg": cfg, "counts": dict(counts), "acc": {}}
    for g, tags in groups.items():
        for p in ("P0_copy", "P1_latest", "P2_gated", "P4_norollback", "O"):
            v = sum((acc[f"{t}/{p}"] for t in tags), [])
            out["acc"][f"{g}/{p}"] = [round(float(np.mean(v)), 4), len(v)]
    for k, v in sorted(acc.items()):
        out["acc"][k] = [round(float(np.mean(v)), 4), len(v)]
    return out


if __name__ == "__main__":
    base = dict(P=4, MV=4, E=12, q=0.3, reloc_at=6, reloc_p=0.5, match_d=5.0, match_sim=1.0, window=3)
    res = [run(base, 100)]
    (HERE / "results2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(r["counts"])
        for k, v in r["acc"].items():
            if "/" in k and k.split("/")[0] in ("decoy_stable", "decoy_all", "reloc_post"):
                print(k, v)
    say("done")
