"""Immutable C0 trajectories with separate public experience and audit truth.

The normal loader never reads the private snapshot. Only the explicit replay
auditor restores it. Hashes detect accidental corruption, not a dishonest
producer who replaces both data and its manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ainerzero.core.contracts import Contract
from ainerzero.core.experience import (
    DatasetPartition,
    Digest,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
    admit_training,
)
from ainerzero.environments.c0 import (
    ACTION_SCHEMA_REVISION,
    ENVIRONMENT_REVISION,
    MAX_EPISODE_TICKS,
    C0Environment,
    C0Snapshot,
)

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 4 * 1024 * 1024
_DATA_FILES = {"public.jsonl", "private.json"}
_ALL_FILES = _DATA_FILES | {"manifest.json"}
StopReason = Literal["requested_steps", "episode_limit", "budget_exhausted"]
StepCount = Annotated[int, Field(strict=True, ge=0, le=MAX_EPISODE_TICKS)]
SchemaVersion = Annotated[int, Field(strict=True, ge=SCHEMA_VERSION, le=SCHEMA_VERSION)]


class TrajectoryError(ValueError):
    """An artifact is incomplete, corrupt, or incompatible with C0 replay."""


class EpisodeTrajectory(Contract):
    initial: ObservationV2
    transitions: Annotated[tuple[ExperienceTransition, ...], Field(max_length=MAX_EPISODE_TICKS)]
    stop_reason: StopReason

    @model_validator(mode="after")
    def complete_chain(self) -> Self:
        if self.initial.step != 0:
            raise ValueError("trajectory must start at step 0")
        context = self.initial.context
        if (
            context.environment_revision != ENVIRONMENT_REVISION
            or context.action_schema_revision != ACTION_SCHEMA_REVISION
            or context.environment_instance_id is None
        ):
            raise ValueError("trajectory requires the supported C0 environment and action versions")
        if self.initial.origin is not OriginKind.OBSERVED:
            raise ValueError("C0 trajectories require observed evidence")
        previous = self.initial
        seen = {previous.id}
        for transition in self.transitions:
            if transition.observation != previous:
                raise ValueError("trajectory must preserve each complete shared observation")
            if transition.observation.context != context:
                raise ValueError("trajectory cannot cross episode contexts")
            for record in (
                transition.action_request,
                transition.action_result,
                transition.next_observation,
            ):
                if record.id in seen:
                    raise ValueError("trajectory record IDs must be globally unique")
                seen.add(record.id)
            if (
                transition.action_result.origin is not OriginKind.OBSERVED
                or transition.next_observation.origin is not OriginKind.OBSERVED
            ):
                raise ValueError("C0 trajectories require observed evidence")
            previous = transition.next_observation
        at_limit = len(self.transitions) == MAX_EPISODE_TICKS
        if (self.stop_reason == "episode_limit") != at_limit:
            raise ValueError("episode_limit must describe exactly 128 completed steps")
        return self


class _Header(Contract):
    schema_version: SchemaVersion
    kind: Literal["trajectory_header"]
    initial: ObservationV2
    stop_reason: StopReason
    transition_count: StepCount


class _FileDescription(Contract):
    size_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_FILE_BYTES)]
    sha256: Digest


class _Manifest(Contract):
    schema_version: SchemaVersion
    episode_id: UUID
    transition_count: StepCount
    environment_revision: Literal[ENVIRONMENT_REVISION]
    action_schema_revision: Literal[ACTION_SCHEMA_REVISION]
    files: dict[str, _FileDescription]

    @model_validator(mode="after")
    def exact_files(self) -> Self:
        if set(self.files) != _DATA_FILES:
            raise ValueError("manifest must describe exactly public.jsonl and private.json")
        return self


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise TrajectoryError(f"Non-finite JSON value: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrajectoryError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(data: bytes) -> Any:
    try:
        return json.loads(data, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrajectoryError("Invalid trajectory JSON") from exc


def _bounded_read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise TrajectoryError(f"Trajectory entry must be a regular file: {path.name}")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise TrajectoryError(f"Trajectory file exceeds size limit: {path.name}")
    return data


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path: Path, data: bytes) -> None:
    if not 0 < len(data) <= MAX_FILE_BYTES:
        raise TrajectoryError(f"Invalid trajectory file size: {path.name}")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _load_manifest(path: Path, expected_id: UUID) -> _Manifest:
    if path.is_symlink() or not path.is_dir():
        raise TrajectoryError("Trajectory must be a complete directory, not a symlink")
    if {entry.name for entry in path.iterdir()} != _ALL_FILES:
        raise TrajectoryError("Trajectory contains missing or unexpected files")
    for name in _ALL_FILES:
        item = path / name
        if item.is_symlink() or not item.is_file():
            raise TrajectoryError(f"Trajectory entry must be a regular file: {name}")
    manifest = _Manifest.model_validate(_read_json(_bounded_read(path / "manifest.json")))
    if manifest.episode_id != expected_id:
        raise TrajectoryError("Trajectory episode ID does not match its directory")
    return manifest


def _verified_file(path: Path, name: str, manifest: _Manifest) -> bytes:
    data = _bounded_read(path / name)
    description = manifest.files[name]
    if (
        len(data) != description.size_bytes
        or hashlib.sha256(data).hexdigest() != description.sha256
    ):
        raise TrajectoryError(f"Trajectory integrity check failed: {name}")
    return data


def _load_public(path: Path, manifest: _Manifest) -> EpisodeTrajectory:
    data = _verified_file(path, "public.jsonl", manifest)
    lines = data.splitlines()
    if len(lines) != manifest.transition_count + 1:
        raise TrajectoryError("Trajectory has missing or extra transition lines")
    header = _Header.model_validate(_read_json(lines[0]))
    if (
        header.transition_count != manifest.transition_count
        or header.initial.context.episode_id != manifest.episode_id
    ):
        raise TrajectoryError("Trajectory header does not match manifest")
    return EpisodeTrajectory(
        initial=header.initial,
        transitions=tuple(
            ExperienceTransition.model_validate(_read_json(line)) for line in lines[1:]
        ),
        stop_reason=header.stop_reason,
    )


def _restore_initial(snapshot: C0Snapshot, initial: ObservationV2) -> C0Environment:
    snapshot = C0Snapshot.model_validate(snapshot)
    environment = C0Environment.restore(snapshot)
    if (
        environment.tick != 0
        or environment.instance_id != initial.context.environment_instance_id
        or environment.observe() != initial.payload
    ):
        raise TrajectoryError("Initial private snapshot does not match the public observation")
    return environment


def save_trajectory(root: Path, trajectory: EpisodeTrajectory, snapshot: C0Snapshot) -> Path:
    """Atomically publish one new episode; an existing ID is never overwritten."""
    trajectory = EpisodeTrajectory.model_validate(trajectory)
    snapshot = C0Snapshot.model_validate(snapshot)
    _restore_initial(snapshot, trajectory.initial)
    episode_id = trajectory.initial.context.episode_id
    header = _Header(
        schema_version=SCHEMA_VERSION,
        kind="trajectory_header",
        initial=trajectory.initial,
        stop_reason=trajectory.stop_reason,
        transition_count=len(trajectory.transitions),
    )
    public = _json_bytes(header.model_dump(mode="json")) + b"".join(
        _json_bytes(transition.model_dump(mode="json")) for transition in trajectory.transitions
    )
    private = _json_bytes(snapshot.model_dump(mode="json"))
    payloads = {"public.jsonl": public, "private.json": private}
    manifest = _Manifest(
        schema_version=SCHEMA_VERSION,
        episode_id=episode_id,
        environment_revision=ENVIRONMENT_REVISION,
        action_schema_revision=ACTION_SCHEMA_REVISION,
        transition_count=len(trajectory.transitions),
        files={
            name: _FileDescription(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            for name, data in payloads.items()
        },
    )
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / str(episode_id)
    lock = root / f".{episode_id}.lock"
    if os.path.lexists(target):
        raise FileExistsError(f"Trajectory already exists: {target}")
    lock_descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary: Path | None = None
    try:
        os.close(lock_descriptor)
        if os.path.lexists(target):
            raise FileExistsError(f"Trajectory already exists: {target}")
        temporary = Path(tempfile.mkdtemp(prefix=f".{episode_id}.tmp-", dir=root))
        for name, data in payloads.items():
            _write_file(temporary / name, data)
        _write_file(temporary / "manifest.json", _json_bytes(manifest.model_dump(mode="json")))
        loaded_manifest = _load_manifest(temporary, episode_id)
        _load_public(temporary, loaded_manifest)
        _verified_file(temporary, "private.json", loaded_manifest)
        _fsync_directory(temporary)
        if os.path.lexists(target):
            raise FileExistsError(f"Trajectory already exists: {target}")
        os.rename(temporary, target)
        temporary = None
        _fsync_directory(root)
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        lock.unlink(missing_ok=True)
    return target


def load_trajectory(path: Path) -> EpisodeTrajectory:
    """Verify and read public experience; never open private snapshot contents."""
    path = Path(path)
    try:
        episode_id = UUID(path.name)
        if str(episode_id) != path.name:
            raise TrajectoryError("Trajectory directory must use its canonical episode UUID")
        manifest = _load_manifest(path, episode_id)
        return _load_public(path, manifest)
    except OSError as exc:
        raise TrajectoryError(f"Unable to read trajectory: {path}") from exc


def load_training_trajectory(path: Path, policy: TrainingPolicy) -> EpisodeTrajectory:
    """Admit public facts only, using the caller's explicit actor/revision policy."""
    trajectory = load_trajectory(path)
    policy = TrainingPolicy.model_validate(policy)
    if trajectory.initial.context.partition is not DatasetPartition.TRAIN:
        raise TrajectoryError("Only train partition trajectories are admitted")
    for transition in trajectory.transitions:
        admit_training(transition, policy)
    return trajectory


