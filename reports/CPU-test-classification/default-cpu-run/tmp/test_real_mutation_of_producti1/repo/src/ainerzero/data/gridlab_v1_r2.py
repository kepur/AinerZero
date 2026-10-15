"""S07-R2: GridLab-v1 split by world/trajectory identity and held-out rules only.

Reverts the S07-R1 rule (union-find on single-frame overlap, which swapped
seeds 25/27). Partition decision inputs are exclusively:
* world identity (world_id, seed+family, initial layout SHA);
* trajectory identity (content digest of the whole public observation
  sequence without ids, and the agent path);
* held-out rules (S04): flagged worlds -> development/final only; occlusion k>=3.
The assignment is the original S07 ``assign_with_heldout``. Duplicate threshold
for world/trajectory/public-file identity across partitions is 0 (rejected).
Single-frame public overlap (content digests, RGB frame SHAs) is *reported
only* and never used to choose worlds. Scripted scenario families are marked
and reported separately.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5

from ainerzero.data import gridlab_v1_trajectory as gt
from ainerzero.environments import gridlab_v1 as v1
from ainerzero.environments.gridlab2d import canonical, check_split_leakage, digest

MANIFEST_NAME = "split_manifest.json"
# Registered identity (coordinator registration 2026-10-13). The validator must compare
# against *this* value, never only against a caller-supplied argument: a caller could
# otherwise re-sign a tampered manifest and walk straight through (review finding A-F1).
FROZEN_MANIFEST_SHA256 = "52eda9a56722eabe1c80e797e969ab33cd371377597fa56a4f61f7450d6eb3b6"
REGISTERED_KIND = "gridlab_v1_split_manifest"
REGISTERED_RULE = "world/trajectory identity + held-out flags; frame overlap reported only"
EPISODE_FILE_NAMES = ("manifest.json", "public.jsonl", "private.json")
SCRIPTED = ("swap_lane", "occlusion_walk")
_KEYS = ("world_id", "seed", "family", "scripted", "partition", "flags", "unseen_paths", "path_sha256",
         "layout_sha256", "trajectory_sha256", "episode_id", "files")


def trajectory_sha256(observations: list[dict]) -> str:
    """Identity of a whole public trajectory, independent of run/episode/observation ids."""
    return digest([{k: o[k] for k in ("step", "agent_xy", "last_action", "view", "visible_objects",
                                      "rgb_sha256")} for o in observations])


def recompute_path_sha256(public: dict) -> str:
    """Recompute the agent path from the actual public observations (A-F2 closure).

    Trusting the declared `path_sha256` lets a tamperer edit the manifest *and* the
    private record consistently while leaving `public.jsonl` untouched; recomputing from
    the real `agent_xy` sequence makes the invariant depend on public content only.
    """
    return v1.path_sha256(public["observations"])


def _cross(sets: dict[str, set]) -> dict[str, int]:
    names = sorted(sets)
    return {f"{a}|{b}": len(sets[a] & sets[b]) for i, a in enumerate(names) for b in names[i + 1:]}


def identity_checks(root: Path, episodes: list[dict]) -> dict:
    """Reject world/trajectory/public-file duplicates across partitions; report frame overlap."""
    check_split_leakage(episodes)  # world_id / seed / layout across partitions
    v1.check_heldout_leakage(episodes)  # held-out combinations not in train; unseen paths
    world, traj, pubfile, frames, content, paths = {}, {}, {}, {}, {}, {}
    for e in episodes:
        p = e["partition"]
        pub = gt.load_public(root / e["episode_id"])
        obs = pub["observations"]
        if trajectory_sha256(obs) != e["trajectory_sha256"]:
            raise ValueError("trajectory identity does not match its record")
        real_path = recompute_path_sha256(pub)
        if real_path != e["path_sha256"]:
            raise ValueError(f"{e['episode_id']} declared path differs from the public trajectory")
        world.setdefault(p, set()).add(e["world_id"])
        paths.setdefault(p, set()).add(real_path)
        traj.setdefault(p, set()).add(e["trajectory_sha256"])
        pubfile.setdefault(p, set()).add(hashlib.sha256((root / e["episode_id"] / "public.jsonl")
                                                        .read_bytes()).hexdigest())
        frames.setdefault(p, set()).update(o["rgb_sha256"] for o in obs)
        content.setdefault(p, set()).update(v1.public_content_digest(o) for o in obs)
    train_paths = {recompute_path_sha256(gt.load_public(root / e["episode_id"]))
                   for e in episodes if e["partition"] == "train"}
    for e in episodes:
        if e["partition"] != "train":
            expected_unseen = recompute_path_sha256(gt.load_public(root / e["episode_id"])) not in train_paths
            if bool(e["unseen_paths"]) is not expected_unseen:
                raise ValueError(f"{e['episode_id']} unseen_paths contradicts the train path set")
    rejected = {"world": _cross(world), "trajectory": _cross(traj), "public_file": _cross(pubfile),
                "path": _cross(paths)}
    bad = {f"{k}:{pair}": n for k, d in rejected.items() for pair, n in d.items() if n}
    if bad:
        raise ValueError(f"cross-partition identity duplicates: {bad}")
    return {"rejected_if_nonzero": rejected,
            "reported_only": {"frame_rgb": _cross(frames), "frame_content": _cross(content)}}


def write_r2(root: Path, *, specs=gt.SAMPLE_SPECS, steps: int = 16) -> dict:
    run_id = uuid5(UUID(int=0), f"{v1.REVISION}:s07-r2")
    sims = [gt.simulate(seed, fam, steps) for seed, fam in specs]
    splits = gt.assign_with_heldout(sims)  # original S07 rule: world + held-out flags only
    train_paths = {s["path_sha256"] for s in sims if splits[s["world"].world_id] is gt.DatasetPartition.TRAIN}
    eps = []
    for s in sims:
        part = splits[s["world"].world_id]
        unseen = part is not gt.DatasetPartition.TRAIN and s["path_sha256"] not in train_paths
        d = gt.write_episode(root, s, run_id=run_id, partition=part, unseen_paths=unseen)
        eps.append({"world_id": str(s["world"].world_id), "seed": s["world"].seed, "family": s["world"].family,
                    "scripted": s["world"].family in SCRIPTED, "partition": str(part), "flags": s["flags"],
                    "unseen_paths": unseen, "path_sha256": s["path_sha256"], "layout_sha256": s["layout_sha256"],
                    "trajectory_sha256": trajectory_sha256(s["public"]), "episode_id": str(s["episode_id"]),
                    "content_digests": sorted({v1.public_content_digest(o) for o in s["public"]}),
                    "files": {n: hashlib.sha256((d / n).read_bytes()).hexdigest()
                              for n in ("manifest.json", "public.jsonl", "private.json")}})
    checks = identity_checks(root, eps)
    manifest = {"kind": "gridlab_v1_split_manifest", "revision": v1.REVISION, "run_id": str(run_id),
                "frozen": True, "occlusion_heldout_k": v1.OCCLUSION_HELDOUT_K,
                "rule": "world/trajectory identity + held-out flags; frame overlap reported only",
                "episodes": [{k: e[k] for k in _KEYS} for e in eps], "checks": checks}
    (root / MANIFEST_NAME).write_bytes(canonical(manifest) + b"\n")
    return manifest


def _reject_manifest_metadata(m: dict) -> None:
    """The manifest's own claims must match the registered ones (finding A-F1)."""
    if m.get("kind") != REGISTERED_KIND:
        raise ValueError("manifest kind differs from the registered value")
    if m.get("frozen") is not True:
        raise ValueError("manifest is not marked frozen")
    if m.get("revision") != v1.REVISION:
        raise ValueError("manifest revision differs from the registered value")
    if m.get("rule") != REGISTERED_RULE:
        raise ValueError("manifest rule differs from the registered value")
    if not isinstance(m.get("run_id"), str) or not m["run_id"]:
        raise ValueError("manifest run_id is missing")
    if m.get("occlusion_heldout_k") != v1.OCCLUSION_HELDOUT_K:
        raise ValueError("occlusion threshold differs from the frozen value")


