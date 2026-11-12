"""S5 摸底第 E 轮（未登记，纯 CPU，只用 lab）：R2 网格标签能不能从画面里学到。

第 D 轮里，从零训练的学生配两种读出头，R2 AP 都只有约 0.03。这里用最朴素的办法检验标签本身：
只取每段最后一帧（R2 标签对应的那一帧），按颜色挑出蓝色像素（圆盘是全场唯一的蓝色物体），
下采样成 28×28 的蓝色占比，用岭回归直接预测 12×7 的占据网格。
训练用 lab 世界 0–31，验证用 lab 世界 96–127，与第 D 轮相同。
如果这样都能明显好过 0.04，说明标签可学，问题出在深度模型的训练设置上。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402

LAB = ROOT / "artifacts/v9/s5/data/s5p1-lab"


def feats(worlds):
    X, Y = [], []
    for w in worlds:
        for c in range(16):
            frame = np.load(LAB / f"world_{w:04d}" / f"clip_{c:02d}.npy")[15].astype(np.float32) / 255
            r, g, b = frame[..., 0], frame[..., 1], frame[..., 2]
            blue = ((b > r + 0.2) & (b > g + 0.15)).astype(np.float32)
            X.append(blue.reshape(28, 8, 28, 8).mean((1, 3)).ravel())
            Y.append(np.load(LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r2"].ravel())
    return np.array(X), np.array(Y, dtype=np.float32)


Xtr, Ytr = feats(range(32))
Xva, Yva = feats(range(96, 128))
mu = Xtr.mean(0)
res = {"train_clips": len(Xtr), "val_clips": len(Xva), "val_positive_rate": float(Yva.mean()),
       "blue_pixel_share_val": float(Xva.mean())}
for lam in (0.1, 1.0, 10.0):
    A = Xtr - mu
    W = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ (Ytr - Ytr.mean(0)))
    pred = (Xva - mu) @ W + Ytr.mean(0)
    res[f"ridge_lambda_{lam:g}_r2_ap"] = grid_ap(pred.reshape(-1, 12, 7), Yva.reshape(-1, 12, 7))
print(json.dumps(res, indent=1))
(Path(__file__).resolve().parent / "round-e").mkdir(exist_ok=True)
(Path(__file__).resolve().parent / "round-e" / "result.json").write_text(json.dumps(res, indent=1))
