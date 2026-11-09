"""Independent brute-force recalculation and verification of readout event labels.

Requirements per Review r1:
- Independent brute-force trajectory scan recalculating prev_visit_t, lag,
  bucket, swapped, and answer for every return event.
- Must reconstruct trajectory directly from step ground-truth coordinates
  (steps[t]["truth"]["x"], steps[t]["truth"]["y"]) without relying on any
  cached or internal trajectory array.
- Hard invariant assertions across >= 100 worlds:
    0 <= event["t"] < len(episode["steps"])
    0 <= event["prev_visit_t"] < event["t"]
- Must cover cases where the agent passed through (路过) content cells.
"""

from __future__ import annotations

import collections
import random
from typing import Any

import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import ContentState
from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode


def _brute_force_recompute_events(
    steps: list[dict[str, Any]],
    content_state: ContentState,
) -> list[dict[str, Any]]:
    """Completely independent, unoptimized brute-force event extractor.

    Reconstructs trajectory strictly from steps[:]["truth"], ensuring zero
    circular dependence on generator internals.
    """
    trajectory = [(int(st["truth"]["x"]), int(st["truth"]["y"])) for st in steps]
    content_set = set(content_state.content_cells)
    expected_events: list[dict[str, Any]] = []

    for t in range(1, len(trajectory)):
        curr_c = trajectory[t]
        prev_c = trajectory[t - 1]

        if curr_c in content_set and curr_c != prev_c:
            # Independent backward search for all previous occurrences of curr_c
            prior_visits = [tau for tau in range(t) if trajectory[tau] == curr_c]
            if prior_visits:
                prev_visit_t = max(prior_visits)
                lag = t - prev_visit_t
                bk = spec.get_bucket(lag)
                tok_then = content_state.get_token(curr_c, prev_visit_t)
                tok_now = content_state.get_token(curr_c, t)
                swapped = (tok_now != tok_then)

                expected_events.append(
                    {
                        "t": t,
                        "cell": list(curr_c),
                        "prev_visit_t": prev_visit_t,
                        "lag": lag,
                        "bucket": bk,
                        "swapped": swapped,
                        "answer": tok_then,
                    }
                )

    return expected_events


def test_events_match_brute_force_and_hard_bounds_100_worlds() -> None:
    """Assert all tour events match independent brute-force scan and satisfy strict bounds across 100 worlds."""
    n_worlds = 100
    total_events_verified = 0

    for w_idx in range(n_worlds):
        w_seed = derive_seed(spec.NAMESPACE_PROBE, "world", w_idx)
        ep_seed = derive_seed(spec.NAMESPACE_PROBE, "ep", w_idx, 0)
        episode = generate_episode(world_seed=w_seed, episode_seed=ep_seed, family="F1")

        steps = episode["steps"]
        n_steps = len(steps)
        assert n_steps == spec.T, f"Expected {spec.T} steps, got {n_steps}"

        # Reconstruct ContentState for independent verification
        cstate_dict = episode["content_state"]
        content_state = ContentState(
            content_cells=tuple(tuple(c) for c in cstate_dict["content_cells"]),
            initial_tokens={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["initial_tokens"].items()
            },
            swap_times={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["swap_times"].items()
            },
            new_tokens={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["new_tokens"].items()
            },
            family=cstate_dict["family"],
        )

        actual_events = episode["events"]
        expected_events = _brute_force_recompute_events(steps, content_state)

        # 1. Exact match between actual and independent brute-force calculation
        assert len(actual_events) == len(expected_events), (
            f"Event count mismatch in world {w_idx}: "
            f"actual {len(actual_events)} != expected {len(expected_events)}"
        )

        # 2. Hard bounds assertions on EVERY event (r1 mandatory item ① & ②)
        for i, (act, exp) in enumerate(zip(actual_events, expected_events)):
            t = act["t"]
            prev_t = act["prev_visit_t"]

            # Strict bounds: 0 <= prev_visit_t < t < len(steps)
            assert 0 <= t < n_steps, (
                f"World {w_idx} event {i} out of bounds: t={t} >= n_steps={n_steps}"
            )
            assert 0 <= prev_t < t, (
                f"World {w_idx} event {i} invalid prev_visit_t: {prev_t} not in [0, {t})"
            )

            # Field-by-field verification
            assert act["t"] == exp["t"], f"Event {i} step t mismatch"
            assert act["cell"] == exp["cell"], f"Event {i} cell mismatch"
            assert act["prev_visit_t"] == exp["prev_visit_t"], (
                f"Event {i} prev_visit_t mismatch: act {act['prev_visit_t']} != exp {exp['prev_visit_t']}"
            )
            assert act["lag"] == exp["lag"], f"Event {i} lag mismatch"
            assert act["bucket"] == exp["bucket"], f"Event {i} bucket mismatch"
            assert act["swapped"] == exp["swapped"], f"Event {i} swapped mismatch"
            assert act["answer"] == exp["answer"], f"Event {i} answer mismatch"

            total_events_verified += 1

    assert total_events_verified > 0, "No events verified across 100 worlds"
