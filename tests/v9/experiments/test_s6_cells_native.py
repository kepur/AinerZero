"""S6 cells (MLX): candidate states, the seal, one cell per arm at tiny sizes, records and determinism."""
from __future__ import annotations

import json

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402

NS = "s6t-cells-native"
TINY = C.Sizes(per=40, rounds=2, steps=15, pool=500, cand_worlds=4)


@pytest.fixture(scope="module")
def source():
    return C.candidate_source(NS, 0, TINY)


@pytest.fixture(scope="module")
def cells(source, tmp_path_factory):
    root = tmp_path_factory.mktemp("cells")
    recs = {arm: C.run_cell(arm, 0, source, root / arm, cand_ns=NS, sizes=TINY) for arm in C.ARMS}
    return root, recs


def test_candidate_states_distinct_deterministic_and_exact(source):
    assert C.n_states(source) == TINY.pool
    assert C.pool_digest(source) == C.pool_digest(C.candidate_source(NS, 0, TINY))
    assert C.pool_digest(source) != C.pool_digest(C.candidate_source(NS, 1, TINY))
    eps = C.candidate_worlds(NS, 0, TINY)
    assert [ep.world_index for ep in eps] == list(range(4))
    assert [ep.world_index for ep in C.candidate_worlds(NS, 2, TINY)] == list(range(8, 12))
    seen = set()
    for n, e in source.items():
        assert set(e) == {"p", "v", "pil"} and e["p"].dtype == np.float64
        for b in range(len(e["p"])):
            key = e["p"][b].tobytes() + e["v"][b].tobytes()
            assert key not in seen
            seen.add(key)
            # every candidate is an exact state of some candidate world
    states = {(ep.n_disks, ep.steps[t].positions.tobytes()) for ep in eps for t in range(len(ep.steps))}
    assert all((n, e["p"][b].tobytes()) in states for n, e in source.items() for b in range(len(e["p"])))
    with pytest.raises(ValueError, match="only"):
        C.candidate_source(NS, 0, C.Sizes(pool=10_000, cand_worlds=2))


@pytest.mark.parametrize("call", ["physics", "generate_episode", "train_worlds", "bounce", "true_physics", "make_pool",
                                  "sim_labels", "reveal", "revealed_pool"])
def test_the_seal_blocks_every_route_to_an_outcome(call, source):
    cp = C.make_candidate_pool(source)
    ep = W.generate_episode(NS, 0, 4, steps=5)
    P, V = ep.steps[0].positions[None], ep.steps[0].velocities[None]
    routes = {"physics": lambda: W.physics(P, V, ep.pillars),
              "generate_episode": lambda: W.generate_episode(NS, 0, 4, steps=5),
              "train_worlds": lambda: A.train_worlds(NS, 1),
              "bounce": lambda: Mo.bounce(P, V, ep.pillars),
              "true_physics": lambda: Mo.true_physics(P, V, ep.pillars),
              "make_pool": lambda: L.make_pool([ep], 2, np.random.default_rng(0), W.physics),
              "sim_labels": lambda: S.sim_labels(P, V, np.asarray(ep.pillars, float)[None]),
              "reveal": lambda: cp.reveal([0]),
              "revealed_pool": lambda: cp.revealed_pool()}
    with C.sealed():
        with pytest.raises(C.SealBreach):
            routes[call]()
    assert cp.log() == [] and cp.revealed_ids().tolist() == []
    routes[call]()                                                   # restored afterwards


def test_the_seal_is_restored_after_an_error():
    real = W.physics
    with pytest.raises(RuntimeError):
        with C.sealed():
            raise RuntimeError("boom")
    assert W.physics is real and S.CandidatePool.reveal.__name__ == "reveal"


def test_every_arm_runs_and_records(cells):
    root, recs = cells
    for arm, rec in recs.items():
        C.verify_cell_dir(root / arm, TINY)
        assert rec["arm"] == arm and len(rec["tracks"]) == (3 if arm == "P" else 1)
        assert json.loads((root / arm / "cell.json").read_text()) == json.loads(json.dumps(rec, sort_keys=True))
    first = recs["R"]["tracks"][0]["picks"][0]
    assert all(tr["picks"][0] == first for rec in recs.values() for tr in rec["tracks"])
    assert recs["T"]["tracks"][0]["picks"] == recs["R"]["tracks"][0]["picks"]       # T picks what R picks
    assert recs["E"]["tracks"][0]["picks"][1] != recs["R"]["tracks"][0]["picks"][1]
    for arm in ("E", "Z", "P"):
        assert all(d is not None for d in recs[arm]["tracks"][0]["score_sha256"][1:])
    for arm in ("R", "T", "G"):
        assert all(d is None for d in recs[arm]["tracks"][0]["score_sha256"])


