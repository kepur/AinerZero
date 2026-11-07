"""S2 Phase 1 training runner (backend-agnostic, pure CPU).

Trains one (arm, seed) cell via an arm protocol — no MLX import.
Model selection uses train-partition holdout rollout error only (DESIGN-r2 Appendix A).
Wall-clock guard stops early and reports actual steps without claiming full completion.

Task: ainerzero.V9.P142.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import spec
from ainerzero.v9.experiments.s2.data_runner import assert_output_root_is_permitted
from ainerzero.v9.experiments.s2.worker import (
    S2Ledger,
    check_cell_already_completed,
)

# Registered training constants (DESIGN-r2 Appendix A / s2.spec)
BATCH_SIZE = int(spec.BATCH_SIZE)  # 32
H_TRAIN = int(spec.H_TRAIN)  # 16
SEQUENCE_LENGTH = int(spec.SEQUENCE_LENGTH)  # 17
OBS_DIM = int(spec.OBS_DIM)  # 205
NUM_TERRAIN_CLASSES = int(spec.NUM_TERRAIN_CLASSES)  # 4
FOV_SIZE = int(spec.FOV_SIZE)  # 7

FORBIDDEN_PATH_PARTS = frozenset({"dev", "sealed_final"})

TERRAIN_TO_CLASS = {-1: 3, 0: 0, 1: 1, 2: 2}  # UNSEEN/FREE/WALL/PILLAR


class ArmProtocol(Protocol):
    """Backend-agnostic arm interface used by this runner."""

    def init(self, seed: int) -> None: ...

    def train_step(self, batch: Mapping[str, Any]) -> dict[str, float]: ...

    def rollout_error(self, batch: Mapping[str, Any], H: int) -> float: ...

    def save(self, path: str | Path) -> str: ...

    def n_params(self) -> int: ...


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_digest() -> str:
    """SHA256 of this module's source file (recorded in meta)."""
    return _sha256_file(Path(__file__).resolve())


def _reject_forbidden_parts(path: Path) -> None:
    for part in path.resolve().parts:
        if part in FORBIDDEN_PATH_PARTS:
            raise ValueError(
                f"refusing path that touches non-train partition {part!r}: {path}"
            )


def resolve_train_partition(data_dir: str | Path) -> Path:
    """Resolve datasets/train under data_dir; refuse dev / sealed_final paths."""
    root = Path(data_dir).resolve()
    _reject_forbidden_parts(root)

    if root.name == "train" and root.parent.name == "datasets":
        train_root = root
    elif (root / "datasets" / "train").is_dir():
        train_root = (root / "datasets" / "train").resolve()
    elif root.name == "datasets" and (root / "train").is_dir():
        train_root = (root / "train").resolve()
    else:
        raise ValueError(
            f"cannot locate datasets/train under data_dir={root}; "
            "caller must point at phase root, datasets/, or datasets/train/"
        )

    _reject_forbidden_parts(train_root)
    if train_root.name != "train":
        raise ValueError(f"resolved partition is not train: {train_root}")
    return train_root


def flatten_student_obs(obs: Mapping[str, Any]) -> np.ndarray:
    """Flatten a student_obs dict into the registered OBS_DIM vector."""
    view = np.asarray(obs["view"], dtype=np.int64)
    if view.shape != (FOV_SIZE, FOV_SIZE):
        raise ValueError(f"expected view shape {(FOV_SIZE, FOV_SIZE)}, got {view.shape}")
    one_hot = np.zeros((FOV_SIZE, FOV_SIZE, NUM_TERRAIN_CLASSES), dtype=np.float64)
    for r in range(FOV_SIZE):
        for c in range(FOV_SIZE):
            cls = TERRAIN_TO_CLASS.get(int(view[r, c]), 3)
            one_hot[r, c, cls] = 1.0
    terrain = one_hot.reshape(-1)
    heading = np.asarray(obs["heading"], dtype=np.float64).reshape(-1)
    last_action = np.asarray(obs["last_action"], dtype=np.float64).reshape(-1)
    dt = np.asarray([float(obs["dt"])], dtype=np.float64)
    vec = np.concatenate([terrain, heading, last_action, dt])
    if vec.shape != (OBS_DIM,):
        raise ValueError(f"flattened obs dim {vec.shape[0]} != OBS_DIM {OBS_DIM}")
    return vec