def replay_trajectory(
    path: Path, *, before_step: Callable[[], None] | None = None
) -> dict[str, str | int]:
    """Re-execute recorded actions from audit truth, comparing every public result."""
    path = Path(path)
    trajectory = load_trajectory(path)
    try:
        manifest = _load_manifest(path, trajectory.initial.context.episode_id)
        snapshot = C0Snapshot.model_validate(
            _read_json(_verified_file(path, "private.json", manifest))
        )
        environment = _restore_initial(snapshot, trajectory.initial)
        for transition in trajectory.transitions:
            if (
                environment.tick != transition.observation.step
                or environment.observe() != transition.observation.payload
            ):
                raise TrajectoryError("Replay preceding observation differs from recorded state")
            if before_step is not None:
                before_step()
            actual = environment.step(transition.action_request.action)
            if (
                environment.tick != transition.next_observation.step
                or actual != transition.next_observation.payload
            ):
                raise TrajectoryError("Replay action result differs from recorded observation")
        if environment.done != (trajectory.stop_reason == "episode_limit"):
            raise TrajectoryError("Replay termination differs from the recorded stop reason")
    except OSError as exc:
        raise TrajectoryError(f"Unable to replay trajectory: {path}") from exc
    return {
        "status": "passed",
        "episode_id": str(trajectory.initial.context.episode_id),
        "replayed_steps": len(trajectory.transitions),
        "stop_reason": trajectory.stop_reason,
        "environment_revision": ENVIRONMENT_REVISION,
    }
