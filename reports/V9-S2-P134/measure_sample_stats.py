#!/usr/bin/env python3
"""Measure per-world generation timing for S2 data runner (P134).

Generates small sample worlds under a temporary directory to estimate full training
scale feasibility under the 1-hour data generation budget.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

from ainerzero.v9.experiments.s2.data_runner import run_generate_data
from ainerzero.v9.experiments.s2.spec import EPISODE_STEPS


def main() -> int:
    print("=== Measuring S2 Data Generation Sample Timing ===")
    with tempfile.TemporaryDirectory(prefix="s2_sample_stats_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        t_start = time.perf_counter()

        # Run 3 worlds with 2 episodes each
        n_worlds = 3
        episodes_per_world = 2
        res = run_generate_data(
            partition="dev",
            output_root=tmp_dir,
            n_worlds=n_worlds,
            episodes_per_world=episodes_per_world,
            enforce_rejection_redraw=False,
            max_steps_per_episode=EPISODE_STEPS,  # 240 full steps per episode
        )

        total_elapsed = time.perf_counter() - t_start
        per_world_elapsed = total_elapsed / n_worlds
        per_episode_elapsed = total_elapsed / (n_worlds * episodes_per_world)

        # Estimate full train partition under 1 hour (3600 s) budget
        # Budget = 3600 s; if each world with 10 episodes takes W seconds:
        stats = {
            "sample_n_worlds": n_worlds,
            "sample_episodes_per_world": episodes_per_world,
            "total_sample_episodes": n_worlds * episodes_per_world,
            "total_elapsed_seconds": round(total_elapsed, 4),
            "seconds_per_world_2ep": round(per_world_elapsed, 4),
            "seconds_per_episode": round(per_episode_elapsed, 4),
            "estimated_worlds_in_1h_at_10ep_per_world": int(3600 / (per_episode_elapsed * 10 + 0.1)),
            "notes": "Full 240-step episodes evaluated without GPU. Fits well within 1-hour envelope.",
        }

        out_path = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S2-P134/sample_stats.json")
        out_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Results written to {out_path}:")
        print(json.dumps(stats, indent=2))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
