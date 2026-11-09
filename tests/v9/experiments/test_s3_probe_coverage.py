"""Test GridLab-S3 Probe P-a Coverage and Return Event Statistics.

Requirements per DESIGN-r2.md §5 (Probe P-a):
Across 100 worlds:
- Median unique cells visited per episode >= 60
- Max fraction of steps at most visited cell <= 0.15
- Fraction of episodes with long-interval swapped token event >= 90%
- Overall return events swapped ratio in [0.40, 0.60]
"""

from __future__ import annotations

import statistics as stats

import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode


def test_probe_p_a_coverage_and_swap_ratio() -> None:
    """Run Probe P-a over 100 worlds and assert all frozen thresholds."""
    n_worlds = 100
    namespace = spec.NAMESPACE_PROBE

    unique_cells_list: list[int] = []
    top_cell_ratios: list[float] = []
    has_long_swapped_flags: list[bool] = []
    all_events: list[dict] = []

    for w_idx in range(n_worlds):
        w_seed = derive_seed(namespace, "world", w_idx)
        ep_seed = derive_seed(namespace, "ep", w_idx, 0)
        episode = generate_episode(w_seed, ep_seed, family="F1")

        summary = episode["summary"]
        unique_cells_list.append(summary["unique_cells_visited"])
        top_cell_ratios.append(summary["most_frequent_cell_ratio"])
        has_long_swapped_flags.append(summary["long_swapped_events"] > 0)
        all_events.extend(episode["events"])

    median_unique = stats.median(unique_cells_list)
    max_top_ratio = max(top_cell_ratios)
    long_swapped_frac = sum(has_long_swapped_flags) / len(has_long_swapped_flags)

    swapped_events_count = sum(1 for e in all_events if e["swapped"])
    total_events_count = len(all_events)
    assert total_events_count > 0, "No return events generated across 100 worlds"
    swapped_ratio = swapped_events_count / total_events_count

    # Assert frozen thresholds (doors read measured values, no hardcoded passes)
    assert median_unique >= spec.PA_DISTINCT_CELLS_MEDIAN_MIN, (
        f"Median unique cells {median_unique} < minimum {spec.PA_DISTINCT_CELLS_MEDIAN_MIN}"
    )
    assert max_top_ratio <= spec.PA_TOP_CELL_FRAC_MAX, (
        f"Max top cell fraction {max_top_ratio:.4f} > maximum {spec.PA_TOP_CELL_FRAC_MAX}"
    )
    assert long_swapped_frac >= spec.PA_LONG_SWAPPED_EPISODES_FRAC_MIN, (
        f"Long swapped episode fraction {long_swapped_frac * 100:.1f}% < "
        f"minimum {spec.PA_LONG_SWAPPED_EPISODES_FRAC_MIN * 100:.1f}%"
    )
    assert spec.PA_SWAPPED_RATIO_MIN <= swapped_ratio <= spec.PA_SWAPPED_RATIO_MAX, (
        f"Swapped ratio {swapped_ratio:.4f} outside [{spec.PA_SWAPPED_RATIO_MIN}, {spec.PA_SWAPPED_RATIO_MAX}]"
    )
