"""S07: GridLab-v1 (CPU only; environment and trajectories, no training).

Spec (IMPLEMENTATION_GUIDE §12.1): 11x11 grid, 5x5 egocentric view rendered as
80x80 RGB, actions = four moves + interact + wait; occluders, doors, switches
and pushable boxes. Discrete grid rules, not physics.

* closed doors are opaque and impassable; open doors are free floor;
* ``INTERACT`` while standing on a switch toggles its linked door (refused if
  the door cell is occupied);
* balls keep a fixed velocity and reflect off blocked cells; boxes are pushed;
* several balls share one appearance on purpose (same-appearance confusion);
* the public observation is egocentric (relative coords) plus the agent's own
  position (proprioception); identity, velocity and hidden objects are private.

Events and S04 held-out subsets are computed from evaluator-private truth only.
Builds on S06 ``gridlab2d`` (canonical JSON, digests, world-level splits).
"""

from __future__ import annotations

import base64
import hashlib
import random
from dataclasses import dataclass
from enum import IntEnum
from uuid import UUID, uuid5

import numpy as np

from ainerzero.environments.gridlab2d import NAMESPACE, canonical, digest

REVISION = "gridlab-v1"
SIZE, VIEW_RADIUS, CELL_PX = 11, 2, 16
FREE, WALL, PILLAR, DOOR_CLOSED, DOOR_OPEN, SWITCH = 0, 1, 2, 3, 4, 5
UNSEEN = -1
OPAQUE = {WALL, PILLAR, DOOR_CLOSED}
APPEARANCE = {"ball": "red_disc", "box": "brown_square"}
COLORS = {UNSEEN: (24, 24, 24), FREE: (200, 200, 200), WALL: (60, 60, 60), PILLAR: (90, 70, 120),
          DOOR_CLOSED: (150, 90, 30), DOOR_OPEN: (230, 200, 150), SWITCH: (60, 160, 60)}
OBJ_COLORS = {"red_disc": (210, 30, 30), "brown_square": (120, 80, 40)}
AGENT_COLOR = (240, 220, 0)
FAMILIES = ("open", "door_room", "swap_lane", "occlusion_walk")  # last two are scripted scenarios


class Action(IntEnum):
    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3
    INTERACT = 4
    WAIT = 5


DELTA = {Action.UP: (0, -1), Action.DOWN: (0, 1), Action.LEFT: (-1, 0), Action.RIGHT: (1, 0)}


@dataclass
class Obj:
    object_id: UUID
    kind: str
    x: int
    y: int
    vx: int = 0
    vy: int = 0

    @property
    def appearance(self) -> str:
        return APPEARANCE[self.kind]


