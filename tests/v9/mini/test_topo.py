"""SPTM 式拓扑组：采样标签、记忆图、最短路与端到端重放（桩网络，不训练）。"""
import mlx.core as mx
import numpy as np

from ainerzero.v9.mini import agents as A
from ainerzero.v9.mini import data as D
from ainerzero.v9.mini import evaluate as E
from ainerzero.v9.mini import topo as T
from ainerzero.v9.mini import world as W

CFG = W.Config()


def _ds():
    return D.generate(3, 2, 60, CFG, seed0=D.TRAIN_SEED0)


def test_sample_reach_labels_follow_time_gap():
    ds = _ds()
    rng = np.random.default_rng(0)
    i, t1, t2, y = T.sample_reach(ds, rng, 4000, k_pos=3, k_neg=25)
    gap = np.abs(t2 - t1)
    assert ((t2 >= 0) & (t2 <= ds.horizon)).all()
    assert (gap[y == 1] <= 3).all()
    assert (gap[y == 0] >= 25).all()
    assert 0.4 < y.mean() < 0.6


def test_sample_loc_targets_within_k():
    ds = _ds()
    rng = np.random.default_rng(1)
    i, t, k, a = T.sample_loc(ds, rng, 4000, k_loc=4)
    assert ((k >= 1) & (k <= 4)).all()
    assert (t + k <= ds.horizon).all()
    assert (a == ds.act[i, t]).all()


def _keys(seq):
    return [bytes([x]) for x in seq]


def test_build_graph_edge_kinds_and_costs():
    # 帧 0..5；帧 1、2 观察相同（撞墙），帧 0 与帧 5 观察相同（回到原处）
    keys = _keys([7, 8, 8, 9, 10, 7])
    n = len(keys)
    p = np.full((n, n), 0.1)
    p[1, 4] = p[4, 1] = 0.99            # 学到的捷径：观察不同、隔得够远
    p[0, 2] = p[2, 0] = 0.99            # 隔 2 帧，不够 min_gap，不连
    cfg = T.TopoPlanConfig(min_gap=3)
    out = T.build_graph(p, keys, cfg)
    e = {(v, u): (w, k) for v, es in enumerate(out) for u, w, k in es}
    assert e[(0, 1)] == (1.0, T.FWD) and e[(1, 0)] == (cfg.w_rev, T.REV)
    assert e[(1, 2)] == (cfg.w_same, T.SAME) and e[(2, 1)] == (cfg.w_same, T.SAME)
    assert e[(0, 5)] == (cfg.w_same, T.SAME) and e[(5, 0)] == (cfg.w_same, T.SAME)
    assert e[(1, 4)] == (cfg.w_near, T.NEAR) and e[(4, 1)] == (cfg.w_near, T.NEAR)
    assert (0, 2) not in e
    out2 = T.build_graph(p, keys, T.TopoPlanConfig(min_gap=3, near=False))
    assert all(k != T.NEAR for es in out2 for _, _, k in es)


def test_dist_path_and_hops():
    keys = _keys([1, 2, 3, 4, 5, 1])     # 帧 5 与帧 0 同一处
    p = np.full((6, 6), 0.0)
    out = T.build_graph(p, keys, T.TopoPlanConfig(near=False))
    d = T.dist_to(out, [3])
    # 从帧 5 出发：同一处到帧 0，再正向 0→1→2→3
    path = T.path_ahead(out, d, 5, 10)
    assert path == [(0, T.SAME), (1, T.FWD), (2, T.FWD), (3, T.FWD)]
    assert abs(d[5] - (3 + T.TopoPlanConfig().w_same)) < 1e-9
    h = T.hops(out, 5, 1)
    assert h[0] == 0 and h[1] == 1 and 2 not in h   # 同一处的边不计跳数


