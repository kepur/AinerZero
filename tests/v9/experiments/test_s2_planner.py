"""CPU tests for S2 shared planner (NumPy): counter, flat CEM, hierarchical CEM.

Toy world: 2-D point mass on a walled grid maze. Dynamics are analytic;
``encode`` is identity; predictors are the known dynamics. No MLX.
Discrete cardinal actions ``{0:N, 1:S, 2:W, 3:E}`` drive CEM categoricals.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pytest

from ainerzero.v9.experiments.s2.fwd_counter import (
    ForwardBudgetExceeded,
    ForwardCounter,
)
from ainerzero.v9.experiments.s2.planner import (
    FlatCEMConfig,
    HierCEMConfig,
    flat_cem_plan,
    hierarchical_cem_plan,
    rollout_l1,
    squared_distance,
)

# ---------------------------------------------------------------------------
# Registered test floors / toy constants (not S2 training params)
# ---------------------------------------------------------------------------
NEAR_SUCCESS_FLOOR = 0.80
NEAR_MAX_STEPS = 10
FAR_MIN_SHORTEST = 40
S2_STRIDE = 8
# Shared decision budget for far-goal sanity; layer shares leave encode/subgoal headroom.
N_FWD_COMPARE = 5000
N_ACT = 4
CARDINAL = (
    np.array([0.0, -1.0]),  # 0 N
    np.array([0.0, 1.0]),  # 1 S
    np.array([-1.0, 0.0]),  # 2 W
    np.array([1.0, 0.0]),  # 3 E
)


# ---------------------------------------------------------------------------
# Toy maze
# ---------------------------------------------------------------------------

def _maze_mask() -> np.ndarray:
    """Walled straight corridor (row y=2 free for x=1..60) plus a detour dead-end.

    Far goals sit ≥ 40 steps along the corridor; walls force grid motion.
    """
    h, w = 5, 62
    g = np.ones((h, w), dtype=np.int8)
    g[2, 1 : w - 1] = 0
    # small alcove near the start (walled pocket; not needed for shortest paths)
    g[1, 2] = 0
    g[3, 2] = 0
    return g


MAZE = _maze_mask()


def _clip_move(pos: np.ndarray, delta: np.ndarray) -> np.ndarray:
    nxt = pos + delta
    x, y = int(round(float(nxt[0]))), int(round(float(nxt[1])))
    h, w = MAZE.shape
    if x < 0 or y < 0 or x >= w or y >= h or MAZE[y, x] == 1:
        return pos.copy()
    return np.array([float(x), float(y)], dtype=np.float64)


def identity_encode(obs: np.ndarray) -> np.ndarray:
    return np.asarray(obs, dtype=np.float64).reshape(-1).copy()


def predict_l1_analytic(z: np.ndarray, a: np.ndarray, dt: float) -> np.ndarray:
    """Discrete cardinal step from action index (float scalar / length-1)."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    idx = int(np.clip(np.round(a[0]), 0, N_ACT - 1))
    delta = CARDINAL[idx]
    steps = max(1, int(round(float(dt))))
    pos = np.asarray(z, dtype=np.float64).reshape(-1)[:2].copy()
    for _ in range(steps):
        pos = _clip_move(pos, delta)
    return pos


def encode_l2_identity(z1: np.ndarray) -> np.ndarray:
    return np.asarray(z1, dtype=np.float64).reshape(-1).copy()


def predict_l2_oracle(z2: np.ndarray, macro: np.ndarray, dt: float) -> np.ndarray:
    """Oracle macro: apply the same cardinal index for ``dt`` (≈ s₂) micro-steps."""
    steps = max(1, int(round(float(dt)))) if dt else S2_STRIDE
    pos = np.asarray(z2, dtype=np.float64).reshape(-1)[:2].copy()
    for _ in range(steps):
        pos = predict_l1_analytic(pos, macro, 1.0)
    return pos