@dataclass
class World:
    seed: int
    family: str
    world_id: UUID
    terrain: list[list[int]]
    switches: dict[tuple[int, int], tuple[int, int]]  # switch cell -> door cell
    agent: tuple[int, int]
    objects: list[Obj]
    step: int = 0
    toggles: int = 0
    balls_pass: bool = False  # swap_lane only: same-kind balls may share/cross cells
    script: tuple[int, ...] | None = None  # scripted agent actions for scenario families

    def free(self, x, y, *, ignore=None, agent_blocks=True) -> bool:
        if not (0 <= x < SIZE and 0 <= y < SIZE) or self.terrain[y][x] in OPAQUE:
            return False
        if agent_blocks and (x, y) == self.agent:
            return False
        return not any((o.x, o.y) == (x, y) and o is not ignore
                       and not (self.balls_pass and ignore is not None and o.kind == ignore.kind == "ball")
                       for o in self.objects)

    def line_of_sight(self, x, y) -> bool:
        ax, ay = self.agent
        n = max(abs(x - ax), abs(y - ay))
        for i in range(1, n):
            fx, fy = ax + (x - ax) * i / n, ay + (y - ay) * i / n
            cells = {(int(fx + 0.5 - 1e-9), int(fy + 0.5 - 1e-9)), (int(fx + 0.5), int(fy + 0.5))}
            if all(self.terrain[cy][cx] in OPAQUE for cx, cy in cells):
                return False
        return True

    def visibility_of(self, x, y) -> str:
        ax, ay = self.agent
        if max(abs(x - ax), abs(y - ay)) > VIEW_RADIUS:
            return "out_of_view"
        return "visible" if self.line_of_sight(x, y) else "occluded"

    def apply(self, action) -> None:
        action = Action(action)
        if action is Action.INTERACT and self.agent in self.switches:
            dx_, dy_ = self.switches[self.agent]
            cur = self.terrain[dy_][dx_]
            occupied = any((o.x, o.y) == (dx_, dy_) for o in self.objects)
            if cur == DOOR_CLOSED or not occupied:
                self.terrain[dy_][dx_] = DOOR_OPEN if cur == DOOR_CLOSED else DOOR_CLOSED
                self.toggles += 1
        elif action in DELTA:
            dx, dy = DELTA[action]
            tx, ty = self.agent[0] + dx, self.agent[1] + dy
            box = next((o for o in self.objects if (o.x, o.y) == (tx, ty)), None)
            if box is not None and box.kind == "box" and self.free(tx + dx, ty + dy):
                box.x, box.y = tx + dx, ty + dy
                self.agent = (tx, ty)
            elif self.free(tx, ty, agent_blocks=False):
                self.agent = (tx, ty)
        for o in self.objects:
            if o.kind != "ball":
                continue
            for vx, vy in ((o.vx, o.vy), (-o.vx, o.vy), (o.vx, -o.vy), (-o.vx, -o.vy)):
                if self.free(o.x + vx, o.y + vy, ignore=o):
                    o.vx, o.vy, o.x, o.y = vx, vy, o.x + vx, o.y + vy
                    break
        self.step += 1

    # ---------------------------------------------------------------- views
    def egocentric_view(self) -> list[list[int]]:
        ax, ay = self.agent
        rows = []
        for dy in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
            row = []
            for dx in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
                x, y = ax + dx, ay + dy
                if not (0 <= x < SIZE and 0 <= y < SIZE):
                    row.append(WALL)
                else:
                    row.append(self.terrain[y][x] if self.visibility_of(x, y) == "visible" else UNSEEN)
            rows.append(row)
        return rows

    def visible_objects(self) -> list[list]:
        ax, ay = self.agent
        return sorted([o.x - ax, o.y - ay, o.appearance] for o in self.objects
                      if self.visibility_of(o.x, o.y) == "visible")

    def public_observation(self, episode_id: UUID, last_action) -> dict:
        view, objs = self.egocentric_view(), self.visible_objects()
        rgb = render(view, objs)
        obs = {"kind": "gridlab_v1_observation", "revision": REVISION,
               "observation_id": str(uuid5(episode_id, f"obs:{self.step}")), "step": self.step,
               "agent_xy": list(self.agent), "last_action": None if last_action is None else int(last_action),
               "view": view, "visible_objects": objs,
               "rgb_shape": [80, 80, 3], "rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
               "rgb_b64": base64.b64encode(rgb.tobytes()).decode()}
        obs["observation_sha256"] = digest(obs)
        return obs

    def private_state(self) -> dict:
        return {"step": self.step, "agent_xy": list(self.agent), "toggles": self.toggles,
                "doors": sorted([list(d), self.terrain[d[1]][d[0]]] for d in self.switches.values()),
                "objects": [{"object_id": str(o.object_id), "kind": o.kind, "appearance": o.appearance,
                             "xy": [o.x, o.y], "v": [o.vx, o.vy], "visibility": self.visibility_of(o.x, o.y)}
                            for o in self.objects]}

    def layout_sha256(self) -> str:
        return digest({"terrain": self.terrain, "agent": list(self.agent),
                       "switches": sorted([list(k), list(v)] for k, v in self.switches.items()),
                       "objects": [[o.kind, o.x, o.y, o.vx, o.vy] for o in self.objects]})


