"""S2 learned-model planning (DESIGN-r2 appendix D3 / D3.1), pure CPU / NumPy.

Fake arms get pose information only from the observation features: the test
builds an observation -> pose table from the layout at construction time (test
side knowledge). Production ``plan_fn`` never passes world state, layout, goal
state or episode spec to the model; a guard proxy asserts this.
"""

from __future__ import annotations

import inspect
import math
import random
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import data as s2_data
from ainerzero.v9.experiments.s2 import eval as s2_eval
from ainerzero.v9.experiments.s2 import learned_planning as lp
from ainerzero.v9.experiments.s2 import planner, spec, world
from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded, ForwardCounter

KEY_DIMS = int(spec.TERRAIN_ONE_HOT_DIM) + 4  # terrain one-hot + heading one-hot
TEST_N_FWD = 1024
FLAT_CHOICE = {"H": 16}
HIER_CHOICE = {"macro_horizon": 4, "budget_ratio": 0.5}


# ---------------------------------------------------------------- fixtures


def _worlds(n_worlds: int = 2, n_pairs: int = 6) -> list[tuple[world.Layout, list[dict[str, Any]]]]:
    out = []
    for w in range(n_worlds):
        rng = random.Random(9100 + w)
        layout, pairs, _ = world.prepare_world_with_long_pairs(9100 + w, rng, n_long_pairs=n_pairs)
        specs = s2_data.make_goal_episode_specs(layout, pairs, random.Random(77 + w), partition="train")
        long_specs = [s for s in specs if s.get("kind", "long") == "long"][:n_pairs] or specs[:n_pairs]
        out.append((layout, long_specs))
    return out


class ObsPoseTable:
    """Observation features (terrain + heading) -> candidate poses, built from the layout."""

    def __init__(self, layout: world.Layout) -> None:
        self.table: dict[bytes, list[tuple[int, int, int]]] = {}
        for y in range(world.SIZE):
            for x in range(world.SIZE):
                if layout.terrain[y][x] == world.WALL:
                    continue
                for h in range(4):
                    st = world.State(x=x, y=y, heading=h)
                    obs = world.student_obs(layout, st, last_action=world.ACTION_WAIT, dt=1)
                    key = lp.featurize_obs(obs, 1)[:KEY_DIMS].tobytes()
                    self.table.setdefault(key, []).append((x, y, h))

    def pose(self, x_feat: np.ndarray) -> tuple[int, int, int]:
        cands = self.table.get(np.asarray(x_feat, dtype=np.float64)[:KEY_DIMS].tobytes())
        if not cands:
            raise KeyError("observation not in table")
        return sorted(cands)[0]


def _z(x: int, y: int, h: int) -> np.ndarray:
    ang = h * math.pi / 2
    return np.array([float(x), float(y), 0.3 * math.cos(ang), 0.3 * math.sin(ang)])


def _unz(z: np.ndarray) -> tuple[int, int, int]:
    z = np.asarray(z, dtype=np.float64)
    h = int(round(math.atan2(z[3], z[2]) / (math.pi / 2))) % 4
    return int(round(z[0])), int(round(z[1])), h


class PoseArm:
    """Good flat fake arm: latent = pose; predict_l1 = true dynamics on the layout."""

    counter = None

    def __init__(self, layout: world.Layout) -> None:
        self._layout = layout
        self._table = ObsPoseTable(layout)

    def encode(self, x: np.ndarray) -> np.ndarray:
        return _z(*self._table.pose(x))

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        x, y, h = _unz(z)
        act = int(np.asarray(a).reshape(-1)[0])
        nxt = world.step(self._layout, world.State(x=x, y=y, heading=h), act, k=max(1, int(round(dt))))
        return _z(nxt.x, nxt.y, nxt.heading)


class GeoPoseArm:
    """Good flat fake arm built per episode by the test: latent = geodesic distance to the
    episode goal (BFS map computed from the layout at construction) plus a tiny pose code."""

    counter = None
    _EPS = 1e-3

    def __init__(self, layout: world.Layout, goal: world.State) -> None:
        self._layout = layout
        self._table = ObsPoseTable(layout)
        self._dist = world.compute_bfs_distances(layout, goal.x, goal.y)
        self._far = float(max(self._dist.values()) + 10)

    def _zp(self, x: int, y: int, h: int) -> np.ndarray:
        d = float(self._dist.get((x, y), self._far))
        return np.array([d, self._EPS * x, self._EPS * y, self._EPS * h])

    def encode(self, x_feat: np.ndarray) -> np.ndarray:
        return self._zp(*self._table.pose(x_feat))

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        z = np.asarray(z, dtype=np.float64)
        x, y, h = (int(round(v / self._EPS)) for v in z[1:4])
        act = int(np.asarray(a).reshape(-1)[0])
        nxt = world.step(self._layout, world.State(x=x, y=y, heading=h % 4), act, k=max(1, int(round(dt))))
        return self._zp(nxt.x, nxt.y, nxt.heading)


