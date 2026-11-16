"""S07: GridLab-v1 episode writer/loader (C0-style public/private separation).

Same directory contract as S06 ``gridlab_trajectory``: ``public.jsonl`` (header
+ one egocentric observation per step, including the 80x80 RGB frame as
base64 with its own SHA), ``private.json`` (truth, events, held-out flags, S05
annotations) and ``manifest.json``. The public loader never opens private.json.

Annotation: visible -> observed grid_xy estimate citing a ``GridCellRef`` whose
world cell equals agent_xy + the public relative offset; occluded and
out_of_view -> a *predicted* estimate (constant velocity from the last two
sightings, else last position) or none if never seen. ``lost`` is reserved for
"should be visible but not found" and is never produced by this truth-based
annotator. Partitions are decided per world *before* annotation, from private
events, so held-out combinations never enter train.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from uuid import UUID, uuid5

from ainerzero.core import spacetime_records as sr
from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.core.spacetime import TimeIndex
from ainerzero.data.gridlab_trajectory import FILES, digest_bytes
from ainerzero.environments import gridlab_v1 as v1
from ainerzero.environments.gridlab2d import canonical, check_split_leakage, digest

FRAME = dict(coordinate_kind="grid_xy", frame_id="gridlab-v1-world", frame_revision=0, unit="cell",
             axes="x_right_y_down")
VIS = {"visible": sr.Visibility.VISIBLE, "occluded": sr.Visibility.OCCLUDED,
       "out_of_view": sr.Visibility.OUT_OF_VIEW}


def rollout(world: v1.World, *, steps: int, policy_seed: int = 0):
    """Seeded scripted-random agent: interacts when standing on a switch, else random."""
    rng = random.Random(f"{v1.REVISION}:policy:{world.family}:{world.seed}:{policy_seed}")
    episode_id = uuid5(world.world_id, f"episode:{policy_seed}")
    public, private, actions = [world.public_observation(episode_id, None)], [world.private_state()], []
    for i in range(steps):
        if world.script is not None:
            a = v1.Action(world.script[i % len(world.script)])
        elif world.agent in world.switches and rng.random() < 0.8:
            a = v1.Action.INTERACT
        else:
            a = v1.Action(rng.choice([0, 1, 2, 3, 3, 5]))
        world.apply(a)
        actions.append(int(a))
        public.append(world.public_observation(episode_id, a))
        private.append(world.private_state())
    return episode_id, public, private, actions


def annotate(world, run_id, episode_id, partition, public, private):
    tracks, truth = [], []
    for k, obj in enumerate(world.objects):
        states, sightings = [], []
        for obs, st in zip(public, private):
            t = TimeIndex(run_id=run_id, world_id=world.world_id, episode_id=episode_id, partition=partition,
                          step=st["step"], available_at_step=st["step"])
            o = st["objects"][k]
            truth.append(sr.SpatialEstimate(
                estimate_id=uuid5(episode_id, f"truth:{k}:{t.step}"), time=t, value=tuple(map(float, o["xy"])),
                uncertainty_basis="none", origin="evaluator_private", **FRAME))
            vis = VIS[o["visibility"]]
            if vis is sr.Visibility.VISIBLE:
                ax, ay = obs["agent_xy"]
                rel = [o["xy"][0] - ax, o["xy"][1] - ay, o["appearance"]]
                assert rel in obs["visible_objects"]
                ref = sr.GridCellRef(time=t, x=o["xy"][0], y=o["xy"][1],
                                     observation_id=UUID(obs["observation_id"]),
                                     observation_sha256=obs["observation_sha256"], origin=OriginKind.OBSERVED)
                est = sr.SpatialEstimate(estimate_id=uuid5(episode_id, f"seen:{k}:{t.step}"), time=t,
                                         value=(float(ref.x), float(ref.y)), uncertainty_basis="none",
                                         supports=(ref,), origin="observed", **FRAME)
                sightings.append(ref)
            elif sightings:
                last = sightings[-1]
                x, y = float(last.x), float(last.y)
                supports = (last,)
                if len(sightings) >= 2:
                    prev = sightings[-2]
                    dt = last.time.step - prev.time.step
                    h = t.step - last.time.step
                    x += (last.x - prev.x) / dt * h
                    y += (last.y - prev.y) / dt * h
                    supports = (prev, last)
                est = sr.SpatialEstimate(estimate_id=uuid5(episode_id, f"pred:{k}:{t.step}"), time=t,
                                         value=(x, y), uncertainty_basis="none", supports=supports,
                                         origin="predicted", **FRAME)
            else:
                est = None
            states.append(sr.TrackState(time=t, visibility=vis, estimate=est))
        tracks.append(sr.EntityTrack(world_id=world.world_id, track_id=obj.object_id, concept_id=obj.kind,
                                     states=tuple(states), asserted_at_step=public[-1]["step"]))
    return tracks, truth


def simulate(seed: int, family: str, steps: int, **kw) -> dict:
    """Pure rollout + private event analysis; no partition yet."""
    world = v1.make_world(seed, family=family, **kw)
    initial = {"layout_sha256": world.layout_sha256(), "terrain": [r[:] for r in world.terrain]}
    episode_id, public, private, actions = rollout(world, steps=steps)
    events = v1.detect_events(private)
    return {"world": world, "episode_id": episode_id, "public": public, "private": private,
            "actions": actions, "events": events, "flags": v1.heldout_flags(events),
            "path_sha256": v1.path_sha256(private), **initial}


def assign_with_heldout(sims: list[dict]) -> dict[UUID, DatasetPartition]:
    """Worlds with any held-out flag go to development/final (alternating, hash order); the rest
    go to train except one each for development and final when enough remain."""
    import hashlib
    key = lambda s: hashlib.sha256(f"split:{s['world'].world_id}".encode()).hexdigest()  # noqa: E731
    flagged = sorted((s for s in sims if any(s["flags"].values())), key=key)
    clean = sorted((s for s in sims if not any(s["flags"].values())), key=key)
    out = {}
    for i, s in enumerate(flagged):
        out[s["world"].world_id] = (DatasetPartition.DEVELOPMENT, DatasetPartition.FINAL)[i % 2]
    for i, s in enumerate(clean):
        part = DatasetPartition.TRAIN
        if len(clean) >= 4 and i == len(clean) - 1:
            part = DatasetPartition.FINAL
        if len(clean) >= 4 and i == len(clean) - 2:
            part = DatasetPartition.DEVELOPMENT
        out[s["world"].world_id] = part
    return out


def write_episode(root: Path, sim: dict, *, run_id: UUID, partition: DatasetPartition, unseen_paths: bool):
    world = sim["world"]
    tracks, truth = annotate(world, run_id, sim["episode_id"], partition, sim["public"], sim["private"])
    steps = len(sim["actions"])
    header = {"kind": "gridlab_v1_header", "revision": v1.REVISION, "run_id": str(run_id),
              "world_id": str(world.world_id), "episode_id": str(sim["episode_id"]), "partition": str(partition),
              "size": v1.SIZE, "view_radius": v1.VIEW_RADIUS, "transition_count": steps,
              "actions": sim["actions"]}
    pub = b"".join(canonical(x) + b"\n" for x in [header, *sim["public"]])
    priv = canonical({
        "kind": "gridlab_v1_private", "seed": world.seed, "family": world.family,
        "layout_sha256": sim["layout_sha256"], "initial_terrain": sim["terrain"],
        "switches": sorted([list(a), list(b)] for a, b in world.switches.items()),
        "states": sim["private"], "events": sim["events"], "heldout_flags": sim["flags"],
        "unseen_paths": unseen_paths, "path_sha256": sim["path_sha256"],
        "entity_tracks": [json.loads(sr.to_canonical_json(t)) for t in tracks],
        "truth_estimates": [json.loads(sr.to_canonical_json(e)) for e in truth],
    }) + b"\n"
    d = root / str(sim["episode_id"])
    d.mkdir(parents=True, exist_ok=False)
    (d / "public.jsonl").write_bytes(pub)
    (d / "private.json").write_bytes(priv)
    manifest = {"schema_version": 1, "revision": v1.REVISION, "episode_id": str(sim["episode_id"]),
                "world_id": str(world.world_id), "partition": str(partition), "transition_count": steps,
                "files": {n: {"size_bytes": len(b), "sha256": digest_bytes(b)}
                          for n, b in (("public.jsonl", pub), ("private.json", priv))}}
    (d / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return d


def _manifest(d: Path) -> dict:
    m = json.loads((d / "manifest.json").read_bytes())
    if m.get("revision") != v1.REVISION or set(m.get("files", {})) != set(FILES):
        raise ValueError("manifest must describe exactly public.jsonl and private.json")
    if {p.name for p in d.iterdir()} != {*FILES, "manifest.json"}:
        raise ValueError("unexpected files in episode directory")
    return m


def _verified(d: Path, name: str, m: dict) -> bytes:
    b = (d / name).read_bytes()
    if len(b) != m["files"][name]["size_bytes"] or digest_bytes(b) != m["files"][name]["sha256"]:
        raise ValueError(f"{name} does not match manifest")
    return b


def load_public(d: Path) -> dict:
    m = _manifest(d)
    lines = [json.loads(x) for x in _verified(d, "public.jsonl", m).decode().splitlines()]
    header, obs = lines[0], lines[1:]
    if header["episode_id"] != m["episode_id"] or len(obs) != m["transition_count"] + 1:
        raise ValueError("public trajectory does not match manifest")
    for i, o in enumerate(obs):
        if o["step"] != i or digest({k: v for k, v in o.items() if k != "observation_sha256"}) != \
                o["observation_sha256"]:
            raise ValueError("observation step or SHA mismatch")
        v1.decode_rgb(o)
    return {"header": header, "observations": obs, "manifest": m}


def load_private(d: Path) -> dict:
    m = _manifest(d)
    pub = load_public(d)
    p = json.loads(_verified(d, "private.json", m))
    tracks = [sr.load_record(sr.EntityTrack, canonical(t)) for t in p["entity_tracks"]]
    truth = [sr.load_record(sr.SpatialEstimate, canonical(e)) for e in p["truth_estimates"]]
    by_id = {o["observation_id"]: o for o in pub["observations"]}
    for t in tracks:
        for s in t.states:
            if s.visibility is not sr.Visibility.VISIBLE:
                continue
            (ref,) = s.estimate.supports
            o = by_id.get(str(ref.observation_id))
            ax, ay = (o or {}).get("agent_xy", (None, None))
            if o is None or o["observation_sha256"] != ref.observation_sha256 or \
                    [ref.x - ax, ref.y - ay] not in [v[:2] for v in o["visible_objects"]]:
                raise ValueError("track evidence does not resolve to a visible public object")
    return {**p, "entity_tracks": tracks, "truth_estimates": truth, "public": pub}


SAMPLE_SPECS = ((21, "open"), (22, "open"), (23, "open"), (24, "door_room"), (25, "door_room"),
                (26, "door_room"), (27, "swap_lane"), (28, "occlusion_walk"))


def write_sample(root: Path, *, specs=SAMPLE_SPECS, steps: int = 16) -> dict:
    run_id = uuid5(UUID(int=0), f"{v1.REVISION}:s07-sample")
    sims = [simulate(seed, fam, steps) for seed, fam in specs]
    splits = assign_with_heldout(sims)
    train_paths = {s["path_sha256"] for s in sims if splits[s["world"].world_id] is DatasetPartition.TRAIN}
    eps = []
    for s in sims:
        part = splits[s["world"].world_id]
        unseen = part is not DatasetPartition.TRAIN and s["path_sha256"] not in train_paths
        write_episode(root, s, run_id=run_id, partition=part, unseen_paths=unseen)
        eps.append({"world_id": str(s["world"].world_id), "seed": s["world"].seed, "family": s["world"].family,
                    "partition": str(part), "layout_sha256": s["layout_sha256"], "flags": s["flags"],
                    "unseen_paths": unseen, "path_sha256": s["path_sha256"],
                    "events": sorted({e["type"] for e in s["events"]}),
                    "content_digests": sorted({v1.public_content_digest(o) for o in s["public"]})})
    check_split_leakage(eps)
    stats = v1.check_heldout_leakage(eps)
    summary = {"revision": v1.REVISION, "episodes": eps, "leakage": stats}
    (root / "splits.json").write_bytes(canonical(summary) + b"\n")
    return summary