def shortest_path_len(start: np.ndarray, goal: np.ndarray) -> int:
    s = (int(start[0]), int(start[1]))
    g = (int(goal[0]), int(goal[1]))
    if s == g:
        return 0
    q = deque([(s[0], s[1], 0)])
    seen = {s}
    while q:
        x, y, d = q.popleft()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            if (nx, ny) == g:
                return d + 1
            if (
                0 <= nx < MAZE.shape[1]
                and 0 <= ny < MAZE.shape[0]
                and MAZE[ny, nx] == 0
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                q.append((nx, ny, d + 1))
    return 10**9



NEAR_START = np.array([1.0, 2.0])
NEAR_GOAL = np.array([6.0, 2.0])  # 5 steps east along the corridor
FAR_START = np.array([1.0, 2.0])
FAR_GOAL = np.array([49.0, 2.0])  # 48 steps east; walls above/below
assert shortest_path_len(NEAR_START, NEAR_GOAL) <= NEAR_MAX_STEPS
assert shortest_path_len(FAR_START, FAR_GOAL) >= FAR_MIN_SHORTEST


def _wrap_all(counter: ForwardCounter):
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)
    p2 = counter.wrap("predict_l2", predict_l2_oracle)
    e2 = counter.wrap("encode_l2", encode_l2_identity)
    return enc, p1, p2, e2


def _mpc_flat(
    start: np.ndarray,
    goal: np.ndarray,
    *,
    cfg: FlatCEMConfig,
    n_fwd: int,
    seed: int,
    max_steps: int,
) -> bool:
    pos = start.astype(np.float64).copy()
    steps = 0
    while steps < max_steps:
        if shortest_path_len(pos, goal) == 0:
            return True
        counter = ForwardCounter(budget=n_fwd)
        enc, p1, _, _ = _wrap_all(counter)
        rng = np.random.default_rng(seed + steps * 17)
        try:
            result = flat_cem_plan(
                encode=enc,
                predict_l1=p1,
                obs=pos,
                goal_obs=goal,
                config=cfg,
                rng=rng,
                counter=counter,
            )
        except ForwardBudgetExceeded:
            return False
        for a in result.actions:
            pos = predict_l1_analytic(pos, a, 1.0)
            steps += 1
            if steps >= max_steps:
                break
    return shortest_path_len(pos, goal) == 0


def _mpc_hier(
    start: np.ndarray,
    goal: np.ndarray,
    *,
    cfg: HierCEMConfig,
    n_fwd: int,
    seed: int,
    max_steps: int,
) -> bool:
    pos = start.astype(np.float64).copy()
    steps = 0
    while steps < max_steps:
        if shortest_path_len(pos, goal) == 0:
            return True
        counter = ForwardCounter(budget=n_fwd)
        enc, p1, p2, e2 = _wrap_all(counter)
        rng = np.random.default_rng(seed + steps * 17)
        try:
            result = hierarchical_cem_plan(
                encode=enc,
                predict_l1=p1,
                predict_l2=p2,
                encode_l2=e2,
                obs=pos,
                goal_obs=goal,
                config=cfg,
                rng=rng,
                counter=counter,
                macro_dts=np.full(cfg.macro_horizon, float(cfg.s2)),
            )
        except ForwardBudgetExceeded:
            return False
        for a in result.actions:
            pos = predict_l1_analytic(pos, a, 1.0)
            steps += 1
            if steps >= max_steps:
                break
    return shortest_path_len(pos, goal) == 0


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def test_forward_count_closed_form_and_encoder_itemized():
    H, I, P = 5, 3, 4
    expected_encode = 2
    expected_predict = I * P * H
    expected_total = expected_encode + expected_predict

    counter = ForwardCounter(budget=expected_total)
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)
    cfg = FlatCEMConfig(
        horizon=H,
        n_iters=I,
        pop_size=P,
        elite_frac=0.5,
        action_dim=1,
        n_exec=1,
        n_categories=N_ACT,
    )
    rng = np.random.default_rng(0)
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=cfg,
        rng=rng,
        counter=counter,
    )
    snap = counter.snapshot()
    assert snap["by_name"]["encode"] == expected_encode
    assert snap["by_name"]["predict_l1"] == expected_predict
    assert snap["total"] == expected_total


