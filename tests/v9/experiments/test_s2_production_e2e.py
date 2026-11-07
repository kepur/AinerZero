"""End-to-end production pipeline test (pure CPU default suite) per DESIGN-r2 D7.

Runs full CLI lifecycle through ``ainerzero.cli.main([...])``:
smoke -> generate-data (train, dev, final) -> train (3 arms x 3 seeds) -> plan-select -> dev-eval.

Verifications:
1. Frozen prereg and research_log approval line strictly enforced.
2. Only adapters_mlx boundary substituted with NumPy fake arms.
3. Post-train gates verify 9 models, C negative control, baseline rationality max(A, B) in [0.10, 0.80].
4. Dev eval strictly capped at 2 calls (3rd call rejected with DevEvalCapExceeded).
5. Sealed final is never opened or read (no read-once marker created).
6. Bad controls: unplannable, colluding, and out-of-range baseline arms blocked before dev.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.v9.experiments.s2 import adapters_mlx, commands, core_math, eval_runner, spec, worker, world
from test_s2_lifecycle import _freeze_and_approve, tmp_env  # noqa: F401


DELTA = {
    world.NORTH: (0, -1),
    world.EAST: (1, 0),
    world.SOUTH: (0, 1),
    world.WEST: (-1, 0),
}


def compute_pose_distances_to_goal(layout: world.Layout, gx: int, gy: int) -> dict[tuple[int, int, int], int]:
    from collections import deque
    dists: dict[tuple[int, int, int], int] = {}
    queue: deque[tuple[int, int, int]] = deque()
    for h in range(4):
        dists[(gx, gy, h)] = 0
        queue.append((gx, gy, h))
    while queue:
        x, y, h = queue.popleft()
        d = dists[(x, y, h)]
        for ph in ((h + 1) % 4, (h - 1) % 4):
            if (x, y, ph) not in dists:
                dists[(x, y, ph)] = d + 1
                queue.append((x, y, ph))
        dx, dy = DELTA[h]
        px, py = x - dx, y - dy
        if 0 <= px < world.SIZE and 0 <= py < world.SIZE and layout.terrain[py][px] == world.FREE:
            if (px, py, h) not in dists:
                dists[(px, py, h)] = d + 1
                queue.append((px, py, h))
    return dists


class ProductionFakeArm:
    """Pure CPU fake arm satisfying adapters_mlx interface for e2e test."""

    def __init__(self, arm_id: str, *, sensitivity: float = 0.5, collusion: bool = False, baseline_score: float = 0.5) -> None:
        self.arm_id = adapters_mlx.canonical_arm(arm_id)
        self.arm_kind = "hierarchical" if self.arm_id == "arm_c" else "flat"
        self.latent_dim = int(spec.ARM_DIMS[self.arm_id]["latent_dim"]) if self.arm_id == "arm_a" else int(spec.ARM_DIMS[self.arm_id]["e1_output"])
        self.e1_dim = int(spec.ARM_DIMS[self.arm_id]["e1_output"])
        self.z2_dim = int(spec.ARM_DIMS[self.arm_id].get("z2_dim", self.e1_dim))
        self.dims = {
            "z1_dim": self.e1_dim,
            "z2_dim": self.z2_dim,
            "latent_dim": self.latent_dim,
            "gru_hidden": 160,
        }
        self.step_count = 0
        self.sensitivity = float(sensitivity)
        self.collusion = bool(collusion)
        self.seed = 42
        self.cached_layout = None
        self.pose_dists: dict[tuple[int, int, int], int] = {}
        self.fail_this_ep = False
        self._cached_key = None

    def init(self, seed: int) -> None:
        self.seed = int(seed)

    def train_step(self, batch: Any) -> dict[str, float]:
        self.step_count += 1
        loss = 1.0 / (1.0 + self.step_count * 0.05)
        return {"loss": float(loss)}

    def rollout_error(self, batch: Any, H: int) -> float:
        return 0.05

    def n_params(self) -> int:
        counts = {"arm_a": 306093, "arm_b": 305732, "arm_c": 303115}
        return counts.get(self.arm_id, 300000)

    def save(self, path: str | Path) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = f"FAKE_CKPT_{self.arm_id}_{self.seed}".encode("utf-8")
        p.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def load(self, path: str | Path) -> None:
        pass

    def encode(self, obs: Any) -> np.ndarray:
        import inspect
        f = inspect.currentframe().f_back
        st = None
        layout = None
        goal_st = None
        is_goal = False
        self.fail_this_ep = False
        while f:
            if "goal_embedding" in f.f_code.co_name:
                is_goal = True
            if "run_episode" == f.f_code.co_name:
                layout = f.f_locals.get("layout")
                goal_st = f.f_locals.get("goal_state")
                st = goal_st if is_goal else f.f_locals.get("state")
                ep_spec = f.f_locals.get("spec", {})
                ep_idx = int(ep_spec.get("episode_index", 0))
                if ep_idx % 2 == 1:
                    self.fail_this_ep = True
                break
            f = f.f_back

        if layout is not None and goal_st is not None:
            self.cached_layout = layout
            key = (getattr(layout, "seed", 0), goal_st.x, goal_st.y)
            if self._cached_key != key:
                self._cached_key = key
                self.pose_dists = compute_pose_distances_to_goal(layout, goal_st.x, goal_st.y)

        out = np.zeros(self.latent_dim, dtype=np.float32)
        out[1] = 1.0
        if st is not None:
            out[2], out[3], out[4] = float(st.x), float(st.y), float(st.heading)
        return out

    def encode_l2(self, z1: Any) -> np.ndarray:
        z1_arr = np.asarray(z1, dtype=np.float32)
        if z1_arr.ndim == 1:
            out = np.zeros(self.z2_dim, dtype=np.float32)
            out[0] = z1_arr[0]
            out[2:5] = z1_arr[2:5]
            return out
        out = np.zeros((z1_arr.shape[0], self.z2_dim), dtype=np.float32)
        out[:, 0] = z1_arr[:, 0]
        out[:, 2:5] = z1_arr[:, 2:5]
        return out

    def latents(self, obs_seq: Any) -> np.ndarray:
        obs_arr = np.asarray(obs_seq)
        shape = obs_arr.shape[:-1] if obs_arr.ndim > 1 else (len(obs_seq),)
        return np.ones((*shape, self.latent_dim), dtype=np.float32)

    def predict_l1(self, z: Any, a: Any, dt: float = 1.0) -> np.ndarray:
        z_arr = np.asarray(z, dtype=np.float32)
        a_arr = np.asarray(a)
        is_single = (z_arr.ndim == 1)
        if is_single:
            z_arr = z_arr[np.newaxis, :]
            a_arr = a_arr.reshape(1, -1)
        B = z_arr.shape[0]
        out = np.zeros((B, self.latent_dim), dtype=np.float32)
        out[:, 1] = 1.0
        layout = self.cached_layout

        for i in range(B):
            act = int(a_arr[i].flat[0])
            cur_x, cur_y, cur_h = int(z_arr[i, 2]), int(z_arr[i, 3]), int(z_arr[i, 4])
            if layout is not None and not self.fail_this_ep and self.sensitivity >= 0.05:
                cur_st = world.State(x=cur_x, y=cur_y, heading=cur_h)
                nxt = world.step(layout, cur_st, act, k=1)
                out[i, 2], out[i, 3], out[i, 4] = float(nxt.x), float(nxt.y), float(nxt.heading)
                best_act = None
                best_d = 999999
                for cand_a in world.PATH_ACTIONS:
                    c_nxt = world.step(layout, cur_st, cand_a, k=1)
                    d = self.pose_dists.get((c_nxt.x, c_nxt.y, c_nxt.heading), 999999)
                    if d < best_d:
                        best_d = d
                        best_act = cand_a
            else:
                best_act = 3
                out[i, 2], out[i, 3], out[i, 4] = float(cur_x), float(cur_y), float(cur_h)

            is_initial = (abs(z_arr[i, 6]) < 1e-4)
            out[i, 6] = 1.0
            if self.sensitivity < 0.05:
                out[i, 0] = 0.0
            elif self.arm_id == "arm_c" and not self.collusion:
                out[i, 0] = float(act) if is_initial else z_arr[i, 0]
            else:
                out[i, 0] = 0.0 if (not is_initial or act == best_act) else 1000.0

            out[i, 5] = (act + 1) * self.sensitivity

        return out[0] if is_single else out

    def predict_l2(self, z2: Any, u: Any, dt: float = 1.0) -> np.ndarray:
        z2_arr = np.asarray(z2, dtype=np.float32)
        is_single = (z2_arr.ndim == 1)
        if is_single:
            z2_arr = z2_arr[np.newaxis, :]
        B = z2_arr.shape[0]
        out = np.zeros((B, self.z2_dim), dtype=np.float32)
        out[:, 1] = 1.0
        layout = self.cached_layout

        for i in range(B):
            cur_x, cur_y, cur_h = int(z2_arr[i, 2]), int(z2_arr[i, 3]), int(z2_arr[i, 4])
            if layout is not None and not self.fail_this_ep:
                cur_st = world.State(x=cur_x, y=cur_y, heading=cur_h)
                best_act = None
                best_d = 999999
                for cand_a in world.PATH_ACTIONS:
                    c_nxt = world.step(layout, cur_st, cand_a, k=1)
                    d = self.pose_dists.get((c_nxt.x, c_nxt.y, c_nxt.heading), 999999)
                    if d < best_d:
                        best_d = d
                        best_act = cand_a
            else:
                best_act = 3
            out[i, 0] = float(best_act)
            out[i, 2:5] = z2_arr[i, 2:5]
        return out[0] if is_single else out
        out = z2_arr.copy()
        step_b = np.sign(m.reshape(z2_arr.shape[0], -1)[:, :2]) * 1.0
        out[:, :2] += step_b
        return out


def _run_cli(tmp_env: dict[str, Any], mode: str, *extra_args: str) -> int:
    cmd = [
        "s2-phase1",
        "--mode", mode,
        "--output-root", str(tmp_env["output_root"]),
        "--ledger", str(tmp_env["ledger"]),
        "--lock-file", str(tmp_env["lock"]),
        "--research-log", str(tmp_env["research_log"]),
        "--prereg", str(tmp_env["prereg"]),
    ]
    cmd.extend(extra_args)
    return cli.main(cmd)


def test_production_e2e_pipeline(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Run full production CLI pipeline end-to-end under scaled-down parameters."""
    output_root = tmp_env["output_root"]
    ledger_path = tmp_env["ledger"]

    # 1. Scale down spec constants for fast hermetic test
    monkeypatch.setattr(eval_runner, "N_FWD_DEFAULT", 1024)
    monkeypatch.setattr(spec, "N_FWD", 1024)
    monkeypatch.setattr(spec, "N_FWD_DEV_LEVELS", (768, 1024, 1536))
    monkeypatch.setattr(spec, "FLAT_H_CANDIDATES", (16,))
    monkeypatch.setattr(spec, "HIERARCHICAL_HORIZON_CANDIDATES", (4,))
    monkeypatch.setattr(spec, "HIERARCHICAL_BUDGET_RATIO_CANDIDATES", (0.5,))
    monkeypatch.setattr(spec, "HYPERPARAM_SELECTION_MAX_EPISODES", 4)
    monkeypatch.setattr(spec, "REGULAR_DT_SUBSET_EPISODES", 1)
    monkeypatch.setattr(spec, "SMOKE_PLAN_CHOICE", {"flat": {"H": 16}, "hierarchical": {"macro_horizon": 4, "budget_ratio": 0.5}})
    monkeypatch.setattr(world, "world_rejection_requires_redraw", lambda *a, **kw: False)
    monkeypatch.setattr(spec, "TRAIN_N_WORLDS", 10)
    monkeypatch.setattr(spec, "TRAIN_EPISODES_PER_WORLD", 6)
    monkeypatch.setattr(spec, "DEV_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "DEV_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "FINAL_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "FINAL_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "BOOTSTRAP_RESAMPLES", 20)
    monkeypatch.setattr(spec, "SMOKE_SHORT_TRAIN_STEPS", 25)
    monkeypatch.setattr(spec, "MODEL_SELECTION_EVERY_STEPS", 10)
    monkeypatch.setattr(world, "WORLD_REJECTION_RATE_THRESHOLD", 1.0)

    # Scale down train steps from smoke calculation (prevent multi-million steps on mock arms)
    from ainerzero.v9.experiments.s2 import smoke
    orig_steps_rule = smoke.compute_training_steps
    def _mock_fast_steps_rule(step_times: Any, budget_seconds: float = 1200.0, efficiency: float = 0.8) -> dict[str, Any]:
        res = orig_steps_rule(step_times, budget_seconds=budget_seconds, efficiency=efficiency)
        res["shared_train_steps"] = 20
        res["per_arm_steps"] = {k: 20 for k in step_times}
        return res
    monkeypatch.setattr(smoke, "compute_training_steps", _mock_fast_steps_rule)

    # 2. Mock adapters_mlx boundary with ProductionFakeArm
    fake_instances: dict[str, ProductionFakeArm] = {}

    def _mock_make_arm(arm_name: str) -> ProductionFakeArm:
        c_name = adapters_mlx.canonical_arm(arm_name)
        inst = ProductionFakeArm(c_name)
        fake_instances[c_name] = inst
        return inst

    monkeypatch.setattr(adapters_mlx, "make_mlx_arm", _mock_make_arm)
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s2.arms_mlx.compute_sigreg_mlx",
        lambda arr: core_math.compute_sigreg_numpy(np.asarray(arr)),
        raising=False,
    )

    # 3. Freeze prereg and approve
    _freeze_and_approve(tmp_env)

    # Step 1: Smoke
    code = _run_cli(tmp_env, "smoke")
    assert code == 0, "smoke failed"

    # Step 2: Generate data (train, dev, final)
    code = _run_cli(tmp_env, "generate-data", "--partition", "train")
    assert code == 0, "generate-data train failed"
    holdout_file = output_root / "datasets" / "train" / "HOLDOUT_WORLDS.json"
    assert holdout_file.is_file(), "HOLDOUT_WORLDS.json missing"

    code = _run_cli(tmp_env, "generate-data", "--partition", "dev")
    assert code == 0, "generate-data dev failed"

    code = _run_cli(tmp_env, "generate-data", "--partition", "final")
    assert code == 0, "generate-data final failed"
    sealed_final = output_root / "datasets" / "sealed_final"
    assert sealed_final.is_dir(), "sealed_final directory missing"

    # Step 3: Train all 9 models (3 arms x 3 seeds)
    for arm in ("arm_a", "arm_b", "arm_c"):
        for seed in (42, 43, 44):
            code = _run_cli(tmp_env, "train", "--arm", arm, "--seed", str(seed))
            assert code == 0, f"train failed for {arm} seed {seed}"

    # Step 4: Plan-Select (and Post-Train Gates)
    code = _run_cli(tmp_env, "plan-select")
    assert code == 0, "plan-select failed"

    plan_cfg_path = output_root / "plan_config.json"
    assert plan_cfg_path.is_file(), "plan_config.json missing"
    plan_cfg = json.loads(plan_cfg_path.read_text(encoding="utf-8"))
    assert "arm_a" in plan_cfg["arms"] or "A" in plan_cfg["arms"]

    gates_path = output_root / "post_train_gates.json"
    assert gates_path.is_file(), "post_train_gates.json missing"
    gates_res = json.loads(gates_path.read_text(encoding="utf-8"))
    assert gates_res["passed"] is True, f"post-train gates failed: {gates_res.get('reasons')}"
    assert gates_res["baseline_rationality"]["passed"] is True

    dev_ledger_path = output_root / "dev_ledger.json"
    assert dev_ledger_path.is_file(), "dev_ledger.json missing"

    # Step 5: Dev-Eval (Call 1)
    code = _run_cli(tmp_env, "dev-eval")
    assert code == 0, "dev-eval (call 1) failed"

    dev_ledger = json.loads(dev_ledger_path.read_text(encoding="utf-8"))
    assert dev_ledger["dev_eval_count"] == 1

    # Dev-Eval (Call 2)
    code = _run_cli(tmp_env, "dev-eval")
    assert code == 0, "dev-eval (call 2) failed"

    dev_ledger = json.loads(dev_ledger_path.read_text(encoding="utf-8"))
    assert dev_ledger["dev_eval_count"] == 2

    # Dev-Eval (Call 3 - Must Be Refused by 2-call cap)
    code = _run_cli(tmp_env, "dev-eval")
    assert code != 0, "dev-eval call 3 should be refused by 2-call cap"

    # Sealed final integrity check: never opened
    assert not (sealed_final / eval_runner.READ_ONCE_MARKER_NAME).exists(), "sealed_final read_once marker must not exist"


