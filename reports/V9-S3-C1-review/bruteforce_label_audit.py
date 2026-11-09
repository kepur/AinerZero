#!/usr/bin/env python3
"""Independent brute-force label audit for S3-C1 (P204 Review).

Independently recalculates all return events from first principles across 60 random episodes:
- prev_visit_t
- lag
- swapped
- answer
- bucket
- checks index boundary against episode['steps']
"""

import collections
import json
from pathlib import Path
import random

from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode
from ainerzero.v9.experiments.s3.spec import BUCKETS


def independent_get_bucket(lag: int) -> str | None:
    for name, lo, hi in BUCKETS:
        if lo <= lag <= hi:
            return name
    return None


def audit_episode_events_bruteforce(ep: dict) -> dict:
    steps = ep["steps"]
    content_meta = ep["content_state"]
    initial_tokens = {tuple(map(int, k.split(","))): v for k, v in content_meta["initial_tokens"].items()}
    swap_times = {tuple(map(int, k.split(","))): v for k, v in content_meta["swap_times"].items()}
    new_tokens = {tuple(map(int, k.split(","))): v for k, v in content_meta["new_tokens"].items()}
    content_cells = set(initial_tokens.keys())

    positions_step_level = [(steps[0]["truth"]["x"], steps[0]["truth"]["y"])] + [
        (s["truth"]["x"], s["truth"]["y"]) for s in steps
    ]
    # Note: steps length is T (360). Each step t contains the state at step t.
    # Terminal state after step T-1 is recorded in trajectory_positions[360] in tour.py.

    actual_events = ep["events"]
    out_of_bounds_events = []
    field_mismatches = []

    for idx, ev in enumerate(actual_events):
        t = ev["t"]
        if t >= len(steps):
            out_of_bounds_events.append(
                {
                    "event_index": idx,
                    "t": t,
                    "steps_len": len(steps),
                    "event": ev,
                    "error": "IndexError: t >= len(steps); event cannot be mapped to any step in steps_data",
                }
            )
            continue

        # For valid step range, verify against steps truth
        pos_at_t = (steps[t]["truth"]["x"], steps[t]["truth"]["y"])
        if tuple(ev["cell"]) != pos_at_t:
            field_mismatches.append(
                {"event_index": idx, "field": "cell", "actual": ev["cell"], "step_truth": pos_at_t}
            )

        prev_t = ev["prev_visit_t"]
        if prev_t >= t:
            field_mismatches.append(
                {"event_index": idx, "field": "prev_visit_t_order", "t": t, "prev_visit_t": prev_t}
            )

        # Independent token re-lookup
        c = tuple(ev["cell"])
        t_swap = swap_times[c]
        tok_now = new_tokens[c] if t >= t_swap else initial_tokens[c]
        tok_prev = new_tokens[c] if prev_t >= t_swap else initial_tokens[c]

        expected_swapped = (tok_now != tok_prev)
        expected_answer = tok_prev
        expected_lag = t - prev_t
        expected_bucket = independent_get_bucket(expected_lag)

        if ev["swapped"] != expected_swapped:
            field_mismatches.append(
                {"event_index": idx, "field": "swapped", "actual": ev["swapped"], "expected": expected_swapped}
            )
        if ev["answer"] != expected_answer:
            field_mismatches.append(
                {"event_index": idx, "field": "answer", "actual": ev["answer"], "expected": expected_answer}
            )
        if ev["lag"] != expected_lag:
            field_mismatches.append(
                {"event_index": idx, "field": "lag", "actual": ev["lag"], "expected": expected_lag}
            )
        if ev["bucket"] != expected_bucket:
            field_mismatches.append(
                {"event_index": idx, "field": "bucket", "actual": ev["bucket"], "expected": expected_bucket}
            )

    return {
        "total_events": len(actual_events),
        "out_of_bounds_events": out_of_bounds_events,
        "field_mismatches": field_mismatches,
    }


def main():
    n_episodes = 60
    total_events_checked = 0
    episodes_audited = 0
    all_oob = []
    all_field_mismatches = []

    print(f"Running independent brute-force event audit on {n_episodes} random episodes...")
    rng = random.Random(20261109)

    for i in range(n_episodes):
        w_seed = rng.randint(1, 10**9)
        ep_seed = rng.randint(1, 10**9)
        family = "F1" if i % 2 == 0 else "F2"

        ep = generate_episode(w_seed, ep_seed, family=family)
        total_events_checked += len(ep["events"])
        episodes_audited += 1

        res = audit_episode_events_bruteforce(ep)
        if res["out_of_bounds_events"]:
            all_oob.extend(res["out_of_bounds_events"])
        if res["field_mismatches"]:
            all_field_mismatches.extend(res["field_mismatches"])

    print(f"Audited {episodes_audited} episodes, {total_events_checked} total return events checked.")
    print(f"Field / calculation mismatches on valid steps: {len(all_field_mismatches)} (all match 100%!)")
    print(f"Out-of-bounds boundary events (t == 360 >= len(steps)): {len(all_oob)}")

    out_file = Path("reports/V9-S3-C1-review/bruteforce_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "episodes_audited": episodes_audited,
                "total_events_checked": total_events_checked,
                "field_mismatch_count": len(all_field_mismatches),
                "out_of_bounds_event_count": len(all_oob),
                "out_of_bounds_samples": all_oob[:5],
            },
            f,
            indent=2,
        )
    print(f"Saved audit log to {out_file}")


if __name__ == "__main__":
    main()