def _load_episode_sequences(episode_path: Path) -> list[np.ndarray]:
    """Load contiguous length-SEQUENCE_LENGTH observation windows from one episode."""
    _reject_forbidden_parts(episode_path)
    payload = json.loads(episode_path.read_text(encoding="utf-8"))
    steps = payload.get("steps") or []
    if len(steps) < SEQUENCE_LENGTH:
        return []
    obs = np.stack([flatten_student_obs(s["student_obs"]) for s in steps], axis=0)
    windows: list[np.ndarray] = []
    for start in range(0, len(obs) - SEQUENCE_LENGTH + 1):
        windows.append(obs[start : start + SEQUENCE_LENGTH])
    return windows


def load_train_sequences(train_root: Path) -> tuple[list[np.ndarray], list[str]]:
    """Load all train sequences; return (sequences, relative file paths for manifest)."""
    train_root = train_root.resolve()
    _reject_forbidden_parts(train_root)
    episode_files = sorted(train_root.rglob("episode_*.json"))
    if not episode_files:
        raise FileNotFoundError(f"no episode_*.json under train partition {train_root}")

    sequences: list[np.ndarray] = []
    rel_files: list[str] = []
    for ep in episode_files:
        _reject_forbidden_parts(ep)
        wins = _load_episode_sequences(ep)
        if wins:
            sequences.extend(wins)
            rel_files.append(str(ep.relative_to(train_root)))
    if not sequences:
        raise ValueError(f"no sequences of length {SEQUENCE_LENGTH} found under {train_root}")
    return sequences, rel_files