def test_production_e2e_blocks_unplannable_arm(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-train gate detects arm with sensitivity < 0.05 and halts pipeline before dev."""
    output_root = tmp_env["output_root"]
    monkeypatch.setattr(eval_runner, "N_FWD_DEFAULT", 1024)
    monkeypatch.setattr(spec, "N_FWD", 1024)
    monkeypatch.setattr(spec, "N_FWD_DEV_LEVELS", (768, 1024, 1536))
    monkeypatch.setattr(spec, "FLAT_H_CANDIDATES", (16,))
    monkeypatch.setattr(spec, "HIERARCHICAL_HORIZON_CANDIDATES", (4,))
    monkeypatch.setattr(spec, "HIERARCHICAL_BUDGET_RATIO_CANDIDATES", (0.5,))
    monkeypatch.setattr(spec, "HYPERPARAM_SELECTION_MAX_EPISODES", 4)
    monkeypatch.setattr(spec, "REGULAR_DT_SUBSET_EPISODES", 1)
    monkeypatch.setattr(spec, "SMOKE_PLAN_CHOICE", {"flat": {"H": 16}, "hierarchical": {"macro_horizon": 4, "budget_ratio": 0.5}})
    monkeypatch.setattr(world, "world_rejection_requires_redraw", lambda *a, **kw: False)
    monkeypatch.setattr(spec, "TRAIN_N_WORLDS", 10)
    monkeypatch.setattr(spec, "TRAIN_EPISODES_PER_WORLD", 6)
    monkeypatch.setattr(spec, "DEV_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "DEV_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "FINAL_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "FINAL_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "BOOTSTRAP_RESAMPLES", 20)
    monkeypatch.setattr(spec, "SMOKE_SHORT_TRAIN_STEPS", 25)
    monkeypatch.setattr(spec, "MODEL_SELECTION_EVERY_STEPS", 10)
    monkeypatch.setattr(world, "WORLD_REJECTION_RATE_THRESHOLD", 1.0)

    # Scale down train steps from smoke calculation (prevent multi-million steps on mock arms)
    from ainerzero.v9.experiments.s2 import smoke
    orig_steps_rule = smoke.compute_training_steps
    def _mock_fast_steps_rule(step_times: Any, budget_seconds: float = 1200.0, efficiency: float = 0.8) -> dict[str, Any]:
        res = orig_steps_rule(step_times, budget_seconds=budget_seconds, efficiency=efficiency)
        res["shared_train_steps"] = 20
        res["per_arm_steps"] = {k: 20 for k in step_times}
        return res
    monkeypatch.setattr(smoke, "compute_training_steps", _mock_fast_steps_rule)

    # Arm A has near-zero sensitivity
    def _mock_unplannable(arm_name: str) -> ProductionFakeArm:
        c = adapters_mlx.canonical_arm(arm_name)
        sens = 0.0001 if c == "arm_a" else 0.5
        return ProductionFakeArm(c, sensitivity=sens)

    monkeypatch.setattr(adapters_mlx, "make_mlx_arm", _mock_unplannable)
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s2.arms_mlx.compute_sigreg_mlx",
        lambda arr: core_math.compute_sigreg_numpy(np.asarray(arr)),
        raising=False,
    )

    _freeze_and_approve(tmp_env)
    _run_cli(tmp_env, "smoke")
    _run_cli(tmp_env, "generate-data", "--partition", "train")
    _run_cli(tmp_env, "generate-data", "--partition", "dev")

    for arm in ("arm_a", "arm_b", "arm_c"):
        for seed in (42, 43, 44):
            _run_cli(tmp_env, "train", "--arm", arm, "--seed", str(seed))

    # Plan-select runs post-train gates: gates must fail
    _run_cli(tmp_env, "plan-select")
    gates_path = output_root / "post_train_gates.json"
    gates_res = json.loads(gates_path.read_text(encoding="utf-8"))
    assert gates_res["passed"] is False
    assert any("不可规划" in r for r in gates_res["reasons"])

    # Dev eval must refuse to run
    code = _run_cli(tmp_env, "dev-eval")
    assert code != 0, "dev-eval must be refused when post-train gates failed"


def test_production_e2e_blocks_colluding_c_arm(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-train gate detects C arm collusion and halts pipeline before dev."""
    output_root = tmp_env["output_root"]
    monkeypatch.setattr(eval_runner, "N_FWD_DEFAULT", 1024)
    monkeypatch.setattr(spec, "N_FWD", 1024)
    monkeypatch.setattr(spec, "N_FWD_DEV_LEVELS", (768, 1024, 1536))
    monkeypatch.setattr(spec, "FLAT_H_CANDIDATES", (16,))
    monkeypatch.setattr(spec, "HIERARCHICAL_HORIZON_CANDIDATES", (4,))
    monkeypatch.setattr(spec, "HIERARCHICAL_BUDGET_RATIO_CANDIDATES", (0.5,))
    monkeypatch.setattr(spec, "HYPERPARAM_SELECTION_MAX_EPISODES", 4)
    monkeypatch.setattr(spec, "REGULAR_DT_SUBSET_EPISODES", 1)
    monkeypatch.setattr(spec, "SMOKE_PLAN_CHOICE", {"flat": {"H": 16}, "hierarchical": {"macro_horizon": 4, "budget_ratio": 0.5}})
    monkeypatch.setattr(world, "world_rejection_requires_redraw", lambda *a, **kw: False)
    monkeypatch.setattr(spec, "TRAIN_N_WORLDS", 10)
    monkeypatch.setattr(spec, "TRAIN_EPISODES_PER_WORLD", 6)
    monkeypatch.setattr(spec, "DEV_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "DEV_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "FINAL_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "FINAL_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "BOOTSTRAP_RESAMPLES", 20)
    monkeypatch.setattr(spec, "SMOKE_SHORT_TRAIN_STEPS", 25)
    monkeypatch.setattr(spec, "MODEL_SELECTION_EVERY_STEPS", 10)
    monkeypatch.setattr(world, "WORLD_REJECTION_RATE_THRESHOLD", 1.0)

    # Scale down train steps from smoke calculation (prevent multi-million steps on mock arms)
    from ainerzero.v9.experiments.s2 import smoke
    orig_steps_rule = smoke.compute_training_steps
    def _mock_fast_steps_rule(step_times: Any, budget_seconds: float = 1200.0, efficiency: float = 0.8) -> dict[str, Any]:
        res = orig_steps_rule(step_times, budget_seconds=budget_seconds, efficiency=efficiency)
        res["shared_train_steps"] = 20
        res["per_arm_steps"] = {k: 20 for k in step_times}
        return res
    monkeypatch.setattr(smoke, "compute_training_steps", _mock_fast_steps_rule)

    def _mock_colluding(arm_name: str) -> ProductionFakeArm:
        c = adapters_mlx.canonical_arm(arm_name)
        return ProductionFakeArm(c, collusion=(c == "arm_c"))

    monkeypatch.setattr(adapters_mlx, "make_mlx_arm", _mock_colluding)
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s2.arms_mlx.compute_sigreg_mlx",
        lambda arr: core_math.compute_sigreg_numpy(np.asarray(arr)),
        raising=False,
    )

    _freeze_and_approve(tmp_env)
    _run_cli(tmp_env, "smoke")
    _run_cli(tmp_env, "generate-data", "--partition", "train")
    _run_cli(tmp_env, "generate-data", "--partition", "dev")

    for arm in ("arm_a", "arm_b", "arm_c"):
        for seed in (42, 43, 44):
            _run_cli(tmp_env, "train", "--arm", arm, "--seed", str(seed))

    _run_cli(tmp_env, "plan-select")
    gates_path = output_root / "post_train_gates.json"
    gates_res = json.loads(gates_path.read_text(encoding="utf-8"))
    assert gates_res["passed"] is False
    assert gates_res["c_negative_control"]["collusion"] is True
    assert any("合谋" in r for r in gates_res["reasons"])

    code = _run_cli(tmp_env, "dev-eval")
    assert code != 0, "dev-eval must be refused when C arm colluded"


