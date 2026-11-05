"""S06: controlled 2D GridLab (CPU only, environment and trajectories, no training).

Discrete grid rules, not physics. A seeded world is a bordered grid with opaque
pillars, one agent and a few objects with persistent identity:

* ``ball`` moves one cell per step with a fixed velocity and reflects off
  blocked cells (simple dynamics that make temporal prediction possible);
* ``box`` is static unless the agent pushes it into a free cell.

The agent sees a square window (Chebyshev radius ``view_radius``) restricted by
line of sight: pillars and walls are opaque, so objects behind them are
*occluded*; objects outside the window are *out of view*. The public
observation exposes only appearance and position of visible objects, never
their identity; identity and full state stay evaluator-private.

World-level splits (S04): whole worlds go to train/development/final; S04's
``final_test`` is ``DatasetPartition.FINAL``.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from enum import IntEnum
from uuid import UUID, uuid5

from ainerzero.core.experience import DatasetPartition

GRIDLAB_REVISION = "gridlab2d-v1"
NAMESPACE = UUID("6f1c2d4e-0a5b-5c3d-9e8f-5e06a1b2c3d4")
FREE, WALL, PILLAR = 0, 1, 2
APPEARANCE = {"ball": "red_disc", "box": "brown_square"}


class Action(IntEnum):
    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3
    WAIT = 4


DELTA = {Action.UP: (0, -1), Action.DOWN: (0, 1), Action.LEFT: (-1, 0),
         Action.RIGHT: (1, 0), Action.WAIT: (0, 0)}


@dataclass
class GridObject:
    object_id: UUID
    kind: str
    x: int
    y: int
    vx: int = 0
    vy: int = 0


@dataclass
class GridWorld:
    seed: int
    world_id: UUID
    width: int
    height: int
    terrain: list[list[int]]  # terrain[y][x]
    agent: tuple[int, int]
    objects: list[GridObject]
    view_radius: int
    step: int = 0
    history: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------ geometry
    def blocked(self, x: int, y: int, *, ignore: UUID | None = None, agent_blocks: bool = True) -> bool:
        if not (0 <= x < self.width and 0 <= y < self.height) or self.terrain[y][x] != FREE:
            return True
        if agent_blocks and (x, y) == self.agent:
            return True
        return any((o.x, o.y) == (x, y) and o.object_id != ignore for o in self.objects)

    def line_of_sight(self, x: int, y: int) -> bool:
        ax, ay = self.agent
        n = max(abs(x - ax), abs(y - ay))
        for i in range(1, n):  # endpoints excluded; supercover via rounding both ways
            fx, fy = ax + (x - ax) * i / n, ay + (y - ay) * i / n
            cells = {(int(fx + 0.5 - 1e-9), int(fy + 0.5 - 1e-9)), (int(fx + 0.5), int(fy + 0.5))}
            if all(self.terrain[cy][cx] != FREE for cx, cy in cells):
                return False
        return True

    def in_window(self, x: int, y: int) -> bool:
        ax, ay = self.agent
        return max(abs(x - ax), abs(y - ay)) <= self.view_radius

    def visibility_of(self, x: int, y: int) -> str:
        if not self.in_window(x, y):
            return "out_of_view"
        return "visible" if self.line_of_sight(x, y) else "occluded"

    # ------------------------------------------------------------ dynamics
    def apply(self, action: Action) -> None:
        action = Action(action)
        dx, dy = DELTA[action]
        if (dx, dy) != (0, 0):
            tx, ty = self.agent[0] + dx, self.agent[1] + dy
            box = next((o for o in self.objects if (o.x, o.y) == (tx, ty)), None)
            if box is not None and box.kind == "box" and not self.blocked(tx + dx, ty + dy):
                box.x, box.y = tx + dx, ty + dy
                self.agent = (tx, ty)
            elif not self.blocked(tx, ty, agent_blocks=False):
                self.agent = (tx, ty)
        for o in self.objects:
            if o.kind != "ball":
                continue
            for vx, vy in ((o.vx, o.vy), (-o.vx, o.vy), (o.vx, -o.vy), (-o.vx, -o.vy)):
                if not self.blocked(o.x + vx, o.y + vy, ignore=o.object_id):
                    o.vx, o.vy, o.x, o.y = vx, vy, o.x + vx, o.y + vy
                    break
        self.step += 1

    # ------------------------------------------------------------ views
    def public_observation(self, episode_id: UUID, last_action: Action | None) -> dict:
        cells = []
        for y in range(self.height):
            for x in range(self.width):
                if self.visibility_of(x, y) == "visible":
                    cells.append([x, y, self.terrain[y][x]])
        objs = sorted(
            ([o.x, o.y, APPEARANCE[o.kind]] for o in self.objects if self.visibility_of(o.x, o.y) == "visible"))
        obs = {
            "kind": "gridlab_observation",
            "revision": GRIDLAB_REVISION,
            "observation_id": str(uuid5(episode_id, f"obs:{self.step}")),
            "step": self.step,
            "agent_xy": list(self.agent),
            "last_action": None if last_action is None else int(last_action),
            "visible_cells": cells,
            "visible_objects": objs,
        }
        obs["observation_sha256"] = digest(obs)
        return obs

    def private_state(self) -> dict:
        return {
            "step": self.step,
            "agent_xy": list(self.agent),
            "objects": [
                {"object_id": str(o.object_id), "kind": o.kind, "xy": [o.x, o.y], "v": [o.vx, o.vy],
                 "visibility": self.visibility_of(o.x, o.y)}
                for o in self.objects
            ],
        }

    def layout_sha256(self) -> str:
        return digest({"terrain": self.terrain, "agent": list(self.agent),
                       "objects": [[o.kind, o.x, o.y, o.vx, o.vy] for o in self.objects]})


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def world_id_for(seed: int) -> UUID:
    return uuid5(NAMESPACE, f"{GRIDLAB_REVISION}:world:{seed}")


def make_world(seed: int, *, width: int = 9, height: int = 9, pillars: int = 5,
               balls: int = 2, boxes: int = 1, view_radius: int = 3) -> GridWorld:
    """Deterministic: same arguments give byte-identical worlds."""
    if seed < 0 or width < 5 or height < 5 or view_radius < 1:
        raise ValueError("invalid GridLab parameters")
    rng = random.Random(f"{GRIDLAB_REVISION}:{seed}")
    terrain = [[WALL if x in (0, width - 1) or y in (0, height - 1) else FREE for x in range(width)]
               for y in range(height)]
    interior = [(x, y) for y in range(1, height - 1) for x in range(1, width - 1)]
    rng.shuffle(interior)
    if pillars + balls + boxes + 1 > len(interior):
        raise ValueError("too many entities for the grid")
    for x, y in interior[:pillars]:
        terrain[y][x] = PILLAR
    free = interior[pillars:]
    agent = free.pop()
    wid = world_id_for(seed)
    objects = []
    for i, kind in enumerate(["ball"] * balls + ["box"] * boxes):
        x, y = free.pop()
        v = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)])
        vx, vy = v if kind == "ball" else (0, 0)
        objects.append(GridObject(uuid5(wid, f"object:{i}"), kind, x, y, vx, vy))
    return GridWorld(seed, wid, width, height, terrain, agent, objects, view_radius)


# ---------------------------------------------------------------- splits

SPLIT_FRACTIONS = {DatasetPartition.TRAIN: 0.6, DatasetPartition.DEVELOPMENT: 0.2,
                   DatasetPartition.FINAL: 0.2}


def assign_splits(world_ids, fractions=SPLIT_FRACTIONS) -> dict[UUID, DatasetPartition]:
    """Whole-world assignment, deterministic in the world-id set (not order)."""
    ids = sorted(set(world_ids), key=lambda w: hashlib.sha256(f"split:{w}".encode()).hexdigest())
    if len(ids) != len(list(world_ids)):
        raise ValueError("duplicate world ids")
    if set(fractions) - set(SPLIT_FRACTIONS) or abs(sum(fractions.values()) - 1) > 1e-9:
        raise ValueError("fractions must cover train/development/final and sum to 1")
    out, start = {}, 0
    order = [p for p in SPLIT_FRACTIONS if p in fractions]
    for k, part in enumerate(order):
        n = len(ids) - start if k == len(order) - 1 else round(fractions[part] * len(ids))
        for w in ids[start:start + n]:
            out[w] = part
        start += n
    return out


def check_split_leakage(episodes) -> None:
    """episodes: iterable of dicts with world_id, partition, seed, layout_sha256.

    Raises if a world, seed or identical initial layout appears in two partitions.
    """
    by = {"world_id": {}, "seed": {}, "layout_sha256": {}}
    for ep in episodes:
        part = DatasetPartition(ep["partition"])
        if part is DatasetPartition.QUARANTINE:
            raise ValueError("quarantine episodes are not part of a split")
        for key, seen in by.items():
            prev = seen.setdefault(ep[key], part)
            if prev is not part:
                raise ValueError(f"split leakage: {key} {ep[key]} in {prev} and {part}")