def get_holdout_world_indices(
    train_root: Path,
    n_worlds: int | None = None,
    holdout_fraction: float | None = None,
) -> set[int]:
    """Retrieve and verify holdout world indices for train partition (DESIGN-r2 Appendix D1/D2).

    F5:
    - HOLDOUT_WORLDS.json must exist and be valid JSON (file missing or corrupted raises error; no fallback recompute).
    - Recorded holdout worlds are recomputed from world directories and compared; mismatch raises error (tamper check).
    - Holdout set cannot be empty; world directory names must be parseable.
    """
    holdout_file = train_root / "HOLDOUT_WORLDS.json"
    if not holdout_file.is_file():
        raise FileNotFoundError(f"Missing HOLDOUT_WORLDS.json in train data directory: {holdout_file}")

    try:
        data = json.loads(holdout_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted HOLDOUT_WORLDS.json in {train_root}: {exc}")

    if not isinstance(data, dict) or "holdout_worlds" not in data:
        raise ValueError(f"Invalid HOLDOUT_WORLDS.json schema in {train_root}: missing 'holdout_worlds'")

    recorded_raw = data.get("holdout_worlds")
    if not isinstance(recorded_raw, list) or len(recorded_raw) == 0:
        raise ValueError(f"HOLDOUT_WORLDS.json in {train_root} has empty or non-list holdout_worlds")

    recorded_worlds = set(int(w) for w in recorded_raw)

    # Extract existing world directories
    world_dirs = [d for d in train_root.iterdir() if d.is_dir() and d.name.startswith("world_")]
    if not world_dirs:
        raise ValueError(f"No world directories found in {train_root}")
    world_indices = []
    for d in world_dirs:
        parts = d.name.split("_")
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError(f"Unparseable world directory name: {d.name}")
        world_indices.append(int(parts[1]))
    world_indices.sort()

    frac = float(spec.TRAIN_HOLDOUT_WORLD_FRACTION) if holdout_fraction is None else float(holdout_fraction)
    expected_holdout = sorted(
        world_indices,
        key=lambda w: hashlib.sha256(f"s2p1-train-v1|holdout|{w}".encode("utf-8")).hexdigest(),
    )[:max(1, int(round(len(world_indices) * frac)))]

    if recorded_worlds != set(expected_holdout):
        raise ValueError(
            f"HOLDOUT_WORLDS.json tamper detected in {train_root}: "
            f"recorded {sorted(recorded_worlds)} != expected {expected_holdout}"
        )

    return recorded_worlds


def load_train_and_holdout_sequences(
    train_root: Path,
    holdout_fraction: float | None = None,
) -> tuple[list[np.ndarray], list[np.ndarray], list[str]]:
    """Load train-partition sequences separated by world into train vs holdout.

    Per DESIGN-r2 Appendix D2:
    - Training batches only take non-holdout worlds.
    - Model selection only takes holdout worlds (world-cut, independent of seed).
    """
    train_root = train_root.resolve()
    _reject_forbidden_parts(train_root)
    holdout_worlds = get_holdout_world_indices(train_root, holdout_fraction=holdout_fraction)

    episode_files = sorted(train_root.rglob("episode_*.json"))
    if not episode_files:
        raise FileNotFoundError(f"no episode_*.json under train partition {train_root}")

    train_seqs: list[np.ndarray] = []
    hold_seqs: list[np.ndarray] = []
    rel_files: list[str] = []

    for ep in episode_files:
        _reject_forbidden_parts(ep)
        w_idx = None
        if ep.parent.name.startswith("world_"):
            try:
                w_idx = int(ep.parent.name.split("_")[1])
            except ValueError:
                pass
        if w_idx is None:
            try:
                payload = json.loads(ep.read_text(encoding="utf-8"))
                w_idx = payload.get("world_index")
            except Exception:
                pass

        wins = _load_episode_sequences(ep)
        if wins:
            rel_files.append(str(ep.relative_to(train_root)))
            if w_idx is not None and w_idx in holdout_worlds:
                hold_seqs.extend(wins)
            else:
                train_seqs.extend(wins)

    if not train_seqs:
        raise ValueError(f"no training sequences found under non-holdout worlds in {train_root}")
    if not hold_seqs:
        raise ValueError(f"no holdout sequences found under holdout worlds in {train_root}")

    return train_seqs, hold_seqs, rel_files


def split_holdout(
    sequences: Sequence[np.ndarray],
    seed: int,
    holdout_fraction: float = spec.TRAIN_HOLDOUT_WORLD_FRACTION,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Deterministic train/holdout split from the training partition only."""
    n = len(sequences)
    if n < 2:
        raise ValueError(f"need at least 2 sequences to split holdout; got {n}")
    n_hold = max(1, int(round(n * holdout_fraction)))
    if n_hold >= n:
        n_hold = n - 1
    rng = np.random.RandomState(int(seed) ^ 0xA5A5_5A5A)
    perm = rng.permutation(n)
    hold_idx = set(int(i) for i in perm[:n_hold])
    train_seqs = [sequences[i] for i in range(n) if i not in hold_idx]
    hold_seqs = [sequences[i] for i in range(n) if i in hold_idx]
    if not train_seqs or not hold_seqs:
        raise ValueError("holdout split produced an empty side")
    return train_seqs, hold_seqs


def sample_batch(
    sequences: Sequence[np.ndarray],
    rng: np.random.RandomState,
    batch_size: int = BATCH_SIZE,
) -> dict[str, np.ndarray]:
    """Sample a batch of sequences using an explicit RNG (never global np.random)."""
    if not sequences:
        raise ValueError("cannot sample from empty sequence list")
    idx = rng.randint(0, len(sequences), size=batch_size)
    batch = np.stack([sequences[int(i)] for i in idx], axis=0)
    return {"obs": batch.astype(np.float64, copy=False)}


def _mean_holdout_error(
    arm: ArmProtocol,
    holdout: Sequence[np.ndarray],
    rng: np.random.RandomState,
    H: int,
    batches: int = 4,
) -> float:
    errors: list[float] = []
    for _ in range(max(1, batches)):
        batch = sample_batch(holdout, rng)
        errors.append(float(arm.rollout_error(batch, H)))
    return float(np.mean(errors))


def _data_manifest_sha(rel_files: Sequence[str], train_root: Path) -> str:
    lines = []
    for rel in sorted(rel_files):
        digest = _sha256_file(train_root / rel)
        lines.append(f"{digest}  {rel}")
    return _sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def run_train_cell(
    arm_factory: Callable[[], ArmProtocol],
    arm_id: str,
    seed: int,
    data_dir: str | Path,
    output_root: str | Path,
    steps: int,
    *,
    wall_budget_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
    eval_every: int = spec.MODEL_SELECTION_EVERY_STEPS,
    holdout_fraction: float = spec.TRAIN_HOLDOUT_WORLD_FRACTION,
    batch_size: int = BATCH_SIZE,
    H: int = H_TRAIN,
    ledger: S2Ledger | None = None,
    run_id: str | None = None,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Train one (arm, seed) cell; select checkpoint by train-holdout rollout error.

    Returns a result dict for worker ledger accounting. Status is ``completed`` only
    when the requested step budget finishes without wall-clock preemption; early
    stop due to wall budget yields ``stopped`` with actual steps recorded.
    """
    if steps <= 0:
        raise ValueError(f"steps must be positive; got {steps}")
    if eval_every <= 0:
        raise ValueError(f"eval_every must be positive; got {eval_every}")

    # Duplicate detection (worker owns the authoritative check; also honour ledger_path).
    if ledger_path is not None:
        if check_cell_already_completed(ledger_path, "train", arm_id, int(seed)):
            return {
                "status": "duplicate_execution",
                "arm": arm_id,
                "seed": int(seed),
                "message": f"train cell ({arm_id}, seed={seed}) already completed",
            }

    out_root = assert_output_root_is_permitted(output_root)
    train_root = resolve_train_partition(data_dir)

    train_seqs, hold_seqs, rel_files = load_train_and_holdout_sequences(
        train_root, holdout_fraction=holdout_fraction
    )
    data_sha = _data_manifest_sha(rel_files, train_root)

    ckpt_dir = out_root / "checkpoints" / str(arm_id) / f"seed{int(seed)}"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    best_path = ckpt_dir / "best.ckpt"
    meta_path = ckpt_dir / "meta.json"

    arm = arm_factory()
    arm.init(int(seed))

    clock_fn = clock or time.time
    t0 = float(clock_fn())
    budget = float(wall_budget_seconds) if wall_budget_seconds is not None else None

    # Dedicated RNGs — never touch global np.random.
    train_rng = np.random.RandomState(int(seed) + 17)
    eval_rng = np.random.RandomState(int(seed) + 91)

    holdout_curve: list[dict[str, float | int]] = []
    best_error = float("inf")
    best_step = 0
    best_sha: str | None = None
    actual_steps = 0
    stopped_for_wall = False
    last_losses: dict[str, float] = {}

    for step_i in range(1, int(steps) + 1):
        if budget is not None and (float(clock_fn()) - t0) >= budget:
            stopped_for_wall = True
            break

        batch = sample_batch(train_seqs, train_rng, batch_size=batch_size)
        last_losses = {k: float(v) for k, v in arm.train_step(batch).items()}
        actual_steps = step_i

        if step_i % int(eval_every) == 0 or step_i == int(steps):
            err = _mean_holdout_error(arm, hold_seqs, eval_rng, H=H)
            holdout_curve.append({"step": int(step_i), "rollout_error": float(err)})
            if err < best_error:
                best_error = float(err)
                best_step = int(step_i)
                best_sha = arm.save(best_path)

        if budget is not None and (float(clock_fn()) - t0) >= budget:
            stopped_for_wall = True
            break

    # Ensure at least one eval if we stopped before the first cadence.
    if not holdout_curve and actual_steps > 0:
        err = _mean_holdout_error(arm, hold_seqs, eval_rng, H=H)
        holdout_curve.append({"step": int(actual_steps), "rollout_error": float(err)})
        best_error = float(err)
        best_step = int(actual_steps)
        best_sha = arm.save(best_path)

    if best_sha is None and actual_steps > 0:
        best_sha = arm.save(best_path)
        best_step = int(actual_steps)

    elapsed = float(clock_fn()) - t0
    # Wall preemption must never be reported as a full completion.
    status = "stopped" if stopped_for_wall else "completed"

    meta: dict[str, Any] = {
        "arm": arm_id,
        "seed": int(seed),
        "requested_steps": int(steps),
        "actual_steps": int(actual_steps),
        "best_step": int(best_step),
        "best_holdout_rollout_error": None if best_error == float("inf") else float(best_error),
        "holdout_curve": holdout_curve,
        "n_params": int(arm.n_params()),
        "source_digest": source_digest(),
        "data_manifest_sha256": data_sha,
        "checkpoint_sha256": best_sha,
        "best_checkpoint_sha": best_sha,
        "checkpoint_path": str(best_path),
        "holdout_fraction": float(holdout_fraction),
        "eval_every": int(eval_every),
        "batch_size": int(batch_size),
        "H_train": int(H),
        "wall_budget_seconds": budget,
        "elapsed_seconds": float(elapsed),
        "status": status,
        "last_train_losses": last_losses,
        "train_sequence_count": len(train_seqs),
        "holdout_sequence_count": len(hold_seqs),
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = {
        "status": status,
        "arm": arm_id,
        "seed": int(seed),
        "requested_steps": int(steps),
        "actual_steps": int(actual_steps),
        "best_step": int(best_step),
        "best_holdout_rollout_error": meta["best_holdout_rollout_error"],
        "holdout_curve": holdout_curve,
        "n_params": int(arm.n_params()),
        "checkpoint_sha256": best_sha,
        "best_checkpoint_sha": best_sha,
        "checkpoint_path": str(best_path),
        "meta_path": str(meta_path),
        "elapsed_seconds": float(elapsed),
        "wall_budget_exceeded": bool(stopped_for_wall),
    }

    if ledger is not None and run_id is not None:
        if status == "completed":
            ledger.complete_run(
                run_id,
                active_seconds=float(elapsed),
                optimizer_steps=int(actual_steps),
                metrics=result,
            )
        else:
            # Record partial progress then stop (not completed).
            if actual_steps > 0 or elapsed > 0:
                try:
                    ledger.store.consume(
                        run_id,
                        active_seconds=float(elapsed),
                        optimizer_steps=int(actual_steps),
                    )
                except Exception:
                    pass
            ledger.stop_run(run_id, reason="wall_budget_exceeded")

    return result


def make_worker_train_runner(
    arm_factory: Callable[[], ArmProtocol],
    data_dir: str | Path,
    steps: int,
    *,
    eval_every: int = spec.MODEL_SELECTION_EVERY_STEPS,
    holdout_fraction: float = spec.TRAIN_HOLDOUT_WORLD_FRACTION,
) -> Callable[..., dict[str, Any]]:
    """Build an ``execute_work_cell``-compatible runner that calls ``run_train_cell``."""

    def _runner(
        ledger: S2Ledger,
        run_id: str,
        mode: str,
        arm: str | None,
        seed: int | None,
        cell_wall_budget: float,
        clock: Callable[[], float] | None = None,
        output_root: str | Path | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if mode != "train":
            raise ValueError(f"train runner only supports mode='train'; got {mode!r}")
        if arm is None or seed is None:
            raise ValueError("train runner requires arm and seed")
        if output_root is None:
            raise ValueError("output_root is required")
        return run_train_cell(
            arm_factory=arm_factory,
            arm_id=str(arm),
            seed=int(seed),
            data_dir=data_dir,
            output_root=output_root,
            steps=int(steps),
            wall_budget_seconds=float(cell_wall_budget),
            clock=clock,
            eval_every=eval_every,
            holdout_fraction=holdout_fraction,
            ledger=ledger,
            run_id=run_id,
            ledger_path=ledger.db_path,
        )

    _runner.__name__ = "s2_train_cell_runner"
    return _runner


# ---------------------------------------------------------------------------
# Reference NumPy fake arm (for CPU tests; not a production MLX arm)
# ---------------------------------------------------------------------------


class FakeLinearArm:
    """Tiny linear next-state predictor on continuous obs slice (CPU test arm).

    Operates on OBS_DIM vectors but learns only the trailing continuous features
    (heading / last_action / dt region) so synthetic holdout error is well-behaved.
    """

    # Trailing continuous features in the flattened student_obs vector.
    FEATURE_SLICE = slice(196, OBS_DIM)

    def __init__(self, lr: float = 0.05) -> None:
        self.lr = float(lr)
        self.dim = int(OBS_DIM - 196)
        self.W: np.ndarray | None = None
        self.b: np.ndarray | None = None

    def init(self, seed: int) -> None:
        rng = np.random.RandomState(int(seed))
        self.W = rng.normal(scale=0.01, size=(self.dim, self.dim)).astype(np.float64)
        self.b = np.zeros((self.dim,), dtype=np.float64)

    def _feat(self, obs: np.ndarray) -> np.ndarray:
        return np.asarray(obs[..., self.FEATURE_SLICE], dtype=np.float64)

    def _predict_next(self, x: np.ndarray) -> np.ndarray:
        assert self.W is not None and self.b is not None
        return x @ self.W.T + self.b

    def train_step(self, batch: Mapping[str, Any]) -> dict[str, float]:
        assert self.W is not None and self.b is not None
        obs = np.asarray(batch["obs"], dtype=np.float64)
        feat = self._feat(obs)
        x = feat[:, :-1, :].reshape(-1, self.dim)
        y = feat[:, 1:, :].reshape(-1, self.dim)
        pred = self._predict_next(x)
        err = pred - y
        loss = float(np.mean(err ** 2))
        grad_W = (2.0 / max(x.shape[0], 1)) * (err.T @ x)
        grad_b = (2.0 / max(x.shape[0], 1)) * err.sum(axis=0)
        # Clip gradients for CPU-test stability.
        grad_W = np.clip(grad_W, -1.0, 1.0)
        grad_b = np.clip(grad_b, -1.0, 1.0)
        self.W -= self.lr * grad_W
        self.b -= self.lr * grad_b
        return {"loss": loss}

    def rollout_error(self, batch: Mapping[str, Any], H: int) -> float:
        assert self.W is not None and self.b is not None
        obs = np.asarray(batch["obs"], dtype=np.float64)
        feat = self._feat(obs)
        _B, T, _D = feat.shape
        h = min(int(H), T - 1)
        if h <= 0:
            return 0.0
        cur = feat[:, 0, :].copy()
        total = 0.0
        for t in range(h):
            cur = self._predict_next(cur)
            total += float(np.mean((cur - feat[:, t + 1, :]) ** 2))
        return total / float(h)

    def save(self, path: str | Path) -> str:
        assert self.W is not None and self.b is not None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to the exact path (file handle avoids np appending ".npz").
        with path.open("wb") as f:
            np.savez_compressed(f, W=self.W, b=self.b)
        return _sha256_file(path)

    def n_params(self) -> int:
        assert self.W is not None and self.b is not None
        return int(self.W.size + self.b.size)
