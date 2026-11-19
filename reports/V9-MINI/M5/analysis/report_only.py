"""M5 只报告项的补充（作者自算，不设门）。

预登记 §1「只报告、不设门」里，登记分析命令 `summarize` 按「各种子成功率的平均」给出短目标和规律相关子集；
judge_m5.py 按「所有运行的回合合在一起」给出长目标。本脚本补齐合在一起的口径，和 latent_topo 的 relocalizations：
- 各组短目标、长目标、m2 规律相关子集的成功率（所有运行的回合合在一起）；
- latent_topo、topo_oracle_ctrl 每回合 relocalizations 的均值、中位数，以及长目标按成败拆开的均值。

只读 episodes.json，不跑模型。用法：.venv/bin/python reports/V9-MINI/M5/analysis/report_only.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]


def main() -> int:
    out = {}
    for w in ("m1", "m2"):
        runs = [json.loads((ROOT / f"reports/V9-MINI/M5/{w}-s{s}/episodes.json").read_text()) for s in range(5)]
        arms = list(runs[0])
        res = {"success": {}, "n": {}, "relocalizations": {}}
        subsets = {"short": lambda r: r["kind"] == "short", "long": lambda r: r["kind"] == "long"}
        if w == "m2":
            subsets["law_relevant"] = lambda r: bool(r["law_relevant"])
        for name, f in subsets.items():
            res["success"][name] = {a: float(np.mean([r["success"] for e in runs for r in e[a] if f(r)])) for a in arms}
            res["n"][name] = sum(1 for e in runs for r in e["oracle"] if f(r))
        for a in ("latent_topo", "topo_oracle_ctrl"):
            rel = np.array([r["relocalizations"] for e in runs for r in e[a]], float)
            lg = [(r["relocalizations"], r["success"]) for e in runs for r in e[a] if r["kind"] == "long"]
            res["relocalizations"][a] = {
                "mean": float(rel.mean()), "median": float(np.median(rel)), "max": float(rel.max()),
                "long_success_mean": float(np.mean([x for x, s in lg if s])) if any(s for _, s in lg) else None,
                "long_fail_mean": float(np.mean([x for x, s in lg if not s])),
            }
        out[w] = res
        print(f"\n===== {w}")
        for name in subsets:
            print(f"  {name}（{res['n'][name]} 个回合）")
            for a in arms:
                print(f"    {a:18s} {res['success'][name][a]:.3f}")
        for a, v in res["relocalizations"].items():
            ls = "—" if v["long_success_mean"] is None else f"{v['long_success_mean']:.1f}"
            print(f"  {a} relocalizations：每回合均值 {v['mean']:.1f}，中位数 {v['median']:.0f}，最大 {v['max']:.0f}；"
                  f"长目标成功 {ls}，失败 {v['long_fail_mean']:.1f}")
    print("\n" + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
