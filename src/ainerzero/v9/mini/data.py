"""训练数据：在训练图上做持续性随机游走，记录观察、动作、真值位姿（真值只用于诊断）。"""
from __future__ import annotations

from dataclasses import dataclass
import random

import numpy as np

from . import world as W

# 种子空间与 S2 及其他阶段的分区完全不重叠
TRAIN_SEED0 = 7_100_000
EVAL_SEED0 = 7_900_000


@dataclass
class Dataset:
    obs: np.ndarray        # (N_traj, T+1, D) float32
    act: np.ndarray        # (N_traj, T) int32
    pose: np.ndarray       # (N_traj, T+1, 3) int16，诊断用
    layout_id: np.ndarray  # (N_traj,) int32

    @property
    def n_traj(self) -> int:
        return self.obs.shape[0]

    @property
    def horizon(self) -> int:
        return self.act.shape[1]


def generate(n_layouts: int, traj_per_layout: int, horizon: int, cfg: W.Config,
             seed0: int = TRAIN_SEED0) -> Dataset:
    obs, act, pose, lid = [], [], [], []
    for i in range(n_layouts):
        layout = W.make_layout(seed0 + i, cfg)
        rng = random.Random(seed0 * 7 + i)
        for _ in range(traj_per_layout):
            start = W.random_pose(layout, rng)
            poses, acts = W.walk(layout, start, horizon, rng)
            obs.append(W.iter_views(layout, poses))
            act.append(np.asarray(acts, dtype=np.int32))
            pose.append(np.asarray(poses, dtype=np.int16))
            lid.append(i)
    return Dataset(np.stack(obs), np.stack(act), np.stack(pose), np.asarray(lid, dtype=np.int32))
