"""Truth-isolation, causality and negative-control contracts for the S3 arms.

Ported to pytest from the non-author harness of P208's second review
(``reports/V9-S3-PHASE1-review/claude-s3rev-1109/evidence/review_harness.py``, checks
T1-T8, T10, T11).  That review showed the previous project suite let 8 of 12 source
mutants through, including an A0 that reads the oracle record and an A2 that retrieves
by ground truth.  The checks keep the reviewer's logic; only the harness plumbing is
replaced by fixtures.  The namespace below is not a registered partition.
"""

from __future__ import annotations

import copy
import json
import math
import warnings
from pathlib import Path

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")

from ainerzero.v9.experiments.s3 import analysis as G  # noqa: E402
from ainerzero.v9.experiments.s3 import arms_mlx as A  # noqa: E402
from ainerzero.v9.experiments.s3 import batching as B  # noqa: E402
from ainerzero.v9.experiments.s3 import data as D  # noqa: E402
from ainerzero.v9.experiments.s3 import spec  # noqa: E402

NS = "test-s3-isolation"
NON_O = ("A0", "A1", "A2", "A3", "N")
ALL_FIELDS = (
    "obs", "query_t", "top1", "oracle", "shuffled", "candidates",
    "cand_feats", "cand_mask", "answer", "swapped", "bucket",
)
PREREG = Path(__file__).resolve().parents[3] / "reports/V9-S3-DESIGN/PREREG-r1.json"


