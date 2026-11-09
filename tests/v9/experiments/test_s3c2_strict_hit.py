"""Unit test for S3-C2 strict hit vs loose hit discrimination.

Verifies that check_hit correctly discriminates between:
1. Strict hit: Candidate step falls within the continuous dwell period
   ending at event['prev_visit_t'].
2. Loose hit: Candidate step is anywhere on event['cell'].
3. Miss: Candidate step is on a different cell.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.experiments.s3.cues import check_hit, find_dwell_start


def test_dwell_start_and_strict_vs_loose_hit() -> None:
    # Synthetic trajectory of 25 steps
    # Steps 0..1: at (1, 1) [dwell interval 1]
    # Steps 2..3: at (1, 2), (1, 3)
    # Steps 4..6: at (1, 1) [dwell interval 2 ending at t=6]
    # Steps 7..19: visiting other cells
    # Step 20: return event at (1, 1)
    trajectory_cells = [
        (1, 1),  # t=0
        (1, 1),  # t=1
        (1, 2),  # t=2
        (1, 3),  # t=3
        (1, 1),  # t=4 (dwell 2 start)
        (1, 1),  # t=5
        (1, 1),  # t=6 (dwell 2 end / prev_visit_t)
        (2, 1),  # t=7
        (2, 2),  # t=8
        (2, 3),  # t=9
        (3, 3),  # t=10
        (3, 2),  # t=11
        (3, 1),  # t=12
        (4, 1),  # t=13
        (4, 2),  # t=14
        (4, 3),  # t=15
        (3, 2),  # t=16
        (2, 2),  # t=17
        (2, 1),  # t=18
        (1, 2),  # t=19
        (1, 1),  # t=20 (return event)
    ]

    steps = [
        {
            "t": t,
            "truth": {"x": cell[0], "y": cell[1]},
        }
        for t, cell in enumerate(trajectory_cells)
    ]

    event = {
        "t": 20,
        "cell": (1, 1),
        "prev_visit_t": 6,
        "interval": 14,
        "bucket": "long",
    }

    # Verify dwell start computation
    t_start = find_dwell_start(steps, prev_visit_t=6, target_cell=(1, 1))
    assert t_start == 4, f"Expected dwell start 4, got {t_start}"

    # Strict hits: t in [4, 5, 6]
    for cand_t in (4, 5, 6):
        is_strict, is_loose = check_hit(cand_t, event, steps)
        assert is_strict is True, f"cand_t={cand_t} should be strict hit"
        assert is_loose is True, f"cand_t={cand_t} should be loose hit"

    # Loose-only hits: t in [0, 1] (agent was at (1, 1), but before dwell 2)
    for cand_t in (0, 1):
        is_strict, is_loose = check_hit(cand_t, event, steps)
        assert is_strict is False, f"cand_t={cand_t} should NOT be strict hit"
        assert is_loose is True, f"cand_t={cand_t} should be loose hit"

    # Misses: steps on different cells
    for cand_t in (2, 3, 7, 8, 9, 10, 15, 19):
        is_strict, is_loose = check_hit(cand_t, event, steps)
        assert is_strict is False, f"cand_t={cand_t} should NOT be strict hit"
        assert is_loose is False, f"cand_t={cand_t} should NOT be loose hit"
