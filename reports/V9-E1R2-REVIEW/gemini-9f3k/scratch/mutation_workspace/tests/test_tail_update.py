import builtins
import importlib
import json
import sys
import types

import numpy as np
import pytest

from ainerzero.learning import tail_update
from ainerzero.learning.gru_intervention import GRU_PARAMETER_COUNT, GRU_SHAPES


def tensors(dtype=np.float32):
    source = {key: np.ones(shape, dtype=dtype) for key, shape in GRU_SHAPES.items()}
    source["model.frozen_fixture"] = np.zeros(393232 - GRU_PARAMETER_COUNT, dtype=dtype)
    current = {key: value.copy() for key, value in source.items()}
    return source, current


def tail_rows(key):
    rows = np.zeros(GRU_SHAPES[key][0], dtype=bool)
    for start, stop in (
        ((128, 256),) if key.endswith(".bhn") else ((128, 256), (384, 512), (640, 768))
    ):
        rows[start:stop] = True
    return rows


@pytest.fixture
def fake_mx(monkeypatch):
    module = types.ModuleType("mlx.core")
    module.array = np.array
    module.where = np.where
    module.zeros_like = np.zeros_like
    package = types.ModuleType("mlx")
    package.core = module
    monkeypatch.setitem(sys.modules, "mlx", package)
    monkeypatch.setitem(sys.modules, "mlx.core", module)
    return module


class FakeModel:
    def __init__(self, arrays):
        self.gru = types.SimpleNamespace(
            **{key.removeprefix("model.gru."): arrays[key].copy() for key in GRU_SHAPES}
        )
        self.updates = 0

    def update(self, tree):
        assert set(tree) == {"gru"}
        self.updates += 1
        for name, value in tree["gru"].items():
            setattr(self.gru, name, value)


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_gradient_mask_keeps_exact_tail_rows_without_mutation(fake_mx, dtype):
    rng = np.random.default_rng(42)
    grads = {
        "gru": {
            key.removeprefix("model.gru."): rng.normal(size=shape).astype(dtype)
            for key, shape in GRU_SHAPES.items()
        }
    }
    originals = {name: value.copy() for name, value in grads["gru"].items()}
    result = tail_update.mask_gru_tail_gradients(grads)
    assert set(result) == {"gru"}
    for name, original in originals.items():
        rows = tail_rows(f"model.gru.{name}")
        masked = result["gru"][name]
        assert masked.dtype == original.dtype
        assert masked.shape == original.shape
        np.testing.assert_array_equal(masked[rows], original[rows])
        assert not masked[~rows].any()
        assert not np.shares_memory(masked, grads["gru"][name])
        np.testing.assert_array_equal(grads["gru"][name], original)


