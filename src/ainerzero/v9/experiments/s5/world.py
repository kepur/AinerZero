"""S5 世界与数据划分模块（纯 CPU；权威世界逻辑委托 s4.world）。

管理 S5 的数据分区、注册分区权限守卫，以及生成学生和教师使用的渲染片段。
世界与轨迹的唯一权威来源：ainerzero.v9.experiments.s4.world.generate_episode。
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ainerzero.v9.experiments.s4 import world as s4_world
from ainerzero.v9.experiments.s5.render import (
    DEFAULT,
    DA2_F,
    DA2_H,
    DA2_W,
    Appearance,
    render,
    to_uint8,
)

PARTITIONS: dict[str, int] = {
    "s5p1-pool": 250,
    "s5p1-lab": 128,
    "s5p1-dev": 32,
    "s5p1-final": 48,
    "s5p1-final-shift": 48,
}

REGISTERED: frozenset[str] = frozenset({"s5p1-final", "s5p1-final-shift"})

VALID_PREFIXES: tuple[str, ...] = ("s5p1-", "s5x-", "s5test-")
STEPS_PER_EPISODE: int = 272
CLIPS_PER_EPISODE: int = 16
FRAMES_PER_CLIP: int = 16


def episode(
    namespace: str,
    world_index: int,
    *,
    allow_registered: bool = False,
    registered_run_id: str | None = None,
) -> s4_world.Episode:
    """获取一个世界的 episode 轨迹。

    - 命名空间白名单：只允许 s5p1-*、s5x-*、s5test-*；
    - s5p1-* 分区必须在 PARTITIONS 白名单内，且 world_index 必须落在 [0, PARTITIONS[分区])；
    - REGISTERED 分区必须带 allow_registered=True 且给出非空 registered_run_id，否则抛出 PermissionError；
    - 严格委托 s4.world.generate_episode，每个世界 6 个圆盘、272 步。
    """
    if not any(namespace.startswith(prefix) for prefix in VALID_PREFIXES):
        raise ValueError(
            f"Invalid namespace '{namespace}': must start with one of {VALID_PREFIXES}"
        )

    if namespace.startswith("s5p1-") and namespace not in PARTITIONS:
        raise ValueError(
            f"Unknown s5p1 partition '{namespace}'; registered partitions are {sorted(PARTITIONS.keys())}"
        )

    if namespace in PARTITIONS:
        max_worlds = PARTITIONS[namespace]
        if not (0 <= world_index < max_worlds):
            raise IndexError(
                f"world_index {world_index} out of range [0, {max_worlds}) for partition {namespace}"
            )

    if namespace in REGISTERED and not allow_registered:
        raise PermissionError(
            f"{namespace} is a registered partition; only a registered run may generate it"
        )
    if namespace in REGISTERED and (not registered_run_id or not str(registered_run_id).strip()):
        raise PermissionError(
            f"{namespace} is a registered partition; only a registered run with non-empty registered_run_id may generate it"
        )

    return s4_world.generate_episode(
        namespace,
        world_index,
        6,
        steps=STEPS_PER_EPISODE,
        allow_registered=allow_registered,
    )


def student_clip(
    ep: s4_world.Episode,
    clip_idx: int,
    appearance: Appearance = DEFAULT,
) -> np.ndarray:
    """生成学生端输入的 16 帧 RGB 视频片段 [16, 224, 224, 3] uint8。

    学生只能拿到像素数据，不包含智能体位姿、编号图或深度。
    """
    if not (0 <= clip_idx < CLIPS_PER_EPISODE):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, {CLIPS_PER_EPISODE})")

    start_t = clip_idx * FRAMES_PER_CLIP
    frames = []
    for t in range(start_t, start_t + FRAMES_PER_CLIP):
        st = ep.steps[t]
        img, _ = render(
            st.agent,
            st.positions,
            ep.pillars,
            width=224,
            height=224,
            appearance=appearance,
        )
        frames.append(to_uint8(img))

    return np.stack(frames, axis=0)


def da2_frames(
    ep: s4_world.Episode,
    clip_idx: int,
    appearance: Appearance = DEFAULT,
) -> np.ndarray:
    """生成 Depth Anything V2 教师抽取所需的 8 帧图像 [8, 392, 518, 3] uint8。

    取每个管长（2 帧）的第 2 帧，即片段内的第 1, 3, 5, 7, 9, 11, 13, 15 帧。
    必须采用显式焦距 f=DA2_F (196.0)。
    """
    if not (0 <= clip_idx < CLIPS_PER_EPISODE):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, {CLIPS_PER_EPISODE})")

    base_t = clip_idx * FRAMES_PER_CLIP
    frames = []
    for k in range(8):
        t = base_t + 2 * k + 1
        st = ep.steps[t]
        img, _ = render(
            st.agent,
            st.positions,
            ep.pillars,
            width=DA2_W,
            height=DA2_H,
            f=DA2_F,
            appearance=appearance,
        )
        frames.append(to_uint8(img))

    return np.stack(frames, axis=0)
