"""P214 复核者建议补的分析测试（纯 CPU）。不改仓库测试；由 run_proposed_tests.py 复制进隔离副本的
tests/v9/experiments/ 下运行，借用同目录 test_s4_analysis_p2.py 的合成记录。每条对应一个存活变异：
在被审提交上应通过，在对应变异上应失败。"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import analysis_p2 as P2

import test_s4_analysis_p2 as T


def _st(value, ci_low, ci_high, bonf_low, bonf_high):
    return {"value": value, "ci_low": ci_low, "ci_high": ci_high, "bonf_low": bonf_low, "bonf_high": bonf_high}


# X01：门读 Bonferroni 区间，不读 95% 区间。每组都是「95% 界能过、Bonferroni 界不过」。
@pytest.mark.parametrize("key,gate,stat", [
    ("GN", "GN", _st(0.0, -0.02, 0.02, -0.031, 0.03)),
    ("GA", "GA", _st(0.06, 0.01, 0.09, -0.001, 0.10)),
    ("GC", "GC", _st(0.95, 0.60, 1.10, 0.50, 1.20)),
    ("GK1_all", "GK1", _st(0.90, 0.86, 0.94, 0.849, 0.95)),
    ("GK1_all", "GK1", _st(0.90, 0.86, 0.94, 0.85, 0.951)),
    ("GK1_collision", "GK1", _st(0.88, 0.82, 0.91, 0.80, 0.92)),
    ("GK2_non_collision", "GK2", _st(0.90, 0.82, 0.93, 0.80, 0.95)),
    ("GK2_collision", "GK2", _st(0.82, 0.70, 0.88, 0.65, 0.90)),
    ("GD_D", "GD", _st(0.85, 0.75, 0.90, 0.70, 0.92)),
    ("GD_ratio", "GD", _st(0.03, 0.02, 0.14, 0.01, 0.151)),
    ("GX_diff", "GX", _st(0.08, 0.02, 0.11, 0.0, 0.12)),
    ("GX_C", "GX", _st(1.0, 0.50, 1.20, 0.40, 1.30)),
])
def test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones(key, gate, stat) -> None:
    st = T._passing()
    st[key] = stat
    passed, neg = P2.decide(st)
    assert not passed[gate] and neg


# X02：11 个门统计都用 m = 11（Bonferroni 区间严格宽于 95% 区间），负对照两项用 m = 1（两者相同）。
def test_every_gate_statistic_is_bonferroni_corrected_and_the_control_is_not() -> None:
    st = P2.gate_stats(T.records(), T.records(100, "extrap", seed=1, coll_share=0.38))
    gate_keys = [k for keys in P2.GATE_STATS.values() for k in keys]
    assert len(gate_keys) == P2.N_COMPARISONS == 11
    for k in gate_keys:
        s = st[k]
        assert s["bonf_low"] < s["ci_low"] and s["bonf_high"] > s["ci_high"], k
    for k in ("neg_C", "neg_D"):
        assert st[k]["bonf_low"] == st[k]["ci_low"] and st[k]["bonf_high"] == st[k]["ci_high"], k


# X03：GX 的 C 读外推记录。外推上 L-int-g 只在没有碰撞的事件上好（C = 0），主评测正常。
def test_GX_reads_the_extrapolation_records() -> None:
    ext = T.records(100, "extrap", seed=1, coll_share=0.38,
                    spec={"L-int-g": (0.42, 0.97, 0.90, 0.88, 0.91, 0.83)})
    r = T._eval(extrap=ext)
    g = r["gates"]
    assert g["GC"]["passed"]
    assert g["GX"]["GX_diff"]["value"] >= 0.03          # 差值那一半能过
    assert not g["GX"]["passed"] and g["GX"]["GX_C"]["value"] < 0.3


# X04：每个事件的对错与重新出现覆盖率按三个种子平均。
def test_event_values_are_averaged_over_the_three_seeds() -> None:
    recs = T.records(2, n_events=4)
    for r in recs:
        for s, val in zip(P2.SEEDS, (1, 0, 0)):
            r["cells"][P2.cell_key("L-int-g", s)]["correct"] = [val] * 4
            r["cells"][P2.cell_key("L-int-g", s)]["reappear"] = [val] * 4
    np.testing.assert_allclose(P2.event_sums(recs, "L-int-g", "all"), [4 / 3, 4 / 3])
    np.testing.assert_allclose(P2.event_sums(recs, "L-int-g", "all", "reappear"), [4 / 3, 4 / 3])
