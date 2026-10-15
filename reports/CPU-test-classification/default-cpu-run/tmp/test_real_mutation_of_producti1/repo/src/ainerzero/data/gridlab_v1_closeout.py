"""S07-R1: GridLab-v1 closeout — overlap-free world-level split, frozen split
manifest with a strict checker, and file-identity overlap checks.

The original S07 sample (artifacts/gridlab2d/s07-sample) is left untouched;
closeout output goes to a new directory.

Deterministic exclusion rule: worlds that share *any* public content digest
(view + visible objects) or RGB frame SHA are joined into one component
(union-find), and a whole component goes to one partition. Components carrying
any held-out flag go to development/final only (alternating in hash order);
clean components go to train except the last two (hash order) which go to
development and final when at least four clean components exist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5

from ainerzero.core.experience import DatasetPartition
from ainerzero.data import gridlab_v1_trajectory as gt
from ainerzero.environments import gridlab_v1 as v1
from ainerzero.environments.gridlab2d import canonical, check_split_leakage

MANIFEST_NAME = "split_manifest.json"
# Registered identity (coordinator registration 2026-10-13). Validation compares against
# this constant, not only against the caller-supplied argument (review finding A-F1).
FROZEN_MANIFEST_SHA256 = "1f80c54a5ff3c4089ae902b6862f540ace1513e976a7280917b8e491e46d36d8"
REGISTERED_KIND = "gridlab_v1_split_manifest"
REGISTERED_RULE = "union-find on public content/frame identity; flagged -> dev/final"
EPISODE_FILE_NAMES = ("manifest.json", "public.jsonl", "private.json")
_KEYS = ("world_id", "seed", "family", "partition", "flags", "unseen_paths", "path_sha256",
         "layout_sha256", "episode_id", "files")


def _hash(world_id) -> str:
    return hashlib.sha256(f"split:{world_id}".encode()).hexdigest()


def _identities(sim: dict) -> set[str]:
    return ({"content:" + v1.public_content_digest(o) for o in sim["public"]}
            | {"rgb:" + o["rgb_sha256"] for o in sim["public"]})


def components(sims: list[dict]) -> list[list[dict]]:
    parent = list(range(len(sims)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, s in enumerate(sims):
        for key in _identities(s):
            j = owner.setdefault(key, i)
            parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, s in enumerate(sims):
        groups.setdefault(find(i), []).append(s)
    out = [sorted(g, key=lambda s: _hash(s["world"].world_id)) for g in groups.values()]
    return sorted(out, key=lambda g: _hash(g[0]["world"].world_id))


def assign_overlap_free(sims: list[dict]) -> dict[UUID, DatasetPartition]:
    comps = components(sims)
    flagged = [c for c in comps if any(any(s["flags"].values()) for s in c)]
    clean = [c for c in comps if c not in flagged]
    out = {}
    for i, c in enumerate(flagged):
        for s in c:
            out[s["world"].world_id] = (DatasetPartition.DEVELOPMENT, DatasetPartition.FINAL)[i % 2]
    for i, c in enumerate(clean):
        part = DatasetPartition.TRAIN
        if len(clean) >= 4 and i == len(clean) - 2:
            part = DatasetPartition.DEVELOPMENT
        if len(clean) >= 4 and i == len(clean) - 1:
            part = DatasetPartition.FINAL
        for s in c:
            out[s["world"].world_id] = part
    return out


def file_identity_overlap(root: Path, episodes: list[dict]) -> dict[str, int]:
    """Cross-partition overlap of whole public files, observation SHAs and RGB frame SHAs."""
    sets: dict[str, dict[str, set]] = {}
    for e in episodes:
        d = root / e["episode_id"]
        pub = gt.load_public(d)
        part = sets.setdefault(e["partition"], {"public_file": set(), "observation": set(), "frame": set()})
        part["public_file"].add(hashlib.sha256((d / "public.jsonl").read_bytes()).hexdigest())
        for o in pub["observations"]:
            part["observation"].add(o["observation_sha256"])
            part["frame"].add(o["rgb_sha256"])
    names = sorted(sets)
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for kind in ("public_file", "observation", "frame"):
                out[f"{kind}:{a}|{b}"] = len(sets[a][kind] & sets[b][kind])
    return out


def check_overlaps(root: Path, episodes: list[dict]) -> dict:
    """Raises unless content and file-identity overlap across partitions are all zero."""
    content = v1.check_heldout_leakage(episodes)["content_overlap"]
    files = file_identity_overlap(root, episodes)
    bad = {k: v for k, v in {**content, **files}.items() if v}
    if bad:
        raise ValueError(f"cross-partition overlap: {bad}")
    return {"content_overlap": content, "file_identity_overlap": files}


def write_closeout(root: Path, *, specs=gt.SAMPLE_SPECS, steps: int = 16) -> dict:
    run_id = uuid5(UUID(int=0), f"{v1.REVISION}:s07-r1-closeout")
    sims = [gt.simulate(seed, fam, steps) for seed, fam in specs]
    splits = assign_overlap_free(sims)
    train_paths = {s["path_sha256"] for s in sims if splits[s["world"].world_id] is DatasetPartition.TRAIN}
    eps = []
    for s in sims:
        part = splits[s["world"].world_id]
        unseen = part is not DatasetPartition.TRAIN and s["path_sha256"] not in train_paths
        d = gt.write_episode(root, s, run_id=run_id, partition=part, unseen_paths=unseen)
        eps.append({"world_id": str(s["world"].world_id), "seed": s["world"].seed, "family": s["world"].family,
                    "partition": str(part), "flags": s["flags"], "unseen_paths": unseen,
                    "path_sha256": s["path_sha256"], "layout_sha256": s["layout_sha256"],
                    "episode_id": str(s["episode_id"]),
                    "content_digests": sorted({v1.public_content_digest(o) for o in s["public"]}),
                    "files": {n: hashlib.sha256((d / n).read_bytes()).hexdigest()
                              for n in ("manifest.json", "public.jsonl", "private.json")}})
    check_split_leakage(eps)
    overlaps = check_overlaps(root, eps)
    manifest = {"kind": "gridlab_v1_split_manifest", "revision": v1.REVISION, "run_id": str(run_id),
                "frozen": True, "rule": "union-find on public content/frame identity; flagged -> dev/final",
                "episodes": [{k: e[k] for k in _KEYS} for e in eps], "overlaps": overlaps}
    (root / MANIFEST_NAME).write_bytes(canonical(manifest) + b"\n")
    return manifest


def recompute_path_sha256(public: dict) -> str:
    """Recompute the agent path from the actual public observations (A-F2 closure)."""
    return v1.path_sha256(public["observations"])


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


def _reject_duplicate_records(m: dict) -> None:
    """Duplicate episode/world records must be rejected, not silently collapsed (A-F1)."""
    episodes = m.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("manifest has no episode records")
    for key in ("episode_id", "world_id"):
        values = [e.get(key) for e in episodes]
        if len(set(values)) != len(values):
            raise ValueError(f"manifest repeats a {key} record")
    for e in episodes:
        if set(e.get("files", {})) != set(EPISODE_FILE_NAMES):
            raise ValueError(f"{e.get('episode_id')} does not record the registered file set")


def verify_split_manifest(root: Path, expected_sha256: str | None = None) -> dict:
    """Reject any deviation: manifest bytes, episode set, per-episode identity/partition/flags/file SHAs,
    split leakage and cross-partition overlaps.

    ``expected_sha256`` is an optional cross-check only; it must equal the registered constant.
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
    dirs = {p.name for p in root.iterdir() if p.is_dir()}
    if dirs != {e["episode_id"] for e in m["episodes"]} or \
            {p.name for p in root.iterdir() if p.is_file()} != {MANIFEST_NAME}:
        raise ValueError("episode directories differ from the frozen manifest")
    eps = []
    for e in m["episodes"]:
        d = root / e["episode_id"]
        for n, sha in e["files"].items():
            if hashlib.sha256((d / n).read_bytes()).hexdigest() != sha:
                raise ValueError(f"{e['episode_id']}/{n} differs from the frozen manifest")
        p = gt.load_private(d)
        pub = gt.load_public(d)
        if recompute_path_sha256(pub) != p["path_sha256"]:
            raise ValueError(f"{e['episode_id']} declared path differs from the public trajectory")
        h = p["public"]["header"]
        actual = {"world_id": h["world_id"], "seed": p["seed"], "family": p["family"],
                  "partition": h["partition"], "flags": p["heldout_flags"], "unseen_paths": p["unseen_paths"],
                  "path_sha256": p["path_sha256"], "layout_sha256": p["layout_sha256"]}
        if any(actual[k] != e[k] for k in actual):
            raise ValueError(f"{e['episode_id']} identity/partition/flags differ from the frozen manifest")
        if str(v1.world_id_for(e["seed"], e["family"])) != e["world_id"]:
            raise ValueError("world id does not derive from seed/family")
        eps.append({**e, "content_digests": sorted({v1.public_content_digest(o)
                                                     for o in p["public"]["observations"]})})
    paths: dict[str, set] = {}
    real: dict[str, str] = {}
    for e in eps:
        real[e["episode_id"]] = recompute_path_sha256(gt.load_public(root / e["episode_id"]))
        paths.setdefault(e["partition"], set()).add(real[e["episode_id"]])
    train_paths = {real[e["episode_id"]] for e in eps if e["partition"] == "train"}
    for e in eps:
        if e["partition"] != "train" and bool(e["unseen_paths"]) is not (
                real[e["episode_id"]] not in train_paths):
            raise ValueError(f"{e['episode_id']} unseen_paths contradicts the train path set")
    shared = {f"{a}|{b}": len(paths[a] & paths[b])
              for i, a in enumerate(sorted(paths)) for b in sorted(paths)[i + 1:]}
    bad = {pair: n for pair, n in shared.items() if n}
    if bad:
        raise ValueError(f"cross-partition identity duplicates: {{'path': {bad}}}")
    check_split_leakage(eps)
    return check_overlaps(root, eps)
