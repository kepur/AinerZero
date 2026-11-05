import json

import numpy as np
import pytest

from ainerzero.learning.memory_codec import audit_bounded_codec


def codec():
    # All 256 binary words give distinct codes using only eight dimensions.
    codes = np.zeros((256, 16), dtype=np.float64)
    codes[:, :8] = 2 * ((np.arange(256)[:, None] >> np.arange(8)) & 1) - 1
    return 4 * codes, codes, np.zeros(256)


def test_all_bytes_have_fixed_bounded_witnesses_without_student_or_input_mutation():
    arrays = codec()
    originals = [value.copy() for value in arrays]
    for value in arrays:
        value.flags.writeable = False
    result = audit_bounded_codec(*arrays)
    assert result["bounded_codec_compatible"]
    assert result["all_256_correct"]
    assert result["correct_count"] == result["positive_margin_count"] == 256
    assert result["minimum_margin"] == 2
    assert result["failed_bytes"] == []
    assert result["clipped_byte_count"] == 256
    assert result["clipped_element_count"] == 256 * 8
    assert result["witness_minimum"] == -1
    assert result["witness_maximum"] == 1
    assert result["state_bounds"] == [-1, 1]
    assert result["state_region"] == "h[:,128:]"
    assert result["diagnostic_only"]
    assert result["failure_does_not_prove_no_bounded_code_exists"]
    for flag in (
        "witnesses_copied_into_student",
        "witnesses_used_as_training_targets",
        "optimization_performed",
        "student_update_performed",
        "gru_learnability_established",
    ):
        assert result[flag] is False
    for original, array in zip(originals, arrays, strict=True):
        np.testing.assert_array_equal(array, original)
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_per_byte_metrics_mask_only_target_class_and_use_actual_softmax_nll():
    result = audit_bounded_codec(*codec())
    expected_nll = 8 * np.log1p(np.exp(-2))
    for byte, row in enumerate(result["per_byte"]):
        assert row["byte"] == row["predicted_byte"] == byte
        assert row["correct"]
        assert row["margin"] == 2
        assert row["clipped_element_count"] == 8
        assert row["nll"] == pytest.approx(expected_nll)
    assert result["mean_nll"] == pytest.approx(expected_nll)
    assert result["maximum_nll"] == pytest.approx(expected_nll)


def test_common_logit_offset_does_not_change_metrics():
    embedding, weight, bias = codec()
    reference = audit_bounded_codec(embedding, weight, bias)
    shifted = audit_bounded_codec(embedding, weight, bias + 1000)
    assert shifted == reference


def test_ties_do_not_establish_compatibility_even_for_argmax_winner():
    result = audit_bounded_codec(np.zeros((256, 16)), np.zeros((256, 16)), np.zeros(256))
    assert result["correct_count"] == 1
    assert result["positive_margin_count"] == 0
    assert not result["bounded_codec_compatible"]
    assert not result["all_256_correct"]
    assert result["failed_bytes"] == list(range(256))
    assert result["per_byte"][0]["correct"]
    assert result["minimum_margin"] == 0
    assert result["mean_nll"] == pytest.approx(np.log(256))


def test_clipping_can_fail_despite_correct_unbounded_embedding_codec():
    embedding = np.zeros((256, 16))
    embedding[:, 0] = np.arange(1, 257)
    weight = 2 * embedding
    bias = -(embedding**2).sum(axis=1)
    np.testing.assert_array_equal((embedding @ weight.T + bias).argmax(axis=1), np.arange(256))
    result = audit_bounded_codec(embedding, weight, bias)
    assert not result["bounded_codec_compatible"]
    assert result["correct_count"] == 1
    assert result["failed_bytes"] == list(range(1, 256))
    assert result["failure_does_not_prove_no_bounded_code_exists"]


@pytest.mark.parametrize(
    "field,value",
    [
        (0, np.zeros((255, 16))),
        (0, np.zeros((256, 15))),
        (1, np.zeros((16, 256))),
        (2, np.zeros((256, 1))),
        (0, np.full((256, 16), np.nan)),
        (1, np.full((256, 16), np.inf)),
        (2, np.full(256, -np.inf)),
        (0, np.zeros((256, 16), dtype=complex)),
        (1, np.zeros((256, 16), dtype=bool)),
        (2, np.full(256, "1")),
        (2, np.zeros(256, dtype=object)),
    ],
)
def test_invalid_codec_arrays_rejected(field, value):
    arrays = list(codec())
    arrays[field] = value
    with pytest.raises(ValueError):
        audit_bounded_codec(*arrays)


def test_clipping_large_finite_embedding_is_safe():
    embedding, weight, bias = codec()
    embedding = np.sign(embedding) * 1e308
    result = audit_bounded_codec(embedding, weight, bias)
    assert result["bounded_codec_compatible"]
    assert result["minimum_margin"] == 2


def test_logit_overflow_is_rejected_before_masking_competitors():
    with pytest.raises(ValueError, match="logits"):
        audit_bounded_codec(np.ones((256, 16)), np.full((256, 16), 1e308), np.zeros(256))


def test_finite_logits_with_overflowing_margin_or_nll_are_rejected():
    bias = np.full(256, -1e308)
    bias[0] = 1e308
    with pytest.raises(ValueError, match="margins and NLL"):
        audit_bounded_codec(np.zeros((256, 16)), np.zeros((256, 16)), bias)


def test_large_finite_nll_mean_does_not_overflow_accumulation():
    bias = np.full(256, -1e306)
    bias[0] = 1e306
    result = audit_bounded_codec(np.zeros((256, 16)), np.zeros((256, 16)), bias)
    assert result["mean_nll"] == pytest.approx(2e306 * (255 / 256))
    assert result["maximum_nll"] == 2e306
    json.dumps(result, allow_nan=False)
