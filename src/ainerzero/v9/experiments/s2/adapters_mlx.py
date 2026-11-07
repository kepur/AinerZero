"""MLX arm adapters for S2 Phase 1 (ainerzero.V9.P148).

Implements backend adapters wrapping MLX models from arms_mlx.py to satisfy:
1. Train protocol (train_runner.ArmProtocol):
   - init(seed: int) -> None
   - train_step(batch: Mapping[str, Any]) -> dict[str, float]
   - rollout_error(batch: Mapping[str, Any], H: int) -> float
   - save(path: str | Path) -> str
   - n_params() -> int
2. Planning protocol (eval_runner and planner.py):
   - arm_kind: "flat" (Arm A, B) or "hierarchical" (Arm C)
   - encode(obs: np.ndarray) -> np.ndarray
   - predict_l1(z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray
   - encode_l2(z1: np.ndarray) -> np.ndarray (Arm C)
   - predict_l2(z2: np.ndarray, macro_a: np.ndarray, macro_dt: float = 1.0) -> np.ndarray (Arm C)
   - cost_fn: observation-space cost for Arm A; None / squared_distance for Arm B/C
   - latents(obs_seq: np.ndarray | Sequence[Any]) -> np.ndarray
3. Forward counting:
   - When a ForwardCounter is provided, every network evaluation is charged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import param_count, spec
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter


class _MLXProxy:
    def __getattr__(self, name: str) -> Any:
        import mlx.core as _real_mx
        globals()["mx"] = _real_mx
        return getattr(_real_mx, name)


class _NNProxy:
    def __getattr__(self, name: str) -> Any:
        import mlx.nn as _real_nn
        globals()["nn"] = _real_nn
        return getattr(_real_nn, name)


class _OptimProxy:
    def __getattr__(self, name: str) -> Any:
        import mlx.optimizers as _real_optim
        globals()["optim"] = _real_optim
        return getattr(_real_optim, name)


class _ArmsMLXProxy:
    def __getattr__(self, name: str) -> Any:
        from ainerzero.v9.experiments.s2 import arms_mlx as _real_arms_mlx
        globals()["arms_mlx"] = _real_arms_mlx
        return getattr(_real_arms_mlx, name)


mx: Any = _MLXProxy()
nn: Any = _NNProxy()
optim: Any = _OptimProxy()
arms_mlx: Any = _ArmsMLXProxy()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _save_params(model: Any, path: str | Path) -> str:
    """Save every parameter (full tree) to exactly ``path``; return its sha256.

    Writes through a file handle so numpy does not append ``.npz`` to the name.
    """
    from mlx.utils import tree_flatten

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    flat = {k: np.asarray(v) for k, v in tree_flatten(model.parameters())}
    if not flat:
        raise ValueError("model has no parameters to save")
    with open(p, "wb") as fh:
        np.savez(fh, **flat)
    return _sha256_file(p)


def _load_params(model: Any, path: str | Path) -> None:
    """Load a checkpoint written by ``_save_params``; keys and shapes must match exactly."""
    from mlx.utils import tree_flatten, tree_unflatten

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Checkpoint not found at {p}")
    expected = {k: tuple(v.shape) for k, v in tree_flatten(model.parameters())}
    with np.load(p) as data:
        got = {k: data[k] for k in data.files}
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    if missing or extra:
        raise ValueError(f"checkpoint keys mismatch: missing={missing[:5]} extra={extra[:5]}")
    bad = [k for k in expected if tuple(got[k].shape) != expected[k]]
    if bad:
        raise ValueError(f"checkpoint shape mismatch for {bad[:5]}")
    model.update(tree_unflatten([(k, mx.array(v)) for k, v in got.items()]))


class MLXArmAAdapter:
    """Adapter for Arm A (FlatRSSMArm) satisfying train and planning protocols."""

    def __init__(self, counter: ForwardCounter | None = None) -> None:
        self.model = arms_mlx.FlatRSSMArm()
        self.arm_kind = "flat"
        self.counter = counter
        self.optimizer: optim.Optimizer | None = None
        self._seed: int | None = None

    def init(self, seed: int) -> None:
        self._seed = seed
        mx.random.seed(seed)
        self.optimizer = optim.Adam(learning_rate=float(spec.LEARNING_RATE))

    def train_step(self, batch: Mapping[str, Any]) -> dict[str, float]:
        if self.optimizer is None:
            self.init(seed=42)

        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)

        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]

            def loss_fn(model: arms_mlx.FlatRSSMArm) -> mx.array:
                losses = [
                    arms_mlx.arm_a_loss_mlx(model, obs_seq[b], act_seq[b], dt_seq[b])
                    for b in range(B)
                ]
                return mx.mean(mx.stack(losses))
        else:

            def loss_fn(model: arms_mlx.FlatRSSMArm) -> mx.array:
                return arms_mlx.arm_a_loss_mlx(model, obs_seq, act_seq, dt_seq)

        loss_and_grad_fn = nn.value_and_grad(self.model, loss_fn)
        loss, grads = loss_and_grad_fn(self.model)
        assert self.optimizer is not None
        self.optimizer.update(self.model, grads)
        mx.eval(self.model.parameters(), self.optimizer.state)

        return {"loss": float(loss.item())}

    def rollout_error(self, batch: Mapping[str, Any], H: int) -> float:
        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)
        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]
            losses = [
                arms_mlx.arm_a_loss_mlx(self.model, obs_seq[b], act_seq[b], dt_seq[b])
                for b in range(B)
            ]
            return float(mx.mean(mx.stack(losses)).item())
        else:
            loss = arms_mlx.arm_a_loss_mlx(self.model, obs_seq, act_seq, dt_seq)
            return float(loss.item())

    def save(self, path: str | Path) -> str:
        return _save_params(self.model, path)

    def load(self, path: str | Path) -> None:
        _load_params(self.model, path)

    def n_params(self) -> int:
        return arms_mlx.count_params(self.model)

    # --- Planning protocol ---

    def encode(self, obs: np.ndarray) -> np.ndarray:
        """Planning latent of Arm A: posterior mean z (latent_dim) at the zero GRU state.

        ``predict_l1`` advances from the zero GRU state and returns the prior mean in
        the same latent space, so encode must return z, not the 128-d E1 features.
        """
        if self.counter is not None:
            self.counter.charge("encode", 1)
        e1 = self.model.encode(obs)
        h0 = mx.zeros((self.model.dims["gru_hidden"],), dtype=mx.float32)
        mean, _ = self.model.posterior(h0, e1)
        return np.asarray(mean, dtype=np.float64)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("predict_l1", 1)
        return self.model.predict_l1(z, a, dt)

    def cost_fn(self, z_T: np.ndarray, goal_obs: np.ndarray) -> float:
        if self.counter is not None:
            self.counter.charge("decode", 1)
        return self.model.planning_cost(z_T, goal_obs)

    def latents(self, obs_seq: np.ndarray | Sequence[Any]) -> np.ndarray:
        arr = mx.array(obs_seq, dtype=mx.float32)
        z = self.model.encode(arr)
        return np.asarray(z, dtype=np.float64)


class MLXArmBAdapter:
    """Adapter for Arm B (FlatJEPAArm) satisfying train and planning protocols."""

    def __init__(self, counter: ForwardCounter | None = None) -> None:
        self.model = arms_mlx.FlatJEPAArm()
        self.arm_kind = "flat"
        self.counter = counter
        self.optimizer: optim.Optimizer | None = None
        self._seed: int | None = None

    def init(self, seed: int) -> None:
        self._seed = seed
        mx.random.seed(seed)
        self.optimizer = optim.Adam(learning_rate=float(spec.LEARNING_RATE))

    def train_step(self, batch: Mapping[str, Any]) -> dict[str, float]:
        if self.optimizer is None:
            self.init(seed=42)

        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)

        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]

            def loss_fn(model: arms_mlx.FlatJEPAArm) -> mx.array:
                losses = []
                dirs = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, model.dims["z_dim"]))
                dirs = dirs / mx.linalg.norm(dirs, axis=-1, keepdims=True)
                for b in range(B):
                    zb = model.encode(obs_seq[b])
                    targets_zb = zb[1:]
                    z0 = zb[0]
                    l_pred = arms_mlx.multistep_latent_rollout_loss_mlx(
                        model, z0, act_seq[b, :-1], dt_seq[b, :-1], targets_zb
                    )
                    l_sigreg = arms_mlx.sigreg_mlx(zb, dirs)
                    idm_logits = model.predict_idm(zb[:-1], zb[1:])
                    l_idm = arms_mlx.idm_loss_mlx(idm_logits, act_seq[b, :-1])
                    losses.append(
                        l_pred + float(spec.SIGREG_LAMBDA) * l_sigreg + float(spec.IDM_MU) * l_idm
                    )
                return mx.mean(mx.stack(losses))
        else:

            def loss_fn(model: arms_mlx.FlatJEPAArm) -> mx.array:
                z_seq = model.encode(obs_seq)
                targets_z = z_seq[1:]
                z0 = z_seq[0]
                l_pred = arms_mlx.multistep_latent_rollout_loss_mlx(
                    model, z0, act_seq[:-1], dt_seq[:-1], targets_z
                )
                dirs = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, z_seq.shape[-1]))
                dirs = dirs / mx.linalg.norm(dirs, axis=-1, keepdims=True)
                l_sigreg = arms_mlx.sigreg_mlx(z_seq, dirs)
                idm_logits = model.predict_idm(z_seq[:-1], z_seq[1:])
                l_idm = arms_mlx.idm_loss_mlx(idm_logits, act_seq[:-1])
                return l_pred + float(spec.SIGREG_LAMBDA) * l_sigreg + float(spec.IDM_MU) * l_idm

        loss_and_grad_fn = nn.value_and_grad(self.model, loss_fn)
        loss, grads = loss_and_grad_fn(self.model)
        assert self.optimizer is not None
        self.optimizer.update(self.model, grads)
        mx.eval(self.model.parameters(), self.optimizer.state)

        return {"loss": float(loss.item())}

    def rollout_error(self, batch: Mapping[str, Any], H: int) -> float:
        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)
        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]
            losses = []
            for b in range(B):
                zb = self.model.encode(obs_seq[b])
                targets_zb = zb[1:H + 1]
                z0 = zb[0]
                l_pred = arms_mlx.multistep_latent_rollout_loss_mlx(
                    self.model, z0, act_seq[b, :H], dt_seq[b, :H], targets_zb
                )
                losses.append(l_pred)
            return float(mx.mean(mx.stack(losses)).item())
        else:
            z_seq = self.model.encode(obs_seq)
            targets_z = z_seq[1:H + 1]
            z0 = z_seq[0]
            l_pred = arms_mlx.multistep_latent_rollout_loss_mlx(
                self.model, z0, act_seq[:H], dt_seq[:H], targets_z
            )
            return float(l_pred.item())

    def save(self, path: str | Path) -> str:
        return _save_params(self.model, path)

    def load(self, path: str | Path) -> None:
        _load_params(self.model, path)

    def n_params(self) -> int:
        return arms_mlx.count_params(self.model)

    # --- Planning protocol ---

    def encode(self, obs: np.ndarray) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("encode", 1)
        z = self.model.encode(obs)
        return np.asarray(z, dtype=np.float64)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("predict_l1", 1)
        return self.model.predict_l1(z, a, dt)

    cost_fn = None  # Uses default squared_distance in planner

    def latents(self, obs_seq: np.ndarray | Sequence[Any]) -> np.ndarray:
        arr = mx.array(obs_seq, dtype=mx.float32)
        z = self.model.encode(arr)
        return np.asarray(z, dtype=np.float64)


class MLXArmCAdapter:
    """Adapter for Arm C (HierarchicalHJEPAArm) satisfying train and planning protocols."""

    def __init__(self, counter: ForwardCounter | None = None) -> None:
        self.model = arms_mlx.HierarchicalHJEPAArm()
        self.arm_kind = "hierarchical"
        self.counter = counter
        self.optimizer: optim.Optimizer | None = None
        self._seed: int | None = None

    def init(self, seed: int) -> None:
        self._seed = seed
        mx.random.seed(seed)
        self.optimizer = optim.Adam(learning_rate=float(spec.LEARNING_RATE))

    def train_step(self, batch: Mapping[str, Any]) -> dict[str, float]:
        if self.optimizer is None:
            self.init(seed=42)

        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)

        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]

            def loss_fn(model: arms_mlx.HierarchicalHJEPAArm) -> mx.array:
                losses = []
                dirs1 = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, model.dims["z1_dim"]))
                dirs1 = dirs1 / mx.linalg.norm(dirs1, axis=-1, keepdims=True)
                dirs2 = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, model.dims["z2_dim"]))
                dirs2 = dirs2 / mx.linalg.norm(dirs2, axis=-1, keepdims=True)
                for b in range(B):
                    z1_seq = model.encode(obs_seq[b])
                    targets_z1 = z1_seq[1:]
                    z0 = z1_seq[0]
                    l_pred1 = arms_mlx.multistep_latent_rollout_loss_mlx(
                        model, z0, act_seq[b, :-1], dt_seq[b, :-1], targets_z1
                    )
                    l_sigreg1 = arms_mlx.sigreg_mlx(z1_seq, dirs1)
                    idm1_logits = model.predict_idm1(z1_seq[:-1], z1_seq[1:])
                    l_idm1 = arms_mlx.idm_loss_mlx(idm1_logits, act_seq[b, :-1])

                    z2_seq = model.encode_l2(z1_seq)
                    l_sigreg2 = arms_mlx.sigreg_mlx(z2_seq, dirs2)

                    loss1 = l_pred1 + float(spec.SIGREG_LAMBDA) * l_sigreg1 + float(spec.IDM_MU) * l_idm1
                    loss2 = float(spec.SIGREG_LAMBDA) * l_sigreg2
                    losses.append(loss1 + loss2)
                return mx.mean(mx.stack(losses))
        else:

            def loss_fn(model: arms_mlx.HierarchicalHJEPAArm) -> mx.array:
                z1_seq = model.encode(obs_seq)
                targets_z1 = z1_seq[1:]
                z0 = z1_seq[0]
                l_pred1 = arms_mlx.multistep_latent_rollout_loss_mlx(
                    model, z0, act_seq[:-1], dt_seq[:-1], targets_z1
                )
                dirs1 = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, z1_seq.shape[-1]))
                dirs1 = dirs1 / mx.linalg.norm(dirs1, axis=-1, keepdims=True)
                l_sigreg1 = arms_mlx.sigreg_mlx(z1_seq, dirs1)
                idm1_logits = model.predict_idm1(z1_seq[:-1], z1_seq[1:])
                l_idm1 = arms_mlx.idm_loss_mlx(idm1_logits, act_seq[:-1])

                z2_seq = model.encode_l2(z1_seq)
                dirs2 = mx.random.normal((spec.SIGREG_NUM_DIRECTIONS, z2_seq.shape[-1]))
                dirs2 = dirs2 / mx.linalg.norm(dirs2, axis=-1, keepdims=True)
                l_sigreg2 = arms_mlx.sigreg_mlx(z2_seq, dirs2)

                loss1 = l_pred1 + float(spec.SIGREG_LAMBDA) * l_sigreg1 + float(spec.IDM_MU) * l_idm1
                loss2 = float(spec.SIGREG_LAMBDA) * l_sigreg2
                return loss1 + loss2

        loss_and_grad_fn = nn.value_and_grad(self.model, loss_fn)
        loss, grads = loss_and_grad_fn(self.model)
        assert self.optimizer is not None
        self.optimizer.update(self.model, grads)
        mx.eval(self.model.parameters(), self.optimizer.state)

        return {"loss": float(loss.item())}

    def rollout_error(self, batch: Mapping[str, Any], H: int) -> float:
        obs_seq = mx.array(batch["observations"], dtype=mx.float32)
        act_seq = mx.array(batch["actions"], dtype=mx.float32)
        dt_seq = mx.array(batch["dts"], dtype=mx.float32)
        if obs_seq.ndim == 3:
            B = obs_seq.shape[0]
            losses = []
            for b in range(B):
                z1_seq = self.model.encode(obs_seq[b])
                targets_z1 = z1_seq[1:H + 1]
                z0 = z1_seq[0]
                loss1 = arms_mlx.multistep_latent_rollout_loss_mlx(
                    self.model, z0, act_seq[b, :H], dt_seq[b, :H], targets_z1
                )
                losses.append(loss1)
            return float(mx.mean(mx.stack(losses)).item())
        else:
            z1_seq = self.model.encode(obs_seq)
            targets_z1 = z1_seq[1:H + 1]
            z0 = z1_seq[0]
            l_pred1 = arms_mlx.multistep_latent_rollout_loss_mlx(
                self.model, z0, act_seq[:H], dt_seq[:H], targets_z1
            )
            return float(l_pred1.item())

    def save(self, path: str | Path) -> str:
        return _save_params(self.model, path)

    def load(self, path: str | Path) -> None:
        _load_params(self.model, path)

    def n_params(self) -> int:
        return arms_mlx.count_params(self.model)

    # --- Planning protocol ---

    def encode(self, obs: np.ndarray) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("encode", 1)
        z1 = self.model.encode(obs)
        return np.asarray(z1, dtype=np.float64)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("predict_l1", 1)
        return self.model.predict_l1(z, a, dt)

    def encode_l2(self, z1: np.ndarray) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("encode_l2", 1)
        z2 = self.model.encode_l2(z1)
        return np.asarray(z2, dtype=np.float64)

    def predict_l2(self, z2: np.ndarray, macro_a: np.ndarray, macro_dt: float = 1.0) -> np.ndarray:
        if self.counter is not None:
            self.counter.charge("predict_l2", 1)
        return self.model.predict_l2(z2, macro_a, macro_dt)

    cost_fn = None  # Uses default squared_distance in planner

    def latents(self, obs_seq: np.ndarray | Sequence[Any]) -> np.ndarray:
        arr = mx.array(obs_seq, dtype=mx.float32)
        z1 = self.model.encode(arr)
        return np.asarray(z1, dtype=np.float64)


def make_mlx_arm(arm_id: str, counter: ForwardCounter | None = None) -> Any:
    """Factory creating an adapted MLX arm satisfying both train and planning protocols."""
    norm = arm_id.lower().replace("-", "_")
    if norm in ("arm_a", "a", "flat_rssm"):
        return MLXArmAAdapter(counter=counter)
    elif norm in ("arm_b", "b", "flat_jepa"):
        return MLXArmBAdapter(counter=counter)
    elif norm in ("arm_c", "c", "hierarchical_hjepa"):
        return MLXArmCAdapter(counter=counter)
    else:
        raise ValueError(f"Unknown arm_id for MLX adapter: {arm_id!r}")


CANONICAL_ARMS = {"a": "arm_a", "arm_a": "arm_a", "b": "arm_b", "arm_b": "arm_b", "c": "arm_c", "arm_c": "arm_c"}


def canonical_arm(arm: str) -> str:
    """Canonical arm id (``arm_a``/``arm_b``/``arm_c``); anything else raises."""
    norm = str(arm).strip().lower().replace("-", "_")
    if norm not in CANONICAL_ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    return CANONICAL_ARMS[norm]


def checkpoint_path(output_root: Path | str, arm: str, seed: int) -> Path:
    """The single registered best-checkpoint location (written by train_runner)."""
    return Path(output_root) / "checkpoints" / canonical_arm(arm) / f"seed{int(seed)}" / "best.ckpt"


def ledger_checkpoint_sha(ledger_path: Path | str, arm: str, seed: int) -> str:
    """Expected checkpoint sha from the completed train run of (arm, seed) in the sqlite ledger.

    Read through ``worker.ledger_read_snapshot`` (never opens the live ledger). Exactly one
    completed train run must exist for the cell and its metrics must carry a 64-hex
    ``checkpoint_sha256``; anything else raises.
    """
    from ainerzero.v9.experiments.s2 import worker

    want_arm = canonical_arm(arm)
    found: list[str] = []
    with worker.ledger_read_snapshot(ledger_path) as store:
        if store is None:
            raise FileNotFoundError(f"ledger not found: {ledger_path}")
        ids = list(worker.LEDGER_EXPERIMENT_IDS)
        placeholders = ", ".join("?" for _ in ids)
        rows = store._conn.execute(
            f"SELECT run_id, state, config_json FROM runs WHERE experiment_id IN ({placeholders})",
            ids,
        ).fetchall()
        for row in rows:
            cfg = json.loads(row["config_json"])
            if cfg.get("mode") != "train" or row["state"] != "completed":
                continue
            if canonical_arm(cfg.get("arm")) != want_arm or int(cfg.get("seed")) != int(seed):
                continue
            metrics = worker.get_run_metrics(store, row["run_id"])
            if not isinstance(metrics, dict):
                raise ValueError(f"train run {row['run_id']} has no recorded metrics")
            sha = metrics.get("checkpoint_sha256")
            if not (isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
                raise ValueError(f"train run {row['run_id']} metrics lack a valid checkpoint_sha256")
            found.append(sha)
    if len(found) != 1:
        raise ValueError(f"expected exactly one completed train run for {want_arm} seed={seed}, found {len(found)}")
    return found[0]


def load_trained_model(
    output_root: Path | str,
    arm: str,
    seed: int,
    *,
    ledger_path: Path | str,
    model_factory: Callable[[str], Any] | None = None,
) -> Any:
    """Load the best checkpoint of (arm, seed) after verifying its sha against the ledger.

    The returned adapter carries no counter (callers charge the episode counter).
    ``model_factory`` exists only so CPU tests can substitute NumPy arms.
    """
    ckpt = checkpoint_path(output_root, arm, seed)
    if not ckpt.is_file():
        raise FileNotFoundError(f"checkpoint missing: {ckpt}")
    expected = ledger_checkpoint_sha(ledger_path, arm, seed)
    actual = _sha256_file(ckpt)
    if actual != expected:
        raise ValueError(f"checkpoint sha mismatch for {canonical_arm(arm)} seed={seed}: ledger {expected}, file {actual}")
    factory = model_factory if model_factory is not None else make_mlx_arm
    model = factory(canonical_arm(arm))
    if getattr(model, "counter", None) is not None:
        raise ValueError("loaded model must carry no counter")
    model.load(ckpt)
    return model


def load_trained_models_for_planning(
    output_root: Path | str,
    *,
    seed: int,
    ledger_path: Path | str,
    arms: Sequence[str] = ("arm_a", "arm_b", "arm_c"),
    model_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Load the (arm, seed) best checkpoints for every arm; ``seed`` is required."""
    return {
        canonical_arm(a): load_trained_model(
            output_root, a, int(seed), ledger_path=ledger_path, model_factory=model_factory
        )
        for a in arms
    }
