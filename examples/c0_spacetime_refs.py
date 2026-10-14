"""S03: minimal C0 spacetime side-car references on an existing public episode.

Reads one existing C0 trajectory through the strict complete loader, or an
explicit two-file ``--public-only`` fixture profile (private is never opened),
builds researcher-made
engineering references for one cell across distinct observations, then
explicitly resolves them and checks the as-of view. No replay/reset/step, no
new data, no model. Links here are created by the researcher, not discovered
by the student, and do not mean the model understands space or time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID

from ainerzero.core import spacetime as spacetime_module
from ainerzero.core.contracts import CELL_COUNT
from ainerzero.core.experience import DatasetPartition, ObservationV2
from ainerzero.core.spacetime import (
    EvidenceKind,
    EvidenceLink,
    cell_ref_from_observation,
    load_evidence_link,
    observation_digest,
    record_digest,
    resolved_links_visible_at,
    to_canonical_json,
    validate_link_history,
    verify_cell_ref,
)
from ainerzero.data import trajectory as trajectory_module
from ainerzero.data.trajectory import (
    MAX_FILE_BYTES,
    EpisodeTrajectory,
    load_public_trajectory,
    load_trajectory,
)

ASSERTED_BY = "s03-example/grokbot-newbot"
SNAPSHOT_SCHEMA = 1
SNAPSHOT_PROTOCOL = "s03-c0-reference-snapshot-v1"
ARCHIVE_FILES = {"evidence_links.jsonl", "summary.json", "manifest.json"}
PRODUCER_FILES = {
    "examples/c0_spacetime_refs.py", "src/ainerzero/core/spacetime.py",
    "src/ainerzero/data/trajectory.py",
}


def _cell_index(cell: int) -> int:
    if type(cell) is not int or not 0 <= cell < CELL_COUNT:
        raise ValueError(f"cell must be an integer from 0 to {CELL_COUNT - 1}")
    return cell


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_observations(trajectory: EpisodeTrajectory) -> dict[UUID, ObservationV2]:
    """Initial + every next_observation, keyed by observation.id (public view)."""
    observations = [trajectory.initial, *(t.next_observation for t in trajectory.transitions)]
    mapping: dict[UUID, ObservationV2] = {}
    for observation in observations:
        if observation.id in mapping and mapping[observation.id] != observation:
            raise ValueError(f"conflicting observations share id {observation.id}")
        mapping[observation.id] = observation
    return mapping


def pick_steps(observations: list[ObservationV2], cell: int, count: int = 3) -> list[ObservationV2]:
    """Earliest ``count`` observations (distinct steps) where ``cell`` is visible."""
    cell = _cell_index(cell)
    picked: list[ObservationV2] = []
    for observation in sorted(observations, key=lambda o: o.step):
        if observation.payload.visible_mask[cell] and all(p.step != observation.step for p in picked):
            picked.append(observation)
        if len(picked) == count:
            return picked
    raise ValueError(f"cell {cell} is visible in fewer than {count} observations")


def build_links(trajectory: EpisodeTrajectory, cell: int) -> tuple[EvidenceLink, EvidenceLink]:
    cell = _cell_index(cell)
    if trajectory.initial.context.environment_instance_id is None:
        raise ValueError("unknown world: same_cell_later is not constructed (no world is invented)")
    first, second, third = pick_steps(list(public_observations(trajectory).values()), cell)
    subject = cell_ref_from_observation(first, cell)
    v0 = EvidenceLink(
        kind=EvidenceKind.SAME_CELL_LATER,
        subject=subject,
        supports=(cell_ref_from_observation(second, cell),),
        asserted_by=ASSERTED_BY,
        asserted_at_step=second.step,
    )
    v1 = EvidenceLink(
        kind=EvidenceKind.SAME_CELL_LATER,
        subject=subject,
        supports=(cell_ref_from_observation(second, cell), cell_ref_from_observation(third, cell)),
        asserted_by=ASSERTED_BY,
        asserted_at_step=third.step,
        revision=1,
        supersedes_sha256=record_digest(v0),
    )
    return v0, v1


def run(episode_dir: Path, cell: int = 0, *, public_only: bool = False) -> dict:
    cell = _cell_index(cell)
    episode_dir = Path(episode_dir)
    expected = {"public.jsonl", "manifest.json"}
    if not public_only:
        expected.add("private.json")
    _regular_directory(episode_dir, expected)
    public = episode_dir / "public.jsonl"
    manifest_path = episode_dir / "manifest.json"
    before = (file_sha256(public), file_sha256(manifest_path))
    trajectory = (load_public_trajectory if public_only else load_trajectory)(episode_dir)
    mapping = public_observations(trajectory)
    v0, v1 = build_links(trajectory, cell)
    for ref in (v1.subject, *v1.supports):
        verify_cell_ref(ref, mapping[ref.observation_id])
    validate_link_history((v0, v1))
    views = {
        step: [link.revision for link in resolved_links_visible_at((v0, v1), step, mapping)]
        for step in sorted({0, v0.subject.time.step, v0.asserted_at_step, v1.asserted_at_step,
                            trajectory.transitions[-1].next_observation.step})
    }
    after = (file_sha256(public), file_sha256(manifest_path))
    if before != after:
        raise RuntimeError("source files changed during read")
    manifest = json.loads(manifest_path.read_text())
    ctx = trajectory.initial.context
    result = {
        "episode_id": str(ctx.episode_id),
        "partition": str(ctx.partition),
        "world_id": str(ctx.environment_instance_id),
        "environment_revision": ctx.environment_revision,
        "transitions": len(trajectory.transitions),
        "public_jsonl_file_sha256": before[0],
        "manifest_recorded_public_sha256": manifest["files"]["public.jsonl"]["sha256"],
        "manifest_file_sha256": before[1],
        "cell": cell,
        "refs": [
            {"step": r.time.step, "observation_id": str(r.observation_id),
             "observation_canonical_sha256": r.observation_sha256,
             "recomputed": observation_digest(mapping[r.observation_id])}
            for r in (v1.subject, *v1.supports)
        ],
        "links": [{"revision": link.revision, "asserted_at_step": link.asserted_at_step,
                   "sha256": record_digest(link)} for link in (v0, v1)],
        "as_of_revisions": {str(k): v for k, v in views.items()},
        "sidecar_jsonl": [to_canonical_json(link).decode() for link in (v0, v1)],
        "private_json_opened": False,
        "load_profile": "public_only" if public_only else "complete",
        "usage": "contract_test_only",
        "not_for_training": True,
        "source_identity": {
            "episode_id": str(ctx.episode_id), "run_id": str(ctx.run_id),
            "partition": str(ctx.partition), "world_id": str(ctx.environment_instance_id),
            "environment_revision": ctx.environment_revision,
            "action_schema_revision": ctx.action_schema_revision,
            "transition_count": len(trajectory.transitions),
            "files": {
                "public.jsonl": {"sha256": before[0], "size_bytes": public.stat().st_size},
                "manifest.json": {"sha256": before[1], "size_bytes": manifest_path.stat().st_size},
            },
        },
        "producer_identity": {
            "name": ASSERTED_BY, "revision": "S03-R1",
            "original_author": "grokbot-newbot", "repair_author": "spacetime_identity_repair",
            "source_sha256": {
                "examples/c0_spacetime_refs.py": file_sha256(Path(__file__)),
                "src/ainerzero/core/spacetime.py": file_sha256(Path(spacetime_module.__file__)),
                "src/ainerzero/data/trajectory.py": file_sha256(Path(trajectory_module.__file__)),
            },
        },
    }
    result["snapshot_identity"] = snapshot_identity(result)
    result["snapshot_digest"] = _digest(result["snapshot_identity"])
    return result


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value).rstrip(b"\n")).hexdigest()


def _no_symlinks(path: Path) -> None:
    if ".." in path.parts:
        raise ValueError("path traversal is not allowed")
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink():
            raise ValueError(f"symlink paths are not allowed: {part}")


def _regular_directory(path: Path, expected_files: set[str]) -> None:
    _no_symlinks(path)
    if not path.is_dir() or {p.name for p in path.iterdir()} != expected_files:
        raise ValueError("directory contains missing or unexpected files")
    if any((path / name).is_symlink() or not (path / name).is_file() for name in expected_files):
        raise ValueError("directory entries must be regular files")


def _hash_identity(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA256 identity")
    return value


def _uuid_identity(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid canonical UUID identity")
    return value


def snapshot_identity(result: dict) -> dict:
    """Stable content/producer identity, independent of absolute machine paths."""
    if result["usage"] != "contract_test_only" or result["not_for_training"] is not True:
        raise ValueError("snapshot summary must remain contract_test_only and not_for_training")
    if result["private_json_opened"] is not False:
        raise ValueError("this snapshot protocol never reads private content")
    source = result["source_identity"]
    DatasetPartition(source["partition"])
    for key in ("episode_id", "world_id", "run_id"):
        _uuid_identity(source[key])
    if set(source["files"]) != {"public.jsonl", "manifest.json"}:
        raise ValueError("source identity must describe the two public files")
    for description in source["files"].values():
        _hash_identity(description["sha256"])
        if type(description["size_bytes"]) is not int or description["size_bytes"] <= 0:
            raise ValueError("invalid source file size")
    for key in ("episode_id", "partition", "world_id", "environment_revision"):
        if result[key] != source[key]:
            raise ValueError(f"summary source scope mismatch: {key}")
    if result["transitions"] != source["transition_count"]:
        raise ValueError("summary transition count does not match source")
    for key, filename in (("public_jsonl_file_sha256", "public.jsonl"),
                          ("manifest_file_sha256", "manifest.json"),
                          ("manifest_recorded_public_sha256", "public.jsonl")):
        if result[key] != source["files"][filename]["sha256"]:
            raise ValueError(f"summary source hash mismatch: {key}")
    producer = result["producer_identity"]
    if set(producer["source_sha256"]) != PRODUCER_FILES:
        raise ValueError("producer identity must bind the three source files")
    for digest in producer["source_sha256"].values():
        _hash_identity(digest)
    link_digests = [_hash_identity(link["sha256"]) for link in result["links"]]
    if len(link_digests) != 2:
        raise ValueError("this example requires exactly two link revisions")
    if result["load_profile"] not in ("complete", "public_only"):
        raise ValueError("invalid load profile")
    return {
        "schema_version": SNAPSHOT_SCHEMA, "protocol": SNAPSHOT_PROTOCOL,
        "producer": result["producer_identity"], "source": source,
        "cell": _cell_index(result["cell"]), "link_sha256": link_digests,
        "load_profile": result["load_profile"], "usage": "contract_test_only",
        "not_for_training": True,
    }


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def archive_snapshot(result: dict, archive_root: Path) -> Path:
    """Publish a new sidecar; manifest is written last, never overwrite a target."""
    identity = snapshot_identity(result)
    digest = _digest(identity)
    if result["snapshot_identity"] != identity or result["snapshot_digest"] != digest:
        raise ValueError("snapshot identity does not match summary")
    source = identity["source"]
    archive_root = Path(archive_root)
    _no_symlinks(archive_root)
    parent = archive_root / source["partition"] / source["episode_id"]
    _no_symlinks(parent)
    parent.mkdir(parents=True, exist_ok=True)
    _no_symlinks(parent)
    target = parent / digest
    target.mkdir(exist_ok=False)  # also rejects incomplete or symlinked existing targets
    summary = {k: v for k, v in result.items() if k != "sidecar_jsonl"}
    payloads = {
        "evidence_links.jsonl": ("\n".join(result["sidecar_jsonl"]) + "\n").encode(),
        "summary.json": _json_bytes(summary),
    }
    manifest = {
        "schema_version": SNAPSHOT_SCHEMA, "kind": "spacetime_snapshot",
        "protocol": SNAPSHOT_PROTOCOL, "snapshot_digest": digest, "identity": identity,
        "files": {name: {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in payloads.items()},
    }
    for name, data in payloads.items():
        _write_new(target / name, data)
    _write_new(target / "manifest.json", _json_bytes(manifest))
    load_snapshot(target)  # readers reject incomplete, corrupted or mismatched snapshots
    return target


def _archive_json(data: bytes) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    def finite(value):
        raise ValueError(f"non-finite JSON value: {value}")

    value = json.loads(data, object_pairs_hook=unique, parse_constant=finite)
    if not isinstance(value, dict):
        raise ValueError("archive JSON must be an object")
    return value


def _archive_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("archive entry must be a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("archive file size is invalid")
    return data


def _load_snapshot(path: Path) -> dict:
    """Read a completed verified sidecar, not an authenticated world fact."""
    path = Path(path)
    _regular_directory(path, ARCHIVE_FILES)
    manifest = _archive_json(_archive_bytes(path / "manifest.json"))
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != SNAPSHOT_SCHEMA or
            manifest["kind"] != "spacetime_snapshot" or manifest["protocol"] != SNAPSHOT_PROTOCOL):
        raise ValueError("unsupported snapshot manifest")
    digest = _hash_identity(manifest["snapshot_digest"])
    if path.name != digest or _digest(manifest["identity"]) != digest:
        raise ValueError("snapshot digest does not match identity or directory")
    if set(manifest["files"]) != {"evidence_links.jsonl", "summary.json"}:
        raise ValueError("snapshot manifest must describe exactly two files")
    payloads = {}
    for name, description in manifest["files"].items():
        data = _archive_bytes(path / name)
        if len(data) != description["size_bytes"] or hashlib.sha256(data).hexdigest() != description["sha256"]:
            raise ValueError(f"snapshot integrity check failed: {name}")
        payloads[name] = data
    summary = _archive_json(payloads["summary.json"])
    identity = snapshot_identity(summary)
    if (identity != manifest["identity"] or summary["snapshot_identity"] != identity or
            summary["snapshot_digest"] != digest):
        raise ValueError("summary does not match snapshot identity")
    source = identity["source"]
    if path.parent.name != source["episode_id"] or path.parent.parent.name != source["partition"]:
        raise ValueError("snapshot directory does not match source scope")
    links = tuple(load_evidence_link(line) for line in payloads["evidence_links.jsonl"].splitlines())
    validate_link_history(links)
    if [record_digest(link) for link in links] != identity["link_sha256"]:
        raise ValueError("snapshot links do not match identity")
    for link in links:
        time = link.subject.time
        if ((str(time.run_id), str(time.episode_id), str(time.world_id), str(time.partition), link.subject.cell)
                != (source["run_id"], source["episode_id"], source["world_id"], source["partition"], identity["cell"])):
            raise ValueError("snapshot link scope does not match source identity")
    return summary


def load_snapshot(path: Path) -> dict:
    """Malformed, incomplete and corrupt archives all fail closed as ValueError."""
    try:
        return _load_snapshot(path)
    except ValueError:
        raise
    except (OSError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"invalid snapshot: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--cell", type=int, default=0)
    parser.add_argument("--public-only", action="store_true", help="strict two-file public fixture")
    parser.add_argument("--archive-root", type=Path, help="publish a new completed sidecar snapshot")
    parser.add_argument("--out", type=Path, help="new JSON file (refuses to overwrite)")
    args = parser.parse_args()
    summary = run(args.episode_dir, args.cell, public_only=args.public_only)
    if args.archive_root:
        archive = archive_snapshot(summary, args.archive_root)
        summary = {**summary, "archive_path": str(archive)}
    result = json.dumps(summary, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "x", encoding="utf-8") as handle:
            handle.write(result + "\n")
    print(result)


if __name__ == "__main__":
    main()
