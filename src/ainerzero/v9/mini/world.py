"""GridMini：多房间网格世界（纯 numpy / 标准库，不导入 MLX）。

和 S2 的 GridLab 同类：有朝向、自我中心局部视野、视线遮挡、多房间与门。
不同处：
- 每个房间有一种地板颜色，颜色到房间的分配每张图随机打乱。颜色只在一张图内区分房间，
  不泄露全局坐标；
- 动作只有三个：前进、左转、右转；
- 可选「未知规律」（v1 再开）：冰面（前进后一直滑到被挡住）与单向传送门。

学生观察：朝向 one-hot（指南针）＋自我中心视野。不给坐标。
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
import random
from typing import Iterable

import numpy as np

# 格子类型
WALL = 0
OOB = 1          # 视野里越界或被遮挡（学生看不到的格）
ICE = 2          # v1 的未知规律之一，v0 不放
PORTAL = 3       # v1：单向传送门入口
FLOOR0 = 4       # 地板颜色 FLOOR0 .. FLOOR0+N_COLORS-1
N_COLORS = 9
N_TYPES = FLOOR0 + N_COLORS

FORWARD, LEFT, RIGHT = 0, 1, 2
N_ACTIONS = 3
# 朝向：0 北 1 东 2 南 3 西；y 向下增大
DELTA = ((0, -1), (1, 0), (0, 1), (-1, 0))


@dataclass
class Config:
    rooms: int = 3            # rooms × rooms 个房间
    room_size: int = 5        # 房间内部边长
    view_radius: int = 2      # 视野 (2r+1)×(2r+1)
    extra_door_prob: float = 0.35  # 生成树之外的门，越小路越绕
    ice: bool = False
    portals: int = 0

    @property
    def size(self) -> int:
        return self.rooms * (self.room_size + 1) + 1

    @property
    def view(self) -> int:
        return 2 * self.view_radius + 1


@dataclass
class Layout:
    seed: int
    cfg: Config
    grid: np.ndarray                     # (size, size) int8，格子类型
    portal_to: dict = field(default_factory=dict)   # (x, y) -> (x, y)

    def passable(self, x: int, y: int) -> bool:
        s = self.cfg.size
        return 0 <= x < s and 0 <= y < s and self.grid[y, x] != WALL

    def free_cells(self) -> list[tuple[int, int]]:
        ys, xs = np.nonzero(self.grid != WALL)
        return list(zip(xs.tolist(), ys.tolist()))


def make_layout(seed: int, cfg: Config | None = None) -> Layout:
    cfg = cfg or Config()
    rng = random.Random(seed)
    n, rs, s = cfg.rooms, cfg.room_size, cfg.size
    grid = np.full((s, s), WALL, dtype=np.int8)
    colors = list(range(N_COLORS))
    rng.shuffle(colors)
    for ry in range(n):
        for rx in range(n):
            x0, y0 = rx * (rs + 1) + 1, ry * (rs + 1) + 1
            grid[y0:y0 + rs, x0:x0 + rs] = FLOOR0 + colors[(ry * n + rx) % N_COLORS]
    # 房间之间的门：先随机生成树保证连通，再按概率加门
    edges = []
    for ry in range(n):
        for rx in range(n):
            if rx + 1 < n:
                edges.append(((rx, ry), (rx + 1, ry)))
            if ry + 1 < n:
                edges.append(((rx, ry), (rx, ry + 1)))
    rng.shuffle(edges)
    parent = {(rx, ry): (rx, ry) for ry in range(n) for rx in range(n)}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb or rng.random() < cfg.extra_door_prob:
            parent[ra] = rb
            _open_door(grid, a, b, cfg, rng)
    layout = Layout(seed=seed, cfg=cfg, grid=grid)
    if cfg.ice:
        _place_ice(layout, rng)
    if cfg.portals:
        _place_portals(layout, rng)
    return layout


def _open_door(grid, a, b, cfg: Config, rng: random.Random) -> None:
    (ax, ay), (bx, by) = a, b
    rs = cfg.room_size
    off = rng.randrange(rs)
    if ay == by:   # 左右相邻，门在竖墙上
        wx = (ax + 1) * (rs + 1)
        wy = ay * (rs + 1) + 1 + off
        grid[wy, wx] = grid[wy, wx - 1]
    else:          # 上下相邻，门在横墙上
        wy = (ay + 1) * (rs + 1)
        wx = ax * (rs + 1) + 1 + off
        grid[wy, wx] = grid[wy - 1, wx]


def _place_ice(layout: Layout, rng: random.Random) -> None:
    free = [c for c in layout.free_cells()]
    for x, y in rng.sample(free, k=max(1, len(free) // 12)):
        layout.grid[y, x] = ICE


def _place_portals(layout: Layout, rng: random.Random) -> None:
    free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
    picks = rng.sample(free, k=2 * layout.cfg.portals)
    for i in range(layout.cfg.portals):
        src, dst = picks[2 * i], picks[2 * i + 1]
        layout.grid[src[1], src[0]] = PORTAL
        layout.portal_to[src] = dst


# ---------------------------------------------------------------- 动力学

Pose = tuple[int, int, int]   # (x, y, heading)


def step(layout: Layout, pose: Pose, action: int) -> Pose:
    x, y, h = pose
    if action == LEFT:
        return (x, y, (h - 1) % 4)
    if action == RIGHT:
        return (x, y, (h + 1) % 4)
    dx, dy = DELTA[h]
    if not layout.passable(x + dx, y + dy):
        return pose
    x, y = x + dx, y + dy
    # 未知规律：冰面一直滑；传送门入口立刻送到出口
    for _ in range(layout.cfg.size):
        if layout.grid[y, x] == PORTAL and (x, y) in layout.portal_to:
            x, y = layout.portal_to[(x, y)]
            break
        if layout.grid[y, x] == ICE and layout.passable(x + dx, y + dy):
            x, y = x + dx, y + dy
            continue
        break
    return (x, y, h)


def analytic_step(known: "np.ndarray", pose: Pose, action: int) -> Pose:
    """解析先验：只知道「前方不是墙就前进一格」，不知道冰面和传送门。

    known：智能体自己的地图，WALL 处不可走，其他（含未知）当作可走。
    """
    x, y, h = pose
    if action == LEFT:
        return (x, y, (h - 1) % 4)
    if action == RIGHT:
        return (x, y, (h + 1) % 4)
    dx, dy = DELTA[h]
    nx, ny = x + dx, y + dy
    s = known.shape[0]
    if not (0 <= nx < s and 0 <= ny < s) or known[ny, nx] == WALL:
        return pose
    return (nx, ny, h)


# ---------------------------------------------------------------- 观察

def _visible(layout: Layout, ax: int, ay: int, bx: int, by: int) -> bool:
    """Bresenham 视线：中间格有墙就看不到终点（终点本身是墙可以看到）。"""
    dx, dy = abs(bx - ax), abs(by - ay)
    sx, sy = (1 if bx > ax else -1), (1 if by > ay else -1)
    err = dx - dy
    x, y = ax, ay
    while (x, y) != (bx, by):
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
        if (x, y) != (bx, by) and layout.grid[y, x] == WALL:
            return False
    return True


def ego_offsets(r: int, heading: int) -> list[tuple[int, int, int, int]]:
    """视野格 (row, col) 到世界偏移 (dx, dy)。row 0 在前方最远处，中心是智能体。"""
    out = []
    for row in range(2 * r + 1):
        fwd = r - row
        for col in range(2 * r + 1):
            lat = col - r
            if heading == 0:
                dx, dy = lat, -fwd
            elif heading == 1:
                dx, dy = fwd, lat
            elif heading == 2:
                dx, dy = -lat, fwd
            else:
                dx, dy = -fwd, -lat
            out.append((row, col, dx, dy))
    return out


_OFFSETS = {}


def ego_view(layout: Layout, pose: Pose) -> np.ndarray:
    """(V, V) int8，格子类型；越界与被遮挡的格是 OOB。"""
    r = layout.cfg.view_radius
    key = (r, pose[2])
    if key not in _OFFSETS:
        _OFFSETS[key] = ego_offsets(r, pose[2])
    x, y, _ = pose
    s = layout.cfg.size
    v = np.full((2 * r + 1, 2 * r + 1), OOB, dtype=np.int8)
    for row, col, dx, dy in _OFFSETS[key]:
        wx, wy = x + dx, y + dy
        if 0 <= wx < s and 0 <= wy < s and _visible(layout, x, y, wx, wy):
            v[row, col] = layout.grid[wy, wx]
    return v


def encode_obs(view: np.ndarray, heading: int) -> np.ndarray:
    """学生输入：视野 one-hot 展平 ＋ 朝向 one-hot。float32。"""
    oh = np.zeros((view.size, N_TYPES), dtype=np.float32)
    oh[np.arange(view.size), view.reshape(-1)] = 1.0
    hd = np.zeros(4, dtype=np.float32)
    hd[heading] = 1.0
    return np.concatenate([oh.reshape(-1), hd])


def obs_dim(cfg: Config) -> int:
    return cfg.view * cfg.view * N_TYPES + 4


# ---------------------------------------------------------------- 真值距离（只作诊断和上界）

def pose_bfs(layout: Layout, start: Pose) -> dict[Pose, int]:
    """从 start 出发、按真实动力学的最少动作数。"""
    dist = {start: 0}
    q = collections.deque([start])
    while q:
        p = q.popleft()
        for a in range(N_ACTIONS):
            n = step(layout, p, a)
            if n not in dist:
                dist[n] = dist[p] + 1
                q.append(n)
    return dist


def dist_to_cell(layout: Layout, start: Pose, cell: tuple[int, int]) -> int | None:
    """到某个格子（朝向不限）的最少动作数。"""
    d = pose_bfs(layout, start)
    best = [v for (x, y, _), v in d.items() if (x, y) == cell]
    return min(best) if best else None


def reverse_bfs_to_cell(layout: Layout, cell: tuple[int, int]) -> dict[Pose, int]:
    """每个位姿到目标格的最少动作数（反向图上 BFS）。"""
    poses = [(x, y, h) for (x, y) in layout.free_cells() for h in range(4)]
    rev = collections.defaultdict(list)
    for p in poses:
        for a in range(N_ACTIONS):
            rev[step(layout, p, a)].append(p)
    dist = {}
    q = collections.deque()
    for h in range(4):
        p = (cell[0], cell[1], h)
        dist[p] = 0
        q.append(p)
    while q:
        p = q.popleft()
        for prev in rev[p]:
            if prev not in dist:
                dist[prev] = dist[p] + 1
                q.append(prev)
    return dist


def random_pose(layout: Layout, rng: random.Random) -> Pose:
    cells = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
    x, y = rng.choice(cells)
    return (x, y, rng.randrange(4))


def walk(layout: Layout, start: Pose, n: int, rng: random.Random,
         p_forward: float = 0.7) -> tuple[list[Pose], list[int]]:
    """持续性随机游走：前进概率高一些，覆盖得快。返回 n+1 个位姿和 n 个动作。"""
    poses, acts = [start], []
    p = start
    for _ in range(n):
        a = FORWARD if rng.random() < p_forward else rng.choice((LEFT, RIGHT))
        p = step(layout, p, a)
        poses.append(p)
        acts.append(a)
    return poses, acts


def iter_views(layout: Layout, poses: Iterable[Pose]) -> np.ndarray:
    return np.stack([encode_obs(ego_view(layout, p), p[2]) for p in poses])
