"""The seven replaceable v9 interfaces (ARCHITECTURE_V9 r5 §3).

Import surface for the contract card ainerzero.V9.B2:

- ``INTERFACES`` is the canonical tuple of the seven ABCs, in the order of the
  r5 §3 table;
- shared types (``types``), the typed error hierarchy (``errors``) and the
  ObservationPacket/v1.1 payload gate (``validation``) live next to them.

Pure CPU by construction: this package imports only the standard library and
``numpy``.  No MLX / ONNX Runtime / torch import, no model, no download, no
network, no side effect at import time (checked by
``tests/v9/contracts/test_interface_surface.py``).
"""

from __future__ import annotations

from .errors import (
    BudgetExhausted,
    ContractViolation,
    EncoderVersionMismatch,
    EnvelopeRejected,
    EvidenceRequired,
    FutureFieldRejected,
    MalformedPayload,
    ObservationRejected,
    PartitionWriteRejected,
    ReferenceRejected,
    SignalRejected,
    SnapshotRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
    UnsupportedInput,
    V9InterfaceError,
)
from .geometry_core import GeometryCore
from .perception import PerceptionEncoder
from .planner import HierarchicalPlanner
from .scheduler import UpdateScheduler
from .spatial_memory import SpatialMemory
from .timescale import TimeScaleAdapter
from .validation import (
    LEAK_RULE_SOURCE_SHA256,
    LEAK_RULES,
    REQUIRED_PAYLOAD_KEYS,
    assert_no_forbidden_keys,
    resolve_reference,
    scan_forbidden_keys,
    validate_observation_payload,
    validate_time_whitelist,
)
from .world_brain import WorldBrainAdapter

INTERFACES: tuple = (
    WorldBrainAdapter,
    GeometryCore,
    TimeScaleAdapter,
    SpatialMemory,
    PerceptionEncoder,
    HierarchicalPlanner,
    UpdateScheduler,
)
"""The seven replaceable interfaces of r5 §3, in contract-table order."""

__all__ = [
    "INTERFACES",
    "WorldBrainAdapter",
    "GeometryCore",
    "TimeScaleAdapter",
    "SpatialMemory",
    "PerceptionEncoder",
    "HierarchicalPlanner",
    "UpdateScheduler",
    "V9InterfaceError",
    "ObservationRejected",
    "EnvelopeRejected",
    "SnapshotRejected",
    "TruthFieldRejected",
    "FutureFieldRejected",
    "TimeWhitelistRejected",
    "ReferenceRejected",
    "MalformedPayload",
    "ContractViolation",
    "UnsupportedInput",
    "BudgetExhausted",
    "EncoderVersionMismatch",
    "PartitionWriteRejected",
    "EvidenceRequired",
    "SignalRejected",
    "LEAK_RULES",
    "LEAK_RULE_SOURCE_SHA256",
    "REQUIRED_PAYLOAD_KEYS",
    "scan_forbidden_keys",
    "assert_no_forbidden_keys",
    "validate_time_whitelist",
    "validate_observation_payload",
    "resolve_reference",
]
