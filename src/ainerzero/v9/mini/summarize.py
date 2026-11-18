"""汇总多次运行：每个臂的成功率与 SPL（各种子的值和均值），以及配对差值的 bootstrap 区间。

区间按图整簇重抽样：同一张留出图上的回合共用探索前缀和起点，彼此不独立（探索批次 3 里，
hybrid_self 与 hybrid 的全部差别都来自同一张图的 4 个长目标）。差值是所有入选回合的平均，
重抽样单位是图（各运行的回合集合不同时，单位是「运行 × 图」）。

用法：.venv/bin/python -m ainerzero.v9.mini.summarize reports/V9-MINI/explore/batch1/m2-s*
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

PAIRS = [("map_hybrid", "map_analytic"), ("map_hybrid_self", "map_analytic"), ("map_hybrid_self", "map_hybrid"), ("map_hybrid", "map_memory"), ("map_hybrid", "map_ungated"),
         ("map_hybrid", "map_ungated_aug"), ("map_memory", "map_analytic"), ("gru_belief", "latent_learned"),
         ("latent_learned", "latent_euclid"), ("latent_topo", "latent_learned"), ("map_hybrid", "latent_topo")]


def _spl(r) -> float:
    return r["success"] * r["d_star"] / max(r["d_star"], r["steps"])


def _subset(rs, kind):
    if kind == "law_relevant":
        return [r for r in rs if r.get("law_relevant")]
    return [r for r in rs if r["kind"] == kind]


def cluster_ci(d, d2, keys, rng, n_boot: int = 4000):
    """按簇（图）重抽样的 95% 区间：每次抽同样多的簇（有放回），估计量是抽中簇的回合差值之和除以回合数。"""
    if any(k[1] is None for k in keys):
        raise ValueError("回合缺 layout_seed，不能按图重抽样（旧版 episodes.json）")
    uniq = sorted(set(keys))
    idx = {k: i for i, k in enumerate(uniq)}
    g = np.array([idx[k] for k in keys])
    s1 = np.bincount(g, weights=d, minlength=len(uniq))
    s2 = np.bincount(g, weights=d2, minlength=len(uniq))
    c = np.bincount(g, minlength=len(uniq)).astype(float)
    b = rng.integers(0, len(uniq), (n_boot, len(uniq)))
    lo, hi = np.percentile(s1[b].sum(1) / c[b].sum(1), [2.5, 97.5])
    lo2, hi2 = np.percentile(s2[b].sum(1) / c[b].sum(1), [2.5, 97.5])
    return lo, hi, lo2, hi2, len(uniq)


def main(paths: list[str]) -> int:
    runs = []
    for p in paths:
        p = Path(p)
        if (p / "result.json").exists() and (p / "episodes.json").exists():
            runs.append((p.name, json.loads((p / "result.json").read_text()), json.loads((p / "episodes.json").read_text())))
    if not runs:
        print("没有找到 result.json")
        return 1
    print(f"运行：{', '.join(n for n, _, _ in runs)}")
    print("\n预测与代价诊断（各种子）")
    for name, res, _ in runs:
        fm = res.get("forward_model", {})
        gated = [v for k, v in fm.items() if k.startswith("gated@")]
        ung = [v for k, v in fm.items() if k.startswith("ungated@")]
        print(f"  {name}: 一步比 {res['prediction']['one_step_ratio']:.3f}  5步比 {res['prediction']['5_step_ratio']:.3f}  "
              f"ρ欧氏远 {res['cost_diagnostics']['rho_euclid_far_ge20']:+.3f}  ρ学到远 {res['cost_diagnostics']['rho_learned_far_ge20']:+.3f}  "
              f"ρGRU远 {res.get('belief', {}).get('diagnostics', {}).get('rho_belief_far_ge20', float('nan')):+.3f}  "
              f"前进模型事件准确率 门控 {gated[-1]['event'] if gated else float('nan'):.3f} 不门控 {ung[-1]['event'] if ung else float('nan'):.3f}")
    arms = list(runs[0][2].keys())
    for kind in ("short", "long", "law_relevant"):
        print(f"\n{kind}：成功率 / SPL（各种子 → 均值）")
        for arm in arms:
            succ, spl, n = [], [], 0
            for _, _, eps in runs:
                sub = _subset(eps[arm], kind)
                if sub:
                    succ.append(np.mean([r["success"] for r in sub]))
                    spl.append(np.mean([_spl(r) for r in sub]))
                    n += len(sub)
            if succ:
                print(f"  {arm:18s} n={n:4d}  成功 {' '.join(f'{s:.2f}' for s in succ)} → {np.mean(succ):.3f}   "
                      f"SPL {' '.join(f'{s:.2f}' for s in spl)} → {np.mean(spl):.3f}")
    sig = [tuple((r.get("layout_seed"), r["kind"], r["d_star"]) for r in eps[arms[0]]) for _, _, eps in runs]
    same = all(s == sig[0] for s in sig)
    print("\n配对差值（同一回合配对；按图整簇 bootstrap 95% 区间，4000 次）")
    if same:
        print(f"  各运行的回合集合相同（只有训练种子不同）：先在 {len(runs)} 个运行间对每个回合取平均，再按图重抽样")
    else:
        print("  各运行的回合集合不同：按「运行 × 图」重抽样")
    rng = np.random.default_rng(0)
    for a, b in PAIRS:
        if a not in arms or b not in arms:
            continue
        for kind in ("long", "law_relevant"):
            per_run = []
            for ri, (_, _, eps) in enumerate(runs):
                ea, eb = _subset(eps[a], kind), _subset(eps[b], kind)
                per_run.append(([ra["success"] - rb["success"] for ra, rb in zip(ea, eb)],
                                [_spl(ra) - _spl(rb) for ra, rb in zip(ea, eb)],
                                [(0 if same else ri, ra.get("layout_seed")) for ra in ea]))
            if not per_run or not per_run[0][0]:
                continue
            if same:
                ds = np.mean([np.array(x[0], float) for x in per_run], axis=0)
                dsp = np.mean([np.array(x[1], float) for x in per_run], axis=0)
                keys = per_run[0][2]
            else:
                ds = np.concatenate([np.array(x[0], float) for x in per_run])
                dsp = np.concatenate([np.array(x[1], float) for x in per_run])
                keys = [k for x in per_run for k in x[2]]
            lo, hi, lo2, hi2, n_cl = cluster_ci(ds, dsp, keys, rng)
            print(f"  {a} − {b} [{kind}, 回合 {len(ds)}，图 {n_cl}]：成功 {ds.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]   "
                  f"SPL {dsp.mean():+.3f} [{lo2:+.3f}, {hi2:+.3f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
