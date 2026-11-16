"""M2m: consistent per-sample byte relabeling of the fixed M2l pool (CPU only).

The only training change relative to M2l is that each scheduled pool row is
relabeled by one independent 256-byte bijection, applied to both frames and all
visible cells through the existing ``permute_symbols``. Hidden cells stay zero,
cursor and actions are unchanged. Nothing here reads model scores to choose
inputs; transfer levels and the next-step table are fixed before the run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from ainerzero.data.augmentation import permute_symbols
from ainerzero.learning.coverage_diagnostic import QUERY_GROUPS, _cell_stats, summarize_cell_scores
from ainerzero.learning.diverse_memory import (
    BATCH_SIZE,
    SAMPLE_COUNT,
    UPDATE_COUNT,
    _validate_pool,
)
from ainerzero.learning.micro_memory import _batch_digest, _digest

RELABEL_TRAINING_SEED = 2307
RELABEL_EVALUATION_SEED = 9103
TRAINING_PERMUTATION_COUNT = UPDATE_COUNT * BATCH_SIZE
TRANSFER_LEVELS = {
    "not_transferred_below": 0.10,
    "transferred_min": 0.80,
    "transferred_changed_min": 0.50,
}
ACTION_NLL_INCREASE_MAX = {"1": 0.05, "4": 0.15}
BRANCHES = ("zero_context_tail", "history_tail")
NEXT_STEPS = {
    "underfit": "do_not_extend_in_place_register_one_longer_budget_candidate_user_decides",
    "coverage_main_cause": "register_m2n_nonzero_history_one_step_training_on_this_candidate",
    "relabel_invariance_but_development_differs": "zero_update_z_or_gate_diagnosis_no_scaling",
    "partial_transfer": "zero_update_cross_slot_jacobian_audit_then_consider_per_slot_tail",
    "coverage_hypothesis_rejected": "stop_relabel_direction_return_to_stage_a_h6_branch",
    "unregistered_combination": "record_results_user_decides",
}


def permutation_sha256(permutation) -> str:
    values = [int(value) for value in np.asarray(permutation).ravel()]
    if sorted(values) != list(range(256)):
        raise ValueError("permutation must be a bijection of 0..255")
    return _digest(values)


def _seed(seed) -> int:
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    return seed


def training_permutation_manifest(seed: int = RELABEL_TRAINING_SEED) -> dict:
    """Replay the 3,200 bijections ``permute_symbols`` will draw, update-major."""
    rng = np.random.default_rng(_seed(seed))
    digests = [permutation_sha256(rng.permutation(256)) for _ in range(TRAINING_PERMUTATION_COUNT)]
    return {
        "seed": seed,
        "count": TRAINING_PERMUTATION_COUNT,
        "order": "zero_based_update_major_then_scheduled_batch_row",
        "draw": "numpy_default_rng(seed).permutation(256)_per_sample_inside_permute_symbols",
        "unique_count": len(set(digests)),
        "digests": digests,
        "manifest_sha256": _digest(digests),
    }


def _replayed(rng: np.random.Generator, count: int) -> list[np.ndarray]:
    probe = np.random.default_rng()
    probe.bit_generator.state = rng.bit_generator.state
    return [probe.permutation(256) for _ in range(count)], probe.bit_generator.state


def relabel_batch(batch: Mapping, rng: np.random.Generator) -> tuple[dict, list[str]]:
    """Apply ``permute_symbols`` and independently confirm what it did."""
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    if not isinstance(batch, dict):
        raise TypeError("batch must be a dictionary of numpy arrays")
    symbols, visible = batch.get("symbols"), batch.get("visible_mask")
    if not isinstance(symbols, np.ndarray) or symbols.ndim != 3 or symbols.shape[1:] != (2, 8):
        raise ValueError("relabeling requires two-frame [B,2,8] pool rows")
    expected, state = _replayed(rng, len(symbols))
    result = permute_symbols(batch, rng)
    if rng.bit_generator.state != state:
        raise RuntimeError("permute_symbols consumed an unexpected number of draws")
    if set(result) != set(batch) or result["symbols"].dtype != np.int32:
        raise RuntimeError("relabeled batch fields or symbol dtype changed")
    for name, values in batch.items():
        if name != "symbols" and (
            result[name].dtype != values.dtype or not np.array_equal(result[name], values)
        ):
            raise RuntimeError("relabeling may only change symbols")
    for index, permutation in enumerate(expected):
        mask = visible[index]
        if not np.array_equal(
            result["symbols"][index][mask], permutation[symbols[index][mask]]
        ) or np.any(result["symbols"][index][~mask] != 0):
            raise RuntimeError("relabeled symbols differ from the replayed bijection")
    return result, [permutation_sha256(permutation) for permutation in expected]


def _changed(batch) -> np.ndarray:
    symbols, visible = batch["symbols"], batch["visible_mask"]
    return visible[:, 0] & visible[:, 1] & (symbols[:, 0] != symbols[:, 1])


def relabel_evaluation_pool(
    pool: dict[str, np.ndarray],
    training_manifest: Mapping,
    seed: int = RELABEL_EVALUATION_SEED,
) -> tuple[dict, dict]:
    """The 256 pool rows under 256 fresh bijections disjoint from training ones."""
    _validate_pool(pool)
    if (
        not isinstance(training_manifest, Mapping)
        or training_manifest.get("count") != TRAINING_PERMUTATION_COUNT
        or len(training_manifest.get("digests", [])) != TRAINING_PERMUTATION_COUNT
        or _digest(training_manifest["digests"]) != training_manifest.get("manifest_sha256")
    ):
        raise ValueError("relabel evaluation requires the registered training manifest")
    rng = np.random.default_rng(_seed(seed))
    batch, digests = relabel_batch(pool, rng)
    overlap = set(digests) & set(training_manifest["digests"])
    if overlap or len(set(digests)) != SAMPLE_COUNT:
        raise ValueError("evaluation bijections must be distinct and unseen in training")
    if not np.array_equal(_changed(batch), _changed(pool)):
        raise RuntimeError("bijection must preserve changed cells")
    return batch, {
        "schema_version": 1,
        "scope": "m2l_pool_rows_under_unseen_consistent_bijections_zero_context",
        "seed": seed,
        "rows": SAMPLE_COUNT,
        "digests": digests,
        "manifest_sha256": _digest(digests),
        "training_overlap": 0,
        "batch_sha256": _batch_digest(batch),
        "visible_targets": int(batch["visible_mask"][:, 0].sum()),
        "changed_targets": int(_changed(batch).sum()),
        "keys": "paired_query_keys_of_each_pool_row_seed_7103",
    }


def summarize_relabel_pool(argmax, nll, batch) -> dict:
    """Per-cell accuracy/NLL of explicit two-frame inputs against their own previous frame."""
    argmax, nll = np.asarray(argmax), np.asarray(nll, dtype=np.float64)
    targets, visible = batch["symbols"][:, 0], batch["visible_mask"][:, 0]
    if argmax.shape != targets.shape or nll.shape != targets.shape:
        raise ValueError("relabel scores must align with the evaluated pool")
    if not np.isfinite(nll[visible]).all() or np.any(nll[visible] < 0):
        raise ValueError("visible relabel NLL must be finite and nonnegative")
    correct, changed = argmax == targets, _changed(batch)
    result = _cell_stats(visible, correct, nll, changed)
    result["by_position"] = [
        _cell_stats(visible & (np.arange(8) == position)[None, :], correct, nll, changed)
        for position in range(8)
    ]
    return result


def _cell_arrays(cells: Sequence[Mapping], branch: str, shape) -> tuple[np.ndarray, np.ndarray]:
    if len(cells) != shape[0]:
        raise ValueError("cell outputs must cover every registered query")
    argmax = np.asarray([row[branch]["argmax"] for row in cells], dtype=np.int64)
    nll = np.asarray(
        [[np.nan if value is None else value for value in row[branch]["nll"]] for row in cells],
        dtype=np.float64,
    )
    if argmax.shape != tuple(shape) or nll.shape != tuple(shape):
        raise ValueError("cell outputs must have eight cells per query")
    return argmax, nll


def _difference(current, reference):
    if isinstance(current, Mapping):
        if "accuracy" in current and "count" in current:
            if current["count"] != reference["count"]:
                raise ValueError("compared strata must contain identical cells")
            a, b = current["accuracy"], reference["accuracy"]
            ca, cb = current["changed_accuracy"], reference["changed_accuracy"]
            return {
                "count": current["count"],
                "accuracy": None if a is None or b is None else a - b,
                "changed_accuracy": None if ca is None or cb is None else ca - cb,
                "nll": None
                if current["nll"] is None or reference["nll"] is None
                else current["nll"] - reference["nll"],
            }
        return {key: _difference(value, reference[key]) for key, value in current.items()}
    if current != reference:
        raise ValueError("compared summaries must have identical structure")
    return current


def compare_strata(
    classification: Mapping,
    labels: Sequence[str],
    targets,
    current_cells: Sequence[Mapping],
    reference_cells: Sequence[Mapping],
) -> dict:
    """Seen-at-position x frame-novel-count accuracy, both branches, M2m minus M2l."""
    targets = np.asarray(targets)
    result = {
        "schema_version": 1,
        "coverage_reference": "visible_previous_frame_targets_of_m2l_256_pool_rows_unpermuted",
        "groups": ["all", *QUERY_GROUPS],
        "branches": {},
    }
    for branch in BRANCHES:
        summaries = {}
        for name, cells in (("m2m", current_cells), ("m2l", reference_cells)):
            argmax, nll = _cell_arrays(cells, branch, targets.shape)
            summaries[name] = summarize_cell_scores(classification, argmax == targets, nll, labels)
        summaries["m2m_minus_m2l"] = _difference(summaries["m2m"], summaries["m2l"])
        result["branches"][branch] = summaries
    return result


def transfer_level(stats: Mapping) -> str:
    accuracy, changed = stats.get("accuracy"), stats.get("changed_accuracy")
    if type(accuracy) not in (int, float) or not np.isfinite(accuracy) or not 0 <= accuracy <= 1:
        raise ValueError("transfer level requires a measured accuracy")
    if accuracy < TRANSFER_LEVELS["not_transferred_below"]:
        return "not_transferred"
    if (
        accuracy >= TRANSFER_LEVELS["transferred_min"]
        and type(changed) in (int, float)
        and changed >= TRANSFER_LEVELS["transferred_changed_min"]
    ):
        return "transferred"
    return "partial"


def regression_flags(before: Mapping, after: Mapping) -> dict:
    """Reconstruction 544/544 gate and action accuracy/NLL limits; flags only."""
    reconstruction = after["reconstruction"]
    checks = {
        "reconstruction_gate_passed": reconstruction["gate"]["status"] == "passed",
        "reconstruction_all_correct": reconstruction["model"]["accuracy"] == 1.0
        and reconstruction["model"]["count"] == before["reconstruction"]["model"]["count"],
    }
    action = {}
    for horizon, limit in ACTION_NLL_INCREASE_MAX.items():
        old = before["action"]["horizons"][horizon]["model"]
        new = after["action"]["horizons"][horizon]["model"]
        action[horizon] = {
            "before_accuracy": old["accuracy"],
            "after_accuracy": new["accuracy"],
            "before_nll": old["nll"],
            "after_nll": new["nll"],
            "nll_increase": new["nll"] - old["nll"],
            "nll_increase_max": limit,
        }
        checks[f"action_{horizon}_accuracy_not_lower"] = new["accuracy"] >= old["accuracy"]
        checks[f"action_{horizon}_nll_increase_within_limit"] = new["nll"] - old["nll"] <= limit
    return {
        "checks": checks,
        "action": action,
        "reconstruction_count": reconstruction["model"]["count"],
        "regression": not all(checks.values()),
        "memory_progress_offsets_regression": False,
    }


def next_step(local_screens_passed: bool, development: str, relabel_pool: str, regression: bool):
    """Fixed reading table of the M2m proposal; no promotion is ever authorized."""
    if type(local_screens_passed) is not bool or type(regression) is not bool:
        raise ValueError("screen and regression flags must be Booleans")
    levels = {"not_transferred", "partial", "transferred"}
    if development not in levels or relabel_pool not in levels:
        raise ValueError("unknown transfer level")
    if not local_screens_passed:
        outcome = "underfit"
    elif development == relabel_pool == "transferred":
        outcome = "coverage_main_cause"
    elif relabel_pool == "transferred" and development == "not_transferred":
        outcome = "relabel_invariance_but_development_differs"
    elif development == relabel_pool == "not_transferred":
        outcome = "coverage_hypothesis_rejected"
    elif development == relabel_pool == "partial":
        outcome = "partial_transfer"
    else:
        outcome = "unregistered_combination"
    return {
        "local_screens_passed": local_screens_passed,
        "development_zero_context_level": development,
        "relabel_pool_level": relabel_pool,
        "outcome": outcome,
        "next_step": NEXT_STEPS[outcome],
        "regression_reported": regression,
        "regression_next_step": "report_and_register_action_preserving_constraint_before_next_candidate"
        if regression
        else None,
        "promotion": False,
        "automatic_next_run": False,
    }
