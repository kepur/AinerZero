"""Contract: WorldBrainAdapter (r5 §3).

Positive: ``step`` consumes only the payload and returns a BeliefSummary that
mirrors the packet's own time; ``propose`` emits SkillProposal records with TTL
and digest-pinned evidence; ``reset`` starts an episode.

Counter-examples: whole envelope / snapshot / forbidden key handed to ``step``,
``t_ticks`` moving backwards inside an episode, world truth in ``reset``
metadata, world identity keys inside a proposal goal.
"""

from __future__ import annotations

import json
import re

import pytest

from ainerzero.v9.fakes import FakeWorldBrain
from ainerzero.v9.interfaces.errors import (
    ContractViolation,
    EnvelopeRejected,
    MalformedPayload,
    SnapshotRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
)
from ainerzero.v9.interfaces.types import BeliefSummary, SkillProposal, evidence_digest


def deep(value: dict) -> dict:
    return json.loads(json.dumps(value))


@pytest.fixture
def brain(geometry, encoder) -> FakeWorldBrain:
    return FakeWorldBrain(geometry=geometry, encoder=encoder)


def test_step_returns_a_belief_summary_matching_the_packet(brain, payload_factory):
    payload = payload_factory()
    summary = brain.step(payload)
    assert isinstance(summary, BeliefSummary)
    assert summary.t_ticks == payload["time"]["t_ticks"]
    assert summary.dt_ticks == payload["time"]["dt_ticks"]
    assert summary.dt_s == pytest.approx(payload["time"]["dt_s"])
    assert summary.sim_hz == 120
    assert summary.used_pose_sensor is False
    assert summary.belief.side == "right"
    assert summary.encoder_version == brain._encoder.describe().encoder_version
    assert brain.last_t_ticks == summary.t_ticks


def test_step_keeps_the_real_clock_not_a_frame_counter(brain, payload_factory):
    """dt comes from the packet (式 3): two steps with different dt differ."""
    first = payload_factory()
    second = payload_factory()
    second["time"]["t_ticks"] = 57
    second["time"]["dt_ticks"] = 7
    second["time"]["dt_s"] = 7 / 120
    s1 = brain.step(first)
    s2 = brain.step(second)
    assert s2.t_ticks - s1.t_ticks == 7
    assert s2.dt_s == pytest.approx(7 / 120)


def test_step_rejects_whole_envelope(brain, payload_factory):
    payload = payload_factory()
    envelope = {"schema_version": "awz.observation_packet.v1.1", "envelope": {}, "payload": payload}
    with pytest.raises(EnvelopeRejected) as caught:
        brain.step(envelope)
    assert caught.value.code == "envelope_rejected"


def test_step_rejects_snapshot_document(brain):
    with pytest.raises(SnapshotRejected) as caught:
        brain.step({"schema_version": "awz.world_snapshot.v1", "student_input": {}})
    assert caught.value.code == "snapshot_rejected"


def test_step_rejects_truth_keys(brain, payload_factory):
    payload = deep(payload_factory())
    payload["task_instruction"]["entity_id"] = "char-7"
    with pytest.raises(TruthFieldRejected) as caught:
        brain.step(payload)
    assert caught.value.code == "truth_field_rejected"


def test_step_rejects_backwards_time(brain, payload_factory):
    payload = payload_factory()
    brain.step(payload)
    earlier = deep(payload)
    earlier["time"]["t_ticks"] = 5
    earlier["time"]["dt_ticks"] = 0
    earlier["time"]["dt_s"] = 0.0
    with pytest.raises(TimeWhitelistRejected) as caught:
        brain.step(earlier)
    assert caught.value.code == "time_whitelist_rejected"
    assert "backwards" in caught.value.detail


def test_reset_allows_the_clock_to_restart(brain, payload_factory):
    brain.step(payload_factory())
    brain.reset({"start_tick": 0})  # clean metadata accepted
    earlier = deep(payload_factory())
    earlier["time"]["t_ticks"] = 5
    earlier["time"]["dt_ticks"] = 0
    earlier["time"]["dt_s"] = 0.0
    assert brain.step(earlier).t_ticks == 5
    assert brain.last_t_ticks == 5


def test_reset_refuses_world_truth_metadata(brain):
    with pytest.raises(TruthFieldRejected) as caught:
        brain.reset({"episode_id": "550e8400-e29b-41d4-a716-446655440000"})
    assert caught.value.code == "truth_field_rejected"
    with pytest.raises(EnvelopeRejected):
        brain.reset({"schema_version": "awz.observation_packet.v1.1", "payload": {}})
    with pytest.raises(SnapshotRejected):
        brain.reset({"schema_version": "awz.world_snapshot.v1"})
    with pytest.raises(MalformedPayload):
        brain.reset("not-a-mapping")


def test_propose_returns_ttl_and_digest_pinned_proposals(brain):
    (proposal,) = brain.propose({"kind": "symbolic", "description": "reach the chair"})
    assert isinstance(proposal, SkillProposal)
    assert proposal.ttl_ticks >= 1
    assert re.fullmatch(r"[0-9a-f]{64}", proposal.evidence_version)
    assert proposal.evidence_version == evidence_digest(proposal.basis)
    assert "t_ticks" in proposal.basis
    assert proposal.actor == "student"


def test_propose_refuses_world_identity_in_the_goal(brain):
    with pytest.raises(TruthFieldRejected) as caught:
        brain.propose({"entity_id": "char-7"})
    assert caught.value.code == "truth_field_rejected"
    with pytest.raises(ContractViolation):
        brain.propose(["not", "a", "mapping"])


def test_proposals_never_carry_world_identity_keys(brain):
    (proposal,) = brain.propose({"kind": "symbolic", "description": "go"})
    from ainerzero.v9.interfaces.validation import scan_forbidden_keys

    assert list(scan_forbidden_keys(dict(proposal.params))) == []
