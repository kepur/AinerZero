"""ObservationPacket/v1.1 payload gate shared by the v9 interfaces.

``WorldBrainAdapter.step`` (and the consumer path of ``PerceptionEncoder.encode``)
receive **only** the ``payload`` object of an ObservationPacket/v1.1 document.
This module enforces that boundary:

- the whole envelope, any ``schema_version`` wrapper and any WorldSnapshot is
  refused (ARCHITECTURE_V9 r5 §3 WorldBrainAdapter; A2 r1 / A7 findings);
- the model-visible time whitelist is exactly ``{sim_hz, t_ticks, dt_ticks,
  dt_s}`` with the registered 120 Hz clock and ``dt_s == dt_ticks / 120``;
- the forbidden-key rules of ``AnimeWorldZero/contracts/v9/observation_leak_rules.v1_1.json``
  (L1–L10) are enforced recursively, including future-information prefixes;
- references (URI / content digest) resolve only inside registered namespaces
  and only as of the packet's own ``t_ticks`` (§8.6).

The rule table below is a frozen copy of the AWZ contract data, pinned by
``tests/v9/contracts/test_payload_gate.py`` against the upstream file when it is
present on this machine.  The runtime does **not** read another repository.

Pure CPU: no model / MLX import, no I/O at call time.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterator, Mapping

from .errors import (
    EnvelopeRejected,
    EvidenceRequired,
    FutureFieldRejected,
    MalformedPayload,
    ReferenceRejected,
    SnapshotRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
)
from .types import SIM_HZ, TIME_WHITELIST_KEYS, ValidatedPayload

__all__ = [
    "LEAK_RULES",
    "REQUIRED_PAYLOAD_KEYS",
    "DEFAULT_REFERABLE_NAMESPACES",
    "scan_forbidden_keys",
    "assert_no_forbidden_keys",
    "validate_time_whitelist",
    "validate_observation_payload",
    "resolve_reference",
    "LEAK_RULE_SOURCE_SHA256",
]

LEAK_RULE_SOURCE_SHA256 = "5a53affd4ee437ba130d9ebddc066f71d50a30598caa6b2d1ffedf392fbe931d"
"""SHA-256 of ``AnimeWorldZero/contracts/v9/observation_leak_rules.v1_1.json`` (frozen copy source)."""

# Frozen copy of awz:v9/observation_leak_rules.v1.1 (rules L1-L10).
LEAK_RULES: tuple = (
    {
        "id": "L1",
        "scope": "all",
        "forbidden_keys": (
            "position", "heading_deg", "velocity", "world_pose", "world_position",
            "world_heading", "world_velocity", "world_yaw_deg",
        ),
        "forbidden_key_patterns": (),
    },
    {
        "id": "L2",
        "scope": "all",
        "forbidden_keys": (
            "entity_id", "character_id", "instance_id", "object_id", "instance_mask",
            "track_id", "identity_sha256",
        ),
        "forbidden_key_patterns": (),
    },
    {
        "id": "L3",
        "scope": "all",
        "forbidden_keys": (),
        "forbidden_key_patterns": ("^future_", "^next_", "^predicted_"),
    },
    {
        "id": "L4",
        "scope": "all",
        "forbidden_keys": (
            "state_hash", "state_sha256", "event_log_hash", "event_log_len", "source_revision",
            "source_digest", "base_revision", "expected_revision", "rng_state_hash", "sim_tick",
            "student_input", "world_version", "scene_revision", "snapshot_sha256", "source_sha256",
        ),
        "forbidden_key_patterns": ("^snapshot",),
    },
    {
        "id": "L5",
        "scope": "all",
        "forbidden_keys": (
            "truth_layer", "event_layer", "event_layers_present", "label", "labels",
            "ground_truth", "score", "answer", "correct",
        ),
        "forbidden_key_patterns": ("^gt_", "^eval_"),
    },
    {
        "id": "L6",
        "scope": "all",
        "forbidden_keys": ("noise_seed", "episode_seed", "world_seed", "sensor_salt"),
        "forbidden_key_patterns": ("^rng_", "_seed$", "^raw_", "^clean_"),
    },
    {
        "id": "L7",
        "scope": "all",
        "forbidden_keys": (),
        "forbidden_key_patterns": (),
    },
    {
        "id": "L8",
        "scope": "all",
        "forbidden_keys": (
            "world_id", "layout_id", "world_rule_version", "asset_manifest_sha256",
            "kernel_version", "mechanics_version",
        ),
        "forbidden_key_patterns": (),
    },
    {
        "id": "L9",
        "scope": "all",
        "forbidden_keys": (
            "visible", "world_time", "shot_time", "camera_id", "presentation", "art_layer", "occluded",
        ),
        "forbidden_key_patterns": (),
    },
    {
        "id": "L10",
        "scope": "payload",
        "forbidden_keys": (
            "envelope", "episode_id", "agent_id", "seq", "partition", "task", "provenance",
            "actor", "origin", "assistance", "license",
        ),
        "forbidden_key_patterns": (),
    },
)

REQUIRED_PAYLOAD_KEYS: tuple = (
    "time",
    "episode_start",
    "observation",
    "pose_sensor_if_allowed",
    "visibility",
    "sensor_noise",
    "last_action_result",
    "task_instruction",
)
"""Required fields of ObservationPacket/v1.1 ``payload`` (schema ``required``)."""

SNAPSHOT_SCHEMA_PREFIX = "awz.world_snapshot"
PACKET_SCHEMA_PREFIX = "awz.observation_packet"
ENVELOPE_LEVEL_KEYS: tuple = ("schema_version", "envelope", "payload")
SNAPSHOT_LEVEL_KEYS: tuple = ("student_input", "consumers", "base", "state", "mechanics_version")

DEFAULT_REFERABLE_NAMESPACES: tuple = ("obs", "sensor", "derived")
"""Namespaces a student-visible reference may point at (§8.6; ``private``/``eval`` are not)."""

_TICK_MARKERS = (
    re.compile(r"[^a-zA-Z0-9]t(\d{1,12})(?:[^a-zA-Z0-9]|$)"),  # t999, .t999, /t999
    re.compile(r"frame_?(\d{1,12})", re.IGNORECASE),           # frame000999, frame_999
)
_NUMERIC_FILENAME = re.compile(r"(?:^|/)(\d+)\.[a-z0-9]+$", re.IGNORECASE)


def resolve_reference(
    uri: Any,
    *,
    as_of_t_ticks: int,
    allowed_namespaces: tuple = DEFAULT_REFERABLE_NAMESPACES,
) -> str:
    """Resolve a student-visible reference as of the packet's own tick (§8.6).

    r1 打回修复：先规范化路径并拒绝 ..、重复分隔、URL 编码分隔；时间截止对 URI
    中任何位置的帧标记生效；解析不了的带数字帧名一律拒 (fail-closed)。

    r3 打回修复（B11）：先做 NFKC，规范化前后不一致或含任何非 ASCII 一律拒绝；
    学生可见引用不允许查询串/片段/参数分隔（``?`` ``#`` ``;``）。
    """
    if not isinstance(uri, str) or not uri:
        raise ReferenceRejected("reference uri must be a non-empty string")

    # 0. NFKC + ASCII-only (fail-closed against fullwidth separators / homoglyphs)
    normalized = unicodedata.normalize("NFKC", uri)
    if normalized != uri:
        raise ReferenceRejected(
            f"reference {uri!r} is not NFKC-stable (normalized form differs); refusing for safety"
        )
    if any(ord(ch) > 127 for ch in uri):
        raise ReferenceRejected(
            f"reference {uri!r} contains non-ASCII characters; only ASCII paths resolve"
        )

    # 1. 查询串 / 片段 / 参数分隔一律拒绝（学生可见引用不得带 ? # ;）
    for sep, label in (("?", "query string"), ("#", "fragment"), (";", "parameter separator")):
        if sep in uri:
            raise ReferenceRejected(
                f"reference {uri!r} contains {label} ({sep!r}); student-visible refs must be bare paths"
            )

    # 2. 规范化与非法字符检查
    if "%" in uri:
        raise ReferenceRejected(f"reference {uri!r} contains URL encoding; use raw paths only")
    if "//" in uri:
        raise ReferenceRejected(f"reference {uri!r} contains duplicate separators")
    if ".." in uri or "/./" in uri or uri.endswith("/."):
        raise ReferenceRejected(f"reference {uri!r} contains relative path components (.. or .)")
    if "://" in uri or uri.startswith("/") or uri.startswith("~") or "\\" in uri:
        raise ReferenceRejected(f"reference {uri!r} is absolute or remote; only relative registered paths resolve")

    # 3. 命名空间检查
    head = uri.split("/", 1)[0]
    if head not in tuple(allowed_namespaces):
        raise ReferenceRejected(
            f"reference {uri!r} is outside the registered namespaces {tuple(allowed_namespaces)}"
        )

    # 4. 时间截止检查 (对 URI 中任何位置的帧标记生效)
    # t999.png, frame_000999 之类都要解析出 tick 并与 as_of 比较
    for pattern in _TICK_MARKERS:
        for match in pattern.finditer(uri):
            tick = int(match.group(1))
            if tick > as_of_t_ticks:
                raise ReferenceRejected(
                    f"reference {uri!r} frame tick {tick} is after the packet cut t_ticks={as_of_t_ticks}"
                )

    # 5. 解析不了的带数字帧名一律拒 (fail-closed)
    # e.g. 999.png if it wasn't caught by markers but has numbers
    num_match = _NUMERIC_FILENAME.search(uri)
    if num_match:
        # 如果命中了纯数字文件名但没有被标记命中，则无法确定 tick，保守拒绝
        # 除非它是被显式允许的 (目前没有白名单)
        found_in_markers = False
        for pattern in _TICK_MARKERS:
            if pattern.search(uri):
                found_in_markers = True
                break
        if not found_in_markers:
            raise ReferenceRejected(
                f"reference {uri!r} has numeric frame name but no explicit 't' or 'frame' marker; "
                "refusing for safety (fail-closed)"
            )

    return uri


_RULE_BY_ID = {rule["id"]: rule for rule in LEAK_RULES}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _error_for_rule(rule_id: str, key: str, path: str) -> Exception:
    detail = f"{rule_id}:{key}@{path}"
    if rule_id == "L4":
        return SnapshotRejected(detail)
    if rule_id == "L3":
        return FutureFieldRejected(detail)
    return TruthFieldRejected(detail)


# r1 打回修复：改为登记表 (producer -> 类别 teacher/llm/self/...) (D-021 §3.4)
PRODUCER_REGISTRY: Mapping[str, str] = {
    "student": "self",
    "baseline": "baseline",
    "contract-harness": "baseline",
    "independent_verifier": "baseline",
    "independent_test": "baseline",
    "teacher": "teacher",
    "distilled-teacher-v1": "teacher",
    "distilled-teacher-v2": "teacher",
    "LLM-gpt": "llm",
    "llm-gpt": "llm",
    "llm-claude": "llm",
    "human_reviewed": "human",
}


def validate_producer(producer: Any) -> str:
    """Validate a producer against the registry; unregistered are rejected."""
    if not isinstance(producer, str):
        raise EvidenceRequired(f"producer must be a string, got {type(producer).__name__}")
    
    # 精确匹配登记表
    category = PRODUCER_REGISTRY.get(producer)
    if category is None:
        raise EvidenceRequired(f"unregistered producer {producer!r}; all producers must be in the registry")
    
    # 拦截非法晋升类别
    if category in {"teacher", "llm", "assistant", "human_unreviewed"}:
        raise EvidenceRequired(
            f"producers of category {category!r} are not allowed to write SLOW directly (D-021 §3.4); "
            f"producer={producer!r}"
        )
    return category


def scan_forbidden_keys(document: Any, *, root: str = "$") -> Iterator[tuple[str, str, str]]:
    """Yield ``(path, key, rule_id)`` for every forbidden key found recursively."""
    if isinstance(document, Mapping):
        for key, value in document.items():
            if not isinstance(key, str):
                continue
            # r1 打回修复：先 NFKC 规范化再按小写比较 (D-021 §3.3)
            norm_key = unicodedata.normalize("NFKC", key).lower()
            for rule in LEAK_RULES:
                if rule["id"] == "L7":
                    continue  # cross-checks only
                if norm_key in rule["forbidden_keys"] or any(
                    re.search(pattern, norm_key) for pattern in rule["forbidden_key_patterns"]
                ):
                    yield (root, key, rule["id"])
            yield from scan_forbidden_keys(value, root=f"{root}.{key}")
    elif isinstance(document, (list, tuple)):
        for index, value in enumerate(document):
            yield from scan_forbidden_keys(value, root=f"{root}[{index}]")


def assert_no_forbidden_keys(document: Any, *, origin: str = "document") -> None:
    """Raise the rule-specific rejection when any forbidden key is present."""
    for path, key, rule_id in scan_forbidden_keys(document):
        raise _error_for_rule(rule_id, key, f"{origin}{path.lstrip('$')}")


def validate_time_whitelist(time: Any, *, origin: str = "payload.time") -> Mapping[str, Any]:
    """Validate the four-field model-visible time whitelist (§2, §3, L3 cross-checks)."""
    if not isinstance(time, Mapping):
        raise TimeWhitelistRejected(f"{origin} must be an object")
    keys = tuple(time.keys())
    if set(keys) != set(TIME_WHITELIST_KEYS) or len(keys) != len(TIME_WHITELIST_KEYS):
        raise TimeWhitelistRejected(
            f"{origin} must contain exactly {TIME_WHITELIST_KEYS}, got {sorted(keys)}"
        )
    sim_hz = time["sim_hz"]
    if not _is_int(sim_hz) or sim_hz != SIM_HZ:
        raise TimeWhitelistRejected(f"{origin}.sim_hz must be the registered {SIM_HZ} Hz clock, got {sim_hz!r}")
    t_ticks = time["t_ticks"]
    dt_ticks = time["dt_ticks"]
    dt_s = time["dt_s"]
    if not _is_int(t_ticks) or t_ticks < 0:
        raise TimeWhitelistRejected(f"{origin}.t_ticks must be a non-negative integer, got {t_ticks!r}")
    if not _is_int(dt_ticks) or dt_ticks < 0:
        raise TimeWhitelistRejected(f"{origin}.dt_ticks must be a non-negative integer, got {dt_ticks!r}")
    if isinstance(dt_s, bool) or not isinstance(dt_s, (int, float)) or not math.isfinite(float(dt_s)):
        raise TimeWhitelistRejected(f"{origin}.dt_s must be a finite number, got {dt_s!r}")
    if float(dt_s) < 0:
        raise TimeWhitelistRejected(f"{origin}.dt_s must be non-negative, got {dt_s!r}")
    if abs(float(dt_s) - dt_ticks / SIM_HZ) > 1e-9:
        raise TimeWhitelistRejected(
            f"{origin}.dt_s={dt_s!r} is inconsistent with dt_ticks/{SIM_HZ}={dt_ticks / SIM_HZ!r}"
        )
    return {
        "sim_hz": int(sim_hz),
        "t_ticks": int(t_ticks),
        "dt_ticks": int(dt_ticks),
        "dt_s": float(dt_s),
    }


def _reject_envelope_level(payload: Mapping) -> None:
    """Refuse envelope-level and snapshot-level documents before anything else."""
    if "schema_version" in payload:
        version = payload["schema_version"]
        text = version if isinstance(version, str) else ""
        if text.startswith(SNAPSHOT_SCHEMA_PREFIX):
            raise SnapshotRejected(f"world snapshot schema_version={version!r} is not student input")
        raise EnvelopeRejected(
            f"schema_version={version!r} belongs to the packet envelope; step() takes only payload"
        )
    if "envelope" in payload or "payload" in payload:
        raise EnvelopeRejected("whole ObservationPacket passed; step() takes only payload")
    if any(key in payload for key in SNAPSHOT_LEVEL_KEYS):
        raise SnapshotRejected(
            f"snapshot-level key(s) {[key for key in SNAPSHOT_LEVEL_KEYS if key in payload]} are not student input"
        )


def validate_observation_payload(payload: Any) -> ValidatedPayload:
    """Full payload gate; returns the allowed view or raises a typed rejection."""
    if not isinstance(payload, Mapping):
        raise MalformedPayload(f"payload must be an object, got {type(payload).__name__}")
    _reject_envelope_level(payload)
    assert_no_forbidden_keys(payload, origin="payload")
    missing = [key for key in REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        raise MalformedPayload(f"payload is missing required ObservationPacket/v1.1 field(s) {missing}")
    extra = [key for key in payload if key not in REQUIRED_PAYLOAD_KEYS]
    if extra:
        raise MalformedPayload(
            f"payload carries field(s) outside the schema whitelist {sorted(REQUIRED_PAYLOAD_KEYS)}: "
            f"{sorted(extra)} (payload.additionalProperties=false)"
        )
    time = validate_time_whitelist(payload["time"])
    observation = payload["observation"]
    if not isinstance(observation, Mapping):
        raise MalformedPayload("payload.observation must be an object")
    channels = observation.get("channels")
    if not isinstance(channels, (list, tuple)) or len(channels) < 1:
        raise MalformedPayload("payload.observation.channels must contain at least one channel")
    kinds: list[str] = []
    for index, channel in enumerate(channels):
        if not isinstance(channel, Mapping):
            raise MalformedPayload(f"channel[{index}] must be an object")
        kind = channel.get("kind")
        if not isinstance(kind, str) or not kind:
            raise MalformedPayload(f"channel[{index}].kind must be a non-empty string")
        kinds.append(kind)
    pose_sensor = payload["pose_sensor_if_allowed"]
    if pose_sensor is not None and not isinstance(pose_sensor, Mapping):
        raise MalformedPayload("payload.pose_sensor_if_allowed must be null or an object")
    return ValidatedPayload(
        t_ticks=time["t_ticks"],
        dt_ticks=time["dt_ticks"],
        dt_s=time["dt_s"],
        sim_hz=time["sim_hz"],
        channel_kinds=tuple(kinds),
        used_pose_sensor=pose_sensor is not None,
        raw=payload,
    )
