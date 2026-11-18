"""注意力记忆组：读出层的分组与因果、hindsight 标签、训练不读真值、智能体的历史拼接。"""
import mlx.core as mx
import numpy as np

from ainerzero.v9.mini import attn as AT
from ainerzero.v9.mini import data as D
from ainerzero.v9.mini import evaluate as E
from ainerzero.v9.mini import world as W

CFG = W.Config()


def _net(seed=0, d=32, heads=4):
    mx.random.seed(seed)
    net = AT.AttnNets(329, d=d, layers=2, heads=heads)
    mx.eval(net.parameters())
    return net


def _rand_inputs(B=2, L=7, G=3, seed=0):
    rng = np.random.default_rng(seed)
    obs = rng.random((B, L, 329)).astype(np.float32)
    prev = rng.integers(0, 4, (B, L)).astype(np.int32)
    og = rng.random((B, G, 329)).astype(np.float32)
    return mx.array(obs), mx.array(prev), mx.array(og)


def _naive_q(net, h, x, og):
    """逐个目标、逐个位置的朴素读出（显式掩码），与分组实现对照。"""
    B, L, d = h.shape
    H, dh = net.heads, d // net.heads
    eg = net.goal_enc(og)
    kv = mx.concatenate([h, x], axis=-1)
    k = net.rope(net.rk(kv).reshape(B, L, H, dh).transpose(0, 2, 1, 3))
    v = net.rv(kv).reshape(B, L, H, dh).transpose(0, 2, 1, 3)
    outs = []
    for g in range(og.shape[1]):
        q = net.rq(mx.concatenate([h, mx.broadcast_to(eg[:, g:g + 1], h.shape)], axis=-1))
        q = net.rope(q.reshape(B, L, H, dh).transpose(0, 2, 1, 3))
        s = (q @ k.transpose(0, 1, 3, 2)) * dh ** -0.5
        mask = np.triu(np.full((L, L), -np.inf, dtype=np.float32), 1)
        r = mx.softmax(s + mx.array(mask), axis=-1) @ v
        r = r.transpose(0, 2, 1, 3).reshape(B, L, d)
        z = mx.concatenate([h, mx.broadcast_to(eg[:, g:g + 1], h.shape), net.ro(r)], axis=-1)
        outs.append(1.0 + net.scale * mx.logaddexp(net.head(z) + net.b0, 0.0))
    return mx.stack(outs, axis=1)


def test_readout_matches_naive_per_goal_attention():
    net = _net()
    obs, prev, og = _rand_inputs()
    h, x = net.encode(obs, prev)
    q = np.array(net.q_values(h, x, og))
    ref = np.array(_naive_q(net, h, x, og))
    assert q.shape == (2, 3, 7, W.N_ACTIONS)
    assert np.allclose(q, ref, atol=1e-4)


def test_last_only_equals_last_position_of_full():
    net = _net(1)
    obs, prev, og = _rand_inputs(L=9, seed=1)
    h, x = net.encode(obs, prev)
    full = np.array(net.q_values(h, x, og))[:, :, -1:]
    last = np.array(net.q_values(h, x, og, last_only=True))
    assert np.allclose(full, last, atol=1e-4)


def test_causal_future_frames_do_not_change_past_q():
    net = _net(2)
    obs, prev, og = _rand_inputs(L=8, seed=2)
    h, x = net.encode(obs, prev)
    q1 = np.array(net.q_values(h, x, og))
    o2 = np.array(obs)
    o2[:, 5:] = np.random.default_rng(9).random(o2[:, 5:].shape)
    h2, x2 = net.encode(mx.array(o2), prev)
    q2 = np.array(net.q_values(h2, x2, og))
    assert np.allclose(q1[:, :, :5], q2[:, :, :5], atol=1e-4)
    assert not np.allclose(q1[:, :, 5:], q2[:, :, 5:], atol=1e-4)


