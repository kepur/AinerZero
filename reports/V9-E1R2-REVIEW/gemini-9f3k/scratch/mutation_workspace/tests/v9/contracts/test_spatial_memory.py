"""Contract: SpatialMemory (r5 §2, §3).

Positive: allowlisted writes, equivariant metric queries, version-checked
reads, budget-bounded consolidation, evidence-gated promotion, stable
parameter fingerprint.

Counter-examples: ``final`` partition write, foreign-latent-space read,
over-budget consolidation, promotion without independent evidence, promotion
fed by a teacher / LLM, promotion with v1 evidence (ADR-0014 §3 C1: fail-closed),
duplicate ids, malformed regions.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes import FakeSpatialMemory
from ainerzero.v9.interfaces.errors import (
    ContractViolation,
    EvidenceRequired,
    PartitionWriteRejected,
    UnsupportedInput,
)
from ainerzero.v9.interfaces.types import Fragment, PromotionEvidence, as_points

from conftest import v2_evidence


def fragment(fid: str, **overrides) -> Fragment:
    base = {
        "fragment_id": fid,
        "t_ticks": 100,
        "place": "room-a",
        "partition": "train",
        "encoder_version": "enc-v1",
        "metric": (0.0, 0.0),
    }
    base.update(overrides)
    return Fragment(**base)


@pytest.fixture
def memory(geometry) -> FakeSpatialMemory:
    return FakeSpatialMemory(geometry)


def promotable(fid: str, **overrides) -> Fragment:
    """A fragment that carries the ARCH §2 provenance triple (promotable)."""
    return fragment(
        fid,
        provenance_ref="obs/t0005.png",
        object_keys=("obj-a",),
        action_keys=("act-1",),
        **overrides,
    )


# ---- writes and the partition seal ---------------------------------------- #


def test_write_returns_ids_and_allows_allowlisted_partitions(memory):
    assert memory.write(fragment("f-train")) == "f-train"
    assert memory.write(fragment("f-dev", partition="development")) == "f-dev"
    assert len(memory) == 2


@pytest.mark.parametrize("partition", ["final", "quarantine"])
def test_write_refuses_non_allowlisted_partitions(memory, partition):
    with pytest.raises(PartitionWriteRejected) as caught:
        memory.write(fragment("f-x", partition=partition))
    assert caught.value.code == "partition_write_rejected"
    assert partition not in ("train", "development")
    assert len(memory) == 0  # nothing partially written


def test_write_rejects_duplicates_and_unknown_partitions(memory):
    memory.write(fragment("f-dup"))
    with pytest.raises(ContractViolation):
        memory.write(fragment("f-dup"))
    with pytest.raises(ValueError):  # unknown partition fails at construction
        fragment("f-unknown", partition="eval")
    with pytest.raises(ContractViolation):
        memory.write("not-a-fragment")


# ---- non-parametric guarantee --------------------------------------------- #


def test_parameter_fingerprint_is_stable_across_operations(memory, geometry):
    before = memory.parameter_fingerprint()
    memory.write(fragment("f-1"))
    after_write = memory.parameter_fingerprint()
    memory.transform({"dx": 1.0, "dy": 0.5, "dtheta": 0.2})
    after_transform = memory.parameter_fingerprint()
    memory.consolidate(budget=5)
    after_consolidate = memory.parameter_fingerprint()
    assert before == after_write == after_transform == after_consolidate
    assert len(before) == 64  # a real digest, not a placeholder


# ---- metric query and equivariance (式 5) --------------------------------- #


def test_metric_query_hits_and_misses_by_disk(memory):
    memory.write(fragment("f-near", metric=(0.1, 0.1)))
    memory.write(fragment("f-far", metric=(5.0, 5.0)))
    hit = memory.query_metric({"center": (0.0, 0.0), "radius_m": 1.0}, encoder_version="enc-v1")
    assert [f.fragment_id for f in hit.entries] == ["f-near"]
    assert hit.excluded == ()
    miss = memory.query_metric({"center": (0.0, 0.0), "radius_m": 0.05}, encoder_version="enc-v1")
    assert miss.entries == ()  # boundary: 0.141 > 0.05
    boundary = memory.query_metric(
        {"center": (0.1, 0.1), "radius_m": 0.0}, encoder_version="enc-v1"
    )
    assert [f.fragment_id for f in boundary.entries] == ["f-near"]  # distance 0 <= radius


def test_metric_query_transforms_equivariantly_with_self_motion(memory, geometry):
    memory.write(fragment("f-1", metric=(0.4, -0.2)))
    memory.write(fragment("f-2", metric=(-1.0, 0.7)))
    motion = {"dx": 0.6, "dy": -0.3, "dtheta": 0.5}
    center = (0.4, -0.2)
    radius = 0.5
    before = memory.query_metric(
        {"center": center, "radius_m": radius}, encoder_version="enc-v1"
    )
    assert [f.fragment_id for f in before.entries] == ["f-1"]
    memory.transform(motion)
    moved_center = tuple(
        geometry.act(geometry.exp((0.6, -0.3, 0.5)), as_points([center]))[0]
    )
    after = memory.query_metric(
        {"center": moved_center, "radius_m": radius}, encoder_version="enc-v1"
    )
    assert [f.fragment_id for f in after.entries] == [
        f.fragment_id for f in before.entries
    ], "the query set must move rigidly with the metric layer (式 5 equivariance)"


def test_metric_query_rejects_malformed_regions(memory):
    memory.write(fragment("f-1"))
    with pytest.raises(ContractViolation):
        memory.query_metric({"center": (0.0, 0.0)}, encoder_version="enc-v1")
    with pytest.raises(UnsupportedInput):
        memory.query_metric(
            {"center": (0.0, 0.0, 1.0), "radius_m": 1.0}, encoder_version="enc-v1"
        )
    with pytest.raises(UnsupportedInput):
        memory.query_metric({"center": (0.0, 0.0), "radius_m": -1.0}, encoder_version="enc-v1")


# ---- encoder-version fence ------------------------------------------------- #


def test_query_excludes_foreign_encoder_version(memory):
    """A v2 latent space must never read v1 entries (and must report the exclusion)."""
    memory.write(fragment("f-v1", metric=(0.0, 0.0)))
    result = memory.query_metric({"center": (0.0, 0.0), "radius_m": 1.0}, encoder_version="enc-v2")
    assert result.entries == ()
    assert [f.fragment_id for f in result.excluded] == ["f-v1"]
    assert result.encoder_version == "enc-v2"
    topology = memory.query_topology("room-a", encoder_version="enc-v2")
    assert topology.entries == ()
    assert [f.fragment_id for f in topology.excluded] == ["f-v1"]


def test_topology_query_filters_by_place_and_version(memory):
    memory.write(fragment("f-a", place="room-a"))
    memory.write(fragment("f-b", place="room-b"))
    result = memory.query_topology("room-a", encoder_version="enc-v1")
    assert [f.fragment_id for f in result.entries] == ["f-a"]
    with pytest.raises(UnsupportedInput):
        memory.query_topology("", encoder_version="enc-v1")


def test_every_entry_carries_its_encoder_version():
    with pytest.raises(ValueError):  # counter-example: a versionless write
        Fragment(
            fragment_id="f-x",
            t_ticks=1,
            place="room",
            partition="train",
            encoder_version="",
        )


# ---- consolidation budget -------------------------------------------------- #


def test_consolidation_never_exceeds_the_budget(memory):
    for index in range(5):
        memory.write(fragment(f"f-{index}", partition="development" if index else "train"))
    report = memory.consolidate(budget=2)
    assert report.budget == 2
    assert report.scanned <= 2
    assert report.kept <= report.scanned <= report.budget
    empty = memory.consolidate(budget=0)
    assert empty.scanned == 0 and empty.kept == 0
    everything = memory.consolidate(budget=99)
    assert everything.scanned == 5
    assert everything.promoted_candidates == ("f-1", "f-2", "f-3", "f-4")


@pytest.mark.parametrize("bad_budget", [-1, 1.5, True, "2"])
def test_consolidation_refuses_bad_budgets(memory, bad_budget):
    with pytest.raises(ContractViolation):
        memory.consolidate(bad_budget)


# ---- promotion evidence ---------------------------------------------------- #


def test_promote_moves_an_entry_into_slow(memory):
    stored = promotable("f-1")
    memory.write(stored)
    evidence = v2_evidence(stored)
    result = memory.promote("f-1", evidence)
    assert result["level"] == "slow"
    assert result["report_ref"] == evidence.report_ref
    assert memory.slow_items() == ("f-1",)
    assert memory.parameter_fingerprint()  # promotion changes no parameter


def test_promote_requires_independent_test_evidence(memory):
    memory.write(fragment("f-1"))
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", None)
    assert caught.value.code == "evidence_required"
    with pytest.raises(ValueError):  # wrong evidence kind fails at construction
        PromotionEvidence(kind="self_report", report_ref="r", producer="s", test_id="t")


def test_promote_refuses_teacher_and_llm_producers():
    for producer in ("teacher_main", "Teacher-T2", "llm", "assistant", "human_unreviewed"):
        with pytest.raises(EvidenceRequired) as caught:
            PromotionEvidence(
                kind="independent_test",
                report_ref="reports/x.md",
                producer=producer,
                test_id="t-1",
            )
        assert "never write SLOW" in caught.value.detail or "unregistered producer" in caught.value.detail


def test_promote_refuses_unknown_items(memory):
    memory.write(promotable("f-1"))
    with pytest.raises(ContractViolation) as caught:
        memory.promote("f-missing", v2_evidence())
    assert "unknown memory item" in str(caught.value)


def test_v1_evidence_is_refused_at_promote(memory):
    """ADR-0014 §3 C1: the old "v1 promotes" expectation is now a negative."""
    memory.write(promotable("f-1"))
    legacy = PromotionEvidence(
        kind="independent_test",
        report_ref="reports/V9-B2/independent.md",
        producer="contract-harness",
        test_id="v9-b2-independent-1",
    )
    assert legacy.schema_version == "v1"  # still constructible / readable
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", legacy)
    assert "schema_version='v2'" in caught.value.detail
    assert memory.slow_items() == ()


# ---- V9.B12 r2：起源硬门（V9.B13 K3）------------------------------------------ #


@pytest.mark.parametrize("origin", ["llm", "teacher"])
def test_llm_or_teacher_origin_cannot_reach_slow_even_with_a_legitimate_producer(memory, origin):
    """ADR-0014 §2 D5：LLM/教师起源只进 MID。producer 与 trusted_context 全部合法、其余字段全部合法时，仍必须被拒。"""
    stored = promotable("f-1")
    memory.write(stored)
    evidence = v2_evidence(stored, origin_category=origin)       # producer='contract-harness' 是登记的独立出具者
    with pytest.raises(EvidenceRequired) as caught:
        memory.promote("f-1", evidence)
    assert origin in caught.value.detail and "MID" in caught.value.detail
    assert memory.slow_items() == ()


@pytest.mark.parametrize("origin", ["sindy", "symbolic", "human", "engineered"])
def test_other_origins_still_promote_when_everything_else_is_legitimate(memory, origin):
    """正对照：同一份证据只把起源换成非 LLM/教师，就可以晋升——证明上面的拒绝来自起源门，而不是环境或别的守卫。"""
    stored = promotable("f-1")
    memory.write(stored)
    result = memory.promote("f-1", v2_evidence(stored, origin_category=origin))
    assert result["level"] == "slow" and memory.slow_items() == ("f-1",)


def test_origin_guard_is_a_standalone_fail_closed_function():
    """起源守卫是独立函数（真实实现也走 ``require_evidence``）：LLM/教师抛错，其余原样返回；非字符串/未知值不被当作放行理由。"""
    from ainerzero.v9.interfaces.validation import SLOW_FORBIDDEN_ORIGINS, require_slow_eligible_origin

    assert set(SLOW_FORBIDDEN_ORIGINS) == {"llm", "teacher"}
    for origin in SLOW_FORBIDDEN_ORIGINS:
        with pytest.raises(EvidenceRequired):
            require_slow_eligible_origin(origin)
    assert require_slow_eligible_origin("sindy") == "sindy"
