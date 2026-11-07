"""CPU contract tests for S2 eval_runner (plan-select / capped dev / one-shot final).

Pure NumPy / standard library. Zero MLX imports.
"""

from __future__ import annotations

import json
from pathlib import Path
import site
import subprocess
import sys
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded
from ainerzero.v9.experiments.s2.probe import RidgeProbe, fit_ridge
from ainerzero.v9.experiments.s2 import eval_runner as er
from ainerzero.v9.experiments.s2 import world

_CACHED_LAYOUT = world.make_layout(42)

_POSE_TABLE: dict[bytes, tuple[int, int, int]] = {}
for _y in range(1, 6):
    for _x in range(1, 6):
        if _CACHED_LAYOUT.terrain[_y][_x] == world.WALL:
            continue
        for _h in range(4):
            _st = world.State(x=_x, y=_y, heading=_h)
            _obs = world.student_obs(_CACHED_LAYOUT, _st, last_action=3, dt=1)
            from ainerzero.v9.experiments.s2 import learned_planning as _lp
            _k = _lp.featurize_obs(_obs, 1)[:196].tobytes()
            _POSE_TABLE[_k] = (_x, _y, _h)

_DIST_MAP = world.compute_bfs_distances(_CACHED_LAYOUT, 2, 1)
_EPS = 1e-3


class _FakeFlat:
    arm_kind = "flat"

    def encode(self, obs: Any) -> np.ndarray:
        key = np.asarray(obs, dtype=np.float64)[:196].tobytes()
        pose = _POSE_TABLE.get(key, (1, 1, 0))
        d = float(_DIST_MAP.get((pose[0], pose[1]), 50))
        return np.array([d, _EPS * pose[0], _EPS * pose[1], _EPS * pose[2]], dtype=np.float64)

    def predict_l1(self, z: np.ndarray, action: Any, dt: float = 1.0) -> np.ndarray:
        import inspect
        f = inspect.currentframe().f_back
        horizon = 0
        while f:
            if "config" in f.f_locals:
                cfg = f.f_locals["config"]
                if hasattr(cfg, "horizon"):
                    horizon = int(cfg.horizon)
                    break
            f = f.f_back
        z = np.asarray(z, dtype=np.float64)
        if z.ndim == 1:
            x, y, h = int(round(z[1] / _EPS)), int(round(z[2] / _EPS)), int(round(z[3] / _EPS)) % 4
            act = int(np.asarray(action).flat[0])
            nxt = world.step(_CACHED_LAYOUT, world.State(x=x, y=y, heading=h), act, k=1)
            if horizon == 32:
                d = float(_DIST_MAP.get((nxt.x, nxt.y), 50))
            else:
                d = 0.0 if act == 3 else 100.0
            return np.array([d, _EPS * nxt.x, _EPS * nxt.y, _EPS * nxt.heading], dtype=np.float64)
        B = z.shape[0]
        a_arr = np.asarray(action).reshape(B, -1)
        out = np.empty((B, 4), dtype=np.float64)
        for i in range(B):
            x, y, h = int(round(z[i, 1] / _EPS)), int(round(z[i, 2] / _EPS)), int(round(z[i, 3] / _EPS)) % 4
            act = int(a_arr[i, 0])
            nxt = world.step(_CACHED_LAYOUT, world.State(x=x, y=y, heading=h), act, k=1)
            if horizon == 32:
                d = float(_DIST_MAP.get((nxt.x, nxt.y), 50))
            else:
                d = 0.0 if act == 3 else 100.0
            out[i] = [d, _EPS * nxt.x, _EPS * nxt.y, _EPS * nxt.heading]
        return out

    def predict_l2(self, z: np.ndarray, macro: Any, dt: float = 1.0) -> np.ndarray:
        return np.asarray(z, dtype=np.float64)

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        return np.asarray(z1, dtype=np.float64)

    def latents(self, obs_seq: Any) -> np.ndarray:
        return np.zeros((len(obs_seq), 4))


