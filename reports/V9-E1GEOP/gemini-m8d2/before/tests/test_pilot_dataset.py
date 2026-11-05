import hashlib
import json

import pytest
from test_sequences import make_episode

from ainerzero.core.experience import DatasetPartition, TrainingPolicy
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.data.trajectory import save_trajectory


@pytest.fixture
def dataset(tmp_path):
    entries = {}
    for seed, name in enumerate(("train", "development")):
        episode, snapshot, policy = make_episode(
            steps=128, seed=seed + 20, partition=DatasetPartition(name)
        )
        directory = save_trajectory(tmp_path / "episodes", episode, snapshot)
        entries[name] = [
            {
                "path": str(directory),
                "public_sha256": hashlib.sha256(
                    (directory / "public.jsonl").read_bytes()
                ).hexdigest(),
            }
        ]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(entries))
    return path, policy, entries


def test_reuse_checks_hashes_and_partitions_without_reading_private_data(dataset):
    path, policy, entries = dataset
    for partition in entries.values():
        from pathlib import Path

        (Path(partition[0]["path"]) / "private.json").write_text("unreadable private truth")
    paths, episodes, identity = load_pilot_dataset(path, policy)
    assert len(paths["train"]) == len(episodes["development"]) == 1
    assert identity["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_reuse_rejects_tampered_registered_hash(dataset):
    path, policy, entries = dataset
    entries["train"][0]["public_sha256"] = "0" * 64
    path.write_text(json.dumps(entries))
    with pytest.raises(ValueError, match="hash"):
        load_pilot_dataset(path, policy)


def test_reuse_cannot_move_development_into_training(dataset):
    path, policy, entries = dataset
    entries["train"] = entries["development"]
    path.write_text(json.dumps(entries))
    with pytest.raises(ValueError):
        load_pilot_dataset(path, policy)


def test_reuse_still_requires_actor_whitelist(dataset):
    path, _, _ = dataset
    with pytest.raises(ValueError):
        load_pilot_dataset(path, TrainingPolicy())


def test_reuse_rejects_repeated_world(dataset):
    path, policy, entries = dataset
    entries["train"] *= 2
    path.write_text(json.dumps(entries))
    with pytest.raises(ValueError, match="distinct"):
        load_pilot_dataset(path, policy)
