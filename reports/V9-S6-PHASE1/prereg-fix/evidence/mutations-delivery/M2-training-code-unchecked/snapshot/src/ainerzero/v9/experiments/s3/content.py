"""GridLab-S3 Content Layer.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §2.
Zero MLX imports. Pure CPU.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Sequence

from ainerzero.v9.experiments.s2.world import Layout
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.world import get_connected_free_cells


@dataclass(frozen=True)
class ContentState:
    """Immutable per-episode content state.

    Attributes:
        content_cells: Distinct walkable cells where tokens are placed (M cells).
        initial_tokens: Map from cell (x, y) to its initial token value.
        swap_times: Map from cell (x, y) to the step t at which its token swaps.
        new_tokens: Map from cell (x, y) to its post-swap token value (!= initial).
        family: Token family name ("F1" or "F2").
    """

    content_cells: tuple[tuple[int, int], ...]
    initial_tokens: dict[tuple[int, int], int]
    swap_times: dict[tuple[int, int], int]
    new_tokens: dict[tuple[int, int], int]
    family: str

    def get_token(self, cell: tuple[int, int], t: int) -> int:
        """Return token at cell at step t (0 if cell is not a content cell)."""
        if cell not in self.initial_tokens:
            return spec.NONE_TOKEN
        if t >= self.swap_times[cell]:
            return self.new_tokens[cell]
        return self.initial_tokens[cell]

    def get_token_map_at_step(self, t: int) -> dict[tuple[int, int], int]:
        """Return map of all content cells to their current token at step t."""
        return {c: self.get_token(c, t) for c in self.content_cells}

    def to_dict(self) -> dict[str, Any]:
        """Serialize for audit and JSON logging."""
        return {
            "family": self.family,
            "content_cells": [list(c) for c in self.content_cells],
            "initial_tokens": {f"{c[0]},{c[1]}": tok for c, tok in self.initial_tokens.items()},
            "swap_times": {f"{c[0]},{c[1]}": st for c, st in self.swap_times.items()},
            "new_tokens": {f"{c[0]},{c[1]}": tok for c, tok in self.new_tokens.items()},
        }


def _select_separated_cells(
    cells: Sequence[tuple[int, int]],
    m: int,
    rng: random.Random,
    min_dist: int = 4,
) -> tuple[tuple[int, int], ...]:
    """Select m cells with minimum Manhattan distance where feasible."""
    pool = list(cells)
    rng.shuffle(pool)
    chosen: list[tuple[int, int]] = []

    for c in pool:
        if all(abs(c[0] - x[0]) + abs(c[1] - x[1]) >= min_dist for x in chosen):
            chosen.append(c)
            if len(chosen) == m:
                break

    # If separation threshold was too strict, fill remaining from pool
    if len(chosen) < m:
        for c in pool:
            if c not in chosen:
                chosen.append(c)
                if len(chosen) == m:
                    break

    return tuple(chosen)


def generate_content_state(
    layout: Layout,
    family: str,
    rng: random.Random,
    *,
    m: int = spec.M,
    min_cell_dist: int = 4,
    swap_window: tuple[int, int] = (130, 220),
) -> ContentState:
    """Generate independent randomized content layer for one episode.

    Requirements:
    - Positions, initial tokens, swap times, and new tokens are independently
      randomized each episode.
    - New token != initial token.
    - Content cells strictly placed on connected walkable (FREE) cells.
    """
    if family == "F1":
        family_tokens = spec.F1_TOKENS
    elif family == "F2":
        family_tokens = spec.F2_TOKENS
    else:
        raise ValueError(f"Unknown family: {family}; expected 'F1' or 'F2'")

    connected_free = get_connected_free_cells(layout)
    if len(connected_free) < m:
        raise RuntimeError(
            f"Layout has only {len(connected_free)} connected free cells; need at least {m}"
        )

    content_cells = _select_separated_cells(connected_free, m, rng, min_dist=min_cell_dist)

    initial_tokens: dict[tuple[int, int], int] = {}
    swap_times: dict[tuple[int, int], int] = {}
    new_tokens: dict[tuple[int, int], int] = {}

    for c in content_cells:
        t_init = rng.choice(family_tokens)
        candidate_news = [tok for tok in family_tokens if tok != t_init]
        t_new = rng.choice(candidate_news)
        t_swap = rng.randint(swap_window[0], swap_window[1])

        initial_tokens[c] = t_init
        swap_times[c] = t_swap
        new_tokens[c] = t_new

    return ContentState(
        content_cells=content_cells,
        initial_tokens=initial_tokens,
        swap_times=swap_times,
        new_tokens=new_tokens,
        family=family,
    )