def test_goal_embedding_cached_across_decisions_in_episode():
    """DESIGN-r2 §4: goal embedding is cached within an episode (charged exactly once)."""
    H, I, P = 3, 2, 4
    cfg = FlatCEMConfig(
        horizon=H,
        n_iters=I,
        pop_size=P,
        elite_frac=0.5,
        action_dim=1,
        n_exec=1,
        n_categories=N_ACT,
    )
    counter = ForwardCounter(budget=10_000)
    counter.begin_episode()
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)
    rng = np.random.default_rng(123)

    # Decision 1: first decision in episode -> encode obs (1) + encode goal (1) = 2
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=cfg,
        rng=rng,
        counter=counter,
    )
    snap1 = counter.snapshot()
    assert snap1["by_name"]["encode"] == 2
    assert snap1["by_name"]["predict_l1"] == I * P * H

    # Decision 2: goal embedding cached -> encode obs (1) + goal (0) = 1
    counter.reset()
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=NEAR_START + np.array([1.0, 0.0]),
        goal_obs=NEAR_GOAL,
        config=cfg,
        rng=rng,
        counter=counter,
    )
    snap2 = counter.snapshot()
    assert snap2["by_name"]["encode"] == 1
    assert snap2["by_name"]["predict_l1"] == I * P * H

    # Decision 3: goal embedding still cached -> encode obs (1) + goal (0) = 1
    counter.reset()
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=NEAR_START + np.array([2.0, 0.0]),
        goal_obs=NEAR_GOAL,
        config=cfg,
        rng=rng,
        counter=counter,
    )
    snap3 = counter.snapshot()
    assert snap3["by_name"]["encode"] == 1
    assert snap3["by_name"]["predict_l1"] == I * P * H

    # New episode begins -> cache cleared
    counter.begin_episode()
    counter.reset()
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=cfg,
        rng=rng,
        counter=counter,
    )
    snap4 = counter.snapshot()
    assert snap4["by_name"]["encode"] == 2
    assert snap4["by_name"]["predict_l1"] == I * P * H


def test_hierarchical_goal_embedding_cached_across_decisions_in_episode():
    """DESIGN-r2 §4: hierarchical CEM caches goal embedding across decisions within episode."""
    counter = ForwardCounter(budget=50_000)
    counter.begin_episode()
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)
    p2 = counter.wrap("predict_l2", predict_l2_oracle)
    e2 = counter.wrap("encode_l2", encode_l2_identity)
    hier = HierCEMConfig(
        macro_horizon=1,
        upper_iters=2,
        upper_pop=4,
        upper_elite_frac=0.5,
        macro_dim=1,
        s2=4,
        lower_iters=2,
        lower_pop=4,
        lower_elite_frac=0.5,
        action_dim=1,
        upper_budget=5_000,
        lower_budget=5_000,
        n_exec=1,
        n_categories=N_ACT,
        n_macro_categories=N_ACT,
    )
    rng = np.random.default_rng(123)

    # Decision 1: first decision in episode -> encode obs (1) + encode goal (1) = 2
    hierarchical_cem_plan(
        encode=enc,
        predict_l1=p1,
        predict_l2=p2,
        encode_l2=e2,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=hier,
        rng=rng,
        counter=counter,
        macro_dts=np.array([4.0]),
    )
    snap1 = counter.snapshot()
    assert snap1["by_name"]["encode"] == 2

    # Decision 2: goal embedding cached -> encode obs (1) + goal (0) = 1
    counter.reset()
    hierarchical_cem_plan(
        encode=enc,
        predict_l1=p1,
        predict_l2=p2,
        encode_l2=e2,
        obs=NEAR_START + np.array([1.0, 0.0]),
        goal_obs=NEAR_GOAL,
        config=hier,
        rng=rng,
        counter=counter,
        macro_dts=np.array([4.0]),
    )
    snap2 = counter.snapshot()
    assert snap2["by_name"]["encode"] == 1

    # Decision 3: goal embedding still cached -> encode obs (1) + goal (0) = 1
    counter.reset()
    hierarchical_cem_plan(
        encode=enc,
        predict_l1=p1,
        predict_l2=p2,
        encode_l2=e2,
        obs=NEAR_START + np.array([2.0, 0.0]),
        goal_obs=NEAR_GOAL,
        config=hier,
        rng=rng,
        counter=counter,
        macro_dts=np.array([4.0]),
    )
    snap3 = counter.snapshot()
    assert snap3["by_name"]["encode"] == 1

    # New episode begins -> cache cleared -> encode obs (1) + encode goal (1) = 2
    counter.begin_episode()
    counter.reset()
    hierarchical_cem_plan(
        encode=enc,
        predict_l1=p1,
        predict_l2=p2,
        encode_l2=e2,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=hier,
        rng=rng,
        counter=counter,
        macro_dts=np.array([4.0]),
    )
    snap4 = counter.snapshot()
    assert snap4["by_name"]["encode"] == 2