def test_t_differs_from_r_only_by_its_curriculum(cells):
    """T picks exactly what R picks with the same seeds, so its weights differ from R's only through the
    collision curriculum in its batches; without the curriculum they would be bit-identical."""
    root, recs = cells
    assert recs["T"]["tracks"][0]["picks"] == recs["R"]["tracks"][0]["picks"]
    t0 = mx.load(str(root / "T" / "r0-n0.safetensors"))
    r0 = mx.load(str(root / "R" / "r0-n0.safetensors"))
    assert set(t0) == set(r0)
    assert any(not np.array_equal(np.array(t0[k]), np.array(r0[k])) for k in t0)
    assert C.T_COLL_SHARE == 0.5


def test_z_picks_the_closest_pairs(cells, source):
    """Against an independent oracle (pairwise loop), not the module's own closest_pair."""
    import math
    _, recs = cells
    st = C.make_candidate_pool(source).states()
    score = np.empty(C.n_states(source))
    for n, e in st.items():
        for b, g in enumerate(e["id"]):
            P = e["p"][b].astype(np.float64)
            score[g] = -min(math.sqrt((P[i, 0] - P[j, 0]) ** 2 + (P[i, 1] - P[j, 1]) ** 2) for i in range(n) for j in range(i + 1, n))
    rem = np.setdiff1d(np.arange(C.n_states(source)), recs["Z"]["tracks"][0]["picks"][0])
    order = sorted(rem.tolist(), key=lambda g: (-score[g], g))
    assert set(recs["Z"]["tracks"][0]["picks"][1]) == set(order[:TINY.per])
    np.testing.assert_allclose(C.closest_pair(st), score, rtol=0, atol=1e-12)


def test_neighbouring_ids_are_not_neighbouring_steps(source):
    """Ids follow the draw order within a disk count, so id g and g+1 are rarely consecutive steps of one world."""
    eps = C.candidate_worlds(NS, 0, TINY)
    where = {(ep.n_disks, ep.steps[t].positions.tobytes()): (ep.world_index, t) for ep in eps for t in range(len(ep.steps))}
    pos = []
    for n, e in sorted(source.items()):
        pos += [where[(n, e["p"][b].tobytes())] for b in range(len(e["p"]))]
    adjacent = np.mean([a[0] == b[0] and abs(a[1] - b[1]) == 1 for a, b in zip(pos, pos[1:])])
    assert adjacent < 0.05, adjacent


def test_tampering_is_detected(cells, tmp_path):
    import shutil
    root, recs = cells
    d = tmp_path / "E"
    shutil.copytree(root / "E", d)
    f = d / "r0-n1.safetensors"
    f.write_bytes(f.read_bytes()[:-1] + bytes([f.read_bytes()[-1] ^ 1]))
    with pytest.raises(AssertionError, match="changed"):
        C.verify_cell_dir(d, TINY)
    rec = json.loads((root / "E" / "cell.json").read_text())
    rec["tracks"][0]["reveal_log"][1]["ids"] = rec["tracks"][0]["reveal_log"][1]["ids"][::-1]
    with pytest.raises(AssertionError, match="reveal log"):
        C.check_cell_record(rec, TINY)
    rec = json.loads((root / "E" / "cell.json").read_text())
    rec["tracks"][0]["picks"][1][0] = rec["tracks"][0]["picks"][0][0]
    rec["tracks"][0]["reveal_log"][1]["ids"][0] = rec["tracks"][0]["picks"][0][0]
    with pytest.raises(AssertionError, match="twice"):
        C.check_cell_record(rec, TINY)


def test_a_learner_retrains_bit_for_bit_from_the_saved_picks(cells, source):
    root, recs = cells
    for arm, j in (("E", 0), ("P", 0)):
        mx.set_default_device(mx.gpu)
        lr = C.make_learner(arm, C.net_seeds(0)[j])
        cp = C.make_candidate_pool(source)
        tr = recs[arm]["tracks"][j if arm == "P" else 0]
        for r in range(TINY.rounds):
            cp.reveal(np.array(tr["picks"][r]))
            lr.train(cp.revealed_pool(), TINY.steps)
            saved = mx.load(str(root / arm / f"r{r}-n{j}.safetensors"))
            from mlx.utils import tree_flatten
            mine = dict(tree_flatten(lr.model.parameters()))
            assert set(saved) == set(mine)
            assert all(np.array_equal(np.array(saved[k]), np.array(mine[k])) for k in mine), (arm, r)


def test_evaluation_arithmetic(cells):
    root, _ = cells
    ep = W.generate_episode(NS + "-test", 0, 6)
    tw = C.prepare_world(ep)
    counts, eb = C.world_counts(tw)
    assert counts.sum() == (len(ep.steps) - 1) * 6
    mx.set_default_device(mx.cpu)
    m = C.load_model("E", root / "E" / "r1-n2.safetensors")
    s = C.world_sums(m, tw)
    _, v, _, _ = m(mx.array(tw.P), mx.array(tw.V), mx.array(tw.pil))
    e = np.linalg.norm(np.array(v, dtype=np.float64) - tw.target, axis=-1)
    np.testing.assert_allclose(s, [e[tw.kinds == c].sum() for c in range(4)])
    pm = C.load_model("P", root / "P" / "r1-n0.safetensors")
    assert pm.z is None                                  # P is evaluated on its base output
