"""S4 第一阶段一级摸底第六轮：修训练后学习模型能否学到碰撞动力学。

未登记，只用来定训练写法，不作结论。只用命名空间 s4x-explore，世界与第五轮相同：
  - 训练世界 5000–5199（4–8 盘均匀），样本池 12 万；评测世界 0–39（6 盘）、200–219（10 盘）。
第五轮的结果：碰撞样本只占约 3%（精确状态）到 9%（扰动后），L-int 2 万步 D 只有 0.44，L-int-c 训练发散成 NaN。
本轮的训练改动（learned_mlx.py）：每批一半取自第 1 步有盘—盘接触的样本；梯度全局范数裁剪到 10；损失非有限即停。
臂：L-ind、L-int、L-int-c 及 L-int 的宽消息变体（MSG 128）各 1 个种子；MLX GPU 训练，CPU 评测；持共享锁。
另量 L-int 在 10 个世界上有碰撞事件的重识别（与 E-B、E-P 比）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx  # noqa: E402

from ainerzero.v9.experiments.s3.run_guard import RunLock  # noqa: E402
from ainerzero.v9.experiments.s4 import filter as F  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import metrics as Me  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

NS = "s4x-explore"
OUT = Path(__file__).resolve().parent
STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
BATCH = 256
SCRATCH = Path(sys.argv[2])
ARMS = sys.argv[3].split(",") if len(sys.argv) > 3 else ["L-int", "L-int-c", "L-ind", "L-int-wide"]


def dyn(eps, model):
    rows = [Me.dynamics_errors(e, model) for e in eps]
    return {"coll": [float(np.sum(r["coll"])) for r in rows], "n_coll": [len(r["coll"]) for r in rows],
            "graze": [float(np.sum(r["graze"])) for r in rows], "n_graze": [len(r["graze"]) for r in rows]}


def summary(x, b):
    D = Me.bootstrap(Me.stat_D, {"x_coll": np.array(x["coll"]), "b_coll": np.array(b["coll"])}, n_boot=2000)
    HF = Me.bootstrap(Me.stat_HF, {"x_graze": np.array(x["graze"]), "n_graze": np.array(x["n_graze"], float),
                                   "b_coll": np.array(b["coll"]), "n_coll": np.array(b["n_coll"], float)}, n_boot=2000)
    return {"D": round(D["value"], 4), "D_low": round(D["ci_low"], 4), "HF": round(HF["value"], 4), "HF_high": round(HF["ci_high"], 4)}


def reid_collided(eps, model, seeds=(0,)):
    rows = []
    for w, e in enumerate(eps):
        for s in seeds:
            ids, _ = F.track([st.detections for st in e.steps], e.pillars, model, np.random.default_rng(1000 * s + w))
            rows += [x["correct"] for x in Me.reid(e, ids) if x["collision"]]
    return sum(rows), len(rows)


def main() -> None:
    res: dict = {"steps": STEPS, "batch": BATCH, "coll_share": L.COLL_SHARE, "clip": L.CLIP}
    with RunLock(REPO / "artifacts/locks/m0-worker.lock"):
        rng = np.random.default_rng(20261110)
        train_eps = [W.generate_episode(NS, 5000 + w, int(rng.integers(4, 9))) for w in range(200)]
        pool = L.make_pool(train_eps, 120_000, np.random.default_rng(1), W.physics)
        ev6 = [W.generate_episode(NS, w, 6) for w in range(40)]
        ev10 = [W.generate_episode(NS, 200 + w, 10) for w in range(20)]
        mx.set_default_device(mx.cpu)
        base6, base10 = dyn(ev6, Mo.bounce), dyn(ev10, Mo.bounce)
        res["reid"] = {"E-B": reid_collided(ev6[:10], Mo.bounce), "E-P": reid_collided(ev6[:10], Mo.true_physics)}
        print("reid", res["reid"], flush=True)
        for name in ARMS:
            arm = "L-int" if name == "L-int-wide" else name
            L.MSG = 128 if name == "L-int-wide" else 64
            mx.set_default_device(mx.gpu)
            t0 = time.time()
            try:
                model, log = L.train(arm, pool, steps=STEPS, batch=BATCH, seed=1, log_every=max(STEPS // 20, 1))
            except FloatingPointError as exc:
                res[name] = {"error": str(exc)}
                print(name, "ERROR", exc, flush=True)
                continue
            train_s = time.time() - t0
            mx.set_default_device(mx.cpu)
            pm = L.as_process_model(model)
            r = {"train_seconds": round(train_s, 1), "params": L.param_count(model), "loss": log,
                 "six": summary(dyn(ev6, pm), base6), "ten": summary(dyn(ev10, pm), base10)}
            if name != "L-ind":
                r["reid"] = reid_collided(ev6[:10], pm)
            print(name, {k: v for k, v in r.items() if k != "loss"}, "last loss", log[-1], flush=True)
            res[name] = r
        L.MSG = 64
    (OUT / f"results6-train-fix-{STEPS}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
