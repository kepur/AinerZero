"""P214 独立复算：一步覆盖率（行的选取、t-1 -> t 的步类、90% 椭圆）与重新出现覆盖率（a 步持有该盘的轨迹、b 步更新前的集合），
用复核者自己的代码重算，与 analysis_p2.track_cell 的输出逐项比对。纯 CPU（只用 E-P、E-B、E-CV 手写模型，不导入 MLX）。

世界取非登记的命名空间 p214-indep（不是 s4p1-*/s4p2-*），只在内存里生成，不落盘。
用法：PYTHONPATH=<src> python indep_coverage_check.py [世界数]
"""
import sys

import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NS = "p214-indep"
CHI2 = -2.0 * np.log(0.1)          # 二维高斯 90% 区域：P(chi2_2 <= x) = 1 - exp(-x/2)


def inside(ens, truth):
    mu = ens.mean(0)
    c = np.cov(ens.T, ddof=1) + np.eye(2) * 1e-9
    d = truth - mu
    return float(d @ np.linalg.inv(c) @ d) <= CHI2


def main():
    print('sources:', [x.__file__ for x in (P2, F, W)], flush=True)
    n_worlds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    assert NS not in W.REGISTERED and not NS.startswith(("s4p1-", "s4p2-"))
    total = {"rows": 0, "coll_rows": 0, "events": 0, "coll_events": 0}
    bad = []
    for w in range(n_worlds):
        ep = W.generate_episode(NS, w, 6)
        events = W.reappearances(ep)
        for arm, model in (("E-P", Mo.true_physics), ("E-B", Mo.bounce), ("E-CV", Mo.constant_velocity)):
            for seed in P2.SEEDS:
                cell = P2.track_cell(ep, model, NS, seed, events)
                # 复核者自己的钩子：只记下每步的预测集合（副本）、分配与 last
                log = []
                rng = np.random.default_rng(W.derive_seed(NS, "filter", w, seed, "base"))
                ids, _ = F.track(A.student_detections(ep), ep.pillars, model, rng, F.FilterConfig(),
                                 on_predict=lambda t, P, V, assign, last: log.append((t, P, dict(assign), list(last))))
                if P2.ids_digest(ids) != cell["ids_sha256"]:
                    bad.append(f"w{w} {arm}#{seed}: assignment digest differs")
                one = {"collision": [0, 0], "other": [0, 0]}
                for t, P, assign, last in log:
                    if t == 0:
                        continue
                    pair = ep.steps[t - 1].contacts                      # 接触发生在 t-1 -> t
                    touched = set()
                    for kind, i, j in pair:
                        if kind == "disk":
                            touched |= {i, j}
                    for r, k in assign.items():
                        if last[k] != t - 1:                             # 只要 t-1 与 t 都分到检测的轨迹
                            continue
                        disk = int(ep.steps[t].truth_ids[r])
                        row = one["collision" if disk in touched else "other"]
                        row[0] += 1
                        row[1] += int(inside(P[:, k], ep.steps[t].positions[disk]))
                if one != cell["one_step"]:
                    bad.append(f"w{w} {arm}#{seed}: one-step {one} vs recorded {cell['one_step']}")
                snaps = {t: P for t, P, _, _ in log}
                rea = []
                for e in events:
                    a, b, k = e["a"], e["b"], e["k"]
                    ra = list(ep.steps[a].truth_ids).index(k)
                    trk = int(ids[a][ra])                                # a 步持有盘 k 的轨迹
                    rea.append(int(inside(snaps[b][:, trk], ep.steps[b].positions[k])))
                if rea != cell["reappear"]:
                    bad.append(f"w{w} {arm}#{seed}: reappear {rea} vs recorded {cell['reappear']}")
                correct = [int(ids[e['a']][list(ep.steps[e['a']].truth_ids).index(e['k'])] ==
                               ids[e['b']][list(ep.steps[e['b']].truth_ids).index(e['k'])]) for e in events]
                if correct != cell["correct"]:
                    bad.append(f"w{w} {arm}#{seed}: correct differs")
                total["rows"] += one["collision"][0] + one["other"][0]
                total["coll_rows"] += one["collision"][0]
                print(f"w{w} {arm}#{seed}: one_step={one} reappear_inside={sum(rea)}/{len(rea)} correct={sum(correct)}/{len(correct)}", flush=True)
        total["events"] += len(events)
        total["coll_events"] += sum(e["collision"] for e in events)
    # 步类的反证：同一世界里，若改用第 t 步的接触（t -> t+1）分类，碰撞行数一般不同
    print("totals", total)
    print("mismatches", bad[:20])
    print("PASSED" if not bad and total["coll_rows"] > 0 else "FAILED")


if __name__ == "__main__":
    main()
