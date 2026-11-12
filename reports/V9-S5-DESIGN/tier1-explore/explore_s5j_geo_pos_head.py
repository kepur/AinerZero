"""S5 摸底第 J 轮（未登记，只用 lab）：带显式位置的几何网格读出头。

第 I 轮的几何头连训练集都拟合不了。原因判断：V-JEPA 用 RoPE，token 本身不带绝对位置；
一个共享线性层既不知道 token 在哪一行、哪一列，又要从单个 token 判断距离。
这里给每个 token 拼上固定的行、列 one-hot（14 + 14 维），过两层 MLP，输出 1 个「这里有圆盘」logit
和 7 个距离 logit；格 (b, d) 的 logit = 方位格 b 所含 token 上 (presence + distance_d) 的 logsumexp。
只用最后一个管长（R2 对应段末帧）。训练 lab 世界 0–31，验证 96–127，30 轮，学习率 1e-3，批量 8。
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
import mlx.optimizers as optim  # noqa: E402
import numpy as np  # noqa: E402

import explore_s5h_teacher_gridhead as H  # noqa: E402
from explore_s5i_geo_head import column_bin_mask  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402


def pos_features() -> np.ndarray:
    rows = np.repeat(np.eye(14, dtype=np.float32)[:, None, :], 14, axis=1)   # [14,14,14] row one-hot
    cols = np.repeat(np.eye(14, dtype=np.float32)[None, :, :], 14, axis=0)   # [14,14,14] col one-hot
    return np.concatenate([rows, cols], -1)                                   # [14,14,28]


class GeoPosHead(nn.Module):
    def __init__(self, d=1024, hidden=256):
        super().__init__()
        self.pos = mx.array(pos_features())
        self.mlp = nn.Sequential(nn.Linear(d + 28, hidden), nn.GELU(), nn.Linear(hidden, 8))
        self.colmask = mx.array(column_bin_mask())

    def __call__(self, tokens):
        B = tokens.shape[0]
        last = tokens.reshape(B, 8, 14, 14, -1)[:, 7]
        x = mx.concatenate([last, mx.broadcast_to(self.pos[None], (B, 14, 14, 28))], axis=-1)
        z = self.mlp(x)                                          # [B, 14, 14, 8]
        z = z[..., :1] + z[..., 1:]                              # presence + distance -> [B, 14, 14, 7]
        z = mx.logsumexp(z, axis=1)                              # over rows -> [B, 14 cols, 7]
        neg = (1.0 - self.colmask)[None, :, :, None] * -1e9
        return mx.logsumexp(z[:, None] + neg, axis=2)            # [B, 12, 7]


def main():
    Xtr, Ytr = H.load(range(32))
    Xva, Yva = H.load(range(96, 128))
    mx.random.seed(0)
    head = GeoPosHead()
    opt = optim.AdamW(learning_rate=1e-3, weight_decay=0.01)
    vg = nn.value_and_grad(head, lambda h, x, y: nn.losses.binary_cross_entropy(h(x), y, with_logits=True))
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
    res = {"val_r2_ap": grid_ap(pv, Yva), "train_r2_ap": grid_ap(pt, Ytr)}
    print(json.dumps(res), flush=True)
    out = Path(__file__).resolve().parent / "round-j"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
