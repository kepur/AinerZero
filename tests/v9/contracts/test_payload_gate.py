"""Contract: the ObservationPacket/v1.1 payload gate (WorldBrainAdapter, PerceptionEncoder).

Positive case: exactly the eight whitelisted payload fields with the four-field
time whitelist pass.  Counter-examples: whole envelope, snapshot document,
forbidden truth / identity / randomness / world-metadata keys, future
information, malformed or inconsistent time, unknown payload fields.

Drift pins: when the AWZ checkout is present, the frozen copy of the L1-L10
leak rules and of the required payload fields must match the upstream contract
files byte-for-byte in content (SHA pin + field-by-field comparison), and every
AWZ example must be classified the same way by this gate.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ainerzero.v9.interfaces.errors import (
    EnvelopeRejected,
    FutureFieldRejected,
    MalformedPayload,
    ReferenceRejected,
    SnapshotRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
    V9InterfaceError,
)
from ainerzero.v9.interfaces.validation import (
    LEAK_RULE_SOURCE_SHA256,
    LEAK_RULES,
    REQUIRED_PAYLOAD_KEYS,
    resolve_reference,
    validate_observation_payload,
    validate_time_whitelist,
)


def deep(value: dict) -> dict:
    return json.loads(json.dumps(value))


# ---- positive ------------------------------------------------------------- #


def test_valid_payload_passes_the_gate(valid_payload):
    validated = validate_observation_payload(valid_payload)
    assert validated.t_ticks == 50
    assert validated.dt_ticks == 10
    assert validated.sim_hz == 120
    assert validated.dt_s == pytest.approx(10 / 120)
    assert validated.used_pose_sensor is False
    assert validated.channel_kinds == ("rgb", "relative_objects", "ego_motion")


def test_required_payload_fields_are_the_schema_whitelist():
    assert REQUIRED_PAYLOAD_KEYS == (
        "time",
        "episode_start",
        "observation",
        "pose_sensor_if_allowed",
        "visibility",
        "sensor_noise",
        "last_action_result",
        "task_instruction",
    )


# ---- counter-examples: envelope / snapshot -------------------------------- #


def test_step_rejects_whole_envelope(payload_factory):
    payload = payload_factory()
    envelope = {"schema_version": "awz.observation_packet.v1.1", "envelope": {}, "payload": payload}
    with pytest.raises(EnvelopeRejected) as caught:
        validate_observation_payload(envelope)
    assert caught.value.code == "envelope_rejected"
    # even without schema_version, an envelope/payload wrapper is refused
    with pytest.raises(EnvelopeRejected):
        validate_observation_payload({"envelope": {}, "payload": payload})


def test_rejects_snapshot_document(payload_factory):
    with pytest.raises(SnapshotRejected) as caught:
        validate_observation_payload(
            {"schema_version": "awz.world_snapshot.v1", "student_input": {}, "state": {}}
        )
    assert caught.value.code == "snapshot_rejected"
    with pytest.raises(SnapshotRejected):
        validate_observation_payload({"student_input": {}, "consumers": []})
    with pytest.raises(SnapshotRejected):  # L4 ^snapshot pattern
        payload = deep(payload_factory())
        payload["snapshot_sha256"] = "b" * 64
        validate_observation_payload(payload)


# ---- counter-examples: forbidden keys ------------------------------------- #


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("position", [0.0, 0.0, 0.0], TruthFieldRejected),  # L1
        ("entity_id", "e-1", TruthFieldRejected),  # L2
        ("future_observation", {}, FutureFieldRejected),  # L3
        ("next_frame", 12, FutureFieldRejected),  # L3
        ("noise_seed", 7, TruthFieldRejected),  # L6
        ("ground_truth", {"x": 1}, TruthFieldRejected),  # L5
        ("world_id", "w-1", TruthFieldRejected),  # L8
        ("camera_id", "cam-1", TruthFieldRejected),  # L9
        ("episode_id", "ep-1", TruthFieldRejected),  # L10
    ],
)
def test_forbidden_keys_are_refused(payload_factory, key, value, error):
    payload = deep(payload_factory())
    payload["task_instruction"][key] = value
    with pytest.raises(error) as caught:
        validate_observation_payload(payload)
    assert isinstance(caught.value, V9InterfaceError)


def test_forbidden_keys_are_refused_deep_inside_lists(payload_factory):
    payload = deep(payload_factory())
    payload["observation"]["channels"][1]["detections"][0]["entity_id"] = "e-42"
    with pytest.raises(TruthFieldRejected) as caught:
        validate_observation_payload(payload)
    assert "entity_id" in caught.value.detail


# ---- counter-examples: time whitelist ------------------------------------- #


def test_time_whitelist_is_exactly_four_fields(payload_factory):
    payload = deep(payload_factory())
    payload["time"]["frame_index"] = 3  # a frame counter is not a time source
    with pytest.raises(TimeWhitelistRejected):
        validate_observation_payload(payload)
    payload = deep(payload_factory())
    del payload["time"]["dt_s"]
    with pytest.raises(TimeWhitelistRejected):
        validate_observation_payload(payload)


def test_time_whitelist_requires_registered_clock_and_consistent_dt(payload_factory):
    payload = deep(payload_factory())
    payload["time"]["sim_hz"] = 60
    with pytest.raises(TimeWhitelistRejected):
        validate_observation_payload(payload)
    payload = deep(payload_factory())
    payload["time"]["dt_s"] = 0.5  # != dt_ticks / 120
    with pytest.raises(TimeWhitelistRejected) as caught:
        validate_observation_payload(payload)
    assert "dt_ticks" in caught.value.detail or "inconsistent" in caught.value.detail


def test_validate_time_whitelist_rejects_bad_types():
    with pytest.raises(TimeWhitelistRejected):
        validate_time_whitelist("not-a-mapping")
    with pytest.raises(TimeWhitelistRejected):
        validate_time_whitelist({"sim_hz": 120, "t_ticks": -1, "dt_ticks": 0, "dt_s": 0.0})
    with pytest.raises(TimeWhitelistRejected):
        validate_time_whitelist({"sim_hz": True, "t_ticks": 0, "dt_ticks": 0, "dt_s": 0.0})


# ---- counter-examples: structural ----------------------------------------- #


def test_missing_or_unknown_payload_fields_are_refused(payload_factory):
    payload = deep(payload_factory())
    del payload["observation"]
    with pytest.raises(MalformedPayload):
        validate_observation_payload(payload)
    payload = deep(payload_factory())
    payload["model_side_channel"] = {"x": 1}  # additionalProperties=false
    with pytest.raises(MalformedPayload):
        validate_observation_payload(payload)
    with pytest.raises(MalformedPayload):
        validate_observation_payload(["not", "a", "mapping"])


def test_malformed_channels_are_refused(payload_factory):
    payload = deep(payload_factory())
    payload["observation"]["channels"] = []
    with pytest.raises(MalformedPayload):
        validate_observation_payload(payload)
    payload = deep(payload_factory())
    payload["observation"]["channels"][0] = {"kind": 3}
    with pytest.raises(MalformedPayload):
        validate_observation_payload(payload)
    payload = deep(payload_factory())
    payload["pose_sensor_if_allowed"] = "not-a-mapping"
    with pytest.raises(MalformedPayload):
        validate_observation_payload(payload)


# ---- references ------------------------------------------------------------ #


def test_reference_namespaces_and_time_cut():
    assert resolve_reference("obs/t0005.png", as_of_t_ticks=50) == "obs/t0005.png"
    assert resolve_reference("sensor/t50/odom.json", as_of_t_ticks=50) == "sensor/t50/odom.json"
    assert resolve_reference("derived/t50/features.npz", as_of_t_ticks=50)
    with pytest.raises(ReferenceRejected) as caught:  # counter-example: private namespace
        resolve_reference("private/secret.png", as_of_t_ticks=50)
    assert caught.value.code == "reference_rejected"
    with pytest.raises(ReferenceRejected):  # counter-example: absolute / remote
        resolve_reference("https://cdn.example/x.png", as_of_t_ticks=50)
    with pytest.raises(ReferenceRejected):
        resolve_reference("/abs/path.png", as_of_t_ticks=50)
    with pytest.raises(ReferenceRejected):  # counter-example: future-stamped reference
        resolve_reference("obs/t99999/frame.png", as_of_t_ticks=50)
    with pytest.raises(ReferenceRejected):
        resolve_reference("", as_of_t_ticks=50)


def test_reference_normalization_rejects_relatives_and_dupes():
    with pytest.raises(ReferenceRejected) as caught:
        resolve_reference("obs/../secret.png", as_of_t_ticks=50)
    assert "relative path" in caught.value.detail
    with pytest.raises(ReferenceRejected):
        resolve_reference("obs//extra.png", as_of_t_ticks=50)
    with pytest.raises(ReferenceRejected):
        resolve_reference("obs/%2e%2e/x.png", as_of_t_ticks=50)


def test_reference_fail_closed_on_unmarked_numeric_names():
    # 0005.png has numbers but no t/frame marker -> fail-closed
    with pytest.raises(ReferenceRejected) as caught:
        resolve_reference("obs/0005.png", as_of_t_ticks=50)
    assert "fail-closed" in caught.value.detail
    # but with marker it works
    assert resolve_reference("obs/frame_0005.png", as_of_t_ticks=50)


def test_reference_rejects_fullwidth_slash_and_non_ascii():
    # B11 r3：全角斜杠曾绕过命名空间检查（NFKC 后变成 obs/private/...）
    with pytest.raises(ReferenceRejected) as caught:
        resolve_reference("obs/\uFF0Fprivate/answers", as_of_t_ticks=50)
    assert "NFKC" in caught.value.detail or "non-ASCII" in caught.value.detail
    with pytest.raises(ReferenceRejected):
        resolve_reference("obs/／private/answers", as_of_t_ticks=50)


def test_reference_rejects_query_fragment_and_param_separators():
    # B11 r3：查询串/片段/参数分隔不得出现在学生可见引用
    with pytest.raises(ReferenceRejected) as caught:
        resolve_reference("obs/cam/x?t=999", as_of_t_ticks=10)
    assert "query string" in caught.value.detail
    with pytest.raises(ReferenceRejected):
        resolve_reference("obs/cam/x#frag", as_of_t_ticks=10)
    with pytest.raises(ReferenceRejected):
        resolve_reference("obs/cam/x;param=1", as_of_t_ticks=10)
    # 全角问号：NFKC → ASCII '?'，规范化前后不一致
    with pytest.raises(ReferenceRejected) as caught:
        resolve_reference("obs/cam/x\uFF1Ft=999", as_of_t_ticks=10)
    assert "NFKC" in caught.value.detail or "non-ASCII" in caught.value.detail


# ---- drift pins against the AWZ contract (skip when absent) ---------------- #


def test_leak_rules_are_pinned_to_the_awz_source(awz_leak_rules):
    digest = hashlib.sha256(awz_leak_rules.read_bytes()).hexdigest()
    assert digest == LEAK_RULE_SOURCE_SHA256, "frozen copy no longer matches the AWZ source file"
    upstream = json.loads(awz_leak_rules.read_text(encoding="utf-8"))["rules"]
    assert [rule["id"] for rule in upstream] == [rule["id"] for rule in LEAK_RULES]
    for source, frozen in zip(upstream, LEAK_RULES, strict=True):
        assert source.get("scope") == frozen["scope"], source["id"]
        assert tuple(source["forbidden_keys"]) == frozen["forbidden_keys"], source["id"]
        assert tuple(source["forbidden_key_patterns"]) == frozen["forbidden_key_patterns"], source["id"]


def test_required_fields_match_the_awz_schema(awz_packet_schema):
    schema = json.loads(awz_packet_schema.read_text(encoding="utf-8"))
    node = schema
    for part in schema["properties"]["payload"]["$ref"].lstrip("#/").split("/"):
        node = node[part]
    assert tuple(node["required"]) == REQUIRED_PAYLOAD_KEYS
    assert node["additionalProperties"] is False
    time_schema = node["properties"]["time"]
    assert tuple(time_schema["required"]) == ("sim_hz", "t_ticks", "dt_ticks", "dt_s")
    assert time_schema["additionalProperties"] is False


def test_leakage_normalization_hits_homoglyphs(payload_factory):
    payload = deep(payload_factory())
    # "Position" with full-width P and lowercase o (homoglyph-ish)
    # Ｐｏｓｉｔｉｏｎ
    payload["observation"]["Ｐｏｓｉｔｉｏｎ"] = [0, 0, 0]
    with pytest.raises(TruthFieldRejected) as caught:
        validate_observation_payload(payload)
    assert "L1" in caught.value.detail


def test_leakage_normalization_is_case_insensitive(payload_factory):
    payload = deep(payload_factory())
    payload["observation"]["POSITION"] = [0, 0, 0]
    with pytest.raises(TruthFieldRejected) as caught:
        validate_observation_payload(payload)
    assert "L1" in caught.value.detail


def test_awz_example_packets_are_classified_the_same(awz_packet_examples):
    from ainerzero.v9.interfaces.errors import V9InterfaceError

    valid_dir = awz_packet_examples / "valid"
    invalid_dir = awz_packet_examples / "invalid"
    accepted = sorted(valid_dir.glob("*.json"))
    assert accepted, "AWZ valid examples missing"
    for path in accepted:
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_observation_payload(document["payload"])  # must pass
    for path in sorted(invalid_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        # every AWZ-invalid document must be refused at the envelope level ...
        with pytest.raises(V9InterfaceError) as caught:
            validate_observation_payload(document)
        assert caught.value.code in {"envelope_rejected", "snapshot_rejected"}
        # ... and the payload-level ones must also be refused on their own
        payload = document.get("payload")
        if payload is None:
            continue
        try:
            validate_observation_payload(payload)
        except V9InterfaceError:
            continue
        # accepted payload: the invalidity lives in the envelope only (producer
        # rules: actor / origin / seq / channel allowlist / envelope dt cross-check)
        assert "envelope" in document, f"{path.name}: payload alone was accepted"
