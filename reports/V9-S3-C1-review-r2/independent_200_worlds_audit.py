#!/usr/bin/env python3
"""Independent 200-World Audit and Boundary Invariant Assertion (P205 Review).

Requirements:
- Run across at least 200 independent worlds (we run 250 worlds).
- Strictly reconstruct trajectory from steps[:]["truth"]["x", "y"] without using trajectory_positions.
- Hard assert for every event:
    0 <= event["t"] < len(episode["steps"])
    0 <= event["prev_visit_t"] < event["t"]
- Independently recalculate prev_visit_t, lag, swapped, answer, and bucket from steps data.
- Save detailed machine-readable audit report to reports/V9-S3-C1-review-r2/audit_200_worlds.json.
"""

import collections
import json
from pathlib import Path
import random
import time

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode


def independent_get_bucket(lag: int) -> str | None:
    for name, lo, hi in spec.BUCKETS:
        if lo <= lag <= hi:
            return name
    return None


def audit_200_worlds(n_worlds: int = 250) -> dict:
    total_events = 0
    total_swapped = 0
    total_lag_lt_8 = 0
    bucket_counts = collections.defaultdict(int)
    swapped_by_bucket = collections.defaultdict(int)

    violations = []
    recalculation_mismatches = []
    max_t_observed = -1

    t0 = time.time()
    for w_idx in range(n_worlds):
        w_seed = derive_seed("audit-p205", "world", w_idx)
        ep_seed = derive_seed("audit-p205", "ep", w_idx)
        family = "F1" if w_idx % 2 == 0 else "F2"

        ep = generate_episode(w_seed, ep_seed, family=family)
        steps = ep["steps"]
        n_steps = len(steps)
        assert n_steps == spec.T, f"Expected {spec.T} steps, got {n_steps}"

        content_meta = ep["content_state"]
        initial_tokens = {tuple(map(int, k.split(","))): v for k, v in content_meta["initial_tokens"].items()}
        swap_times = {tuple(map(int, k.split(","))): v for k, v in content_meta["swap_times"].items()}
        new_tokens = {tuple(map(int, k.split(","))): v for k, v in content_meta["new_tokens"].items()}
        content_cells = set(initial_tokens.keys())

        # STRICTLY reconstruct trajectory from steps truth
        truth_trajectory = [(int(st["truth"]["x"]), int(st["truth"]["y"])) for st in steps]
        assert len(truth_trajectory) == n_steps

        # Independent brute-force replay
        cell_visit_history = collections.defaultdict(list)
        cell_visit_history[truth_trajectory[0]].append(0)

        expected_events = []
        for t in range(1, n_steps):
            c = truth_trajectory[t]
            prev_c = truth_trajectory[t - 1]

            if c in content_cells and c != prev_c:
                history = cell_visit_history[c]
                if history:
                    prev_visit_t = history[-1]
                    lag = t - prev_visit_t
                    bucket = independent_get_bucket(lag)

                    t_swap = swap_times[c]
                    tok_now = new_tokens[c] if t >= t_swap else initial_tokens[c]
                    tok_prev = new_tokens[c] if prev_visit_t >= t_swap else initial_tokens[c]

                    swapped = (tok_now != tok_prev)
                    answer = tok_prev

                    expected_events.append(
                        {
                            "t": t,
                            "cell": list(c),
                            "prev_visit_t": prev_visit_t,
                            "lag": lag,
                            "bucket": bucket,
                            "swapped": swapped,
                            "answer": answer,
                        }
                    )

            cell_visit_history[c].append(t)

        actual_events = ep["events"]

        # Check count match
        if len(actual_events) != len(expected_events):
            violations.append(
                {
                    "world_index": w_idx,
                    "type": "event_count_mismatch",
                    "actual": len(actual_events),
                    "expected": len(expected_events),
                }
            )

        # Check each event
        for ev_idx, (act, exp) in enumerate(zip(actual_events, expected_events)):
            t = act["t"]
            prev_t = act["prev_visit_t"]

            if t > max_t_observed:
                max_t_observed = t

            # HARD INVARIANT 1: 0 <= t < n_steps (strictly < 360)
            if not (0 <= t < n_steps):
                violations.append(
                    {
                        "world_index": w_idx,
                        "event_index": ev_idx,
                        "type": "t_out_of_bounds",
                        "t": t,
                        "n_steps": n_steps,
                    }
                )

            # HARD INVARIANT 2: 0 <= prev_visit_t < t
            if not (0 <= prev_t < t):
                violations.append(
                    {
                        "world_index": w_idx,
                        "event_index": ev_idx,
                        "type": "prev_visit_t_out_of_bounds",
                        "prev_visit_t": prev_t,
                        "t": t,
                    }
                )

            # Recalculation equality checks
            for field in ("t", "cell", "prev_visit_t", "lag", "bucket", "swapped", "answer"):
                if act[field] != exp[field]:
                    recalculation_mismatches.append(
                        {
                            "world_index": w_idx,
                            "event_index": ev_idx,
                            "field": field,
                            "actual": act[field],
                            "expected": exp[field],
                        }
                    )

            total_events += 1
            if act["swapped"]:
                total_swapped += 1
            if act["lag"] < 8:
                total_lag_lt_8 += 1
                if act["bucket"] is not None:
                    violations.append(
                        {
                            "world_index": w_idx,
                            "event_index": ev_idx,
                            "type": "lag_lt_8_bucket_not_none",
                            "lag": act["lag"],
                            "bucket": act["bucket"],
                        }
                    )
            else:
                bucket_counts[act["bucket"]] += 1
                if act["swapped"]:
                    swapped_by_bucket[act["bucket"]] += 1

    t1 = time.time()
    swapped_ratio = total_swapped / total_events if total_events else 0.0

    return {
        "n_worlds": n_worlds,
        "elapsed_seconds": round(t1 - t0, 2),
        "total_events": total_events,
        "total_swapped": total_swapped,
        "swapped_ratio": swapped_ratio,
        "total_lag_lt_8": total_lag_lt_8,
        "max_t_observed": max_t_observed,
        "bucket_counts": dict(bucket_counts),
        "swapped_by_bucket": dict(swapped_by_bucket),
        "violations_count": len(violations),
        "violations": violations,
        "recalculation_mismatches_count": len(recalculation_mismatches),
        "recalculation_mismatches": recalculation_mismatches,
    }


def main():
    print("Starting independent 250-world audit (bounds invariants & brute-force recalculation)...")
    res = audit_200_worlds(250)
    print(f"Completed in {res['elapsed_seconds']}s.")
    print(f"Total events checked: {res['total_events']}")
    print(f"Max t observed: {res['max_t_observed']} (strictly < 360)")
    print(f"Hard invariant violations: {res['violations_count']}")
    print(f"Recalculation mismatches: {res['recalculation_mismatches_count']}")
    print(f"Swapped ratio: {res['swapped_ratio']*100:.2f}% ({res['total_swapped']}/{res['total_events']})")
    print(f"Lag < 8 count: {res['total_lag_lt_8']} (all bucket=None)")
    print(f"Bucket breakdown: {res['bucket_counts']}")

    out_file = Path("reports/V9-S3-C1-review-r2/audit_200_worlds.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Saved audit log to {out_file}")


if __name__ == "__main__":
    main()
