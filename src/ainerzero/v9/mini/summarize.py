"""汇总多次运行：每个臂的成功率与 SPL（各种子的值和均值），以及按回合配对的差值 bootstrap 区间。

用法：.venv/bin/python -m ainerzero.v9.mini.summarize reports/V9-MINI/explore/batch1/m2-s*
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

PAIRS = [("map_hybrid", "map_analytic"), ("map_hybrid", "map_memory"), ("map_hybrid", "map_ungated"),
         ("map_hybrid", "map_ungated_aug"), ("map_memory", "map_analytic"), ("gru_belief", "latent_learned"),
         ("latent_learned", "latent_euclid")]


def _spl(r) -> float:
    return r["success"] * r["d_star"] / max(r["d_star"], r["steps"])


def _subset(rs, kind):
    if kind == "law_relevant":
        return [r for r in rs if r.get("law_relevant")]
    return [r for r in rs if r["kind"] == kind]


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
    print("\n配对差值（同一回合，所有种子合并；bootstrap 95% 区间，2000 次）")
    rng = np.random.default_rng(0)
    for a, b in PAIRS:
        if a not in arms or b not in arms:
            continue
        for kind in ("long", "law_relevant"):
            ds, dsp = [], []
            for _, _, eps in runs:
                ea, eb = _subset(eps[a], kind), _subset(eps[b], kind)
                for ra, rb in zip(ea, eb):
                    ds.append(ra["success"] - rb["success"])
                    dsp.append(_spl(ra) - _spl(rb))
            if not ds:
                continue
            ds, dsp = np.array(ds, float), np.array(dsp, float)
            bs = rng.integers(0, len(ds), (2000, len(ds)))
            lo, hi = np.percentile(ds[bs].mean(1), [2.5, 97.5])
            lo2, hi2 = np.percentile(dsp[bs].mean(1), [2.5, 97.5])
            print(f"  {a} − {b} [{kind}, n={len(ds)}]：成功 {ds.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]   "
                  f"SPL {dsp.mean():+.3f} [{lo2:+.3f}, {hi2:+.3f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
