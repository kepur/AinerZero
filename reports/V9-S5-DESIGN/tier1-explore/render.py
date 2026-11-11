"""S5 摸底用的第一人称光线投射渲染器（NumPy；未登记，只用于摸底）。

把 S4 圆盘世界（`src/ainerzero/v9/experiments/s4/world.py`）从智能体位姿渲染成 RGB 画面，并给出逐像素真值深度。
画面完全由本仓库代码生成，许可干净。

场景：
- 10×10 场地，四面墙高 1.2；
- 3 根柱子，高 2.0；
- 若干同外观圆盘，半径 0.3、高 0.6，颜色一样，没有编号；
- 地面、天空。

相机：
- 高 0.5，水平视场 90°，针孔模型（每列按真实方向投射，按光轴距离做透视）；
- 按 z 缓冲合成。

深度：沿光轴的距离 z，天空为 inf。只用作标签，不进学生输入。
"""
from __future__ import annotations

import math

import numpy as np

ARENA = 10.0
WALL_H, PILLAR_H, DISK_H = 1.2, 2.0, 0.6
DISK_R = 0.3
CAM_H = 0.5
FOV = math.radians(90)
LIGHT = np.array([0.6, 0.8])            # direction the light comes from, in the plane
SKY = np.array([0.62, 0.78, 0.95])
FLOOR = np.array([0.45, 0.50, 0.42])
WALL = np.array([0.70, 0.70, 0.72])
PILLAR = np.array([0.55, 0.38, 0.25])
DISK = np.array([0.20, 0.35, 0.85])


def _circle_t(ox, oy, dx, dy, cx, cy, r):
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


def _wall_t(ox, oy, dx, dy):
    """Distance to the arena boundary along each ray, and the wall normal."""
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 0, (ARENA - ox) / dx, np.where(dx < 0, -ox / dx, np.inf))
        ty = np.where(dy > 0, (ARENA - oy) / dy, np.where(dy < 0, -oy / dy, np.inf))
    use_x = tx < ty
    t = np.where(use_x, tx, ty)
    nx = np.where(use_x, -np.sign(dx), 0.0)
    ny = np.where(use_x, 0.0, -np.sign(dy))
    return t, nx, ny


def render(agent, positions, pillars, *, width=224, height=224, return_ids=False, texture=False):
    """RGB float image [H, W, 3] in [0, 1] and depth [H, W] (z along the optical axis; inf for sky).

    With texture, the floor gets a world-anchored 1 m checker and walls / pillars get vertical stripes,
    so background patches change as the camera moves (otherwise flat shading makes RLT look too easy).
    Disks stay plain and identical.
    With return_ids, also an object-index map [H, W] for labels only (never student input):
    -2 sky, -1 floor, 0 wall, 1..P pillars, 100+i disk i.
    """
    x0, y0, heading = agent
    f = (width / 2) / math.tan(FOV / 2)
    cols = np.arange(width) + 0.5 - width / 2
    ang = heading - np.arctan(cols / f)                     # left of the image is counter-clockwise
    dx, dy = np.cos(ang), np.sin(ang)
    cos_off = np.cos(ang - heading)
    rows = np.arange(height)[:, None] + 0.5 - height / 2    # [H, 1], positive downward

    objects = []                                            # (t per column, nx, ny, height, colour, id)
    objects.append((*_wall_t(x0, y0, dx, dy), WALL_H, WALL, 0))
    for k, (cx, cy, r) in enumerate(pillars):
        objects.append((*_circle_t(x0, y0, dx, dy, cx, cy, r), PILLAR_H, PILLAR, 1 + k))
    for i, (px, py) in enumerate(positions):
        objects.append((*_circle_t(x0, y0, dx, dy, px, py, DISK_R), DISK_H, DISK, 100 + i))

    # background: sky above the horizon, floor below with its own depth
    with np.errstate(divide="ignore"):
        floor_z = np.where(rows > 0, f * CAM_H / rows, np.inf)          # [H, 1]
    depth = np.broadcast_to(np.where(rows > 0, floor_z, np.inf), (height, width)).copy()
    shade_floor = np.clip(1.0 / (1.0 + 0.08 * np.where(np.isfinite(floor_z), floor_z, 0.0)), 0.3, 1.0)
    img = np.where((rows > 0)[..., None], FLOOR * shade_floor[..., None], SKY)
    img = np.broadcast_to(img, (height, width, 3)).copy()
    if texture:
        tf = np.where(np.isfinite(floor_z), floor_z, 0.0) / cos_off[None, :]   # ray length to the floor point
        fx, fy = x0 + tf * dx[None, :], y0 + tf * dy[None, :]
        checker = (np.floor(fx) + np.floor(fy)) % 2
        img = img * np.where((rows > 0), 0.82 + 0.18 * checker, 1.0)[..., None]
    ids = np.broadcast_to(np.where(rows > 0, -1, -2), (height, width)).astype(np.int32)

    lx, ly = LIGHT / np.linalg.norm(LIGHT)
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
        fog = np.clip(1.0 / (1.0 + 0.06 * zs), 0.35, 1.0)
        mod = 1.0
        if texture and oid < 100:                           # walls and pillars: vertical stripes
            with np.errstate(invalid="ignore"):
                if oid == 0:                                # wall: coordinate along the wall, 0.5 m stripes
                    u = np.where(np.abs(nx) > 0.5, y0 + zs / cos_off * dy, x0 + zs / cos_off * dx)
                    mod = np.where(ok, 0.85 + 0.15 * (np.floor(u * 2) % 2), 1.0)
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


def to_uint8(img):
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
