"""S5 摸底第 K 轮（未登记，只用 lab）：「逐 token 打分 + 按位置的线性映射」网格读出头。

第 E 轮里，28×28 蓝色占比 + 岭回归在验证集上 R2 AP 达 0.43：线性模型每一维对应画面固定位置，
几何与远近大小都能学进按位置的权重。第 H–J 轮的注意力池化、几何汇总头都在 0.02–0.05。
这里照第 E 轮的结构：每个 token（最后一个管长，14×14）线性投到 k=4 个分数，展平成 784 维，
再用一层线性映射到 84 个格子（按位置的权重）。只训练这个头，输入是 V-JEPA 特征。
训练 lab 世界 0–31，验证 96–127，30 轮，学习率 1e-3，权重衰减 0.05，批量 8。
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
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402


class FlatHead(nn.Module):
    def __init__(self, d=1024, k=4):
        super().__init__()
        self.norm = nn.LayerNorm(d)
        self.score = nn.Linear(d, k)
        self.out = nn.Linear(196 * k, 84)

    def __call__(self, tokens):
        B = tokens.shape[0]
        last = tokens.reshape(B, 8, 196, -1)[:, 7]               # [B, 196, d]
        s = self.score(self.norm(last)).reshape(B, -1)           # [B, 196*k]
        return self.out(s).reshape(B, 12, 7)


def main():
    Xtr, Ytr = H.load(range(32))
    Xva, Yva = H.load(range(96, 128))
    rows = []
    for k in (1, 4):
        mx.random.seed(0)
        head = FlatHead(k=k)
        opt = optim.AdamW(learning_rate=1e-3, weight_decay=0.05)
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
        r = {"k": k, "val_r2_ap": grid_ap(pv, Yva), "train_r2_ap": grid_ap(pt, Ytr)}
        rows.append(r)
        print(json.dumps(r), flush=True)
    out = Path(__file__).resolve().parent / "round-k"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