class _IdentityNets:
    """桩网络：嵌入就是观察本身；观察完全相同时 R 判为可达，否则不可达。运动网络不应被调用。"""

    def embed(self, obs):
        return obs

    def reach_logit(self, ea, eb):
        ea, eb = mx.broadcast_arrays(ea, eb)
        same = mx.all(ea == eb, axis=-1)
        return mx.where(same, 10.0, -10.0)

    def action_logits(self, et, ew):
        raise AssertionError("这条用例只该用到重放")


def _straight_line():
    for seed in range(D.EVAL_SEED0, D.EVAL_SEED0 + 50):
        lay = W.make_layout(seed, CFG)
        for (x, y) in lay.free_cells():
            if all(lay.grid[y, x + k] >= W.FLOOR0 for k in range(4) if x + k < CFG.size):
                if x + 3 < CFG.size:
                    return lay, (x, y, 1)
    raise AssertionError("找不到直线段")


def test_agent_replays_prefix_to_goal():
    lay, a0 = _straight_line()
    F, L = W.FORWARD, W.LEFT
    acts = [F, F, F, L, L, F, F, F, L, L]   # 东行 3 格到目标，掉头走回，再掉头：终点位姿与第 0 帧相同
    poses = [a0]
    for a in acts:
        poses.append(W.step(lay, poses[-1], a))
    assert poses[-1] == poses[0]
    goal = poses[3]
    obs = W.iter_views(lay, poses)
    ep = A.Episode(obs, None, [p[2] for p in poses], acts, W.encode_obs(W.ego_view(lay, goal), goal[2]), None, goal[2])
    ag = T.TopoAgent(_IdentityNets(), T.TopoPlanConfig(eps=0.0, near=False))
    task = {"prefix_poses": poses, "prefix_acts": acts, "goal": goal, "start": poses[-1]}
    r = E.run_episode(lay, task, ag, budget=10)
    assert r["success"] == 1 and r["steps"] == 3
    assert r["relocalizations"] == 0 and r["lost"] is None   # 不与地图组的 lost 字段混


def test_arm_registered():
    assert "latent_topo" in E.ARMS and "topo_oracle_ctrl" in E.ARMS


def test_oracle_control_goto_follows_true_shortest_path():
    """特权参照组：decide 给出 goto 时，动作是真值最短路的第一步；重放与随机动作原样返回。"""
    lay, a0 = _straight_line()
    poses = [a0, W.step(lay, a0, W.FORWARD)]
    obs = W.iter_views(lay, poses)
    goal = (a0[0] + 3, a0[1], 1)
    ep = A.Episode(obs, None, None, [W.FORWARD], W.encode_obs(W.ego_view(lay, goal), goal[2]), None, goal[2])
    ag = T.TopoOracleControl(_IdentityNets(), T.TopoPlanConfig(eps=0.0, near=False))
    ag.reset(ep)
    task = {"prefix_poses": poses, "goal": goal}
    start = (a0[0], a0[1], 3)                      # 背对目标：最短路第一步必须是转身
    dm = W.reverse_bfs_to_cell(lay, (goal[0], goal[1]))
    best = min(dm.get(W.step(lay, start, a), 10 ** 6) for a in range(W.N_ACTIONS))
    ag.decide = lambda o: ("goto", None, None)
    a = ag.act_privileged(None, start, lay, task)
    assert a != W.FORWARD and dm[W.step(lay, start, a)] == best
    ag.decide = lambda o: ("goto", 0, None)        # 去第 0 帧所在的格
    a = ag.act_privileged(None, poses[1], lay, task)
    d0 = W.reverse_bfs_to_cell(lay, (a0[0], a0[1]))
    assert d0[W.step(lay, poses[1], a)] == min(d0.get(W.step(lay, poses[1], b), 10 ** 6) for b in range(W.N_ACTIONS))
    ag.decide = lambda o: ("replay", W.LEFT, None)
    assert ag.act_privileged(None, start, lay, task) == W.LEFT
