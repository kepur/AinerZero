"""S4 第一阶段摸底的诊断：学习模型在擦边步上的速度误差从哪里来。

未登记，不作结论。只用命名空间 s4x-explore 的评测世界 0–39（6 盘），从精确真值预测一步，MLX 只用 CPU，持共享锁。
把每个「盘·步」分成碰撞（本步有盘—盘接触）、擦边（本步末与另一个盘的中心距 < 2R + 0.3、没有盘—盘接触）、自由三类，
擦边步再按「本步有没有碰墙或柱」、本步末到最近盘的间隙、误差大小拆开。
用法：python -I diag_graze.py <权重文件> <臂> <消息宽度> <输出 json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s3.run_guard import RunLock  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

NS = "s4x-explore"
GAP_BINS = (0.0, 0.02, 0.05, 0.1, 0.2, 0.3)
ERR_BINS = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 9.0)


def main() -> None:
    weights, arm, msg, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    if out.exists():
        raise SystemExit(f"结果文件已存在，不覆盖：{out}")
    with RunLock(REPO / "artifacts/locks/m0-worker.lock"):
        mx.set_default_device(mx.cpu)
        L.MSG = msg
        pm = L.as_process_model(L.load(arm, weights))
        rows = []   # kind (0 coll, 1 graze, 2 free), wall-or-pillar contact, end gap to the nearest disk, error, E-B-style change |v' - v|
        for w in range(40):
            ep = W.generate_episode(NS, w, 6)
            for s, nxt in zip(ep.steps[:-1], ep.steps[1:]):
                coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
                hard = {i for k, i, j in s.contacts if k != "disk"}
                d = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(ep.n_disks) * 99
                gap = d.min(1) - 2 * W.RADIUS
                _, v = pm(s.positions[None], s.velocities[None], ep.pillars)
                err = np.linalg.norm(v[0] - nxt.velocities, axis=1)
                chg = np.linalg.norm(nxt.velocities - s.velocities, axis=1)
                for i in range(ep.n_disks):
                    kind = 0 if i in coll else (1 if gap[i] < 0.3 else 2)
                    rows.append((kind, int(i in hard), float(gap[i]), float(err[i]), float(chg[i])))
    a = np.array(rows)
    kind, hard, gap, err = a[:, 0], a[:, 1] == 1, a[:, 2], a[:, 3]
    base = float(a[kind == 0, 4].mean())             # E-B's mean error on collision disk-steps
    res = {"weights": weights, "arm": arm, "msg": msg, "eb_collision_error": base,
           "n": {k: int((kind == c).sum()) for k, c in (("collision", 0), ("graze", 1), ("free", 2))},
           "mean_error": {k: float(err[kind == c].mean()) for k, c in (("collision", 0), ("graze", 1), ("free", 2))}}
    g = kind == 1
    res["D"] = 1 - res["mean_error"]["collision"] / base
    res["HF"] = res["mean_error"]["graze"] / base
    res["graze_by_hard_contact"] = {name: {"n": int(m.sum()), "mean_error": float(err[m].mean()), "share_of_graze_error": float(err[m].sum() / err[g].sum())}
                                    for name, m in (("wall_or_pillar", g & hard), ("none", g & ~hard))}
    soft = g & ~hard
    res["graze_no_hard_by_gap"] = [{"gap": [lo, hi], "n": int(m.sum()), "mean_error": float(err[m].mean()) if m.any() else None,
                                    "share_of_graze_error": float(err[m].sum() / err[g].sum())}
                                   for lo, hi in zip(GAP_BINS[:-1], GAP_BINS[1:]) for m in [soft & (gap >= lo) & (gap < hi)]]
    res["graze_no_hard_by_error"] = [{"error": [lo, hi], "n": int(m.sum()), "share_of_graze_error": float(err[m].sum() / err[g].sum())}
                                     for lo, hi in zip(ERR_BINS[:-1], ERR_BINS[1:]) for m in [soft & (err >= lo) & (err < hi)]]
    f = kind == 2
    res["free_by_hard_contact"] = {name: {"n": int(m.sum()), "mean_error": float(err[m].mean())} for name, m in (("wall_or_pillar", f & hard), ("none", f & ~hard))}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
