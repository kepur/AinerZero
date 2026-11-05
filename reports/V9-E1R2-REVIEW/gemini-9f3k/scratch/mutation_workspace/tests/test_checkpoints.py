from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ainerzero.runtime import checkpoints
from ainerzero.runtime.checkpoints import (
    CheckpointError,
    atomic_write_json,
    load_checkpoint,
    save_checkpoint,
)


def _save(root: Path, checkpoint_id: str = "step-0001") -> Path:
    return save_checkpoint(
        root,
        checkpoint_id,
        {"model.weight": np.arange(12, dtype=np.float32).reshape(3, 4)},
        {"step": 1, "label": "测试恢复点"},
    )


def test_round_trip_preserves_arrays_and_exact_rng_continuation(tmp_path):
    rng = np.random.default_rng(73)
    rng.normal(size=17)
    tensors = {
        "model.weight": rng.normal(size=(4, 8)).astype(np.float32)[:, ::2],
        "optimizer.step": np.array(17, dtype=np.int64),
        "optimizer.momentum": np.array([0.125, -0.25], dtype=np.float64),
    }
    metadata = {"step": 17, "rng_state": rng.bit_generator.state, "label": "恢复"}
    path = save_checkpoint(tmp_path, "step-17", tensors, metadata)
    loaded, restored_metadata = load_checkpoint(path)
    for key in tensors:
        np.testing.assert_array_equal(loaded[key], tensors[key])
        assert loaded[key].dtype == tensors[key].dtype
        assert loaded[key].shape == tensors[key].shape
    assert restored_metadata == metadata
    restored = np.random.default_rng()
    restored.bit_generator.state = restored_metadata["rng_state"]
    np.testing.assert_array_equal(restored.normal(size=20), rng.normal(size=20))
    manifest = json.loads((path / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["created_at"].endswith("Z")
    assert set(manifest["files"]) == {"metadata.json", "tensors.safetensors"}


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a/b", ".temporary", "", "a..b"])
def test_invalid_ids_do_not_create_anything(tmp_path, name):
    with pytest.raises(CheckpointError):
        _save(tmp_path, name)
    assert not list(tmp_path.iterdir())


def test_existing_checkpoint_is_immutable(tmp_path):
    path = _save(tmp_path)
    before = {item.name: item.read_bytes() for item in path.iterdir()}
    with pytest.raises(FileExistsError):
        save_checkpoint(tmp_path, path.name, {"different": np.zeros(4)}, {})
    assert {item.name: item.read_bytes() for item in path.iterdir()} == before
    assert load_checkpoint(path)[1]["step"] == 1


@pytest.mark.parametrize("filename", ["metadata.json", "tensors.safetensors"])
def test_tampered_data_is_rejected_even_at_same_file_size(tmp_path, filename):
    path = _save(tmp_path)
    file = path / filename
    data = bytearray(file.read_bytes())
    data[-1] ^= 1
    file.write_bytes(data)
    with pytest.raises(CheckpointError, match="integrity"):
        load_checkpoint(path)


@pytest.mark.parametrize("filename", ["metadata.json", "manifest.json", "tensors.safetensors"])
def test_missing_file_is_never_a_valid_checkpoint(tmp_path, filename):
    path = _save(tmp_path)
    (path / filename).unlink()
    with pytest.raises(CheckpointError):
        load_checkpoint(path)


def test_unknown_schema_and_hidden_temporary_checkpoint_are_rejected(tmp_path):
    path = _save(tmp_path)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 2
    atomic_write_json(manifest_path, manifest)
    with pytest.raises(CheckpointError, match="schema"):
        load_checkpoint(path)
    manifest["schema_version"] = 1
    atomic_write_json(manifest_path, manifest)
    hidden = tmp_path / ".step-0001.tmp-aborted"
    path.rename(hidden)
    with pytest.raises(CheckpointError):
        load_checkpoint(hidden)


def test_symlinked_tensor_is_rejected(tmp_path):
    path = _save(tmp_path)
    original = path / "tensors.safetensors"
    outside = tmp_path / "external.safetensors"
    original.rename(outside)
    original.symlink_to(outside)
    with pytest.raises(CheckpointError, match="regular file"):
        load_checkpoint(path)


def test_valid_hash_cannot_make_malformed_tensors_loadable(tmp_path):
    path = _save(tmp_path)
    data = b"invalid safetensors file"
    (path / "tensors.safetensors").write_bytes(data)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["tensors.safetensors"] = {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    atomic_write_json(manifest_path, manifest)
    with pytest.raises(CheckpointError, match="safetensors"):
        load_checkpoint(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metadata_is_rejected_before_writing(tmp_path, value):
    with pytest.raises(ValueError):
        save_checkpoint(tmp_path, "bad", {}, {"nested": {"loss": value}})
    assert not list(tmp_path.iterdir())


def test_failed_publish_preserves_prior_checkpoint_and_other_temporary_dirs(tmp_path, monkeypatch):
    previous = _save(tmp_path, "previous")
    orphan = tmp_path / ".unrelated.tmp-crashed"
    orphan.mkdir()
    (orphan / "evidence").write_text("must be retained")

    def fail_rename(*args, **kwargs):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(checkpoints.os, "rename", fail_rename)
    with pytest.raises(OSError, match="publication failure"):
        _save(tmp_path, "next")
    assert load_checkpoint(previous)[1]["step"] == 1
    assert (orphan / "evidence").read_text() == "must be retained"
    assert {item.name for item in tmp_path.iterdir()} == {previous.name, orphan.name}


def test_atomic_json_failure_preserves_existing_report(tmp_path, monkeypatch):
    report = atomic_write_json(tmp_path / "report.json", {"verified": True})
    before = report.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(checkpoints.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        atomic_write_json(report, {"verified": False})
    assert report.read_bytes() == before
    assert list(tmp_path.iterdir()) == [report]


def test_atomic_json_refuses_nan_without_touching_old_report(tmp_path):
    report = atomic_write_json(tmp_path / "report.json", {"verified": True})
    before = report.read_bytes()
    with pytest.raises(ValueError):
        atomic_write_json(report, {"metric": float("nan")})
    assert report.read_bytes() == before
