"""M6：h 世界的新规律（跳板、单向门）与 m 世界不变性。"""
import hashlib
import random

import numpy as np

from ainerzero.v9.mini import world as W
from ainerzero.v9.mini.mapagent import Frame
from ainerzero.v9.mini.residual import ForwardModel
from ainerzero.v9.mini.run import WORLDS


def _grid_hash(layout):
    return hashlib.sha256(layout.grid.tobytes() + repr(sorted(layout.portal_to.items())).encode()).hexdigest()[:16]


def test_m_worlds_unchanged_by_m6_code():
    """m1/m2 的布局与 M4/M5 代码（M6 改动前的 world.py）逐格相同；哈希由旧代码算出后写死。"""
    pinned = {("m1", 7100000): "2cd62a59d9c908c7", ("m1", 8100000): "fdd8f9be022f0441",
              ("m2", 7900003): "ad9fe131b6e5ede0", ("m2", 8104017): "26554435c76fcc1b"}
    for (name, seed), h in pinned.items():
        assert _grid_hash(W.make_layout(seed, W.Config(**WORLDS[name]))) == h


def _empty(size_rooms=1):
    cfg = W.Config(rooms=size_rooms)
    grid = np.full((cfg.size, cfg.size), W.WALL, dtype=np.int8)
    grid[1:-1, 1:-1] = W.FLOOR0
    return W.Layout(seed=0, cfg=cfg, grid=grid)


def test_pad_jumps_two_more_cells_and_over_walls():
    lay = _empty()                       # 7×7：内部 5×5
    lay.grid[3, 2] = W.PAD
    assert W.step(lay, (1, 3, 1), W.FORWARD) == (4, 3, 1)          # 踩上 (2,3) 再跳到 (4,3)：位移 3
    assert W.forward_outcome(lay, (1, 3, 1)) == 3
    lay.grid[1:6, 3] = W.WALL                                     # 中间一堵墙：照样跳过去
    assert W.step(lay, (1, 3, 1), W.FORWARD) == (4, 3, 1)
    lay.grid[3, 4] = W.WALL                                       # 落点是墙：停在跳板上
    assert W.step(lay, (1, 3, 1), W.FORWARD) == (2, 3, 1)
    lay.grid[3, 4] = W.ICE                                        # 落点不是普通地板：也不跳
    assert W.step(lay, (1, 3, 1), W.FORWARD) == (2, 3, 1)
    assert W.step(lay, (2, 3, 1), W.FORWARD)[:2] == (2, 3)        # 站在跳板上往前：前面是墙，不动


def test_gate_enters_only_along_its_direction():
    lay = _empty()
    lay.grid[3, 3] = W.GATE0 + 1                                  # 只能朝东进
    assert W.step(lay, (2, 3, 1), W.FORWARD) == (3, 3, 1)         # 朝东：进得去
    assert W.step(lay, (4, 3, 3), W.FORWARD) == (4, 3, 3)         # 朝西：挡住
    assert W.step(lay, (3, 2, 2), W.FORWARD) == (3, 2, 2)         # 朝南（横向）：挡住
    assert W.forward_outcome(lay, (4, 3, 3)) == 0
    lay.grid[3, 4:6] = W.ICE                                      # 冰面上朝西滑，前面是逆向的门：停在冰的尽头
    assert W.step(lay, (6, 3, 3), W.FORWARD) == (4, 3, 3)


def test_fold_type_gate_relative_to_heading():
    assert W.fold_type(W.GATE0 + 2, 2) == 6 and W.fold_type(W.GATE0 + 2, 0) == 7 and W.fold_type(W.GATE0 + 2, 1) == 7
    assert W.fold_type(W.PAD) == 5 and W.fold_type(W.FLOOR0 + 3) == 4 and W.fold_type(-1) == 0
    lay = _empty()
    lay.grid[3, 3] = W.GATE0 + 1
    assert W.ray(lay.grid, (2, 3, 1))[0] == 6 and W.ray(lay.grid, (4, 3, 3))[0] == 7
    assert max(W.fold_type(v, h) for v in range(W.N_TYPES) for h in range(4)) == W.RAY_CLASSES - 1


