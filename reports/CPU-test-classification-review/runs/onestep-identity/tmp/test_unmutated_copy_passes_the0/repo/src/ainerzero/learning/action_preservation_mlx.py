"""M2m-d (E13b): MLX keep branch -- teacher cache production and per-row keep loss.

Imported by the memory worker only after initialization. The keep path creates
every random key through ``_key`` from the registered ``ap.key_manifest`` seeds;
it never uses the global seed or derives keys from other keys. Implemented but
not numerically verified here (C06a registers the limited MLX checks).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import mlx.core as mx
import numpy as np

from ainerzero.learning import action_preservation as ap


def _key(seed_u32) -> mx.array:
    return mx.random.key(int(seed_u32))


def _episode_frames(episode) -> tuple[list, list[int]]:
    observations = [episode.initial.payload]
    actions = []
    for index, edge in enumerate(episode.transitions):
        if edge.observation.step != index:
            raise ValueError("episode transitions must be contiguous from tick 0")
        observations.append(edge.next_observation.payload)
        actions.append(int(edge.action_request.action))
    return observations, actions


def _episodes_by_world(train_episodes, windows: Mapping) -> dict[int, tuple[list, list[int]]]:
    by_id = {str(e.initial.context.episode_id): e for e in train_episodes}
    worlds = {}
    for row in windows["rows"]:
        episode = by_id.get(row["episode_id"])
        if episode is None or str(episode.initial.context.environment_instance_id) != row["environment_instance_id"]:
            raise ValueError("window row has no matching train episode")
        worlds.setdefault(row["world_index"], _episode_frames(episode))
    if sorted(worlds) != list(range(ap.WORLD_COUNT)):
        raise ValueError("windows must cover the 16 training worlds")
    return worlds


def _arrays(observation) -> tuple[mx.array, mx.array, mx.array]:
    return (
        mx.array([list(observation.symbols)], dtype=mx.int32),
        mx.array([list(observation.visible_mask)], dtype=mx.bool_),
        mx.array([observation.cursor], dtype=mx.int32),
    )


def _action(value: int) -> mx.array:
    return mx.array([int(value)], dtype=mx.int32)


def row_windows(train_episodes, windows: Mapping) -> list[dict]:
    """Public student inputs per pool row: o_s..o_q and a_s..a_{q+3} only."""
    worlds = _episodes_by_world(train_episodes, windows)
    out = []
    for row in windows["rows"]:
        observations, actions = worlds[row["world_index"]]
        window = ap.student_window(observations, actions, row["q"])
        if window["s"] != row["s"]:
            raise ValueError("window start differs from registration")
        out.append(window)
    return out


def q_visible_mask(train_episodes, windows: Mapping) -> np.ndarray:
    return np.asarray([list(w["observations"][-1].visible_mask) for w in row_windows(train_episodes, windows)],
                      dtype=np.bool_)


def build_teacher_cache(teacher, episodes, windows: Mapping, keys: Mapping, *,
                        before_work: Callable[[int], None]) -> dict[str, np.ndarray]:
    """Frozen teacher, B=1 per world, causal online pass to qmax plus 4-step queries."""
    worlds = _episodes_by_world(episodes, windows)
    rows_by_world: dict[int, list[Mapping]] = {}
    for row in windows["rows"]:
        rows_by_world.setdefault(row["world_index"], []).append(row)
    incoming = np.zeros(ap.CACHE_ARRAYS["incoming_h"][0], dtype=np.float32)
    logits_out = np.zeros(ap.CACHE_ARRAYS["teacher_logits"][0], dtype=np.float32)
    mask = np.zeros(ap.CACHE_ARRAYS["visible_mask"][0], dtype=np.bool_)
    units = 0
    for entry in keys["teacher_online"]:
        world = entry["world_index"]
        observations, actions = worlds[world]
        qmax = windows["teacher_qmax"][world]
        calls = entry["keys"]
        if len(calls) != 1 + 2 * qmax:
            raise ValueError("teacher online keys do not match qmax")
        wanted = {row["s"]: [] for row in rows_by_world[world]}
        queries = {}
        for row in rows_by_world[world]:
            wanted[row["s"]].append(row["row"])
            queries.setdefault(row["q"], []).append(row["row"])
        row_keys = {r: keys["rows"][r]["keys"] for r in sum(queries.values(), [])}
        h, _ = teacher.initial(1)
        if 0 in wanted:
            value = np.array(h[0], dtype=np.float32)
            for r in wanted[0]:
                incoming[r] = value
        before_work(1)
        units += 1
        name, tick, offset, seed = calls[0]
        if (name, tick, offset) != ("observe", 0, 0):
            raise ValueError("teacher must start by observing o_0")
        state = teacher.observe(h, *_arrays(observations[0]), key=_key(seed))
        for t in range(qmax + 1):
            if t in queries:
                for r in queries[t]:
                    query_calls = row_keys[r][-ap.ROLLOUT_STEPS:]
                    h_q, z_q = state["h"], state["z"]
                    steps = []
                    for step, (name, tick, offset, seed) in enumerate(query_calls, start=1):
                        if (name, tick, offset) != ("query_imagine", t, step):
                            raise ValueError("query keys out of order")
                        before_work(1)
                        units += 1
                        imagined = teacher.imagine(h_q, z_q, _action(actions[t + step - 1]), key=_key(seed))
                        h_q, z_q = imagined["h"], imagined["z"]
                        if step in ap.HORIZONS:
                            steps.append(imagined["logits"]["symbols"][0])
                    mx.eval(*steps)
                    logits_out[r] = np.stack([np.array(v, dtype=np.float32) for v in steps])
                    mask[r] = np.asarray(observations[t].visible_mask, dtype=np.bool_)
            if t == qmax:
                break
            (n1, t1, o1, s1), (n2, t2, o2, s2) = calls[1 + 2 * t], calls[2 + 2 * t]
            if (n1, t1, o1, n2, t2, o2) != ("feedback_imagine", t, 0, "feedback_observe", t + 1, 0):
                raise ValueError("teacher feedback keys out of order")
            before_work(1)
            units += 1
            imagined = teacher.imagine(state["h"], state["z"], _action(actions[t]), key=_key(s1))
            if t + 1 in wanted:
                mx.eval(imagined["h"])
                value = np.array(imagined["h"][0], dtype=np.float32)
                for r in wanted[t + 1]:
                    incoming[r] = value
            state = teacher.observe(imagined["h"], *_arrays(observations[t + 1]), key=_key(s2))
            mx.eval(state["h"], state["z"])
    if units != ap.TEACHER_UNITS:
        raise RuntimeError(f"teacher cache used {units} units, expected {ap.TEACHER_UNITS}")
    return {"incoming_h": incoming, "teacher_logits": logits_out, "visible_mask": mask}


def _log_softmax(x):
    x = x / ap.TEMPERATURE
    return x - mx.logsumexp(x, axis=-1, keepdims=True)


def keep_row_loss(model, cached_row: Mapping, window: Mapping, row_keys: Sequence):
    """Masked KL(teacher || student) at h=1,4 for one row (B=1); for nn.value_and_grad."""
    s, q = window["s"], window["q"]
    observations = window["observations"]
    if len(row_keys) != 1 + 2 * (q - s) + ap.ROLLOUT_STEPS:
        raise ValueError("row keys do not match the window")
    h = mx.stop_gradient(mx.array(np.asarray(cached_row["incoming_h"], dtype=np.float32)[None]))
    state = model.observe(h, *_arrays(observations[0]), key=_key(row_keys[0][3]))
    for edge in range(q - s):
        imagined = model.imagine(state["h"], state["z"], _action(window["feedback_actions"][edge]),
                                 key=_key(row_keys[1 + 2 * edge][3]))
        state = model.observe(imagined["h"], *_arrays(observations[edge + 1]),
                              key=_key(row_keys[2 + 2 * edge][3]))
    h_q, z_q = state["h"], state["z"]
    teacher = mx.stop_gradient(mx.array(np.asarray(cached_row["teacher_logits"], dtype=np.float32)))
    visible = mx.array(np.asarray(cached_row["visible_mask"], dtype=np.bool_)).astype(mx.float32)
    per_horizon = []
    query = row_keys[-ap.ROLLOUT_STEPS:]
    for step in range(1, ap.ROLLOUT_STEPS + 1):
        imagined = model.imagine(h_q, z_q, _action(window["rollout_actions"][step - 1]), key=_key(query[step - 1][3]))
        h_q, z_q = imagined["h"], imagined["z"]
        if step in ap.HORIZONS:
            lt = _log_softmax(teacher[ap.HORIZONS.index(step)])
            ls = _log_softmax(imagined["logits"]["symbols"][0])
            kl = mx.sum(mx.exp(lt) * (lt - ls), axis=-1)
            per_horizon.append(mx.sum(kl * visible) / mx.sum(visible))
    loss = (per_horizon[0] + per_horizon[1]) / len(ap.HORIZONS)
    return loss, mx.stack(per_horizon)


class _ReadoutRecorder:
    """Delegates to a predictor and records every symbol-readout call (no extra work)."""

    def __init__(self, model):
        self._model = model
        self.logits = []

    def __getattr__(self, name):
        return getattr(self._model, name)

    def symbol_readout(self, *args, **kwargs):
        out = self._model.symbol_readout(*args, **kwargs)
        self.logits.append(out)
        return out


def memory_distill_sequence_loss(student, teacher, batch: Mapping, *, burn_in: int, key, lam: float,
                                 truncate_each_step: bool = False):
    """D condition: one forward pass, `CE(student) + lam * KL(teacher || student)`.

    Both models run the *same* batch with the *same* keys, so the teacher's
    distribution is defined on exactly the cells the memory objective scores
    (same rows, same relabelled symbols, same masks) -- unlike the M2m-d keep
    branch, which compared a relabelled student against an unrelabelled teacher.
    The teacher must be frozen and is never differentiated; its logical units are
    the caller's responsibility (student + teacher passes).

    ``truncate_each_step`` is forwarded verbatim to both passes (M2n-M4). It
    changes no forward value; it makes the student's CE *and* the KL term read
    from states detached at every loss step, so each loss term's gradient
    crosses exactly one transition.
    """
    from ainerzero.learning.one_step_memory import memory_sequence_loss

    if type(lam) not in (int, float) or isinstance(lam, bool) or not np.isfinite(lam) or lam < 0:
        raise ValueError("distillation lambda must be a finite non-negative number")
    if type(truncate_each_step) is not bool:
        raise ValueError("truncate_each_step must be a bool")
    student_recorder, teacher_recorder = _ReadoutRecorder(student), _ReadoutRecorder(teacher)
    memory_loss, metrics = memory_sequence_loss(
        student_recorder, batch, burn_in=burn_in, key=key, truncate_each_step=truncate_each_step
    )
    memory_sequence_loss(
        teacher_recorder, batch, burn_in=burn_in, key=key, truncate_each_step=truncate_each_step
    )

    import mlx.core as mx

    actions = batch["actions"]
    steps = actions.shape[1]
    valid = batch.get("valid_mask")
    if valid is None:
        valid = mx.ones(actions.shape, dtype=mx.bool_)
    starts = batch["episode_start"]
    if not student_recorder.logits or len(student_recorder.logits) != len(teacher_recorder.logits):
        raise RuntimeError("distillation needs one matched readout per loss step")
    total_kl = None
    for offset, step in enumerate(range(burn_in, steps)):
        path_valid = valid[:, step] & ~starts[:, step + 1]
        visible = batch["visible_mask"][:, step] & path_valid[:, None]
        teacher_logits = mx.stop_gradient(teacher_recorder.logits[offset])
        student_logits = student_recorder.logits[offset]
        teacher_ls = teacher_logits - mx.logsumexp(teacher_logits, axis=-1, keepdims=True)
        student_ls = student_logits - mx.logsumexp(student_logits, axis=-1, keepdims=True)
        cell_kl = mx.sum(mx.exp(teacher_ls) * (teacher_ls - student_ls), axis=-1)
        masked = mx.sum(cell_kl * visible.astype(mx.float32))
        total_kl = masked if total_kl is None else total_kl + masked
    count = mx.maximum(metrics["visible_targets"], 1)
    kl = total_kl / count
    loss = memory_loss + float(lam) * kl
    return loss, {
        "memory_loss": memory_loss,
        "distill_kl": kl,
        "distill_loss": loss,
        "valid_transitions": metrics["valid_transitions"],
        "visible_targets": metrics["visible_targets"],
    }
