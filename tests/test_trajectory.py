import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ainerzero.core.contracts import ActionStatus
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    Actor,
    ActorKind,
    DatasetPartition,
    EpisodeIdentity,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
)
from ainerzero.data import trajectory as trajectory_module
from ainerzero.data.trajectory import (
    MAX_FILE_BYTES,
    EpisodeTrajectory,
    TrajectoryError,
    load_training_trajectory,
    load_trajectory,
    replay_trajectory,
    save_trajectory,
)
from ainerzero.environments.c0 import (
    ACTION_SCHEMA_REVISION,
    ENVIRONMENT_REVISION,
    MAX_EPISODE_TICKS,
    C0Environment,
)


def make_trajectory(steps=8, partition=DatasetPartition.TRAIN, stop_reason=None):
    env = C0Environment(47)
    env.reset(93)
    snapshot = env.snapshot()
    context = EpisodeIdentity(
        run_id=uuid4(),
        episode_id=uuid4(),
        partition=partition,
        environment_instance_id=env.instance_id,
        environment_revision=ENVIRONMENT_REVISION,
        action_schema_revision=ACTION_SCHEMA_REVISION,
    )
    actor = Actor(kind=ActorKind.BASELINE, actor_id="fixture", policy_revision="v1")
    before = initial = ObservationV2(
        context=context, step=0, origin=OriginKind.OBSERVED, payload=env.observe()
    )
    transitions = []
    for index in range(steps):
        request = ActionRequestV2(
            context=context, step=index, actor=actor, action=(0, 2, 1, 2, 3)[index % 5]
        )
        after = ObservationV2(
            context=context,
            step=index + 1,
            origin=OriginKind.OBSERVED,
            payload=env.step(request.action),
        )
        result = ActionResultV2(
            context=context,
            step=index,
            request_id=request.id,
            action=request.action,
            origin=OriginKind.OBSERVED,
            status=ActionStatus.ACCEPTED,
            observation_id=after.id,
            submitted_at=before.created_at,
            completed_at=after.created_at,
            elapsed_ns=42,
        )
        transitions.append(
            ExperienceTransition(
                observation=before,
                action_request=request,
                action_result=result,
                next_observation=after,
            )
        )
        before = after
    return (
        EpisodeTrajectory(
            initial=initial,
            transitions=tuple(transitions),
            stop_reason=stop_reason
            or ("episode_limit" if steps == MAX_EPISODE_TICKS else "requested_steps"),
        ),
        snapshot,
        TrainingPolicy(allowed_actors=(actor,)),
    )


def save_fixture(tmp_path, **kwargs):
    trajectory, snapshot, policy = make_trajectory(**kwargs)
    return save_trajectory(tmp_path, trajectory, snapshot), trajectory, policy


