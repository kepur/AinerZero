"""S4 第一阶段一级摸底第八轮：学习率衰减与加宽消息能否同时拿到 D 和 HF。

未登记，只用来定训练写法，不作结论。只用命名空间 s4x-explore，世界、样本池与第五至七轮相同：
  - 训练世界 5000–5199（4–8 盘均匀），样本池 12 万；评测世界 0–39（6 盘）、200–219（10 盘）。
第七轮的结果：近失样本过采样没有压住擦边步误差（HF 仍约 0.12），问题不在批的构成。
本轮试两样：学习率从 1e-3 余弦衰减到给定的终值（learned_mlx.LR_END；写 none 表示不衰减），以及消息宽度。
配置在命令行给出，格式 名字=臂,碰撞份额,近失份额,消息宽度,学习率终值,步数，分号分隔。
每个配置 1 个种子；MLX GPU 训练，CPU 评测；持共享锁。另量 10 个世界上有碰撞事件的重识别（与 E-B、E-P 比）。

用法：python -I explore8.py <标签> "<配置;配置;…>" [存权重的目录]
权重只为事后诊断（diag_graze.py）而存，放在仓库之外的临时目录。
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
BATCH = 256
TAG = sys.argv[1]
WEIGHTS = Path(sys.argv[3]) if len(sys.argv) > 3 else None
CONFIGS = []
for item in sys.argv[2].split(";"):
    label, spec = item.split("=")
    arm, coll, near, msg, lr_end, steps = spec.split(",")
    CONFIGS.append((label, arm, float(coll), float(near), int(msg), None if lr_end == "none" else float(lr_end), int(steps)))


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
    res: dict = {"batch": BATCH, "clip": L.CLIP, "near_gap": L.NEAR_GAP,
                 "configs": {c[0]: {"arm": c[1], "coll_share": c[2], "near_share": c[3], "msg": c[4], "lr_end": c[5], "steps": c[6]} for c in CONFIGS}}
    out = OUT / f"results8-{TAG}.json"
    if out.exists():
        raise SystemExit(f"结果文件已存在，不覆盖：{out}")
    with RunLock(REPO / "artifacts/locks/m0-worker.lock"):
        rng = np.random.default_rng(20261110)
        train_eps = [W.generate_episode(NS, 5000 + w, int(rng.integers(4, 9))) for w in range(200)]
        pool = L.make_pool(train_eps, 120_000, np.random.default_rng(1), W.physics)
        kinds = {n: L.sample_kinds(e) for n, e in pool.by_n.items()}
        res["pool"] = {"size": pool.size(), "contact": int(sum(len(h) for h, _ in kinds.values())), "near": int(sum(len(q) for _, q in kinds.values()))}
        print("pool", res["pool"], flush=True)
        ev6 = [W.generate_episode(NS, w, 6) for w in range(40)]
        ev10 = [W.generate_episode(NS, 200 + w, 10) for w in range(20)]
        mx.set_default_device(mx.cpu)
        base6, base10 = dyn(ev6, Mo.bounce), dyn(ev10, Mo.bounce)
        res["reid"] = {"E-B": reid_collided(ev6[:10], Mo.bounce), "E-P": reid_collided(ev6[:10], Mo.true_physics)}
        print("reid", res["reid"], flush=True)
        for name, arm, coll, near, msg, lr_end, STEPS in CONFIGS:
            L.MSG, L.COLL_SHARE, L.NEAR_SHARE, L.LR_END = msg, coll, near, lr_end
            mx.set_default_device(mx.gpu)
            t0 = time.time()
            try:
                model, log = L.train(arm, pool, steps=STEPS, batch=BATCH, seed=1, log_every=max(STEPS // 20, 1))
            except FloatingPointError as exc:
                res[name] = {"error": str(exc)}
                print(name, "ERROR", exc, flush=True)
                continue
            train_s = time.time() - t0
            if WEIGHTS is not None:
                L.save(model, str(WEIGHTS / f"explore8-{TAG}-{name}.safetensors"))
            mx.set_default_device(mx.cpu)
            pm = L.as_process_model(model)
            r = {"train_seconds": round(train_s, 1), "params": L.param_count(model), "loss": log,
                 "six": summary(dyn(ev6, pm), base6), "ten": summary(dyn(ev10, pm), base10)}
            if arm != "L-ind":
                r["reid"] = reid_collided(ev6[:10], pm)
            print(name, {k: v for k, v in r.items() if k != "loss"}, "last loss", log[-1], flush=True)
            res[name] = r
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
