"""Deterministic fake teachers (CPU-only; no MLX / torch / Core ML imports)."""

from __future__ import annotations

import hashlib
import struct
from typing import List, Sequence

from .mode import ModeGuard, ModeViolationError


def _seeded_floats(seed: bytes, count: int) -> List[float]:
    out: List[float] = []
    counter = 0
    while len(out) < count:
        block = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
        for i in range(0, len(block) - 3, 4):
            u = int.from_bytes(block[i : i + 4], "little")
            out.append((u / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(out) >= count:
                break
        counter += 1
    return out


def floats_to_bytes(values: Sequence[float]) -> bytes:
    return b"".join(struct.pack("<f", float(v)) for v in values)


class FakeTeacher:
    """In-process fake teacher; every extract re-validates ModeGuard (F5/F6)."""

    def __init__(self, teacher_id: str, teacher_kind: str = "feature", dim: int = 16):
        self.teacher_id = teacher_id
        self.teacher_kind = teacher_kind
        self.dim = dim
        self._generation = ModeGuard.check_teacher_load(teacher_id, teacher_kind)

    def extract(self, input_sha256: str, timestamps_ticks: Sequence[int]) -> bytes:
        ModeGuard.assert_handle_valid(self.teacher_id, self._generation)
        seed = hashlib.sha256(
            f"{self.teacher_id}|{self.teacher_kind}|{input_sha256}|{list(timestamps_ticks)}".encode()
        ).digest()
        n = self.dim * max(1, len(timestamps_ticks))
        return floats_to_bytes(_seeded_floats(seed, n))

    def unload(self) -> None:
        ModeGuard.release_teacher()
        # Stale generation retained so extract fails after unload
