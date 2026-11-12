"""S5 摸底第 H 轮（未登记，只用 lab）：GridHead 能不能从 V-JEPA 教师特征里读出 R2。

第 G 轮里，冻结学生（随机、A1/A2/A3 probe）配 GridHead 的 R2 AP 都约 0.03。
这里绕过学生，直接用 lab 的 V-JEPA 特征（[1568, 1024]）训练 GridHead（d=1024）：
- 学不起来：问题在 GridHead 或 BCE 损失；
- 学得起来：问题在学生特征质量。
另加一个对照：每段把 V-JEPA 特征在最后一个管长（第 7 个）上按 14×14 平铺展开，做逐块线性分类，
再按相机几何聚到 12×7 网格；本轮只做第一种，第二种留作后续。
训练 lab 世界 0–31，验证 96–127，30 轮，学习率 1e-3，批量 8。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import mlx.optimizers as optim  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s5.heads import GridHead  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402

LAB = ROOT / "artifacts/v9/s5/data/s5p1-lab"
VJ = ROOT / "artifacts/v9/s5/teachers/vjepa/s5p1-lab"


def load(worlds):
    X, Y = [], []
    for w in worlds:
        for c in range(16):
            X.append(np.load(VJ / f"world_{w:04d}" / f"clip_{c:02d}.vjepa.npy"))
            Y.append(np.load(LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r2"])
    return np.stack(X), np.stack(Y).astype(np.float32)


def main():
    Xtr, Ytr = load(range(32))
    Xva, Yva = load(range(96, 128))
    mx.random.seed(0)
    head = GridHead(out=(12, 7), d=1024, heads=8)
    opt = optim.AdamW(learning_rate=1e-3, weight_decay=0.01)
    rng = np.random.default_rng(0)

    def loss_fn(h, x, y):
        return h.loss(h(x), y)

    vg = nn.value_and_grad(head, loss_fn)
    losses = []
    for epoch in range(30):
        order = rng.permutation(len(Xtr))
        for i in range(0, len(order) - 7, 8):
            b = order[i:i + 8]
            l, g = vg(head, mx.array(Xtr[b].astype(np.float32)), mx.array(Ytr[b]))
            opt.update(head, g)
            mx.eval(head.parameters(), opt.state, l)
            losses.append(float(l.item()))
    preds = []
    for i in range(0, len(Xva), 32):
        preds.append(np.array(head(mx.array(Xva[i:i + 32].astype(np.float32)))))
    pred = np.concatenate(preds)
    tr_pred = np.concatenate([np.array(head(mx.array(Xtr[i:i + 32].astype(np.float32)))) for i in range(0, len(Xtr), 32)])
    res = {"val_r2_ap": grid_ap(pred, Yva), "train_r2_ap": grid_ap(tr_pred, Ytr),
           "loss_first": losses[0], "loss_last": float(np.mean(losses[-20:])), "steps": len(losses)}
    print(json.dumps(res, indent=1))
    out = Path(__file__).resolve().parent / "round-h"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
