"""S5 摸底第 D 轮（未登记，冻结前设计决定用）：R2/R3 网格读出头的结构。

probe（use id probe-20261112b）里，A0 用满 2048 段 lab 训练 30 轮，dev 上 R2 AP 只有 0.040
（随机 0.014，只用各格子正例率当分数 0.023）。怀疑单查询注意力池化 + MLP 的 GridHead 太弱：
它要把 1568 个 token 压成一个向量，再一次出 84 个格子，做不好「哪个方位、哪个距离」这种定位。

这里比较两种头，学生都从零端到端训练（A0 设定），只用 lab，不碰 dev：
- single：现有 `heads.GridHead`（1 个查询）；
- percell：每个格子一个可学查询（84 个），各自对 token 做按 mask 的注意力，再经共享线性层出 1 个 logit。
训练用 lab 世界 0–31（512 段，即 L=512 一档），验证用 lab 世界 96–127（512 段）。

运行（须持锁，主环境）：
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py \
      artifacts/locks/m0-worker.lock .venv/bin/python -I reports/V9-S5-DESIGN/tier1-explore/explore_s5d_gridhead.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s5 import train as T  # noqa: E402
from ainerzero.v9.experiments.s5.data import ClipIndex  # noqa: E402
from ainerzero.v9.experiments.s5.heads import GridHead  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap  # noqa: E402
from ainerzero.v9.experiments.s5.student import Student  # noqa: E402

LAB = ROOT / "artifacts/v9/s5/data/s5p1-lab"
OUT = Path(__file__).resolve().parent / "round-d"


class PerCellQueryHead(nn.Module):
    """One learned query per grid cell; masked attention over tokens; shared linear readout."""

    def __init__(self, out=(12, 7), d=192, heads=3):
        super().__init__()
        self.out = out
        n = out[0] * out[1]
        self.queries = mx.random.normal((n, d)) * 0.02
        self.attn = nn.MultiHeadAttention(d, heads)
        self.norm = nn.LayerNorm(d)
        self.mlp = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    def __call__(self, tokens, mask=None):
        B = tokens.shape[0]
        q = mx.broadcast_to(self.queries[None], (B, *self.queries.shape))
        attn_mask = None
        if mask is not None:
            attn_mask = mx.where(mask.reshape(B, 1, 1, -1), 0.0, -1e9)
        pooled = self.attn(q, tokens, tokens, mask=attn_mask)            # [B, 84, d]
        return self.mlp(self.norm(pooled)).reshape(B, *self.out)

    def loss(self, logits, targets):
        return nn.losses.binary_cross_entropy(logits, targets.astype(mx.float32), with_logits=True)


def run(kind: str, seed: int = 0, epochs: int = 30) -> dict:
    train_idx = ClipIndex(LAB, worlds=list(range(32)))
    val_idx = ClipIndex(LAB, worlds=list(range(96, 128)))
    mx.random.seed(seed)
    student = Student()
    if kind == "single":
        heads = {"r2": GridHead(out=(12, 7), d=192, heads=3), "r3": GridHead(out=(12, 7), d=192, heads=3)}
    else:
        heads = {"r2": PerCellQueryHead(), "r3": PerCellQueryHead()}
    cfg = T.TrainConfig(lr=1e-3, batch_size=8, epochs=epochs, seed=seed, warmup_frac=0.05)
    t0 = time.time()
    student, hc, log = T.train_supervised(train_idx, cfg, student=student, heads=heads)
    train_s = time.time() - t0
    pred = T.predict(student, hc, val_idx)
    tgt2 = np.stack([np.load(LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r2"] for w, c in val_idx.items])
    tgt3 = np.stack([np.load(LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz")["r3"] for w, c in val_idx.items])
    steps = log["step_logs"]
    return {"kind": kind, "seed": seed, "epochs": epochs, "train_clips": len(train_idx), "val_clips": len(val_idx),
            "r2_ap": grid_ap(pred["r2_logit"], tgt2), "r3_ap": grid_ap(pred["r3_logit"], tgt3),
            "loss_first": steps[0]["loss"], "loss_last": float(np.mean([s["loss"] for s in steps[-20:]])),
            "train_s": train_s, "data_fraction": float(np.sum([s["data_s"] for s in steps]) / max(1e-9, train_s))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in ("single", "percell"):
        r = run(kind)
        rows.append(r)
        print(json.dumps(r), flush=True)
    (OUT / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
