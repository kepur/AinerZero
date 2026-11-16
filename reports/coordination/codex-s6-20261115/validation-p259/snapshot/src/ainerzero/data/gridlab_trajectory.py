"""S06: GridLab episode writer/loader with C0-style public/private separation.

Layout per episode directory (mirrors C0): ``public.jsonl`` (header line + one
public observation per step), ``private.json`` (evaluator-private truth and
S05 annotations) and ``manifest.json`` (exact sizes/SHAs of both). The public
loader never opens ``private.json``.

Annotations: for every object, an S05 ``EntityTrack`` whose visible states rest
on an *observed* ``SpatialEstimate`` (grid_xy, no z) citing a ``GridCellRef``
into the public observation of that same step, and whose occluded/out-of-view
states cite only a *predicted* last-seen-position estimate (or none if never
seen). True positions are ``evaluator_private`` estimates, stored privately.
Track identity is ground truth and therefore private too.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from uuid import UUID, uuid5

from ainerzero.core import spacetime_records as sr
from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.core.spacetime import TimeIndex
from ainerzero.environments.gridlab2d import (
    GRIDLAB_REVISION,
    Action,
    GridWorld,
    canonical,
    digest,
)

FRAME = dict(coordinate_kind="grid_xy", frame_id="gridlab2d-world", frame_revision=0, unit="cell",
             axes="x_right_y_down")
FILES = ("public.jsonl", "private.json")
VIS = {"visible": sr.Visibility.VISIBLE, "occluded": sr.Visibility.OCCLUDED,
       "out_of_view": sr.Visibility.OUT_OF_VIEW}  # S07 migration (was LOST)


def _time(run_id, world: GridWorld, episode_id, partition, step) -> TimeIndex:
    return TimeIndex(run_id=run_id, world_id=world.world_id, episode_id=episode_id,
                     partition=partition, step=step, available_at_step=step)


def rollout(world: GridWorld, *, steps: int, policy_seed: int):
    """Seeded random agent; returns (episode_id, public obs list, private states, actions)."""
    rng = random.Random(f"{GRIDLAB_REVISION}:policy:{world.seed}:{policy_seed}")
    episode_id = uuid5(world.world_id, f"episode:{policy_seed}")
    public, private, actions = [world.public_observation(episode_id, None)], [world.private_state()], []
    for _ in range(steps):
        a = Action(rng.randrange(len(Action)))
        world.apply(a)
        actions.append(int(a))
        public.append(world.public_observation(episode_id, a))
        private.append(world.private_state())
    return episode_id, public, private, actions


def annotate(world, run_id, episode_id, partition, public, private):
    tracks, truth = [], []
    for k, obj in enumerate(world.objects):
        states, last_ref = [], None
        for obs, st in zip(public, private):
            t = _time(run_id, world, episode_id, partition, st["step"])
            o = st["objects"][k]
            assert o["object_id"] == str(obj.object_id)
            truth.append(sr.SpatialEstimate(
                estimate_id=uuid5(episode_id, f"truth:{k}:{t.step}"), time=t, value=tuple(map(float, o["xy"])),
                uncertainty_basis="none", origin="evaluator_private", **FRAME))
            vis = VIS[o["visibility"]]
            if vis is sr.Visibility.VISIBLE:
                ref = sr.GridCellRef(time=t, x=o["xy"][0], y=o["xy"][1],
                                     observation_id=UUID(obs["observation_id"]),
                                     observation_sha256=obs["observation_sha256"], origin=OriginKind.OBSERVED)
                est = sr.SpatialEstimate(estimate_id=uuid5(episode_id, f"seen:{k}:{t.step}"), time=t,
                                         value=(float(ref.x), float(ref.y)), uncertainty_basis="none",
                                         supports=(ref,), origin="observed", **FRAME)
                last_ref = ref
            elif last_ref is not None:
                est = sr.SpatialEstimate(estimate_id=uuid5(episode_id, f"hold:{k}:{t.step}"), time=t,
                                         value=(float(last_ref.x), float(last_ref.y)), uncertainty_basis="none",
                                         supports=(last_ref,), origin="predicted", **FRAME)
            else:
                est = None
            states.append(sr.TrackState(time=t, visibility=vis, estimate=est))
        tracks.append(sr.EntityTrack(world_id=world.world_id, track_id=obj.object_id, concept_id=obj.kind,
                                     states=tuple(states), asserted_at_step=public[-1]["step"]))
    return tracks, truth


def write_episode(root: Path, world: GridWorld, *, run_id: UUID, partition: DatasetPartition,
                  steps: int, policy_seed: int = 0) -> Path:
    layout = world.layout_sha256()
    episode_id, public, private, actions = rollout(world, steps=steps, policy_seed=policy_seed)
    tracks, truth = annotate(world, run_id, episode_id, partition, public, private)
    header = {"kind": "gridlab_header", "revision": GRIDLAB_REVISION, "run_id": str(run_id),
              "world_id": str(world.world_id), "episode_id": str(episode_id),
              "partition": str(partition), "width": world.width, "height": world.height,
              "view_radius": world.view_radius, "transition_count": steps, "actions": actions}
    pub = b"".join(canonical(x) + b"\n" for x in [header, *public])
    priv = canonical({
        "kind": "gridlab_private", "seed": world.seed, "policy_seed": policy_seed, "layout_sha256": layout,
        "terrain": world.terrain, "states": private,
        "entity_tracks": [json.loads(sr.to_canonical_json(t)) for t in tracks],
        "truth_estimates": [json.loads(sr.to_canonical_json(e)) for e in truth],
    }) + b"\n"
    d = root / str(episode_id)
    d.mkdir(parents=True, exist_ok=False)
    (d / "public.jsonl").write_bytes(pub)
    (d / "private.json").write_bytes(priv)
    manifest = {"schema_version": 1, "revision": GRIDLAB_REVISION, "episode_id": str(episode_id),
                "world_id": str(world.world_id), "partition": str(partition), "transition_count": steps,
                "files": {n: {"size_bytes": len(b), "sha256": digest_bytes(b)}
                          for n, b in (("public.jsonl", pub), ("private.json", priv))}}
    (d / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return d


def digest_bytes(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _manifest(d: Path) -> dict:
    m = json.loads((d / "manifest.json").read_bytes())
    if m.get("revision") != GRIDLAB_REVISION or set(m.get("files", {})) != set(FILES):
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
    """Student view: verifies public.jsonl against the manifest, never reads private.json."""
    m = _manifest(d)
    lines = [json.loads(x) for x in _verified(d, "public.jsonl", m).decode().splitlines()]
    header, obs = lines[0], lines[1:]
    if header["episode_id"] != m["episode_id"] or len(obs) != m["transition_count"] + 1:
        raise ValueError("public trajectory does not match manifest")
    for i, o in enumerate(obs):
        body = {k: v for k, v in o.items() if k != "observation_sha256"}
        if o["step"] != i or digest(body) != o["observation_sha256"]:
            raise ValueError("observation step or SHA mismatch")
    return {"header": header, "observations": obs, "manifest": m}


def load_private(d: Path) -> dict:
    """Evaluator view: verifies and revalidates every S05 record."""
    m = _manifest(d)
    pub = load_public(d)
    p = json.loads(_verified(d, "private.json", m))
    tracks = [sr.load_record(sr.EntityTrack, canonical(t)) for t in p["entity_tracks"]]
    truth = [sr.load_record(sr.SpatialEstimate, canonical(e)) for e in p["truth_estimates"]]
    by_id = {o["observation_id"]: o for o in pub["observations"]}
    for t in tracks:
        for s in t.states:
            for ref in (s.estimate.supports if s.estimate else ()):
                o = by_id.get(str(ref.observation_id))
                if o is None or o["observation_sha256"] != ref.observation_sha256 or \
                        [ref.x, ref.y] not in [v[:2] for v in o["visible_objects"]]:
                    raise ValueError("track evidence does not resolve to a visible public object")
    return {**p, "entity_tracks": tracks, "truth_estimates": truth, "public": pub}


def write_sample(root: Path, *, seeds=(11, 12, 13, 14, 15), steps: int = 12) -> list[Path]:
    from ainerzero.environments.gridlab2d import assign_splits, check_split_leakage, make_world

    run_id = uuid5(UUID(int=0), f"{GRIDLAB_REVISION}:s06-sample")
    worlds = [make_world(s) for s in seeds]
    splits = assign_splits([w.world_id for w in worlds])
    eps = [{"world_id": str(w.world_id), "partition": str(splits[w.world_id]), "seed": w.seed,
            "layout_sha256": w.layout_sha256()} for w in worlds]
    check_split_leakage(eps)
    dirs = [write_episode(root, w, run_id=run_id, partition=splits[w.world_id], steps=steps) for w in worlds]
    (root / "splits.json").write_bytes(canonical({"revision": GRIDLAB_REVISION, "episodes": eps}) + b"\n")
    return dirs
