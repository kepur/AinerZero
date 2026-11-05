"""Numeric backend seam for the S1 worker.

The production backend (``MlxBackend``) is the only place that imports MLX.  The
training control flow, budget reservations, checkpoint policy and metric
orchestration live in :mod:`worker` and :mod:`evaluation`; a controlled CPU
backend can therefore execute the *same* ``_train`` control flow in tests
without importing MLX or running a real model.  A substitute backend is a test
instrument, not a capability result.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from . import data, spec


class BackendError(RuntimeError):
    """The numeric backend could not produce a required array."""


class MlxBackend:
    """MLX-CPU implementation used by the production worker (never in CPU tests)."""

    name = "mlx-cpu"

    # -- model / optimizer -------------------------------------------------
    def build_model(self, arm_id: str, seed: int):
        from . import arms

        return arms.build_trainable_arm(arm_id, seed=int(seed))

    def make_optimizer(self, protocol: Mapping[str, Any]):
        import mlx.optimizers as optim

        optimizer = optim.AdamW(
            learning_rate=float(protocol["learning_rate"]),
            betas=tuple(protocol["adam_betas"]),
            eps=float(protocol["adam_epsilon"]),
            weight_decay=float(protocol["weight_decay"]),
        )
        return optimizer

    def init_optimizer(self, optimizer, model) -> None:
        optimizer.init(model.trainable_parameters())

    def value_and_grad(self, model):
        import mlx.nn as nn

        from . import arms

        return nn.value_and_grad(model, arms.training_loss)

    def eval(self, *values) -> None:
        import mlx.core as mx

        mx.eval(*values)

    def clip_grad_norm(self, grads, norm: float):
        import mlx.optimizers as optim

        return optim.clip_grad_norm(grads, float(norm))

    def optimizer_update(self, optimizer, model, grads) -> None:
        optimizer.update(model, grads)

    def sync_parameters(self, model, optimizer) -> None:
        import mlx.core as mx

        mx.eval(model.parameters(), optimizer.state)

    def loss_value(self, loss) -> float:
        return float(np.asarray(loss))

    def parameter_sha256(self, model) -> str:
        from . import arms

        return arms.parameter_sha256(model)

    def save_params(self, model, path: Path, *, exclusive: bool = False) -> None:
        from . import arms

        params = {name: np.asarray(value) for name, value in arms._params(model)}
        path = Path(path)
        if exclusive:
            if path.exists():
                raise FileExistsError(f"refusing to overwrite checkpoint {path}")
            with open(path, "xb") as handle:
                np.savez(handle, **params)
            return
        np.savez(path, **params)

    def load_params(self, model, path: Path) -> None:
        from mlx.utils import tree_unflatten

        import mlx.core as mx

        with np.load(path) as loaded:
            params = {name: mx.array(loaded[name]) for name in loaded.files}
            model.update(tree_unflatten(list(params.items())))
            mx.eval(model.parameters())

    def encode(self, model, obs_row) -> np.ndarray:
        """Encoder embedding for one observation row (no parameter update)."""
        import mlx.core as mx

        return np.asarray(model.encode(mx.array(np.asarray(obs_row, dtype=np.float32)[None, :])))[0]

    # -- bounded sequence execution ---------------------------------------
    def step_sequence(
        self,
        model,
        sequence: Mapping[str, Any],
        *,
        stop: int | None = None,
        memory=None,
        pose=None,
    ) -> dict:
        """Run every one-step prediction of an episode, carrying memory/pose.

        Returns the per-step loss/pose/prediction rows plus the final memory.
        No optimizer is created or updated.
        """
        frames = len(sequence["obs"]) if stop is None else int(stop)
        if frames < 2:
            raise BackendError("a sequence probe needs at least two frames")
        steps: list[dict] = []
        current_memory = memory
        current_pose = (
            np.zeros((1, 4), dtype=np.float32)
            if pose is None
            else np.asarray(pose, dtype=np.float32).reshape((1, 4))
        )
        for t in range(frames - 1):
            batch = data.sequence_batch(sequence, t, t + 2)
            loss, parts, current_pose, predictions, current_memory = model.forward_terms(
                batch, burn_in=0, memory=current_memory, pose=current_pose
            )
            self.eval(loss, *parts.values())
            steps.append(
                {
                    "frame": t + 1,
                    "loss": float(np.asarray(loss)),
                    "pose": np.asarray(current_pose)[0].copy(),
                    "predictions": None
                    if predictions is None
                    else np.asarray(predictions)[0].copy(),
                    "parts": {name: float(np.asarray(value)) for name, value in parts.items()},
                }
            )
        return {"steps": steps, "memory": current_memory, "pose": np.asarray(current_pose)}

    # -- memory probe graph ------------------------------------------------
    def probe_graph(self, model, memory, pose=None) -> dict:
        """Nodes/positions/edges of the arm's episodic place graph.

        Topology memories expose their own nodes and adjacency; the metric-map
        arm exposes occupied metric cells in the current agent frame, rotated
        into the episode frame with the carried pose.  This is the arm's real
        memory state, not a synthetic graph.
        """
        if memory is None:
            return {"nodes": np.zeros((0, 1)), "positions": np.zeros((0, 2)), "edges": set(), "threshold": 0.0}
        graph = memory["graph"] if isinstance(memory, dict) and "graph" in memory else memory
        if hasattr(graph, "nodes") and hasattr(graph, "edges"):
            count = int(graph.filled[0])
            if count <= 0:
                return {"nodes": np.zeros((0, 1)), "positions": np.zeros((0, 2)), "edges": set(), "threshold": 0.0}
            nodes = np.asarray(graph.nodes[0, :count], dtype=np.float64)
            positions = np.asarray(graph.node_pose[0, :count, :2], dtype=np.float64)
            adjacency = np.asarray(graph.adjacency()[0, :count, :count])
            edges = {
                (int(i), int(j))
                for i in range(count)
                for j in range(i + 1, count)
                if adjacency[i, j] > 0 and adjacency[j, i] > 0
            }
            return {
                "nodes": nodes,
                "positions": positions,
                "edges": edges,
                "threshold": float(getattr(graph, "match_threshold", 0.0)),
            }
        if hasattr(graph, "map"):
            grid = int(graph.grid)
            extent = float(graph.extent_m)
            cell_m = float(graph.cell_m)
            flat = np.asarray(graph.map[0], dtype=np.float64)
            norms = np.linalg.norm(flat, axis=-1)
            occupied = norms > 1e-6
            if not np.any(occupied):
                return {"nodes": np.zeros((0, flat.shape[-1])), "positions": np.zeros((0, 2)), "edges": set(), "threshold": 0.0}
            index = np.where(occupied)[0]
            rows, cols = np.divmod(index, grid)
            local = np.stack(
                [
                    (cols - (grid - 1) / 2.0) * cell_m,
                    (rows - (grid - 1) / 2.0) * cell_m,
                ],
                axis=-1,
            )
            if pose is None:
                positions = local
            else:
                anchor = np.asarray(pose, dtype=np.float64).reshape(-1)[:4]
                yaw = np.deg2rad(anchor[3])
                cos, sin = np.cos(yaw), np.sin(yaw)
                positions = np.stack(
                    [
                        anchor[0] + cos * local[:, 0] + sin * local[:, 1],
                        anchor[2] - sin * local[:, 0] + cos * local[:, 1],
                    ],
                    axis=-1,
                )
            occupied_cells = {(int(r), int(c)) for r, c in zip(rows, cols)}
            remap = {cell: position for cell, position in zip(index, range(len(index)))}
            edges = set()
            for cell, index_a in remap.items():
                r, c = cell
                for neighbour in ((r + 1, c), (r, c + 1)):
                    if neighbour in occupied_cells:
                        edges.add((int(index_a), int(remap[neighbour])))
            return {
                "nodes": flat[index],
                "positions": positions,
                "edges": edges,
                "threshold": 0.0,
            }
        return {"nodes": np.zeros((0, 1)), "positions": np.zeros((0, 2)), "edges": set(), "threshold": 0.0}

    # -- development probe (training checkpoints and eval) -----------------
    def window_probe(
        self,
        model,
        windows: Mapping[str, Any],
        protocol: Mapping[str, Any],
        *,
        max_batches: int | None = None,
    ) -> dict:
        """Deterministic development window probe returning raw per-window rows.

        Uses contiguous, non-overlapping batches of the frozen development
        windows; the caller owns tick/truth alignment.
        """
        batch_size = int(protocol["batch_size"])
        count = len(windows.get("obs", []))
        if count < 1:
            raise BackendError("development window probe has no windows")
        batch_count = (count + batch_size - 1) // batch_size
        limit = int(protocol.get("eval_batches", spec.TIMING["eval_batches"]))
        if max_batches is not None:
            limit = min(limit, int(max_batches))
        batch_count = min(batch_count, max(limit, 1))
        rows = []
        for batch_index in range(batch_count):
            start_index = batch_index * batch_size
            indices = np.arange(start_index, min(start_index + batch_size, count))
            if len(indices) == 0:
                continue
            batch = data.sample_batch(windows, indices)
            output = model.forward_loss(batch)
            self.eval(output.loss)
            pose = np.asarray(output.pose_belief, dtype=np.float64).copy()
            predictions = (
                None if output.predictions is None else np.asarray(output.predictions, dtype=np.float64).copy()
            )
            for offset, window_index in enumerate(indices):
                meta = windows["windows"][int(window_index)]
                rows.append(
                    {
                        "window_index": int(window_index),
                        "episode_id": meta["episode_id"],
                        "start": int(meta["start"]),
                        "target_frame": int(meta["start"]) + 1,
                        "loss": float(np.asarray(output.loss)),
                        "parts": {
                            str(name): float(value) for name, value in (output.metrics or {}).items()
                        },
                        "pose": pose[offset].copy(),
                        "prediction": None if predictions is None else predictions[offset].copy(),
                        "target": np.asarray(windows["targets"][int(window_index)][0], dtype=np.float64).copy(),
                    }
                )
        return {
            "rows": rows,
            "batches": batch_count,
            "windows": len(rows),
        }


def copy_memory(memory):
    """Deep copy a non-parametric memory state (no parameters, numpy only)."""
    return None if memory is None else copy.deepcopy(memory)
