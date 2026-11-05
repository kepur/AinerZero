"""The four S1 arms (three trainable MLX-CPU students, one frozen candidate).

Arm 1 is the ainerzero.V9.A2 pinned D candidate: it is only *loaded and
evaluated* (no training, no parameter changes) and its C0 observation contract
is not comparable with the S1 arena payloads.  Arms 2/3/4 are the structure
comparison: an equivariant metric-map memory, an episodic topology graph, and
their combination.  All three share one frozen training protocol (same
optimizer, learning rate, batch size, sequence length, seeds and update budget);
only the memory structure and therefore the parameter count differ.

Memory is deliberately non-parametric (numpy state): writes do not change
network parameters, matching ARCHITECTURE_V9 §1/§3 (episodic-store writes do not
update the network; the metric map is a transformed latent state).  Learned
parts are the observation encoder, the readout projection and the prediction
heads.  The analytic ego-motion integration (G3-style estimated pose) is fixed
code, not a learned module; the pose head only predicts a bounded residual.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from . import data, spec

D = data.FEATURE_DIM
K = data.K


# --- tiny MLX helpers -----------------------------------------------------
def _key(seed: int):
    import mlx.core as mx

    return mx.random.key(int(seed) & 0x7FFFFFFF)


def _params(module) -> list:
    from mlx.utils import tree_flatten

    return list(tree_flatten(module.parameters()))


def count_parameters(module) -> int:
    return int(sum(value.size for _, value in _params(module)))


def parameter_sha256(module) -> str:
    digest = hashlib.sha256()
    for name, value in _params(module):
        array = np.asarray(value)
        digest.update(name.encode("utf-8"))
        digest.update(str(array.shape).encode("utf-8"))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _concat(values):
    import mlx.core as mx

    return mx.concatenate(list(values), axis=-1)


class _Linear(nn.Module):
    """Explicit-key Xavier linear layer (MLX 0.32 nn.Linear takes no key)."""

    def __init__(self, inputs: int, outputs: int, *, key: mx.array):
        super().__init__()
        import math

        bound = math.sqrt(6 / (inputs + outputs))
        self.weight = mx.random.uniform(
            -bound, bound, shape=(outputs, inputs), dtype=mx.float32, key=key
        )
        self.bias = mx.zeros((outputs,), dtype=mx.float32)

    def __call__(self, x: mx.array) -> mx.array:
        return mx.addmm(self.bias, x, self.weight.T)


# --- numpy memory state ---------------------------------------------------
class MetricMapMemory:
    """Agent-centred latent grid transformed by the estimated ego motion."""

    def __init__(self, *, batch_size: int, grid: int, channels: int, extent_m: float, decay: float):
        self.batch_size = int(batch_size)
        self.grid = int(grid)
        self.channels = int(channels)
        self.extent_m = float(extent_m)
        self.decay = float(decay)
        self.cell_m = 2.0 * self.extent_m / self.grid
        self.map = np.zeros((batch_size, grid * grid, channels), dtype=np.float32)

    # -- write ---------------------------------------------------------
    def update(self, values: np.ndarray, xy: np.ndarray, present: np.ndarray) -> None:
        """Bilinear splat write. values [B,C], xy [B,K,2], present [B,K]."""
        half = self.extent_m
        x = (xy[..., 0] + half) / self.cell_m - 0.5
        z = (xy[..., 1] + half) / self.cell_m - 0.5
        x0 = np.floor(x).astype(np.int64)
        z0 = np.floor(z).astype(np.int64)
        fx = (x - x0).astype(np.float32)
        fz = (z - z0).astype(np.float32)
        self.map *= self.decay
        for dx in (0, 1):
            for dz in (0, 1):
                xi = x0 + dx
                zi = z0 + dz
                valid = (xi >= 0) & (xi < self.grid) & (zi >= 0) & (zi < self.grid)
                weight = np.where(valid, (fx if dx else 1.0 - fx) * (fz if dz else 1.0 - fz), 0.0)
                weight = weight * (present > 0) * self.decay
                flat = np.where(valid, zi * self.grid + xi, 0)
                for b in range(self.batch_size):
                    rows = flat[b][valid[b]]
                    if rows.size == 0:
                        continue
                    add = values[b][None, :] * weight[b][valid[b]][:, None]
                    np.add.at(self.map[b], rows, add.astype(np.float32))

    # -- transform -----------------------------------------------------
    def warp(self, motions: np.ndarray) -> None:
        """Re-centre the map by estimated per-step ego motion [B,3] (dx, dz, dyaw)."""
        cells = np.arange(self.grid * self.grid)
        rows, cols = np.divmod(cells, self.grid)
        coord = np.stack(
            [
                (cols - (self.grid - 1) / 2.0) * self.cell_m,
                (rows - (self.grid - 1) / 2.0) * self.cell_m,
            ],
            axis=-1,
        ).astype(np.float32)  # [G*G,2] (x right, z forward)
        flat = self.map.reshape(self.batch_size, self.grid, self.grid, self.channels)
        new_map = np.zeros_like(self.map)
        for b in range(self.batch_size):
            dx, dz, dyaw = (float(motions[b, 0]), float(motions[b, 1]), float(motions[b, 2]))
            rad = np.deg2rad(dyaw)
            cos, sin = np.float32(np.cos(rad)), np.float32(np.sin(rad))
            # destination cell in the new frame -> source coordinates in the old frame
            sx = cos * coord[:, 0] + sin * coord[:, 1] - dx
            sz = -sin * coord[:, 0] + cos * coord[:, 1] - dz
            u = (sx + self.extent_m) / self.cell_m - 0.5
            v = (sz + self.extent_m) / self.cell_m - 0.5
            i0 = np.floor(u).astype(np.int64)
            j0 = np.floor(v).astype(np.int64)
            fu = (u - i0).astype(np.float32)
            fv = (v - j0).astype(np.float32)
            sample = np.zeros((self.grid * self.grid, self.channels), dtype=np.float32)
            for di in (0, 1):
                for dj in (0, 1):
                    ii = i0 + di
                    jj = j0 + dj
                    valid = (ii >= 0) & (ii < self.grid) & (jj >= 0) & (jj < self.grid)
                    weight = (fu if di else 1.0 - fu) * (fv if dj else 1.0 - fv) * valid
                    ii_c = np.clip(ii, 0, self.grid - 1)
                    jj_c = np.clip(jj, 0, self.grid - 1)
                    sample += weight[:, None] * flat[b, jj_c, ii_c]
            new_map[b] = sample
        self.map = new_map

    # -- read ----------------------------------------------------------
    def readout(self, queries: np.ndarray) -> np.ndarray:
        scores = np.einsum("bgc,bc->bg", self.map, queries)
        scores = scores - scores.max(axis=-1, keepdims=True)
        weights = np.exp(scores)
        weights = weights / np.maximum(weights.sum(axis=-1, keepdims=True), 1e-9)
        return np.einsum("bg,bgc->bc", weights, self.map).astype(np.float32)


class TopologyMemory:
    """Non-parametric place graph: nodes written by observation similarity."""

    def __init__(self, *, batch_size: int, place_dim: int, max_nodes: int, match_threshold: float):
        self.batch_size = int(batch_size)
        self.place_dim = int(place_dim)
        self.max_nodes = int(max_nodes)
        self.match_threshold = float(match_threshold)
        self.nodes = np.zeros((batch_size, max_nodes, place_dim), dtype=np.float32)
        self.counts = np.zeros((batch_size, max_nodes), dtype=np.float32)
        self.edges = np.zeros((batch_size, max_nodes, max_nodes), dtype=np.float32)
        self.node_pose = np.zeros((batch_size, max_nodes, 3), dtype=np.float32)
        self.filled = np.zeros((batch_size,), dtype=np.int32)
        self.current = np.full((batch_size,), -1, dtype=np.int32)

    def update(self, places: np.ndarray, poses: np.ndarray) -> np.ndarray:
        """places [B,P], poses [B,3] -> matched node id [B]."""
        matched = np.full((self.batch_size,), -1, dtype=np.int32)
        for b in range(self.batch_size):
            filled = int(self.filled[b])
            place = places[b]
            norm = float(np.linalg.norm(place)) + 1e-9
            if filled > 0:
                node_norms = np.linalg.norm(self.nodes[b, :filled], axis=-1) + 1e-9
                similarity = (self.nodes[b, :filled] @ place) / (node_norms * norm)
                best = int(np.argmax(similarity))
                if similarity[best] >= self.match_threshold:
                    matched[b] = best
            if matched[b] < 0:
                if filled >= self.max_nodes:
                    matched[b] = filled - 1
                else:
                    self.nodes[b, filled] = place
                    self.counts[b, filled] = 1.0
                    self.node_pose[b, filled] = poses[b]
                    self.filled[b] = filled + 1
                    matched[b] = filled
            if self.current[b] >= 0 and matched[b] >= 0:
                self.edges[b, self.current[b], matched[b]] += 1.0
            self.current[b] = matched[b]
        return matched

    def readout(self, queries: np.ndarray) -> np.ndarray:
        out = np.zeros((self.batch_size, self.place_dim), dtype=np.float32)
        for b in range(self.batch_size):
            count = int(self.filled[b])
            if count == 0:
                continue
            nodes = self.nodes[b, :count]
            denom = (np.linalg.norm(nodes, axis=-1) * (float(np.linalg.norm(queries[b])) + 1e-9)) + 1e-9
            scores = (nodes @ queries[b]) / denom
            scores = scores - scores.max()
            weights = np.exp(scores)
            weights = weights / max(float(weights.sum()), 1e-9)
            out[b] = weights @ nodes
        return out

    def adjacency(self) -> np.ndarray:
        return (self.edges > 0).astype(np.float32)


# --- shared loss ----------------------------------------------------------
def prediction_loss(pred, target, *, prediction_weight: float = 1.0):
    """Masked one-step observation prediction loss (MLX arrays)."""
    import mlx.core as mx
    import mlx.nn as nn

    predicted = pred.reshape((-1, K, 10))
    truth = target.reshape((-1, K, 10))
    present = truth[:, :, 3]
    mask = present
    position_error = mx.sum(
        ((predicted[:, :, 0:3] - truth[:, :, 0:3]) ** 2), axis=(-1, -2)
    ) / mx.maximum(3.0 * mx.sum(mask, axis=-1), 1.0)
    position = mx.mean(position_error)
    logit = predicted[:, :, 3]
    label = truth[:, :, 3]
    presence = mx.mean(
        mx.maximum(logit, 0.0) - logit * label + mx.logaddexp(mx.zeros_like(logit), -mx.abs(logit))
    )
    class_logits = predicted[:, :, 4:]
    class_labels = mx.argmax(truth[:, :, 4:], axis=-1)
    class_error = nn.losses.cross_entropy(class_logits, class_labels)
    class_loss = mx.mean(
        mx.sum(class_error * mask, axis=-1) / mx.maximum(mx.sum(mask, axis=-1), 1.0)
    )
    total = prediction_weight * position + 0.2 * presence + 0.2 * class_loss
    return total, {"position": position, "presence": presence, "class": class_loss}


@dataclass
class ArmOutput:
    loss: Any
    metrics: dict
    pose_belief: np.ndarray
    predictions: np.ndarray | None


class TrainableArmBase(nn.Module):
    """Sequence forward: observe -> memory write -> readout -> predict next frame."""

    ARCHITECTURE = "s1_base_v1"

    def __init__(self, dims: Mapping[str, Any], *, seed: int):
        super().__init__()
        self.dims = dict(dims)
        self.seed = int(seed)
        self.hidden = int(dims["hidden"])
        self.readout_dim = int(dims["readout_dim"])
        keys = mx.random.split(_key(seed), num=8)
        self.encoder = [
            _Linear(D, self.hidden, key=keys[0]),
            _Linear(self.hidden, self.hidden, key=keys[1]),
        ]
        self.query = _Linear(self.hidden, self.readout_dim, key=keys[2])
        pose_in = self.hidden + self.readout_dim + 8  # h + context + pose + action
        pred_in = self.hidden + self.readout_dim + 11  # h + context + pose + action + residual
        self.pose_head = [
            _Linear(pose_in, self.hidden, key=keys[3]),
            _Linear(self.hidden, 3, key=keys[4]),
        ]
        self.pred_head = [
            _Linear(pred_in, self.hidden, key=keys[5]),
            _Linear(self.hidden, K * 10, key=keys[6]),
        ]

    def encode(self, obs):
        import mlx.nn as nn

        return nn.silu(self.encoder[1](nn.silu(self.encoder[0](obs))))

    # -- overridable memory hooks -------------------------------------
    def initial_memory(self, batch_size: int):
        raise NotImplementedError

    def memory_update(self, memory, h_np: np.ndarray, xy: np.ndarray, present: np.ndarray, pose) -> None:
        raise NotImplementedError

    def memory_readout(self, memory, query_np: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def memory_warp(self, memory, motions: np.ndarray) -> None:
        return None

    # -- fixed analytic pieces -----------------------------------------
    @staticmethod
    def motion_from_residual(actions: np.ndarray, residual: np.ndarray) -> np.ndarray:
        """Local estimated motion [B,3] = logged motion + bounded learned residual."""
        dx = actions[:, 0] + 0.05 * residual[:, 0]
        dz = actions[:, 2] + 0.05 * residual[:, 1]
        dyaw = actions[:, 3] * 180.0 + 2.0 * residual[:, 2]
        return np.stack([dx, dz, dyaw], axis=-1).astype(np.float32)

    @staticmethod
    def integrate_pose(pose: np.ndarray, motion: np.ndarray) -> np.ndarray:
        """World-frame integration of an agent-frame motion (analytic normalisation)."""
        yaw = np.deg2rad(pose[:, 3].astype(np.float64))
        cos, sin = np.cos(yaw), np.sin(yaw)
        dx = cos * motion[:, 0] + sin * motion[:, 1]
        dz = -sin * motion[:, 0] + cos * motion[:, 1]
        out = pose.copy()
        out[:, 0] += dx.astype(np.float32)
        out[:, 2] += dz.astype(np.float32)
        out[:, 3] += motion[:, 2]
        return out

    # -- forward --------------------------------------------------------
    def forward_loss(self, batch: Mapping[str, np.ndarray], *, burn_in: int | None = None) -> ArmOutput:
        import mlx.core as mx

        burn_in = spec.TRAIN_COMMON["burn_in_steps"] if burn_in is None else int(burn_in)
        obs = np.asarray(batch["obs"], dtype=np.float32)
        actions = np.asarray(batch["actions"], dtype=np.float32)
        targets = np.asarray(batch["targets"], dtype=np.float32)
        xy = np.asarray(batch["det_xy"], dtype=np.float32)
        present = np.asarray(batch["det_present"], dtype=np.float32)
        size, steps_plus_one = obs.shape[0], obs.shape[1]
        steps = steps_plus_one - 1
        memory = self.initial_memory(size)
        pose = np.zeros((size, 4), dtype=np.float32)
        losses = []
        parts: dict[str, list] = {"position": [], "presence": [], "class": []}
        last_pred = None
        for t in range(steps_plus_one):
            h = self.encode(mx.array(obs[:, t]))
            h_np = np.asarray(h)
            self.memory_update(memory, h_np, xy[:, t], present[:, t], pose)
            query = np.asarray(self.query(h))
            context = self.memory_readout(memory, query)
            if t < steps:
                residual, pred = self._heads(h, context, pose)
                motion = self.motion_from_residual(actions[:, t], np.asarray(residual))
                pose = self.integrate_pose(pose, motion)
                self.memory_warp(memory, motion)
                if t >= burn_in:
                    loss, step_parts = prediction_loss(pred, mx.array(targets[:, t]))
                    losses.append(loss)
                    for name, value in step_parts.items():
                        parts[name].append(float(np.asarray(value)))
                last_pred = np.asarray(pred)
        if not losses:
            raise RuntimeError("no prediction step survived the burn-in window")
        total = mx.mean(mx.stack(losses))
        return ArmOutput(
            loss=total,
            metrics={
                name: float(np.mean(values)) if values else float("nan")
                for name, values in parts.items()
            },
            pose_belief=pose,
            predictions=last_pred,
        )

    def _heads(self, h, context: np.ndarray, pose: np.ndarray, action: np.ndarray):
        context_mx = mx.array(np.asarray(context, dtype=np.float32))
        pose_mx = mx.array(np.asarray(pose, dtype=np.float32))
        action_mx = mx.array(np.asarray(action, dtype=np.float32))
        decoder_in = mx.concatenate([h, context_mx, pose_mx, action_mx], axis=-1)
        hidden = mx.maximum(self.pose_head[0](decoder_in), 0.0)
        residual = mx.tanh(self.pose_head[1](hidden))
        # The residual reaches the prediction head through a differentiable
        # MLX input, so the bounded pose residual is trained by the same
        # one-step prediction objective (no truth pose is ever supplied).
        pose_input = mx.concatenate([pose_mx, action_mx, 0.05 * residual], axis=-1)
        features = mx.maximum(
            self.pred_head[0](mx.concatenate([h, context_mx, pose_input], axis=-1)), 0.0
        )
        pred = self.pred_head[1](features).reshape((-1, K, 10))
        return residual, pred

    def forward_terms(self, batch: Mapping[str, np.ndarray], *, burn_in: int | None = None,
                      memory=None, pose=None):
        """Forward pass returning (loss, metric arrays, pose, predictions, memory).

        ``memory``/``pose`` may be supplied to continue an episodic memory across
        bounded calls (the frozen M2/zero-state/history probes do this); the
        default path initialises both exactly as before, so training is unchanged.
        """
        burn_in = spec.TRAIN_COMMON["burn_in_steps"] if burn_in is None else int(burn_in)
        obs = np.asarray(batch["obs"], dtype=np.float32)
        actions = np.asarray(batch["actions"], dtype=np.float32)
        targets = np.asarray(batch["targets"], dtype=np.float32)
        xy = np.asarray(batch["det_xy"], dtype=np.float32)
        present = np.asarray(batch["det_present"], dtype=np.float32)
        size, steps_plus_one = obs.shape[0], obs.shape[1]
        steps = steps_plus_one - 1
        memory = self.initial_memory(size) if memory is None else memory
        pose = (
            np.zeros((size, 4), dtype=np.float32)
            if pose is None
            else np.asarray(pose, dtype=np.float32)
        )
        losses = []
        parts: dict[str, list] = {"position": [], "presence": [], "class": []}
        predictions = None
        for t in range(steps_plus_one):
            h = self.encode(mx.array(obs[:, t]))
            h_np = np.asarray(h)
            self.memory_update(memory, h_np, xy[:, t], present[:, t], pose)
            query = np.asarray(self.query(h))
            context = self.memory_readout(memory, query)
            if t < steps:
                residual, pred = self._heads(h, context, pose, actions[:, t])
                if t >= burn_in:
                    loss_t, parts_t = prediction_loss(pred, mx.array(targets[:, t]))
                    losses.append(loss_t)
                    for name, value in parts_t.items():
                        parts[name].append(value)
                motion = self.motion_from_residual(actions[:, t], np.asarray(residual))
                pose = self.integrate_pose(pose, motion)
                self.memory_warp(memory, motion)
                predictions = np.asarray(pred)
        if not losses:
            raise RuntimeError("no prediction step survived the burn-in window")
        total = mx.mean(mx.stack(losses))
        mean_parts = {
            name: mx.mean(mx.stack(values)) for name, values in parts.items() if values
        }
        return total, mean_parts, pose, predictions, memory

    def forward_loss(self, batch: Mapping[str, np.ndarray], *, burn_in: int | None = None) -> ArmOutput:
        total, parts, pose, predictions, _memory = self.forward_terms(batch, burn_in=burn_in)
        mx.eval(total, *parts.values())
        return ArmOutput(
            loss=total,
            metrics={name: float(np.asarray(value)) for name, value in parts.items()},
            pose_belief=pose,
            predictions=predictions,
        )


def training_loss(model, batch):
    """Loss + aux arrays for nn.value_and_grad (the P1 training step uses this)."""
    total, parts, _pose, _predictions, _memory = model.forward_terms(batch)
    return total, parts


class EquivariantMetricMapArm(TrainableArmBase):
    """Arm 2: equivariant metric map memory (warped by the estimated ego motion)."""

    ARCHITECTURE = "s1_equivariant_metric_map_v1"

    def __init__(self, dims, *, seed):
        channels = int(dims["memory_channels"])
        super().__init__({**dims, "readout_dim": channels}, seed=seed)
        self.channels = channels

    def initial_memory(self, batch_size: int) -> MetricMapMemory:
        return MetricMapMemory(
            batch_size=batch_size,
            grid=int(self.dims["grid"]),
            channels=self.channels,
            extent_m=float(self.dims["extent_m"]),
            decay=float(self.dims["decay"]),
        )

    def memory_update(self, memory: MetricMapMemory, h_np, xy, present, pose) -> None:
        memory.update(h_np[:, : self.channels], xy, present)

    def memory_readout(self, memory: MetricMapMemory, query_np) -> np.ndarray:
        return memory.readout(query_np)

    def memory_warp(self, memory: MetricMapMemory, motions) -> None:
        memory.warp(motions)


class EpisodicTopologyArm(TrainableArmBase):
    """Arm 3: episodic topology graph memory (non-parametric place store)."""

    ARCHITECTURE = "s1_episodic_topology_graph_v1"

    def __init__(self, dims, *, seed):
        place_dim = int(dims["place_dim"])
        super().__init__({**dims, "readout_dim": place_dim}, seed=seed)
        self.place_dim = place_dim

    def initial_memory(self, batch_size: int) -> TopologyMemory:
        return TopologyMemory(
            batch_size=batch_size,
            place_dim=self.place_dim,
            max_nodes=int(self.dims["max_nodes"]),
            match_threshold=float(self.dims["match_threshold"]),
        )

    def memory_update(self, memory: TopologyMemory, h_np, xy, present, pose) -> None:
        places = h_np[:, : self.place_dim]
        memory.update(places, pose[:, [0, 2, 3]])

    def memory_readout(self, memory: TopologyMemory, query_np) -> np.ndarray:
        return memory.readout(query_np)


class MetricPlusTopologyArm(TrainableArmBase):
    """Arm 4: both memories, fused readout (the registered combination arm)."""

    ARCHITECTURE = "s1_metric_plus_topology_v1"

    def __init__(self, dims, *, seed):
        channels = int(dims["memory_channels"])
        place_dim = int(dims["place_dim"])
        super().__init__({**dims, "readout_dim": channels + place_dim}, seed=seed)
        self.channels = channels
        self.place_dim = place_dim

    def initial_memory(self, batch_size: int) -> dict:
        return {
            "map": MetricMapMemory(
                batch_size=batch_size,
                grid=int(self.dims["grid"]),
                channels=self.channels,
                extent_m=float(self.dims["extent_m"]),
                decay=float(self.dims["decay"]),
            ),
            "graph": TopologyMemory(
                batch_size=batch_size,
                place_dim=self.place_dim,
                max_nodes=int(self.dims["max_nodes"]),
                match_threshold=float(self.dims["match_threshold"]),
            ),
        }

    def memory_update(self, memory, h_np, xy, present, pose) -> None:
        memory["map"].update(h_np[:, : self.channels], xy, present)
        memory["graph"].update(h_np[:, self.channels : self.channels + self.place_dim], pose[:, [0, 2, 3]])

    def memory_readout(self, memory, query_np) -> np.ndarray:
        map_context = memory["map"].readout(query_np[:, : self.channels])
        graph_context = memory["graph"].readout(query_np[:, self.channels :])
        return np.concatenate([map_context, graph_context], axis=-1)

    def memory_warp(self, memory, motions) -> None:
        memory["map"].warp(motions)


ARM_CLASSES = {
    "arm2": (EquivariantMetricMapArm, spec.ARM_SPECS["arm2"]["dims"]),
    "arm3": (EpisodicTopologyArm, spec.ARM_SPECS["arm3"]["dims"]),
    "arm4": (MetricPlusTopologyArm, spec.ARM_SPECS["arm4"]["dims"]),
}


def build_trainable_arm(arm_id: str, *, seed: int):
    if arm_id not in ARM_CLASSES:
        raise KeyError(f"{arm_id!r} is not a trainable S1 arm")
    cls, dims = ARM_CLASSES[arm_id]
    return cls(dims, seed=seed)


def parameter_report(arm_id: str, *, seed: int = 0) -> dict:
    model = build_trainable_arm(arm_id, seed=seed)
    return {
        "arm_id": arm_id,
        "architecture": model.ARCHITECTURE,
        "parameter_count": count_parameters(model),
        "seed": seed,
    }


# --- arm 1: A2-pinned D candidate ----------------------------------------
D_PILOT_DIR = spec.ARM_SPECS["arm1"]["identity"]["pilot_dir"]
D_CHECKPOINT_ID = spec.ARM_SPECS["arm1"]["identity"]["checkpoint_id"]


def verify_d_candidate_identity(repo_root: Path | None = None) -> dict:
    """Recompute the A2 manifest SHA-256 of every pinned D-candidate file.

    r8 (S1-R8-DECISION F6/F7): the byte-level trust-root verification lives in
    the stdlib-only :mod:`ainerzero.v9.experiments.s1.identity` module, so a CPU
    identity check never imports MLX.  This wrapper stays for the MLX-side
    loaders that already imported this module.
    """
    from . import identity as identity_module

    return identity_module.verify_d_candidate_identity(repo_root)



def load_d_candidate(repo_root: Path | None = None):
    """Load the frozen D candidate for evaluation only (never trained here)."""
    import mlx.core as mx
    from mlx.utils import tree_flatten, tree_unflatten

    from ainerzero.core.pilot import PilotModel
    from ainerzero.learning.pilot_model import SharedSymbolPredictor
    from ainerzero.runtime.checkpoints import load_checkpoint

    root = Path(repo_root or spec.REPO_ROOT)
    identity = verify_d_candidate_identity(root)
    checkpoint_dir = root / identity["pilot_dir"] / "checkpoints" / D_CHECKPOINT_ID
    tensors, metadata = load_checkpoint(checkpoint_dir)
    if metadata.get("architecture") != spec.ARM_SPECS["arm1"]["architecture"]:
        raise RuntimeError(
            f"D candidate architecture {metadata.get('architecture')!r} differs from the "
            f"registered {spec.ARM_SPECS['arm1']['architecture']!r}"
        )
    config = PilotModel.model_validate(metadata["config"]["model"])
    model = SharedSymbolPredictor(config, key=mx.random.key(0))
    model.update(
        tree_unflatten([(name[6:], mx.array(value)) for name, value in tensors.items() if name.startswith("model.")])
    )
    mx.eval(model.parameters())
    from mlx.utils import tree_flatten as _flatten

    loaded = dict(_flatten(model.parameters()))
    mismatch = [
        name
        for name, value in tensors.items()
        if name.startswith("model.")
        and (name[6:] not in loaded or np.asarray(loaded[name[6:]]).shape != value.shape)
    ]
    if mismatch:
        raise RuntimeError(f"D candidate tensors do not match the architecture: {mismatch[:5]}")
    return model, {
        "identity": identity,
        "architecture": metadata.get("architecture"),
        "optimizer_steps": metadata.get("optimizer_steps"),
        "parameter_count": count_parameters(model),
        "parameter_sha256": parameter_sha256(model),
        "run_id": metadata.get("run_id"),
        "experiment_id": metadata.get("experiment_id", spec.ARM_SPECS["arm1"]["identity"]["experiment_id"]),
    }


def d_candidate_fixed_batch(repo_root: Path | None = None) -> dict:
    root = Path(repo_root or spec.REPO_ROOT)
    path = root / D_PILOT_DIR / "fixed-batch.npz"
    if not path.is_file():
        raise FileNotFoundError(f"D candidate fixed batch is missing: {path}")
    with np.load(path) as payload:
        return {name: np.asarray(payload[name]) for name in payload.files}


def d_candidate_forward_loss(model, batch: Mapping[str, np.ndarray], *, seed: int = 0) -> ArmOutput:
    """Forward + observation loss on the fixed batch; no optimizer, no update."""
    import mlx.core as mx

    from ainerzero.learning.pilot_model import observation_loss

    keys = mx.random.split(mx.random.key(int(seed) & 0x7FFFFFFF), num=2)
    symbols = np.asarray(batch["symbols"], dtype=np.int32)
    visible = np.asarray(batch["visible_mask"], dtype=bool)
    cursor = np.asarray(batch["cursor"], dtype=np.int32)
    actions = np.asarray(batch["actions"], dtype=np.int32)
    size = symbols.shape[0]
    h, _ = model.initial(size)
    posterior = model.observe(
        h, mx.array(symbols[:, 0]), mx.array(visible[:, 0]), mx.array(cursor[:, 0]), key=keys[0]
    )
    loss0, nll0 = observation_loss(
        posterior["logits"], mx.array(symbols[:, 0]), mx.array(visible[:, 0]), mx.array(cursor[:, 0])
    )
    imagined = model.imagine(
        posterior["h"], posterior["z"], mx.array(actions[:, 0]), key=keys[1]
    )
    loss1, nll1 = observation_loss(
        imagined["logits"], mx.array(symbols[:, 1]), mx.array(visible[:, 1]), mx.array(cursor[:, 1])
    )
    total = mx.mean(loss0) + mx.mean(loss1)
    return ArmOutput(
        loss=total,
        metrics={
            "observation_loss_t0": float(np.asarray(mx.mean(loss0))),
            "observation_loss_t1": float(np.asarray(mx.mean(loss1))),
            "symbol_nll_t0": float(np.asarray(mx.mean(nll0))),
            "symbol_nll_t1": float(np.asarray(mx.mean(nll1))),
        },
        pose_belief=np.zeros((size, 4), dtype=np.float32),
        predictions=None,
    )


def arm_parameter_counts() -> dict:
    """Parameter count for every arm, for the preregistration document."""
    counts = {}
    for arm_id in ("arm2", "arm3", "arm4"):
        counts[arm_id] = parameter_report(arm_id)["parameter_count"]
    try:
        _, info = load_d_candidate()
        counts["arm1"] = int(info["parameter_count"])
    except Exception as exc:  # pragma: no cover - reported, never silently invented
        counts["arm1"] = None
        counts["arm1_error"] = f"{type(exc).__name__}: {exc}"
    return counts