def resign(path, name):
    manifest = json.loads((path / "manifest.json").read_text())
    data = (path / name).read_bytes()
    manifest["files"][name] = {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    (path / "manifest.json").write_text(json.dumps(manifest))


def edit_public(path, edit):
    records = [json.loads(line) for line in (path / "public.jsonl").read_text().splitlines()]
    edit(records)
    (path / "public.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    resign(path, "public.jsonl")


@pytest.mark.parametrize("steps", [0, 1, 8, 128])
def test_round_trip_and_replay_preserve_complete_public_experience(tmp_path, steps):
    path, original, policy = save_fixture(tmp_path, steps=steps)
    restored = load_trajectory(path)
    assert restored == original
    assert load_training_trajectory(path, policy) == original
    for left, right in zip(restored.transitions, restored.transitions[1:]):
        assert left.next_observation == right.observation
    assert replay_trajectory(path) == {
        "status": "passed",
        "episode_id": path.name,
        "replayed_steps": steps,
        "stop_reason": original.stop_reason,
        "environment_revision": ENVIRONMENT_REVISION,
    }


def test_public_loader_never_reads_private_contents(tmp_path, monkeypatch):
    path, original, policy = save_fixture(tmp_path)
    real_open = Path.open

    def public_only_open(item, *args, **kwargs):
        if item.name == "private.json":
            raise AssertionError("normal experience loading must not read private truth")
        return real_open(item, *args, **kwargs)

    monkeypatch.setattr(Path, "open", public_only_open)
    assert load_trajectory(path) == original
    assert load_training_trajectory(path, policy) == original
    with pytest.raises(AssertionError, match="private truth"):
        replay_trajectory(path)


def test_hidden_rules_only_appear_in_private_snapshot(tmp_path):
    path, _, _ = save_fixture(tmp_path)
    public = (path / "public.jsonl").read_text()
    private = json.loads((path / "private.json").read_text())
    for field in ("input_cells", "output_cells", "output_sources", "symbol_pairs", "bits"):
        assert f'"{field}"' not in public
        assert field in private
    assert '"seed"' not in public


@pytest.mark.parametrize("partition", list(DatasetPartition))
@pytest.mark.parametrize("steps", [0, 2])
def test_training_gate_rejects_evaluation_and_quarantine_even_when_empty(
    tmp_path, partition, steps
):
    path, original, policy = save_fixture(tmp_path, steps=steps, partition=partition)
    assert load_trajectory(path) == original
    if partition is DatasetPartition.TRAIN:
        assert load_training_trajectory(path, policy) == original
    else:
        with pytest.raises(ValueError, match="Only train partition"):
            load_training_trajectory(path, policy)


def test_training_gate_checks_actor_version_and_revalidates_unknown_policy(tmp_path):
    path, _, policy = save_fixture(tmp_path)
    actor = policy.allowed_actors[0].model_copy(update={"policy_revision": "other-version"})
    with pytest.raises(ValueError, match="actor or policy revision"):
        load_training_trajectory(path, TrainingPolicy(allowed_actors=(actor,)))
    empty_path, _, _ = save_fixture(tmp_path, steps=0)
    forged = policy.model_copy(update={"allowed_actors": (Actor(kind=ActorKind.UNKNOWN),)})
    with pytest.raises(ValueError, match="unknown actors"):
        load_training_trajectory(empty_path, forged)


def test_chain_rejects_replaced_observation_even_with_same_id_and_payload():
    original, _, _ = make_trajectory(2)
    raw = original.model_dump()
    raw["transitions"][1]["observation"]["created_at"] = original.initial.created_at
    with pytest.raises(ValidationError, match="complete shared observation"):
        EpisodeTrajectory.model_validate(raw)


def test_chain_rejects_changed_run_and_reused_action_ids():
    original, _, _ = make_trajectory(2)
    raw = original.model_dump()
    raw["transitions"][1]["action_request"]["context"]["run_id"] = uuid4()
    with pytest.raises(ValidationError, match="cannot cross"):
        EpisodeTrajectory.model_validate(raw)
    raw = original.model_dump()
    duplicate = raw["transitions"][0]["action_request"]["id"]
    raw["transitions"][1]["action_request"]["id"] = duplicate
    raw["transitions"][1]["action_result"]["request_id"] = duplicate
    with pytest.raises(ValidationError, match="globally unique"):
        EpisodeTrajectory.model_validate(raw)


@pytest.mark.parametrize(
    "reason,steps", [("episode_limit", 0), ("requested_steps", 128), ("budget_exhausted", 128)]
)
def test_stop_reason_must_agree_with_episode_limit(reason, steps):
    with pytest.raises(ValidationError, match="128 completed steps"):
        make_trajectory(steps=steps, stop_reason=reason)


def test_budget_exhausted_can_archive_an_incomplete_or_empty_episode(tmp_path):
    for steps in (0, 3):
        path, _, _ = save_fixture(tmp_path, steps=steps, stop_reason="budget_exhausted")
        assert replay_trajectory(path)["replayed_steps"] == steps


def test_initial_snapshot_must_match_step_instance_and_sensor(tmp_path):
    trajectory, snapshot, _ = make_trajectory()
    changed_instance = snapshot.model_copy(update={"instance_id": uuid4()})
    moved = C0Environment.restore(snapshot)
    moved.step(3)
    changed_cursor = snapshot.model_copy(update={"cursor": (snapshot.cursor + 1) % 8})
    for wrong in (changed_instance, moved.snapshot(), changed_cursor):
        with pytest.raises(ValueError, match="Initial private snapshot"):
            save_trajectory(tmp_path, trajectory, wrong)
    assert not list(tmp_path.iterdir())


def test_saving_revalidates_model_copy_bypass(tmp_path):
    trajectory, snapshot, _ = make_trajectory()
    forged = trajectory.model_copy(update={"stop_reason": "episode_limit"})
    with pytest.raises(ValidationError, match="128 completed steps"):
        save_trajectory(tmp_path, forged, snapshot)


def test_save_never_overwrites_existing_id_or_exclusive_lock(tmp_path):
    trajectory, snapshot, _ = make_trajectory()
    path = save_trajectory(tmp_path, trajectory, snapshot)
    originals = {file.name: file.read_bytes() for file in path.iterdir()}
    with pytest.raises(FileExistsError):
        save_trajectory(tmp_path, trajectory, snapshot)
    assert {file.name: file.read_bytes() for file in path.iterdir()} == originals
    second, second_snapshot, _ = make_trajectory()
    lock = tmp_path / f".{second.initial.context.episode_id}.lock"
    lock.touch()
    with pytest.raises(FileExistsError):
        save_trajectory(tmp_path, second, second_snapshot)
    assert lock.exists()


def test_failure_before_publish_leaves_no_valid_episode(tmp_path, monkeypatch):
    trajectory, snapshot, _ = make_trajectory()

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(trajectory_module, "_write_file", fail)
    with pytest.raises(OSError, match="disk failure"):
        save_trajectory(tmp_path, trajectory, snapshot)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["public.jsonl", "private.json"])
def test_integrity_hashes_detect_changed_data_at_the_respective_boundary(tmp_path, name):
    path, original, _ = save_fixture(tmp_path)
    with (path / name).open("ab") as handle:
        handle.write(b" ")
    if name == "private.json":
        assert load_trajectory(path) == original
        operation = replay_trajectory
    else:
        operation = load_trajectory
    with pytest.raises(TrajectoryError, match="integrity check"):
        operation(path)


@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_missing_or_extra_transition_lines_fail_even_with_updated_hash(tmp_path, mode):
    path, _, _ = save_fixture(tmp_path)
    if mode == "missing":
        edit_public(path, lambda records: records.pop())
    else:
        edit_public(path, lambda records: records.append(records[-1]))
    with pytest.raises(TrajectoryError, match="missing or extra transition"):
        load_trajectory(path)


def test_replay_reexecutes_actions_instead_of_trusting_recorded_results(tmp_path):
    path, _, _ = save_fixture(tmp_path, steps=1)

    def change_final(records):
        payload = records[1]["next_observation"]["payload"]
        payload["cursor"] = (payload["cursor"] + 1) % 8

    edit_public(path, change_final)
    assert len(load_trajectory(path).transitions) == 1
    with pytest.raises(TrajectoryError, match="action result differs"):
        replay_trajectory(path)


def test_replay_budget_hook_runs_once_before_each_action_and_can_abort(tmp_path):
    path, _, _ = save_fixture(tmp_path, steps=3)
    calls = []
    replay_trajectory(path, before_step=lambda: calls.append("step"))
    assert calls == ["step"] * 3

    def exhausted():
        raise RuntimeError("budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        replay_trajectory(path, before_step=exhausted)


@pytest.mark.parametrize(
    "field", ["schema_version", "environment_revision", "action_schema_revision"]
)
@pytest.mark.parametrize("change", ["remove", "unsupported"])
def test_manifest_versions_are_explicit_and_supported(tmp_path, field, change):
    path, _, _ = save_fixture(tmp_path)
    manifest = json.loads((path / "manifest.json").read_text())
    if change == "remove":
        manifest.pop(field)
    else:
        manifest[field] = 99 if field == "schema_version" else "future-version"
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        load_trajectory(path)


def test_header_schema_and_private_snapshot_versions_cannot_be_omitted(tmp_path):
    path, _, _ = save_fixture(tmp_path)
    edit_public(path, lambda records: records[0].pop("schema_version"))
    with pytest.raises(ValidationError):
        load_trajectory(path)
    other, _, _ = save_fixture(tmp_path)
    private = json.loads((other / "private.json").read_text())
    private.pop("schema_version")
    (other / "private.json").write_text(json.dumps(private))
    resign(other, "private.json")
    with pytest.raises(ValidationError):
        replay_trajectory(other)


def test_manifest_episode_identity_must_match_directory_and_header(tmp_path):
    path, _, _ = save_fixture(tmp_path)
    renamed = path.with_name(str(uuid4()))
    path.rename(renamed)
    with pytest.raises(TrajectoryError, match="does not match its directory"):
        load_trajectory(renamed)
    path, _, _ = save_fixture(tmp_path)
    edit_public(
        path, lambda records: records[0]["initial"]["context"].update(episode_id=str(uuid4()))
    )
    with pytest.raises(TrajectoryError, match="header does not match"):
        load_trajectory(path)


@pytest.mark.parametrize("filename", ["public.jsonl", "private.json", "manifest.json"])
def test_missing_or_symlinked_files_are_not_valid_artifacts(tmp_path, filename):
    path, _, _ = save_fixture(tmp_path)
    original = path / filename
    outside = tmp_path / "external-data"
    original.rename(outside)
    with pytest.raises(TrajectoryError, match="missing or unexpected files"):
        load_trajectory(path)
    original.symlink_to(outside)
    with pytest.raises(TrajectoryError, match="regular file"):
        load_trajectory(path)


def test_unexpected_files_and_symlinked_directories_are_rejected(tmp_path):
    path, _, _ = save_fixture(tmp_path)
    (path / "extra.json").write_text("{}")
    with pytest.raises(TrajectoryError, match="missing or unexpected files"):
        load_trajectory(path)
    other, _, _ = save_fixture(tmp_path)
    symlink = tmp_path / str(uuid4())
    symlink.symlink_to(other, target_is_directory=True)
    with pytest.raises(TrajectoryError, match="not a symlink"):
        load_trajectory(symlink)


def test_bounded_reads_and_duplicate_json_keys_are_rejected(tmp_path):
    path, _, _ = save_fixture(tmp_path)
    (path / "manifest.json").write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(TrajectoryError, match="size limit"):
        load_trajectory(path)
    other, _, _ = save_fixture(tmp_path)
    manifest = (other / "manifest.json").read_text()
    (other / "manifest.json").write_text('{"schema_version":1,' + manifest[1:])
    with pytest.raises(TrajectoryError, match="Duplicate JSON key"):
        load_trajectory(other)
