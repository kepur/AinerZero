"""Small, budgeted C0 collection and replay checks; no learner or goal solver."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from time import monotonic, monotonic_ns
from uuid import UUID, uuid4

import numpy as np

from ainerzero.core.contracts import ActionStatus, utc_now
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
)
from ainerzero.data.trajectory import (
    EpisodeTrajectory,
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
from ainerzero.runtime.checkpoints import atomic_write_json
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore

RANDOM_ACTOR = Actor(
    kind=ActorKind.BASELINE, actor_id="uniform_random", policy_revision="pcg64_c0_v1"
)


def collection_manifest(pilot: dict) -> dict:
    """A separate ten-minute engineering check, not the first learning experiment."""
    manifest = copy.deepcopy(pilot)
    manifest["purpose"] = "c0_collection_check_v1"
    for section, ceilings in (
        (
            "budget",
            dict(
                max_environment_steps=128,
                max_optimizer_steps=1,
                max_model_transitions=1,
                max_wall_seconds=30,
            ),
        ),
        (
            "experiment_budget",
            dict(
                max_model_runs=1,
                max_environment_steps=1024,
                max_optimizer_steps=1,
                max_model_transitions=1,
                max_wall_seconds=600,
                max_calibration_seconds=30,
            ),
        ),
    ):
        for key, ceiling in ceilings.items():
            manifest[section][key] = min(manifest[section][key], ceiling)
    # Positive schema fields are ceilings, not permission to train: only
    # auxiliary runs are dispatched here and no model operations are present.
    return manifest


def _seed(seed: int, partition: DatasetPartition, stream: str) -> int:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("seed must be an integer in [0, 2**64)")
    payload = f"c0_collection_v1:{partition.value}:{seed}:{stream}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _new_run(store: RunStore, experiment_id: str, metadata: dict):
    manifest = store.get_experiment(experiment_id).manifest
    return store.create_run(
        {"budget": manifest["budget"], "c0_check": metadata},
        str(uuid4()),
        run_id=str(uuid4()),
        experiment_id=experiment_id,
        role="auxiliary",
    )


def _reserve(store: RunStore, run_id: str, steps: int, *, partial: bool) -> tuple[int, float]:
    """Reserve a complete bounded batch before dispatch; never refund on failure."""
    run = store.get_run(run_id)
    remaining = run.remaining
    experiment = store.get_experiment(run.experiment_id)
    count = min(steps, remaining["environment_steps"], experiment.remaining["environment_steps"])
    if count < steps and not partial:
        raise ValueError("remaining budget cannot cover the complete replay")
    window = min(
        10.0,
        remaining["wall_seconds"] / 2,
        remaining["daily_active_seconds"] / 2,
        experiment.remaining["wall_seconds"] / 2,
    )
    if window <= 0 or count <= 0:
        raise ValueError("no budget remains for this C0 check")
    store.consume(run_id, environment_steps=count, active_seconds=window)
    return count, monotonic() + window


def _fail_if_unfinished(store: RunStore, run_id: str) -> None:
    if store.get_run(run_id).state not in TERMINAL_STATES:
        store.transition(run_id, "failed", reason="c0_check_interrupted_or_failed")


def collect_c0(
    store: RunStore,
    experiment_id: str,
    *,
    seed: int,
    partition: DatasetPartition,
    steps: int,
    output_root: Path,
) -> dict:
    """Collect one public episode with a fixed random baseline, never a student.

    This trusted collector assigns partition/identities. World and policy RNG
    streams are independently derived and disjoint across train/development.
    The final evaluation protocol is intentionally not exposed by this entry.
    """
    if type(steps) is not int or not 1 <= steps <= MAX_EPISODE_TICKS:
        raise ValueError("steps must be an integer in [1, 128]")
    partition = DatasetPartition(partition)
    if partition not in {DatasetPartition.TRAIN, DatasetPartition.DEVELOPMENT}:
        raise ValueError("C0 engineering collection only supports train/development")
    world_seed = _seed(seed, partition, "world")
    reset_seed = _seed(seed, partition, "reset")
    policy_seed = _seed(seed, partition, "policy")
    run = _new_run(store, experiment_id, dict(seed=seed, partition=partition.value, steps=steps))
    started = monotonic()
    try:
        store.transition(run.run_id, "initializing")
        store.transition(run.run_id, "collecting")
        allowed, deadline = _reserve(store, run.run_id, steps, partial=True)
        env = C0Environment(world_seed)
        payload = env.reset(reset_seed)
        snapshot = env.snapshot()
        context = EpisodeIdentity(
            run_id=UUID(run.run_id),
            episode_id=uuid4(),
            partition=partition,
            environment_instance_id=env.instance_id,
            environment_revision=ENVIRONMENT_REVISION,
            action_schema_revision=ACTION_SCHEMA_REVISION,
        )
        initial = ObservationV2(
            context=context, step=0, origin=OriginKind.OBSERVED, payload=payload
        )
        before = initial
        transitions = []
        policy = np.random.Generator(np.random.PCG64(policy_seed))
        for _ in range(allowed):
            if monotonic() >= deadline:
                break
            request = ActionRequestV2(
                context=context,
                step=env.tick,
                action=int(policy.integers(0, 4)),
                actor=RANDOM_ACTOR,
            )
            submitted = utc_now()
            start_ns = monotonic_ns()
            payload = env.step(request.action)
            elapsed_ns = monotonic_ns() - start_ns
            after = ObservationV2(
                context=context,
                step=env.tick,
                origin=OriginKind.OBSERVED,
                payload=payload,
            )
            result = ActionResultV2(
                context=context,
                step=request.step,
                origin=OriginKind.OBSERVED,
                request_id=request.id,
                action=request.action,
                status=ActionStatus.ACCEPTED,
                observation_id=after.id,
                submitted_at=submitted,
                completed_at=utc_now(),
                elapsed_ns=elapsed_ns,
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
        reason = (
            "episode_limit"
            if env.done
            else "requested_steps"
            if len(transitions) == steps
            else "budget_exhausted"
        )
        trajectory = EpisodeTrajectory(
            initial=initial, transitions=tuple(transitions), stop_reason=reason
        )
        path = save_trajectory(Path(output_root), trajectory, snapshot)
        store.transition(run.run_id, "completed", reason=reason)
        report = {
            "status": "collected",
            "learning_status": "not_started",
            "experiment_id": experiment_id,
            "run_id": run.run_id,
            "episode_id": str(context.episode_id),
            "partition": partition.value,
            "actor": RANDOM_ACTOR.model_dump(mode="json"),
            "requested_steps": steps,
            "reserved_environment_steps": allowed,
            "actual_environment_steps": len(transitions),
            "stop_reason": reason,
            "elapsed_seconds": monotonic() - started,
            "trajectory_path": str(path.resolve()),
            "symbol_changes": sum(
                t.observation.payload.symbols != t.next_observation.payload.symbols
                for t in transitions
            ),
            "cursor_changes": sum(
                t.observation.payload.cursor != t.next_observation.payload.cursor
                for t in transitions
            ),
        }
        atomic_write_json(Path(output_root) / f"{run.run_id}.json", report)
        return report
    finally:
        _fail_if_unfinished(store, run.run_id)


def replay_c0(store: RunStore, path: Path) -> dict:
    """Audit the recorded episode, charging re-execution to its original package."""
    trajectory = load_trajectory(path)
    source = store.get_run(str(trajectory.initial.context.run_id))
    if source.experiment_id is None:
        raise ValueError("source trajectory must belong to an experiment")
    run = _new_run(store, source.experiment_id, {"replay_of_run": source.run_id})
    started = monotonic()
    try:
        store.transition(run.run_id, "initializing")
        store.transition(run.run_id, "validating")
        count = len(trajectory.transitions)
        # Empty budget-stopped episodes still reserve time for initial verification.
        if count:
            _, deadline = _reserve(store, run.run_id, count, partial=False)
        else:
            store.consume(run.run_id, active_seconds=0.01)
            deadline = monotonic() + 0.01

        def check_deadline():
            if monotonic() >= deadline:
                raise TimeoutError("C0 replay exceeded its reserved time window")

        report = replay_trajectory(path, before_step=check_deadline)
        store.transition(run.run_id, "completed", reason="replay_verified")
        return {
            **report,
            "verification_run_id": run.run_id,
            "source_run_id": source.run_id,
            "experiment_id": source.experiment_id,
            "reserved_environment_steps": count,
            "elapsed_seconds": monotonic() - started,
        }
    finally:
        _fail_if_unfinished(store, run.run_id)