def test_goal_embedding_changed_goal_in_same_episode_raises():
    """DESIGN-r2 §4: Changing goal observation within the same episode must raise error."""
    counter = ForwardCounter(budget=10_000)
    counter.begin_episode()
    enc = counter.wrap("encode", identity_encode)

    # First goal observation in episode
    _ = counter.goal_embedding(NEAR_GOAL, enc)
    assert counter.by_name.get("encode", 0) == 1

    # Same goal observation -> cache hit, no error, no extra charge
    _ = counter.goal_embedding(NEAR_GOAL, enc)
    assert counter.by_name.get("encode", 0) == 1

    # Different goal observation without begin_episode -> must raise ValueError
    with pytest.raises(ValueError, match="goal observation changed within the same episode"):
        counter.goal_embedding(FAR_GOAL, enc)

    # After begin_episode -> new goal observation is permitted and charged
    counter.begin_episode()
    _ = counter.goal_embedding(FAR_GOAL, enc)
    assert counter.by_name.get("encode", 0) == 2


def test_budget_exceeded_by_one_raises():
    H, I, P = 4, 2, 3
    exact = 2 + I * P * H
    counter = ForwardCounter(budget=exact - 1)
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)
    cfg = FlatCEMConfig(
        horizon=H,
        n_iters=I,
        pop_size=P,
        elite_frac=0.5,
        action_dim=1,
        n_exec=1,
        n_categories=N_ACT,
    )
    with pytest.raises(ForwardBudgetExceeded):
        flat_cem_plan(
            encode=enc,
            predict_l1=p1,
            obs=NEAR_START,
            goal_obs=NEAR_GOAL,
            config=cfg,
            rng=np.random.default_rng(1),
            counter=counter,
        )


def test_anti_cheat_encoder_nested_predict_is_visible():
    counter = ForwardCounter(budget=100)
    wrapped_predict = counter.wrap("predict_l1", predict_l1_analytic)

    def sneaky_encode(obs: np.ndarray) -> np.ndarray:
        z = identity_encode(obs)
        _ = wrapped_predict(z, np.array([3.0]), 1.0)
        return z

    wrapped_encode = counter.wrap("encode", sneaky_encode)
    _ = wrapped_encode(NEAR_START)
    snap = counter.snapshot()
    assert snap["by_name"]["encode"] == 1
    assert snap["by_name"]["predict_l1"] == 1
    assert snap["total"] == 2


# ---------------------------------------------------------------------------
# Flat CEM
# ---------------------------------------------------------------------------

def test_flat_near_goal_success_rate():
    start, goal = NEAR_START, NEAR_GOAL
    assert 1 <= shortest_path_len(start, goal) <= NEAR_MAX_STEPS
    # Execute the planned horizon open-loop (n_exec=H); still CEM-planned.
    cfg = FlatCEMConfig(
        horizon=8,
        n_iters=8,
        pop_size=64,
        elite_frac=0.3,
        action_dim=1,
        n_exec=8,
        n_categories=N_ACT,
    )
    n_fwd = 2 + cfg.n_iters * cfg.pop_size * cfg.horizon
    successes = 0
    trials = 20
    for t in range(trials):
        ok = _mpc_flat(
            start, goal, cfg=cfg, n_fwd=n_fwd, seed=1000 + t, max_steps=NEAR_MAX_STEPS
        )
        successes += int(ok)
    rate = successes / trials
    assert rate >= NEAR_SUCCESS_FLOOR, f"near-goal success {rate:.2f} < {NEAR_SUCCESS_FLOOR}"


def test_flat_reproducible_with_explicit_rng():
    cfg = FlatCEMConfig(
        horizon=5,
        n_iters=4,
        pop_size=16,
        elite_frac=0.25,
        action_dim=1,
        n_exec=3,
        n_categories=N_ACT,
    )
    n_fwd = 2 + cfg.n_iters * cfg.pop_size * cfg.horizon

    def once(seed: int):
        counter = ForwardCounter(budget=n_fwd)
        enc, p1, _, _ = _wrap_all(counter)
        rng = np.random.default_rng(seed)
        result = flat_cem_plan(
            encode=enc,
            predict_l1=p1,
            obs=NEAR_START,
            goal_obs=np.array([3.0, 2.0]),
            config=cfg,
            rng=rng,
            counter=counter,
        )
        return result.actions.copy(), result.info["full_sequence"].copy(), counter.snapshot()

    a1, s1, c1 = once(42)
    a2, s2, c2 = once(42)
    assert np.array_equal(a1, a2)
    assert np.array_equal(s1, s2)
    assert c1 == c2


