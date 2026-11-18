"""探索（不算证据）：把三批探索的回合按任务配对，汇总潜空间各组与地图组，给 M5 定门槛用。

来源（同样的 3 个训练种子、同样的 30 张探索留出图 7_900_000 起，任务逐个相同，脚本会逐回合核对）：
- explore/topo-batch/{w}-s{s}：random、旧潜空间四组、latent_topo、map_analytic、map_hybrid、oracle；
- explore/batch3/{w}-s{s}：map_hybrid_self（topo-batch 没跑这一组）；
- explore/attn/batch/{w}-s{s}：latent_attn。

用法：.venv/bin/python reports/V9-MINI/explore/attn/merge_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ainerzero.v9.mini.summarize import cluster_ci

ROOT = Path(__file__).resolve().parents[4]
EX = ROOT / "reports/V9-MINI/explore"
LATENT = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn")
SOURCES = (("topo-batch", None), ("batch3", ("map_hybrid_self",)), ("attn/batch", ("latent_attn",)))


def load(w: str, s: int) -> dict:
    eps: dict = {}
    sig = None
    for d, arms in SOURCES:
        e = json.loads((EX / d / f"{w}-s{s}" / "episodes.json").read_text())
        for arm in (arms or e.keys()):
            rs = e[arm]
            si = [(r["layout_seed"], r["kind"], r["d_star"]) for r in rs]
            if sig is None:
                sig = si
            if si != sig:
                raise SystemExit(f"{d} {w}-s{s} {arm} 的任务与其他来源不一致")
            eps[arm] = rs
    return eps


def main() -> int:
    rng = np.random.default_rng(0)
    for w in ("m1", "m2"):
        runs = [load(w, s) for s in range(3)]
        print(f"\n===== {w}（3 个种子，同一套 30 张图；回合已逐个核对一致）")
        arms = [a for a in ("random",) + LATENT + ("map_analytic", "map_hybrid", "map_hybrid_self", "oracle") if a in runs[0]]
        for kind in ("short", "long"):
            print(f"  {kind}：")
            for a in arms:
                v = [np.mean([r["success"] for r in e[a] if r["kind"] == kind]) for e in runs]
                print(f"    {a:16s} {' '.join(f'{x:.3f}' for x in v)} → {np.mean(v):.3f}")
        longs = {a: np.mean([[r["success"] for r in e[a] if r["kind"] == "long"] for e in runs], axis=0) for a in arms}
        keys = [(0, r["layout_seed"]) for r in runs[0][arms[0]] if r["kind"] == "long"]
        best = max(LATENT, key=lambda a: (longs[a].mean(), a))
        print(f"  最好的潜空间组（长目标，事后取最大）：{best} {longs[best].mean():.3f}")
        for a, b in (("map_hybrid_self", best), ("map_hybrid", best), ("map_hybrid_self", "latent_topo"),
                     ("map_hybrid_self", "latent_attn"), ("latent_attn", "random"), ("latent_attn", "latent_topo")):
            d = longs[a] - longs[b]
            lo, hi, _, _, n = cluster_ci(d, d, keys, rng)
            print(f"  {a} − {b} [long, 回合 {len(d)}，图 {n}]：{d.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