@pytest.mark.parametrize(
    "bad", [None, [], {}, {"other": {}}, {"gru": []}, {"gru": {}}, {"gru": {}, "extra": {}}]
)
def test_gradient_mask_rejects_incomplete_or_extra_trees_without_tensor_import(bad, monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx.core", None)
    with pytest.raises(ValueError, match="four gru"):
        tail_update.mask_gru_tail_gradients(bad)


@pytest.mark.parametrize("kind", ["extra", "missing", "shape"])
def test_gradient_mask_rejects_invalid_leaves(kind, monkeypatch):
    grads = {"gru": {k.removeprefix("model.gru."): np.ones(s) for k, s in GRU_SHAPES.items()}}
    if kind == "extra":
        grads["gru"]["other"] = np.ones(1)
    elif kind == "missing":
        grads["gru"].pop("bhn")
    else:
        grads["gru"]["Wh"] = np.ones((256, 768))
    monkeypatch.setitem(sys.modules, "mlx.core", None)
    with pytest.raises(ValueError):
        tail_update.mask_gru_tail_gradients(grads)


def test_gradient_mask_accepts_mlx_empty_frozen_module_branches(fake_mx):
    grads = {"gru": {k.removeprefix("model.gru."): np.ones(s) for k, s in GRU_SHAPES.items()}}
    grads.update(
        byte_embedding={},
        encoder=[{}, {}],
        posterior=[{}, {}],
        prior=[{}, {}],
        symbol_readout={},
        frozen_nested={"empty": [(), {}]},
    )
    result = tail_update.mask_gru_tail_gradients(grads)
    assert set(result) == {"gru"}
    assert grads["encoder"] == [{}, {}]
    for name, value in result["gru"].items():
        rows = tail_rows(f"model.gru.{name}")
        assert (value[rows] == 1).all()
        assert (value[~rows] == 0).all()


@pytest.mark.parametrize("leaf", [np.zeros(1), np.zeros(0), 0.0, None, "frozen"])
def test_gradient_mask_still_rejects_any_non_gru_gradient_leaf(leaf, monkeypatch):
    grads = {"gru": {k.removeprefix("model.gru."): np.ones(s) for k, s in GRU_SHAPES.items()}}
    grads["encoder"] = [{}, {"weight": leaf}]
    monkeypatch.setitem(sys.modules, "mlx.core", None)
    with pytest.raises(ValueError, match="four gru"):
        tail_update.mask_gru_tail_gradients(grads)


def test_projection_restores_front_after_weight_decay_and_preserves_tail(fake_mx):
    source, current = tensors()
    source["model.gru.b"][0] = -0.0
    # Emulate an optimizer affecting every GRU row via decoupled weight decay.
    for key in GRU_SHAPES:
        current[key] *= 0.99
        current[key][tail_rows(key)] += 0.1
    current["model.gru.b"][0] = 0.0
    model = FakeModel(current)
    tail_update.project_gru_front(model, source)
    assert model.updates == 1
    assert np.signbit(model.gru.b[0])
    for key in GRU_SHAPES:
        projected = getattr(model.gru, key.removeprefix("model.gru."))
        rows = tail_rows(key)
        assert projected[~rows].tobytes() == source[key][~rows].tobytes()
        assert projected[rows].tobytes() == current[key][rows].tobytes()
    output = {**source, **{key: getattr(model.gru, key[10:]) for key in GRU_SHAPES}}
    result = tail_update.verify_tail_update(source, output)
    assert result["changed_elements"] == 111104
    assert result["frozen_parameter_count"] == 282128


@pytest.mark.parametrize("kind", ["shape", "dtype"])
def test_projection_validation_happens_before_any_model_update(fake_mx, kind):
    source, current = tensors()
    model = FakeModel(current)
    if kind == "shape":
        model.gru.bhn = np.zeros(128, dtype=np.float32)
    else:
        model.gru.bhn = model.gru.bhn.astype(np.float64)
    with pytest.raises(ValueError, match="shape or dtype"):
        tail_update.project_gru_front(model, source)
    assert model.updates == 0


def test_projection_rejects_nonfinite_source_before_tensor_import(monkeypatch):
    source, current = tensors()
    source["model.frozen_fixture"][0] = np.nan
    monkeypatch.setitem(sys.modules, "mlx.core", None)
    with pytest.raises(ValueError, match="finite"):
        tail_update.project_gru_front(FakeModel(current), source)


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_verifier_accepts_only_tail_changes_and_reports_exact_evidence(dtype):
    source, current = tensors(dtype)
    for key in GRU_SHAPES:
        current[key][tail_rows(key)] += 0.25
    result = tail_update.verify_tail_update(source, current)
    assert result["model_parameter_count"] == 393232
    assert result["gru_parameter_count"] == 222208
    assert result["allowed_parameter_count"] == 111104
    assert result["frozen_parameter_count"] == 282128
    assert result["changed_elements"] == 111104
    assert result["changed_model_tensors"] == sorted(GRU_SHAPES)
    assert result["model_keys_shapes_dtypes_match"]
    assert result["all_model_weights_finite"]
    assert result["frozen_parameters_bitwise_identical"]
    for key, detail in result["per_gru_tensor"].items():
        assert detail["changed_elements"] == source[key].size // 2
        assert detail["changed_row_ranges"] == detail["allowed_tail_row_ranges"]
        assert detail["frozen_front_bitwise_identical"]
    assert result["model_sha256"]["source"] != result["model_sha256"]["current"]
    assert result["state_path_isolation_established"] is False
    assert result["behavioral_effect_established"] is False
    assert result["promotion_allowed"] is False
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_verifier_accepts_unchanged_source_as_preupdate_check():
    source, current = tensors()
    result = tail_update.verify_tail_update(source, current)
    assert result["changed_model_tensors"] == []
    assert result["changed_elements"] == 0
    assert result["model_sha256"]["source"] == result["model_sha256"]["current"]


def test_sparse_and_signed_zero_tail_changes_count_by_bits():
    source, current = tensors()
    source["model.gru.b"][128] = 0.0
    current["model.gru.b"][128] = -0.0
    current["model.gru.Wh"][255, 0] += 1
    current["model.gru.Wh"][384, 255] += 1
    result = tail_update.verify_tail_update(source, current)
    assert result["changed_elements"] == 3
    assert result["changed_model_tensors"] == ["model.gru.Wh", "model.gru.b"]
    assert result["per_gru_tensor"]["model.gru.b"]["changed_row_ranges"] == [[128, 129]]
    assert result["per_gru_tensor"]["model.gru.Wh"]["changed_row_ranges"] == [
        [255, 256],
        [384, 385],
    ]


@pytest.mark.parametrize("key", list(GRU_SHAPES))
@pytest.mark.parametrize("row_kind", ["first", "last"])
def test_any_front_change_is_rejected(key, row_kind):
    source, current = tensors()
    rows = np.flatnonzero(~tail_rows(key))
    row = rows[0 if row_kind == "first" else -1]
    current[key][row] += 0.1
    with pytest.raises(ValueError, match="frozen GRU front"):
        tail_update.verify_tail_update(source, current)


@pytest.mark.parametrize("key", ["model.gru.b", "model.frozen_fixture"])
def test_signed_zero_front_or_non_gru_difference_is_rejected(key):
    source, current = tensors()
    source[key][0] = 0.0
    current[key][0] = -0.0
    with pytest.raises(ValueError, match="frozen"):
        tail_update.verify_tail_update(source, current)


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("key", ["model.gru.b", "model.frozen_fixture"])
def test_nonfinite_source_or_current_is_rejected(side, value, key):
    pair = tensors()
    pair[side][key].flat[-1] = value
    with pytest.raises(ValueError, match="finite"):
        tail_update.verify_tail_update(*pair)


@pytest.mark.parametrize("kind", ["key", "shape", "dtype", "count", "gru_shape", "gru_key"])
def test_all_model_keys_shapes_dtypes_and_fixed_counts_are_checked(kind):
    source, current = tensors()
    if kind == "key":
        current["model.other"] = current.pop("model.frozen_fixture")
    elif kind == "shape":
        current["model.frozen_fixture"] = current["model.frozen_fixture"].reshape(2, -1)
    elif kind == "dtype":
        current["model.gru.b"] = current["model.gru.b"].astype(np.float64)
    elif kind == "count":
        current["model.frozen_fixture"] = current["model.frozen_fixture"][:-1]
    elif kind == "gru_shape":
        current["model.gru.Wh"] = current["model.gru.Wh"].T
    else:
        current["model.gru.other"] = current.pop("model.gru.bhn")
    with pytest.raises(ValueError):
        tail_update.verify_tail_update(source, current)


@pytest.mark.parametrize("dtype", [np.int32, np.complex64, np.bool_, object])
def test_nonfloating_model_weights_rejected(dtype):
    source, current = tensors()
    current["model.frozen_fixture"] = current["model.frozen_fixture"].astype(dtype)
    with pytest.raises(ValueError, match="floating-point"):
        tail_update.verify_tail_update(source, current)


@pytest.mark.parametrize("bad", [None, [], {0: np.ones(1)}, {}])
def test_invalid_tensor_mapping_rejected(bad):
    source, _ = tensors()
    with pytest.raises(ValueError):
        tail_update.verify_tail_update(source, bad)


def test_verifier_ignores_nonmodel_arrays_and_is_storage_order_independent():
    source, current = tensors()
    current["model.gru.Wh"][640, 12] += 1
    expected = tail_update.verify_tail_update(source, current)
    source = {key: np.asfortranarray(value) for key, value in reversed(source.items())}
    current = {key: np.asfortranarray(value) for key, value in reversed(current.items())}
    source["optimizer.bad_fixture"] = np.array([np.nan])
    current["rng.key"] = np.array([0, 1], dtype=np.uint32)
    assert tail_update.verify_tail_update(source, current) == expected


def test_verification_is_read_only_and_accepts_readonly_arrays():
    source, current = tensors()
    snapshots = [
        dict((key, value.tobytes()) for key, value in group.items()) for group in (source, current)
    ]
    for group in (source, current):
        for value in group.values():
            value.flags.writeable = False
    tail_update.verify_tail_update(source, current)
    for group, snapshot in zip((source, current), snapshots, strict=True):
        assert {key: value.tobytes() for key, value in group.items()} == snapshot


def test_module_and_verifier_do_not_import_mlx(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx."):
            raise AssertionError("CPU verification must not import tensor runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(tail_update)
    source, current = tensors()
    tail_update.verify_tail_update(source, current)
