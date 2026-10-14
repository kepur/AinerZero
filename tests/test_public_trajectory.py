"""Explicit two-file public mirrors; no environment action or private reads."""

import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from ainerzero.core.experience import TrainingPolicy
from ainerzero.data.trajectory import (
    TrajectoryError,
    load_public_trajectory,
    load_training_trajectory,
    load_trajectory,
    replay_trajectory,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "c0_spacetime_v1"
EPISODES = [
    FIXTURE_ROOT / "development" / "242b7060-4a2c-4ca9-aa46-e4bbc59f4786",
    FIXTURE_ROOT / "train" / "2d457a1e-c746-48ae-8adb-59b47929d69e",
]


def copy_public(tmp_path, index=0):
    source = EPISODES[index]
    assert source.is_dir(), f"required public fixture is missing: {source}"
    return Path(shutil.copytree(source, tmp_path / source.name))


def resign_public(path, records):
    data = "".join(json.dumps(row) + "\n" for row in records).encode()
    (path / "public.jsonl").write_bytes(data)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["files"]["public.jsonl"] = {
        "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    (path / "manifest.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize("path", EPISODES, ids=lambda path: path.parent.name)
def test_public_mirror_preserves_original_manifest_profile_without_private(path, monkeypatch):
    real_open = Path.open

    def reject_private(item, *args, **kwargs):
        assert item.name != "private.json", "public mirrors never open private data"
        return real_open(item, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_private)
    trajectory = load_public_trajectory(path)
    assert str(trajectory.initial.context.episode_id) == path.name
    assert str(trajectory.initial.context.partition) == path.parent.name
    manifest = json.loads((path / "manifest.json").read_text())
    assert set(manifest["files"]) == {"public.jsonl", "private.json"}
    assert len(trajectory.transitions) == manifest["transition_count"]
    assert not (path / "private.json").exists()


@pytest.mark.parametrize("consumer", [load_trajectory, load_training_trajectory, replay_trajectory])
def test_public_profile_is_not_automatically_admitted_to_full_training_or_replay(consumer, monkeypatch):
    path = EPISODES[1]
    real_open = Path.open

    def reject_private(item, *args, **kwargs):
        assert item.name != "private.json"
        return real_open(item, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_private)
    if consumer is load_training_trajectory:
        public = load_public_trajectory(path)
        policy = TrainingPolicy(allowed_actors=(public.transitions[0].action_request.actor,))
        def operation():
            return consumer(path, policy)
    else:
        def operation():
            return consumer(path)
    with pytest.raises(TrajectoryError, match="missing or unexpected"):
        operation()


@pytest.mark.parametrize("name", ["public.jsonl", "manifest.json"])
def test_public_profile_rejects_missing_files(tmp_path, name):
    path = copy_public(tmp_path)
    (path / name).unlink()
    with pytest.raises(TrajectoryError, match="missing or unexpected"):
        load_public_trajectory(path)


def test_public_profile_rejects_extra_files_and_private_named_entry(tmp_path):
    path = copy_public(tmp_path)
    (path / "unexpected.json").write_text("{}")
    with pytest.raises(TrajectoryError, match="missing or unexpected"):
        load_public_trajectory(path)
    (path / "unexpected.json").unlink()
    (path / "private.json").mkdir()  # unexpected directory, not a fabricated private snapshot
    with pytest.raises(TrajectoryError, match="missing or unexpected"):
        load_public_trajectory(path)


@pytest.mark.parametrize("name", ["public.jsonl", "manifest.json"])
def test_public_profile_rejects_symlinked_entries(tmp_path, name):
    path = copy_public(tmp_path)
    external = tmp_path / "external"
    (path / name).rename(external)
    (path / name).symlink_to(external)
    with pytest.raises(TrajectoryError, match="regular file"):
        load_public_trajectory(path)


def test_public_profile_rejects_symlinked_directory_and_ancestor(tmp_path):
    path = copy_public(tmp_path / "data")
    alias = tmp_path / path.name
    alias.symlink_to(path, target_is_directory=True)
    with pytest.raises(TrajectoryError, match="symlink"):
        load_public_trajectory(alias)
    parent_alias = tmp_path / "alias"
    parent_alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(TrajectoryError, match="symlink"):
        load_public_trajectory(parent_alias / path.name)


def test_public_profile_rejects_tampered_content_before_parsing(tmp_path):
    path = copy_public(tmp_path)
    with (path / "public.jsonl").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(TrajectoryError, match="integrity check"):
        load_public_trajectory(path)


@pytest.mark.parametrize("violation", ["header", "missing_line", "chain", "partition"])
def test_public_profile_retains_header_and_chain_checks_even_when_resigned(tmp_path, violation):
    path = copy_public(tmp_path)
    records = [json.loads(line) for line in (path / "public.jsonl").read_text().splitlines()]
    if violation == "header":
        records[0]["initial"]["context"]["episode_id"] = str(uuid4())
    elif violation == "missing_line":
        records.pop()
    elif violation == "chain":
        records[2]["observation"]["created_at"] = records[0]["initial"]["created_at"]
    else:
        records[2]["next_observation"]["context"]["partition"] = "train"
    resign_public(path, records)
    with pytest.raises(ValueError):
        load_public_trajectory(path)


def test_public_profile_still_requires_the_original_manifest_file_declarations(tmp_path):
    path = copy_public(tmp_path)
    manifest = json.loads((path / "manifest.json").read_text())
    del manifest["files"]["private.json"]
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="exactly public.jsonl and private.json"):
        load_public_trajectory(path)


def test_public_profile_rejects_noncanonical_and_wrong_episode_directory(tmp_path):
    path = copy_public(tmp_path)
    renamed = path.with_name(str(uuid4()))
    path.rename(renamed)
    with pytest.raises(TrajectoryError, match="does not match its directory"):
        load_public_trajectory(renamed)
    uppercase = renamed.with_name(EPISODES[0].name.upper())
    renamed.rename(uppercase)
    with pytest.raises(TrajectoryError, match="canonical"):
        load_public_trajectory(uppercase)
