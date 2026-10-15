"""Immutable, verified checkpoints with no dependency on a GPU runtime.

Only complete directories are published. Callers put model/optimizer arrays in
``tensors`` and JSON-compatible RNG, environment, and configuration state in
``metadata``. A hash detects accidental changes; it is not a digital signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from safetensors.numpy import load as load_tensors
from safetensors.numpy import save_file

SCHEMA_VERSION = 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_DATA_FILES = {"tensors.safetensors", "metadata.json"}


class CheckpointError(ValueError):
    """A checkpoint is incomplete, unsupported, or failed integrity checks."""


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise CheckpointError(f"Non-finite JSON value: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CheckpointError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(data: bytes) -> Any:
    try:
        return json.loads(data, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError("Invalid checkpoint JSON") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, payload: Any) -> Path:
    """Replace one JSON document atomically, preserving it on pre-commit failure."""
    path = Path(path)
    data = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _validate_id(checkpoint_id: str) -> None:
    if not isinstance(checkpoint_id, str) or not _ID.fullmatch(checkpoint_id):
        raise CheckpointError(
            "Checkpoint ID must be 1-128 ASCII letters, digits, underscores or "
            "hyphens, starting with a letter or digit"
        )


def _load_verified(path: Path, *, expected_id: str) -> tuple[dict[str, np.ndarray], dict]:
    if path.is_symlink() or not path.is_dir():
        raise CheckpointError("Checkpoint must be a complete directory, not a symlink")
    if {entry.name for entry in path.iterdir()} != _DATA_FILES | {"manifest.json"}:
        raise CheckpointError("Checkpoint contains missing or unexpected files")
    for name in _DATA_FILES | {"manifest.json"}:
        item = path / name
        if item.is_symlink() or not item.is_file():
            raise CheckpointError(f"Checkpoint entry is not a regular file: {name}")
    manifest = _read_json((path / "manifest.json").read_bytes())
    if not isinstance(manifest, dict):
        raise CheckpointError("Checkpoint manifest must be an object")
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        raise CheckpointError("Unsupported checkpoint schema_version")
    if manifest.get("checkpoint_id") != expected_id:
        raise CheckpointError("Checkpoint ID does not match its directory")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != _DATA_FILES:
        raise CheckpointError("Invalid checkpoint file manifest")
    verified: dict[str, bytes] = {}
    for name in sorted(_DATA_FILES):
        description = files[name]
        if not isinstance(description, dict):
            raise CheckpointError(f"Invalid file description: {name}")
        size = description.get("size_bytes")
        digest = description.get("sha256")
        if type(size) is not int or size < 0 or not isinstance(digest, str):
            raise CheckpointError(f"Invalid file integrity fields: {name}")
        data = (path / name).read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise CheckpointError(f"Checkpoint integrity check failed: {name}")
        verified[name] = data
    metadata = _read_json(verified["metadata.json"])
    if not isinstance(metadata, dict):
        raise CheckpointError("Checkpoint metadata must be a JSON object")
    try:
        tensors = load_tensors(verified["tensors.safetensors"])
    except Exception as exc:
        raise CheckpointError("Invalid safetensors data") from exc
    return tensors, metadata


def save_checkpoint(
    root: Path,
    checkpoint_id: str,
    tensors: dict[str, np.ndarray],
    metadata: dict,
) -> Path:
    """Publish a new immutable checkpoint; never overwrite an existing ID.

    An exclusive per-ID lock prevents concurrent publishers from replacing one
    another. An interrupted lock or hidden temporary directory is not a valid
    checkpoint and is intentionally left for explicit inspection after a crash.
    """
    _validate_id(checkpoint_id)
    if not isinstance(metadata, dict):
        raise TypeError("Checkpoint metadata must be a dictionary")
    metadata_bytes = _json_bytes(metadata)
    if not isinstance(tensors, dict) or any(
        not isinstance(name, str) or not isinstance(value, np.ndarray)
        for name, value in tensors.items()
    ):
        raise TypeError("Checkpoint tensors must map strings to NumPy arrays")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / checkpoint_id
    lock = root / f".{checkpoint_id}.lock"
    # lexists includes broken symlinks, which must not be overwritten either.
    if os.path.lexists(target):
        raise FileExistsError(f"Checkpoint already exists: {target}")
    lock_descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary: Path | None = None
    try:
        os.close(lock_descriptor)
        if os.path.lexists(target):
            raise FileExistsError(f"Checkpoint already exists: {target}")
        temporary = Path(tempfile.mkdtemp(prefix=f".{checkpoint_id}.tmp-", dir=root))
        arrays = {
            name: value if value.flags.c_contiguous else np.ascontiguousarray(value)
            for name, value in tensors.items()
        }
        save_file(arrays, temporary / "tensors.safetensors")
        with (temporary / "metadata.json").open("wb") as handle:
            handle.write(metadata_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        with (temporary / "tensors.safetensors").open("rb") as handle:
            os.fsync(handle.fileno())
        files = {}
        for name in sorted(_DATA_FILES):
            data = (temporary / name).read_bytes()
            files[name] = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        atomic_write_json(
            temporary / "manifest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "checkpoint_id": checkpoint_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "files": files,
            },
        )
        _load_verified(temporary, expected_id=checkpoint_id)
        if os.path.lexists(target):
            raise FileExistsError(f"Checkpoint already exists: {target}")
        os.rename(temporary, target)
        temporary = None
        _fsync_directory(root)
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        lock.unlink(missing_ok=True)
    return target


def load_checkpoint(path: Path) -> tuple[dict[str, np.ndarray], dict]:
    """Load only published checkpoints, verifying every data byte before decoding."""
    path = Path(path)
    _validate_id(path.name)
    try:
        return _load_verified(path, expected_id=path.name)
    except OSError as exc:
        raise CheckpointError(f"Unable to read checkpoint: {path}") from exc