class _FakeFlatTie:
    """All H equally good → plan-select must pick smallest H (16) by compute."""

    arm_kind = "flat"

    def encode(self, obs: Any) -> np.ndarray:
        return np.zeros(2)

    def predict_l1(self, z: np.ndarray, action: Any, dt: float = 1.0) -> np.ndarray:
        z_arr = np.asarray(z, dtype=np.float64)
        return z_arr

    def predict_l2(self, z: np.ndarray, macro: Any, dt: float = 1.0) -> np.ndarray:
        return np.asarray(z, dtype=np.float64)

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        return np.asarray(z1, dtype=np.float64)

    def latents(self, obs_seq: Any) -> np.ndarray:
        return np.zeros((len(obs_seq), 2))


def _train_specs(n: int = 4) -> list[dict[str, Any]]:
    return [
        {
            "partition": "train",
            "world_index": i // 2,
            "episode_index": i,
            "start": {"x": 1, "y": 1, "heading": 0},
            "goal": {"x": 2, "y": 1, "heading": 0},
            "bfs_distance": 2,
            "layout": _CACHED_LAYOUT,
        }
        for i in range(n)
    ]


def test_plan_select_rejects_dev_specs(tmp_path: Path) -> None:
    specs = _train_specs(2)
    specs[1]["partition"] = "dev"
    with pytest.raises(er.PlanSelectError, match="non-train"):
        er.run_plan_select({"A": _FakeFlat()}, specs, output_path=tmp_path / "x.json")


