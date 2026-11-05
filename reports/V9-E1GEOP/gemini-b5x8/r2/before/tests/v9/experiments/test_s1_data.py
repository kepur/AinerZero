"""S1 dataset identity / partition guard / feature-view tests (pure CPU)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import data, spec
from ainerzero.v9.interfaces.validation import (
    FutureFieldRejected,
    TruthFieldRejected,
    validate_observation_payload,
)

from s1_testkit import build_payload, make_plan, write_staging


def test_frozen_plan_is_within_registered_caps():
    plan = data.build_plan()
    assert plan["train"]["worlds"] == spec.DATA_CAPS["train_worlds_max"] == 2_000
    assert plan["development"]["worlds"] == spec.DATA_CAPS["development_worlds_max"] == 200
    assert plan["train"]["rounds_per_world"] == 1
    assert plan["partitions"] == ["train", "development"]
    assert plan["final_partition"] == "not_generated_not_read"
    assert data.plan_problems(plan) == []
    assert data.build_plan() == plan  # deterministic enumeration


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda plan: plan["train"].update({"worlds": 2_001}), "train worlds"),
        (lambda plan: plan["development"].update({"worlds": 201}), "development worlds"),
        (lambda plan: plan["train"].update({"rounds_per_world": 5}), "rounds per world"),
        (lambda plan: plan.update({"partitions": ["train", "development", "final"]}), "final"),
        (lambda plan: plan.update({"final_partition": "generated"}), "final_partition"),
    ],
)
def test_plan_rejects_oversized_or_sealed_plans(mutate, needle):
    plan = make_plan()
    mutate(plan)
    problems = data.plan_problems(plan)
    assert any(needle in problem for problem in problems), problems
    with pytest.raises(data.DatasetError):
        data.validate_plan(plan)


def test_consumer_gate_rejects_leaked_fields():
    payload = build_payload(seq=1)
    validate_observation_payload(payload)  # positive control
    for key, error in (("entity_id", TruthFieldRejected), ("future_position", FutureFieldRejected)):
        broken = json.loads(json.dumps(payload))
        broken["observation"]["leaked_" + key] = 1
        broken[key] = 1
        with pytest.raises(error):
            validate_observation_payload(broken)


def test_dataset_roundtrip_views_and_shapes(synthetic_dataset):
    manifest, dataset_dir, plan = synthetic_dataset
    assert manifest["counts"]["train_worlds"] == plan["train"]["worlds"]
    verified = data.verify_dataset(dataset_dir)
    assert verified["dataset_digest"] == manifest["dataset_digest"]
    identity = data.dataset_identity(manifest)
    assert identity["plan"]["final_partition"] == "not_generated_not_read"
    assert len(identity["dataset_digest"]) == 64
    train = data.load_training_episodes(dataset_dir, "train")
    development = data.load_training_episodes(dataset_dir, "development")
    assert len(train) == plan["train"]["worlds"]
    assert len(development) == plan["development"]["worlds"]
    assert all(len(episode.payloads) == 4 for episode in train)
    windows = data.build_windows(train)
    assert windows["obs"].shape == (8, spec.TRAIN_COMMON["sequence_steps"] + 1, data.FEATURE_DIM)
    assert windows["targets"].shape == (8, spec.TRAIN_COMMON["sequence_steps"], data.TARGET_DIM)
    assert windows["actions"].shape == (8, spec.TRAIN_COMMON["sequence_steps"], 4)
    assert windows["det_xy"].shape == (8, 3, data.K, 2)
    assert windows["det_present"].shape == (8, 3, data.K)
    batch = data.fixed_batch(windows, 4, seed=0)
    assert batch["obs"].shape == (4, 3, data.FEATURE_DIM)
    truth = data.load_truth_view(dataset_dir, "development")
    assert len(truth) == plan["development"]["worlds"]
    poses = data.truth_pose_sequence(truth[0])
    assert poses.shape == (4, 4)


def test_training_view_is_payload_only_and_has_no_truth(synthetic_dataset):
    _, dataset_dir, _ = synthetic_dataset
    for episode in data.load_training_episodes(dataset_dir, "train"):
        for payload in episode.payloads:
            assert set(payload) == set(
                (
                    "time",
                    "episode_start",
                    "observation",
                    "pose_sensor_if_allowed",
                    "visibility",
                    "sensor_noise",
                    "last_action_result",
                    "task_instruction",
                )
            )
            flat = json.dumps(payload)
            for forbidden in ("entity_id", "world_id", "ground_truth", "future_", "handle_to_entity"):
                assert forbidden not in flat


def test_final_partition_is_sealed_everywhere(synthetic_dataset):
    _, dataset_dir, _ = synthetic_dataset
    with pytest.raises(data.FinalPartitionSealed):
        data.load_training_episodes(dataset_dir, "final")
    with pytest.raises(data.FinalPartitionSealed):
        data.load_truth_view(dataset_dir, "final")
    with pytest.raises(data.FinalPartitionSealed):
        data.require_partition("final")
    with pytest.raises(data.DatasetError):
        data.require_partition("quarantine")
    assert not (dataset_dir / "packets" / "final.jsonl").exists()
    assert not (dataset_dir / "truth" / "final.jsonl").exists()


def test_dataset_tamper_control(synthetic_dataset):
    _, dataset_dir, _ = synthetic_dataset
    (dataset_dir / "packets" / "train.jsonl").write_text(
        '{"episode_id":"x","partition":"train","seq":0,"payload":{}}\n', encoding="utf-8"
    )
    with pytest.raises(data.DatasetError):
        data.verify_dataset(dataset_dir)
    manifest = data.load_manifest(dataset_dir)
    manifest["counts"]["train_packets"] += 1
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    with pytest.raises(data.DatasetError):
        data.verify_dataset(dataset_dir, expected_digest=manifest["dataset_digest"])


def test_finalize_rejects_broken_sequencing(tmp_path):
    plan = make_plan()
    staging = tmp_path / "staging"
    write_staging(staging, plan=plan)
    packets = staging / "packets" / "train.jsonl"
    rows = [json.loads(line) for line in packets.read_text(encoding="utf-8").splitlines()]
    rows[1]["seq"] = 5
    packets.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    with pytest.raises(data.DatasetError):
        data.finalize_dataset(
            staging,
            tmp_path / "dataset-broken",
            plan=plan,
            generation_seconds=1.0,
            generation_command=["synthetic-producer"],
        )


def test_dataset_digest_is_deterministic(tmp_path):
    plan = make_plan()
    digests = []
    for index in range(2):
        staging = tmp_path / f"staging-{index}"
        write_staging(staging, plan=plan)
        manifest = data.finalize_dataset(
            staging,
            tmp_path / f"dataset-{index}",
            plan=plan,
            generation_seconds=12.5,
            generation_command=["synthetic-producer"],
        )
        digests.append(manifest["dataset_digest"])
    assert digests[0] == digests[1]


def test_truth_geometry_helpers(synthetic_dataset):
    _, dataset_dir, _ = synthetic_dataset
    episode = data.load_truth_view(dataset_dir, "development")[0]
    cells = data.truth_visited_cells(episode)
    assert cells == [(0, 0), (1, 0), (2, 0), (3, 0)]
    adjacency = data.truth_free_adjacency(episode)
    assert ((0, 0), (1, 0)) in adjacency or ((1, 0), (0, 0)) in adjacency
    assert len(adjacency) == 3
