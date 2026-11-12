"""S5 摸底第 I 轮（未登记，只用 lab）：按相机几何汇总的网格读出头。

第 H 轮里，单查询 GridHead 直接读 V-JEPA 特征，连训练集 R2 AP 都只有 0.045，损失停在先验熵附近，
说明它只学到先验。这里换成利用相机几何（内参已知，不是真值）的读出头：
- 取最后一个管长的 14×14 个 token，每个 token 线性输出 7 个距离格 logit；
- 方位格 b 覆盖 [-45° + 7.5° b, -45° + 7.5° (b+1)]，正方位在画面左侧；
  token 列 j 的中心角为 atan((112 − (16 j + 8)) / 112)，与方位格重叠的列（全部行）归入该格；
- 每个 (方位格, 距离格) 的 logit = 该格所属 token 上对应距离 logit 的 logsumexp。
另做一个更宽松的对照：同样结构，但每个 token 输出全部 84 个格的 logit，再对所有 token 做 logsumexp（不利用几何）。
训练 lab 世界 0–31，验证 96–127，30 轮，学习率 1e-3，批量 8。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import mlx.optimizers as optim  # noqa: E402
import numpy as np  # noqa: E402

import explore_s5h_teacher_gridhead as H  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402


def column_bin_mask() -> np.ndarray:
    """[12, 14] 0/1: which token columns overlap each bearing bin."""
    m = np.zeros((12, 14), dtype=np.float32)
    for j in range(14):
        lo = math.degrees(math.atan((112 - (16 * j + 16)) / 112))
        hi = math.degrees(math.atan((112 - (16 * j)) / 112))
        for b in range(12):
            b_lo, b_hi = -45 + 7.5 * b, -45 + 7.5 * (b + 1)
            if min(hi, b_hi) > max(lo, b_lo):
                m[b, j] = 1.0
    return m


class GeoHead(nn.Module):
    def __init__(self, d=1024, geometric=True):
        super().__init__()
        self.geometric = geometric
        self.lin = nn.Linear(d, 7 if geometric else 84)
        self.colmask = mx.array(column_bin_mask())                      # [12, 14]

    def __call__(self, tokens):                                         # tokens [B, 1568, d]
        B = tokens.shape[0]
        last = tokens.reshape(B, 8, 14, 14, -1)[:, 7]                   # [B, 14(rows), 14(cols), d]
        z = self.lin(last)                                              # [B, 14, 14, 7 or 84]
        if not self.geometric:
            return mx.logsumexp(z.reshape(B, 196, 84), axis=1).reshape(B, 12, 7)
        z = mx.logsumexp(z, axis=1)                                     # over rows -> [B, 14(cols), 7]
        neg = (1.0 - self.colmask)[None, :, :, None] * -1e9             # [1, 12, 14, 1]
        return mx.logsumexp(z[:, None, :, :] + neg, axis=2)             # [B, 12, 7]

    def loss(self, logits, y):
        return nn.losses.binary_cross_entropy(logits, y, with_logits=True)


def fit(geometric: bool, Xtr, Ytr, Xva, Yva) -> dict:
    mx.random.seed(0)
    head = GeoHead(geometric=geometric)
    opt = optim.AdamW(learning_rate=1e-3, weight_decay=0.01)
    vg = nn.value_and_grad(head, lambda h, x, y: h.loss(h(x), y))
    rng = np.random.default_rng(0)
    for _ in range(30):
        order = rng.permutation(len(Xtr))
        for i in range(0, len(order) - 7, 8):
            b = order[i:i + 8]
            l, g = vg(head, mx.array(Xtr[b].astype(np.float32)), mx.array(Ytr[b]))
            opt.update(head, g)
            mx.eval(head.parameters(), opt.state, l)
    pv = np.concatenate([np.array(head(mx.array(Xva[i:i + 32].astype(np.float32)))) for i in range(0, len(Xva), 32)])
    pt = np.concatenate([np.array(head(mx.array(Xtr[i:i + 32].astype(np.float32)))) for i in range(0, len(Xtr), 32)])
    return {"geometric": geometric, "val_r2_ap": grid_ap(pv, Yva), "train_r2_ap": grid_ap(pt, Ytr)}


def main():
    print("column->bin mask rows per bin:", column_bin_mask().sum(1).tolist(), flush=True)
    Xtr, Ytr = H.load(range(32))
    Xva, Yva = H.load(range(96, 128))
    rows = [fit(True, Xtr, Ytr, Xva, Yva), fit(False, Xtr, Ytr, Xva, Yva)]
    for r in rows:
        print(json.dumps(r), flush=True)
    out = Path(__file__).resolve().parent / "round-i"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