def _reject_duplicate_records(m: dict) -> None:
    """Duplicate episode/world records must be rejected, not silently collapsed (A-F1)."""
    episodes = m.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("manifest has no episode records")
    episode_ids = [e.get("episode_id") for e in episodes]
    if len(set(episode_ids)) != len(episode_ids):
        raise ValueError("manifest repeats an episode record")
    world_ids = [e.get("world_id") for e in episodes]
    if len(set(world_ids)) != len(world_ids):
        raise ValueError("manifest repeats a world record")
    for e in episodes:
        if set(e.get("files", {})) != set(EPISODE_FILE_NAMES):
            raise ValueError(f"{e.get('episode_id')} does not record the registered file set")


def verify_r2(root: Path, expected_sha256: str | None = None) -> dict:
    """Reject any deviation from the *registered* manifest identity.

    ``expected_sha256`` is an optional cross-check only: it must equal the registered
    constant, so re-signing a tampered manifest cannot bypass validation (A-F1).
    """
    expected = FROZEN_MANIFEST_SHA256 if expected_sha256 is None else expected_sha256
    if expected != FROZEN_MANIFEST_SHA256:
        raise ValueError("expected SHA differs from the registered frozen value")
    raw = (root / MANIFEST_NAME).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_MANIFEST_SHA256:
        raise ValueError("split manifest SHA differs from the registered frozen value")
    m = json.loads(raw)
    _reject_manifest_metadata(m)
    _reject_duplicate_records(m)
    if m.get("occlusion_heldout_k") != v1.OCCLUSION_HELDOUT_K:
        raise ValueError("occlusion threshold differs from the frozen value")
    if {p.name for p in root.iterdir() if p.is_dir()} != {e["episode_id"] for e in m["episodes"]} or \
            {p.name for p in root.iterdir() if p.is_file()} != {MANIFEST_NAME}:
        raise ValueError("episode directories differ from the frozen manifest")
    eps = []
    for e in m["episodes"]:
        d = root / e["episode_id"]
        for n, sha in e["files"].items():
            if hashlib.sha256((d / n).read_bytes()).hexdigest() != sha:
                raise ValueError(f"{e['episode_id']}/{n} differs from the frozen manifest")
        p = gt.load_private(d)
        h = p["public"]["header"]
        actual = {"world_id": h["world_id"], "seed": p["seed"], "family": p["family"],
                  "scripted": p["family"] in SCRIPTED, "partition": h["partition"], "flags": p["heldout_flags"],
                  "unseen_paths": p["unseen_paths"], "path_sha256": p["path_sha256"],
                  "layout_sha256": p["layout_sha256"]}
        if any(actual[k] != e[k] for k in actual):
            raise ValueError(f"{e['episode_id']} identity/partition/flags differ from the frozen manifest")
        if str(v1.world_id_for(e["seed"], e["family"])) != e["world_id"]:
            raise ValueError("world id does not derive from seed/family")
        if e["flags"] != v1.heldout_flags(p["events"]):
            raise ValueError("held-out flags do not follow from the recorded events")
        eps.append({**e, "content_digests": sorted({v1.public_content_digest(o)
                                                     for o in p["public"]["observations"]})})
    checks = identity_checks(root, eps)
    reported = m.get("checks")
    if not isinstance(reported, dict):
        raise ValueError("manifest carries no self-reported checks")
    for group in ("rejected_if_nonzero", "reported_only"):
        claimed = reported.get(group)
        if not isinstance(claimed, dict):
            raise ValueError(f"manifest self-report lacks {group}")
        for name, value in claimed.items():
            if checks.get(group, {}).get(name) != value:
                raise ValueError(
                    f"manifest self-reported {group}.{name} differs from the recomputed value")
    return checks
