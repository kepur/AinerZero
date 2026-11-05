"""Regression tests from B3 probes (D-021 §3.5).

These probes were findings in r1 and are now enforced as contract tests.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes import FakePerceptionEncoder, FakeWorldBrain
from ainerzero.v9.interfaces.errors import (
    EvidenceRequired,
    ReferenceRejected,
    TimeWhitelistRejected,
    TruthFieldRejected,
)
from ainerzero.v9.interfaces.types import PromotionEvidence


def _payload(t=10, dt=4, **extra):
    p = {
        "time": {"sim_hz": 120, "t_ticks": t, "dt_ticks": dt, "dt_s": dt / 120.0},
        "episode_start": False,
        "observation": {"channels": [{"kind": "rgb"}]},
        "pose_sensor_if_allowed": None,
        "visibility": {"agent_visible": True},
        "sensor_noise": {
            "rgb": {"model": "none", "params": {}},
        },
        "last_action_result": {"action_seq": 4, "status": "executed", "reason_code": "none"},
        "task_instruction": {"text": "go", "goal": {"kind": "symbolic", "description": "target"}},
    }
    p.update(extra)
    return p


def _enc_payload(uri, t=10):
    p = _payload(t=t)
    p["observation"]["channels"][0]["image"] = {"uri": uri, "sha256": "a" * 64}
    p["observation"]["channels"][0]["width"] = 320
    p["observation"]["channels"][0]["height"] = 180
    return p


def test_probe_ref_traversal():
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/../private/answers"))
    assert "relative path" in caught.value.detail


def test_probe_ref_future_ext():
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/cam/t999.png", t=10))
    assert "after the packet cut" in caught.value.detail


def test_probe_ref_fail_closed():
    encoder = FakePerceptionEncoder()
    # 999.png has numbers but no 't' or 'frame' marker; should be rejected by fail-closed
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/cam/999.png", t=10))
    assert "fail-closed" in caught.value.detail


def test_probe_time_stalled():
    brain = FakeWorldBrain()
    brain.step(_payload(t=10, dt=4))
    with pytest.raises(TimeWhitelistRejected) as caught:
        brain.step(_payload(t=10, dt=4))
    assert "t_ticks" in caught.value.detail and "detected" in caught.value.detail


def test_probe_time_jump():
    brain = FakeWorldBrain()
    brain.step(_payload(t=10, dt=4))
    with pytest.raises(TimeWhitelistRejected) as caught:
        brain.step(_payload(t=410, dt=4))
    assert "jump" in caught.value.detail


def test_probe_truth_nfkc_variant():
    brain = FakeWorldBrain()
    # Full-width 'Ｐ' (U+FF30) should be normalized to 'P' and then lowered to 'p'
    # which hits "position" in L1.
    with pytest.raises(TruthFieldRejected) as caught:
        brain.step(_payload(visibility={"Ｐosition": [1, 2]}))
    assert "L1" in caught.value.detail


def test_probe_teacher_alias():
    # distilled-teacher-v2 should be rejected as a producer category that cannot write SLOW
    with pytest.raises(EvidenceRequired) as caught:
        PromotionEvidence(
            kind="independent_test",
            report_ref="r",
            producer="distilled-teacher-v2",
            test_id="t",
        )
    assert "not allowed to write SLOW" in caught.value.detail


def test_probe_llm_alias():
    # LLM-gpt should be rejected as a producer category that cannot write SLOW
    with pytest.raises(EvidenceRequired) as caught:
        PromotionEvidence(
            kind="independent_test",
            report_ref="r",
            producer="LLM-gpt",
            test_id="t",
        )
    assert "not allowed to write SLOW" in caught.value.detail


# ---- r3 / B11：全角斜杠与查询串绕过 -------------------------------------- #


def test_probe_ref_fullwidth_slash_to_private():
    """B11：``obs/／private/answers`` 曾被接受；须 NFKC/非 ASCII fail-closed。"""
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/\uFF0Fprivate/answers"))
    detail = caught.value.detail.lower()
    assert "nfkc" in detail or "non-ascii" in detail


def test_probe_ref_fullwidth_slash_literal():
    """同一绕过的字面全角斜杠写法（与上条等价，防拷贝时漏测）。"""
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected):
        encoder.encode(_enc_payload("obs/／private/answers"))


def test_probe_ref_query_future_tick():
    """B11：``obs/cam/x?t=999`` 曾被接受；查询串一律拒绝。"""
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/cam/x?t=999"))
    assert "query string" in caught.value.detail


def test_probe_ref_query_nfkc_variant_fullwidth_question():
    """查询分隔符的全角 ``？``：NFKC 后变为 ``?``，须因规范化不一致被拒。"""
    encoder = FakePerceptionEncoder()
    with pytest.raises(ReferenceRejected) as caught:
        encoder.encode(_enc_payload("obs/cam/x\uFF1Ft=999"))
    detail = caught.value.detail.lower()
    assert "nfkc" in detail or "non-ascii" in detail
