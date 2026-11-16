"""GridLab-S3 phase 3: world sequences with persistent cells, decoys and one relocation.

Per reports/V9-S3-PHASE3-DESIGN/DESIGN-r0.md §2. Pure CPU, NumPy / standard library only.
Zero MLX imports. The world, tour, odometry, observation and record parsing are the
frozen phase 1 modules, used unchanged; this module only adds a content layer that
persists across the episodes of one world.

The random draws follow the exploration script exactly, so
``generate_sequence("s3p3x-explore", w)`` rebuilds the exploration worlds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s2.world import Layout, make_layout
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import ContentState
from ainerzero.v9.experiments.s3.data import derive_seed
from ainerzero.v9.experiments.s3.store import parse_student_step
from ainerzero.v9.experiments.s3.tour import run_tour
from ainerzero.v9.experiments.s3.world import get_connected_free_cells

N_PERSISTENT = 4
N_VOLATILE = 4
N_EPISODES = 12
P_DECOY = 0.3
RELOCATION_EPISODE = 6
P_RELOCATE = 0.5
MIN_CELL_DIST = 4
SWAP_WINDOW = (130, 220)
NEVER = 10**9

# Registered partitions that must not be generated outside a registered run.
REGISTERED = frozenset({"s3p3-dev", "s3p3-final"})

Cell = tuple[int, int]


@dataclass(frozen=True)
class Episode:
    index: int
    raw: dict[str, Any]            # run_tour output (steps carry a 'truth' block)
    regime: dict[Cell, int]        # persistent value of each persistent cell this episode
    decoy: dict[Cell, bool]        # whether the cell shows a decoy for the whole episode
    volatile: tuple[Cell, ...]


@dataclass(frozen=True)
class WorldSequence:
    namespace: str
    world_index: int
    world_seed: int
    layout_sha256: str
    persistent: tuple[Cell, ...]
    before: dict[Cell, int]
    after: dict[Cell, int]
    relocated: frozenset[Cell]
    episodes: tuple[Episode, ...]


def separated_cells(
    cells: Sequence[Cell],
    m: int,
    rng: random.Random,
    *,
    banned: Sequence[Cell] = (),
    min_dist: int = MIN_CELL_DIST,
) -> tuple[Cell, ...]:
    """Pick m cells at least ``min_dist`` apart (Manhattan) from each other and from ``banned``.

    Falls back to filling from the shuffled pool when the spacing cannot be met,
    as the frozen ``content._select_separated_cells`` does.
    """
    banned = list(banned)
    pool = [c for c in cells if c not in banned]
    rng.shuffle(pool)
    chosen: list[Cell] = []
    for c in pool:
        if all(abs(c[0] - x[0]) + abs(c[1] - x[1]) >= min_dist for x in chosen + banned):
            chosen.append(c)
            if len(chosen) == m:
                return tuple(chosen)
    for c in pool:
        if c not in chosen:
            chosen.append(c)
            if len(chosen) == m:
                break
    if len(chosen) < m:
        raise RuntimeError(f"only {len(chosen)} cells available, need {m}")
    return tuple(chosen)


def _other(tokens: Sequence[int], than: int, rng: random.Random) -> int:
    return rng.choice([k for k in tokens if k != than])


def generate_sequence(
    namespace: str,
    world_index: int,
    *,
    n_episodes: int = N_EPISODES,
    allow_registered: bool = False,
) -> WorldSequence:
    """Generate the episode sequence of one world."""
    if namespace in REGISTERED and not allow_registered:
        raise PermissionError(f"{namespace} is a registered partition; only a registered run may generate it")
    tokens = spec.F1_TOKENS
    world_seed = derive_seed(namespace, "world", world_index)
    layout: Layout = make_layout(world_seed)
    free = get_connected_free_cells(layout)

    wr = random.Random(derive_seed(namespace, "persist", world_index))
    persistent = separated_cells(free, N_PERSISTENT, wr)
    before = {c: wr.choice(tokens) for c in persistent}
    after = dict(before)
    relocated: set[Cell] = set()
    for c in persistent:
        if wr.random() < P_RELOCATE:
            after[c] = _other(tokens, before[c], wr)
            relocated.add(c)

    episodes = []
    for e in range(n_episodes):
        er = random.Random(derive_seed(namespace, "ep", world_index, e))
        regime = dict(after if e >= RELOCATION_EPISODE else before)
        volatile = separated_cells(free, N_VOLATILE, er, banned=persistent)
        shown: dict[Cell, int] = {}
        swap: dict[Cell, int] = {}
        new: dict[Cell, int] = {}
        decoy: dict[Cell, bool] = {}
        for c in persistent:
            decoy[c] = er.random() < P_DECOY
            shown[c] = _other(tokens, regime[c], er) if decoy[c] else regime[c]
            swap[c] = NEVER
            new[c] = [k for k in tokens if k != shown[c]][0]  # never shown: swap is NEVER
        for c in volatile:
            shown[c] = er.choice(tokens)
            new[c] = _other(tokens, shown[c], er)
            swap[c] = er.randint(*SWAP_WINDOW)
        cells = list(persistent) + list(volatile)
        er.shuffle(cells)
        content = ContentState(tuple(cells), shown, swap, new, "F1")
        raw = run_tour(layout, content, er, t_max=spec.T, p_slip=spec.P_SLIP, noise=spec.NOISE)
        episodes.append(Episode(e, raw, regime, decoy, volatile))

    return WorldSequence(
        namespace=namespace,
        world_index=world_index,
        world_seed=world_seed,
        layout_sha256=layout.layout_sha256,
        persistent=persistent,
        before=before,
        after=after,
        relocated=frozenset(relocated),
        episodes=tuple(episodes),
    )


@dataclass(frozen=True)
class Records:
    """Every step of a world sequence, flattened in time order.

    ``ep``, ``t``, ``xy``, ``terrain`` and ``token`` are student-visible (parsed by the frozen
    ``store.parse_student_step``). ``truth_cell`` is the true position and is only for event
    definitions and truth-keyed diagnostics, never for a policy's answer.
    """

    ep: np.ndarray          # [N] int32
    t: np.ndarray           # [N] int32
    xy: np.ndarray          # [N, 2] float64 estimated position
    terrain: np.ndarray     # [N, 9] int8 world-aligned 3x3 terrain
    token: np.ndarray       # [N] int32 token seen at the centre cell
    truth_cell: np.ndarray  # [N, 2] int32
    start: tuple[int, ...]  # index of the first record of each episode

    def gtime(self, idx: np.ndarray | int) -> np.ndarray:
        """Global time: episode * T + step."""
        return self.ep[idx].astype(np.int64) * spec.T + self.t[idx]


def records_of(seq: WorldSequence) -> Records:
    ep, t, xy, ter, tok, cell, start = [], [], [], [], [], [], []
    for episode in seq.episodes:
        start.append(len(ep))
        for s in episode.raw["steps"]:
            r = parse_student_step(s)
            ep.append(episode.index)
            t.append(r.t)
            xy.append((r.est_pose[0], r.est_pose[1]))
            ter.append(r.world_terrain.reshape(-1))
            tok.append(r.observed_token)
            cell.append((int(s["truth"]["x"]), int(s["truth"]["y"])))
    return Records(
        ep=np.array(ep, dtype=np.int32),
        t=np.array(t, dtype=np.int32),
        xy=np.array(xy, dtype=np.float64),
        terrain=np.stack(ter).astype(np.int8),
        token=np.array(tok, dtype=np.int32),
        truth_cell=np.array(cell, dtype=np.int32),
        start=tuple(start),
    )


def first_arrivals(seq: WorldSequence, e: int) -> list[tuple[Cell, int]]:
    """(persistent cell, first step on it) for episode e, in ``seq.persistent`` order. Truth-defined."""
    steps = seq.episodes[e].raw["steps"]
    out = []
    for c in seq.persistent:
        for s in steps:
            if (int(s["truth"]["x"]), int(s["truth"]["y"])) == c:
                out.append((c, int(s["t"])))
                break
    return out
