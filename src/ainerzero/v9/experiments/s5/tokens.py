"""S5 Tubelet Patches 与 RLT 接口模块（纯 NumPy）。

实现规范：
- `tubelet_patches`：管长 2、块 16，展平顺序为（管长内帧, 块行, 块列, 通道），像素值归一化至 [0, 1] float32。
  时空 token 顺序为 (t, h, w)，与 V-JEPA 2.1 源码（`PatchEmbed3D.__call__`，行 110-115）严格一致。
- `rlt_keep`：权威接入 `ainerzero.v9.tokenization.rlt.rlt_frame_dropping`。
  返回 `(keep, run_len)`，保留位置记录代表管长数，被并掉位置记 0。
- `restoration_error`：统计被并掉的块与其所并入 token 的 ‖·‖∞ 分布，返回 (median, p95)。
"""
from __future__ import annotations

from typing import NamedTuple
import numpy as np

from ainerzero.v9.tokenization.rlt import rlt_frame_dropping

TUBELET_SIZE: int = 2
PATCH_SIZE: int = 16
FRAMES: int = 16
HEIGHT: int = 224
WIDTH: int = 224
CHANNELS: int = 3

NUM_TUBES: int = FRAMES // TUBELET_SIZE      # 8
GRID_H: int = HEIGHT // PATCH_SIZE           # 14
GRID_W: int = WIDTH // PATCH_SIZE            # 14
PATCH_DIM: int = TUBELET_SIZE * PATCH_SIZE * PATCH_SIZE * CHANNELS  # 1536


class RestorationError:
    def __init__(self, median: float, p95: float):
        self.median = float(median)
        self.p95 = float(p95)

    def __iter__(self):
        yield self.median
        yield self.p95

    def __getitem__(self, idx):
        if idx == 0 or idx == "median":
            return self.median
        if idx == 1 or idx == "p95":
            return self.p95
        raise IndexError(idx)

    def __repr__(self) -> str:
        return f"RestorationError(median={self.median}, p95={self.p95})"

    def __eq__(self, other) -> bool:
        if isinstance(other, (RestorationError, tuple, list)):
            return tuple(self) == tuple(other)
        return False


def tubelet_patches(clip_uint8: np.ndarray) -> np.ndarray:
    """将视频切片 [16, 224, 224, 3] 转换为时空 Tubelet 块 [8, 14, 14, 1536]。

    支持单 clip 或带批次维 [B, 16, 224, 224, 3]。
    展平顺序内部为：(dt, dh, dw, c)，外部为 (t, h, w)。
    """
    has_batch = (clip_uint8.ndim == 5)
    if not has_batch and clip_uint8.ndim != 4:
        raise ValueError(f"Expected 4D or 5D input, got {clip_uint8.ndim}D")

    clip = clip_uint8 if has_batch else clip_uint8[np.newaxis, ...]
    B, T, H, W, C = clip.shape

    if (T, H, W, C) != (FRAMES, HEIGHT, WIDTH, CHANNELS):
        raise ValueError(
            f"Expected shape (*, {FRAMES}, {HEIGHT}, {WIDTH}, {CHANNELS}), got {clip.shape}"
        )

    # 1. 拆分网格与管长
    # (B, 8, 2, 14, 16, 14, 16, 3)
    reshaped = clip.reshape(
        B,
        NUM_TUBES,
        TUBELET_SIZE,
        GRID_H,
        PATCH_SIZE,
        GRID_W,
        PATCH_SIZE,
        CHANNELS,
    )

    # 2. 转置为 (B, t, h, w, dt, dh, dw, c)
    transposed = reshaped.transpose(0, 1, 3, 5, 2, 4, 6, 7)

    # 3. 展平成 (B, 8, 14, 14, 1536) 并归一化到 float32 [0, 1]
    patches = transposed.reshape(B, NUM_TUBES, GRID_H, GRID_W, PATCH_DIM).astype(np.float32) / 255.0

    return patches if has_batch else patches[0]


