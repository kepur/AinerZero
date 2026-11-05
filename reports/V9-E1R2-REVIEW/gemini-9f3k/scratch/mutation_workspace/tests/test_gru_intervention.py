import importlib
import json
import sys

import numpy as np
import pytest

from ainerzero.learning.gru_intervention import (
    FRONT_ROW_RANGES,
    GRU_PARAMETER_COUNT,
    GRU_SHAPES,
    MODEL_PARAMETER_COUNT,
    action_nll_recovery,
    build_front_reverted_variants,
)


def paired_arrays(dtype=np.float32):
    # Synthetic CPU arrays with the fixed GRU shapes; no student is constructed.
    source = {
        key: np.full(shape, index + 1, dtype=dtype)
        for index, (key, shape) in enumerate(GRU_SHAPES.items())
    }
    source["model.frozen_fixture"] = np.zeros(
        MODEL_PARAMETER_COUNT - GRU_PARAMETER_COUNT, dtype=dtype
    )
    candidate = {key: value.copy() for key, value in source.items()}
    for key in GRU_SHAPES:
        candidate[key] += 0.5
    return source, candidate


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_only_front_output_rows_restored_with_exact_evidence(dtype):
    source, candidate = paired_arrays(dtype)
    variants, evidence = build_front_reverted_variants(source, candidate)
    assert set(variants) == {"source", "candidate", "front_reverted"}
    hybrid = variants["front_reverted"]
    for key in source:
        np.testing.assert_array_equal(source[key], variants["source"][key])
        np.testing.assert_array_equal(candidate[key], variants["candidate"][key])
        assert hybrid[key].dtype == source[key].dtype
        assert hybrid[key].shape == source[key].shape
        if key not in GRU_SHAPES:
            np.testing.assert_array_equal(hybrid[key], candidate[key])
            continue
        ranges = ((0, 128),) if key.endswith(".bhn") else FRONT_ROW_RANGES
        rows = np.zeros(source[key].shape[0], dtype=bool)
        for start, stop in ranges:
            rows[start:stop] = True
        np.testing.assert_array_equal(hybrid[key][rows], source[key][rows])
        np.testing.assert_array_equal(hybrid[key][~rows], candidate[key][~rows])
        detail = evidence["per_gru_tensor"][key]
        assert detail["restored_row_ranges"] == [list(pair) for pair in ranges]
        assert detail["hybrid_candidate_changed_row_ranges"] == [list(p) for p in ranges]
        assert detail["restored_front_equals_source"]
        assert detail["retained_tail_equals_candidate"]
        for field in (
            "restored_parameter_count",
            "front_source_candidate_changed_elements",
            "tail_source_candidate_changed_elements",
            "hybrid_candidate_changed_elements",
            "hybrid_source_changed_elements",
        ):
            assert detail[field] == source[key].size // 2
    assert evidence["model_parameter_count"] == 393232
    assert evidence["gru_parameter_count"] == 222208
    assert evidence["restored_parameter_count"] == 111104
    for field in (
        "source_candidate_changed_model_tensors",
        "hybrid_candidate_changed_model_tensors",
        "hybrid_source_changed_model_tensors",
    ):
        assert evidence[field] == sorted(GRU_SHAPES)
    assert evidence["model_keys_shapes_dtypes_match"]
    assert evidence["all_model_weights_finite"]
    assert evidence["frozen_non_gru_tensors_bitwise_identical"]
    assert evidence["diagnostic_only"]
    assert evidence["student_updates"] == 0
    assert evidence["promotion_allowed"] is False
    assert evidence["state_path_isolation_established"] is False
    assert evidence["behavioral_effect_established"] is False
    assert len(set(evidence["model_sha256"].values())) == 3
    assert json.loads(json.dumps(evidence, allow_nan=False)) == evidence


def test_inputs_can_be_read_only_and_all_variant_storage_is_independent():
    source, candidate = paired_arrays()
    snapshots = [{k: a.copy() for k, a in group.items()} for group in (source, candidate)]
    for group in (source, candidate):
        for array in group.values():
            array.flags.writeable = False
    variants, _ = build_front_reverted_variants(source, candidate)
    for key in source:
        outputs = [group[key] for group in variants.values()]
        for index, array in enumerate(outputs):
            for other in [source[key], candidate[key], *outputs[:index]]:
                assert not np.shares_memory(array, other)
        outputs[0].fill(99)
    for original, saved in zip((source, candidate), snapshots, strict=True):
        for key in original:
            np.testing.assert_array_equal(original[key], saved[key])


