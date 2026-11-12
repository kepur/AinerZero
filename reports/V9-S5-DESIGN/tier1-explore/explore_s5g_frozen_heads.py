"""S5 摸底第 G 轮（未登记，冻结前设计决定用，只用 lab）：冻结学生 + 训读出头，R2 学不学得起来。

第 D、F 轮里，从零端到端训练的学生（A0 设定）R2 AP 都只有约 0.03，换头、换学习率、加正例权重都没用。
这里把 probe（probe-20261112b）里训好的蒸馏学生（A1、A2、A3 各 1000 步，约设计蒸馏步数的 1/10）
冻结，只训 R1/R2/R3 读出头；另加一个随机初始化、冻结不训的学生作下界。
训练用 lab 世界 0–31（512 段），验证用 lab 世界 96–127，30 轮，学习率 1e-3。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s5 import train as T  # noqa: E402
from ainerzero.v9.experiments.s5.data import ClipIndex  # noqa: E402
from ainerzero.v9.experiments.s5.metrics import grid_ap, logd_rmse  # noqa: E402
from ainerzero.v9.experiments.s5.student import Student  # noqa: E402

LAB = ROOT / "artifacts/v9/s5/data/s5p1-lab"
W = ROOT / "artifacts/v9/s5/runs/probe-probe-20261112b-20261112T110650Z/weights"


def run(name: str, weights: Path | None) -> dict:
    train_idx = ClipIndex(LAB, worlds=list(range(32)))
    val_idx = ClipIndex(LAB, worlds=list(range(96, 128)))
    mx.random.seed(0)
    student = Student()
    if weights is not None:
        student.load_weights(str(weights))
    cfg = T.TrainConfig(lr=1e-3, batch_size=8, epochs=30, seed=0, warmup_frac=0.05)
    heads, log = T.train_heads(student, train_idx, cfg)
    pred = T.predict(student, heads, val_idx)
    lab = [np.load(LAB / f"world_{w:04d}" / f"labels_{c:02d}.npz") for w, c in val_idx.items]
    return {"student": name,
            "r2_ap": grid_ap(pred["r2_logit"], np.stack([d["r2"] for d in lab])),
            "r3_ap": grid_ap(pred["r3_logit"], np.stack([d["r3"] for d in lab])),
            "r1_rmse": logd_rmse(pred["r1_logd"], np.stack([d["r1_logd"] for d in lab])),
            "cache_s": log.get("cache_time_s")}


def main():
    out = Path(__file__).resolve().parent / "round-g"
    out.mkdir(exist_ok=True)
    rows = []
    for name, wf in (("random-frozen", None), ("A1-probe", W / "probe-distill-A1-s0-student.npz"),
                     ("A2-probe", W / "probe-distill-A2-s0-student.npz"), ("A3-probe", W / "probe-distill-A3-s0-student.npz")):
        r = run(name, wf)
        rows.append(r)
        print(json.dumps(r), flush=True)
    (out / "result.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