def test_map_agent_rays_fold_gates_by_heading():
    """地图智能体的批量射线表与 world.ray 逐位姿一致（单向门按朝向折叠）。"""
    lay = W.make_layout(7_950_000, W.Config(**WORLDS["h2"]))
    fr = Frame(lay.cfg.size, lay.cfg, ForwardModel(kind="analytic"), (1, 1, 0))
    fr.map[:] = lay.grid
    seen = []
    fr.fm.predict = lambda rays: seen.append(rays) or np.zeros(rays.shape[:-1], dtype=np.int64)
    fr.table()
    rays = seen[0]
    for x, y in lay.free_cells():
        for h in range(4):
            assert (rays[y, x, h] == W.ray(lay.grid, (x, y, h))).all()


def test_h2_layouts_have_all_laws_and_no_traps():
    cfg = W.Config(**WORLDS["h2"])
    for seed in range(7_950_000, 7_950_006):
        lay = W.make_layout(seed, cfg)
        g = lay.grid
        assert (g == W.PAD).sum() == cfg.pads
        assert ((g >= W.GATE0) & (g < W.GATE0 + 4)).sum() == cfg.gates
        assert len(lay.portal_to) == cfg.portals
        assert W._strongly_connected(lay)
        rs = cfg.room_size
        for y, x in zip(*np.nonzero((g >= W.GATE0) & (g < W.GATE0 + 4))):   # 门只在墙线上，方向沿门洞的轴
            d = int(g[y, x]) - W.GATE0
            assert (x % (rs + 1) == 0 and d in (1, 3)) or (y % (rs + 1) == 0 and d in (0, 2))
        rng = random.Random(seed)
        for _ in range(50):
            p = W.random_pose(lay, rng)
            assert W.is_floor(int(g[p[1], p[0]]))


def test_analytic_step_matches_true_step_in_h1():
    cfg = W.Config(**WORLDS["h1"])
    lay = W.make_layout(7_950_100, cfg)
    for x, y in lay.free_cells():
        for h in range(4):
            for a in range(W.N_ACTIONS):
                assert W.analytic_step(lay.grid, (x, y, h), a) == W.step(lay, (x, y, h), a)


def test_fast_strong_connectivity_matches_reference():
    """新写法与 M6 之前的写法判定相同：正例取已生成的图，反例取放置过程中被拒的图。"""
    import random as _r
    cfg = W.Config(**WORLDS["h2"])
    checked = {True: 0, False: 0}
    for seed in range(7_950_200, 7_950_212):
        for name in ("m2", "h2"):                                    # 正例：生成器产出的图
            g = W.make_layout(seed, W.Config(**WORLDS[name]))
            assert W._strongly_connected(g) and W._strongly_connected_ref(g)
            checked[True] += 1
        rng = _r.Random(seed)
        base = W.make_layout(seed, W.Config(rooms=5)).grid.copy()
        for _ in range(4):
            lay = W.Layout(seed=seed, cfg=cfg, grid=base.copy())
            W._place_ice(lay, rng)
            W._place_portals(lay, rng)
            W._place_pads(lay, rng)
            free = [c for c in lay.free_cells() if W._room_interior(lay, c) is False and W.is_floor(lay.grid[c[1], c[0]])]
            for c in rng.sample(free, k=min(8, len(free))):          # 随机放单向门，不查连通，制造反例
                d = rng.choice((1, 3) if c[0] % (cfg.room_size + 1) == 0 else (0, 2))
                lay.grid[c[1], c[0]] = W.GATE0 + d
            fast, ref = W._strongly_connected(lay), W._strongly_connected_ref(lay)
            assert fast == ref
            checked[ref] += 1
    assert checked[True] > 0 and checked[False] > 0
