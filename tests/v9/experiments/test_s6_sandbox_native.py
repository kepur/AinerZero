"""S6 sandbox against the real pieces (MLX imports): make_pool labels and gated.geo_gate parity."""
from __future__ import annotations

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

from ainerzero.v9.experiments.s4 import gated as G  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402

NS = "s6t-sandbox-native"


class ScriptedDraws:
    """Drives learned_mlx.make_pool to draw exactly the given (episode, step) pairs, exact states:
    per draw make_pool calls integers(len(episodes)), integers(len(steps)), then random() < exact_frac."""

    def __init__(self, pairs):
        self.seq = []
        for e, t in pairs:
            self.seq += [("i", e), ("i", t), ("r", 0.0)]
        self.pos = 0

    def _next(self, kind):
        k, v = self.seq[self.pos]
        assert k == kind, (k, kind, self.pos)
        self.pos += 1
        return v

    def integers(self, n):
        v = self._next("i")
        assert 0 <= v < n
        return v

    def random(self):
        return self._next("r")


@pytest.fixture(scope="module")
def episodes():
    return [W.generate_episode(NS, w, n, steps=80) for w, n in enumerate([4, 6, 8, 10, 6])]


def _states_from(episodes, pairs):
    by_n = {}
    for e, t in pairs:
        ep = episodes[e]
        row = by_n.setdefault(ep.n_disks, {"p": [], "v": [], "pil": []})
        row["p"].append(np.asarray(ep.steps[t].positions, float))
        row["v"].append(np.asarray(ep.steps[t].velocities, float))
        row["pil"].append(np.asarray(ep.pillars, float))
    return {n: {k: np.stack(v) for k, v in d.items()} for n, d in sorted(by_n.items())}


def test_rollout_and_label_keys_match_make_pool():
    assert S.ROLLOUT == L.ROLLOUT
    assert set(S.LABEL_KEYS) | set(S.STATE_KEYS) == {"p", "v", "pil", "contact", "p1", "v1", "p5", "v5", "p10", "v10"}


def test_sim_labels_equal_make_pool_labels(episodes):
    """Same exact states, labelled by make_pool (driven to draw exactly them) and by sim_labels: identical."""
    rng = np.random.default_rng(4)
    pairs = sorted({(int(rng.integers(5)), int(rng.integers(80))) for _ in range(200)})
    pool = L.make_pool(episodes, len(pairs), ScriptedDraws(pairs), W.physics, exact_frac=1.0)
    # make_pool groups by (disk count, episode) in sorted order, draws in order within a group
    order = sorted(range(len(pairs)), key=lambda i: (episodes[pairs[i][0]].n_disks, pairs[i][0], i))
    by_n_pairs = {}
    for i in order:
        by_n_pairs.setdefault(episodes[pairs[i][0]].n_disks, []).append(pairs[i])
    contacts = 0
    for n, prs in by_n_pairs.items():
        st = _states_from(episodes, prs)[n]
        lab = S.sim_labels(st["p"], st["v"], st["pil"])
        np.testing.assert_array_equal(pool.by_n[n]["p"], st["p"].astype(np.float32))
        np.testing.assert_array_equal(pool.by_n[n]["pil"], st["pil"].astype(np.float32))
        for k in S.LABEL_KEYS:
            np.testing.assert_array_equal(pool.by_n[n][k], lab[k], err_msg=f"n={n} {k}")
        contacts += int(lab["contact"].sum())
    assert contacts > 0                                          # the comparison covers disk contacts


def test_geo_flags_match_gated_geo_gate(episodes):
    pairs = [(e, t) for e in range(5) for t in range(80)]
    cp = S.CandidatePool(_states_from(episodes, pairs), pool_type=L.Pool)
    st = cp.states()
    flags = S.geo_flags(st)
    want = np.concatenate([G.geo_gate(e["p"].astype(np.float64), e["v"].astype(np.float64)).any(-1)
                           for _, e in sorted(st.items())])
    np.testing.assert_array_equal(flags, want)
    assert 0 < flags.sum() < len(flags)
    # flagged samples hold disk contacts far more often than unflagged ones
    a = cp.reveal(np.flatnonzero(flags)); b = cp.reveal(np.flatnonzero(~flags))
    share = lambda q: np.mean(np.concatenate([e["contact"].sum((1, 2)) > 0 for e in q.by_n.values()]))
    assert share(a) > 0.5 > 0.05 > share(b)


def test_geo_flags_match_geo_gate_on_boundary_cases():
    R = W.RADIUS
    P = np.array([[[0, 0], [2 * R, 0], [5, 5]], [[0, 0], [R, 0], [5, 5]], [[0, 0], [2 * R + 0.05, 0], [5, 5]]], float)
    V = np.array([[[0, 1], [0, -1], [0, 0]], [[1, 0], [0, 0], [0, 0]], [[1, 0], [-1, 0], [0, 0]]], float)
    st = {3: {"id": np.arange(3), "p": P, "v": V, "pil": np.zeros((3, 3, 3))}}
    np.testing.assert_array_equal(S.geo_flags(st), G.geo_gate(P, V).any(-1))
    assert S.geo_flags(st).tolist() == [False, True, True]


def test_revealed_pool_is_a_training_pool(episodes):
    cp = S.CandidatePool(_states_from(episodes, [(e, t) for e in range(5) for t in range(0, 80, 2)]), pool_type=L.Pool)
    cp.reveal(S.pick_random(cp.remaining(), 120, np.random.default_rng(1)))
    rp = cp.revealed_pool()
    assert type(rp) is L.Pool and rp.size() == 120
    for n, idx in L.batches(rp, 3, 64, np.random.default_rng(2)):
        assert set(rp.by_n[n]) == {"p", "v", "pil", "p1", "v1", "p5", "v5", "p10", "v10", "contact"}
        assert len(idx) == 64
    batch = {k: mx.array(v[:8]) for k, v in rp.by_n[sorted(rp.by_n)[0]].items()}
    assert np.isfinite(float(L.rollout_loss(L.Dynamics("L-int"), batch).item()))