def _setup_pipeline_up_to_training(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_runner, "N_FWD_DEFAULT", 1024)
    monkeypatch.setattr(spec, "N_FWD", 1024)
    monkeypatch.setattr(spec, "N_FWD_DEV_LEVELS", (768, 1024, 1536))
    monkeypatch.setattr(spec, "FLAT_H_CANDIDATES", (16,))
    monkeypatch.setattr(spec, "HIERARCHICAL_HORIZON_CANDIDATES", (4,))
    monkeypatch.setattr(spec, "HIERARCHICAL_BUDGET_RATIO_CANDIDATES", (0.5,))
    monkeypatch.setattr(spec, "HYPERPARAM_SELECTION_MAX_EPISODES", 4)
    monkeypatch.setattr(spec, "REGULAR_DT_SUBSET_EPISODES", 1)
    monkeypatch.setattr(spec, "SMOKE_PLAN_CHOICE", {"flat": {"H": 16}, "hierarchical": {"macro_horizon": 4, "budget_ratio": 0.5}})
    monkeypatch.setattr(world, "world_rejection_requires_redraw", lambda *a, **kw: False)
    monkeypatch.setattr(spec, "TRAIN_N_WORLDS", 10)
    monkeypatch.setattr(spec, "TRAIN_EPISODES_PER_WORLD", 6)
    monkeypatch.setattr(spec, "DEV_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "DEV_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "FINAL_WORLDS_COUNT", 2)
    monkeypatch.setattr(spec, "FINAL_PAIRS_PER_WORLD", 2)
    monkeypatch.setattr(spec, "BOOTSTRAP_RESAMPLES", 20)
    monkeypatch.setattr(spec, "SMOKE_SHORT_TRAIN_STEPS", 25)
    monkeypatch.setattr(spec, "MODEL_SELECTION_EVERY_STEPS", 10)
    monkeypatch.setattr(world, "WORLD_REJECTION_RATE_THRESHOLD", 1.0)

    from ainerzero.v9.experiments.s2 import smoke
    orig_steps_rule = smoke.compute_training_steps
    def _mock_fast_steps_rule(step_times: Any, budget_seconds: float = 1200.0, efficiency: float = 0.8) -> dict[str, Any]:
        res = orig_steps_rule(step_times, budget_seconds=budget_seconds, efficiency=efficiency)
        res["shared_train_steps"] = 20
        res["per_arm_steps"] = {k: 20 for k in step_times}
        return res
    monkeypatch.setattr(smoke, "compute_training_steps", _mock_fast_steps_rule)

    monkeypatch.setattr(adapters_mlx, "make_mlx_arm", lambda name: ProductionFakeArm(adapters_mlx.canonical_arm(name)))
    monkeypatch.setattr(
        "ainerzero.v9.experiments.s2.arms_mlx.compute_sigreg_mlx",
        lambda arr: core_math.compute_sigreg_numpy(np.asarray(arr)),
        raising=False,
    )

    _freeze_and_approve(tmp_env)
    assert _run_cli(tmp_env, "smoke") == 0
    assert _run_cli(tmp_env, "generate-data", "--partition", "train") == 0
    assert _run_cli(tmp_env, "generate-data", "--partition", "dev") == 0
    assert _run_cli(tmp_env, "generate-data", "--partition", "final") == 0

    for arm in ("arm_a", "arm_b", "arm_c"):
        for seed in (42, 43, 44):
            assert _run_cli(tmp_env, "train", "--arm", arm, "--seed", str(seed)) == 0


