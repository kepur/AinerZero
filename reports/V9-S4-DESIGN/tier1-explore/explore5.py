"""S4 第一阶段一级摸底第五轮：学习模型能否学到碰撞动力学（实现后、探针前的可行性检查）。

未登记，只用来定训练写法与步数的量级，不作结论。只用命名空间 s4x-explore：
  - 训练世界 5000–5199，每个世界 4–8 盘均匀（同 train 分区的规则）；
  - 评测世界 0–39（6 盘，与第二轮同一批）和 200–219（10 盘）。
学习臂 L-ind、L-int、L-int-c 各 1 个种子，MLX GPU 训练；评测在 CPU。持有共享锁 m0-worker.lock。
量：D、擦边误差比（HF）、10 盘的 D；L-int 在 10 个世界上的重识别（看耗时和量级）。
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
SCRATCH = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT


def dyn(eps, model):
    rows = [Me.dynamics_errors(e, model) for e in eps]
    return {"coll": [float(np.sum(r["coll"])) for r in rows], "n_coll": [len(r["coll"]) for r in rows],
            "graze": [float(np.sum(r["graze"])) for r in rows], "n_graze": [len(r["graze"]) for r in rows]}


def summary(x, b):
    D = Me.bootstrap(Me.stat_D, {"x_coll": np.array(x["coll"]), "b_coll": np.array(b["coll"])}, n_boot=2000)
    HF = Me.bootstrap(Me.stat_HF, {"x_graze": np.array(x["graze"]), "n_graze": np.array(x["n_graze"], float),
                                   "b_coll": np.array(b["coll"]), "n_coll": np.array(b["n_coll"], float)}, n_boot=2000)
    return {"D": round(D["value"], 4), "D_low": round(D["ci_low"], 4), "HF": round(HF["value"], 4), "HF_high": round(HF["ci_high"], 4)}


def main() -> None:
    res: dict = {"steps": STEPS, "batch": BATCH}
    with RunLock(REPO / "artifacts/locks/m0-worker.lock"):
        rng = np.random.default_rng(20261110)
        t0 = time.time()
        train_eps = [W.generate_episode(NS, 5000 + w, int(rng.integers(4, 9))) for w in range(200)]
        pool = L.make_pool(train_eps, 120_000, np.random.default_rng(1), W.physics)
        res["pool"] = {"size": pool.size(), "buckets": {n: len(e["p"]) for n, e in pool.by_n.items()}, "seconds": round(time.time() - t0, 1)}
        print("pool", res["pool"], flush=True)
        ev6 = [W.generate_episode(NS, w, 6) for w in range(40)]
        ev10 = [W.generate_episode(NS, 200 + w, 10) for w in range(20)]
        mx.set_default_device(mx.cpu)
        base6, base10 = dyn(ev6, Mo.bounce), dyn(ev10, Mo.bounce)
        res["E-B"] = {"err_coll_mean6": sum(base6["coll"]) / sum(base6["n_coll"]), "n_coll6": sum(base6["n_coll"]), "n_graze6": sum(base6["n_graze"])}
        for arm in L.MEAN_ARMS:
            mx.set_default_device(mx.gpu)
            t0 = time.time()
            model, log = L.train(arm, pool, steps=STEPS, batch=BATCH, seed=1, log_every=max(STEPS // 20, 1))
            train_s = time.time() - t0
            L.save(model, str(SCRATCH / f"explore5-{arm}.safetensors"))
            mx.set_default_device(mx.cpu)
            pm = L.as_process_model(model)
            t0 = time.time()
            r = {"train_seconds": round(train_s, 1), "loss": log,
                 "six": summary(dyn(ev6, pm), base6), "ten": summary(dyn(ev10, pm), base10)}
            r["dyn_eval_seconds"] = round(time.time() - t0, 1)
            print(arm, {k: v for k, v in r.items() if k != "loss"}, "last loss", log[-1], flush=True)
            res[arm] = r
        # identity on 10 worlds with L-int vs E-B / E-P (shared registered noise)
        model = L.load("L-int", str(SCRATCH / "explore5-L-int.safetensors"))
        pm = L.as_process_model(model)
        acc = {}
        t0 = time.time()
        for name, m in (("E-B", Mo.bounce), ("E-P", Mo.true_physics), ("L-int", pm)):
            rows = []
            for w, e in enumerate(ev6[:10]):
                ids, _ = F.track([s.detections for s in e.steps], e.pillars, m, np.random.default_rng(w))
                rows += [x for x in Me.reid(e, ids) if x["collision"]]
            acc[name] = (sum(x["correct"] for x in rows), len(rows))
            print(name, acc[name], round(time.time() - t0, 1), flush=True)
        res["reid_collided_10worlds"] = acc
    (OUT / "results5-learned.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
