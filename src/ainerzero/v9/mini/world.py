"""GridMini：多房间网格世界（纯 numpy / 标准库，不导入 MLX）。

和 S2 的 GridLab 同类：有朝向、自我中心局部视野、视线遮挡、多房间与门。
不同处：
- 每个房间有一种地板颜色，颜色到房间的分配每张图随机打乱。颜色只在一张图内区分房间，
  不泄露全局坐标；
- 动作只有三个：前进、左转、右转；
- 可选「未知规律」（v1 再开）：冰面（前进后一直滑到被挡住）与单向传送门；
  M6 的大图（h 世界）再加两条：跳板（踏上去再向前跳 2 格，可越过墙）与单向门（只能顺着门的方向进门）。

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
PAD = FLOOR0 + N_COLORS      # M6：跳板（未知规律）
GATE0 = PAD + 1              # M6：单向门 GATE0 + d，d 是允许进门的朝向（0 北 1 东 2 南 3 西）
N_TYPES = GATE0 + 4

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
    ice_rooms: int = 0        # 整间铺冰的房间数（未知规律：前进后一直滑到被挡住或离开冰面）
    portals: int = 0          # 单向传送门数（未知规律：踏上入口就到出口）
    pads: int = 0             # M6 跳板数（未知规律：踏上去再沿朝向跳 2 格，落点须是普通地板，可越过墙）
    gates: int = 0            # M6 单向门数（未知规律：门格只能顺着门的方向进入）

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

    def can_enter(self, x: int, y: int, h: int) -> bool:
        """朝 h 方向走进 (x, y)：不越界、不是墙；单向门只能顺着门的方向进。"""
        if not self.passable(x, y):
            return False
        v = self.grid[y, x]
        return not (GATE0 <= v < GATE0 + 4 and v - GATE0 != h)


def is_floor(v: int) -> bool:
    """普通地板（带房间颜色），不含冰、传送门、跳板、单向门。"""
    return FLOOR0 <= v < FLOOR0 + N_COLORS


_LAYOUTS: dict = {}


def make_layout(seed: int, cfg: Config | None = None) -> Layout:
    """同一个种子和配置只生成一次（一次运行里同一张图会被数据、残差、自监督标签、任务各取一遍）。

    缓存的网格设为只读，调用方误写会直接报错。
    """
    cfg = cfg or Config()
    key = (seed, tuple(sorted(cfg.__dict__.items())))
    lay = _LAYOUTS.get(key)
    if lay is None:
        lay = _make_layout(seed, cfg)
        lay.grid.flags.writeable = False
        _LAYOUTS[key] = lay
    return lay


def _make_layout(seed: int, cfg: Config) -> Layout:
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
    base = grid.copy()
    for _attempt in range(100):
        layout = Layout(seed=seed, cfg=cfg, grid=base.copy())
        if cfg.ice_rooms:
            _place_ice(layout, rng)
        if cfg.portals:
            _place_portals(layout, rng)
        if cfg.pads:        # m1/m2 不进这两个分支，随机数序列与 M4/M5 一致
            _place_pads(layout, rng)
        if cfg.gates:
            if not _strongly_connected(layout):   # 冰带、传送门、跳板本身已有陷阱：不必再放门，直接重来
                continue
            _place_gates(layout, rng)
        if not (cfg.ice_rooms or cfg.portals or cfg.pads or cfg.gates) or _strongly_connected(layout):
            return layout
    raise RuntimeError(f"seed {seed}: 100 次都放不出没有陷阱的未知规律布局")


def _strongly_connected(layout: "Layout") -> bool:
    """所有地板格两两可达：从起点格能走到每个地板格，且从任一可达位姿都能回到起点格。

    只查第二条不够（A27 F-02）：传送门入口堵在某间房唯一的门前时，那间房从起点走不进去，
    第二条只看起点走得到的位姿，会平凡成立；起点所在区域本身出不去时也一样。

    M6 起改成先建一次位姿转移表（只有前进要模拟，转向是纯旋转），正反两次 BFS 都在表上做；
    判定与原来的 pose_bfs + reverse_bfs_to_cell 写法相同（_strongly_connected_ref 留作对照测试）。
    """
    free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
    cells = layout.free_cells()
    idx = {(x, y, h): 4 * i + h for i, (x, y) in enumerate(cells) for h in range(4)}
    n = len(idx)
    nxt = [None] * n
    for (x, y, h), i in idx.items():
        nxt[i] = (idx[step(layout, (x, y, h), FORWARD)], 4 * (i // 4) + (h - 1) % 4, 4 * (i // 4) + (h + 1) % 4)
    s0 = idx[(free[0][0], free[0][1], 0)]
    seen = bytearray(n)
    seen[s0] = 1
    stack = [s0]
    while stack:
        for j in nxt[stack.pop()]:
            if not seen[j]:
                seen[j] = 1
                stack.append(j)
    reached_cells = {cells[i // 4] for i in range(n) if seen[i]}
    if not all(c in reached_cells for c in free):
        return False
    rev = [[] for _ in range(n)]
    for i, js in enumerate(nxt):
        for j in js:
            rev[j].append(i)
    back = bytearray(n)
    stack = [idx[(free[0][0], free[0][1], h)] for h in range(4)]
    for i in stack:
        back[i] = 1
    while stack:
        for j in rev[stack.pop()]:
            if not back[j]:
                back[j] = 1
                stack.append(j)
    return all(back[i] for i in range(n) if seen[i])


def _strongly_connected_ref(layout: "Layout") -> bool:
    """M6 之前的写法，只留给测试对照。"""
    free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
    start = (free[0][0], free[0][1], 0)
    reach = pose_bfs(layout, start)
    cells = {(p[0], p[1]) for p in reach}
    if not all(c in cells for c in free):
        return False
    back = reverse_bfs_to_cell(layout, free[0])
    return all(p in back for p in reach)


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
    cfg = layout.cfg
    rs = cfg.room_size
    rooms = [(rx, ry) for ry in range(cfg.rooms) for rx in range(cfg.rooms)]
    # 每间选中的房间里放一条 2 格宽、贯穿房间的冰带。踩上去会滑过整条冰带；整间铺冰会把智能体困死，不用。
    for rx, ry in rng.sample(rooms, k=cfg.ice_rooms):
        x0, y0 = rx * (rs + 1) + 1, ry * (rs + 1) + 1
        off = rng.randrange(1, rs - 2)
        if rng.random() < 0.5:
            layout.grid[y0 + off:y0 + off + 2, x0:x0 + rs] = ICE
        else:
            layout.grid[y0:y0 + rs, x0 + off:x0 + off + 2] = ICE


def _place_portals(layout: Layout, rng: random.Random) -> None:
    """入口和出口放在房间内部的地板格上，两者至少隔 8 格（曼哈顿），做成捷径。"""
    rs = layout.cfg.room_size
    free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0
            and c[0] % (rs + 1) != 0 and c[1] % (rs + 1) != 0]
    used: set = set()
    for _ in range(layout.cfg.portals):
        for _try in range(200):
            src, dst = rng.sample(free, k=2)
            if src in used or dst in used or abs(src[0] - dst[0]) + abs(src[1] - dst[1]) < 8:
                continue
            break
        used.update((src, dst))
        layout.grid[src[1], src[0]] = PORTAL
        layout.portal_to[src] = dst


def _room_interior(layout: Layout, c) -> bool:
    rs = layout.cfg.room_size
    return c[0] % (rs + 1) != 0 and c[1] % (rs + 1) != 0


def _place_pads(layout: Layout, rng: random.Random) -> None:
    """跳板放在房间内部的普通地板上，不挨着传送门的出口（出口落在跳板上会接着跳，规律叠在一起不好学）。"""
    exits = set(layout.portal_to.values())
    free = [c for c in layout.free_cells() if is_floor(layout.grid[c[1], c[0]]) and _room_interior(layout, c)
            and c not in exits]
    for c in rng.sample(free, k=layout.cfg.pads):
        layout.grid[c[1], c[0]] = PAD


def _rooms_strongly_connected(n: int, edges: list) -> bool:
    """房间图：edges 是 (a, b, 方向)，方向 0 表示双向，1 只能 a→b，-1 只能 b→a。"""
    fwd = {r: [] for r in range(n * n)}
    bwd = {r: [] for r in range(n * n)}
    for a, b, d in edges:
        if d >= 0:
            fwd[a].append(b)
            bwd[b].append(a)
        if d <= 0:
            fwd[b].append(a)
            bwd[a].append(b)
    for g in (fwd, bwd):
        seen, stack = {0}, [0]
        while stack:
            for m in g[stack.pop()]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if len(seen) != n * n:
            return False
    return True


def _place_gates(layout: Layout, rng: random.Random) -> None:
    """单向门放在房间之间的门洞上（墙线上的非墙格），方向沿门洞的轴随机取一边。

    逐个放：先查房间图（快），再查整图位姿强连通（慢，但把冰带、传送门、跳板都算进去），
    两样都过才留下，否则换另一个方向，再不行就跳过这个门洞。只查房间图不够：门洞正对冰带
    尽头或传送门入口时，这个门洞只有一边进得去，房间图看不出来（种子 7_100_109 因此
    100 次都放不出）。门洞不够时少放，测试会查个数。
    """
    cfg = layout.cfg
    rs, n = cfg.room_size, cfg.rooms
    doors = []   # (x, y, 可选方向, 房间 a, 房间 b)，a 在西或北
    for x, y in layout.free_cells():
        on_v, on_h = x % (rs + 1) == 0, y % (rs + 1) == 0
        if on_v != on_h and is_floor(layout.grid[y, x]):
            if on_v:   # 竖墙上的门洞只能东西向穿过
                ry, rx = y // (rs + 1), x // (rs + 1)
                doors.append((x, y, (1, 3), ry * n + rx - 1, ry * n + rx))
            else:
                ry, rx = y // (rs + 1), x // (rs + 1)
                doors.append((x, y, (0, 2), (ry - 1) * n + rx, ry * n + rx))
    state = {(x, y): 0 for x, y, *_ in doors}

    def ok() -> bool:
        return _rooms_strongly_connected(n, [(a, b, state[(x, y)]) for x, y, _, a, b in doors])

    placed = 0
    for x, y, dirs, a, b in rng.sample(doors, k=len(doors)):
        if placed == cfg.gates:
            break
        for d in rng.sample(dirs, k=2):
            state[(x, y)] = 1 if d in (1, 2) else -1     # 朝东或朝南进门：只能从 a（西/北）到 b
            if ok():
                old = layout.grid[y, x]
                layout.grid[y, x] = GATE0 + d
                if _strongly_connected(layout):
                    placed += 1
                    break
                layout.grid[y, x] = old
            state[(x, y)] = 0


# ---------------------------------------------------------------- 动力学

Pose = tuple[int, int, int]   # (x, y, heading)


def step(layout: Layout, pose: Pose, action: int) -> Pose:
    x, y, h = pose
    if action == LEFT:
        return (x, y, (h - 1) % 4)
    if action == RIGHT:
        return (x, y, (h + 1) % 4)
    dx, dy = DELTA[h]
    if not layout.can_enter(x + dx, y + dy, h):
        return pose
    x, y = x + dx, y + dy
    # 未知规律：冰面一直滑；传送门入口立刻送到出口；跳板再向前跳 2 格（落点是普通地板才跳）；
    # 单向门只能顺着门的方向进（滑行也一样）。m1/m2 里没有跳板和单向门，can_enter 与 passable 相同。
    for _ in range(layout.cfg.size):
        v = layout.grid[y, x]
        if v == PORTAL and (x, y) in layout.portal_to:
            x, y = layout.portal_to[(x, y)]
            break
        if v == ICE and layout.can_enter(x + dx, y + dy, h):
            x, y = x + dx, y + dy
            continue
        if v == PAD and layout.passable(x + 2 * dx, y + 2 * dy) and is_floor(layout.grid[y + 2 * dy, x + 2 * dx]):
            x, y = x + 2 * dx, y + 2 * dy
            break
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
    cells = [c for c in layout.free_cells() if is_floor(layout.grid[c[1], c[0]])]   # m 世界里与旧写法 >= FLOOR0 相同
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


# ---------------------------------------------------------------- 残差模型的输入：前方射线

RAY_LEN = 6
# 0 未知 1 墙 2 冰 3 传送门 4 地板（颜色折叠掉：规律与颜色无关，这是规范化的一步）
# M6 加：5 跳板 6 顺向的单向门 7 逆向或横向的单向门（门的方向按射线朝向折成相对方向，与视野旋转同属已知几何）
RAY_CLASSES = 8


def fold_type(v: int, heading: int = 0) -> int:
    if v < 0:
        return 0
    if v == WALL or v == OOB:
        return 1
    if v == ICE:
        return 2
    if v == PORTAL:
        return 3
    if v == PAD:
        return 5
    if GATE0 <= v < GATE0 + 4:
        return 6 if v - GATE0 == heading else 7
    return 4


def ray(cells: np.ndarray, pose: Pose, length: int = RAY_LEN) -> np.ndarray:
    """cells：真值网格或智能体地图（-1 表示未知）。返回 (length,) 折叠后的类型，越界算墙。"""
    x, y, h = pose
    dx, dy = DELTA[h]
    n = cells.shape[0]
    out = np.zeros(length, dtype=np.int64)
    for k in range(1, length + 1):
        cx, cy = x + k * dx, y + k * dy
        out[k - 1] = fold_type(int(cells[cy, cx]), h) if 0 <= cx < n and 0 <= cy < n else 1
    return out


def forward_outcome(layout: Layout, pose: Pose) -> int:
    """前进一步的真实结果：沿朝向移动的格数 0..RAY_LEN；不在射线上（传送）记 RAY_LEN+1。"""
    x, y, h = pose
    nx, ny, _ = step(layout, pose, FORWARD)
    dx, dy = DELTA[h]
    for k in range(0, RAY_LEN + 1):
        if (x + k * dx, y + k * dy) == (nx, ny):
            return k
    return RAY_LEN + 1