def test_hindsight_labels_hand_case():
    # 观察编号：位置 0..7；目标编号 5 出现在位置 2 和 6；编号 9 从不出现
    wid = np.array([[1, 2, 5, 3, 4, 3, 5, 1]])
    gid = np.array([[5, 9]])
    ub, done, valid = AT.hindsight_labels(wid, gid)
    assert ub.shape == (1, 2, 7)
    # 目标 5：t=0 → 第一次在 2，用 2 步；t=1 → 1 步；t=2 → 下一次在 6，4 步；t=5 → 1 步；t=6 → 之后没有
    assert ub[0, 0].tolist() == [2, 1, 4, 3, 2, 1, np.inf]
    assert done[0, 0].tolist() == [False, True, False, False, False, True, False]
    assert valid[0, 0].tolist() == [True, True, False, True, True, True, False]
    assert np.isinf(ub[0, 1]).all() and not done[0, 1].any() and valid[0, 1].all()


def test_compose_target_takes_min_of_bootstrap_bound_and_cap():
    v = np.array([5.0, 5.0, 500.0, 0.3])
    done = np.array([False, False, False, True])
    ub = np.array([np.inf, 3.0, np.inf, np.inf])
    y = AT.compose_target(v, done, ub, cap=200.0)
    assert y.tolist() == [6.0, 3.0, 200.0, 1.0]


def test_long_walks_same_layouts_and_env_steps():
    a = D.generate(3, 4, 50, CFG)
    b = AT.long_walks(CFG, 3, 4, 50)
    assert b.n_traj == 3 and b.horizon == 200
    assert a.act.size == b.act.size
    assert (b.layout_id == np.arange(3)).all()


def test_obs_ids_exact_equality():
    o = np.zeros((1, 4, 5), dtype=np.float32)
    o[0, 1, 0] = 1
    o[0, 3, 0] = 1
    ids = AT.obs_ids(o)
    assert ids[0, 0] == ids[0, 2] and ids[0, 1] == ids[0, 3] and ids[0, 0] != ids[0, 1]


def test_training_reads_only_obs_and_act():
    ds = AT.long_walks(CFG, 2, 1, 40)
    ds.pose = None                       # 训练若读真值位姿会直接出错
    net, info = AT.train_attn(ds, AT.AttnConfig(steps=2, batch=2, goals=2, window=20, d=16, layers=1, heads=2, log_every=1),
                              log=lambda *_: None)
    assert info["params"] > 0 and len(info["history"]) == 2


class _RecNets:
    """桩网络：记下每次看到的历史；代价让动作 2 最便宜。"""

    def __init__(self):
        self.seen = []

    def encode(self, obs, prev):
        self.seen.append((np.array(obs)[0], np.array(prev)[0]))
        return obs, obs

    def q_values(self, h, x, og, last_only=False):
        return mx.array(np.array([[[[3.0, 2.0, 1.0]]]], dtype=np.float32))


def test_agent_history_appends_obs_and_own_actions():
    n = 4
    prefix = np.eye(n, 6, dtype=np.float32)
    from ainerzero.v9.mini import agents as A
    ep = A.Episode(prefix, None, None, [0, 1, 2], np.ones(6, np.float32), None, None)
    rec = _RecNets()
    ag = AT.AttnAgent(rec, eps=0.0)
    ag.reset(ep)
    a1 = ag.act(prefix[-1], None, None)       # 第一步：观察就是前缀最后一帧，不重复追加
    o2 = np.full(6, 7, np.float32)
    a2 = ag.act(o2, None, None)
    assert a1 == 2 and a2 == 2
    obs1, prev1 = rec.seen[0]
    assert obs1.shape[0] == n and prev1.tolist() == [AT.NONE_ACTION, 0, 1, 2]
    obs2, prev2 = rec.seen[1]
    assert obs2.shape[0] == n + 1 and (obs2[-1] == 7).all() and prev2.tolist() == [AT.NONE_ACTION, 0, 1, 2, 2]


def test_arm_registered():
    assert "latent_attn" in E.ARMS