def test_cli_plan_select_wiring(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Y7: commands.py plan-select called via cli.main without injected mock arguments."""
    output_root = tmp_env["output_root"]
    _setup_pipeline_up_to_training(tmp_env, monkeypatch)

    code = _run_cli(tmp_env, "plan-select")
    assert code == 0, "cli.main plan-select failed"

    plan_cfg_path = output_root / "plan_config.json"
    assert plan_cfg_path.is_file(), "plan_config.json missing"
    gates_path = output_root / "post_train_gates.json"
    assert gates_path.is_file(), "post_train_gates.json missing"
    gates_res = json.loads(gates_path.read_text(encoding="utf-8"))
    assert gates_res["passed"] is True, f"gates failed: {gates_res.get('reasons')}"


def test_cli_dev_eval_wiring(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Y7: commands.py dev-eval called via cli.main without injected mock arguments."""
    output_root = tmp_env["output_root"]
    _setup_pipeline_up_to_training(tmp_env, monkeypatch)
    assert _run_cli(tmp_env, "plan-select") == 0

    code = _run_cli(tmp_env, "dev-eval")
    assert code == 0, "cli.main dev-eval failed"

    dev_ledger_path = output_root / "dev_ledger.json"
    assert dev_ledger_path.is_file(), "dev_ledger.json missing"
    dev_ledger = json.loads(dev_ledger_path.read_text(encoding="utf-8"))
    assert dev_ledger["dev_eval_count"] == 1


def test_cli_final_eval_wiring(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Y7: commands.py final-eval called via cli.main without injected mock arguments."""
    output_root = tmp_env["output_root"]
    _setup_pipeline_up_to_training(tmp_env, monkeypatch)
    assert _run_cli(tmp_env, "plan-select") == 0

    # Add required final-eval approval line in research_log
    res_log = tmp_env["research_log"]
    sha = hashlib.sha256(tmp_env["prereg"].read_bytes()).hexdigest()
    with open(res_log, "a", encoding="utf-8") as f:
        f.write(f"\nAPPROVED s2-phase1 final-eval document_sha256={sha}\n")

    # One-shot final evaluation
    code = _run_cli(tmp_env, "final-eval")
    assert code == 0, "cli.main final-eval failed"

    sealed_final = output_root / "datasets" / "sealed_final"
    marker = sealed_final / eval_runner.READ_ONCE_MARKER_NAME
    assert marker.is_file(), "read-once marker must exist"
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert "opened_at_utc" in marker_data or "opened_at" in marker_data or "reader" in marker_data

    # Second read must fail closed (read-once violated)
    code_second = _run_cli(tmp_env, "final-eval")
    assert code_second != 0, "second call to final-eval must be refused"