def render(view: list[list[int]], objects: list[list]) -> np.ndarray:
    """80x80x3 uint8: 16 px per egocentric cell; objects drawn as disc/square, agent at centre."""
    img = np.zeros((80, 80, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:CELL_PX, 0:CELL_PX]
    disc = (xx - 7.5) ** 2 + (yy - 7.5) ** 2 <= 30
    square = (xx >= 3) & (xx <= 12) & (yy >= 3) & (yy <= 12)
    for r, row in enumerate(view):
        for c, code in enumerate(row):
            img[r * CELL_PX:(r + 1) * CELL_PX, c * CELL_PX:(c + 1) * CELL_PX] = COLORS[code]
    for dx, dy, appearance in objects:
        r, c = dy + VIEW_RADIUS, dx + VIEW_RADIUS
        tile = img[r * CELL_PX:(r + 1) * CELL_PX, c * CELL_PX:(c + 1) * CELL_PX]
        tile[disc if appearance == "red_disc" else square] = OBJ_COLORS[appearance]
    centre = img[2 * CELL_PX:3 * CELL_PX, 2 * CELL_PX:3 * CELL_PX]
    centre[(xx >= 5) & (xx <= 10) & (yy >= 5) & (yy <= 10)] = AGENT_COLOR
    return img


def world_id_for(seed: int, family: str) -> UUID:
    return uuid5(NAMESPACE, f"{REVISION}:{family}:world:{seed}")


def _scenario(seed: int, family: str) -> World:
    """Scripted scenarios guaranteeing S04 special events (geometry fixed, seed only names the world)."""
    terrain = [[WALL if x in (0, SIZE - 1) or y in (0, SIZE - 1) else FREE for x in range(SIZE)]
               for y in range(SIZE)]
    wid = world_id_for(seed, family)
    terrain[7][5] = PILLAR
    if family == "swap_lane":
        # two same-appearance balls cross behind the pillar at the same step -> identity_swap
        objs = [Obj(uuid5(wid, "object:0"), "ball", 3, 6, 1, 0), Obj(uuid5(wid, "object:1"), "ball", 7, 6, -1, 0)]
        return World(seed, family, wid, terrain, {}, (5, 8), objs, balls_pass=True,
                     script=(int(Action.WAIT),) * 6)
    # occlusion_walk: observer motion hides a static box behind the pillar for 3 steps
    objs = [Obj(uuid5(wid, "object:0"), "box", 5, 6)]
    return World(seed, family, wid, terrain, {}, (4, 8), objs,
                 script=(int(Action.RIGHT), int(Action.WAIT), int(Action.WAIT), int(Action.RIGHT),
                         int(Action.WAIT), int(Action.LEFT)))


def make_world(seed: int, *, family: str = "open", pillars: int = 8, balls: int = 2, boxes: int = 1) -> World:
    if seed < 0 or family not in FAMILIES or balls < 0 or boxes < 0 or pillars < 0:
        raise ValueError("invalid GridLab-v1 parameters")
    if family in ("swap_lane", "occlusion_walk"):
        return _scenario(seed, family)
    rng = random.Random(f"{REVISION}:{family}:{seed}")
    terrain = [[WALL if x in (0, SIZE - 1) or y in (0, SIZE - 1) else FREE for x in range(SIZE)]
               for y in range(SIZE)]
    switches = {}
    reserved = set()
    if family == "door_room":
        door_y = rng.randrange(2, SIZE - 2)
        for y in range(1, SIZE - 1):
            terrain[y][SIZE // 2] = DOOR_CLOSED if y == door_y else WALL
        sw = (rng.randrange(1, SIZE // 2), rng.randrange(1, SIZE - 1))
        terrain[sw[1]][sw[0]] = SWITCH
        switches[sw] = (SIZE // 2, door_y)
        reserved = {(SIZE // 2 - 1, door_y), (SIZE // 2 + 1, door_y), sw}
    interior = [(x, y) for y in range(1, SIZE - 1) for x in range(1, SIZE - 1)
                if terrain[y][x] == FREE and (x, y) not in reserved]
    rng.shuffle(interior)
    if pillars + balls + boxes + 1 > len(interior):
        raise ValueError("too many entities for the grid")
    for x, y in interior[:pillars]:
        terrain[y][x] = PILLAR
    free = interior[pillars:]
    if family == "door_room":  # agent starts on the switch side
        left = [p for p in free if p[0] < SIZE // 2]
        agent = left[-1]
        free.remove(agent)
    else:
        agent = free.pop()
    wid = world_id_for(seed, family)
    objects = []
    for i, kind in enumerate(["ball"] * balls + ["box"] * boxes):
        x, y = free.pop()
        vx, vy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]) \
            if kind == "ball" else (0, 0)
        objects.append(Obj(uuid5(wid, f"object:{i}"), kind, x, y, vx, vy))
    return World(seed, family, wid, terrain, switches, agent, objects)


def decode_rgb(obs: dict) -> np.ndarray:
    raw = base64.b64decode(obs["rgb_b64"])
    if hashlib.sha256(raw).hexdigest() != obs["rgb_sha256"] or len(raw) != 80 * 80 * 3:
        raise ValueError("rgb payload does not match its digest")
    return np.frombuffer(raw, dtype=np.uint8).reshape(80, 80, 3)


def public_content_digest(obs: dict) -> str:
    """Content-only digest (no ids/step) for S04 cross-partition overlap checks."""
    return digest({k: obs[k] for k in ("view", "visible_objects")})


# ---------------------------------------------------------------- events (private truth only)

OCCLUSION_HELDOUT_K = 3  # registered threshold proposal: train must have max k < 3


def detect_events(states: list[dict]) -> list[dict]:
    """Events from evaluator-private per-step states.

    * occlusion: visible at t0, occluded for t0+1..t0+k, visible at t0+k+1;
    * same_appearance_confusion: two same-appearance objects visible together within 1 cell;
    * identity_swap: two same-appearance objects both unseen, then on reappearance each is
      nearer the *other's* last-seen position (nearest-last-seen association would swap);
    * door_toggle: the agent toggled a door.
    """
    events = []
    n = len(states[0]["objects"])
    vis = [[s["objects"][k]["visibility"] for s in states] for k in range(n)]
    for k in range(n):
        t = 0
        while t < len(states) - 1:
            if vis[k][t] == "visible" and vis[k][t + 1] == "occluded":
                e = t + 1
                while e < len(states) and vis[k][e] == "occluded":
                    e += 1
                if e < len(states) and vis[k][e] == "visible":
                    events.append({"type": "occlusion", "object_index": k, "t0": t, "k": e - t - 1})
                t = e
            else:
                t += 1
    for i in range(n):
        for j in range(i + 1, n):
            if states[0]["objects"][i]["appearance"] != states[0]["objects"][j]["appearance"]:
                continue
            last = {i: None, j: None}
            unseen_since = None
            for t, s in enumerate(states):
                oi, oj = s["objects"][i], s["objects"][j]
                vi, vj = oi["visibility"] == "visible", oj["visibility"] == "visible"
                if vi and vj and max(abs(oi["xy"][0] - oj["xy"][0]), abs(oi["xy"][1] - oj["xy"][1])) <= 1:
                    events.append({"type": "same_appearance_confusion", "objects": [i, j], "t": t})
                if not vi and not vj and last[i] and last[j]:
                    unseen_since = unseen_since if unseen_since is not None else t
                if vi and vj and unseen_since is not None:
                    def d(a, b):
                        return abs(a[0] - b[0]) + abs(a[1] - b[1])
                    if d(oi["xy"], last[j]) + d(oj["xy"], last[i]) < d(oi["xy"], last[i]) + d(oj["xy"], last[j]):
                        events.append({"type": "identity_swap", "objects": [i, j], "hidden_from": unseen_since,
                                       "reappear": t})
                    unseen_since = None
                if vi:
                    last[i] = oi["xy"]
                if vj:
                    last[j] = oj["xy"]
    for t in range(1, len(states)):
        if states[t]["toggles"] != states[t - 1]["toggles"]:
            events.append({"type": "door_toggle", "t": t})
    return events


def path_sha256(states: list[dict]) -> str:
    return digest([s["agent_xy"] for s in states])


def heldout_flags(events: list[dict]) -> dict[str, bool]:
    """S04 held-out subset predicates (2D). unseen_paths is relative to train paths, see check."""
    return {
        "occlusion": any(e["type"] == "occlusion" and e["k"] >= OCCLUSION_HELDOUT_K for e in events),
        "similar_objects": any(e["type"] in ("identity_swap", "same_appearance_confusion") for e in events),
    }


def check_heldout_leakage(episodes: list[dict]) -> dict:
    """episodes: dicts with partition, flags, path_sha256, unseen_paths(bool), content_digests.

    Raises if any train episode carries a held-out defining combination, or a
    held-out unseen-path episode reuses a train path. Returns overlap stats of
    public content digests between partitions (threshold still to be registered).
    """
    train = [e for e in episodes if e["partition"] == "train"]
    for e in train:
        bad = [k for k, v in e["flags"].items() if v]
        if bad or e.get("unseen_paths"):
            raise ValueError(f"held-out combination {bad or ['unseen_paths']} in train")
    train_paths = {e["path_sha256"] for e in train}
    for e in episodes:
        if e.get("unseen_paths") and e["path_sha256"] in train_paths:
            raise ValueError("unseen_paths episode reuses a train path")
    parts: dict[str, set] = {}
    for e in episodes:
        parts.setdefault(e["partition"], set()).update(e["content_digests"])
    names = sorted(parts)
    overlap = {f"{a}|{b}": len(parts[a] & parts[b]) for i, a in enumerate(names) for b in names[i + 1:]}
    return {"content_overlap": overlap, "content_sizes": {k: len(v) for k, v in parts.items()},
            "note": "overlap threshold not yet registered (S04 【待登记】)"}


__all__ = ["canonical", "digest"]
