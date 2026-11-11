"""S5 摸底第 B 轮（未登记）：小 MLX 学生编码器每步训练要多久，用来写预算。

只量时间与内存，不学任何东西（输入是随机张量）。量三件事：
1. 时空 ViT（224²、16 帧、管长 2、块 16 → 1568 个 token）在不同宽度、深度、批量下，前向 + 反向 + AdamW 一步的中位耗时；
2. 只保留一部分 token（模拟 RLT 去掉停帧块）时，耗时怎么随保留率变化；
3. 峰值内存。

运行（须持锁，主环境 .venv）：
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py \
      artifacts/locks/m0-worker.lock .venv/bin/python -I reports/V9-S5-DESIGN/tier1-explore/explore_s5b_cost.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten

OUT = Path(__file__).resolve().parent / "round-b"
TOKENS_FULL = 8 * 14 * 14          # 16 frames / tubelet 2, 224 / 16 squared
PATCH_DIM = 2 * 16 * 16 * 3        # one tubelet patch, flattened


class Block(nn.Module):
    def __init__(self, d, heads):
        super().__init__()
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.attn = nn.MultiHeadAttention(d, heads)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))

    def __call__(self, x):
        h = self.n1(x)
        x = x + self.attn(h, h, h)
        return x + self.mlp(self.n2(x))


class Student(nn.Module):
    def __init__(self, d, depth, heads, out_dim):
        super().__init__()
        self.embed = nn.Linear(PATCH_DIM, d)
        self.pos = mx.zeros((TOKENS_FULL, d))
        self.blocks = [Block(d, heads) for _ in range(depth)]
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, out_dim)          # stands in for distillation / readout heads

    def __call__(self, patches, idx):
        x = self.embed(patches) + self.pos[idx]
        for b in self.blocks:
            x = b(x)
        return self.head(self.norm(x))


def bench(d, depth, heads, batch, keep, out_dim=1024, steps=12):
    mx.random.seed(0)
    model = Student(d, depth, heads, out_dim)
    mx.eval(model.parameters())
    n_params = sum(v.size for _, v in tree_flatten(model.parameters()))
    opt = optim.AdamW(1e-4)
    n_tok = int(round(TOKENS_FULL * keep))
    rng = np.random.default_rng(0)
    idx = mx.array(np.sort(rng.choice(TOKENS_FULL, n_tok, replace=False)))
    x = mx.random.normal((batch, n_tok, PATCH_DIM))
    y = mx.random.normal((batch, n_tok, out_dim))

    def loss_fn(m):
        p = m(x, idx)
        num = (p * y).sum(-1)
        den = mx.sqrt((p * p).sum(-1) * (y * y).sum(-1)) + 1e-6
        return (1 - num / den).mean()

    vg = nn.value_and_grad(model, loss_fn)
    times = []
    mx.reset_peak_memory()
    for _ in range(steps):
        t0 = time.perf_counter()
        loss, g = vg(model)
        opt.update(model, g)
        mx.eval(model.parameters(), opt.state, loss)
        times.append(time.perf_counter() - t0)
    return {"d": d, "depth": depth, "heads": heads, "batch": batch, "keep": keep, "tokens": n_tok,
            "params_m": n_params / 1e6, "first_step_s": times[0], "median_step_s": float(np.median(times[2:])),
            "clips_per_s": batch / float(np.median(times[2:])), "peak_gb": mx.get_peak_memory() / 1e9}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mx.set_default_device(mx.gpu)
    rows = []
    for cfg in ((192, 6, 3, 8, 1.0), (192, 6, 3, 16, 1.0), (256, 8, 4, 8, 1.0), (384, 8, 6, 8, 1.0),
                (192, 6, 3, 8, 0.5), (192, 6, 3, 8, 0.25), (256, 8, 4, 8, 0.5)):
        r = bench(*cfg)
        rows.append(r)
        print(json.dumps(r), flush=True)
    (OUT / "result.json").write_text(json.dumps({"mlx": mx.__version__, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
