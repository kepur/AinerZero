"""Contract: φ posterior and MSG route records (ADR-0014 r3 §3 C7, M6 + R1).

Why a separate carrier exists (R1 evidence, reproduced here as a test): the fake
scheduler's full fallback does ``belief[node] + 1`` for **every** key of the belief
mapping, and ``require_graph`` demands neighbour sequences, while
``BeliefSummary.belief`` is a ``PoseBelief``.  A ``ParamBelief`` therefore cannot
live in the scheduler's node mapping — hence ``ParamBeliefStore``.

Positive: a well-formed belief round-trips; the store only accepts writes from the
MSG ``PARAMETRIC`` branch; route records summarise into 8 buckets.

Counter-examples: non-symmetric / non-PSD covariance, missing dimensionless scale,
time going backwards, wrong route code, missing NIS statistic on 4a/4b, mismatched
registration SHA, overwriting a delivered ``msg_routes.json``.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from ainerzero.v9.fakes import FakeUpdateScheduler
from ainerzero.v9.interfaces.cmfl import (
    MSG_ROUTE_ORDER,
    NIS_ROUTE_CODES,
    PARAMETRIC_ROUTE_CODE,
    ROUTE_CODES,
    MSGRouteLog,
    MSGRouteRecord,
    ParamBelief,
    ParamBeliefStore,
)
from ainerzero.v9.interfaces.errors import ContractViolation, UnsupportedInput

REGISTRATION_SHA = "c" * 64


def belief(mean=(0.1, -0.2), *, ticks: int = 120) -> ParamBelief:
    cov = np.diag([0.01, 0.02])
    return ParamBelief(
        mean=mean,
        cov=cov.tolist(),
        dimensionless_scale=(1.0, 0.5),
        updated_at_ticks=ticks,
    )


# ---- ParamBelief ----------------------------------------------------------- #


def test_param_belief_round_trips_and_exposes_arrays():
    stored = belief()
    assert stored.dimension == 2
    assert np.allclose(stored.mean_array(), [0.1, -0.2])
    assert np.allclose(stored.cov_array(), np.diag([0.01, 0.02]))
    assert stored.to_json()["updated_at_ticks"] == 120


def test_param_belief_refuses_asymmetric_covariance():
    with pytest.raises(UnsupportedInput) as caught:
        ParamBelief(mean=(0.0, 0.0), cov=((1.0, 0.5), (0.0, 1.0)), dimensionless_scale=(1.0, 1.0), updated_at_ticks=1)
    assert "symmetric" in str(caught.value)


def test_param_belief_refuses_indefinite_covariance():
    with pytest.raises(UnsupportedInput) as caught:
        ParamBelief(mean=(0.0, 0.0), cov=((1.0, 2.0), (2.0, 1.0)), dimensionless_scale=(1.0, 1.0), updated_at_ticks=1)
    assert "positive semi-definite" in str(caught.value)


def test_param_belief_requires_a_dimensionless_scale():
    """§2 D1 row 6: τ_id only means something on a non-dimensionalised φ."""
    with pytest.raises(UnsupportedInput) as caught:
        ParamBelief(mean=(0.0, 0.0), cov=((1.0, 0.0), (0.0, 1.0)), dimensionless_scale=(1.0,), updated_at_ticks=1)
    assert "dimensionless_scale" in str(caught.value)
    with pytest.raises(UnsupportedInput):
        ParamBelief(mean=(0.0,), cov=((1.0,),), dimensionless_scale=(0.0,), updated_at_ticks=1)


def test_param_belief_refuses_non_finite_and_negative_ticks():
    with pytest.raises(UnsupportedInput):
        ParamBelief(mean=(math.nan,), cov=((1.0,),), dimensionless_scale=(1.0,), updated_at_ticks=1)
    with pytest.raises(UnsupportedInput):
        ParamBelief(mean=(0.0,), cov=((1.0,),), dimensionless_scale=(1.0,), updated_at_ticks=-1)


# ---- ParamBeliefStore ------------------------------------------------------ #


def test_store_is_not_a_mapping():
    """It must not be mistaken for the scheduler's node mapping (R1)."""
    from collections.abc import Mapping

    store = ParamBeliefStore(registration_sha=REGISTRATION_SHA)
    assert not isinstance(store, Mapping)
    assert len(store) == 0


def test_store_accepts_parametric_writes_only():
    store = ParamBeliefStore(registration_sha=REGISTRATION_SHA)
    store.put("phi/room-a", belief(), route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)
    assert store.get("phi/room-a").updated_at_ticks == 120
    assert store.ids() == ("phi/room-a",)
    assert store.version == 1
    for other in ROUTE_CODES:
        if other == PARAMETRIC_ROUTE_CODE:
            continue
        with pytest.raises(ContractViolation) as caught:
            store.put("phi/room-a", belief(ticks=240), route_code=other, registration_sha=REGISTRATION_SHA)
        assert "PARAMETRIC" in str(caught.value)