class HierPoseArm(PoseArm):
    """Good hierarchical fake arm: z2 = position; macro (dx, dy) moves z2 in world frame."""

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        return np.asarray(z1, dtype=np.float64)[:2].copy()

    def predict_l2(self, z2: np.ndarray, macro_a: np.ndarray, macro_dt: float = 1.0) -> np.ndarray:
        m = np.asarray(macro_a, dtype=np.float64).reshape(-1)
        assert m.shape[0] == spec.MACRO_ACTION_DIM
        return np.asarray(z2, dtype=np.float64) + m[:2] / float(spec.MACRO_DXY_SCALE) * float(spec.S2_MACRO_STEPS)


class RandomArm:
    """Bad fake arm: latents unrelated to pose."""

    counter = None

    def __init__(self, seed: int = 0) -> None:
        self._rng = np.random.default_rng(seed)

    def encode(self, x: np.ndarray) -> np.ndarray:
        return self._rng.normal(size=4)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        return self._rng.normal(size=4)


class TruthGuard:
    """Proxy that forbids attribute writes and records argument types of every call."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "arg_types", set())

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: D401
        raise AssertionError(f"plan_fn must not set model attribute {name!r}")

    def __getattr__(self, name: str) -> Any:
        attr = getattr(object.__getattribute__(self, "_inner"), name)
        if not callable(attr):
            return attr
        types = object.__getattribute__(self, "arg_types")

        def call(*args: Any, **kwargs: Any) -> Any:
            for v in list(args) + list(kwargs.values()):
                types.add(type(v).__name__)
                assert not isinstance(v, (world.State, world.Layout, dict)), f"truth reached model: {type(v)}"
            return attr(*args, **kwargs)

        return call


def _run(arm: Any, kind: str, choice: dict, layout: world.Layout, ep_spec: dict, seed: int, n_fwd: int = TEST_N_FWD):
    plan_fn = lp.make_plan_fn(arm, kind, choice, n_fwd)
    counter = ForwardCounter(budget=n_fwd)
    return s2_eval.run_episode(
        layout, ep_spec, plan_fn, counter, seed, m=int(spec.REPLAN_M_STEPS), catch_budget_exceeded=True
    )


# ---------------------------------------------------------------- D3.1 rule


@pytest.mark.parametrize("n_fwd", [2048, 4096, 8192])
@pytest.mark.parametrize("h", list(spec.FLAT_H_CANDIDATES))
def test_flat_population_follows_registered_rule(n_fwd: int, h: int) -> None:
    cfg = lp.cem_config_for_budget("arm_b", {"H": h}, n_fwd)
    assert cfg.pop_size == (n_fwd - spec.CEM_ENCODE_RESERVE) // (spec.CEM_N_ITERS * h)
    assert cfg.n_iters == spec.CEM_N_ITERS and cfg.horizon == h
    assert cfg.n_exec == spec.REPLAN_M_STEPS and cfg.n_categories == spec.ACTION_DIM
    assert cfg.pop_size * cfg.n_iters * h + spec.CEM_ENCODE_RESERVE <= n_fwd


@pytest.mark.parametrize("n_fwd", [2048, 4096, 8192])
@pytest.mark.parametrize("m", list(spec.HIERARCHICAL_HORIZON_CANDIDATES))
@pytest.mark.parametrize("rho", list(spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES))
def test_hierarchical_populations_follow_registered_rule(n_fwd: int, m: int, rho: float) -> None:
    cfg = lp.cem_config_for_budget("arm_c", {"macro_horizon": m, "budget_ratio": rho}, n_fwd)
    usable = n_fwd - spec.CEM_ENCODE_RESERVE
    upper = int(math.floor(rho * usable))
    assert cfg.upper_budget == upper and cfg.lower_budget == usable - upper
    assert cfg.upper_pop == upper // (spec.CEM_N_ITERS * m)
    assert cfg.lower_pop == (usable - upper) // (spec.CEM_N_ITERS * (spec.S2_MACRO_STEPS + 1))
    assert cfg.s2 == spec.S2_MACRO_STEPS and cfg.macro_dim == spec.MACRO_ACTION_DIM
    assert cfg.n_macro_categories is None


def test_plan_choice_is_required_and_validated() -> None:
    with pytest.raises(ValueError):
        lp.cem_config_for_budget("arm_a", None, 4096)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        lp.cem_config_for_budget("arm_a", {"H": 20}, 4096)
    with pytest.raises(ValueError):
        lp.cem_config_for_budget("arm_a", {"H": 16, "pop_size": 32}, 4096)
    with pytest.raises(ValueError):
        lp.cem_config_for_budget("arm_c", {"macro_horizon": 6}, 4096)
    with pytest.raises(ValueError):
        lp.cem_config_for_budget("arm_b", {"H": 48}, 300)  # population < CEM_MIN_POP
    with pytest.raises(ValueError):
        lp.make_plan_fn(RandomArm(), "arm_b", None, 4096)  # type: ignore[arg-type]


def test_expected_k_and_macro_denormalization() -> None:
    assert lp.expected_k() == pytest.approx(1.7)
    out = lp.denormalize_macro(np.array([1.0, -1.0, 0.5, 1.0, -1.0, 1.0, -1.0]))
    assert out[0] == pytest.approx(spec.MACRO_DXY_SCALE) and out[1] == pytest.approx(-spec.MACRO_DXY_SCALE)
    assert out[2] == pytest.approx(0.5 * math.pi)
    assert out[3:].sum() == pytest.approx(1.0)


# ---------------------------------------------------------------- truth isolation


def test_plan_fn_signature_excludes_truth() -> None:
    plan_fn = lp.make_plan_fn(RandomArm(), "arm_b", FLAT_CHOICE, TEST_N_FWD)
    assert list(inspect.signature(plan_fn).parameters) == ["obs", "goal_obs", "k", "counter", "rng"]


def test_no_truth_reaches_model_during_episode() -> None:
    layout, specs = _worlds(1, 1)[0]
    guard = TruthGuard(PoseArm(layout))
    res = _run(guard, "arm_b", FLAT_CHOICE, layout, specs[0], seed=3)
    assert res.total_forwards > 0
    assert guard.arg_types <= {"ndarray", "float", "int", "float64", "int64"}


def test_model_with_own_counter_is_refused() -> None:
    arm = RandomArm()
    arm.counter = ForwardCounter(budget=10)  # type: ignore[assignment]
    with pytest.raises(ValueError):
        lp.make_plan_fn(arm, "arm_b", FLAT_CHOICE, TEST_N_FWD)


# ---------------------------------------------------------------- closed-loop quality


# Closed-loop success of a perfect fake arm is owned by W5 (DESIGN-r2 appendix E): under the
# r2.5 protocol (m=4, terminal cost, future dt=E[k]) even a perfect model fails on long goals.


def test_hierarchical_arm_runs_two_levels_and_charges_l2() -> None:
    layout, specs = _worlds(1, 2)[0]
    plan_fn = lp.make_plan_fn(HierPoseArm(layout), "arm_c", HIER_CHOICE, TEST_N_FWD)
    counter = ForwardCounter(budget=TEST_N_FWD)
    counter.begin_episode()
    obs = world.student_obs(layout, s2_eval._to_state(specs[0]["start"]), last_action=world.ACTION_WAIT, dt=1)
    goal_state = s2_eval._to_state(specs[0]["goal"])
    goal_obs = {
        "view": world.compute_ego_view(layout, goal_state.x, goal_state.y, goal_state.heading),
        "heading": [1 if i == goal_state.heading else 0 for i in range(4)],
    }
    res = plan_fn(obs, goal_obs, 1, counter, np.random.default_rng(0))
    names = counter.by_name
    assert names.get("encode_l2", 0) > 0 and names.get("predict_l2", 0) > 0
    assert names.get("predict_l1", 0) > 0
    assert counter.total <= TEST_N_FWD
    assert len(np.asarray(res.actions).reshape(-1)) == spec.REPLAN_M_STEPS


# ---------------------------------------------------------------- counting


def test_goal_encoding_charged_once_per_episode_and_budget_respected() -> None:
    layout, specs = _worlds(1, 1)[0]
    res = _run(PoseArm(layout), "arm_b", FLAT_CHOICE, layout, specs[0], seed=5)
    per_decision = [d for d in res.decision_counts]
    assert len(per_decision) >= 2
    enc = [int(d["by_name"].get("encode", 0)) for d in per_decision]
    # decision 1: current obs + goal; later decisions: current obs only
    assert enc[0] == 2 and all(e == 1 for e in enc[1:]), enc
    assert all(int(d.get("total", 0)) <= TEST_N_FWD for d in per_decision)


def test_budget_overrun_voids_episode() -> None:
    layout, specs = _worlds(1, 1)[0]
    plan_fn = lp.make_plan_fn(PoseArm(layout), "arm_b", FLAT_CHOICE, TEST_N_FWD)
    small = ForwardCounter(budget=TEST_N_FWD)
    small.charge("encode", TEST_N_FWD - 3)  # leave almost nothing, then plan
    with pytest.raises(ForwardBudgetExceeded):
        plan_fn(
            world.student_obs(layout, s2_eval._to_state(specs[0]["start"]), last_action=world.ACTION_WAIT, dt=1),
            {"view": world.compute_ego_view(layout, 1, 1, 0), "heading": [1, 0, 0, 0]},
            1,
            small,
            np.random.default_rng(0),
        )


# ---------------------------------------------------------------- checkpoints (G3)


class _NpArm:
    counter = None

    def __init__(self) -> None:
        self.loaded: str | None = None

    def load(self, path: Any) -> None:
        self.loaded = str(path)


def _ledger_with_train_run(tmp_path: Any, arm: str, seed: int, sha: str | None, *, complete: bool = True) -> Any:
    from ainerzero.v9.experiments.s2 import worker

    db = tmp_path / "control.sqlite3"
    led = worker.S2Ledger(db)
    try:
        rid = led.open_run(mode="train", arm=arm, seed=seed, cell_wall_budget=10.0)
        led.begin_run(rid, state="training")
        if complete:
            led.complete_run(rid, metrics={} if sha is None else {"checkpoint_sha256": sha})
    finally:
        led.close()
    return db


def _write_ckpt(root: Any, arm: str, seed: int, payload: bytes) -> str:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    path = adapters_mlx.checkpoint_path(root, arm, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return adapters_mlx._sha256_file(path)


def test_checkpoint_loads_only_when_ledger_sha_matches(tmp_path: Any) -> None:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    sha = _write_ckpt(tmp_path, "arm_b", 43, b"weights")
    db = _ledger_with_train_run(tmp_path, "arm_b", 43, sha)
    model = adapters_mlx.load_trained_model(tmp_path, "B", 43, ledger_path=db, model_factory=lambda a: _NpArm())
    assert model.loaded == str(adapters_mlx.checkpoint_path(tmp_path, "arm_b", 43))


def test_checkpoint_refused_on_sha_mismatch_missing_record_or_meta_only(tmp_path: Any) -> None:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    _write_ckpt(tmp_path, "arm_a", 42, b"weights")
    bad = _ledger_with_train_run(tmp_path, "arm_a", 42, "0" * 64)
    with pytest.raises(ValueError, match="sha mismatch"):
        adapters_mlx.load_trained_model(tmp_path, "arm_a", 42, ledger_path=bad, model_factory=lambda a: _NpArm())
    # a meta.json next to the checkpoint is never a substitute for the ledger
    meta = adapters_mlx.checkpoint_path(tmp_path, "arm_a", 42).parent / "meta.json"
    meta.write_text('{"checkpoint_sha256": "%s"}' % adapters_mlx._sha256_file(adapters_mlx.checkpoint_path(tmp_path, "arm_a", 42)))
    with pytest.raises(FileNotFoundError):
        adapters_mlx.load_trained_model(tmp_path, "arm_a", 42, ledger_path=tmp_path / "absent.sqlite3", model_factory=lambda a: _NpArm())


def test_checkpoint_refused_without_completed_run_or_valid_sha(tmp_path: Any) -> None:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    _write_ckpt(tmp_path, "arm_c", 44, b"w")
    sub1 = tmp_path / "a"
    sub1.mkdir()
    db = _ledger_with_train_run(sub1, "arm_c", 44, None, complete=False)
    with pytest.raises(ValueError, match="exactly one"):
        adapters_mlx.load_trained_model(tmp_path, "arm_c", 44, ledger_path=db, model_factory=lambda a: _NpArm())
    sub2 = tmp_path / "b"
    sub2.mkdir()
    db2 = _ledger_with_train_run(sub2, "arm_c", 44, None)
    with pytest.raises(ValueError, match="checkpoint_sha256"):
        adapters_mlx.load_trained_model(tmp_path, "arm_c", 44, ledger_path=db2, model_factory=lambda a: _NpArm())


def test_load_for_planning_requires_seed(tmp_path: Any) -> None:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    with pytest.raises(TypeError):
        adapters_mlx.load_trained_models_for_planning(tmp_path, ledger_path=tmp_path / "x")  # type: ignore[call-arg]
