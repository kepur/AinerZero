"""M2m-a CPU-only coverage stratification, single-slot substitutions and slot audit.

Nothing in this module runs the student. It defines, before any model work,
which query cells were seen at the same position in the M2l training pool, the
4,096 single-slot substitution inputs, and a CPU audit of the frozen byte
embedding subspace. "Seen" always refers to the visible previous-frame targets
of the 256 pool rows unless a field explicitly says ``input`` (either frame).
Development worlds are only scored; they never select pool rows or variants.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np

from ainerzero.learning.diverse_memory import SAMPLE_COUNT, SAMPLES_PER_WORLD, _validate_pool
from ainerzero.learning.micro_memory import _batch_digest, _digest

SUBSTITUTION_SEED = 7307
SUBSTITUTION_KINDS = ("unseen_at_position", "seen_other_world")
VARIANT_COUNT = len(SUBSTITUTION_KINDS) * SAMPLE_COUNT * 8
NOVEL_BUCKETS = (("0", 0, 0), ("1-2", 1, 2), ("3-5", 3, 5), ("6-8", 6, 8))
QUERY_GROUPS = (
    "selected_train",
    "unselected_train_previous_in_pool",
    "unselected_train_previous_not_in_pool",
    "development",
)
DECISION_RULES = {
    "r1_substituted_accuracy_max": 0.5,
    "r2_other_cell_drop_min": 0.10,
    "identity_ok_substituted_accuracy_min": 0.9,
    "identity_ok_other_cell_drop_max": 0.05,
    "identity_ok_development_same_position_accuracy_max": 0.10,
}
_FRAME_FIELDS = {
    "previous_symbols": ((8,), np.dtype(np.int32)),
    "previous_visible": ((8,), np.dtype(np.bool_)),
    "previous_cursor": ((), np.dtype(np.int32)),
    "current_symbols": ((8,), np.dtype(np.int32)),
    "current_visible": ((8,), np.dtype(np.bool_)),
    "actions": ((), np.dtype(np.int32)),
}


def _validate_frames(frames: Mapping) -> int:
    if not isinstance(frames, Mapping) or set(frames) != set(_FRAME_FIELDS):
        raise ValueError("query frames must contain exactly the public two-frame fields")
    count = None
    for name, (shape, dtype) in _FRAME_FIELDS.items():
        values = frames[name]
        if not isinstance(values, np.ndarray) or values.dtype != dtype:
            raise ValueError(f"{name} must be a numpy array of dtype {dtype}")
        if values.ndim != 1 + len(shape) or values.shape[1:] != shape or values.shape[0] < 1:
            raise ValueError(f"{name} must have shape [N,{','.join(map(str, shape))}]")
        if count is not None and values.shape[0] != count:
            raise ValueError("query frame fields must have the same length")
        count = values.shape[0]
    for prefix in ("previous", "current"):
        symbols, visible = frames[f"{prefix}_symbols"], frames[f"{prefix}_visible"]
        if np.any(symbols < 0) or np.any(symbols > 255):
            raise ValueError("symbols must be bytes")
        if np.any(symbols[~visible] != 0):
            raise ValueError("hidden symbols must be the public zero placeholder")
    return count


def query_frames(episodes_by_partition) -> tuple[dict[str, np.ndarray], dict]:
    """Public previous/current frames for all 2,560 paired queries, in M2k order."""
    from ainerzero.learning.paired_memory import _prepare

    episodes, evidence = _prepare(episodes_by_partition)
    rows = {name: [] for name in _FRAME_FIELDS}
    for episode in episodes:
        for edge in episode.transitions:
            target, current = edge.observation.payload, edge.next_observation.payload
            rows["previous_symbols"].append(list(target.symbols))
            rows["previous_visible"].append(list(target.visible_mask))
            rows["previous_cursor"].append(target.cursor)
            rows["current_symbols"].append(list(current.symbols))
            rows["current_visible"].append(list(current.visible_mask))
            rows["actions"].append(edge.action_request.action)
    frames = {
        name: np.asarray(values, dtype=_FRAME_FIELDS[name][1]) for name, values in rows.items()
    }
    if _validate_frames(frames) != len(evidence["queries"]):
        raise ValueError("query frames must align with the registered query manifest")
    return frames, evidence


def pool_position_symbol_sets(pool: dict[str, np.ndarray]) -> dict:
    """Bytes seen per position as visible previous-frame targets and as any input."""
    _validate_pool(pool)
    symbols, visible = pool["symbols"], pool["visible_mask"]
    target = [sorted({int(s) for s in symbols[:, 0, p][visible[:, 0, p]]}) for p in range(8)]
    inputs = [
        sorted({int(s) for frame in (0, 1) for s in symbols[:, frame, p][visible[:, frame, p]]})
        for p in range(8)
    ]
    return {
        "definition": "visible_previous_frame_targets_of_the_256_pool_rows",
        "target_by_position": target,
        "input_by_position": inputs,
        "target_global": sorted(set().union(*map(set, target))),
        "input_global": sorted(set().union(*map(set, inputs))),
        "target_unique_by_position": [len(values) for values in target],
        "input_unique_by_position": [len(values) for values in inputs],
    }


def query_labels(queries: Sequence[Mapping], training_evidence: Mapping) -> list[str]:
    """Group label of every query from hash-verified pool identities only."""
    samples = training_evidence.get("samples")
    if not isinstance(samples, list) or len(samples) != SAMPLE_COUNT:
        raise ValueError("coverage labels require the 256-row M2l pool evidence")
    if _digest(samples) != training_evidence.get("sample_manifest_sha256"):
        raise ValueError("training sample manifest digest mismatch")
    selected = {(row["episode_id"], row["query_tick"]) for row in samples}
    previous = {row["previous_input_sha256"] for row in samples}
    labels = []
    for query in queries:
        if query["partition"] == "development":
            labels.append("development")
        elif (query["episode_id"], query["query_tick"]) in selected:
            labels.append("selected_train")
        elif query["previous_input_sha256"] in previous:
            labels.append("unselected_train_previous_in_pool")
        else:
            labels.append("unselected_train_previous_not_in_pool")
    if Counter(labels)["selected_train"] != SAMPLE_COUNT:
        raise ValueError("every pool row must label exactly one registered query")
    return labels


def classify_query_cells(frames: Mapping, symbol_sets: Mapping) -> dict:
    """Per-cell coverage flags; no prediction or score is read."""
    count = _validate_frames(frames)
    previous, visible = frames["previous_symbols"], frames["previous_visible"]
    target = [set(values) for values in symbol_sets["target_by_position"]]
    if len(target) != 8:
        raise ValueError("symbol sets must cover eight positions")
    global_set = np.zeros(256, dtype=bool)
    global_set[list(symbol_sets["target_global"])] = True
    table = np.zeros((8, 256), dtype=bool)
    for position, values in enumerate(target):
        table[position, list(values)] = True
    same = visible & table[np.arange(8)[None, :], previous]
    seen = visible & global_set[previous]
    changed = visible & frames["current_visible"] & (previous != frames["current_symbols"])
    novel = (visible & ~same).sum(axis=1).astype(np.int32)
    result = {
        "query_count": count,
        "visible": visible.copy(),
        "changed": changed,
        "global_seen": seen,
        "same_position_seen": same,
        "frame_novel_count": novel,
    }
    result["classification_sha256"] = _digest(
        {
            name: result[name].tolist()
            for name in (
                "visible",
                "changed",
                "global_seen",
                "same_position_seen",
                "frame_novel_count",
            )
        }
    )
    return result


def _bucket(novel: np.ndarray, low: int, high: int) -> np.ndarray:
    return (novel >= low) & (novel <= high)


def _cell_stats(mask, correct, nll, changed) -> dict:
    count = int(mask.sum())
    changed_mask = mask & changed
    changed_count = int(changed_mask.sum())
    hits = int((mask & correct).sum())
    changed_hits = int((changed_mask & correct).sum())
    return {
        "count": count,
        "correct": hits,
        "accuracy": hits / count if count else None,
        "nll": float(nll[mask].mean()) if count else None,
        "changed_count": changed_count,
        "changed_correct": changed_hits,
        "changed_accuracy": changed_hits / changed_count if changed_count else None,
    }


def summarize_cell_scores(classification: Mapping, correct, nll, labels: Sequence[str]) -> dict:
    """Accuracy/NLL by group and by coverage stratum, from per-cell scores."""
    visible = classification["visible"]
    correct, nll = np.asarray(correct, dtype=bool), np.asarray(nll, dtype=np.float64)
    labels = np.asarray(labels)
    if correct.shape != visible.shape or nll.shape != visible.shape or len(labels) != len(visible):
        raise ValueError("cell scores must align with classified query cells")
    if not np.isfinite(nll[visible]).all() or np.any(nll[visible] < 0):
        raise ValueError("visible cell NLL must be finite and nonnegative")
    changed = classification["changed"]
    same, seen = classification["same_position_seen"], classification["global_seen"]
    novel = classification["frame_novel_count"][:, None] * np.ones((1, 8), dtype=np.int32)
    result = {}
    for group in ("all", *QUERY_GROUPS):
        rows = np.ones(len(labels), dtype=bool) if group == "all" else labels == group
        base = visible & rows[:, None]

        def stats(mask, base=base):
            return _cell_stats(base & mask, correct, nll, changed)

        result[group] = {
            "query_count": int(rows.sum()),
            "all": stats(np.ones_like(visible)),
            "same_position_seen": {
                str(flag).lower(): stats(same == flag) for flag in (True, False)
            },
            "global_seen": {str(flag).lower(): stats(seen == flag) for flag in (True, False)},
            "frame_novel_count": {
                name: stats(_bucket(novel, low, high)) for name, low, high in NOVEL_BUCKETS
            },
            "same_position_seen_by_frame_novel_count": {
                str(flag).lower(): {
                    name: stats((same == flag) & _bucket(novel, low, high))
                    for name, low, high in NOVEL_BUCKETS
                }
                for flag in (True, False)
            },
        }
    return result


def build_substitution_variants(
    pool: dict[str, np.ndarray], samples: Sequence[Mapping], *, seed: int = SUBSTITUTION_SEED
) -> tuple[dict[str, np.ndarray], dict]:
    """Return 2 kinds x 256 rows x 8 positions single-slot substitutions.

    The previous-frame cell is replaced; the current-frame cell is replaced too
    only when it was visible and unchanged, so every changed/unchanged mask is
    preserved. Candidates exclude any byte visible in either frame of the row.
    ``unseen_at_position`` bytes never occur at that position in either frame of
    any pool row. ``seen_other_world`` bytes are previous-frame pool targets at
    that position in another world and never occur at that position in the
    row's own world. One ``default_rng(seed)`` draw per variant, in order kind,
    row, position, picks uniformly from the sorted candidate list.
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    _validate_pool(pool)
    if not isinstance(samples, Sequence) or len(samples) != SAMPLE_COUNT:
        raise ValueError("substitutions require the 256 pool sample identities")
    worlds = []
    for row, sample in enumerate(samples):
        if (
            not isinstance(sample, Mapping)
            or sample.get("row") != row
            or sample.get("world_index") != row // SAMPLES_PER_WORLD
        ):
            raise ValueError("pool identities must be world-major rows of 16")
        worlds.append(row // SAMPLES_PER_WORLD)
    symbols, visible = pool["symbols"], pool["visible_mask"]
    if not visible[:, 0].all():
        raise ValueError("single-slot substitution requires every previous-frame cell visible")
    sets = pool_position_symbol_sets(pool)
    unseen_excluded = [set(values) for values in sets["input_by_position"]]
    world_count = SAMPLE_COUNT // SAMPLES_PER_WORLD
    own = [[set() for _ in range(8)] for _ in range(world_count)]
    targets = [[set() for _ in range(8)] for _ in range(world_count)]
    for row in range(SAMPLE_COUNT):
        for position in range(8):
            for frame in (0, 1):
                if visible[row, frame, position]:
                    own[worlds[row]][position].add(int(symbols[row, frame, position]))
            targets[worlds[row]][position].add(int(symbols[row, 0, position]))
    rng = np.random.default_rng(seed)
    variants = []
    arrays = {name: [] for name in pool}
    for kind in SUBSTITUTION_KINDS:
        for row in range(SAMPLE_COUNT):
            world = worlds[row]
            frame_bytes = {
                int(s) for frame in (0, 1) for s in symbols[row, frame][visible[row, frame]]
            }
            for position in range(8):
                if kind == "unseen_at_position":
                    candidates = [
                        b
                        for b in range(256)
                        if b not in unseen_excluded[position] and b not in frame_bytes
                    ]
                else:
                    others = set().union(
                        *(targets[w][position] for w in range(world_count) if w != world)
                    )
                    candidates = sorted(others - own[world][position] - frame_bytes)
                if not candidates:
                    raise ValueError(f"no {kind} substitution candidate for row {row} p{position}")
                replacement = int(candidates[int(rng.integers(len(candidates)))])
                original = int(symbols[row, 0, position])
                current_visible = bool(visible[row, 1, position])
                unchanged = current_visible and int(symbols[row, 1, position]) == original
                variant_symbols = symbols[row].copy()
                variant_symbols[0, position] = replacement
                if unchanged:
                    variant_symbols[1, position] = replacement
                arrays["symbols"].append(variant_symbols)
                for name in ("visible_mask", "cursor", "episode_start", "actions"):
                    arrays[name].append(pool[name][row].copy())
                variants.append(
                    {
                        "variant": len(variants),
                        "kind": kind,
                        "row": row,
                        "world_index": world,
                        "position": position,
                        "original_symbol": original,
                        "replacement_symbol": replacement,
                        "candidate_count": len(candidates),
                        "current_replaced": unchanged,
                        "substituted_cell_changed": current_visible and not unchanged,
                    }
                )
    batch = {name: np.stack(values) for name, values in arrays.items()}
    _check_variants(pool, batch, variants, unseen_excluded, own, targets)
    return batch, {
        "schema_version": 1,
        "scope": "single_slot_substitution_of_m2l_pool_inputs_no_new_environment_steps",
        "seed": seed,
        "kinds": list(SUBSTITUTION_KINDS),
        "variant_count": len(variants),
        "order": ["kind", "pool_row", "position"],
        "previous_frame": "replace_one_visible_cell",
        "current_frame": "replace_same_cell_only_if_visible_and_unchanged",
        "exclusions": "bytes_visible_in_either_frame_of_the_row",
        "unseen_at_position": "never_visible_at_that_position_in_either_frame_of_any_pool_row",
        "seen_other_world": (
            "previous_frame_target_at_that_position_in_another_world_and_never_visible_"
            "at_that_position_in_the_row_world"
        ),
        "draw": "default_rng(seed).integers(len(sorted_candidates)) per variant",
        "variant_manifest_sha256": _digest(variants),
        "batch_sha256": _batch_digest(batch),
        "variants": variants,
    }


def _check_variants(pool, batch, variants, unseen_excluded, own, targets):
    if len(variants) != VARIANT_COUNT:
        raise ValueError("substitution must produce exactly 4096 variants")
    pool_changed = pool["visible_mask"][:, 0] & pool["visible_mask"][:, 1]
    pool_changed &= pool["symbols"][:, 0] != pool["symbols"][:, 1]
    for index, variant in enumerate(variants):
        row, position = variant["row"], variant["position"]
        symbols = batch["symbols"][index]
        replacement = variant["replacement_symbol"]
        differs = symbols[0] != pool["symbols"][row, 0]
        if differs.sum() != 1 or not differs[position] or symbols[0, position] != replacement:
            raise ValueError("variant must change exactly the declared previous-frame cell")
        changed = batch["visible_mask"][index, 0] & batch["visible_mask"][index, 1]
        changed &= symbols[0] != symbols[1]
        if not np.array_equal(changed, pool_changed[row]):
            raise ValueError("substitution must preserve the changed-cell mask")
        row_bytes = {
            int(s)
            for frame in (0, 1)
            for s in pool["symbols"][row, frame][pool["visible_mask"][row, frame]]
        }
        if replacement in row_bytes:
            raise ValueError("replacement byte must not already occur in the row")
        if variant["kind"] == "unseen_at_position":
            if replacement in unseen_excluded[position]:
                raise ValueError("unseen replacement occurs at that pool position")
        elif replacement in own[variant["world_index"]][position] or not any(
            replacement in targets[w][position]
            for w in range(len(targets))
            if w != variant["world_index"]
        ):
            raise ValueError("other-world replacement must come only from another world")
    for name in ("visible_mask", "cursor", "episode_start", "actions"):
        rows = [variant["row"] for variant in variants]
        if not np.array_equal(batch[name], pool[name][rows]):
            raise ValueError("substitution may only change symbols")


def summarize_substitutions(
    evidence: Mapping,
    variant_argmax,
    variant_nll,
    baseline_argmax,
    pool_previous_symbols,
    pool_changed,
) -> dict:
    """Score substituted cells and the seven untouched cells against the baseline.

    ``baseline_argmax`` are the zero-context predictions for the same 256 pool
    queries, same keys and particles (A1). Other-cell drop is baseline minus
    variant accuracy over identical cells, pooled over all variants of a kind.
    """
    variants = evidence["variants"]
    variant_argmax = np.asarray(variant_argmax)
    variant_nll = np.asarray(variant_nll, dtype=np.float64)
    baseline_argmax = np.asarray(baseline_argmax)
    previous = np.asarray(pool_previous_symbols)
    pool_changed = np.asarray(pool_changed, dtype=bool)
    if (
        variant_argmax.shape != (len(variants), 8)
        or variant_nll.shape != (len(variants), 8)
        or baseline_argmax.shape != (SAMPLE_COUNT, 8)
        or previous.shape != (SAMPLE_COUNT, 8)
        or pool_changed.shape != (SAMPLE_COUNT, 8)
        or not np.isfinite(variant_nll).all()
    ):
        raise ValueError("substitution scores must align with the variant manifest")
    baseline_correct = baseline_argmax == previous
    result = {}
    for kind in SUBSTITUTION_KINDS:
        indices = [i for i, v in enumerate(variants) if v["kind"] == kind]
        totals = Counter()
        positions = {p: Counter() for p in range(8)}
        affected_variants = 0
        for index in indices:
            variant = variants[index]
            row, position = variant["row"], variant["position"]
            predicted = variant_argmax[index]
            hit = int(predicted[position] == variant["replacement_symbol"])
            others = np.arange(8) != position
            target = previous[row]
            variant_correct = (predicted == target) & others
            base_correct = baseline_correct[row] & others
            flips = (predicted != baseline_argmax[row]) & others
            newly_wrong = base_correct & ~variant_correct
            other_changed = pool_changed[row] & others
            values = {
                "substituted": 1,
                "substituted_correct": hit,
                "substituted_nll": float(variant_nll[index, position]),
                "substituted_changed": int(variant["substituted_cell_changed"]),
                "substituted_changed_correct": hit * int(variant["substituted_cell_changed"]),
                "other": int(others.sum()),
                "other_correct": int(variant_correct.sum()),
                "other_baseline_correct": int(base_correct.sum()),
                "other_prediction_flips": int(flips.sum()),
                "other_newly_wrong": int(newly_wrong.sum()),
                "other_newly_correct": int((variant_correct & ~base_correct).sum()),
                "other_nll": float(variant_nll[index][others].sum()),
                "other_changed": int(other_changed.sum()),
                "other_changed_correct": int((variant_correct & other_changed).sum()),
                "other_changed_baseline_correct": int((base_correct & other_changed).sum()),
            }
            affected_variants += int(newly_wrong.any())
            totals.update(values)
            positions[position].update(values)
        result[kind] = {
            **_substitution_rates(totals),
            "variants_with_any_newly_wrong_other_cell": affected_variants,
            "by_position": {str(p): _substitution_rates(c) for p, c in positions.items()},
        }
    return result


def _substitution_rates(c: Counter) -> dict:
    def ratio(a, b):
        return c[a] / c[b] if c[b] else None

    other_accuracy = ratio("other_correct", "other")
    other_baseline = ratio("other_baseline_correct", "other")
    changed_accuracy = ratio("other_changed_correct", "other_changed")
    changed_baseline = ratio("other_changed_baseline_correct", "other_changed")
    return {
        "variant_count": c["substituted"],
        "substituted_correct": c["substituted_correct"],
        "substituted_accuracy": ratio("substituted_correct", "substituted"),
        "substituted_nll": c["substituted_nll"] / c["substituted"] if c["substituted"] else None,
        "substituted_changed_count": c["substituted_changed"],
        "substituted_changed_accuracy": ratio("substituted_changed_correct", "substituted_changed"),
        "other_cell_count": c["other"],
        "other_correct": c["other_correct"],
        "other_accuracy": other_accuracy,
        "other_baseline_accuracy": other_baseline,
        "other_accuracy_drop": None if other_accuracy is None else other_baseline - other_accuracy,
        "other_nll": c["other_nll"] / c["other"] if c["other"] else None,
        "other_prediction_flips": c["other_prediction_flips"],
        "other_newly_wrong": c["other_newly_wrong"],
        "other_newly_correct": c["other_newly_correct"],
        "other_changed_count": c["other_changed"],
        "other_changed_accuracy": changed_accuracy,
        "other_changed_baseline_accuracy": changed_baseline,
        "other_changed_accuracy_drop": None
        if changed_accuracy is None
        else changed_baseline - changed_accuracy,
    }


def coverage_decision(substitutions: Mapping, development_same_position_accuracy) -> dict:
    """Apply the preregistered M2m-a reading; never authorizes promotion."""
    rules = DECISION_RULES
    unseen = substitutions["unseen_at_position"]
    accuracy, drop = unseen["substituted_accuracy"], unseen["other_accuracy_drop"]
    dev = development_same_position_accuracy
    if any(type(v) not in (int, float) or not np.isfinite(v) for v in (accuracy, drop, dev)):
        raise ValueError("decision inputs must be finite measured rates")
    r1 = accuracy <= rules["r1_substituted_accuracy_max"]
    r2 = drop >= rules["r2_other_cell_drop_min"]
    identity_ok = (
        accuracy >= rules["identity_ok_substituted_accuracy_min"]
        and drop < rules["identity_ok_other_cell_drop_max"]
        and dev <= rules["identity_ok_development_same_position_accuracy_max"]
    )
    if r1 or r2:
        outcome, next_step = (
            "supports_coverage_or_cross_slot_interference",
            "stage_b_consistent_symbol_permutation_may_be_registered_by_user",
        )
    elif identity_ok:
        outcome, next_step = (
            "symbol_identity_not_the_bottleneck",
            "do_not_run_stage_b_diagnose_latent_or_gate_h6",
        )
    else:
        outcome, next_step = "intermediate", "record_and_let_user_decide"
    return {
        "rules": dict(rules),
        "unseen_substituted_accuracy": accuracy,
        "unseen_other_cell_accuracy_drop": drop,
        "development_same_position_seen_accuracy": dev,
        "r1_substituted_cell_fails": r1,
        "r2_cross_slot_interference": r2,
        "identity_not_bottleneck_branch": identity_ok,
        "cross_slot_interference_confirmed": r2,
        "outcome": outcome,
        "next_step": next_step,
        "promotion": False,
        "automatic_stage_b": False,
    }


def _slot_vectors(embedding: np.ndarray, symbols: np.ndarray, visible: np.ndarray) -> np.ndarray:
    masked = np.where(visible, symbols, 0)
    return (embedding[masked] * visible[..., None]).reshape(len(symbols), 128)


def slot_subspace_audit(
    byte_embedding, pool: dict[str, np.ndarray], frames: Mapping, labels: Sequence[str]
) -> dict:
    """SVD rank of pool h[:128] and the share of query vectors outside that span.

    h[:128] after observing a frame is exactly the frozen byte embedding of its
    visible symbols (hidden cells zero); cursor and mask do not enter it.
    """
    embedding = np.asarray(byte_embedding, dtype=np.float64)
    if embedding.shape != (256, 16) or not np.isfinite(embedding).all():
        raise ValueError("byte embedding must be a finite [256,16] matrix")
    _validate_pool(pool)
    _validate_frames(frames)
    labels = np.asarray(labels)
    if len(labels) != len(frames["previous_symbols"]):
        raise ValueError("labels must align with query frames")
    pool_vectors = _slot_vectors(embedding, pool["symbols"][:, 0], pool["visible_mask"][:, 0])
    _, singular, vt = np.linalg.svd(pool_vectors, full_matrices=False)
    tolerance = singular.max() * max(pool_vectors.shape) * np.finfo(np.float64).eps
    rank = int((singular > tolerance).sum())
    basis = vt[:rank]
    distinct = np.unique(
        np.concatenate([pool["symbols"][:, 0], pool["visible_mask"][:, 0]], axis=1), axis=0
    )
    query_vectors = _slot_vectors(embedding, frames["previous_symbols"], frames["previous_visible"])
    residual = query_vectors - (query_vectors @ basis.T) @ basis
    norms = np.linalg.norm(query_vectors, axis=1)
    ratios = np.divide(
        np.linalg.norm(residual, axis=1), norms, out=np.zeros_like(norms), where=norms > 0
    )
    groups = {}
    for group in QUERY_GROUPS:
        values = ratios[labels == group]
        groups[group] = {
            "query_count": int(len(values)),
            "outside_norm_fraction_mean": float(values.mean()) if len(values) else None,
            "outside_norm_fraction_median": float(np.median(values)) if len(values) else None,
            "outside_norm_fraction_max": float(values.max()) if len(values) else None,
            "queries_outside_above_0_1": int((values > 0.1).sum()),
            "queries_outside_above_1e_6": int((values > 1e-6).sum()),
        }
    per_slot_rank = []
    for position in range(8):
        seen = sorted(
            {int(s) for s in pool["symbols"][:, 0, position][pool["visible_mask"][:, 0, position]]}
        )
        per_slot_rank.append(int(np.linalg.matrix_rank(embedding[seen])) if seen else 0)
    pool_cursor = Counter(int(c) for c in pool["cursor"][:, 0])
    pool_action = Counter(int(a) for a in pool["actions"][:, 0])
    pool_pairs = {(int(c), int(a)) for c, a in zip(pool["cursor"][:, 0], pool["actions"][:, 0])}
    coverage = {}
    for group in QUERY_GROUPS:
        rows = labels == group
        cursors = frames["previous_cursor"][rows]
        actions = frames["actions"][rows]
        coverage[group] = {
            "query_count": int(rows.sum()),
            "cursor_counts": {str(k): int((cursors == k).sum()) for k in range(8)},
            "action_counts": {str(k): int((actions == k).sum()) for k in range(4)},
            "cursor_in_pool": int(sum(int(c) in pool_cursor for c in cursors)),
            "action_in_pool": int(sum(int(a) in pool_action for a in actions)),
            "cursor_action_pair_in_pool": int(
                sum((int(c), int(a)) in pool_pairs for c, a in zip(cursors, actions))
            ),
        }
    return {
        "scope": "cpu_only_frozen_byte_embedding_previous_frame_slots",
        "pool_rows": SAMPLE_COUNT,
        "pool_distinct_symbol_visibility_frames": int(len(distinct)),
        "pool_slot_rank": rank,
        "rank_tolerance": float(tolerance),
        "pool_singular_values": [float(v) for v in singular],
        "embedding_rank": int(np.linalg.matrix_rank(embedding)),
        "per_position_seen_byte_embedding_rank": per_slot_rank,
        "groups": groups,
        "pool_cursor_counts": {str(k): pool_cursor.get(k, 0) for k in range(8)},
        "pool_action_counts": {str(k): pool_action.get(k, 0) for k in range(4)},
        "pool_cursor_action_pairs": len(pool_pairs),
        "cursor_action_coverage": coverage,
    }