def rlt_keep(
    patches: np.ndarray, tau: float
) -> tuple[np.ndarray, np.ndarray]:
    """对 patches [8, 14, 14, 1536] 执行 RLT frame dropping（权威调用 rlt.py）。

    返回：
        keep: bool [8, 14, 14] 保留掩码
        run_len: int [8, 14, 14] 游程长度（保留处为 1..8，被并掉处为 0）
    """
    has_batch = (patches.ndim == 5)
    if not has_batch and patches.ndim != 4:
        raise ValueError(f"Expected 4D or 5D input, got {patches.ndim}D")

    arr = patches if has_batch else patches[np.newaxis, ...]
    B, T, H, W, D = arr.shape

    all_keep = []
    all_run_len = []

    for b in range(B):
        # 权威模块输入要求: [T, ph, pw, D]
        chunk = arr[b]  # [8, 14, 14, 1536]
        retained, run_lengths, positions, restoration, rate = rlt_frame_dropping(
            chunk, tau
        )

        keep_mask = np.zeros((T, H, W), dtype=bool)
        run_len_mask = np.zeros((T, H, W), dtype=int)

        # 还原 keep_mask 与 run_len_mask：
        # rlt_frame_dropping 中，第一帧始终为 True
        # 随后的 t >= 1 只有在 diff_max >= tau 时保留
        # 根据 positions 和 run_lengths 填回
        # 注意 positions 对应每个保留的 token
        token_idx = 0
        for pos_idx in range(H * W):
            h = pos_idx // W
            w = pos_idx % W
            # 在当前位置 (h, w)，顺序读取该位置的所有保留 token
            curr_t = 0
            while curr_t < T:
                # 记录保留
                keep_mask[curr_t, h, w] = True
                rl = int(run_lengths[token_idx])
                run_len_mask[curr_t, h, w] = rl
                token_idx += 1
                curr_t += rl

        all_keep.append(keep_mask)
        all_run_len.append(run_len_mask)

    keep_res = np.stack(all_keep, axis=0)
    run_len_res = np.stack(all_run_len, axis=0)

    return (keep_res, run_len_res) if has_batch else (keep_res[0], run_len_res[0])


def rlt_keep_fast(
    patches: np.ndarray, tau: float
) -> tuple[np.ndarray, np.ndarray]:
    """对 patches [8, 14, 14, 1536] 执行纯 NumPy 向量化 RLT 保留掩码与游程长度计算。

    与 `rlt_keep`（调用权威 `rlt_frame_dropping`）逐元素严格一致：
    - 算法照式 10：`keep[0] = True`；`keep[t] = max|p_t - p_{t-1}| >= tau`。
    - `run_len` 为保留位置到下一个保留位置的距离（或到序列末尾 T 的距离），被并掉位置为 0。

    返回：
        keep: bool [8, 14, 14]（或 [B, 8, 14, 14]）保留掩码
        run_len: int [8, 14, 14]（或 [B, 8, 14, 14]）游程长度
    """
    has_batch = (patches.ndim == 5)
    if not has_batch and patches.ndim != 4:
        raise ValueError(f"Expected 4D or 5D input, got {patches.ndim}D")
    assert tau >= 0, f"tau must be >= 0, got {tau}"

    arr = patches if has_batch else patches[np.newaxis, ...]
    B, T, H, W, _ = arr.shape

    keep = np.zeros((B, T, H, W), dtype=bool)
    keep[:, 0] = True
    if T > 1:
        diff_max = np.max(np.abs(arr[:, 1:] - arr[:, :-1]), axis=-1)
        keep[:, 1:] = diff_max >= tau

    t_idx = np.arange(T, dtype=int)[None, :, None, None]
    kept_t = np.where(keep, t_idx, T)
    next_kept = np.full((B, T, H, W), T, dtype=int)
    if T > 1:
        next_kept[:, :-1] = np.minimum.accumulate(kept_t[:, :0:-1], axis=1)[:, ::-1]

    run_len = np.where(keep, next_kept - t_idx, 0)
    return (keep, run_len) if has_batch else (keep[0], run_len[0])


def restoration_error(
    patches: np.ndarray, keep: np.ndarray
) -> RestorationError:
    """计算被并掉的块与它所并入 anchor token 之间的 ‖·‖∞ 分布。

    返回:
        RestorationError(median, p95)
    """
    has_batch = (patches.ndim == 5)
    arr = patches if has_batch else patches[np.newaxis, ...]
    k_arr = keep if has_batch else keep[np.newaxis, ...]
    B, T, H, W, D = arr.shape

    errors: list[float] = []

    for b in range(B):
        for h in range(H):
            for w in range(W):
                anchor_vec = None
                for t in range(T):
                    if k_arr[b, t, h, w]:
                        anchor_vec = arr[b, t, h, w]
                    else:
                        assert anchor_vec is not None, "First frame must be kept"
                        # ‖·‖∞ 范数: max(|p_t - anchor|)
                        diff_inf = float(np.max(np.abs(arr[b, t, h, w] - anchor_vec)))
                        errors.append(diff_inf)

    if not errors:
        return RestorationError(0.0, 0.0)

    errs = np.array(errors, dtype=np.float64)
    med = float(np.median(errs))
    p95 = float(np.percentile(errs, 95))
    return RestorationError(med, p95)
