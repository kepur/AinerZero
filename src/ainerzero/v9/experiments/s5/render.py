"""S5 第一人称光线投射渲染器（NumPy；权威实现，纯 CPU）。

把 S4 圆盘世界（`src/ainerzero/v9/experiments/s4/world.py`）从智能体位姿渲染成 RGB 画面，并给出逐像素真值深度。
基于 `reports/V9-S5-DESIGN/tier1-explore/render.py` 移植，支持显式焦距 f 与外观域切换 Appearance。

场景：
- 10×10 场地，四面墙高 1.2；
- 3 根柱子，高 2.0；
- 若干同外观圆盘，半径 0.3、高 0.6，没有编号；
- 地面、天空。

相机：
- 高 0.5，针孔模型（每列按真实方向投射，按光轴距离做透视）；
- 默认 f=None 时按水平 90° FOV 计算：f = (width / 2) / tan(45°)；
- 针对 Depth Anything V2 帧渲染：DA2_W=518, DA2_H=392, DA2_F=196.0。
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

ARENA = 10.0
WALL_H, PILLAR_H, DISK_H = 1.2, 2.0, 0.6
DISK_R = 0.3
CAM_H = 0.5
FOV = math.radians(90)

DA2_W: int = 518
DA2_H: int = 392
DA2_F: float = 196.0


@dataclass(frozen=True)
class Appearance:
    """渲染外观参数（冻结配置），支持领域偏移（Shift）。"""
    sky: tuple[float, float, float]
    floor: tuple[float, float, float]
    wall: tuple[float, float, float]
    pillar: tuple[float, float, float]
    disk: tuple[float, float, float]
    checker_size: float = 1.0
    stripe_width: float = 0.5
    light_dir: tuple[float, float] = (0.6, 0.8)
    fog_coeff: float = 0.06
    floor_shade_coeff: float = 0.08


# 预设 1：DEFAULT 与摸底版 tier1-explore/render.py 完全一致
DEFAULT = Appearance(
    sky=(0.62, 0.78, 0.95),
    floor=(0.45, 0.50, 0.42),
    wall=(0.70, 0.70, 0.72),
    pillar=(0.55, 0.38, 0.25),
    disk=(0.20, 0.35, 0.85),
    checker_size=1.0,
    stripe_width=0.5,
    light_dir=(0.6, 0.8),
    fog_coeff=0.06,
    floor_shade_coeff=0.08,
)

# 预设 2：SHIFT_BG 只换背景（天空、地面、墙、柱子、方格、条纹、光照、雾），圆盘保持原样
SHIFT_BG = Appearance(
    sky=(0.85, 0.65, 0.50),        # 黄昏暖橙天空
    floor=(0.35, 0.35, 0.40),      # 深灰板岩地面
    wall=(0.55, 0.50, 0.45),       # 砂岩色墙体
    pillar=(0.25, 0.45, 0.50),     # 青铜/蓝绿色柱子
    disk=(0.20, 0.35, 0.85),       # 圆盘保持蓝色不变
    checker_size=1.5,              # 方格变大 1.5 倍
    stripe_width=0.3,              # 条纹变细
    light_dir=(-0.8, 0.6),         # 光源方向变到左侧
    fog_coeff=0.12,                # 浓雾
    floor_shade_coeff=0.12,
)

# 预设 3：SHIFT_ALL 在 SHIFT_BG 基础上连圆盘颜色一起换（形状大小不变）
SHIFT_ALL = Appearance(
    sky=(0.85, 0.65, 0.50),
    floor=(0.35, 0.35, 0.40),
    wall=(0.55, 0.50, 0.45),
    pillar=(0.25, 0.45, 0.50),
    disk=(0.85, 0.25, 0.20),       # 圆盘变为醒目红橙色
    checker_size=1.5,
    stripe_width=0.3,
    light_dir=(-0.8, 0.6),
    fog_coeff=0.12,
    floor_shade_coeff=0.12,
)


def _circle_t(ox: float, oy: float, dx: np.ndarray, dy: np.ndarray, cx: float, cy: float, r: float):
    """Nearest positive ray parameter t of the hit with a circle (inf if none); also the hit normal."""
    fx, fy = ox - cx, oy - cy
    b = fx * dx + fy * dy
    c = fx * fx + fy * fy - r * r
    disc = b * b - c
    hit = disc >= 0
    sq = np.sqrt(np.where(hit, disc, 0.0))
    t = -b - sq
    t = np.where(hit & (t > 1e-6), t, np.inf)
    nx = (ox + t * dx - cx) / r
    ny = (oy + t * dy - cy) / r
    return t, nx, ny


def _wall_t(ox: float, oy: float, dx: np.ndarray, dy: np.ndarray):
    """Distance to the arena boundary along each ray, and the wall normal."""
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 0, (ARENA - ox) / dx, np.where(dx < 0, -ox / dx, np.inf))
        ty = np.where(dy > 0, (ARENA - oy) / dy, np.where(dy < 0, -oy / dy, np.inf))
    use_x = tx < ty
    t = np.where(use_x, tx, ty)
    nx = np.where(use_x, -np.sign(dx), 0.0)
    ny = np.where(use_x, 0.0, -np.sign(dy))
    return t, nx, ny


def render(
    agent: tuple[float, float, float] | Sequence[float],
    positions: Sequence[Sequence[float]] | np.ndarray,
    pillars: Sequence[tuple[float, float, float]] | Sequence[Sequence[float]],
    *,
    width: int = 224,
    height: int = 224,
    f: float | None = None,
    return_ids: bool = False,
    appearance: Appearance = DEFAULT,
    texture: bool = True,
):
    """RGB float image [H, W, 3] in [0, 1] and depth [H, W] (z along the optical axis; inf for sky).

    纹理默认开启 (texture=True)。
    若 return_ids=True，同时返回编号图 [H, W]（-2 天空，-1 地面，0 墙，1..P 柱子，100+i 圆盘 i）。
    """
    x0, y0, heading = float(agent[0]), float(agent[1]), float(agent[2])
    if f is None:
        f = (width / 2.0) / math.tan(FOV / 2.0)

    sky = np.asarray(appearance.sky, dtype=np.float64)
    floor = np.asarray(appearance.floor, dtype=np.float64)
    wall = np.asarray(appearance.wall, dtype=np.float64)
    pillar = np.asarray(appearance.pillar, dtype=np.float64)
    disk = np.asarray(appearance.disk, dtype=np.float64)
    light_dir = np.asarray(appearance.light_dir, dtype=np.float64)

    cols = np.arange(width) + 0.5 - width / 2.0
    ang = heading - np.arctan(cols / f)                     # left of the image is counter-clockwise
    dx, dy = np.cos(ang), np.sin(ang)
    cos_off = np.cos(ang - heading)
    rows = np.arange(height)[:, None] + 0.5 - height / 2.0  # [H, 1], positive downward

    objects = []
    objects.append((*_wall_t(x0, y0, dx, dy), WALL_H, wall, 0))
    for k, (cx, cy, r) in enumerate(pillars):
        objects.append((*_circle_t(x0, y0, dx, dy, float(cx), float(cy), float(r)), PILLAR_H, pillar, 1 + k))
    for i, p in enumerate(positions):
        objects.append((*_circle_t(x0, y0, dx, dy, float(p[0]), float(p[1]), DISK_R), DISK_H, disk, 100 + i))

    # background: sky above the horizon, floor below with its own depth
    with np.errstate(divide="ignore"):
        floor_z = np.where(rows > 0, f * CAM_H / rows, np.inf)          # [H, 1]
    depth = np.broadcast_to(np.where(rows > 0, floor_z, np.inf), (height, width)).copy()
    shade_floor = np.clip(1.0 / (1.0 + appearance.floor_shade_coeff * np.where(np.isfinite(floor_z), floor_z, 0.0)), 0.3, 1.0)
    img = np.where((rows > 0)[..., None], floor * shade_floor[..., None], sky)
    img = np.broadcast_to(img, (height, width, 3)).copy()

    if texture:
        tf = np.where(np.isfinite(floor_z), floor_z, 0.0) / cos_off[None, :]   # ray length to the floor point
        fx, fy = x0 + tf * dx[None, :], y0 + tf * dy[None, :]
        checker = (np.floor(fx / appearance.checker_size) + np.floor(fy / appearance.checker_size)) % 2
        img = img * np.where((rows > 0), 0.82 + 0.18 * checker, 1.0)[..., None]
    ids = np.broadcast_to(np.where(rows > 0, -1, -2), (height, width)).astype(np.int32)

    lx, ly = light_dir / np.linalg.norm(light_dir)
    for t, nx, ny, h, colour, oid in objects:
        z = t * cos_off                                     # [W]
        ok = np.isfinite(z) & (z > 1e-3)
        zs = np.where(ok, z, 1.0)
        top = -f * (h - CAM_H) / zs                         # row offsets (positive downward)
        bottom = f * CAM_H / zs
        inside = ok[None, :] & (rows >= top[None, :]) & (rows <= bottom[None, :])
        zz = np.where(inside, zs[None, :], np.inf)
        nearer = zz < depth
        with np.errstate(invalid="ignore"):                 # misses have NaN normals; they are masked anyway
            ndotl = np.where(ok, nx * lx + ny * ly, 0.0)
        lambert = np.clip(0.35 + 0.65 * np.maximum(ndotl, 0.0), 0.0, 1.0)
        fog = np.clip(1.0 / (1.0 + appearance.fog_coeff * zs), 0.35, 1.0)
        mod = 1.0
        if texture and oid < 100:                           # walls and pillars: vertical stripes
            with np.errstate(invalid="ignore"):
                if oid == 0:                                # wall: coordinate along the wall
                    u = np.where(np.abs(nx) > 0.5, y0 + zs / cos_off * dy, x0 + zs / cos_off * dx)
                    mod = np.where(ok, 0.85 + 0.15 * (np.floor(u / appearance.stripe_width) % 2), 1.0)
                else:                                       # pillar: 8 angular segments
                    a = np.arctan2(np.where(ok, ny, 0.0), np.where(ok, nx, 1.0))
                    mod = 0.85 + 0.15 * (np.floor((a + np.pi) / (np.pi / 4)) % 2)
        col = colour[None, :] * (lambert * fog * mod)[:, None]    # [W, 3]
        img = np.where(nearer[..., None], col[None, :, :], img)
        depth = np.where(nearer, zz, depth)
        ids = np.where(nearer, oid, ids)

    if return_ids:
        return np.clip(img, 0.0, 1.0), depth, ids
    return np.clip(img, 0.0, 1.0), depth


def to_uint8(img: np.ndarray) -> np.ndarray:
    """Float image [0, 1] to uint8 [0, 255]."""
    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def da2_center_crop(arr: np.ndarray) -> np.ndarray:
    """Crop the center 392 columns of a 518-wide image/tensor."""
    # Find the axis with length 518
    for ax in range(arr.ndim - 1, -1, -1):
        if arr.shape[ax] == DA2_W:
            # Crop 392 columns starting from (518 - 392) // 2 = 63 to 455
            slc = [slice(None)] * arr.ndim
            slc[ax] = slice(63, 455)
            return arr[tuple(slc)]
    raise ValueError(f"No dimension of size {DA2_W} found in array with shape {arr.shape}")
