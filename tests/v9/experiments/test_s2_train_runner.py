"""CPU tests for S2 train_runner (ainerzero.V9.P142).

Covers: holdout model selection, train-only paths, wall-clock guard,
reproducibility, duplicate_execution wiring, P138 output_root guard,
and no-MLX import isolation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import commands, spec, worker
from ainerzero.v9.experiments.s2.data_runner import assert_output_root_is_permitted
from ainerzero.v9.experiments.s2.train_runner import (
    OBS_DIM,
    SEQUENCE_LENGTH,
    FakeLinearArm,
    flatten_student_obs,
    make_worker_train_runner,
    resolve_train_partition,
    run_train_cell,
    sample_batch,
    source_digest,
)

QUALIFIED_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class FakeClock:
    def __init__(self, start_ts: float = 1_700_000_000.0) -> None:
        self.current = float(start_ts)

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += float(seconds)


def _student_obs_from_vec(vec: np.ndarray) -> dict[str, Any]:
    """Approximate inverse of flatten_student_obs for synthetic episode writing."""
    v = np.asarray(vec, dtype=np.float64).reshape(OBS_DIM)
    terrain = v[: 7 * 7 * 4].reshape(7, 7, 4)
    cls = terrain.argmax(axis=-1)
    view = np.where(cls == 3, -1, cls).astype(int).tolist()
    heading = v[196:200].tolist()
    last_action = v[200:204].tolist()
    dt = float(abs(v[204]) + 1.0)  # keep dt positive-ish
    return {
        "view": view,
        "heading": heading,
        "last_action": last_action,
        "dt": dt,
    }


def _make_latent_obs(state: np.ndarray) -> np.ndarray:
    """Embed a small continuous state into OBS_DIM with FREE view one-hots."""
    vec = np.zeros(OBS_DIM, dtype=np.float64)
    # FREE one-hot at every view cell (class 0)
    for r in range(7):
        for c in range(7):
            vec[(r * 7 + c) * 4 + 0] = 1.0
    # pack 8-D state into heading(4)+last_action(4); dt scalar
    s = np.asarray(state, dtype=np.float64).reshape(-1)
    dim = min(8, s.size)
    vec[196 : 196 + dim] = s[:dim]
    vec[204] = 1.0
    return vec


def write_synthetic_train_partition(
    phase_root: Path,
    *,
    n_episodes: int = 8,
    steps_per_ep: int = 48,
    seed: int = 0,
) -> Path:
    """Write learnable synthetic train episodes under phase_root/datasets/train."""
    rng = np.random.RandomState(seed)
    # Stable linear dynamics on 8-D latent.
    A = np.eye(8) * 0.90
    A[0, 1] = 0.05
    A[1, 0] = -0.03
    train_root = phase_root / "datasets" / "train"
    import hashlib
    holdout_worlds = sorted(
        range(n_episodes),
        key=lambda w: hashlib.sha256(f"s2p1-train-v1|holdout|{w}".encode("utf-8")).hexdigest(),
    )[:max(1, int(round(n_episodes * 0.1)))]
    train_root.mkdir(parents=True, exist_ok=True)
    (train_root / "HOLDOUT_WORLDS.json").write_text(
        json.dumps({
            "partition": "train",
            "n_worlds": n_episodes,
            "n_holdout_worlds": len(holdout_worlds),
            "holdout_worlds": holdout_worlds,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    for e in range(n_episodes):
        world = train_root / f"world_{e:04d}"
        world.mkdir(parents=True, exist_ok=True)
        state = rng.normal(scale=1.0, size=8)
        steps = []
        for t in range(steps_per_ep):
            obs_vec = _make_latent_obs(state)
            steps.append(
                {
                    "step_index": t,
                    "action": int(t % 4),
                    "dt": 1,
                    "segment_kind": "synth",
                    "student_obs": _student_obs_from_vec(obs_vec),
                    "truth_before": {"x": 0, "y": 0},
                    "truth_after": {"x": 0, "y": 0},
                }
            )
            state = A @ state + rng.normal(scale=0.01, size=8)
        ep = {
            "steps": steps,
            "steps_count": len(steps),
            "total_env_steps": len(steps),
            "max_steps": steps_per_ep,
            "k_histogram": {"1": len(steps)},
            "segment_stats": {"non_bfs_steps": len(steps), "bfs_steps": 0},
            "segments": [],
            "layout_sha256": "synth",
        }
        (world / f"episode_{0:04d}.json").write_text(
            json.dumps(ep, sort_keys=True) + "\n", encoding="utf-8"
        )
    return train_root


@pytest.fixture
def synth_env(tmp_path: Path) -> dict[str, Any]:
    phase = tmp_path / "phase"
    phase.mkdir()
    train_root = write_synthetic_train_partition(phase, n_episodes=10, steps_per_ep=40, seed=123)
    out = tmp_path / "out"
    out.mkdir()
    # Sanity: flatten round-trip on first step.
    sample = json.loads(next(train_root.rglob("episode_*.json")).read_text())["steps"][0]
    flat = flatten_student_obs(sample["student_obs"])
    assert flat.shape == (OBS_DIM,)
    return {"tmp_path": tmp_path, "phase": phase, "train_root": train_root, "output_root": out}


class _ScriptedHoldoutArm:
    """Deterministic arm whose holdout error is non-monotonic (best at mid step)."""

    def __init__(self) -> None:
        self._train_steps = 0
        # eval_every=5 over 20 steps → errors at 5,10,15,20 with unique minimum at 10
        self._script = {5: 0.50, 10: 0.05, 15: 0.20, 20: 0.40}
        self._payload = np.array([1.0, 2.0, 3.0], dtype=np.float64)

    def init(self, seed: int) -> None:
        self._train_steps = 0
        self._payload = np.array([1.0, 2.0, float(seed % 7)], dtype=np.float64)

    def train_step(self, batch):  # noqa: ANN001
        self._train_steps += 1
        return {"loss": 1.0 / max(self._train_steps, 1)}

    def rollout_error(self, batch, H: int) -> float:  # noqa: ANN001
        return float(self._script.get(self._train_steps, 0.99))

    def save(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._payload.tobytes() + str(self._train_steps).encode())
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def n_params(self) -> int:
        return int(self._payload.size)


def test_holdout_error_decreases_and_best_step_is_argmin(synth_env: dict[str, Any]) -> None:
    """Holdout curve improves vs first eval; best_step is the true argmin (not merely last)."""
    # Part A: real FakeLinearArm — holdout one-step error improves.
    out_a = synth_env["output_root"] / "learn"
    out_a.mkdir(exist_ok=True)
    learned = run_train_cell(
        arm_factory=lambda: FakeLinearArm(lr=0.05),
        arm_id="arm_a",
        seed=42,
        data_dir=synth_env["phase"],
        output_root=out_a,
        steps=60,
        eval_every=5,
        wall_budget_seconds=10_000.0,
        H=1,
    )
    assert learned["status"] == "completed"
    curve_l = learned["holdout_curve"]
    first = float(curve_l[0]["rollout_error"])
    best = min(float(p["rollout_error"]) for p in curve_l)
    assert best < first

    # Part B: scripted non-monotonic curve — best must be step 10, not the last step 20.
    out_b = synth_env["output_root"] / "scripted"
    out_b.mkdir(exist_ok=True)
    result = run_train_cell(
        arm_factory=_ScriptedHoldoutArm,
        arm_id="arm_a",
        seed=42,
        data_dir=synth_env["phase"],
        output_root=out_b,
        steps=20,
        eval_every=5,
        wall_budget_seconds=10_000.0,
        H=1,
    )
    assert result["status"] == "completed"
    curve = result["holdout_curve"]
    errors = [float(p["rollout_error"]) for p in curve]
    best_idx = int(np.argmin(errors))
    assert int(curve[best_idx]["step"]) == 10
    assert int(result["best_step"]) == 10
    assert int(result["best_step"]) != int(curve[-1]["step"]), "best must not blindly be the last eval"
    meta = json.loads(Path(result["meta_path"]).read_text(encoding="utf-8"))
    assert meta["best_step"] == 10
    assert meta["source_digest"] == source_digest()
    assert Path(result["checkpoint_path"]).is_file()


def test_dev_and_sealed_final_paths_rejected(tmp_path: Path) -> None:
    """Touching dev or sealed_final in the data path raises immediately."""
    dev = tmp_path / "datasets" / "dev"
    dev.mkdir(parents=True)
    with pytest.raises(ValueError, match="dev"):
        resolve_train_partition(dev)

    sealed = tmp_path / "datasets" / "sealed_final"
    sealed.mkdir(parents=True)
    with pytest.raises(ValueError, match="sealed_final"):
        resolve_train_partition(sealed)

    # Also reject when a forbidden name appears as an ancestor of an otherwise-ok tree.
    bad = tmp_path / "dev" / "datasets" / "train"
    bad.mkdir(parents=True)
    (bad / "world_0000").mkdir()
    with pytest.raises(ValueError, match="dev"):
        resolve_train_partition(tmp_path / "dev")


def test_wall_clock_guard_stops_early_not_completed(synth_env: dict[str, Any]) -> None:
    """Fake clock: each step burns budget; runner stops and must not claim completed."""
    clock = FakeClock()

    class SlowArm(FakeLinearArm):
        def train_step(self, batch):  # type: ignore[override]
            clock.advance(50.0)
            return super().train_step(batch)

    result = run_train_cell(
        arm_factory=SlowArm,
        arm_id="arm_b",
        seed=7,
        data_dir=synth_env["phase"],
        output_root=synth_env["output_root"],
        steps=100,
        eval_every=5,
        wall_budget_seconds=120.0,
        clock=clock.time,
    )
    assert result["status"] == "stopped"
    assert result["status"] != "completed"
    assert result["wall_budget_exceeded"] is True
    assert result["actual_steps"] < 100
    assert result["actual_steps"] > 0
    meta = json.loads(Path(result["meta_path"]).read_text(encoding="utf-8"))
    assert meta["status"] == "stopped"
    assert meta["status"] != "completed"
    assert meta["actual_steps"] == result["actual_steps"]


def test_fixed_seed_checkpoint_sha_reproducible(synth_env: dict[str, Any]) -> None:
    """Same seed twice → identical checkpoint SHA (explicit RNG, not global)."""
    # Pollute global RNG differently before each run; explicit rng must ignore it.
    out1 = synth_env["output_root"] / "r1"
    out2 = synth_env["output_root"] / "r2"
    out1.mkdir()
    out2.mkdir()

    np.random.seed(1)
    np.random.rand(20)
    r1 = run_train_cell(
        arm_factory=lambda: FakeLinearArm(lr=0.1),
        arm_id="arm_a",
        seed=42,
        data_dir=synth_env["phase"],
        output_root=out1,
        steps=15,
        eval_every=5,
    )
    np.random.seed(999)
    np.random.rand(50)
    r2 = run_train_cell(
        arm_factory=lambda: FakeLinearArm(lr=0.1),
        arm_id="arm_a",
        seed=42,
        data_dir=synth_env["phase"],
        output_root=out2,
        steps=15,
        eval_every=5,
    )
    assert r1["status"] == "completed" and r2["status"] == "completed"
    assert r1["checkpoint_sha256"] == r2["checkpoint_sha256"]
    assert r1["best_step"] == r2["best_step"]


def test_duplicate_execution_via_worker_commands(synth_env: dict[str, Any], tmp_path: Path) -> None:
    """Wire train runner into s2_phase1_command; second identical cell is duplicate_execution."""
    output_root = tmp_path / "artifacts" / "v9" / "s2" / "phase1"
    output_root.mkdir(parents=True)
    ledger = output_root / "control.sqlite3"
    lock = tmp_path / "artifacts" / "locks" / "m0-worker.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    research_log = tmp_path / "RESEARCH_LOG.md"
    # Run modes require a frozen prereg + approval bound to its document SHA (commands Preflight 0).
    from ainerzero.v9.experiments.s2 import freeze as s2_freeze
    from ainerzero.v9.experiments.s2 import prereg as s2_prereg

    repo_root = Path(__file__).resolve().parents[3]
    frozen_sha = s2_freeze.freeze(s2_prereg.build_draft(repo_root=repo_root), out_dir=output_root, repo_root=repo_root)
    research_log.write_text(
        f"## R20261106-S2-approval\n\n{s2_freeze.approval_line(frozen_sha)}\n",
        encoding="utf-8",
    )
    prereg = output_root / "prereg.json"

    # Pre-record passed smoke run in ledger
    led = worker.S2Ledger(ledger)
    s_rid = led.open_run(mode="smoke", arm=None, seed=None, cell_wall_budget=1200.0)
    led.begin_run(s_rid, state="training")
    led.complete_run(s_rid, metrics={"passed": True, "shared_train_steps": 10})
    led.close()

    runner = make_worker_train_runner(
        arm_factory=lambda: FakeLinearArm(lr=0.1),
        data_dir=synth_env["phase"],
        steps=10,
        eval_every=5,
    )
    args = argparse.Namespace(
        mode="train",
        arm="arm_a",
        seed=42,
        output_root=output_root,
        ledger=ledger,
        lock_file=lock,
        research_log=research_log,
        prereg=prereg,
        budget=600.0,
        runner=runner,
        fake_clock=None,
        experiment_id=worker.EXPERIMENT_ID,
    )
    report1, code1 = commands.s2_phase1_command(args)
    assert code1 == commands.EXIT_COMPLETED
    assert report1["status"] == "completed"
    assert report1["result"]["status"] == "completed"

    report2, code2 = commands.s2_phase1_command(args)
    assert code2 == commands.EXIT_FAILED
    assert report2["status"] == "refused"
    assert report2["stage"] == "duplicate_execution"


def test_output_root_must_pass_p138_guard(synth_env: dict[str, Any], tmp_path: Path) -> None:
    """Non-registered artifacts path is refused by P138 guard."""
    bad = tmp_path / "artifacts" / "v9" / "s2" / "other"
    bad.mkdir(parents=True)
    # Monkeypatch registered host root to tmp_path so artifacts/ under it is policed.
    import ainerzero.v9.experiments.s2.data_runner as dr
    import ainerzero.v9.experiments.s2.train_runner as tr

    old_host = dr.REGISTERED_HOST_ROOT
    try:
        dr.REGISTERED_HOST_ROOT = tmp_path.resolve()
        with pytest.raises(ValueError, match="non-registered artifacts"):
            run_train_cell(
                arm_factory=lambda: FakeLinearArm(),
                arm_id="arm_a",
                seed=1,
                data_dir=synth_env["phase"],
                output_root=bad,
                steps=5,
            )
        # tmp (non-artifacts) still permitted
        ok = assert_output_root_is_permitted(synth_env["output_root"])
        assert ok == synth_env["output_root"].resolve()
    finally:
        dr.REGISTERED_HOST_ROOT = old_host


def test_no_mlx_imported_under_isolated_python(tmp_path: Path) -> None:
    """`-I` subprocess import of train_runner must leave mlx out of sys.modules."""
    repo = Path(__file__).resolve().parents[3]
    src = repo / "src"
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(src)!r})\n"
        "import ainerzero.v9.experiments.s2.train_runner as tr\n"
        "assert 'mlx' not in sys.modules, sorted(sys.modules)\n"
        "print('ok', tr.BATCH_SIZE)\n"
    )
    py = repo / ".venv" / "bin" / "python"
    exe = str(py) if py.is_file() else sys.executable
    proc = subprocess.run(
        [exe, "-I", "-c", code],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok" in proc.stdout


def test_sample_batch_uses_explicit_rng_not_global() -> None:
    """Explicit RandomState sampling is deterministic under global RNG pollution."""
    seqs = [np.zeros((SEQUENCE_LENGTH, OBS_DIM)), np.ones((SEQUENCE_LENGTH, OBS_DIM))]
    rng = np.random.RandomState(0)
    np.random.seed(123)
    b1 = sample_batch(seqs, rng, batch_size=4)
    rng2 = np.random.RandomState(0)
    np.random.seed(999)
    b2 = sample_batch(seqs, rng2, batch_size=4)
    assert np.array_equal(b1["obs"], b2["obs"])