class Spy(dict):
    """Record which keys are read; reading a forbidden key raises."""

    def __init__(self, d, read: set, forbidden=()):
        super().__init__(d)
        self.read, self.forbidden = read, set(forbidden)

    def _note(self, k):
        if k in self.forbidden:
            raise AssertionError(f"read forbidden field {k!r}")
        self.read.add(k)

    def __getitem__(self, k):
        self._note(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self._note(k)
        return super().get(k, default)


@pytest.fixture(scope="module", autouse=True)
def _cpu():
    mx.set_default_device(mx.cpu)


@pytest.fixture(scope="module")
def eps():
    return [D.generate_episode(D.derive_seed(NS, "world", i), D.derive_seed(NS, "ep", i)) for i in range(6)]


@pytest.fixture(scope="module")
def prep(eps):
    return [B.prepare_episode(e, 1.0, perm_seed=i) for i, e in enumerate(eps)]


@pytest.fixture(scope="module")
def batch(prep):
    return {k: mx.array(v) for k, v in B.collate(prep).items()}


def changed_fields(a, b, fields=ALL_FIELDS) -> list[str]:
    return [f for f in fields if not np.array_equal(getattr(a, f), getattr(b, f))]


def perturbed(b, keys, seed=99):
    rng = np.random.default_rng(seed)
    out = dict(b)
    n = b["query_t"].shape[0]
    if "oracle" in keys:
        out["oracle"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "top1" in keys:
        out["top1"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "shuffled" in keys:
        out["shuffled"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    if "answer" in keys:
        out["answer"] = mx.array(rng.integers(1, 17, size=n), dtype=mx.int32)
    if "swapped" in keys:
        out["swapped"] = mx.array(rng.random(n) < 0.5)
    if "bucket" in keys:
        out["bucket"] = mx.array(rng.integers(0, 4, size=n), dtype=mx.int32)
    if "candidates" in keys:
        c = np.array(b["candidates"]).copy()
        mask = np.array(b["cand_mask"])
        c[mask] = rng.integers(0, spec.T, size=int(mask.sum()))
        out["candidates"] = mx.array(c)
    return out


def logits(model, b, hard):
    lg, aux = A.forward(model, b, hard=hard)
    mx.eval(lg, aux)
    return np.asarray(lg)


def model_of(arm, seed=7):
    mx.random.seed(seed)
    m = A.ReadoutArm(arm)
    mx.eval(m.parameters())
    return m


def test_preparation_never_reads_truth_keys(eps, prep) -> None:
    step_read, event_read, ep_read = set(), set(), set()
    for i, e in enumerate(eps):
        spied = Spy(
            {
                **e,
                "steps": [Spy(s, step_read, forbidden=("truth",)) for s in e["steps"]],
                "events": [Spy(v, event_read, forbidden=("cell", "lag")) for v in e["events"]],
            },
            ep_read,
            forbidden=("content_state", "summary", "layout_sha256", "world_seed", "episode_seed"),
        )
        assert changed_fields(B.prepare_episode(spied, 1.0, perm_seed=i), prep[i]) == []
    assert step_read == {"t", "obs", "est_pose"}
    assert event_read == {"t", "prev_visit_t", "answer", "swapped", "bucket"}


@pytest.mark.parametrize(
    "name,slot",
    [("prev_visit_t", "oracle"), ("answer", "answer"), ("swapped", "swapped"), ("bucket", "bucket")],
)
def test_event_labels_reach_only_their_own_slot(eps, prep, name, slot) -> None:
    for i, e in enumerate(eps):
        e2 = copy.copy(e)
        evs = []
        for v in e["events"]:
            v = dict(v)
            if name == "prev_visit_t":
                v[name] = 0
            elif name == "answer":
                v[name] = 16 if v[name] != 16 else 15
            elif name == "swapped":
                v[name] = not v[name]
            else:
                v[name] = spec.BUCKET_LONG if v[name] != spec.BUCKET_LONG else spec.BUCKET_SHORT
            evs.append(v)
        e2["events"] = evs
        changed = changed_fields(B.prepare_episode(e2, 1.0, perm_seed=i), prep[i])
        assert [f for f in changed if f != slot] == []


@pytest.mark.parametrize("arm", NON_O)
@pytest.mark.parametrize("hard", [True, False])
def test_non_oracle_arms_ignore_oracle_and_labels(batch, arm, hard) -> None:
    m = model_of(arm)
    other = perturbed(batch, ("oracle", "answer", "swapped", "bucket"))
    assert np.array_equal(logits(m, batch, hard), logits(m, other, hard))


def test_oracle_arm_does_depend_on_oracle(batch) -> None:
    m = model_of("O")
    assert not np.array_equal(logits(m, batch, True), logits(m, perturbed(batch, ("oracle",)), True))


@pytest.mark.parametrize(
    "arm,keys",
    [
        ("A0", ("oracle", "top1", "shuffled", "candidates")),
        ("A1", ("oracle", "top1", "shuffled", "candidates")),
        ("A2", ("oracle", "shuffled", "candidates")),
        ("N", ("oracle", "top1", "candidates")),
        ("A3", ("oracle", "top1", "shuffled")),
    ],
)
def test_arms_read_only_their_own_retrieval_field(batch, arm, keys) -> None:
    m = model_of(arm)
    assert np.array_equal(logits(m, batch, True), logits(m, perturbed(batch, keys), True))


@pytest.mark.parametrize("arm,keys", [("A2", ("top1",)), ("N", ("shuffled",)), ("A3", ("candidates",))])
def test_arms_do_read_their_retrieval_field(batch, arm, keys) -> None:
    m = model_of(arm)
    assert not np.array_equal(logits(m, batch, True), logits(m, perturbed(batch, keys), True))


def _one_event_per_episode(batch, n_eps):
    ep, rng = np.array(batch["ep"]), np.random.default_rng(5)
    return [int(rng.choice(np.where(ep == e)[0])) for e in range(n_eps) if (ep == e).any()]


@pytest.mark.parametrize("arm", ("A0", "A1", "A2", "A3"))
def test_future_observations_do_not_change_an_event(batch, prep, arm) -> None:
    obs0, ep, q = np.array(batch["obs"]), np.array(batch["ep"]), np.array(batch["query_t"])
    m = model_of(arm)
    base = logits(m, batch, True)
    for i in _one_event_per_episode(batch, len(prep)):
        obs = obs0.copy()
        obs[ep[i], int(q[i]) + 1:] = 1.0 - obs[ep[i], int(q[i]) + 1:]
        other = dict(batch)
        other["obs"] = mx.array(obs)
        assert np.array_equal(base[i], logits(m, other, True)[i]), (int(ep[i]), int(q[i]))


def test_gru_depends_on_the_past_and_a0_only_on_the_present(batch, prep) -> None:
    obs0, ep, q = np.array(batch["obs"]), np.array(batch["ep"]), np.array(batch["query_t"])
    i = _one_event_per_episode(batch, len(prep))[0]
    t = int(q[i])

    m = model_of("A1")
    obs = obs0.copy()
    obs[ep[i], :t] = 1.0 - obs[ep[i], :t]
    other = dict(batch)
    other["obs"] = mx.array(obs)
    assert not np.array_equal(logits(m, batch, True)[i], logits(m, other, True)[i])

    m = model_of("A0")
    obs = obs0.copy()
    mask = np.ones(obs.shape[1], dtype=bool)
    mask[t] = False
    obs[ep[i], mask] = 1.0 - obs[ep[i], mask]
    other = dict(batch)
    other["obs"] = mx.array(obs)
    assert np.array_equal(logits(m, batch, True)[i], logits(m, other, True)[i])


def test_retrieval_is_unchanged_when_the_episode_is_cut_at_the_event(eps, prep) -> None:
    n = 0
    for i, e in enumerate(eps):
        full = prep[i]
        for v in e["events"]:
            t = v["t"]
            p = B.prepare_episode({**e, "steps": e["steps"][: t + 1], "events": [v]}, 1.0, perm_seed=i)
            if len(p.query_t) == 0:
                continue
            k = int(np.where(full.query_t == t)[0][0])
            n += 1
            assert p.top1[0] == full.top1[k]
            assert np.array_equal(p.candidates[0], full.candidates[k])
            assert np.array_equal(p.cand_feats[0], full.cand_feats[k])
            assert np.array_equal(p.cand_mask[0], full.cand_mask[k])
    assert n > 0


def test_records_respect_the_minimum_gap(prep) -> None:
    for p in prep:
        assert (p.top1 <= p.query_t - 5).all()
        for r in range(len(p.query_t)):
            assert (p.candidates[r][p.cand_mask[r]] <= p.query_t[r] - 5).all()


def test_retrieval_only_uses_pose_differences(eps, prep) -> None:
    for i, e in enumerate(eps):
        steps = [{**s, "est_pose": [s["est_pose"][0] + 1000.0, s["est_pose"][1] - 777.0, s["est_pose"][2]]} for s in e["steps"]]
        changed = changed_fields(
            B.prepare_episode({**e, "steps": steps}, 1.0, perm_seed=i),
            prep[i],
            ("top1", "candidates", "cand_feats", "cand_mask", "shuffled"),
        )
        assert changed == []


def _clustered(n_ep=40, n_seed=3, ev=8, seed=3):
    rng = np.random.default_rng(seed)
    ep, a, b = [], [], []
    p_a = np.clip(rng.normal(0.6, 0.25, n_ep), 0, 1)
    p_b = np.clip(p_a - rng.normal(0.1, 0.2, n_ep), 0, 1)
    for _ in range(n_seed):
        for e in range(n_ep):
            ep.append(np.full(ev, e))
            a.append(rng.random(ev) < p_a[e])
            b.append(rng.random(ev) < p_b[e])
    return np.concatenate(ep), np.concatenate(a), np.concatenate(b)


def _brute_force_interval(ep, a, b, resamples, seed):
    groups: dict[int, list[int]] = {}
    for e, x, y in zip(ep.tolist(), a.astype(int).tolist(), b.astype(int).tolist()):
        g = groups.setdefault(e, [0, 0, 0])
        g[0] += 1
        g[1] += x
        g[2] += y
    keys = sorted(groups)
    rng = np.random.default_rng(seed)
    out = []
    for row in rng.integers(0, len(keys), size=(resamples, len(keys))).tolist():
        n = sa = sb = 0
        for j in row:
            g = groups[keys[j]]
            n += g[0]
            sa += g[1]
            sb += g[2]
        out.append((sa - sb) / n)
    return np.percentile(out, [2.5, 97.5])


def test_bootstrap_matches_brute_force_episode_resampling() -> None:
    ep, a, b = _clustered()
    r = G.paired_bootstrap_delta(ep, a, b, resamples=2000, seed=11)
    lo, hi = _brute_force_interval(ep, a, b, 2000, 11)
    assert r["ci_low"] == pytest.approx(lo, abs=1e-12)
    assert r["ci_high"] == pytest.approx(hi, abs=1e-12)
    assert r["delta"] == pytest.approx(a.mean() - b.mean(), abs=1e-12)
    assert r["n_episodes"] == 40
    assert r["ci_low"] < r["delta"] < r["ci_high"]


def test_treating_seeds_as_episodes_narrows_the_interval() -> None:
    ep, a, b = _clustered()
    together = G.paired_bootstrap_delta(ep, a, b, resamples=2000, seed=11)
    offset = ep + np.repeat(np.arange(3) * 1000, len(ep) // 3)
    apart = G.paired_bootstrap_delta(offset, a, b, resamples=2000, seed=11)
    assert apart["n_episodes"] == 120
    assert together["ci_high"] - together["ci_low"] > apart["ci_high"] - apart["ci_low"]


def test_empty_data_cannot_pass_a_gate() -> None:
    c, empty = np.array([True, False]), np.array([False, False])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prim = {k: float(c[empty].mean()) for k in ("A0", "O", "N", "A1", "A2", "A3")}
        uns = {k: float(c[empty].mean()) for k in ("A2", "A3")}
    assert all(math.isnan(v) for v in prim.values())
    assert not any(G.legality(prim, uns, ("A2", "A3")).values())
    with pytest.raises(ValueError):
        G.paired_bootstrap_delta(np.array([], dtype=int), np.array([], dtype=bool), np.array([], dtype=bool))
    assert not float("nan") <= G.H3_MAX_DROP
    assert not G.difference_gate({"delta": float("nan"), "ci_low": 0.5}, 0.1)
    assert not G.difference_gate({"delta": 0.5, "ci_low": float("nan")}, 0.1)


def test_gate_constants_are_the_registered_values() -> None:
    assert G.CHANCE == 1.0 / 7.0
    assert G.FLOOR == 1.0 / 7.0 + 0.03
    assert G.H1_MIN_DELTA == 0.10
    assert G.H2_MIN_DELTA == 0.05
    assert G.H3_MAX_DROP == 0.05
    assert G.UPPER_MIN == 0.90
    assert G.UNSWAPPED_MIN == 0.80
    assert G.BOOTSTRAP_RESAMPLES == 10000
    assert G.BOOTSTRAP_SEED == 20261109


def test_gate_constants_agree_with_the_preregistration_file() -> None:
    if not PREREG.is_file():
        pytest.skip("preregistration not present in this copy")
    g = json.loads(PREREG.read_text(encoding="utf-8"))["gates"]
    assert G.CHANCE == g["chance"]
    assert G.FLOOR == g["floor"]
    assert G.UPPER_MIN == g["upper_O"]
    assert G.UNSWAPPED_MIN == g["unswapped_min"]
    assert G.BOOTSTRAP_RESAMPLES == g["bootstrap"]["resamples"]
    assert G.BOOTSTRAP_SEED == g["bootstrap"]["seed"]


def test_negative_control_record_differs_from_the_retrieved_one(prep) -> None:
    assert float(np.mean([np.mean(p.shuffled != p.top1) for p in prep])) > 0.9
