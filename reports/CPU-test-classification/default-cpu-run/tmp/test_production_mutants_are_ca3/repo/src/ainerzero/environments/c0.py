"""The minimal, fully visible SwitchLab C0 world.

Rules are sampled once per instance. Reset changes only episode state. The
student sees ``SymbolObservation``; ``C0Snapshot`` is a private persistence and
replay interface, not a sensor or a source of training labels.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID, uuid5

import numpy as np
from pydantic import Field, model_validator

from ainerzero.core.contracts import Byte, CellIndex, Contract, SymbolObservation

ENVIRONMENT_REVISION = "switchlab_c0_v1"
ACTION_SCHEMA_REVISION = "switchlab_actions_v1"
MAX_EPISODE_TICKS = 128
MAX_SEED = 2**64 - 1
_INSTANCE_NAMESPACE = UUID("c86050af-75e7-44b5-b713-5326a5fae4fd")

Bit = Annotated[int, Field(strict=True, ge=0, le=1)]
FourCells = Annotated[tuple[CellIndex, ...], Field(min_length=4, max_length=4)]
SymbolPair = Annotated[tuple[Byte, ...], Field(min_length=2, max_length=2)]


class C0Snapshot(Contract):
    """Complete private state, independent of seed regeneration or RNG internals.

    Each output copies the bit at the corresponding ``output_sources`` entry.
    Its displayed byte comes from its *own* symbol pair, so causal copying does
    not imply matching displayed symbols. Pairs may overlap across cells.

    Validation detects incompatible or inconsistent state, not malicious edits
    that produce another valid world. Authenticity belongs to the artifact
    producer/storage boundary.
    """

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    instance_id: UUID
    environment_revision: Literal["switchlab_c0_v1"]
    action_schema_revision: Literal["switchlab_actions_v1"]
    input_cells: FourCells
    output_cells: FourCells
    output_sources: FourCells
    symbol_pairs: Annotated[tuple[SymbolPair, ...], Field(min_length=8, max_length=8)]
    bits: Annotated[tuple[Bit, ...], Field(min_length=8, max_length=8)]
    cursor: CellIndex
    tick: Annotated[int, Field(strict=True, ge=0, le=MAX_EPISODE_TICKS)]

    @model_validator(mode="after")
    def consistent_world(self) -> Self:
        if set(self.input_cells + self.output_cells) != set(range(8)):
            raise ValueError("input/output cells must partition all eight positions")
        if any(source not in self.input_cells for source in self.output_sources):
            raise ValueError("every output source must be an input cell")
        if any(pair[0] == pair[1] for pair in self.symbol_pairs):
            raise ValueError("each cell requires two distinct symbol bytes")
        for output, source in zip(self.output_cells, self.output_sources, strict=True):
            if self.bits[output] != self.bits[source]:
                raise ValueError("output bits must copy their input sources")
        return self


def _seed(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SEED:
        raise ValueError(f"seed must be an integer in [0, {MAX_SEED}]")
    return value


class C0Environment:
    """Eight cells, four copying outputs, four discrete actions, no delay.

    Actions are 0 left, 1 right, 2 press, 3 wait. Every valid action consumes
    one tick, including edge moves and presses on output cells. Public actions
    accept only Python integers; rejected calls do not alter state.
    """

    def __init__(self, seed: int):
        seed = _seed(seed)
        rng = np.random.default_rng(seed)
        positions = rng.permutation(8)
        input_cells = tuple(sorted(int(cell) for cell in positions[:4]))
        output_cells = tuple(sorted(int(cell) for cell in positions[4:]))
        output_sources = tuple(int(cell) for cell in rng.choice(input_cells, size=4))
        pairs = tuple(
            tuple(int(symbol) for symbol in rng.choice(256, size=2, replace=False))
            for _ in range(8)
        )
        self._state = C0Snapshot(
            schema_version=1,
            instance_id=uuid5(_INSTANCE_NAMESPACE, f"{ENVIRONMENT_REVISION}:{seed}"),
            environment_revision=ENVIRONMENT_REVISION,
            action_schema_revision=ACTION_SCHEMA_REVISION,
            input_cells=input_cells,
            output_cells=output_cells,
            output_sources=output_sources,
            symbol_pairs=pairs,
            bits=(0,) * 8,
            cursor=0,
            tick=0,
        )
        self.reset(seed)

    @property
    def instance_id(self) -> UUID:
        return self._state.instance_id

    @property
    def tick(self) -> int:
        return self._state.tick

    @property
    def done(self) -> bool:
        return self.tick == MAX_EPISODE_TICKS

    def observe(self) -> SymbolObservation:
        """Read the current public sensor payload without consuming a tick."""
        state = self._state
        return SymbolObservation(
            symbols=tuple(
                pair[bit] for pair, bit in zip(state.symbol_pairs, state.bits, strict=True)
            ),
            visible_mask=(True,) * 8,
            cursor=state.cursor,
            episode_start=(state.tick == 0),
        )

    def _set_state(self, bits: list[int], cursor: int, tick: int) -> None:
        for output, source in zip(
            self._state.output_cells, self._state.output_sources, strict=True
        ):
            bits[output] = bits[source]
        data = self._state.model_dump()
        data.update(bits=tuple(bits), cursor=cursor, tick=tick)
        self._state = C0Snapshot.model_validate(data)

    def reset(self, seed: int) -> SymbolObservation:
        """Start a new episode while preserving this instance's hidden rules."""
        rng = np.random.default_rng(_seed(seed))
        bits = [0] * 8
        for cell, bit in zip(self._state.input_cells, rng.integers(0, 2, size=4), strict=True):
            bits[cell] = int(bit)
        self._set_state(bits, int(rng.integers(0, 8)), 0)
        return self.observe()

    def step(self, action: int) -> SymbolObservation:
        if type(action) is not int or not 0 <= action <= 3:
            raise ValueError("action must be an integer in [0, 3]")
        if self.done:
            raise ValueError("episode has ended; reset before taking another action")
        bits = list(self._state.bits)
        cursor = self._state.cursor
        if action == 0:
            cursor = max(0, cursor - 1)
        elif action == 1:
            cursor = min(7, cursor + 1)
        elif action == 2 and cursor in self._state.input_cells:
            bits[cursor] = 1 - bits[cursor]
        self._set_state(bits, cursor, self.tick + 1)
        return self.observe()

    def snapshot(self) -> C0Snapshot:
        """Return an immutable private snapshot for authorized replay code."""
        return self._state

    @classmethod
    def restore(cls, snapshot: C0Snapshot) -> C0Environment:
        """Restore complete state, including at terminal or nonzero ticks."""
        state = C0Snapshot.model_validate(snapshot)
        env = cls.__new__(cls)
        env._state = state
        return env
