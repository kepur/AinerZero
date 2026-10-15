"""M2m-d (C05): frozen-M2d distilled action preservation -- CPU protocol layer.

Implements the CPU-checkable parts of ``M2MD_ACTION_PRESERVATION.md``:
the frozen plan and exact logical-unit budget, the per-row preservation
windows (q, s = max(0, q-4), min(4, q) real feedback edges, then 4 free
imagine steps; only h = 1 and h = 4 are distilled), the SeedSequence key
manifest (namespace 3307, never touching memory/augmentation RNGs), a NumPy
reference of ``L_keep`` (masked KL(p_M2d || p_student), stable log-softmax),
branch normalisation for the combined loss, and the teacher-cache manifest
binding with fail-closed mismatch checks.

No MLX import, no model calls, no training. Runtime wiring into the memory
worker/CLI and every MLX numeric/gradient property remain unverified here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from uuid import UUID

import numpy as np

from ainerzero.learning.gru_intervention import GRU_SHAPES
from ainerzero.learning.tail_update import TAIL_ROW_RANGES

PROTOCOL = "m2m_d_m2d_distilled_action_preservation_v1"
SOURCE_CHECKPOINT = "f33974c9-b86f-4429-9ea9-8ea0e733142a"  # original M2d (teacher and student start)
KEEP_SEED = 3307
LAMBDA_KEEP = 1.0
TEMPERATURE = 1.0
HORIZONS = (1, 4)
ROLLOUT_STEPS = 4
MAX_FEEDBACK = 4
SYMBOL_CLASSES = 256
CELLS = 8
WORLD_COUNT = 16
ROWS_PER_UPDATE = 16
UPDATE_COUNT = 200
EPISODE_TRANSITIONS = 128
KEEP_ROW_ACCUMULATION = 4
STREAM_OBSERVE, STREAM_FEEDBACK_IMAGINE, STREAM_QUERY_IMAGINE = 0, 1, 2

# Frozen C05 budget (logical model units; not FLOPs).
RETAINED_UNITS = 178_304
TEACHER_UNITS = 2_254
STUDENT_UNITS = 27_988
TOTAL_UNITS = 208_546
PADDED_EXTRA_UNITS = 812  # fixed-4 padding variant: NOT adopted
SECONDS = {
    "retained_fixed": 940,
    "updates": UPDATE_COUNT * 3,
    "teacher_cache": 60,
    "cache_protocol_checks": 10,
}
PREPAID_SECONDS = 1_610
WORK_DEADLINE_SECONDS = 1_660
SUPERVISOR_DEADLINE_SECONDS = 1_710
SINGLE_RUN_LIMIT_SECONDS = 1_800
FRONT_APPLIED_GRADIENT_MAX = 1e-8
PRESERVATION_GATES = {
    "development_zero_context": {"overall_min": 3892, "overall_of": 4096, "changed_min": 115, "changed_of": 127},
    "relabel_pool": {"overall_min": 1946, "overall_of": 2048, "changed_min": 126, "changed_of": 140},
    "action_1": {"accuracy_min": 377, "of": 384, "nll_increase_max": 0.05},
    "action_4": {"accuracy_min": 359, "of": 384, "nll_increase_max": 0.15},
    "reconstruction": {"gate": "passed", "correct": 544, "of": 544},
}


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def action_preservation_plan() -> dict:
    """A fresh, independent copy of the frozen M2m-d plan (F01)."""
    return copy.deepcopy(_build_plan())


def _build_plan() -> dict:
    if sum(SECONDS.values()) != PREPAID_SECONDS or RETAINED_UNITS + TEACHER_UNITS + STUDENT_UNITS != TOTAL_UNITS:
        raise RuntimeError("frozen budget constants are inconsistent")
    if not PREPAID_SECONDS < WORK_DEADLINE_SECONDS < SUPERVISOR_DEADLINE_SECONDS <= SINGLE_RUN_LIMIT_SECONDS:
        raise RuntimeError("deadlines must stay inside the single-run limit")
    return {
        "protocol": PROTOCOL,
        "start_checkpoint": SOURCE_CHECKPOINT,
        "teacher_checkpoint": SOURCE_CHECKPOINT,
        "teacher_frozen": True,
        "reset_optimizer": True,
        "memory_branch": {
            "pool": "m2l_256_rows_original_order", "schedule": "200x16_original",
            "learning_rate": 0.003, "updates": UPDATE_COUNT, "batch_size": 16, "micro_batch_size": 4,
            "gradient_clip_norm": 1.0, "relabel_permutations": 3200,
            "seeds": {"latent": 2203, "augmentation": 2307, "relabel_evaluation": 9103},
        },
        "parameters": {"total": 393_232, "trainable_tail": 111_104, "frozen": 282_128},
        "keep_branch": {
            "lambda": LAMBDA_KEEP, "temperature": TEMPERATURE, "horizons": list(HORIZONS),
            "rollout_steps": ROLLOUT_STEPS, "max_feedback_edges": MAX_FEEDBACK,
            "target": "full_256_class_symbol_distribution_kl_teacher_to_student",
            "mask": "publicly_visible_cells_at_q", "particles": {"teacher": 1, "student": 1},
            "data": "unrelabeled_public_train_trajectories_same_16_scheduled_rows",
            "row_batch": 1, "row_accumulation": KEEP_ROW_ACCUMULATION, "seed": KEEP_SEED,
            "padding": "none_invalid_edges_not_executed",
            "student_start": "stop_gradient_teacher_incoming_h_at_s",
        },
        "loss": "L_memory + 1.0 * L_keep, each normalised by its own effective targets",
        "gradient": {
            "single_mask_clip_adamw_per_full_batch": True,
            "front_applied_gradient_max": FRONT_APPLIED_GRADIENT_MAX,
            "raw_front_gradient": "finite_logged_may_be_nonzero_new_protocol_only",
            "frozen_bitwise_check": "every_update_and_final",
        },
        "units": {"retained": RETAINED_UNITS, "teacher": TEACHER_UNITS, "student": STUDENT_UNITS, "total": TOTAL_UNITS},
        "seconds": dict(SECONDS, prepaid=PREPAID_SECONDS, work_deadline=WORK_DEADLINE_SECONDS,
                        supervisor_deadline=SUPERVISOR_DEADLINE_SECONDS),
        "reuse_frozen_m2l_baselines": {"units_saved": 86_176, "seconds_saved": 330, "requires_hash_closure": True},
        "gates": copy.deepcopy(PRESERVATION_GATES),
        "promotion": False,
        "automatic_next_run": False,
    }


FROZEN_PLAN_SHA256 = "cb1437efa7980e7e15dffc736ed9ec170a0be4dabdb4b5ebdd7989d1286af489"


def plan_sha256(plan: Mapping) -> str:
    return _digest(plan)


def verify_frozen_plan(plan: Mapping) -> str:
    """Reject any caller-modified plan; a dict is not a pre-registration by itself."""
    if not isinstance(plan, Mapping):
        raise ValueError("plan must be a mapping")
    digest = plan_sha256(plan)
    if digest != FROZEN_PLAN_SHA256 or digest != plan_sha256(_build_plan()):
        raise ValueError("plan differs from the frozen M2m-d registration")
    return digest


# ---------------------------------------------------------------- windows

def _units(rows: Sequence[Mapping], schedule: np.ndarray) -> tuple[list[int], dict]:
    qmax = [max((r["q"] for r in rows if r["world_index"] == w), default=None) for w in range(WORLD_COUNT)]
    if any(v is None for v in qmax):
        raise ValueError("every training world needs scheduled rows")
    if schedule.min() < 0 or schedule.max() >= len(rows):
        raise ValueError("schedule references unknown rows")
    presentations = [rows[int(r)] for r in schedule.ravel()]
    student_feedback = sum(r["feedback"] for r in presentations)
    return qmax, {
        "teacher": WORLD_COUNT + sum(qmax) + ROLLOUT_STEPS * len(rows),
        "student": len(presentations) + student_feedback + ROLLOUT_STEPS * len(presentations),
        "student_feedback": student_feedback,
        "padded_extra_not_executed": sum(MAX_FEEDBACK - r["feedback"] for r in presentations),
    }


def _schedule_array(schedule) -> np.ndarray:
    table = np.asarray(schedule)
    if table.shape != (UPDATE_COUNT, ROWS_PER_UPDATE) or table.dtype.kind not in "iu":
        raise ValueError("schedule must be the registered 200x16 integer table")
    return table


def preservation_windows(samples: Sequence[Mapping], schedule) -> dict:
    """COMPUTE windows/units from a manifest. This does NOT verify the source.

    Use ``verify_registered_inputs`` before any model work: equal units or keys
    never prove the original rows or schedule order (F02).
    """
    schedule = _schedule_array(schedule)
    if len(samples) != WORLD_COUNT * ROWS_PER_UPDATE:
        raise ValueError("pool manifest must list 256 rows")
    rows = []
    for index, sample in enumerate(samples):
        q, world = sample.get("query_tick"), sample.get("world_index")
        if sample.get("row") != index or type(q) is not int or type(world) is not int:
            raise ValueError("pool rows must be in order with integer query_tick/world_index")
        if not 1 <= q <= EPISODE_TRANSITIONS - ROLLOUT_STEPS or not 0 <= world < WORLD_COUNT:
            raise ValueError(f"row {index}: query tick {q} leaves no room for the 4-step rollout")
        if sample.get("target_tick") != q - 1:
            raise ValueError(f"row {index}: query must follow its target edge")
        s = max(0, q - MAX_FEEDBACK)
        rows.append({"row": index, "world_index": world, "episode_id": sample.get("episode_id"),
                     "environment_instance_id": sample.get("environment_instance_id"),
                     "public_episode_sha256": sample.get("public_episode_sha256"),
                     "public_transition_sha256": sample.get("public_transition_sha256"),
                     "q": q, "s": s, "feedback": q - s,
                     "rollout_actions_ticks": list(range(q, q + ROLLOUT_STEPS))})
    qmax, units = _units(rows, schedule)
    return {
        "rows": rows,
        "schedule": schedule.tolist(),
        "teacher_qmax": qmax,
        "units": units,
        "windows_schema": WINDOWS_SCHEMA,
        # v2 binds source identity; v1 (E13a) hashed only row/world/q/s.
        "windows_sha256": _digest([[r["row"], r["world_index"], r["q"], r["s"], r["episode_id"],
                                    r["environment_instance_id"], r["public_episode_sha256"],
                                    r["public_transition_sha256"]] for r in rows]),
        "schedule_sha256": _digest(schedule.tolist()),
        "registered_manifest_verified": False,
        "public_records_checked": False,
    }


WINDOWS_SCHEMA = "m2md_windows_v2_source_bound"
SCHEDULE_RULE = "row=w*16+(zero_based_update+w)%16"
# Authoritative identities of the registered M2m-c training pool (logical SHAs).
REGISTERED_INPUT = MappingProxyType({
    "partition": "train",
    "sample_manifest_sha256": "3558c8b5e924def7703bf46d246888612dee406a2f86829ca111fca5c9ede618",
    "schedule_sha256": "d6fcfa69202f05ec3c010f96ed931eb8f17f250cdc6b4e5973816ffd31c03e3f",
    "schedule_rule": SCHEDULE_RULE,
    "source_report_sha256": "47d1f1c8fca4ecf340b18fb7e431751ae37326c78e66075b8d7e2119fe7a3216",
})
REGISTERED_WINDOWS_SHA256 = "60e86293c6cc85aeee36e917fad544414cc1ce0d33b4ad2074c26f1924067b83"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _is_sha(value) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _is_uuid(value) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def registered_schedule() -> list[list[int]]:
    return [[w * ROWS_PER_UPDATE + (u + w) % ROWS_PER_UPDATE for w in range(WORLD_COUNT)]
            for u in range(UPDATE_COUNT)]


def verify_registered_inputs(
    samples: Sequence[Mapping],
    schedule,
    *,
    partition: str,
    public_records: Mapping[str, Mapping] | None = None,
) -> dict:
    """VERIFY that inputs are the registered pool/schedule, then compute windows.

    ``public_records`` (optional) maps episode_id -> already-loaded public
    identities: {"environment_instance_id", "public_episode_sha256",
    "partition", "transitions": {transition_index: {...ids/sha...}}}. Full
    file/RunStore closure is E13b's job; this layer rejects internal mismatch.
    """
    if partition != REGISTERED_INPUT["partition"] or partition != "train":
        raise ValueError("keep data must be the registered train partition")
    table = _schedule_array(schedule)
    if table.tolist() != registered_schedule():
        raise ValueError("schedule differs from the registered rule (rows/batches swapped?)")
    if _digest(table.tolist()) != REGISTERED_INPUT["schedule_sha256"]:
        raise ValueError("schedule logical SHA differs from registration")
    if _digest(list(samples)) != REGISTERED_INPUT["sample_manifest_sha256"]:
        raise ValueError("pool sample manifest differs from registration")
    worlds: dict[int, tuple] = {}
    seen: dict[str, set[str]] = {"target_observation_id": set(), "current_observation_id": set(),
                                 "action_request_id": set()}
    for sample in samples:
        ident = (sample.get("episode_id"), sample.get("environment_instance_id"),
                 sample.get("public_episode_sha256"))
        if not (_is_uuid(ident[0]) and _is_uuid(ident[1]) and _is_sha(ident[2])):
            raise ValueError(f"row {sample.get('row')}: malformed public source identity")
        if worlds.setdefault(sample["world_index"], ident) != ident:
            raise ValueError("one world_index maps to several episodes/worlds")
        for key in ("target_observation_id", "current_observation_id", "action_request_id"):
            if not _is_uuid(sample.get(key)) or sample[key] in seen[key]:
                raise ValueError(f"row {sample.get('row')}: {key} missing or reused")
            seen[key].add(sample[key])
        if not _is_sha(sample.get("public_transition_sha256")):
            raise ValueError("public transition SHA missing")
        if public_records is not None:
            record = public_records.get(ident[0])
            if record is None or record.get("partition") != "train" or (
                record.get("environment_instance_id"), record.get("public_episode_sha256")
            ) != ident[1:]:
                raise ValueError(f"row {sample['row']}: public episode identity mismatch")
            t = record.get("transitions", {}).get(sample.get("transition_index"))
            want = {k: sample.get(k) for k in ("target_observation_id", "current_observation_id",
                                              "action_request_id", "public_transition_sha256")}
            if t is None or {k: t.get(k) for k in want} != want or t.get("target_tick") != sample["target_tick"]:
                raise ValueError(f"row {sample['row']}: public observation/action identity mismatch")
    if sorted(worlds) != list(range(WORLD_COUNT)) or len({v[0] for v in worlds.values()}) != WORLD_COUNT \
            or len({v[1] for v in worlds.values()}) != WORLD_COUNT:
        raise ValueError("pool must cover 16 distinct episodes/worlds")
    windows = preservation_windows(samples, table)
    windows["registered_manifest_verified"] = True
    windows["public_records_checked"] = public_records is not None
    windows["registered_input"] = dict(REGISTERED_INPUT)
    validate_windows(windows)
    return windows


_WINDOW_ROW_FIELDS = frozenset({
    "row", "world_index", "episode_id", "environment_instance_id",
    "public_episode_sha256", "public_transition_sha256", "q", "s",
    "feedback", "rollout_actions_ticks",
})
_UNIT_FIELDS = frozenset({"teacher", "student", "student_feedback", "padded_extra_not_executed"})


def validate_windows(windows: Mapping) -> dict:
    """Recompute the current window content before budget/key consumption.

    Generic computed windows remain usable, including synthetic source labels.
    Stored digests, qmax, units and optional registered identities are comparison
    targets only; caller-modifiable verification flags are never evidence. This
    does not repeat public-record/file/RunStore checks or certify their truth.
    """
    if not isinstance(windows, Mapping) or windows.get("windows_schema") != WINDOWS_SCHEMA:
        raise ValueError("windows must use the source-bound v2 schema")
    if "source_verified" in windows:
        raise ValueError("source_verified is not a window certification field")
    registered_flag = windows.get("registered_manifest_verified")
    public_flag = windows.get("public_records_checked")
    if type(registered_flag) is not bool or type(public_flag) is not bool:
        raise ValueError("window verification states must be explicit booleans")
    if registered_flag != ("registered_input" in windows) or (public_flag and not registered_flag):
        raise ValueError("window verification state contradicts the registration metadata")
    rows = windows.get("rows")
    if not isinstance(rows, (list, tuple)) or len(rows) != WORLD_COUNT * ROWS_PER_UPDATE:
        raise ValueError("windows must contain 256 ordered rows")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != _WINDOW_ROW_FIELDS:
            raise ValueError(f"window row {index} has an invalid schema")
        if any(type(row[k]) is not int for k in ("row", "world_index", "q", "s", "feedback")):
            raise ValueError(f"window row {index} indices must be integers, not bool")
        q, s = row["q"], row["s"]
        if row["row"] != index or not 0 <= row["world_index"] < WORLD_COUNT:
            raise ValueError(f"window row {index} order/world index differs")
        if not 1 <= q <= EPISODE_TRANSITIONS - ROLLOUT_STEPS or s != max(0, q - MAX_FEEDBACK) \
                or row["feedback"] != q - s:
            raise ValueError(f"window row {index} query/feedback sequence differs")
        ticks = row["rollout_actions_ticks"]
        if not isinstance(ticks, list) or any(type(t) is not int for t in ticks) \
                or ticks != list(range(q, q + ROLLOUT_STEPS)):
            raise ValueError(f"window row {index} rollout action sequence differs")
        for key in ("episode_id", "environment_instance_id", "public_episode_sha256",
                    "public_transition_sha256"):
            if row[key] is not None and type(row[key]) is not str:
                raise ValueError(f"window row {index} source field {key} must be str or null")
    table = _schedule_array(windows.get("schedule"))
    windows_sha = _digest([[r["row"], r["world_index"], r["q"], r["s"], r["episode_id"],
                            r["environment_instance_id"], r["public_episode_sha256"],
                            r["public_transition_sha256"]] for r in rows])
    schedule_sha = _digest(table.tolist())
    if windows_sha != windows.get("windows_sha256") or schedule_sha != windows.get("schedule_sha256"):
        raise ValueError("stored window/schedule SHA differs from current content")
    qmax, units = _units(rows, table)
    stored_qmax, stored_units = windows.get("teacher_qmax"), windows.get("units")
    if not isinstance(stored_qmax, list) or any(type(q) is not int for q in stored_qmax) \
            or stored_qmax != qmax:
        raise ValueError("stored teacher qmax differs from current rows")
    if not isinstance(stored_units, Mapping) or set(stored_units) != _UNIT_FIELDS \
            or any(type(value) is not int for value in stored_units.values()) or dict(stored_units) != units:
        raise ValueError("stored units differ from the recomputed call list")
    if "registered_input" in windows:
        registered = windows["registered_input"]
        if not isinstance(registered, Mapping) or dict(registered) != dict(REGISTERED_INPUT) \
                or windows_sha != REGISTERED_WINDOWS_SHA256 \
                or schedule_sha != REGISTERED_INPUT["schedule_sha256"] \
                or table.tolist() != registered_schedule():
            raise ValueError("window content differs from the fixed M2m-d registration")
    return {"windows_sha256": windows_sha, "schedule_sha256": schedule_sha,
            "teacher_qmax": qmax, "units": units}


def check_budget(windows: Mapping) -> dict:
    """Recompute units from rows+schedule; stop if they differ from the frozen budget."""
    units = validate_windows(windows)["units"]
    if units["teacher"] != TEACHER_UNITS or units["student"] != STUDENT_UNITS:
        raise ValueError(f"call list {units} differs from registered teacher/student units; stop")
    if units["padded_extra_not_executed"] != PADDED_EXTRA_UNITS:
        raise ValueError("padding accounting differs from the registered 812")
    return {"retained": RETAINED_UNITS, "teacher": TEACHER_UNITS, "student": STUDENT_UNITS,
            "total": TOTAL_UNITS}


def student_window(episode_observations: Sequence, episode_actions: Sequence[int], q: int) -> dict:
    """Public inputs for one keep row: o_s..o_q (never beyond q) and a_s..a_{q+3}."""
    if type(q) is not int or q < 1:
        raise ValueError("q must be a positive integer")
    if q + ROLLOUT_STEPS > len(episode_actions) or q >= len(episode_observations):
        raise ValueError("window exceeds the recorded episode")
    s = max(0, q - MAX_FEEDBACK)
    return {
        "s": s, "q": q,
        "observations": list(episode_observations[s : q + 1]),
        "feedback_actions": list(episode_actions[s:q]),
        "rollout_actions": list(episode_actions[q : q + ROLLOUT_STEPS]),
    }


# ---------------------------------------------------------------- keys

def call_key(stream_kind: int, world_index: int, tick: int, offset: int = 0) -> int:
    """uint32 of SeedSequence([3307, stream, world, tick, offset]); own namespace."""
    if stream_kind not in (STREAM_OBSERVE, STREAM_FEEDBACK_IMAGINE, STREAM_QUERY_IMAGINE):
        raise ValueError("unknown stream kind")
    if stream_kind == STREAM_QUERY_IMAGINE:
        if offset not in range(1, ROLLOUT_STEPS + 1):
            raise ValueError("query offsets are 1..4 at tick q")
    elif offset != 0:
        raise ValueError("observe/feedback keys use offset 0")
    for value in (world_index, tick):
        if type(value) is not int or value < 0:
            raise ValueError("world_index and tick must be non-negative integers")
    seq = np.random.SeedSequence([KEEP_SEED, stream_kind, world_index, tick, offset])
    return int(seq.generate_state(1, dtype=np.uint32)[0])


def row_call_keys(world_index: int, s: int, q: int) -> list[tuple[str, int, int, int]]:
    """Ordered (call, tick, offset, key) list a keep row uses; teacher shares them."""
    calls = [("observe", s, 0, call_key(STREAM_OBSERVE, world_index, s))]
    for t in range(s, q):
        calls.append(("feedback_imagine", t, 0, call_key(STREAM_FEEDBACK_IMAGINE, world_index, t)))
        calls.append(("feedback_observe", t + 1, 0, call_key(STREAM_OBSERVE, world_index, t + 1)))
    for offset in range(1, ROLLOUT_STEPS + 1):
        calls.append(("query_imagine", q, offset, call_key(STREAM_QUERY_IMAGINE, world_index, q, offset)))
    return calls


def key_manifest(windows: Mapping) -> dict:
    """Per-call seeds are unchanged from E13a; the manifest digest now also binds
    the source-bound windows and the schedule (schema v2)."""
    checked = validate_windows(windows)
    rows = [{"row": r["row"], "keys": [list(c) for c in row_call_keys(r["world_index"], r["s"], r["q"])]}
            for r in windows["rows"]]
    teacher = []
    for world, qmax in enumerate(checked["teacher_qmax"]):
        teacher.append({"world_index": world,
                        "keys": [list(c) for c in row_call_keys(world, 0, qmax)[: 1 + 2 * qmax]]})
    keys_only = _digest({"rows": rows, "teacher": teacher})  # == E13a v1 manifest digest
    return {"seed": KEEP_SEED, "schema": "m2md_keys_v2_bound", "rows": rows, "teacher_online": teacher,
            "keys_sha256": keys_only,
            "manifest_sha256": _digest({"keys_sha256": keys_only, "windows_sha256": checked["windows_sha256"],
                                        "schedule_sha256": checked["schedule_sha256"]})}


# ---------------------------------------------------------------- loss (NumPy reference)

def _log_softmax(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float64) / TEMPERATURE
    shifted = logits - logits.max(axis=-1, keepdims=True)
    return shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))


def keep_loss_reference(teacher_logits, student_logits, visible_mask) -> dict:
    """L_keep: per row/horizon mean KL over visible cells, then mean of horizons and rows.

    Shapes [R, 2(h=1,4), 8, 256] for logits and [R, 8] for the q-time visible mask.
    Full teacher probabilities are required; argmax or NLL substitutes are rejected
    by shape. Rows without a visible target raise instead of changing the denominator.
    """
    t, s = np.asarray(teacher_logits), np.asarray(student_logits)
    mask = np.asarray(visible_mask)
    if t.shape != s.shape or t.ndim != 4 or t.shape[1:] != (len(HORIZONS), CELLS, SYMBOL_CLASSES):
        raise ValueError("teacher/student logits must be [R,2,8,256] full distributions")
    if mask.shape != (t.shape[0], CELLS) or mask.dtype != np.bool_:
        raise ValueError("visible mask must be boolean [R,8]")
    if not (np.isfinite(t).all() and np.isfinite(s).all()):
        raise ValueError("logits must be finite")
    if not mask.any(axis=1).all():
        raise ValueError("a keep row without visible targets must stop the run")
    lt, ls = _log_softmax(t), _log_softmax(s)
    kl = (np.exp(lt) * (lt - ls)).sum(axis=-1)  # [R,2,8]
    per = (kl * mask[:, None, :]).sum(-1) / mask.sum(-1)[:, None]  # [R,2]
    loss = float(per.mean())
    if not np.isfinite(loss) or loss < -1e-12:
        raise ValueError("keep loss must be finite and non-negative")
    return {"loss": loss, "per_row_horizon": per, "rows": int(t.shape[0])}


def _positive_count(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("effective target count must be a finite positive int/float (not bool)")
    return float(value)


def _leaf(value, name) -> np.ndarray:
    arr = np.asarray(value)
    if arr.dtype.kind not in "fiu" or arr.dtype == np.bool_:
        raise ValueError(f"gradient leaf {name} must be numeric")
    if not np.isfinite(arr).all():
        raise ValueError(f"non-finite raw gradient in {name}")
    return arr.astype(np.float64)


def combine_branch_gradients(memory_sum: Mapping, memory_targets: float,
                             keep_row_grads: Sequence[Mapping]) -> dict:
    """g = sum_mem/targets + LAMBDA * mean_rows(g_keep); one tree for one mask/clip/AdamW.

    Trees must be non-empty with identical keys and leaf shapes (no broadcasting);
    every raw branch leaf must be finite (F04).
    """
    targets = _positive_count(memory_targets)
    if not isinstance(memory_sum, Mapping) or not memory_sum:
        raise ValueError("gradient tree must be non-empty")
    if len(keep_row_grads) != ROWS_PER_UPDATE:
        raise ValueError("keep branch must cover the 16 scheduled rows")
    keys = set(memory_sum)
    shapes = {k: _leaf(memory_sum[k], k).shape for k in keys}
    for g in keep_row_grads:
        if not isinstance(g, Mapping) or set(g) != keys:
            raise ValueError("branch gradient trees differ")
        for k in keys:
            if _leaf(g[k], k).shape != shapes[k]:
                raise ValueError(f"leaf shape mismatch in {k}")
    out = {}
    for k in keys:
        keep = sum(_leaf(g[k], k) for g in keep_row_grads) / ROWS_PER_UPDATE
        value = _leaf(memory_sum[k], k) / targets + LAMBDA_KEEP * keep
        if not np.isfinite(value).all():
            raise ValueError(f"non-finite combined gradient in {k}")
        out[k] = value
    return out


GRU_LEAVES = {k.removeprefix("model.gru."): v for k, v in GRU_SHAPES.items()}


def frozen_row_mask(name: str) -> np.ndarray:
    """True on GRU output rows that must not change (complement of the tail)."""
    if name not in GRU_LEAVES:
        raise ValueError(f"unknown GRU leaf {name}")
    shape = GRU_LEAVES[name]
    frozen = np.ones(shape[0], dtype=bool)
    for start, stop in ((128, 256),) if name == "bhn" else TAIL_ROW_RANGES:
        frozen[start:stop] = False
    return frozen


def _gru_tree(tree: Mapping, label: str) -> dict:
    if not isinstance(tree, Mapping) or set(tree) != set(GRU_LEAVES):
        raise ValueError(f"{label} gradient tree must be exactly the GRU leaves {sorted(GRU_LEAVES)}")
    out = {}
    for name, shape in GRU_LEAVES.items():
        arr = _leaf(tree[name], f"{label}.{name}")
        if arr.shape != shape:
            raise ValueError(f"{label}.{name} shape {arr.shape} != {shape}")
        out[name] = arr
    return out


def check_applied_front_gradient(raw: Mapping, applied: Mapping) -> dict:
    """Guard on the gradient actually handed to the optimizer (F05).

    The frozen (front) rows of ``applied`` must have L2 <= 1e-8; the raw frozen
    norm is recorded separately (may be finite nonzero in this protocol). Never
    inferred from raw - applied. AdamW projection and bitwise freeze checks are
    separate steps still owned by E13b/C06a.
    """
    raw, applied = _gru_tree(raw, "raw"), _gru_tree(applied, "applied")
    raw_sq = applied_sq = 0.0
    with np.errstate(over="ignore", invalid="ignore"):
        for name, arr in applied.items():
            mask = frozen_row_mask(name)
            raw_sq += float(np.sum(raw[name][mask] ** 2))
            applied_sq += float(np.sum(arr[mask] ** 2))
    raw_front, applied_front = math.sqrt(raw_sq), math.sqrt(applied_sq)
    if not math.isfinite(raw_front) or not math.isfinite(applied_front):
        raise ValueError("derived frozen-row gradient norms must be finite")
    if applied_front > FRONT_APPLIED_GRADIENT_MAX:
        raise ValueError(f"applied frozen-row gradient {applied_front} exceeds 1e-8")
    return {"raw_front_gradient_l2": raw_front, "applied_front_gradient_l2": applied_front,
            "front_applied_gradient_max": FRONT_APPLIED_GRADIENT_MAX}


# ---------------------------------------------------------------- teacher cache

TEACHER_ARCHITECTURE = "pilot_shared_symbol_v1"
HIDDEN_DIM = 256
MASK_RULE = "public_visible_at_q"
CACHE_BINDING_FIELDS = (
    "protocol", "teacher_checkpoint", "teacher_checkpoint_manifest_sha256", "teacher_source_sha256",
    "architecture", "training_samples_sha256", "schedule_sha256", "windows_sha256",
    "key_manifest_sha256", "particles", "temperature", "mask_rule", "run_id", "budget_units",
)
_SHA_FIELDS = ("teacher_checkpoint_manifest_sha256", "teacher_source_sha256", "training_samples_sha256",
               "schedule_sha256", "windows_sha256", "key_manifest_sha256")
POOL_ROWS = WORLD_COUNT * ROWS_PER_UPDATE
CACHE_ARRAYS = {
    "incoming_h": ((POOL_ROWS, HIDDEN_DIM), np.float32),
    "teacher_logits": ((POOL_ROWS, len(HORIZONS), CELLS, SYMBOL_CLASSES), np.float32),
    "visible_mask": ((POOL_ROWS, CELLS), np.bool_),
}


def _array_identity(value: np.ndarray) -> dict:
    """Raw contiguous array content SHA -- NOT a .npy/safetensors file SHA."""
    data = np.ascontiguousarray(value)
    return {"shape": list(data.shape), "dtype": str(data.dtype), "content_bytes": int(data.nbytes),
            "content_sha256": hashlib.sha256(data.tobytes()).hexdigest()}


def validate_cache_binding(binding: Mapping) -> dict:
    """Strict typed binding (F03). Structural only: run existence, budget reservation
    and checkpoint-file truth are verified by E13b against RunStore/files."""
    if not isinstance(binding, Mapping):
        raise ValueError("binding must be a mapping")
    missing = [f for f in CACHE_BINDING_FIELDS if f not in binding]
    extra = sorted(set(binding) - set(CACHE_BINDING_FIELDS))
    if missing or extra:
        raise ValueError(f"cache binding fields: missing {missing}, extra {extra}")
    if binding["protocol"] != PROTOCOL or binding["teacher_checkpoint"] != SOURCE_CHECKPOINT:
        raise ValueError("cache must bind the M2m-d protocol and original M2d teacher")
    if binding["architecture"] != TEACHER_ARCHITECTURE:
        raise ValueError(f"teacher architecture must be {TEACHER_ARCHITECTURE}")
    for field in _SHA_FIELDS:
        if not _is_sha(binding[field]):
            raise ValueError(f"{field} must be a lowercase SHA256 hex digest")
    if not _is_uuid(binding["run_id"]):
        raise ValueError("run_id must be a canonical UUID string")
    if type(binding["particles"]) is not int or binding["particles"] != 1:
        raise ValueError("cache uses exactly one teacher particle (int 1)")
    if type(binding["temperature"]) not in (int, float) or binding["temperature"] != TEMPERATURE:
        raise ValueError("temperature must be numeric 1 (not bool)")
    if binding["mask_rule"] != MASK_RULE:
        raise ValueError(f"mask_rule must be {MASK_RULE}")
    if type(binding["budget_units"]) is not int or binding["budget_units"] != TEACHER_UNITS:
        raise ValueError("teacher cache budget must be int 2254")
    return dict(binding)


def _validate_cache_arrays(arrays: Mapping[str, np.ndarray]) -> dict:
    if not isinstance(arrays, Mapping) or set(arrays) != set(CACHE_ARRAYS):
        raise ValueError("cache arrays must be exactly incoming_h, teacher_logits, visible_mask")
    identities = {}
    for name, (shape, dtype) in CACHE_ARRAYS.items():
        value = arrays[name]
        if not isinstance(value, np.ndarray) or value.dtype != np.dtype(dtype) or value.shape != shape:
            raise ValueError(f"{name} must be a materialised {np.dtype(dtype)} array of shape {shape}")
        if value.dtype != np.bool_ and not np.isfinite(value).all():
            raise ValueError(f"{name} must be finite")
        identities[name] = _array_identity(value)
    if not arrays["visible_mask"].any(axis=1).all():
        raise ValueError("every cached row needs at least one q-visible target")
    return identities


def teacher_cache_manifest(binding: Mapping, arrays: Mapping[str, np.ndarray]) -> dict:
    body = {"binding": validate_cache_binding(binding), "arrays": _validate_cache_arrays(arrays)}
    return {**body, "manifest_sha256": _digest(body)}


def verify_teacher_cache(manifest: Mapping, arrays: Mapping[str, np.ndarray], expected_binding: Mapping,
                         expected_visible_mask: np.ndarray | None = None) -> None:
    """Fail closed on any binding, array, mask, or manifest digest mismatch.

    ``expected_binding`` must come from trusted inputs (verified windows/keys,
    checkpoint manifest); equality only shows both sides agree.
    """
    expected = validate_cache_binding(expected_binding)
    body = {"binding": manifest.get("binding"), "arrays": manifest.get("arrays")}
    if _digest(body) != manifest.get("manifest_sha256"):
        raise ValueError("cache manifest digest mismatch")
    if dict(manifest["binding"]) != expected:
        diff = sorted(k for k in set(expected) | set(manifest["binding"])
                      if manifest["binding"].get(k) != expected.get(k))
        raise ValueError(f"cache binding mismatch: {diff}")
    if _validate_cache_arrays(arrays) != manifest["arrays"]:
        raise ValueError("cache array identity mismatch")
    if expected_visible_mask is not None and not np.array_equal(arrays["visible_mask"], expected_visible_mask):
        raise ValueError("cached mask differs from the public q-visible mask")
