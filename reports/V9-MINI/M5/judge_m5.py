"""M5 判定脚本：按预登记 §1 判 H1s，并输出只报告的配对差。

- 每个世界读 5 个运行（reports/V9-MINI/M5/{w}-s{0..4}），各运行用互不重叠的留出图，所以簇是「运行 × 留出图」。
- 最好的潜空间组：6 组里，所有运行的长目标回合合在一起，成功率最高的一组（并列时按组名取字典序最大的，结果只影响打印的组名）。
- 区间：summarize.cluster_ci，4000 次，随机种子 0；每个配对用同一个随机数发生器依次抽（顺序见 PAIRS）。
- 门：map_hybrid_self − 最好的潜空间组 ≥ 0.50，且下界 > 0。

用法：.venv/bin/python reports/V9-MINI/M5/judge_m5.py [运行目录 ...]
不给参数时读 reports/V9-MINI/M5/{m1,m2}-s{0..4}；给参数时把这些目录当成同一个世界的运行（冻结前用来试跑）。
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np

from ainerzero.v9.mini.summarize import cluster_ci

ROOT = Path(__file__).resolve().parents[3]
LATENT = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn")
GATE = 0.50


def judge(dirs: list[Path], rng: np.random.Generator) -> dict:
    runs = [json.loads((d / "episodes.json").read_text()) for d in dirs]
    def longs(arm):
        rs = [(ri, r) for ri, e in enumerate(runs) for r in e[arm] if r["kind"] == "long"]
        return np.array([r["success"] for _, r in rs], float), [(ri, r["layout_seed"]) for ri, r in rs]
    ref, keys = longs("oracle")
    out = {"n_long": len(ref), "n_clusters": len(set(keys)), "long_success": {}}
    for arm in runs[0]:
        v, k = longs(arm)
        assert k == keys, f"{arm} 的长目标回合与 oracle 不一致"
        out["long_success"][arm] = float(v.mean())
    best = max(LATENT, key=lambda a: (out["long_success"][a], a))
    out["best_latent"] = best
    pairs = [("map_hybrid_self", best), ("map_hybrid", best), ("map_hybrid_self", "latent_topo"),
             ("map_hybrid_self", "latent_attn"), ("topo_oracle_ctrl", "latent_topo"), ("map_hybrid_self", "topo_oracle_ctrl")]
    out["pairs"] = {}
    for a, b in pairs:
        key = f"{a} - {b}"
        if key in out["pairs"]:
            continue
        d = longs(a)[0] - longs(b)[0]
        lo, hi, _, _, n = cluster_ci(d, d, keys, rng)
        out["pairs"][key] = {"diff": float(d.mean()), "lo": float(lo), "hi": float(hi), "clusters": n}
    g = out["pairs"][f"map_hybrid_self - {best}"]
    out["H1s"] = {"diff": g["diff"], "lo": g["lo"], "pass": bool(g["diff"] >= GATE and g["lo"] > 0)}
    return out


def main(argv: list[str]) -> int:
    rng = np.random.default_rng(0)
    if argv:
        groups = {"given": [Path(a) for a in argv]}
    else:
        groups = {w: [ROOT / f"reports/V9-MINI/M5/{w}-s{s}" for s in range(5)] for w in ("m1", "m2")}
    res = {}
    for w, dirs in groups.items():
        res[w] = r = judge(dirs, rng)
        print(f"\n===== {w}：{len(dirs)} 个运行，长目标 {r['n_long']} 个回合，{r['n_clusters']} 个簇")
        for arm, v in r["long_success"].items():
            print(f"  {arm:18s} {v:.3f}")
        print(f"  最好的潜空间组：{r['best_latent']}")
        for k, v in r["pairs"].items():
            print(f"  {k}: {v['diff']:+.3f} [{v['lo']:+.3f}, {v['hi']:+.3f}]（{v['clusters']} 簇）")
        h = r["H1s"]
        print(f"  H1s：{h['diff']:+.3f}，下界 {h['lo']:+.3f} → {'过' if h['pass'] else '不过'}（门：≥ {GATE} 且下界 > 0）")
    print("\n" + json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
