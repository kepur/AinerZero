"""GridMini 世界的纯 CPU 测试（不导入 MLX）。"""
import random

import numpy as np

from ainerzero.v9.mini import world as W


def test_layout_connected_and_deterministic():
    for seed in range(20):
        a, b = W.make_layout(seed), W.make_layout(seed)
        assert np.array_equal(a.grid, b.grid)
        free = set(a.free_cells())
        start = next(iter(free))
        reach = {(x, y) for x, y, _ in W.pose_bfs(a, (*start, 0))}
        assert reach == free


def test_rooms_have_one_color_each_and_colors_shuffled():
    firsts = set()
    for seed in range(10):
        L = W.make_layout(seed)
        rs = L.cfg.room_size
        firsts.add(int(L.grid[1, 1]))
        for ry in range(L.cfg.rooms):
            for rx in range(L.cfg.rooms):
                x0, y0 = rx * (rs + 1) + 1, ry * (rs + 1) + 1
                assert len(np.unique(L.grid[y0:y0 + rs, x0:x0 + rs])) == 1
    assert len(firsts) > 1


def test_ego_view_rotates_with_heading():
    L = W.make_layout(3)
    x, y = 3, 3
    north = W.ego_view(L, (x, y, 0))
    for h in range(4):
        v = W.ego_view(L, (x, y, h))
        # 视野正前方一格就是 DELTA[h] 方向的格子
        dx, dy = W.DELTA[h]
        r = L.cfg.view_radius
        assert v[r - 1, r] == L.grid[y + dy, x + dx]
        assert v[r, r] == L.grid[y, x]
    assert north.shape == (L.cfg.view, L.cfg.view)


def test_walls_occlude():
    L = W.make_layout(0)
    # 房间边墙以外的格子（墙后）在视野里是 OOB
    v = W.ego_view(L, (1, 3, 3))   # 站在最左列朝西：前方是边界墙，墙外越界
    r = L.cfg.view_radius
    assert v[r - 1, r] == W.WALL
    assert v[0, r] == W.OOB


def test_analytic_step_matches_true_step_without_unknown_laws():
    L = W.make_layout(7)
    known = L.grid.copy()
    rng = random.Random(0)
    p = W.random_pose(L, rng)
    for _ in range(500):
        a = rng.randrange(W.N_ACTIONS)
        assert W.analytic_step(known, p, a) == W.step(L, p, a)
        p = W.step(L, p, a)


def test_reverse_bfs_agrees_with_forward_bfs():
    L = W.make_layout(11)
    rng = random.Random(1)
    goal = W.random_pose(L, rng)
    rev = W.reverse_bfs_to_cell(L, (goal[0], goal[1]))
    for _ in range(20):
        s = W.random_pose(L, rng)
        assert rev[s] == W.dist_to_cell(L, s, (goal[0], goal[1]))


def test_ice_slides_and_portal_teleports():
    cfg = W.Config(ice=True, portals=1)
    L = W.make_layout(5, cfg)
    src, dst = next(iter(L.portal_to.items()))
    for h in range(4):
        dx, dy = W.DELTA[h]
        prev = (src[0] - dx, src[1] - dy)
        if L.passable(*prev) and L.grid[prev[1], prev[0]] != W.ICE:
            assert W.step(L, (prev[0], prev[1], h), W.FORWARD)[:2] == dst
            break
    ice = [c for c in L.free_cells() if L.grid[c[1], c[0]] == W.ICE]
    assert ice
