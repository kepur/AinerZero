"""S5 摸底第 F 轮（未登记，冻结前设计决定用，只用 lab）：R2 学不起来是不是训练设置的问题。

第 E 轮里，蓝色掩码 + 岭回归在验证集上的 R2 AP 是 0.43，说明标签可学；
第 D 轮里，从零训练的学生只有约 0.03。这里固定单查询 GridHead，改两样：
- 学习率：1e-3 或 3e-4；
- R2/R3 的 BCE 正例权重：1（不加权）或 20（正例只占约 1.4%）。
训练与验证的划分同第 D 轮（lab 世界 0–31 训练，96–127 验证），30 轮。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402

import explore_s5d_gridhead as D  # noqa: E402
from ainerzero.v9.experiments.s5 import train as T  # noqa: E402
from ainerzero.v9.experiments.s5.data import ClipIndex  # noqa: E402
from ainerzero.v9.experiments.s5.heads import GridHead  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402
from ainerzero.v9.experiments.s5.student import Student  # noqa: E402
import numpy as np  # noqa: E402


class WeightedGridHead(GridHead):
    def __init__(self, pos_weight: float, **kw):
        super().__init__(**kw)
        self.pos_weight = float(pos_weight)

    def loss(self, logits, targets):
        t = targets.astype(mx.float32)
        w = 1.0 + (self.pos_weight - 1.0) * t
        return nn.losses.binary_cross_entropy(logits, t, weights=w, with_logits=True)


def run(lr: float, pos_weight: float, seed: int = 0, epochs: int = 30) -> dict:
    train_idx = ClipIndex(D.LAB, worlds=list(range(32)))
    val_idx = ClipIndex(D.LAB, worlds=list(range(96, 128)))
    mx.random.seed(seed)
    student = Student()
    heads = {k: WeightedGridHead(pos_weight, out=(12, 7), d=192, heads=3) for k in ("r2", "r3")}
    cfg = T.TrainConfig(lr=lr, batch_size=8, epochs=epochs, seed=seed, warmup_frac=0.05)
    student, hc, log = T.train_supervised(train_idx, cfg, student=student, heads=heads)
    pred = T.predict(student, hc, val_idx)
    tgt2 = np.stack([np.load(D.LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r2"] for w, c in val_idx.items])
    tgt3 = np.stack([np.load(D.LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r3"] for w, c in val_idx.items])
    return {"lr": lr, "pos_weight": pos_weight, "r2_ap": grid_ap(pred["r2_logit"], tgt2),
            "r3_ap": grid_ap(pred["r3_logit"], tgt3),
            "loss_last": float(np.mean([s["loss"] for s in log["step_logs"][-20:]]))}


def main():
    out = Path(__file__).resolve().parent / "round-f"
    out.mkdir(exist_ok=True)
    rows = []
    for lr, pw in ((3e-4, 1.0), (1e-3, 20.0), (3e-4, 20.0)):
        r = run(lr, pw)
        rows.append(r)
        print(json.dumps(r), flush=True)
    (out / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
