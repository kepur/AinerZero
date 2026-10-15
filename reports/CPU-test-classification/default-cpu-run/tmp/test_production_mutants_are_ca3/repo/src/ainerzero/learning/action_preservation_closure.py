"""M2m-d (E13b): production input closure for the action-preservation entry point.

Pure CPU, no MLX import. Everything here runs before any model work:

* B1/B2 production windows: registered pool/schedule verified against public
  records built independently from the dataset-validated train episodes, then
  re-checked without trusting any flag (windows SHA, key manifest v2 SHA and
  keys-content SHA must equal the registered constants);
* the per-update student unit table;
* the frozen M2l baseline reuse closure from the completed M2m-c report
  (file SHA, reference equality, CPU recomputation of the reused cell results,
  RunStore ledger) -- no M2l weights are loaded or run;
* the trusted expected teacher-cache binding;
* the integer preservation gates (judgement only, never promotion).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from ainerzero.learning import action_preservation as ap

REGISTERED_KEY_MANIFEST_SHA256 = "71deb0f0b98be564f04227225ff5925108c479223910de3e1d3442b37542c1ca"
REGISTERED_KEYS_CONTENT_SHA256 = "5a6449008da160e7b32c3056d724c4fd954efba8008ce62478bd67411d6c4ad1"
M2MC_REPORT_SHA256 = "47d1f1c8fca4ecf340b18fb7e431751ae37326c78e66075b8d7e2119fe7a3216"
M2MC_RUN_ID = "9169008d-348b-47b3-8519-8f87affcb60c"
M2MC_RESERVED_UNITS = 264_480
M2L_RESERVED_UNITS = 174_208
PAIRED_QUERIES = 2_560
PAIRED_BRANCHES = ("history_tail", "zero_context_tail")
STUDENT_UPDATE_UNITS_RANGE = (137, 144)
TEACHER_SOURCE_FILES = ("pilot_model.py", "action_preservation.py", "action_preservation_mlx.py")
FLOAT_TOLERANCE = 1e-12  # recomputation of saved floats; ints compare exactly
# C06a amendment (2026-10-13, coordinator decision after the registered probe):
# the first-update keep loss cannot be bitwise 0.0 because the frozen teacher
# cache and the student's re-executed suffix are two separately compiled MLX
# graphs. Measured: cache repeat bitwise identical (KL 0.0) while the 16 first
# update rows were +/-1.21e-7 with ~1-2 float32 ULP logit differences. The
# production stop condition is therefore this registered absolute bound instead
# of exact zero; capability gates, science parameters and data are unchanged.
# Evidence: artifacts/reports/C06a-probe-execution-20261013.md
FIRST_UPDATE_KEEP_LOSS_MAX = 1e-5

# C07 registered condition (2026-10-13): the ONLY change versus M2m-d is the keep
# weight lambda 1.0 -> 10.0. The frozen base plan stays byte-identical and its
# SHA is carried for provenance; the modified copy gets its own condition SHA.
# Motivation: the E17 diagnosis measured the keep gradient at ~3.7% of the
# memory gradient, so lambda=1 was too weak to constrain the drift.
C07_PROTOCOL = "m2m_d_lambda10_action_preservation_v1"
LAMBDA_KEEP_V2 = 10.0


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


# ---------------------------------------------------------------- B2 records


def public_records_from_episodes(train_episodes) -> dict:
    """Public identities keyed by episode_id, same algorithm as the diverse pool.

    Episode SHA = digest(episode.model_dump(json)); transition SHA = digest of the
    admitted transition dump; transition keys and target_tick are Python int.
    """
    from ainerzero.core.experience import TrainingPolicy, admit_training
    from ainerzero.runtime.c0_collection import RANDOM_ACTOR

    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    records = {}
    for episode in train_episodes:
        context = episode.initial.context
        if context.partition.value != "train":
            raise ValueError("public records are built from train episodes only")
        episode_id = str(context.episode_id)
        if episode_id in records:
            raise ValueError("duplicate train episode")
        transitions = {}
        for index, item in enumerate(episode.transitions):
            transition = admit_training(item, policy)
            transitions[int(index)] = {
                "target_observation_id": str(transition.observation.id),
                "current_observation_id": str(transition.next_observation.id),
                "action_request_id": str(transition.action_request.id),
                "public_transition_sha256": _digest(transition.model_dump(mode="json")),
                "target_tick": int(transition.observation.step),
            }
        records[episode_id] = {
            "partition": "train",
            "environment_instance_id": str(context.environment_instance_id),
            "public_episode_sha256": _digest(episode.model_dump(mode="json")),
            "transitions": transitions,
        }
    return records


_RECORD_FIELDS = frozenset({"partition", "environment_instance_id", "public_episode_sha256", "transitions"})
_TRANSITION_FIELDS = frozenset({
    "target_observation_id", "current_observation_id", "action_request_id",
    "public_transition_sha256", "target_tick",
})


def _strict_records(public_records) -> dict:
    """Reject non-int transition keys/ticks and unknown fields (incl. forged flags)."""
    if not isinstance(public_records, Mapping) or not public_records:
        raise ValueError("production windows require public_records from the train episodes")
    out = {}
    for episode_id, record in public_records.items():
        if type(episode_id) is not str or not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
            raise ValueError("public record must have exactly the registered identity fields")
        transitions = record["transitions"]
        if not isinstance(transitions, Mapping):
            raise ValueError("public record transitions must be a mapping")
        checked = {}
        for key, value in transitions.items():
            if type(key) is not int:
                raise ValueError("transition keys must be Python int (not str/np.int64)")
            if not isinstance(value, Mapping) or set(value) != _TRANSITION_FIELDS:
                raise ValueError("transition record must have exactly the registered fields")
            if type(value["target_tick"]) is not int:
                raise ValueError("target_tick must be Python int")
            checked[key] = dict(value)
        out[episode_id] = {**record, "transitions": checked}
    return out


# ---------------------------------------------------------------- B1 windows


def require_production_windows(windows: Mapping) -> dict:
    """Independent re-check of windows; reads no *_verified/*_checked flag."""
    if not isinstance(windows, Mapping) or dict(windows.get("registered_input") or {}) != dict(
        ap.REGISTERED_INPUT
    ):
        raise ValueError("production needs registered_input windows (generic windows rejected)")
    checked = ap.validate_windows(windows)
    if checked["windows_sha256"] != ap.REGISTERED_WINDOWS_SHA256:
        raise ValueError("windows differ from the registered v2 windows")
    keys = ap.key_manifest(windows)
    check_keys(keys)
    return keys


def check_keys(keys: Mapping) -> None:
    if keys.get("manifest_sha256") != REGISTERED_KEY_MANIFEST_SHA256:
        raise ValueError("key manifest v2 binding differs from registration")
    if keys.get("keys_sha256") != REGISTERED_KEYS_CONTENT_SHA256:
        raise ValueError("key content differs from registration")
    rows = keys.get("rows")
    body = {"rows": rows, "teacher": keys.get("teacher_online")}
    if _digest(body) != REGISTERED_KEYS_CONTENT_SHA256:
        raise ValueError("listed keys do not hash to the registered key content")


def student_units_per_update(windows: Mapping) -> list[int]:
    rows = windows["rows"]
    table = [sum(1 + rows[int(r)]["feedback"] + ap.ROLLOUT_STEPS for r in batch) for batch in windows["schedule"]]
    low, high = STUDENT_UPDATE_UNITS_RANGE
    if len(table) != ap.UPDATE_COUNT or sum(table) != ap.STUDENT_UNITS or not all(low <= v <= high for v in table):
        raise ValueError("student units per update must be 200 entries in 137..144 summing to 27988")
    return table


def production_windows(samples: Sequence[Mapping], schedule, public_records) -> dict:
    records = _strict_records(public_records)
    windows = ap.verify_registered_inputs(samples, schedule, partition="train", public_records=records)
    keys = require_production_windows(windows)
    return {"windows": windows, "keys": keys, "student_units": student_units_per_update(windows)}


# ---------------------------------------------------------------- M2l reuse


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _cell_arrays(cell, label):
    if not isinstance(cell, Mapping) or set(cell) != {"argmax", "nll"}:
        raise ValueError(f"{label}: cell result needs argmax/nll")
    argmax, nll = cell["argmax"], cell["nll"]
    if len(argmax) != ap.CELLS or len(nll) != ap.CELLS or not all(type(v) is int for v in argmax):
        raise ValueError(f"{label}: cell shape/type mismatch")
    values = np.array([np.nan if v is None else v for v in nll], dtype=np.float64)
    if not all(v is None or (type(v) is float and math.isfinite(v)) for v in nll):
        raise ValueError(f"{label}: cell nll must be finite or None")
    return np.asarray(argmax, dtype=np.int64), values


def _metrics(argmax, nll, targets, target_mask, current, current_mask, label) -> dict:
    if not np.array_equal(np.isnan(nll), ~target_mask):
        raise ValueError(f"{label}: nll present exactly on visible targets")
    changed = target_mask & current_mask & (targets != current)
    unchanged = target_mask & current_mask & (targets == current)
    correct = argmax == targets

    def part(mask):
        n = int(mask.sum())
        return n, (float(np.mean(correct[mask])) if n else None), (float(np.mean(nll[mask])) if n else None)

    count, accuracy, value = part(target_mask)
    c_count, c_acc, c_nll = part(changed)
    u_count, u_acc, u_nll = part(unchanged)
    return {"count": count, "accuracy": accuracy, "nll": value, "changed_count": c_count,
            "changed_accuracy": c_acc, "changed_nll": c_nll, "unchanged_count": u_count,
            "unchanged_accuracy": u_acc, "unchanged_nll": u_nll}


def _close(observed, expected, label, stats):
    for key, value in observed.items():
        want = expected.get(key)
        if isinstance(value, int) or value is None or want is None:
            if value != want:
                raise ValueError(f"{label}.{key}: {value} != {want}")
        else:
            diff = abs(value - want)
            stats["max_float_diff"] = max(stats["max_float_diff"], diff)
            if diff > FLOAT_TOLERANCE:
                raise ValueError(f"{label}.{key}: {value} vs {want}")
        stats["compared"] += 1


PAIRED_COUNT_FIELDS = tuple(
    f"{prefix}{name}"
    for prefix in ("", "changed_")
    for name in ("count", "history_only_correct", "zero_only_correct", "both_correct",
                 "neither_correct", "prediction_disagreements")
)


def paired_counts(history_argmax, zero_argmax, targets, target_mask, current, current_mask) -> dict:
    """Same-query history/zero pairing counts (paired_memory._paired_counts rule, from argmax)."""
    changed = target_mask & current_mask & (targets != current)
    h_correct, z_correct = history_argmax == targets, zero_argmax == targets
    out = {}
    for prefix, mask in (("", target_mask), ("changed_", changed)):
        out.update({
            f"{prefix}count": int(mask.sum()),
            f"{prefix}history_only_correct": int((mask & h_correct & ~z_correct).sum()),
            f"{prefix}zero_only_correct": int((mask & z_correct & ~h_correct).sum()),
            f"{prefix}both_correct": int((mask & h_correct & z_correct).sum()),
            f"{prefix}neither_correct": int((mask & ~h_correct & ~z_correct).sum()),
            f"{prefix}prediction_disagreements": int((mask & (history_argmax != zero_argmax)).sum()),
        })
    return out


def paired_result(counts: Mapping, methods: Mapping) -> dict:
    """counts plus history_minus_zero_{accuracy,nll,changed_accuracy,changed_nll}."""
    out = dict(counts)
    history, zero = methods["history_tail"], methods["zero_context_tail"]
    for field in ("accuracy", "nll", "changed_accuracy", "changed_nll"):
        a, b = history[field], zero[field]
        out[f"history_minus_zero_{field}"] = None if a is None or b is None else a - b
    return out


def _close_all(observed, expected, label, stats):
    if set(observed) != set(expected):
        raise ValueError(f"{label}: field set differs {sorted(set(observed) ^ set(expected))}")
    _close(observed, expected, label, stats)


def recompute_paired(cells: Sequence[Mapping], frames: Mapping, queries: Sequence[Mapping], expected: Mapping) -> dict:
    """Per-query, per-world and per-group methods AND paired stats from saved cells (M2k rules)."""
    from ainerzero.learning.evaluation import _Summary

    if len(cells) != PAIRED_QUERIES or len(queries) != PAIRED_QUERIES:
        raise ValueError("paired cells must cover the 2560 registered queries")
    if len(expected["per_query"]) != PAIRED_QUERIES:
        raise ValueError("M2l paired report must list 2560 queries")
    stats = {"compared": 0, "max_float_diff": 0.0}
    groups = {name: {b: _Summary() for b in PAIRED_BRANCHES} for name in expected["groups"]}
    worlds: dict[int, dict] = {}
    group_counts = {name: dict.fromkeys(PAIRED_COUNT_FIELDS, 0) for name in expected["groups"]}
    world_counts: dict[int, dict] = {}
    for index, (row, query) in enumerate(zip(cells, queries, strict=True)):
        if not isinstance(row, Mapping) or set(row) != set(PAIRED_BRANCHES):
            raise ValueError(f"query {index}: cells need both branches")
        report_row = expected["per_query"][index]
        if (report_row.get("episode_id"), report_row.get("query_tick")) != (query["episode_id"], query["query_tick"]):
            raise ValueError(f"query {index}: order differs from the registered manifest")
        world = report_row["world_index"]
        bucket = worlds.setdefault(world, {b: _Summary() for b in PAIRED_BRANCHES})
        frame = (frames["previous_symbols"][index], frames["previous_visible"][index],
                 frames["current_symbols"][index], frames["current_visible"][index])
        methods, argmaxes = {}, {}
        for branch in PAIRED_BRANCHES:
            argmax, nll = _cell_arrays(row[branch], f"query {index}.{branch}")
            value = _metrics(argmax, nll, *frame, f"query {index}.{branch}")
            _close(value, report_row["methods"][branch], f"per_query[{index}].{branch}", stats)
            groups[query["group"]][branch].add(value)
            bucket[branch].add(value)
            methods[branch], argmaxes[branch] = value, argmax
        counts = paired_counts(argmaxes["history_tail"], argmaxes["zero_context_tail"], *frame)
        _close_all(paired_result(counts, methods), report_row["paired"], f"per_query[{index}].paired", stats)
        totals = world_counts.setdefault(world, dict.fromkeys(PAIRED_COUNT_FIELDS, 0))
        for name, count in counts.items():
            totals[name] += count
            group_counts[query["group"]][name] += count
    for name, summaries in groups.items():
        results = {branch: summary.result() for branch, summary in summaries.items()}
        for branch, result in results.items():
            _close(result, expected["groups"][name]["methods"][branch], f"groups.{name}.{branch}", stats)
        _close_all(paired_result(group_counts[name], results), expected["groups"][name]["paired"],
                   f"groups.{name}.paired", stats)
    for entry in expected["per_world"]:
        results = {branch: worlds[entry["world_index"]][branch].result() for branch in PAIRED_BRANCHES}
        for branch in PAIRED_BRANCHES:
            _close(results[branch], entry["methods"][branch], f"per_world[{entry['world_index']}].{branch}", stats)
        _close_all(paired_result(world_counts[entry["world_index"]], results), entry["paired"],
                   f"per_world[{entry['world_index']}].paired", stats)
    if len(worlds) != len(expected["per_world"]):
        raise ValueError("paired worlds differ from the M2l report")
    return stats


def m2l_reuse_closure(m2mc_report_path, relabel_binding: Mapping, store, *, episodes) -> dict:
    """Read-only reuse of frozen M2l paired/relabel-pool cells from the M2m-c report."""
    from ainerzero.learning.coverage_diagnostic import query_frames
    from ainerzero.learning.relabel_memory import summarize_relabel_pool

    data = Path(m2mc_report_path).read_bytes()
    file_sha = hashlib.sha256(data).hexdigest()
    if file_sha != M2MC_REPORT_SHA256:
        raise ValueError("M2m-c report file SHA differs from registration")
    report = json.loads(data)
    if report.get("status") != "completed" or report.get("run_id") != M2MC_RUN_ID:
        raise ValueError("M2m-c report must be the completed registered run")
    if report.get("relabel", {}).get("m2l") != relabel_binding["report"]["m2l"]:
        raise ValueError("M2m-c M2l reference differs from the rebuilt M2l reference")
    if report.get("m2l_paired_reproduction", {}).get("exact_match") is not True:
        raise ValueError("M2m-c did not reproduce the M2l paired report exactly")
    paired_cells = report["cells"]["m2l"]
    frames, evidence = query_frames(episodes)
    expected_manifest = relabel_binding["m2l_report"]["paired"].get("query_manifest_sha256")
    if evidence["query_manifest_sha256"] != expected_manifest:
        raise ValueError("episodes' query manifest differs from the M2l paired report")
    paired = recompute_paired(paired_cells, frames, evidence["queries"], relabel_binding["m2l_report"]["paired"])
    pool_cells = report["relabel_pool"]["m2l_cells"]
    batch = relabel_binding["batch"]
    rows = len(batch["symbols"])
    if len(pool_cells["argmax"]) != rows or len(pool_cells["nll"]) != rows:
        raise ValueError("relabel pool cells must cover the registered relabel pool")
    pool_argmax = np.empty((rows, ap.CELLS), dtype=np.int64)
    pool_nll = np.empty((rows, ap.CELLS), dtype=np.float64)
    for index in range(rows):
        pool_argmax[index], pool_nll[index] = _cell_arrays(
            {"argmax": pool_cells["argmax"][index], "nll": pool_cells["nll"][index]}, f"pool {index}"
        )
    pool = summarize_relabel_pool(pool_argmax, pool_nll, batch)
    if pool != report["relabel_pool"]["m2l"]:
        raise ValueError("CPU recompute of the M2l relabel pool differs from the M2m-c report")
    run = store.get_run(M2MC_RUN_ID)
    if (run.state != "completed" or run.role != "model" or run.reserved_optimizer_steps != 200
            or run.reserved_model_transitions != M2MC_RESERVED_UNITS):
        raise ValueError("canonical ledger does not confirm the completed M2m-c run")
    m2l = relabel_binding["m2l_report"]
    prior = store.get_run(m2l["run_id"])
    experiment = store.get_experiment(prior.experiment_id)
    if (prior.state != "completed" or prior.experiment_id != m2l.get("experiment_id") or prior.role != "model"
            or prior.reserved_optimizer_steps != 200 or prior.reserved_environment_steps != 0
            or prior.reserved_model_transitions != M2L_RESERVED_UNITS
            or experiment.manifest_hash != m2l["manifest_hash"]):
        raise ValueError("canonical ledger does not confirm the completed M2l candidate")
    return {
        "paired_cells": paired_cells,
        "relabel_pool_cells": pool_cells,
        "relabel_pool": pool,
        "m2mc_report_bytes": data,
        "evidence": {
            "m2mc_report": {"path": str(Path(m2mc_report_path).resolve()), "sha256": file_sha, "run_id": M2MC_RUN_ID},
            "paired_cells_sha256": _digest(paired_cells),
            "relabel_pool_cells_sha256": _digest(pool_cells),
            "paired_recompute": paired,
            "relabel_pool_recompute_equal": True,
            "m2l_run_id": m2l["run_id"],
            "ledger": {"m2mc_units": M2MC_RESERVED_UNITS, "m2l_units": M2L_RESERVED_UNITS},
            "m2l_weights_loaded": False,
        },
    }


# ---------------------------------------------------------------- cache binding


def teacher_source_sha256(learning_dir=None) -> str:
    base = Path(learning_dir) if learning_dir is not None else Path(__file__).parent
    return _digest({name: _sha(base / name) for name in TEACHER_SOURCE_FILES})


def expected_cache_binding(*, checkpoint_path, windows: Mapping, keys: Mapping, run_id: str,
                           source_sha256: str | None = None) -> dict:
    """Trusted 14-field binding; never copied from the cache or its manifest."""
    keys_checked = require_production_windows(windows)
    if keys_checked["manifest_sha256"] != keys.get("manifest_sha256"):
        raise ValueError("keys do not belong to these windows")
    check_keys(keys)
    binding = {
        "protocol": ap.PROTOCOL,
        "teacher_checkpoint": ap.SOURCE_CHECKPOINT,
        "teacher_checkpoint_manifest_sha256": _sha(Path(checkpoint_path) / "manifest.json"),
        "teacher_source_sha256": source_sha256 or teacher_source_sha256(),
        "architecture": ap.TEACHER_ARCHITECTURE,
        "training_samples_sha256": ap.REGISTERED_INPUT["sample_manifest_sha256"],
        "schedule_sha256": ap.REGISTERED_INPUT["schedule_sha256"],
        "windows_sha256": ap.REGISTERED_WINDOWS_SHA256,
        "key_manifest_sha256": REGISTERED_KEY_MANIFEST_SHA256,
        "particles": 1,
        "temperature": ap.TEMPERATURE,
        "mask_rule": ap.MASK_RULE,
        "run_id": run_id,
        "budget_units": ap.TEACHER_UNITS,
    }
    return ap.validate_cache_binding(binding)


# ---------------------------------------------------------------- gates


def _count(accuracy, count, label) -> int:
    if accuracy is None or type(count) is not int:
        raise ValueError(f"{label}: missing accuracy/count")
    value = accuracy * count
    exact = round(value)
    if abs(value - exact) > 1e-6:
        raise ValueError(f"{label}: accuracy is not an integer count")
    return int(exact)


def preservation_screen(before: Mapping, after: Mapping, paired: Mapping, relabel_pool: Mapping) -> dict:
    gates = ap.PRESERVATION_GATES
    checks = {}
    dev = paired["groups"]["development"]["methods"]["zero_context_tail"]
    g = gates["development_zero_context"]
    if dev["count"] != g["overall_of"] or dev["changed_count"] != g["changed_of"]:
        raise ValueError("development denominators differ from the registered 4096/127")
    correct = _count(dev["accuracy"], dev["count"], "development")
    changed = _count(dev["changed_accuracy"], dev["changed_count"], "development changed")
    checks["development_zero_context"] = {"correct": correct, "changed_correct": changed,
                                          "passed": correct >= g["overall_min"] and changed >= g["changed_min"]}
    g = gates["relabel_pool"]
    if relabel_pool["count"] != g["overall_of"] or relabel_pool["changed_count"] != g["changed_of"]:
        raise ValueError("relabel pool denominators differ from the registered 2048/140")
    correct, changed = relabel_pool["correct"], relabel_pool["changed_correct"]
    if type(correct) is not int or type(changed) is not int:
        raise ValueError("relabel pool counts must be int")
    checks["relabel_pool"] = {"correct": correct, "changed_correct": changed,
                              "passed": correct >= g["overall_min"] and changed >= g["changed_min"]}
    for horizon in ("1", "4"):
        g = gates[f"action_{horizon}"]
        new = after["action"]["horizons"][horizon]["model"]
        old = before["action"]["horizons"][horizon]["model"]
        if new["count"] != g["of"] or old["count"] != g["of"]:
            raise ValueError(f"action h={horizon} denominator differs from 384")
        correct = _count(new["accuracy"], new["count"], f"action {horizon}")
        increase = new["nll"] - old["nll"]
        if not math.isfinite(increase):
            raise ValueError("action NLL must be finite")
        checks[f"action_{horizon}"] = {"correct": correct, "nll_increase": increase,
                                       "passed": correct >= g["accuracy_min"] and increase <= g["nll_increase_max"]}
    g = gates["reconstruction"]
    model = after["reconstruction"]["model"]
    correct = _count(model["accuracy"], model["count"], "reconstruction") if model["count"] else 0
    checks["reconstruction"] = {
        "gate": after["reconstruction"]["gate"]["status"], "correct": correct,
        "passed": after["reconstruction"]["gate"]["status"] == g["gate"] and model["count"] == g["of"]
        and correct == g["correct"],
    }
    return {"checks": checks, "status": "passed" if all(c["passed"] for c in checks.values()) else "failed",
            "promotion": False, "automatic_next_run": False}


# ------------------------------------------------- first-update alignment guard


def check_first_update_keep_loss(losses, *, bound: float = FIRST_UPDATE_KEEP_LOSS_MAX) -> dict:
    """Fail closed when the first update's per-row keep loss is non-finite or above bound.

    The registered bound replaces the original exact-0.0 condition (see the
    C06a amendment note above). A real key/tick/window/state misalignment gives
    O(1) loss, so the bound keeps the diagnostic power while tolerating float32
    rounding; non-finite values always stop the run.
    """
    values = [float(v) for v in losses]
    if not values:
        raise ValueError("first update must report at least one row keep loss")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("first-update keep loss must be finite")
    worst = max(abs(v) for v in values)
    result = {
        "count": len(values),
        "max": max(values),
        "max_abs": worst,
        "registered_max_abs": float(bound),
        "all_exact_zero": worst == 0.0,
        "within_registered_bound": worst <= bound,
    }
    if worst > bound:
        raise ValueError(
            f"first-update keep loss {worst} exceeds the registered bound {bound}"
        )
    return result


# --------------------------------------------------- C07 lambda condition (CPU)


def c07_condition_plan() -> dict:
    """Registered C07 condition: frozen base plan with keep lambda 1.0 -> 10.0.

    The base plan is re-verified against its own registration first, then copied;
    the copy carries `base_plan_sha256` plus its own `condition_sha256` so the
    single-factor claim stays auditable.
    """
    plan = ap.action_preservation_plan()
    if ap.verify_frozen_plan(plan) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("C07 base plan differs from the frozen M2m-d registration")
    if plan["keep_branch"]["lambda"] != ap.LAMBDA_KEEP:
        raise RuntimeError("C07 base plan must start from the registered lambda")
    plan["base_plan_sha256"] = ap.FROZEN_PLAN_SHA256
    plan["base_protocol"] = plan["protocol"]
    plan["protocol"] = C07_PROTOCOL
    plan["keep_branch"] = {**plan["keep_branch"], "lambda": LAMBDA_KEEP_V2}
    plan["single_factor"] = "keep_lambda_only_base_plan_otherwise_identical"
    plan["condition_sha256"] = _digest(plan)
    return plan


def combine_branch_gradients_v2(memory_sum: Mapping, memory_targets: float,
                                keep_row_grads: Sequence[Mapping], *, lam) -> dict:
    """`ap.combine_branch_gradients` with an explicit registered lambda.

    Same validation order and arithmetic as the frozen CPU reference; with
    ``lam == ap.LAMBDA_KEEP`` (1.0) the result is bitwise identical, which the
    tests assert. Only the lambda is parameterised -- no other protocol change.
    """
    if type(lam) not in (int, float) or isinstance(lam, bool) \
            or not math.isfinite(lam) or lam <= 0:
        raise ValueError("keep lambda must be a finite positive number (not bool)")
    targets = ap._positive_count(memory_targets)
    if not isinstance(memory_sum, Mapping) or not memory_sum:
        raise ValueError("gradient tree must be non-empty")
    if len(keep_row_grads) != ap.ROWS_PER_UPDATE:
        raise ValueError("keep branch must cover the 16 scheduled rows")
    keys = set(memory_sum)
    shapes = {k: ap._leaf(memory_sum[k], k).shape for k in keys}
    for row in keep_row_grads:
        if not isinstance(row, Mapping) or set(row) != keys:
            raise ValueError("branch gradient trees differ")
        for key in keys:
            if ap._leaf(row[key], key).shape != shapes[key]:
                raise ValueError(f"leaf shape mismatch in {key}")
    out = {}
    for key in keys:
        keep = sum(ap._leaf(row[key], key) for row in keep_row_grads) / ap.ROWS_PER_UPDATE
        value = ap._leaf(memory_sum[key], key) / targets + float(lam) * keep
        if not np.isfinite(value).all():
            raise ValueError(f"non-finite combined gradient in {key}")
        out[key] = value
    return out


# ------------------------------- D condition: in-batch teacher distillation (CPU)

D_PROTOCOL = "m2m_d1_inbatch_teacher_distillation_v1"


def d_condition_plan() -> dict:
    """Registered D condition: fold the teacher KL into the memory batch itself.

    Root cause from C07: the M2m-d keep branch compared a *relabelled* student
    against an *unrelabelled* teacher on the same rows, so raising lambda only
    deepened the symbol-space conflict. D keeps lambda=1 but routes the teacher
    signal through the same batch, the same forward pass and the same relabelled
    symbols the memory objective scores; the separate 16-row keep branch (and its
    cache) is removed, and the teacher runs online once per update instead.
    """
    plan = ap.action_preservation_plan()
    if ap.verify_frozen_plan(plan) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("D base plan differs from the frozen M2m-d registration")
    plan["base_plan_sha256"] = ap.FROZEN_PLAN_SHA256
    plan["base_protocol"] = plan["protocol"]
    plan["protocol"] = D_PROTOCOL
    plan["single_factor"] = "loss_routing_only_same_batch_same_forward"
    plan["loss"] = ("L_memory + 1.0 * KL(p_M2d || p_student) on the SAME relabelled "
                    "memory batch cells and the SAME forward pass")
    plan["keep_branch"] = {**plan["keep_branch"], "rows": 0,
                           "mode": "in_batch_same_forward_relabelled_teacher"}
    plan["teacher_cache"] = "none_teacher_online_once_per_update_on_the_same_batch"
    plan["units"] = {"retained": 178_304, "teacher_online": 6_400, "keep_branch": 0, "total": 184_704}
    plan["seconds"] = {"retained_fixed": 940, "updates": 600, "prepaid": 1_540,
                       "work_deadline": 1_590, "supervisor_deadline": 1_640}
    plan["condition_sha256"] = _digest(plan)
    return plan


# ------------------------- M2n condition: nonzero-history windows (CPU, M2n/E23)

M2N_PROTOCOL = "m2m_n_nonzero_history_one_step_v1"
# SequenceSampler(sequence_steps=S) yields burn_in + S transitions (M2h: 4+16=20),
# so 8 loss steps mean 12 transitions / 13 frames per sample (review finding F2).
M2N_LOSS_STEPS = 8
M2N_TRANSITIONS = 12
M2N_UNITS_PER_UPDATE = 2 * 16 * (M2N_TRANSITIONS + 1)


def m2n_condition_plan() -> dict:
    """Registered M2n condition: D's in-batch distillation over real history windows.

    New capability experiment (not a single-factor ablation of D): the memory
    branch trains on multi-step public history (burn_in=4 context edges plus 8
    loss edges = 12 transitions / 13 frames) instead of single edges, so the student must use its own
    recurrent state. Everything else (source, scope, seeds, gates, evaluations,
    lambda=1 in-batch distillation) stays as registered for D.
    """
    plan = ap.action_preservation_plan()
    if ap.verify_frozen_plan(plan) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("M2n base plan differs from the frozen M2m-d registration")
    plan["base_plan_sha256"] = ap.FROZEN_PLAN_SHA256
    plan["base_protocol"] = plan["protocol"]
    plan["protocol"] = M2N_PROTOCOL
    plan["single_factor"] = "new_capability_history_windows_multiple_formulation_changes_disclosed"
    plan["memory_windows"] = ("sampler_history_windows_burn_in_4_sequence_steps_8_"
                              "no_relabel_manifest_per_window_byte_permutation")
    plan["loss"] = ("L_memory over 8 loss edges conditioned on 4 real context edges "
                    "(12 transitions / 13 frames) + "
                    "1.0 * KL(p_M2d || p_student) on the SAME batch and forward pass")
    plan["keep_branch"] = {**plan["keep_branch"], "rows": 0,
                           "mode": "in_batch_same_forward_relabelled_teacher"}
    plan["teacher_cache"] = "none_teacher_online_once_per_update_on_the_same_batch"
    plan["units"] = {"retained": 171_904, "student_history": 41_600,
                     "teacher_online": 41_600, "keep_branch": 0, "total": 255_104}
    plan["seconds"] = {"retained_fixed": 940, "updates": 800, "prepaid": 1_740,
                       "work_deadline": 1_760, "supervisor_deadline": 1_790}
    plan["windows"] = {"burn_in": 4, "loss_steps": M2N_LOSS_STEPS,
                       "transitions_per_window": M2N_TRANSITIONS,
                       "frames_per_sample": M2N_TRANSITIONS + 1,
                       "units_per_update": M2N_UNITS_PER_UPDATE}
    plan["condition_sha256"] = _digest(plan)
    return plan


# ---------------- M2n-M condition: mixed single-edge + history batch (E24)

MIXED_PROTOCOL = "m2m_n_mixed_single_edge_history_v1"
MIXED_SINGLE_ROWS = 12
MIXED_HISTORY_ROWS = 4
MIXED_HISTORY_BURN_IN = 4
MIXED_HISTORY_LOSS_STEPS = 8
MIXED_HISTORY_TRANSITIONS = MIXED_HISTORY_BURN_IN + MIXED_HISTORY_LOSS_STEPS  # 12
MIXED_SINGLE_UNITS_PER_ROW = 2          # one edge: two frames
MIXED_HISTORY_UNITS_PER_ROW = MIXED_HISTORY_TRANSITIONS + 1  # 13 frames
MIXED_UNITS_PER_UPDATE = 2 * (MIXED_SINGLE_ROWS * MIXED_SINGLE_UNITS_PER_ROW
                              + MIXED_HISTORY_ROWS * MIXED_HISTORY_UNITS_PER_ROW)  # 152


def mixed_condition_plan() -> dict:
    """Registered mixed-batch condition: mostly single-edge, one quarter history.

    Tests the displacement explanation for M2n: if multi-step history reshaped the
    recurrent dynamics away from the single-edge regime, then restricting history to
    a quarter of the batch should preserve the single-edge capability while keeping
    the (still sub-threshold) retention readout that M2n produced.

    Split rule: rows 0-11 of the registered 16-row schedule stay single-edge with the
    registered per-row bijections (all 16 rows are still relabelled, so the manifest
    digest stream is byte-identical to M2m-d/C07/D); rows 12-15 are not trained and
    the history half is drawn from the registered window seed instead.
    """
    plan = ap.action_preservation_plan()
    if ap.verify_frozen_plan(plan) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("mixed base plan differs from the frozen M2m-d registration")
    plan["base_plan_sha256"] = ap.FROZEN_PLAN_SHA256
    plan["base_protocol"] = plan["protocol"]
    plan["protocol"] = MIXED_PROTOCOL
    plan["single_factor"] = "mixed_batch_share_of_history_windows_relative_to_M2n"
    plan["batch"] = {"single_edge_rows": MIXED_SINGLE_ROWS, "history_rows": MIXED_HISTORY_ROWS,
                     "single_edge_form": "registered_two_frame_pool_rows_rows_0_11",
                     "history_form": "sampler_windows_burn_in_4_loss_steps_8",
                     "unused_rows": "schedule_rows_12_15_relabelled_but_not_trained"}
    plan["normalization"] = ("row_weighted_mean_of_per_target_means: "
                             "L_CE=(12*CE_single+4*CE_history)/16, "
                             "L_KL=(12*KL_single+4*KL_history)/16, L=L_CE+1.0*L_KL")
    plan["loss"] = ("L_memory over 12 single-edge rows (2 frames) and 4 history windows "
                    "(12 transitions / 13 frames) + 1.0 * KL(p_M2d || p_student) on the SAME "
                    "sub-batch and forward pass of each half")
    plan["keep_branch"] = {**plan["keep_branch"], "rows": 0,
                           "mode": "in_batch_same_forward_teacher_on_each_half"}
    plan["teacher_cache"] = "none_teacher_online_once_per_half_per_update"
    student_single = 200 * MIXED_SINGLE_ROWS * MIXED_SINGLE_UNITS_PER_ROW
    student_history = 200 * MIXED_HISTORY_ROWS * MIXED_HISTORY_UNITS_PER_ROW
    teacher = 200 * MIXED_SINGLE_ROWS * MIXED_SINGLE_UNITS_PER_ROW \
        + 200 * MIXED_HISTORY_ROWS * MIXED_HISTORY_UNITS_PER_ROW
    plan["units"] = {"retained": 171_904, "single_edge_student": student_single,
                     "history_student": student_history, "teacher_online": teacher,
                     "keep_branch": 0,
                     "total": 171_904 + student_single + student_history + teacher
                     + 200 * 0}
    plan["seconds"] = {"retained_fixed": 1_140, "updates": 600, "prepaid": 1_740,
                       "work_deadline": 1_760, "supervisor_deadline": 1_780,
                       "amendment": ("evaluation windows +67% on the two memory partitions and "
                                     "+20% on the other six (registered 2026-10-13) after two "
                                     "bounded attempts died on the 90 s before_memory_train window "
                                     "under Metal contention invisible to load averages")}
    plan["history_permutation"] = {
        "stream": "separate_registered_generator",
        "seed": 2407,
        "why": "the 16-row single-edge relabel stream must stay byte-identical to the "
               "registered manifest, so the history half must not consume it (finding B-F3)",
    }
    plan["sampler_geometry"] = {"burn_in": MIXED_HISTORY_BURN_IN,
                                "sequence_steps": MIXED_HISTORY_LOSS_STEPS}
    plan["windows"] = {
        "single_edge_transitions": 1,
        "history_burn_in": MIXED_HISTORY_BURN_IN,
        "history_loss_steps": MIXED_HISTORY_LOSS_STEPS,
        "history_transitions": MIXED_HISTORY_TRANSITIONS,
        "history_frames": MIXED_HISTORY_UNITS_PER_ROW,
        "single_edge_units_per_row": MIXED_SINGLE_UNITS_PER_ROW,
        "units_per_update": MIXED_UNITS_PER_UPDATE,
        "units_per_update_breakdown": {
            "student_single_edge": MIXED_SINGLE_ROWS * MIXED_SINGLE_UNITS_PER_ROW,
            "student_history": MIXED_HISTORY_ROWS * MIXED_HISTORY_UNITS_PER_ROW,
            "teacher_both_halves": (MIXED_SINGLE_ROWS * MIXED_SINGLE_UNITS_PER_ROW
                                    + MIXED_HISTORY_ROWS * MIXED_HISTORY_UNITS_PER_ROW),
        },
    }
    plan["condition_sha256"] = _digest(plan)
    return plan


# ------- M2n-M2 condition: mixed batch with the history half weighted by lambda_h (A3)

WEIGHT025_PROTOCOL = "m2m_n_mixed_history_weight025_v1"
WEIGHT0_CONTROL_PROTOCOL = "m2m_n_mixed_history_weight0_control_v1"
MIXED_HISTORY_WEIGHT = 0.25   # lambda_h, registered in A3
MIXED_CONTROL_HISTORY_WEIGHT = 0.0
MIXED_KEEP_WEIGHT = 1.0       # the single-edge half is not scaled
A3_DESIGN_REGISTRATION_SHA256 = "279655b7be9dc8f6fa387e503c897a5b07b1659569e4f04c30a2f5200abd7962"
CONTROL_DESIGN_REGISTRATION_SHA256 = "84cf6938e0156f74283032111d9aafd8c2b553b249742b8106297e879b91ef25"
WEIGHT025_DUTY_PATH = ("resources", "active", "training_duty_cycle")
WEIGHT025_SOURCE_DUTY = 0.25
WEIGHT025_LIVE_DUTY = 1.0


def mixed_half_weights(single_rows: int, history_rows: int, history_weight: float, protocol: str | None = None) -> tuple[dict, float]:
    """Row weights for combining the two per-target-mean halves, and the fixed denominator.

    The history half's CE and KL (and therefore its gradient) are multiplied by
    ``history_weight``; the denominator stays the registered row count (16) and is
    NOT renormalized to the new weight sum (A3: renormalize_after_scaling=false).
    With 12/4 and 0.25: L = 0.75*(CE_s+KL_s) + 0.0625*(CE_h+KL_h).
    """
    valid = (0.0 <= history_weight <= 1.0) if protocol == WEIGHT0_CONTROL_PROTOCOL else (0.0 < history_weight <= 1.0)
    if not valid or single_rows <= 0 or history_rows <= 0:
        raise ValueError("history weight must be in (0, 1] and both halves non-empty")
    weights = {"single_edge": float(single_rows) * float(history_weight),
               "history": float(history_rows)}
    return weights, float(single_rows + history_rows)


def mixed_weight0_half_weights(single_rows: int, history_rows: int) -> tuple[dict, float]:
    """M2n-M3-control: the registered lambda_h = 0.0 weights, passed explicitly under the new protocol."""
    return mixed_half_weights(single_rows, history_rows, MIXED_CONTROL_HISTORY_WEIGHT,
                              protocol=WEIGHT0_CONTROL_PROTOCOL)


def combine_mixed_halves(half_values: dict, weights: dict, denominator: float, tree_map):
    """sum_h weights[h] * value_h / denominator; applied once, before mask/clip/AdamW."""
    if set(half_values) != set(weights) or denominator <= 0:
        raise ValueError("mixed halves and weights must name the same halves")
    combined = None
    for name in sorted(half_values):
        scaled = tree_map(lambda g, w=weights[name]: g * w, half_values[name])
        combined = scaled if combined is None else tree_map(lambda a, b: a + b, combined, scaled)
    return tree_map(lambda g: g / denominator, combined)


def mixed_gradient_shares(flat_halves: dict, rows: dict, weights: dict) -> dict:
    """Per-half gradient-share telemetry before and after the lambda_h scaling.

    ``flat_halves`` maps half -> {param: ndarray} (per-target-mean, masked).
    Reports the norm-sum share (comparable with E24 telemetry) and the exact
    projection share <c_h, G>/||G||^2, where c_h is the half's contribution and
    G = sum_h c_h, which sums to 1 (E24 review F2).
    """
    out = {}
    for label, coeff in (("before_scaling", rows), ("after_scaling", weights)):
        contrib = {h: {k: np.asarray(v, dtype=np.float64) * float(coeff[h]) for k, v in g.items()}
                   for h, g in flat_halves.items()}
        keys = sorted(next(iter(contrib.values())))
        total = {k: sum(c[k] for c in contrib.values()) for k in keys}
        g2 = float(sum(np.sum(total[k] ** 2) for k in keys))
        norms = {h: float(np.sqrt(sum(np.sum(c[k] ** 2) for k in keys))) for h, c in contrib.items()}
        norm_sum = sum(norms.values())
        out[label] = {
            h: {
                "norm_share": norms[h] / norm_sum if norm_sum > 0 else 0.0,
                "projection_share": (float(sum(np.sum(contrib[h][k] * total[k]) for k in keys)) / g2
                                     if g2 > 0 else 0.0),
                "contribution_l2": norms[h],
            }
            for h in contrib
        }
    return out


def mixed_weight025_condition_plan() -> dict:
    """Registered M2n-M2 condition: the E24 mixed batch with lambda_h = 0.25 on history.

    Single scientific change against the E24 mixed condition: the history half's CE
    and KL are multiplied by 0.25; rows, denominator (16), per-half normalization,
    the single-edge front-row invariant, the first-update KL guard, seeds, data,
    bijection streams, budget and evaluation windows are unchanged.
    """
    plan = mixed_condition_plan()
    plan["mixed_condition_sha256"] = plan.pop("condition_sha256")
    plan["mixed_protocol"] = plan["protocol"]
    plan["protocol"] = WEIGHT025_PROTOCOL
    plan["single_factor"] = "history_half_loss_weight_lambda_h_0.25_relative_to_E24_mixed"
    plan["history_weight"] = MIXED_HISTORY_WEIGHT
    plan["renormalize_after_scaling"] = False
    plan["design_registration_sha256"] = A3_DESIGN_REGISTRATION_SHA256
    plan["normalization"] = (
        "row_weighted_mean_of_per_target_means_with_history_weight: "
        "L=(12*(CE_single+KL_single)+0.25*4*(CE_history+KL_history))/16 = "
        "0.75*(CE_single+KL_single)+0.0625*(CE_history+KL_history); denominator stays 16; "
        "applied once before mask/clip/AdamW")
    plan["start"] = {"checkpoint": "original_M2d_f33974c9-b86f-4429-9ea9-8ea0e733142a",
                     "optimizer": "fresh_AdamW", "resume": "none"}
    plan["condition_sha256"] = _digest(plan)
    return plan


def _config_differences(source, live, path=()):
    if isinstance(source, dict) and isinstance(live, dict):
        found = []
        for key in sorted(set(source) | set(live)):
            if key not in source or key not in live:
                found.append({"path": path + (key,), "source": source.get(key), "live": live.get(key)})
            else:
                found.extend(_config_differences(source[key], live[key], path + (key,)))
        return found
    if source != live or type(source) is not type(live):
        return [{"path": path, "source": source, "live": live}]
    return []


def weight025_source_schedule_compat(metadata: dict, live_config: dict, identity: dict) -> dict:
    """Allow only the registered active duty migration, and record it.

    The source config is read from ``metadata["config"]``. Callers cannot pass a
    substitute source. Every other config field, including science, data,
    architecture, optimizer counts and memory/swap/disk/power guards, must match.
    """
    if (
        metadata.get("architecture") != "pilot_shared_symbol_v1"
        or metadata.get("phase") not in {"action_prediction", "action_refinement"}
        or type(metadata.get("optimizer_steps")) is not int
        or metadata["optimizer_steps"] < 1
        or not metadata.get("run_id")
        or metadata.get("dataset_source") != identity
        or not isinstance(metadata.get("config"), dict)
        or not isinstance(live_config, dict)
    ):
        raise ValueError(
            "weight025 source architecture, phase, completed updates, dataset or config mismatch"
        )
    source_config = metadata["config"]
    diffs = _config_differences(source_config, live_config)
    allowed = [
        item for item in diffs
        if item["path"] == WEIGHT025_DUTY_PATH
        and item["source"] == WEIGHT025_SOURCE_DUTY
        and item["live"] == WEIGHT025_LIVE_DUTY
        and type(item["source"]) is float
        and type(item["live"]) is float
    ]
    other = [item for item in diffs if item not in allowed]
    if other or len(allowed) != 1:
        shown = [".".join(item["path"]) for item in other] or ["resources.active.training_duty_cycle"]
        raise ValueError("weight025 source config mismatch: " + ", ".join(shown))
    encoded = json.dumps(
        source_config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return {
        "protocol": WEIGHT025_PROTOCOL,
        "source_config_sha256": hashlib.sha256(encoded).hexdigest(),
        "allowed_difference": {
            "path": "resources.active.training_duty_cycle",
            "source": WEIGHT025_SOURCE_DUTY,
            "live": WEIGHT025_LIVE_DUTY,
        },
    }


def mixed_weight0_control_condition_plan() -> dict:
    """Registered M2n-M3-control condition: E24 mixed batch with lambda_h = 0.0 on history.

    The single scientific change against M2n-M2 (weight025): the history half's CE
    and KL loss weight is set to 0.0 (lambda_h = 0.0); rows, denominator (16),
    per-half normalization, the single-edge front-row invariant, the first-update
    KL guard, seeds, data, bijection streams, budget and evaluation windows are unchanged.
    """
    plan = mixed_condition_plan()
    plan["mixed_condition_sha256"] = plan.pop("condition_sha256")
    plan["mixed_protocol"] = plan["protocol"]
    plan["protocol"] = WEIGHT0_CONTROL_PROTOCOL
    plan["single_factor"] = "history_half_loss_weight_lambda_h_0.0_control_relative_to_E24_mixed"
    plan["history_weight"] = MIXED_CONTROL_HISTORY_WEIGHT
    plan["renormalize_after_scaling"] = False
    plan["design_registration_sha256"] = CONTROL_DESIGN_REGISTRATION_SHA256
    plan["normalization"] = (
        "row_weighted_mean_of_per_target_means_with_history_weight: "
        "L=(12*(CE_single+KL_single)+0.0*4*(CE_history+KL_history))/16 = "
        "0.75*(CE_single+KL_single)+0.0*(CE_history+KL_history); denominator stays 16; "
        "applied once before mask/clip/AdamW"
    )
    plan["start"] = {
        "checkpoint": "original_M2d_f33974c9-b86f-4429-9ea9-8ea0e733142a",
        "optimizer": "fresh_AdamW",
        "resume": "none",
    }
    plan["condition_sha256"] = _digest(plan)
    return plan


ONESTEP_PROTOCOL = "m2m_n_mixed_history_onestep_v1"
ONESTEP_DESIGN_REGISTRATION_SHA256 = "fa3a37e2724756416a9772b4f9dd558d31e873e527959af5618c8fb47a5550ef"
MIXED_ONESTEP_HISTORY_WEIGHT = 1.0  # E24's implicit lambda_h, now explicit
ONESTEP_TRUNCATE_EACH_STEP = True


def mixed_onestep_condition_plan() -> dict:
    """Registered M2n-M4 condition: E24 mixed batch with the history half's backward pass
    truncated to one transition per loss step.

    The single scientific change against the E24 mixed condition (``dd02c4fe…``): the
    incoming ``(h, z)`` of the history half is detached at every loss step
    ``t >= burn_in`` before imagine/observe, whereas the base implementation detaches only
    once at ``t == burn_in``. The objective (``(12*(CE_s+KL_s)+4*(CE_h+KL_h))/16``), rows,
    denominator, per-half normalization, forward pass, teacher/student units, seeds, data,
    bijection streams, budget and evaluation windows are unchanged, and ``history_weight``
    stays E24's 1.0. The design digest is bound to the bytes of the A25 registration file.
    """
    plan = mixed_condition_plan()
    plan["mixed_condition_sha256"] = plan.pop("condition_sha256")
    plan["mixed_protocol"] = plan["protocol"]
    plan["protocol"] = ONESTEP_PROTOCOL
    plan["single_factor"] = (
        "history_half_backward_truncated_to_one_transition_per_loss_step_relative_to_E24_mixed"
    )
    plan["history_weight"] = MIXED_ONESTEP_HISTORY_WEIGHT
    plan["renormalize_after_scaling"] = False
    plan["truncate_each_step"] = ONESTEP_TRUNCATE_EACH_STEP
    plan["design_registration_sha256"] = ONESTEP_DESIGN_REGISTRATION_SHA256
    # The objective string is E24's, unchanged: only the backward graph changes.
    plan["backward"] = {
        "history": "stop_gradient(h,z)_at_every_loss_step_t>=burn_in_before_imagine_observe",
        "base_history": "stop_gradient(h,z)_only_at_t==burn_in",
        "single_edge": "full_backward_through_its_two_frames_unchanged",
        "forward": "bitwise_unchanged_units_and_readouts",
    }
    plan["start"] = {
        "checkpoint": "original_M2d_f33974c9-b86f-4429-9ea9-8ea0e733142a",
        "optimizer": "fresh_AdamW",
        "resume": "none",
    }
    plan["condition_sha256"] = _digest(plan)
    return plan


def onestep_source_schedule_compat(metadata: dict, live_config: dict, identity: dict) -> dict:
    """Allow only the registered active-duty migration for the one-step protocol.

    Same registered difference as weight025 (active duty 0.25 stored on M2d,
    live duty 1.0). The source config is read from ``metadata["config"]``.
    Callers cannot pass a substitute. Every other field must match. This is
    not a general exemption: the recorded protocol is only
    ``m2m_n_mixed_history_onestep_v1``.
    """
    if (
        metadata.get("architecture") != "pilot_shared_symbol_v1"
        or metadata.get("phase") not in {"action_prediction", "action_refinement"}
        or type(metadata.get("optimizer_steps")) is not int
        or metadata["optimizer_steps"] < 1
        or not metadata.get("run_id")
        or metadata.get("dataset_source") != identity
        or not isinstance(metadata.get("config"), dict)
        or not isinstance(live_config, dict)
    ):
        raise ValueError(
            "onestep source architecture, phase, completed updates, dataset or config mismatch"
        )
    source_config = metadata["config"]
    diffs = _config_differences(source_config, live_config)
    allowed = [
        item for item in diffs
        if item["path"] == WEIGHT025_DUTY_PATH
        and item["source"] == WEIGHT025_SOURCE_DUTY
        and item["live"] == WEIGHT025_LIVE_DUTY
        and type(item["source"]) is float
        and type(item["live"]) is float
    ]
    other = [item for item in diffs if item not in allowed]
    if other or len(allowed) != 1:
        shown = [".".join(item["path"]) for item in other] or ["resources.active.training_duty_cycle"]
        raise ValueError("onestep source config mismatch: " + ", ".join(shown))
    encoded = json.dumps(
        source_config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return {
        "protocol": ONESTEP_PROTOCOL,
        "source_config_sha256": hashlib.sha256(encoded).hexdigest(),
        "allowed_difference": {
            "path": "resources.active.training_duty_cycle",
            "source": WEIGHT025_SOURCE_DUTY,
            "live": WEIGHT025_LIVE_DUTY,
        },
    }


def weight0_control_source_schedule_compat(metadata: dict, live_config: dict, identity: dict) -> dict:
    """Allow only the registered active duty migration for weight0 control, and record it."""
    if (
        metadata.get("architecture") != "pilot_shared_symbol_v1"
        or metadata.get("phase") not in {"action_prediction", "action_refinement"}
        or type(metadata.get("optimizer_steps")) is not int
        or metadata["optimizer_steps"] < 1
        or not metadata.get("run_id")
        or metadata.get("dataset_source") != identity
        or not isinstance(metadata.get("config"), dict)
        or not isinstance(live_config, dict)
    ):
        raise ValueError(
            "weight0_control source architecture, phase, completed updates, dataset or config mismatch"
        )
    source_config = metadata["config"]
    diffs = _config_differences(source_config, live_config)
    allowed = [
        item for item in diffs
        if item["path"] == WEIGHT025_DUTY_PATH
        and item["source"] == WEIGHT025_SOURCE_DUTY
        and item["live"] == WEIGHT025_LIVE_DUTY
        and type(item["source"]) is float
        and type(item["live"]) is float
    ]
    other = [item for item in diffs if item not in allowed]
    if other or len(allowed) != 1:
        shown = [".".join(item["path"]) for item in other] or ["resources.active.training_duty_cycle"]
        raise ValueError("weight0_control source config mismatch: " + ", ".join(shown))
    encoded = json.dumps(
        source_config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return {
        "protocol": WEIGHT0_CONTROL_PROTOCOL,
        "source_config_sha256": hashlib.sha256(encoded).hexdigest(),
        "allowed_difference": {
            "path": "resources.active.training_duty_cycle",
            "source": WEIGHT025_SOURCE_DUTY,
            "live": WEIGHT025_LIVE_DUTY,
        },
    }
