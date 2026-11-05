"""Identity-aligned S1 evaluation orchestration (pure numpy, duck-typed backend).

Everything here is independent of MLX: the numeric backend supplies per-step
poses/predictions/memory, and this module applies the frozen metric definitions
with explicit episode/world/tick identity.  The same code is used by the
production worker and by the CPU tests with a substitute backend.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from . import data, metrics, spec
from .runtime import BackendError, copy_memory


class EvaluationError(RuntimeError):
    """A frozen metric cannot be computed without inventing a value."""


def align_relative_pose(relative: np.ndarray, anchor: Sequence[float]) -> np.ndarray:
    """Move an episode-relative pose into the evaluator frame.

    The model integrates from zero position/yaw at the window start.  The
    evaluator anchor is the truth pose of that same tick; truth is never an
    input to the model.  Translation is rotated by the anchor yaw with the same
    convention as ``TrainableArmBase.integrate_pose``.
    """
    pose = np.asarray(relative, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64).reshape(4)
    yaw = np.deg2rad(anchor[3])
    cos, sin = np.cos(yaw), np.sin(yaw)
    x = anchor[0] + cos * pose[..., 0] + sin * pose[..., 2]
    z = anchor[2] - sin * pose[..., 0] + cos * pose[..., 2]
    yaw_out = (anchor[3] + pose[..., 3] + 180.0) % 360.0 - 180.0
    out = np.empty_like(pose)
    out[..., 0] = x
    out[..., 1] = pose[..., 1]
    out[..., 2] = z
    out[..., 3] = yaw_out
    return out


def truth_index(truth_view: Sequence[data.TruthEpisode]) -> dict[str, data.TruthEpisode]:
    index = {episode.episode_id: episode for episode in truth_view}
    if len(index) != len(truth_view):
        raise EvaluationError("duplicate episode id in the evaluator truth view")
    return index


def relative_cells(episode: data.TruthEpisode) -> list[tuple[int, int]]:
    """Visited cells in the episode-relative frame (origin = first truth pose).

    Cells are rounded in the world frame and then translated, so the relative
    graph is exactly the world-frame visited graph moved by an integer origin.
    """
    poses = data.truth_pose_sequence(episode)
    if len(poses) == 0:
        return []
    origin_x = int(round(float(poses[0][0])))
    origin_z = int(round(float(poses[0][2])))
    cells: list[tuple[int, int]] = []
    for pose in poses:
        cell = (
            int(round(float(pose[0]))) - origin_x,
            int(round(float(pose[2]))) - origin_z,
        )
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return cells


def relative_cell_path(episode: data.TruthEpisode) -> list[tuple[int, int]]:
    """Per-step relative cell path, one entry for every truth step.

    ``relative_cells`` deduplicates consecutive stays and therefore cannot be
    indexed by a step/tick number.  Transition-level metrics (loop pairs, the
    few-shot query edge) must use this aligned path instead; real development
    episodes often stay in one cell for several ticks.
    """
    poses = data.truth_pose_sequence(episode)
    if len(poses) == 0:
        return []
    origin_x = int(round(float(poses[0][0])))
    origin_z = int(round(float(poses[0][2])))
    return [
        (
            int(round(float(pose[0]))) - origin_x,
            int(round(float(pose[2]))) - origin_z,
        )
        for pose in poses
    ]


def relative_free_adjacency(episode: data.TruthEpisode) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """True free-space adjacency of the episode, translated to relative cells."""
    poses = data.truth_pose_sequence(episode)
    if len(poses) == 0:
        return set()
    origin_x = int(round(float(poses[0][0])))
    origin_z = int(round(float(poses[0][2])))
    width = int(episode.world["width"])
    height = int(episode.world["height"])
    blocked = {(int(x), int(z)) for x, z in episode.world["blocked"]}
    visited = set(relative_cells(episode))
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for cell in visited:
        x, z = cell
        for nx, nz in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if (nx, nz) not in visited:
                continue
            ax, az = x + origin_x, z + origin_z
            bx, bz = nx + origin_x, nz + origin_z
            if not (0 <= bx < width and 0 <= bz < height):
                continue
            if (ax, az) in blocked or (bx, bz) in blocked:
                continue
            edges.add(tuple(sorted((cell, (nx, nz)))))
    return edges


def _truth_step(episode: data.TruthEpisode, index: int) -> dict:
    if not 0 <= index < len(episode.steps):
        raise EvaluationError(
            f"episode {episode.episode_id} has no truth step {index} "
            f"(steps={len(episode.steps)})"
        )
    return episode.steps[index]


def development_rows(
    probe: Mapping[str, Any],
    truth_view: Sequence[data.TruthEpisode],
    *,
    allow_partial: bool = True,
) -> list[dict]:
    """Tick-aligned per-episode localization/NLL rows from a window probe."""
    by_id = truth_index(truth_view)
    grouped: dict[str, list[dict]] = {}
    for row in probe["rows"]:
        episode_id = row["episode_id"]
        if episode_id not in by_id:
            raise EvaluationError(f"window episode {episode_id} has no truth row")
        episode = by_id[episode_id]
        start = int(row["start"])
        target = start + 1
        if target >= len(episode.steps):
            raise EvaluationError(
                f"window target step {target} is outside episode {episode_id} truth"
            )
        anchor = data.truth_pose_sequence(episode)[start]
        estimate = align_relative_pose(np.asarray(row["pose"]), anchor)
        truth = data.truth_pose_sequence(episode)[target]
        tick = int(_truth_step(episode, target).get("tick", target))
        parts = row.get("parts") or {}
        nll = None
        if "presence" in parts and "class" in parts:
            nll = float(parts["presence"]) + float(parts["class"])
        grouped.setdefault(episode_id, []).append(
            {
                "tick": tick,
                "target_frame": target,
                "estimate": estimate,
                "truth": truth,
                "prediction_nll": nll if nll is not None else float(row["loss"]),
                "prediction_position_mse": parts.get("position"),
            }
        )
    rows: list[dict] = []
    for episode_id, entries in sorted(grouped.items()):
        entries.sort(key=lambda item: item["tick"])
        ticks = [item["tick"] for item in entries]
        if len(set(ticks)) != len(ticks):
            raise EvaluationError(f"episode {episode_id} produced duplicate scored ticks")
        episode = by_id[episode_id]
        cells = relative_cell_path(episode)
        pairs = metrics.revisit_pairs(cells)
        tick_to_index = {tick: index for index, tick in enumerate(ticks)}
        step_tick = {
            index: int(step.get("tick", index)) for index, step in enumerate(episode.steps)
        }
        loop_pairs = []
        for first, second in pairs:
            tick_a, tick_b = step_tick.get(first), step_tick.get(second)
            if tick_a in tick_to_index and tick_b in tick_to_index:
                loop_pairs.append((tick_to_index[tick_a], tick_to_index[tick_b]))
        row = metrics.episode_localization_row(
            episode_id=episode_id,
            scene_id=episode.scene_id,
            family=episode.family or "unknown",
            ticks=ticks,
            estimate=np.stack([item["estimate"] for item in entries]),
            truth=np.stack([item["truth"] for item in entries]),
            prediction_nll=float(np.mean([item["prediction_nll"] for item in entries])),
            loop_pairs=loop_pairs,
        )
        row["prediction_position_mse"] = float(
            np.mean(
                [
                    item["prediction_position_mse"]
                    for item in entries
                    if item["prediction_position_mse"] is not None
                ]
            )
        ) if any(item["prediction_position_mse"] is not None for item in entries) else None
        rows.append(row)
    if not rows:
        raise EvaluationError("development probe produced no scored episode rows")
    if not allow_partial and len(rows) != len(truth_view):
        raise EvaluationError(
            f"development probe covered {len(rows)} of {len(truth_view)} development worlds"
        )
    return rows


def localization_report(rows: Sequence[Mapping]) -> dict:
    unseen = metrics.strict_unseen_map(rows)
    closures = [row["loop_closure"] for row in rows if row.get("loop_closure")]
    if closures:
        loop = {
            "status": "completed",
            "episodes_with_revisit": len(closures),
            "distance_error_mean_m": float(
                np.mean([row["distance_error_mean_m"] for row in closures])
            ),
            "yaw_error_mean_deg": float(
                np.mean([row["yaw_error_mean_deg"] for row in closures])
            ),
            "pairs": int(sum(row["pairs"] for row in closures)),
        }
    else:
        loop = {
            "status": "no_samples",
            "message": "no scored episode contained a non-consecutive revisit; the "
            "loop-closure segment is not replaced by a zero",
        }
    return {
        "status": "completed",
        "localization_error": {
            "episodes": unseen["episodes"],
            "worlds": unseen["worlds"],
            "translation_mean_m": unseen["translation_mean_m"],
            "translation_median_m": unseen["translation_median_m"],
            "yaw_mean_deg": unseen["yaw_mean_deg"],
            "alignment_rule": unseen["alignment_rule"],
        },
        "loop_closure": loop,
        "unseen": unseen,
    }


def topology_report(
    backend,
    model,
    sequences: Sequence[Mapping],
    truth_view: Sequence[data.TruthEpisode],
) -> dict:
    by_id = truth_index(truth_view)
    rows = []
    for sequence in sequences:
        episode = by_id[sequence["episode_id"]]
        run = backend.step_sequence(model, sequence)
        graph = backend.probe_graph(model, run["memory"], pose=run["pose"][-1])
        cells = relative_cells(episode)
        truth_edges = relative_free_adjacency(episode)
        result = metrics.topology_edge_metrics(
            np.asarray(graph["positions"]).tolist(),
            sorted(graph["edges"]),
            cells,
            truth_edges,
        )
        rows.append(
            {
                "episode_id": episode.episode_id,
                "scene_id": episode.scene_id,
                "family": episode.family or "unknown",
                **result,
            }
        )
    return metrics.topology_report(rows)


def _cosine_match(nodes: np.ndarray, query: np.ndarray, threshold: float) -> int | None:
    if len(nodes) == 0:
        return None
    denom = np.linalg.norm(nodes, axis=-1) * (float(np.linalg.norm(query)) + 1e-9) + 1e-9
    similarity = (nodes @ query) / denom
    best = int(np.argmax(similarity))
    if float(similarity[best]) < float(threshold):
        return None
    return best


def few_shot_report(
    backend,
    model,
    sequences: Sequence[Mapping],
    truth_view: Sequence[data.TruthEpisode],
    *,
    k_values: Sequence[int] = (0, 1, 2, 4, 8),
    query_limit: int | None = None,
    preregistration: Mapping | None = None,
) -> dict:
    """Real k-support/query probe over the arm's episodic memory.

    Support transitions are written by running the model over the support
    prefix (no optimizer exists in this path).  Query transitions are disjoint
    and scored against the evaluator truth graph/displacement.  When a world
    cannot supply k support transitions plus one held-out query, that k value is
    reported ``insufficient_data`` for that world; a k value with no query
    anywhere fails closed.

    ``query_limit`` must come from a verified preregistration
    (``preregistration=...``) or be passed explicitly by a CPU fixture that
    already pinned the registered value.  There is no code-only default.
    """
    if preregistration is not None:
        resolved = metrics.require_query_limit(preregistration)
        if query_limit is not None and int(query_limit) != resolved:
            raise metrics.QueryLimitError(
                f"caller query_limit {query_limit!r} differs from preregistration "
                f"{resolved}"
            )
        query_limit = resolved
    elif query_limit is None:
        raise metrics.QueryLimitError(
            "few_shot_report requires preregistration evaluation.query_limit "
            "(or an explicit registered query_limit in CPU fixtures)"
        )
    else:
        # Fixture path: still refuse values other than the registered one.
        if int(query_limit) != int(spec.EVALUATION["query_limit"]):
            raise metrics.QueryLimitError(
                f"query_limit {query_limit!r} differs from the registered "
                f"{spec.EVALUATION['query_limit']}"
            )
        query_limit = int(query_limit)
    by_id = truth_index(truth_view)
    per_k: dict[int, dict] = {}
    for k in k_values:
        predicted_exists: list[bool] = []
        true_exists: list[bool] = []
        displacement_errors: list[float] = []
        worlds = 0
        unavailable: list[str] = []
        by_world: dict[str, dict] = {}
        for sequence in sequences:
            episode = by_id[sequence["episode_id"]]
            transitions = max(len(episode.steps) - 1, 0)
            support, query = metrics.split_support_query(
                transitions, int(k), query_limit=int(query_limit)
            )
            if not query:
                unavailable.append(episode.episode_id)
                continue
            memory = None
            if support:
                # ``stop`` is an exclusive frame bound, so covering support
                # transition ``support[-1]`` (which consumes frames
                # ``support[-1]`` and ``support[-1] + 1``) needs
                # ``support[-1] + 2``.  The r5 code used ``+ 1``: k=1 asked for
                # a single frame (BackendError) and k=2/k=4 silently wrote one
                # support transition fewer than frozen k.
                run = backend.step_sequence(model, sequence, stop=support[-1] + 2)
                memory = run["memory"]
            graph = backend.probe_graph(model, memory)
            cells = relative_cell_path(episode)
            truth_edges = relative_free_adjacency(episode)
            poses = data.truth_pose_sequence(episode)
            ticks: list[int] = []
            for index in query:
                h_start = backend.encode(model, sequence["obs"][index])
                h_end = backend.encode(model, sequence["obs"][index + 1])
                match_start = _cosine_match(
                    np.asarray(graph["nodes"], dtype=np.float64),
                    np.asarray(h_start, dtype=np.float64),
                    float(graph.get("threshold", 0.0)),
                )
                match_end = _cosine_match(
                    np.asarray(graph["nodes"], dtype=np.float64),
                    np.asarray(h_end, dtype=np.float64),
                    float(graph.get("threshold", 0.0)),
                )
                predicted = bool(
                    match_start is not None
                    and match_end is not None
                    and tuple(sorted((match_start, match_end))) in graph["edges"]
                )
                true_edge = tuple(sorted((cells[index], cells[index + 1])))
                predicted_exists.append(predicted)
                true_exists.append(true_edge in truth_edges)
                ticks.append(int(episode.steps[index + 1].get("tick", index + 1)))
                if match_start is not None and match_end is not None:
                    positions = np.asarray(graph["positions"], dtype=np.float64)
                    predicted_m = float(
                        np.linalg.norm(positions[match_start] - positions[match_end])
                    )
                    true_m = float(
                        np.linalg.norm(poses[index + 1] - poses[index])
                    )
                    displacement_errors.append(abs(predicted_m - true_m))
            worlds += 1
            by_world[episode.episode_id] = {
                "transitions": transitions,
                "support": len(support),
                "queries": len(query),
                "target_ticks": ticks,
            }
        if not predicted_exists:
            per_k[k] = {
                "k": int(k),
                "queries": 0,
                "support": int(k),
                "worlds": 0,
                "reason": "no development world supplied k support transitions plus a "
                "held-out query",
                "unavailable_worlds": len(unavailable),
            }
            continue
        result = metrics.few_shot_transition_metrics(predicted_exists, true_exists)
        result.update(
            {
                "k": int(k),
                "support": int(k),
                "queries": len(predicted_exists),
                "worlds": worlds,
                "edge_samples": len(predicted_exists),
                "displacement_samples": len(displacement_errors),
                "displacement_mae_m": (
                    float(np.mean(displacement_errors)) if displacement_errors else None
                ),
                "by_world": by_world,
                "unavailable_worlds": len(unavailable),
            }
        )
        per_k[k] = result
    return metrics.few_shot_report(per_k.values())


def _probe_metrics(
    backend,
    model,
    sequence: Mapping,
    episode: data.TruthEpisode,
    memory,
) -> dict[str, float]:
    """Score one bounded memory probe against the evaluator truth sidecar.

    Truth is only used after the forward pass.  Poses are aligned with the same
    per-episode anchor transform as the main localization evaluator, and the NLL
    is the presence+class next-observation loss (the reported ``loss`` when the
    backend does not expose those terms).
    """
    run = backend.step_sequence(model, sequence, memory=copy_memory(memory))
    poses = data.truth_pose_sequence(episode)
    if len(poses) == 0:
        raise EvaluationError(f"episode {episode.episode_id} has no truth poses")
    anchor = poses[0]
    estimates = []
    truths = []
    nlls = []
    for step in run["steps"]:
        frame = int(step["frame"])
        if not 0 <= frame < len(poses):
            raise EvaluationError(
                f"probe frame {frame} is outside episode {episode.episode_id} truth"
            )
        estimates.append(align_relative_pose(np.asarray(step["pose"], dtype=np.float64), anchor))
        truths.append(poses[frame])
        parts = step.get("parts") or {}
        if "presence" in parts and "class" in parts:
            nlls.append(float(parts["presence"]) + float(parts["class"]))
        else:
            nlls.append(float(step["loss"]))
    localization = metrics.localization_error(np.stack(estimates), np.stack(truths))
    return {
        "development_nll": float(np.mean(nlls)),
        "localization_translation_mean_m": float(localization["translation_mean_m"]),
        "steps": len(nlls),
    }


def m2_interference(
    backend,
    model,
    probe_sequences: Sequence[Mapping],
    truth_view: Sequence[data.TruthEpisode],
    history_sequence: Mapping,
    new_world_sequence: Mapping,
    *,
    probe_labels: Sequence[str] | None = None,
) -> dict:
    """Zero-state vs history-paired vs after-new-world-write memory probe."""
    by_id = truth_index(truth_view)
    before_params = backend.parameter_sha256(model)

    zero_state_rows = [
        _probe_metrics(backend, model, sequence, by_id[sequence["episode_id"]], None)
        for sequence in probe_sequences
    ]
    zero_state = {
        key: float(np.mean([row[key] for row in zero_state_rows]))
        for key in ("development_nll", "localization_translation_mean_m")
    }

    history_run = backend.step_sequence(model, history_sequence)
    history_rows = [
        _probe_metrics(
            backend, model, sequence, by_id[sequence["episode_id"]], history_run["memory"]
        )
        for sequence in probe_sequences
    ]
    history_paired = {
        key: float(np.mean([row[key] for row in history_rows]))
        for key in ("development_nll", "localization_translation_mean_m")
    }

    extended = copy_memory(history_run["memory"])
    backend.step_sequence(model, new_world_sequence, memory=extended)
    after_rows = [
        _probe_metrics(backend, model, sequence, by_id[sequence["episode_id"]], extended)
        for sequence in probe_sequences
    ]
    after_new_world = {
        key: float(np.mean([row[key] for row in after_rows]))
        for key in ("development_nll", "localization_translation_mean_m")
    }

    after_params = backend.parameter_sha256(model)
    if before_params != after_params:
        raise EvaluationError(
            "memory probe changed model parameters; the registered probe forbids updates"
        )
    report = metrics.interference_probes(
        zero_state=zero_state,
        history_paired=history_paired,
        before_new_world=history_paired,
        after_new_world=after_new_world,
        probe={
            "probe_episodes": [sequence["episode_id"] for sequence in probe_sequences],
            "history_episode": history_sequence["episode_id"],
            "new_world_episode": new_world_sequence["episode_id"],
            "parameter_sha256_before": before_params,
            "parameter_sha256_after": after_params,
            "labels": list(probe_labels or ("zero_state", "history", "after_new_world_write")),
            "per_condition": {
                "zero_state": zero_state_rows,
                "history_paired": history_rows,
                "after_new_world_write": after_rows,
            },
            "truth_rule": "truth is read only by this scorer after each forward pass; it "
            "is never an input to the model or its memory",
        },
    )
    return report


def sample_efficiency(rows: Sequence[Mapping]) -> dict:
    return metrics.sample_efficiency_dual(rows)
