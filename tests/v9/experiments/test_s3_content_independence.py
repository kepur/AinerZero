"""Test Content Layer Independence and Invariants.

Requirements:
- Positions, tokens, and swap times do not follow fixed patterns across worlds/episodes.
- new_token != initial_token for every content cell.
- Content cells strictly placed on walkable FREE cells.
- F1 tokens in 1..8, F2 tokens in 9..16 (mutually disjoint).
"""

from __future__ import annotations

import random

import pytest

from ainerzero.v9.experiments.s2.world import FREE, make_layout
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import generate_content_state


def test_content_invariants_and_token_families() -> None:
    """Verify new_token != initial_token and strict family bounds."""
    layout = make_layout(5001)

    for family, valid_tokens in [("F1", spec.F1_TOKENS), ("F2", spec.F2_TOKENS)]:
        rng = random.Random(12345)
        cs = generate_content_state(layout, family, rng, m=spec.M)

        assert len(cs.content_cells) == spec.M
        assert len(set(cs.content_cells)) == spec.M

        for cell in cs.content_cells:
            # Must be placed on FREE cell
            assert layout.terrain[cell[1]][cell[0]] == FREE

            t_init = cs.initial_tokens[cell]
            t_new = cs.new_tokens[cell]
            t_swap = cs.swap_times[cell]

            # Tokens must be in registered family
            assert t_init in valid_tokens
            assert t_new in valid_tokens

            # New token must differ from initial token
            assert t_new != t_init, f"new_token {t_new} equals initial_token {t_init} at {cell}"

            # Swap time must be within reasonable active range
            assert 100 <= t_swap <= 300


def test_content_layer_independence_across_episodes() -> None:
    """Assert positions, tokens, and swap times vary independently across episodes."""
    n_samples = 25
    layout = make_layout(5002)

    positions_set: set[tuple[tuple[int, int], ...]] = set()
    initial_tokens_tuples: set[tuple[int, ...]] = set()
    swap_times_tuples: set[tuple[int, ...]] = set()
    new_tokens_tuples: set[tuple[int, ...]] = set()

    for idx in range(n_samples):
        rng = random.Random(idx * 77 + 13)
        cs = generate_content_state(layout, "F1", rng, m=spec.M)

        sorted_cells = tuple(sorted(cs.content_cells))
        positions_set.add(sorted_cells)

        init_tup = tuple(cs.initial_tokens[c] for c in sorted_cells)
        initial_tokens_tuples.add(init_tup)

        swap_tup = tuple(cs.swap_times[c] for c in sorted_cells)
        swap_times_tuples.add(swap_tup)

        new_tup = tuple(cs.new_tokens[c] for c in sorted_cells)
        new_tokens_tuples.add(new_tup)

    # Across 25 random draws, there should be high diversity (no fixed pattern)
    assert len(positions_set) >= 20, f"Positions lack diversity: {len(positions_set)}/{n_samples}"
    assert len(initial_tokens_tuples) >= 20, f"Initial tokens lack diversity: {len(initial_tokens_tuples)}/{n_samples}"
    assert len(swap_times_tuples) >= 20, f"Swap times lack diversity: {len(swap_times_tuples)}/{n_samples}"
    assert len(new_tokens_tuples) >= 20, f"New tokens lack diversity: {len(new_tokens_tuples)}/{n_samples}"
