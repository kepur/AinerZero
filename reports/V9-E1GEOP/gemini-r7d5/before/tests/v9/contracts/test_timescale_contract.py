"""Contract: TimeScaleAdapter (r5 §3, §4 式 3).

Positive: explicit-dt alignment on the registered 120 Hz clock, frozen macro
rules, real step durations.

Counter-examples: an unregistered macro rule, a frame-index-shaped ``delta_s``,
an empty or malformed action sequence, an unknown action class, a negative or
non-integer tick count, an unregistered level.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes.timescale import REGISTERED_MACRO_RULES, FakeTimeScaleAdapter
from ainerzero.v9.interfaces.errors import ContractViolation, UnsupportedInput
from ainerzero.v9.interfaces.types import SIM_HZ, LevelSpec


@pytest.fixture
def scale() -> FakeTimeScaleAdapter:
    return FakeTimeScaleAdapter(
        [
            LevelSpec(level=0, stride_ticks=1, macro_rule="action_histogram", macro_dim=3,
                      action_classes=("move", "turn", "stay")),
            LevelSpec(level=1, stride_ticks=12, macro_rule="displacement_heading", macro_dim=3),
            LevelSpec(level=2, stride_ticks=120, macro_rule="displacement_heading", macro_dim=3),
        ]
    )


def test_registered_levels_are_exposed_lowest_first(scale):
    levels = scale.levels()
    assert [spec.level for spec in levels] == [0, 1, 2]
    assert [spec.stride_ticks for spec in levels] == [1, 12, 120]
    assert {spec.macro_rule for spec in levels} == set(REGISTERED_MACRO_RULES)


# ---- alignment against the 120 Hz clock ----------------------------------- #


def test_align_reports_real_dt_not_the_stride(scale):
    """式 3: delta_s is the real elapsed time, never stride/120 or a frame index."""
    for alignment in scale.align(t_ticks=25, dt_ticks=7):
        assert alignment.delta_s == pytest.approx(7 / SIM_HZ)
        assert alignment.delta_s != pytest.approx(alignment.stride_ticks / SIM_HZ)
        assert alignment.t_ticks == 25
        assert alignment.dt_ticks == 7


def test_align_accumulates_irregular_dt(scale):
    steps = [(10, 7), (17, 5), (22, 12), (34, 3)]
    total_ticks = 0
    total_s = 0.0
    for t_ticks, dt_ticks in steps:
        alignments = scale.align(t_ticks, dt_ticks)
        assert {a.delta_s for a in alignments} == {dt_ticks / SIM_HZ}
        total_ticks += dt_ticks
        total_s += alignments[0].delta_s
    assert total_ticks == 27
    assert total_s == pytest.approx(27 / SIM_HZ)


def test_align_alignment_is_per_level_and_indexed(scale):
    alignments = {a.level: a for a in scale.align(t_ticks=25, dt_ticks=7)}
    assert alignments[0].aligned_ticks == 25 and alignments[0].step_index == 25
    assert alignments[1].aligned_ticks == 24 and alignments[1].step_index == 2
    assert alignments[2].aligned_ticks == 0 and alignments[2].step_index == 0
    for alignment in alignments.values():
        assert alignment.aligned_ticks <= alignment.t_ticks
        assert alignment.aligned_ticks % alignment.stride_ticks == 0


@pytest.mark.parametrize(("t_ticks", "dt_ticks"), [(-1, 5), (0, -5), (1.5, 5), (0, True)])
def test_align_rejects_bad_ticks(scale, t_ticks, dt_ticks):
    with pytest.raises(UnsupportedInput):
        scale.align(t_ticks, dt_ticks)


# ---- macro rules ----------------------------------------------------------- #


def test_displacement_heading_aggregates_the_stride(scale):
    actions = [
        {"dx": 0.4, "dy": 0.1, "dtheta": 0.05, "dt_ticks": 4},
        {"dx": -0.1, "dy": 0.2, "dtheta": -0.05, "dt_ticks": 3},
        {"dy": 0.05, "dt_ticks": 5},  # missing keys default to zero
    ]
    macro = scale.macro_action(1, actions)
    assert macro.rule == "displacement_heading"
    assert macro.level == 1
    assert list(macro.values) == pytest.approx([0.3, 0.35, 0.0])
    assert macro.delta_ticks == 12
    assert macro.delta_s == pytest.approx(12 / SIM_HZ)


def test_action_histogram_counts_registered_classes(scale):
    actions = [
        {"action_class": "move", "dt_ticks": 1},
        {"action_class": "move", "dt_ticks": 1},
        {"action_class": "turn", "dt_ticks": 1},
    ]
    macro = scale.macro_action(0, actions)
    assert macro.rule == "action_histogram"
    assert list(macro.values) == [2.0, 1.0, 0.0]
    assert macro.delta_s == pytest.approx(3 / SIM_HZ)


def test_macro_action_rejects_unknown_classes_and_empty_input(scale):
    with pytest.raises(ContractViolation) as caught:  # counter-example: unregistered class
        scale.macro_action(0, [{"action_class": "teleport", "dt_ticks": 1}])
    assert caught.value.code == "contract_violation"
    with pytest.raises(ContractViolation):  # counter-example: nothing to aggregate
        scale.macro_action(1, [])
    with pytest.raises(ContractViolation):  # counter-example: not a mapping
        scale.macro_action(1, ["move"])
    with pytest.raises(ContractViolation):  # counter-example: bad dt
        scale.macro_action(1, [{"dx": 0.0, "dt_ticks": -3}])
    with pytest.raises(ContractViolation):  # counter-example: unknown level
        scale.macro_action(7, [{"dx": 0.0, "dt_ticks": 1}])


def test_macro_dim_mismatch_is_refused_per_level():
    """A displacement level declaring the wrong dimension cannot aggregate."""
    scale = FakeTimeScaleAdapter(
        [LevelSpec(level=0, stride_ticks=1, macro_rule="displacement_heading", macro_dim=2)]
    )
    with pytest.raises(ContractViolation) as caught:
        scale.macro_action(0, [{"dx": 1.0, "dy": 2.0, "dtheta": 3.0, "dt_ticks": 1}])
    assert "macro_dim=3" in str(caught.value)


# ---- construction guards --------------------------------------------------- #


def test_unregistered_macro_rule_is_refused_at_construction():
    with pytest.raises(ContractViolation) as caught:
        FakeTimeScaleAdapter(
            [LevelSpec(level=0, stride_ticks=1, macro_rule="neural_rollout", macro_dim=3)]
        )
    assert "not registered" in str(caught.value)


def test_construction_guards():
    with pytest.raises(ContractViolation):
        FakeTimeScaleAdapter([])  # no levels
    with pytest.raises(ContractViolation):  # duplicate level
        FakeTimeScaleAdapter(
            [
                LevelSpec(level=0, stride_ticks=1, macro_rule="displacement_heading", macro_dim=3),
                LevelSpec(level=0, stride_ticks=2, macro_rule="displacement_heading", macro_dim=3),
            ]
        )
    with pytest.raises(ContractViolation):  # histogram without classes
        FakeTimeScaleAdapter(
            [LevelSpec(level=0, stride_ticks=1, macro_rule="action_histogram", macro_dim=3)]
        )
    with pytest.raises(ContractViolation):  # dim != len(action_classes)
        FakeTimeScaleAdapter(
            [
                LevelSpec(
                    level=0,
                    stride_ticks=1,
                    macro_rule="action_histogram",
                    macro_dim=2,
                    action_classes=("a", "b", "c"),
                )
            ]
        )
    with pytest.raises(ContractViolation):  # not a LevelSpec
        FakeTimeScaleAdapter([{"level": 0}])
