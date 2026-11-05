"""Contract: PerceptionEncoder (r5 §3, §8.6).

Positive: gated encode with reference resolution, declared provenance,
RLT retention accounting across calls.

Counter-examples: envelope / snapshot / forbidden keys handed to ``encode``,
private or remote URIs, references stamped after the packet cut, an external
encoder without source+license, an enabled RLT policy without a threshold.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from ainerzero.v9.fakes import FakePerceptionEncoder
from ainerzero.v9.fakes.perception import REFERENCE_CHANNEL_KEYS
from ainerzero.v9.interfaces.errors import (
    ContractViolation,
    EnvelopeRejected,
    MalformedPayload,
    ReferenceRejected,
    SnapshotRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
)
from ainerzero.v9.interfaces.types import EncoderDescriptor, RetentionReport, TokenPolicy


def deep(value: dict) -> dict:
    return json.loads(json.dumps(value))


# ---- provenance ------------------------------------------------------------ #


def test_describe_reports_version_and_derived_capability_note():
    fake = FakePerceptionEncoder(encoder_version="enc-fake-1", kind="symbolic")
    descriptor = fake.describe()
    assert isinstance(descriptor, EncoderDescriptor)
    assert descriptor.encoder_version == "enc-fake-1"
    assert descriptor.external_pretrained is False
    assert "no external weights" in descriptor.capability_note


def test_external_encoder_must_declare_source_and_license():
    with pytest.raises(ValueError) as caught:
        FakePerceptionEncoder(external_pretrained=True)
    message = str(caught.value)
    assert "source" in message and "license" in message
    with pytest.raises(ValueError):
        FakePerceptionEncoder(external_pretrained=True, source="hf://model")
    declared = FakePerceptionEncoder(
        external_pretrained=True, source="hf://some/model", license="apache-2.0"
    ).describe()
    assert declared.source == "hf://some/model" and declared.license == "apache-2.0"
    assert "hf://some/model" in declared.capability_note
    assert "apache-2.0" in declared.capability_note
    with pytest.raises(ValueError):  # the type itself fails closed
        EncoderDescriptor(encoder_version="x", kind="visual", external_pretrained=True)


# ---- token policy ---------------------------------------------------------- #


def test_token_policy_declares_switch_threshold_and_retention(encoder, payload_factory):
    policy = encoder.token_policy()
    assert isinstance(policy, TokenPolicy)
    assert policy.rlt_enabled is False
    assert policy.threshold_tau is None
    assert policy.retention.tokens_seen == 0 and policy.retention.rate == 1.0
    encoder.encode(payload_factory())
    policy = encoder.token_policy()
    assert policy.retention.tokens_seen > 0
    assert policy.retention.rate == 1.0  # no dedup without RLT

    rlt = FakePerceptionEncoder(rlt_enabled=True, threshold_tau=0.5)
    assert rlt.token_policy().threshold_tau == pytest.approx(0.5)


def test_token_policy_threshold_is_frozen():
    policy = TokenPolicy(rlt_enabled=True, threshold_tau=0.5, retention=RetentionReport(0, 0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.threshold_tau = 9.0


def test_enabled_rlt_requires_a_threshold_disabled_rlt_forbids_one():
    with pytest.raises(ContractViolation):
        FakePerceptionEncoder(rlt_enabled=True)
    with pytest.raises(ContractViolation):
        FakePerceptionEncoder(rlt_enabled=True, threshold_tau=-0.1)
    with pytest.raises(ContractViolation):
        FakePerceptionEncoder(rlt_enabled=False, threshold_tau=0.5)


def test_retention_accounting_drops_when_rlt_dedups(payload_factory):
    rlt = FakePerceptionEncoder(rlt_enabled=True, threshold_tau=0.5)
    payload = payload_factory()
    first = rlt.encode(payload)
    second = rlt.encode(payload)
    retention = rlt.token_policy().retention
    assert retention.tokens_seen == first.tokens + second.tokens
    assert retention.tokens_kept == first.tokens  # duplicates seen, not kept
    assert retention.rate < 1.0
    assert isinstance(retention, RetentionReport)
    with pytest.raises(ValueError):  # counters cannot exceed what was seen
        RetentionReport(tokens_seen=1, tokens_kept=2)


# ---- encode gate ----------------------------------------------------------- #


def test_encode_returns_tokens_and_resolved_references(encoder, payload_factory):
    encoded = encoder.encode(payload_factory())
    assert encoded.tokens > 0
    assert encoded.encoder_version == encoder.describe().encoder_version
    assert encoded.t_ticks == 50
    assert "obs/t0005.png" in encoded.resolved_references
    assert len(encoded.token_signatures) == encoded.tokens
    assert len(set(encoded.token_signatures)) == encoded.tokens  # one sig per token


def test_encode_refuses_envelopes_snapshots_and_truth_keys(encoder, payload_factory):
    payload = payload_factory()
    with pytest.raises(EnvelopeRejected):
        encoder.encode({"schema_version": "awz.observation_packet.v1.1", "payload": payload})
    with pytest.raises(SnapshotRejected):
        encoder.encode({"schema_version": "awz.world_snapshot.v1", "student_input": {}})
    tainted = deep(payload)
    tainted["visibility"]["entity_id"] = "e-1"
    with pytest.raises(TruthFieldRejected):
        encoder.encode(tainted)
    broken = deep(payload)
    broken["time"]["sim_hz"] = 60
    with pytest.raises(TimeWhitelistRejected):
        encoder.encode(broken)


def test_encode_resolves_only_registered_namespaces(encoder, payload_factory):
    payload = deep(payload_factory())
    payload["observation"]["channels"][0]["image"]["uri"] = "private/secret.png"
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(payload)
    assert caught.value.code == "reference_rejected"
    payload = deep(payload_factory())
    payload["observation"]["channels"][0]["image"]["uri"] = "https://cdn.example/f.png"
    with pytest.raises(ReferenceRejected):
        encoder.encode(payload)
    payload = deep(payload_factory())
    payload["observation"]["channels"][0]["image"]["uri"] = "eval/labels.json"
    with pytest.raises(ReferenceRejected):
        encoder.encode(payload)


def test_encode_resolves_tick_stamped_references_as_of_the_packet(encoder, payload_factory):
    payload = deep(payload_factory())
    payload["observation"]["channels"][0]["image"]["uri"] = "obs/t50/frame.png"
    assert "obs/t50/frame.png" in encoder.encode(payload).resolved_references
    payload = deep(payload_factory())
    payload["observation"]["channels"][0]["image"]["uri"] = "obs/t99999/frame.png"
    with pytest.raises(ReferenceRejected) as caught:  # counter-example: future reference
        encoder.encode(payload)
    assert "after the packet cut" in caught.value.detail


def test_reference_channel_keys_are_registered():
    assert "uri" in REFERENCE_CHANNEL_KEYS
    assert all(isinstance(key, str) for key in REFERENCE_CHANNEL_KEYS)


def test_encode_requires_an_observation_payload(encoder):
    with pytest.raises(MalformedPayload):  # no required fields at all
        encoder.encode({})
    with pytest.raises(MalformedPayload):  # not even a mapping
        encoder.encode(["not", "a", "mapping"])