def test_store_refuses_time_travel_and_foreign_values():
    store = ParamBeliefStore(registration_sha=REGISTRATION_SHA)
    store.put("phi", belief(ticks=240), route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)
    with pytest.raises(ContractViolation) as caught:
        store.put("phi", belief(ticks=120), route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)
    assert "backwards" in str(caught.value)
    with pytest.raises(UnsupportedInput):
        store.put("phi", {"mean": [0.0]}, route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)


def test_store_refuses_a_foreign_registration():
    store = ParamBeliefStore(registration_sha=REGISTRATION_SHA)
    with pytest.raises(ContractViolation) as caught:
        store.put("phi", belief(), route_code=PARAMETRIC_ROUTE_CODE, registration_sha="d" * 64)
    assert "registration" in str(caught.value)
    with pytest.raises(ContractViolation):
        store.put("phi", belief(), route_code=PARAMETRIC_ROUTE_CODE)


def test_store_digest_changes_when_the_posterior_moves():
    store = ParamBeliefStore(registration_sha=REGISTRATION_SHA)
    store.put("phi", belief(ticks=120), route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)
    first = store.digest()
    store.put("phi", belief(mean=(0.3, -0.2), ticks=240), route_code=PARAMETRIC_ROUTE_CODE, registration_sha=REGISTRATION_SHA)
    assert store.digest() != first
    store.drop("phi")
    assert store.ids() == ()
    with pytest.raises(ContractViolation):
        store.drop("phi")


def test_param_belief_cannot_be_fed_to_the_scheduler_belief_mapping():
    """R1 的直接证据：放进 ``UpdateScheduler.update`` 的节点映射就会炸。"""
    scheduler = FakeUpdateScheduler(f_max=2, u_max=0.1)
    with pytest.raises(TypeError):
        scheduler.update({"node-a": belief()}, ("node-a",))
    # 正常节点信念（标量）照旧可用，说明我们只是没把参数塞进去
    result = scheduler.update({"node-a": 0.0}, ("node-a",))
    assert result.belief["node-a"] == 1.0


# ---- MSGRouteRecord ------------------------------------------------------- #


def test_route_record_requires_a_registered_code_and_reason():
    record = MSGRouteRecord(
        context_id="ctx-1",
        t_ticks=120,
        route_code="SUFFICIENT",
        reason="NIS inside the two-sided band",
        nis_stat=3.4,
        dof=3,
        registration_sha=REGISTRATION_SHA,
    )
    assert record.to_json()["route_code"] == "SUFFICIENT"
    with pytest.raises(UnsupportedInput):
        MSGRouteRecord(context_id="ctx-1", t_ticks=120, route_code="LEARN", reason="x")
    with pytest.raises(UnsupportedInput):
        MSGRouteRecord(context_id="ctx-1", t_ticks=120, route_code="ABSTAIN", reason="")


@pytest.mark.parametrize("code", NIS_ROUTE_CODES)
def test_nis_routes_must_record_the_statistic(code):
    with pytest.raises(UnsupportedInput) as caught:
        MSGRouteRecord(context_id="ctx-1", t_ticks=120, route_code=code, reason="no stats")
    assert "nis_stat" in str(caught.value)
    record = MSGRouteRecord(
        context_id="ctx-1", t_ticks=120, route_code=code, reason="lower tail", nis_stat=0.4, dof=3
    )
    assert record.nis_stat == 0.4


def test_route_record_validates_the_registration_digest():
    with pytest.raises(UnsupportedInput):
        MSGRouteRecord(context_id="ctx-1", t_ticks=120, route_code="ABSTAIN", reason="x", registration_sha="short")


def test_route_log_counts_all_eight_codes(tmp_path):
    log = MSGRouteLog(registration_sha=REGISTRATION_SHA)
    log.record(
        MSGRouteRecord(
            context_id="ctx-1",
            t_ticks=120,
            route_code="SUFFICIENT",
            reason="band",
            nis_stat=3.4,
            dof=3,
            registration_sha=REGISTRATION_SHA,
        )
    )
    log.record(
        MSGRouteRecord(
            context_id="ctx-2", t_ticks=240, route_code="ABSTAIN", reason="outside D_permit",
            registration_sha=REGISTRATION_SHA,
        )
    )
    counts = log.counts()
    assert tuple(counts) == MSG_ROUTE_ORDER
    assert len(counts) == 8
    assert counts["SUFFICIENT"] == 1 and counts["ABSTAIN"] == 1
    assert counts["COVARIANCE_INCONSISTENT"] == 0  # 单独计类，缺省为 0

    target = log.to_json(tmp_path / "msg_routes.json")
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["route_order"] == list(MSG_ROUTE_ORDER)
    assert document["registration_sha"] == REGISTRATION_SHA
    assert len(document["records"]) == 2


def test_route_log_refuses_a_foreign_registration_and_overwrite(tmp_path):
    log = MSGRouteLog(registration_sha=REGISTRATION_SHA)
    with pytest.raises(ContractViolation):
        log.record(
            MSGRouteRecord(
                context_id="ctx-1", t_ticks=1, route_code="ABSTAIN", reason="x", registration_sha="e" * 64
            )
        )
    target = tmp_path / "msg_routes.json"
    log.to_json(target)
    with pytest.raises(ContractViolation) as caught:
        log.to_json(target)
    assert "never overwrite" in str(caught.value)