def test_optimizer_and_rng_arrays_are_excluded_even_when_nonfinite():
    source, candidate = paired_arrays()
    source["optimizer.state"] = np.array([np.nan])
    candidate["rng.key"] = np.array([0, 1], dtype=np.uint32)
    variants, evidence = build_front_reverted_variants(source, candidate)
    assert all(all(key.startswith("model.") for key in group) for group in variants.values())
    clean_source, clean_candidate = paired_arrays()
    assert evidence == build_front_reverted_variants(clean_source, clean_candidate)[1]


def test_hashes_are_stable_across_mapping_order_and_memory_layout():
    source, candidate = paired_arrays()
    expected = build_front_reverted_variants(source, candidate)[1]
    source = {k: np.asfortranarray(v) for k, v in reversed(source.items())}
    candidate = {k: np.asfortranarray(v) for k, v in reversed(candidate.items())}
    actual = build_front_reverted_variants(source, candidate)[1]
    assert actual == expected


def test_hashes_include_names_shapes_dtype_and_payload():
    base_source, base_candidate = paired_arrays()
    hashes = {
        build_front_reverted_variants(base_source, base_candidate)[1]["model_sha256"]["source"]
    }
    for change in ("name", "shape", "dtype", "payload"):
        source, candidate = paired_arrays()
        for group in (source, candidate):
            if change == "name":
                group["model.other"] = group.pop("model.frozen_fixture")
            elif change == "shape":
                group["model.frozen_fixture"] = group["model.frozen_fixture"].reshape(2, -1)
            elif change == "dtype":
                group["model.frozen_fixture"] = group["model.frozen_fixture"].astype(np.float64)
            else:
                group["model.frozen_fixture"][0] = 1
        hashes.add(build_front_reverted_variants(source, candidate)[1]["model_sha256"]["source"])
    assert len(hashes) == 5


def test_sparse_differences_report_only_actual_rows_not_all_declared_rows():
    source, _ = paired_arrays()
    candidate = {key: value.copy() for key, value in source.items()}
    for row in (0, 1, 127, 128, 256, 511, 512, 639, 640):
        candidate["model.gru.Wh"][row, 3] += 1
    _, evidence = build_front_reverted_variants(source, candidate)
    detail = evidence["per_gru_tensor"]["model.gru.Wh"]
    assert detail["hybrid_candidate_changed_row_ranges"] == [
        [0, 2],
        [127, 128],
        [256, 257],
        [512, 513],
        [639, 640],
    ]
    assert detail["hybrid_source_changed_row_ranges"] == [[128, 129], [511, 512], [640, 641]]
    assert detail["hybrid_candidate_changed_elements"] == 6
    assert detail["hybrid_source_changed_elements"] == 3
    assert evidence["source_candidate_changed_model_tensors"] == ["model.gru.Wh"]
    assert evidence["per_gru_tensor"]["model.gru.b"]["hybrid_candidate_changed_row_ranges"] == []


def test_identical_pair_has_identical_variant_hashes_and_no_changes():
    source, _ = paired_arrays()
    _, evidence = build_front_reverted_variants(source, source)
    assert len(set(evidence["model_sha256"].values())) == 1
    assert evidence["source_candidate_changed_model_tensors"] == []
    assert evidence["hybrid_candidate_changed_model_tensors"] == []
    assert evidence["hybrid_source_changed_model_tensors"] == []


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("key", ["model.gru.Wx", "model.frozen_fixture"])
def test_nonfinite_model_weights_rejected(bad_value, side, key):
    groups = paired_arrays()
    groups[side][key].flat[0] = bad_value
    with pytest.raises(ValueError, match="finite"):
        build_front_reverted_variants(*groups)


@pytest.mark.parametrize("dtype", [np.int32, np.bool_, np.complex64, object])
def test_nonfloating_model_arrays_rejected(dtype):
    source, candidate = paired_arrays()
    source["model.frozen_fixture"] = source["model.frozen_fixture"].astype(dtype)
    with pytest.raises(ValueError, match="floating-point"):
        build_front_reverted_variants(source, candidate)


