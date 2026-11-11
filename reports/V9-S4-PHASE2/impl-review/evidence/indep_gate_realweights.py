"""P214 独立核对：用一期 final 的真实权重（只读），在滤波器实际产生的成员状态上，
- 头门：复核者自己按「sigmoid(logit) > p，且另一盘在 MSG_RADIUS 内、不含自身」算门，与 gated.head_gate 逐元素比对；
- 几何门：逐成员调用一期基线 analysis.cv_contact_pairs（循环版）算门，与 gated.geo_gate 比对；
- 门控输出：门开处与 L-int（或 L-ind）原模型逐位相同，门关处与 E-B 逐位相同；
- 门打开的成员—盘步比例。
MLX 只用 CPU，必须在共享锁内运行。世界取非登记命名空间 p214-indep，只在内存里生成。
用法：PYTHONPATH=<src> python indep_gate_realweights.py <权重目录>
"""
import sys
from pathlib import Path

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import gated as G
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NS = "p214-indep"


def my_head_mask(net, P, V, pillars, p):
    pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
    _, _, lg, _ = net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
    prob = 1.0 / (1.0 + np.exp(-np.array(lg, dtype=np.float64)))
    M, n = P.shape[:2]
    out = np.zeros((M, n), bool)
    for m in range(M):
        for i in range(n):
            for j in range(n):
                if i != j and np.hypot(*(P[m, i] - P[m, j])) < L.MSG_RADIUS and prob[m, i, j] > p:
                    out[m, i] = True
    return out


def my_geo_mask(P, V):
    M, n = P.shape[:2]
    out = np.zeros((M, n), bool)
    for m in range(M):
        for i, j in A.cv_contact_pairs(P[m], V[m]):
            out[m, i] = out[m, j] = True
    return out


def main():
    print('sources:', [x.__file__ for x in (G, L, F)], flush=True)
    wdir = Path(sys.argv[1])
    mx.set_default_device(mx.cpu)
    lint = L.load("L-int", str(wdir / "L-int#1.safetensors"))
    lind = L.load("L-ind", str(wdir / "L-ind#1.safetensors"))
    arms = {"L-int-g": (lint, 0.5), "L-int-g3": (lint, 0.3), "L-int-g7": (lint, 0.7), "L-int-geo": (lint, "geo"), "L-ind-geo": (lind, "geo")}
    bad, stats = [], {}
    for w, n in ((0, 6), (1000, 10)):
        assert NS not in W.REGISTERED
        ep = W.generate_episode(NS, w, n, steps=120)
        states = []
        base = G.gated_model(lint, 0.5)

        def rec(P, V, pillars):
            states.append((P.copy(), V.copy()))
            return base(P, V, pillars)
        F.track(A.student_detections(ep), ep.pillars, rec, np.random.default_rng(11), F.FilterConfig())
        states = [s for s in states if s[0].shape[1] >= 2]
        for arm, (net, gate) in arms.items():
            cnt = [0, 0]
            model = G.gated_model(net, gate, counter=cnt)
            learned = L.as_process_model(net)
            n_open = n_all = 0
            for P, V in states:
                out = model(P, V, ep.pillars)
                mine = my_geo_mask(P, V) if gate == "geo" else my_head_mask(net, P, V, ep.pillars, gate)
                theirs = G.geo_gate(P, V) if gate == "geo" else None
                if theirs is not None and not np.array_equal(mine, theirs):
                    bad.append(f"{arm} w{w}: geo_gate differs from the phase-1 baseline")
                lp, lv = learned(P, V, ep.pillars)
                bp, bv = Mo.bounce(P, V, ep.pillars)
                want_p, want_v = np.where(mine[..., None], lp, bp), np.where(mine[..., None], lv, bv)
                if not (np.array_equal(out[0], want_p) and np.array_equal(out[1], want_v)):
                    bad.append(f"{arm} w{w}: gated output is not where(my gate, learned, E-B) bit for bit")
                n_open += int(mine.sum()); n_all += mine.size
            if cnt != [n_open, n_all]:
                bad.append(f"{arm} w{w}: counter {cnt} vs my count {[n_open, n_all]}")
            stats[f"{arm} w{w} ({n} disks)"] = {"predict_calls": len(states), "open": n_open, "all": n_all, "share": round(n_open / n_all, 4)}
    for k, v in stats.items():
        print(k, v)
    print("mismatches", bad[:20])
    print("PASSED" if not bad else "FAILED")


if __name__ == "__main__":
    main()
