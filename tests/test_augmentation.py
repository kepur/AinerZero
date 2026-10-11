import copy

import numpy as np
import pytest

from ainerzero.data.augmentation import permute_symbols


def make_batch(batch_size=3):
    # Every sample contains the complete byte alphabet twice, at shifted cells.
    values = np.arange(256, dtype=np.int32).reshape(32, 8)
    symbols = np.tile(np.concatenate([values, np.roll(values, 3, axis=1)]), (batch_size, 1, 1))
    return {
        "symbols": symbols,
        "visible_mask": np.ones(symbols.shape, dtype=np.bool_),
        "actions": np.full((batch_size, 63), 2, dtype=np.int32),
        "cursor": np.zeros((batch_size, 64), dtype=np.int32),
        "episode_start": np.zeros((batch_size, 64), dtype=np.bool_),
    }


def test_bijection_preserves_equality_across_time_and_cells():
    original = make_batch()
    result = permute_symbols(original, np.random.default_rng(73))
    for old, new in zip(original["symbols"], result["symbols"], strict=True):
        assert np.array_equal(np.sort(np.unique(new)), np.arange(256))
        old = old.ravel()
        new = new.ravel()
        np.testing.assert_array_equal(old[:, None] == old, new[:, None] == new)


def test_each_sample_receives_an_independent_bijection():
    result = permute_symbols(make_batch(), np.random.default_rng(73))
    for first in range(3):
        for second in range(first):
            assert not np.array_equal(result["symbols"][first], result["symbols"][second])


def test_input_and_non_symbol_fields_are_preserved_in_independent_copies():
    batch = make_batch()
    originals = {name: values.copy() for name, values in batch.items()}
    result = permute_symbols(batch, np.random.default_rng(73))
    assert result.keys() == batch.keys()
    for name, original in originals.items():
        np.testing.assert_array_equal(batch[name], original)
        assert not np.shares_memory(result[name], batch[name])
        if name != "symbols":
            np.testing.assert_array_equal(result[name], original)
            assert result[name].dtype == original.dtype
        result[name].fill(0)
        np.testing.assert_array_equal(batch[name], original)


def test_hidden_cells_are_zero_even_if_input_contains_hidden_nonzero_bytes():
    batch = make_batch()
    batch["visible_mask"][:, ::2, ::2] = False
    result = permute_symbols(batch, np.random.default_rng(73))
    assert np.all(result["symbols"][~batch["visible_mask"]] == 0)
    # A hidden occurrence does not reserve byte zero or change visible mapping.
    unmasked = permute_symbols(make_batch(), np.random.default_rng(73))
    np.testing.assert_array_equal(
        result["symbols"][batch["visible_mask"]], unmasked["symbols"][batch["visible_mask"]]
    )


def test_seed_and_restored_caller_rng_reproduce_transforms():
    batch = make_batch()
    rng = np.random.default_rng(73)
    state = copy.deepcopy(rng.bit_generator.state)
    expected = permute_symbols(batch, rng)
    seeded = permute_symbols(batch, np.random.default_rng(73))
    assert rng.bit_generator.state != state
    permute_symbols(batch, rng)
    rng.bit_generator.state = state
    restored = permute_symbols(batch, rng)
    for name in batch:
        np.testing.assert_array_equal(expected[name], seeded[name])
        np.testing.assert_array_equal(expected[name], restored[name])


@pytest.mark.parametrize("dtype", [np.int8, np.uint8, np.int16, np.int32, np.int64, np.uint64])
def test_integer_inputs_cannot_overflow_after_relabeling(dtype):
    batch = make_batch(1)
    batch["symbols"] = (batch["symbols"] % 128).astype(dtype)
    result = permute_symbols(batch, np.random.default_rng(73))
    assert result["symbols"].dtype == np.int32
    assert result["symbols"].min() >= 0
    assert result["symbols"].max() > 127
    assert result["symbols"].max() <= 255


@pytest.mark.parametrize("rng", [None, 3, np.random.RandomState(73)])
def test_invalid_rng_is_rejected(rng):
    with pytest.raises(TypeError, match="Generator"):
        permute_symbols(make_batch(), rng)


@pytest.mark.parametrize("key", ["symbols", "visible_mask"])
def test_missing_required_array_is_rejected(key):
    batch = make_batch()
    del batch[key]
    with pytest.raises(ValueError, match="requires"):
        permute_symbols(batch, np.random.default_rng(73))


@pytest.mark.parametrize("shape", [(2, 8), (2, 3, 7), (0, 3, 8), (2, 0, 8), (2, 3, 8, 1)])
def test_invalid_symbol_shape_is_rejected(shape):
    batch = make_batch()
    batch["symbols"] = np.zeros(shape, dtype=np.int32)
    with pytest.raises(ValueError, match="shape"):
        permute_symbols(batch, np.random.default_rng(73))


@pytest.mark.parametrize("dtype", [np.float32, np.bool_, np.complex64, object])
def test_non_integer_symbols_are_rejected(dtype):
    batch = make_batch()
    batch["symbols"] = batch["symbols"].astype(dtype)
    with pytest.raises(TypeError, match="integer dtype"):
        permute_symbols(batch, np.random.default_rng(73))


@pytest.mark.parametrize("value", [-1, 256])
def test_out_of_range_symbols_are_rejected(value):
    batch = make_batch()
    batch["symbols"][0, 0, 0] = value
    with pytest.raises(ValueError, match="0..255"):
        permute_symbols(batch, np.random.default_rng(73))


def test_mask_shape_and_dtype_are_validated():
    batch = make_batch()
    batch["visible_mask"] = batch["visible_mask"][:, :-1]
    with pytest.raises(ValueError, match="same shape"):
        permute_symbols(batch, np.random.default_rng(73))
    batch = make_batch()
    batch["visible_mask"] = batch["visible_mask"].astype(np.int32)
    with pytest.raises(TypeError, match="Boolean dtype"):
        permute_symbols(batch, np.random.default_rng(73))


@pytest.mark.parametrize("batch", [None, [], {"symbols": [], "visible_mask": []}])
def test_batch_container_and_values_must_be_arrays(batch):
    with pytest.raises(TypeError):
        permute_symbols(batch, np.random.default_rng(73))


def test_invalid_input_does_not_advance_rng():
    batch = make_batch()
    batch["symbols"][0, 0, 0] = 256
    rng = np.random.default_rng(73)
    state = copy.deepcopy(rng.bit_generator.state)
    with pytest.raises(ValueError):
        permute_symbols(batch, rng)
    assert state == rng.bit_generator.state