@pytest.mark.parametrize(
    "kind", ["dtype", "shape", "key", "frozen", "count", "gru_shape", "gru_key"]
)
def test_incompatible_source_candidate_pairs_rejected(kind):
    source, candidate = paired_arrays()
    if kind == "dtype":
        candidate["model.gru.b"] = candidate["model.gru.b"].astype(np.float64)
    elif kind == "shape":
        candidate["model.frozen_fixture"] = candidate["model.frozen_fixture"].reshape(2, -1)
    elif kind == "key":
        candidate["model.other"] = candidate.pop("model.frozen_fixture")
    elif kind == "frozen":
        candidate["model.frozen_fixture"][0] = 1
    elif kind == "count":
        candidate["model.frozen_fixture"] = candidate["model.frozen_fixture"][:-1]
    elif kind == "gru_shape":
        candidate["model.gru.Wx"] = candidate["model.gru.Wx"].reshape(384, 64)
    else:
        candidate["model.gru.unknown"] = candidate.pop("model.gru.Wx")
    with pytest.raises(ValueError):
        build_front_reverted_variants(source, candidate)


def test_signed_zero_changes_are_not_silently_treated_as_identical():
    source, candidate = paired_arrays()
    candidate["model.frozen_fixture"][0] = -0.0
    with pytest.raises(ValueError, match="frozen"):
        build_front_reverted_variants(source, candidate)
    candidate["model.frozen_fixture"][0] = 0.0
    source["model.gru.b"][0] = 0.0
    candidate["model.gru.b"][0] = -0.0
    variants, evidence = build_front_reverted_variants(source, candidate)
    assert not np.signbit(variants["front_reverted"]["model.gru.b"][0])
    assert evidence["per_gru_tensor"]["model.gru.b"]["hybrid_candidate_changed_elements"] == 384


@pytest.mark.parametrize("value", [None, [], {0: np.ones(1)}, {}])
def test_invalid_tensor_mappings_rejected(value):
    source, _ = paired_arrays()
    with pytest.raises(ValueError):
        build_front_reverted_variants(source, value)


@pytest.mark.parametrize(
    "source,candidate,hybrid,ratio",
    [
        (1, 3, 2, 0.5),
        (1, 3, 1, 1),
        (1, 3, 3, 0),
        (1, 3, 4, -0.5),
        (1, 3, 0, 1.5),
        (np.float32(1), np.float64(3), np.float16(2), 0.5),
    ],
)
def test_action_nll_recovery_preserves_unclipped_ratio(source, candidate, hybrid, ratio):
    result = action_nll_recovery(source, candidate, hybrid)
    assert result["recovery_ratio"] == ratio
    assert result["candidate_minus_source_nll"] == candidate - source
    assert result["candidate_minus_hybrid_nll"] == candidate - hybrid
    assert result["applicable"]
    assert result["reason"] is None
    assert result["ratio_clipped"] is False
    assert result["promotion_threshold"] is None
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("source,candidate", [(1, 1), (3, 1)])
def test_nonpositive_denominator_reports_raw_differences_and_reason(source, candidate):
    result = action_nll_recovery(source, candidate, 0.5)
    assert result["recovery_ratio"] is None
    assert result["applicable"] is False
    assert result["reason"] == "candidate_nll_not_worse_than_source"
    assert result["candidate_minus_source_nll"] == candidate - source
    assert result["candidate_minus_hybrid_nll"] == candidate - 0.5


@pytest.mark.parametrize(
    "value",
    [
        np.nan,
        np.inf,
        -np.inf,
        -1,
        True,
        np.bool_(False),
        "1",
        None,
        [1],
        np.array(1),
        1j,
        10**1000,
    ],
)
@pytest.mark.parametrize("index", [0, 1, 2])
def test_invalid_action_nll_values_rejected(value, index):
    values = [1, 3, 2]
    values[index] = value
    with pytest.raises(ValueError, match="finite nonnegative real scalar"):
        action_nll_recovery(*values)


def test_finite_scores_with_overflowing_ratio_rejected():
    with pytest.raises(ValueError, match="ratio must be finite"):
        action_nll_recovery(0.0, np.nextafter(0.0, 1.0), 1e308)


def test_cpu_module_does_not_import_mlx():
    before = set(sys.modules)
    module = importlib.import_module("ainerzero.learning.gru_intervention")
    importlib.reload(module)
    assert not any(key == "mlx" or key.startswith("mlx.") for key in set(sys.modules) - before)
