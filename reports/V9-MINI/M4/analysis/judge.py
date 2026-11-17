"""M4 判定脚本（一级 claude 写，2026-11-17，运行结束后）。

按冻结预登记 reports/V9-MINI/M4/M4-PREREG.md §1 判定 H1、H2、H2′、H3、H4。

两套区间：
  A. 登记实现：ainerzero.v9.mini.summarize.cluster_ci，每条门用新的 default_rng(0)，4000 次；
  B. 作者自查（不是非作者复算）：自己写的按图重抽样，簇 = 种子 × 图，按回合加权；
     另用 5 个随机种子各 4000 次，看区间对随机种子是否敏感。

另做完整性检查：代码哈希、留出图种子、回合数、任务序列逐臂一致、oracle 全到达。

用法：.venv/bin/python reports/V9-MINI/M4/analysis/judge.py > reports/V9-MINI/M4/analysis/judge.txt
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ainerzero.v9.mini.summarize import cluster_ci

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "FREEZE.json").read_text())
LATENT = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief")
EXPECT_EPISODES = {"m1": 1523, "m2": 1703}  # M4-prefreeze/oracle_check.json


def load(world):
    runs = []
    for s in range(5):
        d = ROOT / f"{world}-s{s}"
        res = json.loads((d / "result.json").read_text())
        eps = json.loads((d / "episodes.json").read_text())
        runs.append((s, res, eps))
    return runs


def integrity(world, runs):
    out = []
    n_total = 0
    seen = set()
    for s, res, eps in runs:
        m = res["meta"]
        assert m["code_sha256"] == FREEZE["code_sha256"], (world, s, "code_sha256")
        assert m["eval_seed0"] == 8_000_000 + 1000 * s, (world, s, "eval_seed0")
        assert m["seed"] == s and m["preset"]["eval_layouts"] == 80
        ref = [(r["layout_seed"], r["kind"], r["d_star"], r["law_relevant"]) for r in eps["oracle"]]
        for arm, rs in eps.items():
            sig = [(r["layout_seed"], r["kind"], r["d_star"], r["law_relevant"]) for r in rs]
            assert sig == ref, (world, s, arm, "任务序列与 oracle 不一致")
        assert all(r["success"] == 1 for r in eps["oracle"]), (world, s, "oracle 未全到达")
        lay = {r["layout_seed"] for r in eps["oracle"]}
        assert all(8_000_000 + 1000 * s <= x < 8_000_000 + 1000 * s + 80 for x in lay), (world, s, "留出图越界")
        assert not (lay & seen), (world, s, "种子间留出图重叠")
        seen |= lay
        n_total += len(ref)
        out.append(f"  {world}-s{s}: 代码哈希一致；mlx {m['mlx']}；留出图 {min(lay)}..{max(lay)}（{len(lay)} 张有任务）；"
                   f"回合 {len(ref)}；12 组任务序列一致；oracle 全到达")
    assert n_total == EXPECT_EPISODES[world], (world, n_total)
    out.append(f"  {world} 回合合计 {n_total}，与冻结前 oracle 检查一致")
    return out


def pooled(runs, a, b, kind="long"):
    d, keys = [], []
    for s, _, eps in runs:
        for ra, rb in zip(eps[a], eps[b]):
            if ra["kind"] != kind:
                continue
            d.append(ra["success"] - rb["success"])
            keys.append((s, ra["layout_seed"]))
    return np.array(d, float), keys


def ci_registered(runs, a, b):
    d, keys = pooled(runs, a, b)
    lo, hi, _, _, ncl = cluster_ci(d, d, keys, np.random.default_rng(0))
    return d.mean(), lo, hi, len(d), ncl


def ci_own(runs, a, b, seed):
    d, keys = pooled(runs, a, b)
    clusters = {}
    for x, k in zip(d, keys):
        clusters.setdefault(k, []).append(x)
    sums = np.array([sum(v) for v in clusters.values()])
    cnts = np.array([len(v) for v in clusters.values()], float)
    rng = np.random.default_rng(seed)
    est = np.empty(4000)
    for i in range(4000):
        pick = rng.integers(0, len(sums), len(sums))
        est[i] = sums[pick].sum() / cnts[pick].sum()
    lo, hi = np.quantile(est, [0.025, 0.975])
    return d.mean(), lo, hi


def long_rate(runs, arm):
    xs = [r["success"] for _, _, eps in runs for r in eps[arm] if r["kind"] == "long"]
    return float(np.mean(xs))


def gate_line(name, world, runs, a, b, rule, ok_fn):
    est, lo, hi, n, ncl = ci_registered(runs, a, b)
    own = [ci_own(runs, a, b, sd) for sd in (0, 1, 2, 3, 4)]
    los = [o[1] for o in own]
    ok = ok_fn(est, lo)
    return ok, (f"{name} [{world}] {a} − {b}（长目标，回合 {n}，图 {ncl}）：{est:+.3f} [{lo:+.3f}, {hi:+.3f}]  "
                f"门：{rule}  → {'过' if ok else '不过'}\n"
                f"      作者自写重抽样，随机种子 0..4 的下界：{', '.join(f'{x:+.3f}' for x in los)}")


def main():
    m1, m2 = load("m1"), load("m2")
    print("== 完整性 ==")
    for line in integrity("m1", m1) + integrity("m2", m2):
        print(line)

    print("\n== 门（预登记 §1；区间 = summarize.cluster_ci，default_rng(0)，4000 次）==")
    results = {}
    for world, runs in (("m1", m1), ("m2", m2)):
        rates = {arm: long_rate(runs, arm) for arm in LATENT}
        best = max(LATENT, key=lambda k: rates[k])
        print(f"H1 [{world}] 潜空间组长目标成功率：" + "，".join(f"{k} {v:.4f}" for k, v in rates.items())
              + f"；事后取最好：{best}")
        ok, line = gate_line("H1", world, runs, "map_hybrid", best, "≥ 0.50 且下界 > 0",
                             lambda e, lo: e >= 0.50 and lo > 0)
        results[f"H1-{world}"] = ok
        print(line)
    ok, line = gate_line("H2", "m2", m2, "map_hybrid", "map_analytic", "≥ +0.10 且下界 > 0",
                         lambda e, lo: e >= 0.10 and lo > 0)
    results["H2"] = ok
    print(line)
    ok, line = gate_line("H2′", "m1", m1, "map_hybrid", "map_analytic", "下界 ≥ −0.02",
                         lambda e, lo: lo >= -0.02)
    results["H2′"] = ok
    print(line)
    ok, line = gate_line("H3", "m2", m2, "map_hybrid", "map_memory", "≥ +0.05 且下界 > 0",
                         lambda e, lo: e >= 0.05 and lo > 0)
    results["H3"] = ok
    print(line)
    ok, line = gate_line("H4①", "m2", m2, "map_hybrid_self", "map_analytic", "≥ +0.08 且下界 > 0",
                         lambda e, lo: e >= 0.08 and lo > 0)
    results["H4①"] = ok
    print(line)

    diffs = []
    print("H4② [m2] 前进模型留出事件准确率：真值标签（gated 全量）减自监督（gated_self）")
    for s, res, _ in m2:
        fm = res["forward_model"]
        g = max((k for k in fm if k.startswith("gated@")), key=lambda k: int(k.split("@")[1]))
        sk = next(k for k in fm if k.startswith("gated_self@"))
        diffs.append(fm[g]["event"] - fm[sk]["event"])
        print(f"      s{s}: {g} {fm[g]['event']:.4f}  {sk} {fm[sk]['event']:.4f}  差 {diffs[-1]:+.4f}"
              f"（事件样本 {fm[g]['n_event']}）")
    ok = float(np.mean(diffs)) <= 0.05
    results["H4②"] = ok
    print(f"      5 个种子平均差 {np.mean(diffs):+.4f}  门：≤ 0.05  → {'过' if ok else '不过'}")
    results["H4"] = results["H4①"] and results["H4②"]

    print("\n== 只报告、不设门 ==")
    for world, runs in (("m2", m2), ("m1", m1)):
        est, lo, hi, n, ncl = ci_registered(runs, "map_hybrid_self", "map_hybrid")
        print(f"  [{world}] map_hybrid_self − map_hybrid（长目标）：{est:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    for world, runs in (("m2", m2), ("m1", m1)):
        print(f"  [{world}] 地图组迷路统计（全部回合，各种子合计；lost 是开碎片次数，不是迷路步数）：")
        for arm in ("map_analytic", "map_memory", "map_hybrid", "map_hybrid_self", "map_ungated", "map_ungated_aug"):
            rs = [r for _, _, eps in runs for r in eps[arm]]
            steps = sum(r["steps"] for r in rs)
            lost = sum(r["lost"] for r in rs)
            surp = sum(r["surprises"] for r in rs)
            las = np.mean([bool(r["lost_at_start"]) for r in rs])
            pl = np.mean([r["prefix_lost"] for r in rs])
            fail = [r for r in rs if r["kind"] == "long" and not r["success"]]
            fail_las = np.mean([bool(r["lost_at_start"]) for r in fail]) if fail else float("nan")
            print(f"    {arm:16s} 任务段迷路次数/回合 {lost / len(rs):.3f}  惊讶/步 {surp / steps:.4f}  "
                  f"开局即迷路 {las:.3f}  前缀迷路次数均值 {pl:.2f}  长目标失败 {len(fail)}，其中开局即迷路 {fail_las:.3f}")

    print("\n== 判定汇总 ==")
    for k in ("H1-m1", "H1-m2", "H2", "H2′", "H3", "H4①", "H4②", "H4"):
        print(f"  {k}: {'过' if results[k] else '不过'}")
    (ROOT / "analysis" / "verdict.json").write_text(json.dumps({k: bool(v) for k, v in results.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