def test_plan_select_picks_known_best_H(tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    frozen = er.run_plan_select({"A": _FakeFlat()}, _train_specs(), output_path=out)
    assert frozen["arms"]["A"]["config"]["H"] == 32
    assert out.is_file()


def test_plan_select_tie_break_smaller_compute(tmp_path: Path) -> None:
    specs = [
        {
            "partition": "train",
            "world_index": i // 2,
            "episode_index": i,
            "start": {"x": 1, "y": 1, "heading": 0},
            "goal": {"x": 5, "y": 5, "heading": 0},
            "bfs_distance": 12,
            "layout": _CACHED_LAYOUT,
        }
        for i in range(4)
    ]
    frozen = er.run_plan_select({"A": _FakeFlatTie()}, specs, output_path=tmp_path / "t.json")
    assert frozen["arms"]["A"]["config"]["H"] == 16


def test_dev_eval_third_call_refused(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    er.save_dev_ledger(ledger, {"dev_eval_count": 0, "post_train_gates": {"passed": True}})
    frozen = {"arms": {"A": {"config": {"H": 32}}}}
    model = {"A": _FakeFlat()}
    specs = _train_specs(3)
    for s in specs:
        s["partition"] = "dev"

    er.run_dev_eval(model, frozen, long_specs=specs, ledger_path=ledger, n_boot=20)
    er.run_dev_eval(model, frozen, long_specs=specs, ledger_path=ledger, n_boot=20)
    with pytest.raises(er.DevEvalCapExceeded, match="already used 2"):
        er.run_dev_eval(model, frozen, long_specs=specs, ledger_path=ledger, n_boot=20)


def test_dev_eval_evaluates_all_seeds(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    er.save_dev_ledger(ledger, {"dev_eval_count": 0, "post_train_gates": {"passed": True}})
    frozen = {"arms": {"A": {"config": {"H": 32}}}}
    model = {"A": _FakeFlat()}
    specs = _train_specs(1)
    for s in specs:
        s["partition"] = "dev"

    result = er.run_dev_eval(model, frozen, long_specs=specs, ledger_path=ledger, n_boot=20)
    observed_seeds = {r["model_seed"] for r in result["per_episode"]}
    assert observed_seeds == {42, 43, 44}, f"Dev eval must evaluate all 3 seeds (42, 43, 44), got {observed_seeds}"


def test_dev_probe_fit_uses_train_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _spy_fit(Z, XY, lam: float = 1.0, source_partition: str = "missing", **kwargs):
        seen["source_partition"] = source_partition
        seen["Z"] = np.asarray(Z)
        return fit_ridge(Z, XY, lam=lam)

    ledger = tmp_path / "ledger.json"
    er.save_dev_ledger(ledger, {"dev_eval_count": 0, "post_train_gates": {"passed": True}})
    Z = np.arange(20, dtype=np.float64).reshape(10, 2)
    XY = np.arange(20, dtype=np.float64).reshape(10, 2) / 10.0
    train_latents = {
        "A": {"Z": Z, "XY": XY, "partition": "train"},
    }
    er.run_dev_eval(
        {"A": _FakeFlat()},
        {"arms": {"A": {"config": {"H": 32}}}},
        long_specs=[{**_train_specs(1)[0], "partition": "dev"}],
        ledger_path=ledger,
        train_latents_by_arm=train_latents,
        fit_ridge_fn=_spy_fit,
        n_boot=10,
    )
    assert seen["source_partition"] == "train"
    assert seen["Z"].shape == (10, 2)


def test_dev_voids_when_forward_budget_exceeded(tmp_path: Path) -> None:
    class _Hungry(_FakeFlat):
        def encode(self, obs: Any) -> np.ndarray:
            raise ForwardBudgetExceeded("encode", 5, 0, 10)

    ledger = tmp_path / "ledger.json"
    er.save_dev_ledger(ledger, {"dev_eval_count": 0, "post_train_gates": {"passed": True}})
    result = er.run_dev_eval(
        {"A": _Hungry()},
        {"arms": {"A": {"config": {"H": 16}}}},
        long_specs=[{**_train_specs(1)[0], "partition": "dev", "world_index": 0}],
        ledger_path=ledger,
        n_fwd_curve=(512,),  # triggers hungry path via primary still 4096; force via curve only
        n_boot=10,
    )
    # Primary uses N_fwd_DEFAULT=4096 so Hungry voids every primary episode too.
    assert result["voided_comparisons"], "expected voided comparisons when budget exceeded"
    assert all(v.get("void") for v in result["voided_comparisons"])


def _write_research_log(path: Path, *, lines: list[str]) -> None:
    body = ["## R20261106-S2-approval", ""] + lines + ["", "## Other", "x"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def test_final_requires_separate_final_eval_approval(tmp_path: Path) -> None:
    log = tmp_path / "RESEARCH_LOG.md"
    sha = "a" * 64
    # Only prereg line
    _write_research_log(log, lines=[f"{er.PREREG_APPROVAL_PREFIX}{sha}"])
    sealed = tmp_path / "sealed_final"
    sealed.mkdir()
    with pytest.raises(er.FinalEvalRefused, match="prereg approval only"):
        er.run_final_eval(
            {"A": _FakeFlat()},
            {"arms": {}},
            sealed_final_dir=sealed,
            research_log=log,
            long_specs=_train_specs(1),
            expected_document_sha256=sha,
        )

    # No approval at all
    _write_research_log(log, lines=["no approval here"])
    with pytest.raises(er.FinalEvalRefused, match="no qualifying final-eval"):
        er.find_final_eval_approval(log)


def test_final_blockquote_approval_ignored(tmp_path: Path) -> None:
    log = tmp_path / "RESEARCH_LOG.md"
    sha = "b" * 64
    _write_research_log(
        log,
        lines=[
            f"> {er.FINAL_APPROVAL_PREFIX}{sha}",
            f"{er.PREREG_APPROVAL_PREFIX}{'c' * 64}",
        ],
    )
    with pytest.raises(er.FinalEvalRefused, match="prereg approval only|no qualifying"):
        er.find_final_eval_approval(log, expected_sha256=sha)


def test_final_read_once_and_second_refused(tmp_path: Path) -> None:
    log = tmp_path / "RESEARCH_LOG.md"
    sha = "d" * 64
    _write_research_log(log, lines=[f"{er.FINAL_APPROVAL_PREFIX}{sha}"])
    sealed = tmp_path / "sealed_final"
    sealed.mkdir()
    frozen = {"arms": {"A": {"config": {"H": 32}}}}
    specs = [{**_train_specs(1)[0], "partition": "final"}]

    first = er.run_final_eval(
        {"A": _FakeFlat()},
        frozen,
        sealed_final_dir=sealed,
        research_log=log,
        long_specs=specs,
        expected_document_sha256=sha,
        success_diff=0.12,
        success_ci_lower=0.02,
        pred_delta_ci_upper=0.5,
    )
    assert (sealed / er.READ_ONCE_MARKER_NAME).is_file()
    assert first["gate"]["passed"] is True

    with pytest.raises(er.FinalEvalRefused, match="already read once"):
        er.run_final_eval(
            {"A": _FakeFlat()},
            frozen,
            sealed_final_dir=sealed,
            research_log=log,
            long_specs=specs,
            expected_document_sha256=sha,
            success_diff=0.12,
            success_ci_lower=0.02,
            pred_delta_ci_upper=0.5,
        )


def test_gate_requires_positive_ci_lower() -> None:
    ok = er.judge_hs2_gate(
        success_diff=0.12, success_ci_lower=0.02, pred_delta_ci_upper=0.5
    )
    assert ok.passed is True

    bad = er.judge_hs2_gate(
        success_diff=0.12, success_ci_lower=-0.01, pred_delta_ci_upper=0.5
    )
    assert bad.passed is False
    assert any("ci_lower" in r for r in bad.reasons)


def test_pure_cpu_no_mlx_import() -> None:
    user_site = site.getusersitepackages()
    code = (
        "import sys, site; "
        f"site.addsitedir({repr(user_site)}); "
        "sys.path.insert(0, 'src'); sys.path.insert(0, '.'); "
        "from ainerzero.v9.experiments.s2 import eval_runner; "
        "assert 'mlx' not in sys.modules; "
        "print('OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def _gate_specs(n: int = 64) -> list[dict[str, Any]]:
    specs = []
    for i in range(n):
        if i % 2 == 0:
            start = {"x": 1, "y": 1, "heading": 1}
            goal = {"x": 4, "y": 1, "heading": 1}
        else:
            start = {"x": 1, "y": 1, "heading": 2}
            goal = {"x": 1, "y": 4, "heading": 2}
        specs.append(
            {
                "partition": "train",
                "world_index": i // 2,
                "episode_index": i,
                "start": start,
                "goal": goal,
                "bfs_distance": 4,
                "layout": _CACHED_LAYOUT,
            }
        )
    return specs


class _ResponsiveCArm:
    arm_kind = "hierarchical"

    def encode(self, obs: Any) -> np.ndarray:
        key = np.asarray(obs, dtype=np.float64)[:196].tobytes()
        pose = _POSE_TABLE.get(key, (1, 1, 1))
        return np.array([float(pose[0]), float(pose[1]), float(pose[2]), 0.0], dtype=np.float64)

    def predict_l1(self, z: np.ndarray, action: Any, dt: float = 1.0) -> np.ndarray:
        z = np.asarray(z, dtype=np.float64)
        if z.ndim == 1:
            x, y, h = int(round(z[0])), int(round(z[1])), int(round(z[2])) % 4
            act = int(np.asarray(action).flat[0])
            nxt = world.step(_CACHED_LAYOUT, world.State(x=x, y=y, heading=h), act, k=1)
            return np.array([float(nxt.x), float(nxt.y), float(nxt.heading), 0.0], dtype=np.float64)
        B = z.shape[0]
        a_arr = np.asarray(action).reshape(B, -1)
        out = np.empty((B, 4), dtype=np.float64)
        for i in range(B):
            x, y, h = int(round(z[i, 0])), int(round(z[i, 1])), int(round(z[i, 2])) % 4
            act = int(a_arr[i, 0])
            nxt = world.step(_CACHED_LAYOUT, world.State(x=x, y=y, heading=h), act, k=1)
            out[i] = [float(nxt.x), float(nxt.y), float(nxt.heading), 0.0]
        return out

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        z = np.asarray(z1, dtype=np.float64)
        if z.ndim == 1:
            return z[:2].copy()
        return z[:, :2].copy()

    def predict_l2(self, z2: np.ndarray, macro: Any, dt: float = 1.0) -> np.ndarray:
        z2_arr = np.asarray(z2, dtype=np.float64)
        m = np.asarray(macro, dtype=np.float64)
        step = np.sign(m.reshape(-1)[:2]) * 1.0
        if z2_arr.ndim == 1:
            return z2_arr + step
        step_b = np.sign(m.reshape(z2_arr.shape[0], -1)[:, :2]) * 1.0
        return z2_arr + step_b

    def latents(self, obs_seq: Any) -> np.ndarray:
        return np.zeros((len(obs_seq), 4))


class _ResponsiveFlat(_ResponsiveCArm):
    arm_kind = "flat"


class _UnplannableFlat:
    arm_kind = "flat"

    def encode(self, obs: Any) -> np.ndarray:
        return np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)

    def predict_l1(self, z: np.ndarray, action: Any, dt: float = 1.0) -> np.ndarray:
        a_idx = int(action) if np.ndim(action) == 0 else int(np.argmax(action))
        return np.asarray(z, dtype=np.float64) + (a_idx + 1) * 0.0001

    def latents(self, obs_seq: Any) -> np.ndarray:
        return np.zeros((len(obs_seq), 4))


class _ColludingCArm(_ResponsiveCArm):
    arm_kind = "hierarchical"

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        z = np.asarray(z1, dtype=np.float64)
        if z.ndim == 1:
            return np.zeros(2, dtype=np.float64)
        return np.zeros((z.shape[0], 2), dtype=np.float64)


def test_post_train_gates_rejects_dev_or_final_specs() -> None:
    specs = _train_specs(4)
    specs[2]["partition"] = "dev"
    with pytest.raises(er.PostTrainGateError, match="refuses non-train"):
        er.run_post_train_gates({"A": _ResponsiveFlat()}, specs)

    specs[2]["partition"] = "final"
    with pytest.raises(er.PostTrainGateError, match="refuses non-train"):
        er.run_post_train_gates({"A": _ResponsiveFlat()}, specs)


def test_unplannable_arm_fails_gate_and_dev_refused(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    specs = _gate_specs(64)
    model = {"A": _UnplannableFlat()}

    result = er.run_post_train_gates(model, specs, ledger_path=ledger)
    assert result["passed"] is False
    assert "A" in result["unplannable_arms"]
    assert any("不可规划" in r for r in result["reasons"])
    assert result["sensitivity_by_arm"]["A"] < er.ACTION_SENSITIVITY_FLOOR

    dev_specs = [{**s, "partition": "dev"} for s in _train_specs(2)]
    with pytest.raises(er.PostTrainGateRefused, match="不可规划"):
        er.run_dev_eval(model, {"arms": {}}, long_specs=dev_specs, ledger_path=ledger)


def test_c_arm_collusion_detected_and_dev_refused(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    specs = _gate_specs(50)
    model = {"A": _ResponsiveFlat(), "C": _ColludingCArm()}

    result = er.run_post_train_gates(model, specs, ledger_path=ledger, c_shuffle_episodes=50, plan_config={"arms": {"A": {"plan_choice": {"H": 32}}, "C": {"plan_choice": {"macro_horizon": 6, "budget_ratio": 0.5}}}})
    assert result["passed"] is False
    assert result["c_negative_control"]["collusion"] is True
    assert result["c_negative_control"]["drop"] < er.SUBGOAL_DROP_FLOOR
    assert any("合谋" in r for r in result["reasons"])

    dev_specs = [{**s, "partition": "dev"} for s in _train_specs(2)]
    with pytest.raises(er.PostTrainGateRefused, match="合谋"):
        er.run_dev_eval(model, {"arms": {}}, long_specs=dev_specs, ledger_path=ledger)


def test_normal_model_passes_post_train_gates_and_enters_dev(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    out_json = tmp_path / "gates.json"
    specs = _gate_specs(64)
    model = {"A": _ResponsiveFlat(), "C": _ResponsiveCArm()}

    result = er.run_post_train_gates(
        model,
        specs,
        ledger_path=ledger,
        output_path=out_json,
        c_shuffle_episodes=50,
        plan_config={"arms": {"A": {"plan_choice": {"H": 32}}, "C": {"plan_choice": {"macro_horizon": 6, "budget_ratio": 0.5}}}},
    )
    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["sensitivity_by_arm"]["A"] >= er.ACTION_SENSITIVITY_FLOOR
    assert result["sensitivity_by_arm"]["C"] >= er.ACTION_SENSITIVITY_FLOOR
    assert result["c_negative_control"]["collusion"] is False
    assert result["c_negative_control"]["drop"] >= er.SUBGOAL_DROP_FLOOR
    assert out_json.is_file()

    dev_specs = [{**s, "partition": "dev"} for s in _train_specs(2)]
    dev_res = er.run_dev_eval(
        model,
        {"arms": {"A": {"plan_choice": {"H": 32}}, "C": {"plan_choice": {"macro_horizon": 6, "budget_ratio": 0.5}}}},
        long_specs=dev_specs,
        ledger_path=ledger,
        n_boot=10,
    )
    assert dev_res["dev_eval_count"] == 1


def test_dev_eval_refused_without_post_train_gates(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    model = {"A": _ResponsiveFlat()}
    dev_specs = [{**s, "partition": "dev"} for s in _train_specs(2)]
    with pytest.raises(er.PostTrainGateRefused, match="post_train_gates record missing"):
        er.run_dev_eval(model, {"arms": {}}, long_specs=dev_specs, ledger_path=ledger)


def test_baseline_rationality_gate_out_of_range(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    specs = _train_specs(50)

    class _LowBaselineArm(_ResponsiveFlat):
        def predict_l1(self, z: np.ndarray, action: Any, dt: float = 1.0) -> np.ndarray:
            z_arr = np.asarray(z, dtype=np.float64)
            act = int(np.asarray(action).flat[0]) if np.ndim(action) > 0 else int(action)
            out = np.zeros_like(z_arr)
            out[..., 0] = 50.0 + (act + 1) * 0.5
            return out

    model_low = {"A": _LowBaselineArm(), "C": _ResponsiveCArm()}
    plan_cfg = {"arms": {"A": {"plan_choice": {"H": 32}}, "C": {"plan_choice": {"macro_horizon": 6, "budget_ratio": 0.5}}}}
    res_low = er.run_post_train_gates(model_low, specs, plan_config=plan_cfg, ledger_path=ledger)
    assert res_low["passed"] is False
    assert any("Baseline rationality" in r for r in res_low["reasons"])

    class _HighBaselineArm(_ResponsiveFlat):
        pass

    specs_high = [
        {**s, "start": {"x": 2, "y": 1, "heading": 0}, "goal": {"x": 2, "y": 1, "heading": 0}}
        for s in specs
    ]
    model_high = {"A": _HighBaselineArm(), "C": _ResponsiveCArm()}
    res_high = er.run_post_train_gates(model_high, specs_high, plan_config=plan_cfg, ledger_path=ledger)
    assert res_high["passed"] is False
    assert any("Baseline rationality" in r for r in res_high["reasons"])