# ---------------------------------------------------------------------------
# Hierarchical CEM
# ---------------------------------------------------------------------------

def test_hierarchical_lower_cost_goes_through_e2():
    counter = ForwardCounter(budget=50_000)
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_analytic)

    def zero_e2(z1: np.ndarray) -> np.ndarray:
        z = np.asarray(z1, dtype=np.float64).reshape(-1)
        return np.zeros_like(z)

    e2 = counter.wrap("encode_l2", zero_e2)
    cfg_s2 = 4
    rng = np.random.default_rng(7)
    z1_0 = enc(NEAR_START)
    z2_subgoal = np.array([3.0, 3.0])
    costs = []
    for _ in range(12):
        actions = rng.integers(0, N_ACT, size=(cfg_s2, 1)).astype(np.float64)
        z1_T = rollout_l1(p1, z1_0, actions)
        z2_pred = e2(z1_T)
        costs.append(squared_distance(z2_pred, z2_subgoal))
    assert np.allclose(costs, costs[0]), costs
    assert costs[0] == pytest.approx(squared_distance(np.zeros(2), z2_subgoal))

    counter2 = ForwardCounter(budget=50_000)
    enc2, p1b, _, e2_real = _wrap_all(counter2)
    z1_0b = enc2(NEAR_START)
    costs_real = []
    rng2 = np.random.default_rng(7)
    for _ in range(12):
        actions = rng2.integers(0, N_ACT, size=(cfg_s2, 1)).astype(np.float64)
        z1_T = rollout_l1(p1b, z1_0b, actions)
        costs_real.append(squared_distance(e2_real(z1_T), z2_subgoal))
    assert np.std(costs_real) > 1e-6

    # Planner-level: lower CEM must call encode_l2 once per candidate (DESIGN §4).
    # Bypassing E₂ drops encode_l2 charges to the initial z2_0 / z2_goal only → red.
    counter3 = ForwardCounter(budget=50_000)
    enc3 = counter3.wrap("encode", identity_encode)
    p1c = counter3.wrap("predict_l1", predict_l1_analytic)
    p2c = counter3.wrap("predict_l2", predict_l2_oracle)
    e2z = counter3.wrap("encode_l2", zero_e2)
    hier = HierCEMConfig(
        macro_horizon=1,
        upper_iters=2,
        upper_pop=8,
        upper_elite_frac=0.5,
        macro_dim=1,
        s2=4,
        lower_iters=3,
        lower_pop=16,
        lower_elite_frac=0.5,
        action_dim=1,
        upper_budget=5_000,
        lower_budget=5_000,
        n_exec=1,
        n_categories=N_ACT,
        n_macro_categories=N_ACT,
    )
    result = hierarchical_cem_plan(
        encode=enc3,
        predict_l1=p1c,
        predict_l2=p2c,
        encode_l2=e2z,
        obs=NEAR_START,
        goal_obs=NEAR_GOAL,
        config=hier,
        rng=np.random.default_rng(11),
        counter=counter3,
        macro_dts=np.array([4.0]),
    )
    elite = result.info["lower_elite_costs"]
    assert elite, "expected lower elite costs"
    assert np.allclose(elite, elite[0]), elite
    e2_calls = counter3.by_name.get("encode_l2", 0)
    # z2_0 + z2_goal + ≥ one full lower population of encode_l2 evaluations
    assert e2_calls >= 2 + hier.lower_pop, (
        f"lower loop must evaluate E₂; encode_l2 calls={e2_calls}"
    )


