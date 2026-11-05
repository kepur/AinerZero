"""Verify immutable public datasets before a paired prediction experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ainerzero.core.experience import DatasetPartition, TrainingPolicy
from ainerzero.data.trajectory import load_training_trajectory, load_trajectory


def load_pilot_dataset(path: Path, policy: TrainingPolicy) -> tuple[dict, dict, dict]:
    raw = Path(path).read_bytes()
    dataset = json.loads(raw)
    if not isinstance(dataset, dict) or set(dataset) != {"train", "development"}:
        raise ValueError("dataset requires exactly train and development partitions")
    episodes, paths = {}, {}
    ids, worlds = set(), set()
    for partition, maximum in (("train", 32), ("development", 8)):
        entries = dataset[partition]
        if not isinstance(entries, list) or not 1 <= len(entries) <= maximum:
            raise ValueError("dataset partition exceeds the bounded pilot size")
        episodes[partition], paths[partition] = [], []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "public_sha256"}:
                raise ValueError("dataset entry requires path and public_sha256")
            directory = Path(entry["path"])
            if not directory.is_absolute():
                raise ValueError("dataset trajectory paths must be absolute")
            episode = (
                load_training_trajectory(directory, policy)
                if partition == "train"
                else load_trajectory(directory)
            )
            if (
                hashlib.sha256((directory / "public.jsonl").read_bytes()).hexdigest()
                != entry["public_sha256"]
            ):
                raise ValueError("dataset public hash differs from the registered source")
            context = episode.initial.context
            if context.partition is not DatasetPartition(partition):
                raise ValueError("dataset partition does not match trajectory provenance")
            if context.episode_id in ids or context.environment_instance_id in worlds:
                raise ValueError("dataset episodes/worlds must be distinct across partitions")
            if len(episode.transitions) != 128:
                raise ValueError("paired pilot requires complete 128-step episodes")
            ids.add(context.episode_id)
            worlds.add(context.environment_instance_id)
            episodes[partition].append(episode)
            paths[partition].append(directory)
    identity = {
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "public_sha256": {
            name: [item["public_sha256"] for item in entries] for name, entries in dataset.items()
        },
    }
    return paths, episodes, identity
