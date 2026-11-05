"""Fixtures for the v9 contract suite (card ainerzero.V9.B2).

Pure CPU by construction: no model import, no MLX/ORT/torch, no network, no
file writes.  The AWZ checkout is read **only** when it is present on this
machine (drift pins and example counter-examples), otherwise those tests skip
with an explicit reason instead of silently passing.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ainerzero.v9.fakes import FakeGeometryCore, FakePerceptionEncoder
from ainerzero.v9.interfaces.types import PoseBelief

AWZ_ROOT = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")
AWZ_PACKET_EXAMPLES = AWZ_ROOT / "contracts/v9/examples/observation_packet_v1_1"
AWZ_LEAK_RULES = AWZ_ROOT / "contracts/v9/observation_leak_rules.v1_1.json"
AWZ_PACKET_SCHEMA = AWZ_ROOT / "contracts/v9/observation_packet.v1_1.schema.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def build_valid_payload() -> dict:
    """A payload that satisfies ObservationPacket/v1.1 exactly (8 whitelisted fields)."""
    return {
        "time": {"sim_hz": 120, "t_ticks": 50, "dt_ticks": 10, "dt_s": 10 / 120},
        "episode_start": False,
        "observation": {
            "channels": [
                {
                    "kind": "rgb",
                    "image": {"uri": "obs/t0005.png", "sha256": "a" * 64},
                    "width": 320,
                    "height": 180,
                },
                {
                    "kind": "relative_objects",
                    "detections": [
                        {
                            "handle": "h-1",
                            "appearance_class": "char/heroine",
                            "rel_position_m": [0.4, 0.0, 2.1],
                            "rel_yaw_deg": -30.0,
                            "confidence": 0.92,
                        }
                    ],
                },
                {
                    "kind": "ego_motion",
                    "delta": {"dx_m": 0.0, "dy_m": 0.0, "dz_m": 0.08, "dyaw_deg": 1.5},
                },
            ]
        },
        "pose_sensor_if_allowed": None,
        "visibility": {"fov_deg": 90.0, "range_m": 12.0, "occlusion": "hidden_objects_absent"},
        "sensor_noise": {
            "rgb": {"model": "none", "params": {}},
            "relative_objects": {"model": "gaussian", "params": {"sigma_m": 0.05}},
            "ego_motion": {"model": "gaussian", "params": {"sigma_m": 0.01}},
        },
        "last_action_result": {"action_seq": 4, "status": "executed", "reason_code": "none"},
        "task_instruction": {"text": "walk", "goal": {"kind": "symbolic", "description": "chair"}},
    }


@pytest.fixture
def payload_factory():
    """Fresh valid payload per call (tests mutate copies freely)."""
    return build_valid_payload


@pytest.fixture
def valid_payload() -> dict:
    return build_valid_payload()


@pytest.fixture
def geometry() -> FakeGeometryCore:
    """SE(2) double with a registered process-noise rate (for predict cross-checks)."""
    return FakeGeometryCore(process_covariance_rate=((1e-4, 0.0, 0.0), (0.0, 1e-4, 0.0), (0.0, 0.0, 1e-5)))


@pytest.fixture
def belief() -> PoseBelief:
    """Right-hand SE(2) belief with a non-trivial mean and explicit gravity."""
    import numpy as np

    theta = 0.35
    mean = (
        (float(np.cos(theta)), -float(np.sin(theta)), 0.7),
        (float(np.sin(theta)), float(np.cos(theta)), -0.25),
        (0.0, 0.0, 1.0),
    )
    return PoseBelief(
        group="SE2",
        mean=mean,
        covariance=((0.02, 0.004, 0.0), (0.004, 0.03, 0.0), (0.0, 0.0, 0.01)),
        gravity=(0.0, 0.0, -1.0),
        unobservable_dof=("global_translation", "global_yaw"),
    )


@pytest.fixture
def encoder() -> FakePerceptionEncoder:
    return FakePerceptionEncoder()


@pytest.fixture
def awz_packet_examples() -> Path:
    if not AWZ_PACKET_EXAMPLES.is_dir():
        pytest.skip(f"AWZ example checkout not present: {AWZ_PACKET_EXAMPLES}")
    return AWZ_PACKET_EXAMPLES


@pytest.fixture
def awz_leak_rules() -> Path:
    if not AWZ_LEAK_RULES.is_file():
        pytest.skip(f"AWZ leak-rule contract not present: {AWZ_LEAK_RULES}")
    return AWZ_LEAK_RULES


@pytest.fixture
def awz_packet_schema() -> Path:
    if not AWZ_PACKET_SCHEMA.is_file():
        pytest.skip(f"AWZ packet schema not present: {AWZ_PACKET_SCHEMA}")
    return AWZ_PACKET_SCHEMA


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def deep(value: dict) -> dict:
    return copy.deepcopy(value)


# ---- ADR-0014 r3 §3 C1/C2 fixtures (card ainerzero.V9.B12) ----------------- #
# 共享构造器：v2 证据必须带可信上下文绑定，绑定摘要覆盖 (context_id, producer,
# category)，因此测试不能靠"自报字符串"通过；负例只改一个字段。


def trusted_context_for(producer: str = "contract-harness", *, context_id: str = "ctx-b12") -> dict:
    """Build a trusted context whose admission binding matches ``producer``."""
    from ainerzero.v9.interfaces.validation import PRODUCER_REGISTRY, slow_binding_digest

    category = PRODUCER_REGISTRY[producer]
    return {
        "context_id": context_id,
        "issuer": "relay:independent-harness",
        "admission_bindings": [
            {
                "producer": producer,
                "category": category,
                "context_id": context_id,
                "binding_sha256": slow_binding_digest(
                    context_id=context_id, producer=producer, category=category
                ),
            }
        ],
    }


def v2_evidence(fragment=None, *, producer: str = "contract-harness", test_id: str = "v9-b12-independent-1", **overrides):
    """A complete PromotionEvidence v2; ``overrides`` replaces whole fields."""
    from ainerzero.v9.interfaces.types import PromotionEvidence

    base = {
        "kind": "independent_test",
        "report_ref": "reports/V9-B12/independent.md",
        "producer": producer,
        "test_id": test_id,
        "schema_version": "v2",
        "trusted_context": trusted_context_for(producer),
        "domain_ref": "dom:room-a@enc-v1",
        "calibration": {
            "method": "split_conformal",
            "alpha_dom": 0.05,
            "n_cal": 40,
            "n_min": 10,
            "exchangeability_ref": "audit/exchangeability-1.json",
            "fpca_basis_ref": "none",
        },
        "error_control": {
            "elond_state_ref": "elond/state-1.json",
            "alpha_t": 0.05,
            "attempts_N": 1,
            "test_id_frozen_ref": "freeze/test-1.json",
            "frozen_test_id": test_id,
            "block_unit": "world_instance",
        },
        "counterexample_ref": "counterexamples/ce-1.json",
        "origin_category": "sindy",
        "data_identity": {
            "discovery": "dev-D-20261028",
            "calibration": "dev-C-20261028",
            "test": "dev-T-20261028",
        },
        "regression_ref": "regression/eq6-1.json",
        "entry_digest": fragment.content_digest() if fragment is not None else "a" * 64,
        "encoder_version": fragment.encoder_version if fragment is not None else "enc-v1",
        "prior_version": "fprior-v9-r5",
    }
    base.update(overrides)
    return PromotionEvidence(**base)