def test_hierarchical_far_goal_vs_flat_same_budget():
    """Oracle-macro hierarchical vs flat under identical N_fwd (sanity, not science)."""
    start, goal = FAR_START, FAR_GOAL
    dist = shortest_path_len(start, goal)
    assert dist >= FAR_MIN_SHORTEST, f"far goal shortest={dist}, need >= {FAR_MIN_SHORTEST}"

    # Flat: short horizon, weak CEM → slow progress under the same N_fwd.
    flat_cfg = FlatCEMConfig(
        horizon=6,
        n_iters=2,
        pop_size=16,
        elite_frac=0.25,
        action_dim=1,
        n_exec=1,
        n_categories=N_ACT,
    )
    assert 2 + flat_cfg.n_iters * flat_cfg.pop_size * flat_cfg.horizon <= N_FWD_COMPARE

    # Hierarchical: oracle macros of length s2 cover ground faster.
    # Layer shares leave headroom for encode / encode_l2 / subgoal predict.
    # Upper horizon 1: each decision picks the next oracle macro toward the goal
    # (avoids long-horizon first-macro detours under terminal cost).
    hier_cfg = HierCEMConfig(
        macro_horizon=1,
        upper_iters=6,
        upper_pop=32,
        upper_elite_frac=0.5,
        macro_dim=1,
        s2=S2_STRIDE,
        lower_iters=6,
        lower_pop=32,
        lower_elite_frac=0.3,
        action_dim=1,
        upper_budget=800,
        lower_budget=2200,
        n_exec=S2_STRIDE,
        n_categories=N_ACT,
        n_macro_categories=N_ACT,
    )

    trials = 10
    # Tight step cap: hier macros (×s2) can finish; weak flat often cannot.
    max_steps = 56
    flat_ok = 0
    hier_ok = 0
    for t in range(trials):
        flat_ok += int(
            _mpc_flat(
                start,
                goal,
                cfg=flat_cfg,
                n_fwd=N_FWD_COMPARE,
                seed=2000 + t,
                max_steps=max_steps,
            )
        )
        hier_ok += int(
            _mpc_hier(
                start,
                goal,
                cfg=hier_cfg,
                n_fwd=N_FWD_COMPARE,
                seed=3000 + t,
                max_steps=max_steps,
            )
        )
    flat_rate = flat_ok / trials
    hier_rate = hier_ok / trials
    assert hier_rate > flat_rate, (
        f"hierarchical sanity failed: hier={hier_rate:.2f} flat={flat_rate:.2f} "
        f"(not a scientific claim; do not retune to pass)"
    )


def test_no_mlx_import_in_s2_modules():
    import ainerzero.v9.experiments.s2.fwd_counter as fc
    import ainerzero.v9.experiments.s2.planner as pl
    import ainerzero.v9.experiments.s2 as s2pkg

    for mod in (fc, pl, s2pkg):
        src = open(mod.__file__, encoding="utf-8").read()
        for line in src.splitlines():
            s = line.strip()
            if s.startswith("import mlx") or s.startswith("from mlx"):
                pytest.fail(f"MLX import in {mod.__file__}: {s}")


def test_flat_cem_cost_fn_forward_counter_and_custom_cost() -> None:
    """Verify flat_cem_plan supports cost_fn hook and counts neural forward calls in ForwardCounter."""
    start = np.array([2.0, 2.0], dtype=np.float64)
    goal = np.array([10.0, 2.0], dtype=np.float64)

    cfg = FlatCEMConfig(
        horizon=6,
        n_iters=3,
        pop_size=10,
        elite_frac=0.2,
        action_dim=1,
        n_categories=4,
    )
    rng = np.random.default_rng(42)
    counter = ForwardCounter(budget=1000)

    # Mock neural decoder function (e.g. for Arm A observation-space planning)
    def mocked_decoder(z: np.ndarray) -> np.ndarray:
        return z * 1.5

    wrapped_decoder = counter.wrap("decode", mocked_decoder)

    def custom_cost_fn(z_T: np.ndarray, goal_obs: np.ndarray) -> float:
        # Calls wrapped decoder: should charge 1 to 'decode'
        dec = wrapped_decoder(z_T)
        return float(np.sum((dec - goal_obs) ** 2))

    res = flat_cem_plan(
        encode=identity_encode,
        predict_l1=predict_l1_analytic,
        obs=start,
        goal_obs=goal,
        config=cfg,
        rng=rng,
        counter=counter,
        cost_fn=custom_cost_fn,
    )

    expected_evals = cfg.n_iters * cfg.pop_size
    assert counter.by_name.get("decode", 0) == expected_evals, (
        f"Expected {expected_evals} decode calls in ForwardCounter, got {counter.by_name.get('decode', 0)}"
    )
    assert res.actions.shape[0] == cfg.n_exec

    # Verify that a budget limit is enforced on cost_fn calls
    counter_tight = ForwardCounter(budget=5)
    wrapped_tight = counter_tight.wrap("decode", mocked_decoder)
    with pytest.raises(ForwardBudgetExceeded):
        flat_cem_plan(
            encode=identity_encode,
            predict_l1=predict_l1_analytic,
            obs=start,
            goal_obs=goal,
            config=cfg,
            rng=np.random.default_rng(42),
            counter=counter_tight,
            cost_fn=lambda z, g: float(np.sum(wrapped_tight(z) - g)),
        )
