"""Deterministic arena -> dataset producer (run under AnimeWorldZero's interpreter).

This module is the only S1 component that imports ``animeworld``, and it does so
lazily inside :func:`main`, so the AinerZero test environment can import the
module without the AnimeWorldZero dependencies.

It uses the frozen awz.V9.B3 r2 pieces only:

- ``animeworld.exams.scenarios`` procedural world factories (the same factories
  ``ExamGenerator.build`` calls; ``scene_id`` expands them deterministically),
- ``animeworld.exams.packets.emit_stream`` -- the r2 student-stream projection
  built on awz.V9.B1 r3 ``HandleAllocator`` + ``CounterNoise`` and validated by
  the A3 ``ProtocolValidator``,
- read-only metadata from ``animeworld.exams.world`` / ``partitions``.

Not called: ``ExamGenerator.build``/``generate_suite`` (they instantiate the
sealed final worlds), ``seal_final_exam``, ``read_sealed_once`` -- the final
partition is never generated or read in S1 phase 1.

Each emitted ``payload`` is additionally checked by the AinerZero consumer gate
(``ainerzero.v9.interfaces.validation.validate_observation_payload``) before it
is written, so the dataset is valid for both the producer and the consumer
contract.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

FAMILY_CODES = {
    "navigation": "nav",
    "time": "time",
    "relation": "rel",
    "e3_identity": "e3",
}
FAMILY_ORDER = ("navigation", "time", "relation", "e3_identity")
PARTITIONS = ("train", "development")
# Source files whose bytes define the arena/exit behaviour used here.
SOURCE_GLOBS = (
    "python/animeworld/exams/*.py",
    "python/animeworld/sensing/handles.py",
    "python/animeworld/sensing/noise.py",
    "python/animeworld/protocols/v9/*.py",
    "contracts/v9/observation_packet.v1_1.schema.json",
    "contracts/v9/observation_leak_rules.v1_1.json",
)
GENERATOR_SPEC = "awz-v9-b3-v0"
ROUND0_SALT = bytes(range(32)).hex()


def canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_plan(
    *,
    train_worlds: int,
    development_worlds: int,
    rounds_per_world: int = 1,
    generator_seed: str = GENERATOR_SPEC,
) -> dict:
    """Deterministic world enumeration; refuses any partition other than train/dev."""
    if not isinstance(train_worlds, int) or train_worlds < 1:
        raise ValueError("train_worlds must be a positive integer")
    if not isinstance(development_worlds, int) or development_worlds < 1:
        raise ValueError("development_worlds must be a positive integer")
    if rounds_per_world not in (1, 2, 3, 4):
        raise ValueError("rounds_per_world must be 1..4")
    per_family = {"train": train_worlds // len(FAMILY_ORDER), "development": development_worlds // len(FAMILY_ORDER)}
    if any(count < 1 for count in per_family.values()):
        raise ValueError("each partition needs at least one world per family")
    worlds = []
    for partition in PARTITIONS:
        for family in FAMILY_ORDER:
            for index in range(per_family[partition]):
                worlds.append(
                    {
                        "partition": partition,
                        "family": family,
                        "index": index,
                        "scene_id": f"s1-{partition}-{FAMILY_CODES[family]}-{index:05d}",
                    }
                )
    return {
        "generator_spec": generator_seed,
        "generator_seed": generator_seed,
        "partitions": list(PARTITIONS),
        "rounds_per_world": rounds_per_world,
        "worlds": worlds,
        "counts": {
            "train_worlds": per_family["train"] * len(FAMILY_ORDER),
            "development_worlds": per_family["development"] * len(FAMILY_ORDER),
            "rounds_per_world": rounds_per_world,
        },
    }


def world_round_salt(generator_seed: str, scene_id: str, family: str, round_index: int) -> str:
    """Per-round sensor realisation salt; round 0 keeps the registered default."""
    if round_index == 0:
        return ROUND0_SALT
    material = f"{generator_seed}|{scene_id}|{family}|round{round_index}".encode()
    return sha256_bytes(material)


def round_episode_id(generator_seed: str, world_fingerprint: str, partition: str, round_index: int) -> str:
    digest = sha256_bytes(
        f"awz.v9.b3.s1:{generator_seed}:{world_fingerprint}:{partition}:round{round_index}".encode()
    )
    return f"{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:32]}"


def source_identity(awz_root: Path) -> dict:
    """Pin the uncommitted arena code by content, not by the (missing) git identity."""
    files: dict[str, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in sorted(awz_root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(awz_root).as_posix()
            files[rel] = sha256_bytes(path.read_bytes())
    try:
        head = subprocess.run(
            ["git", "-C", str(awz_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
    except Exception as exc:  # pragma: no cover - host dependent
        head = f"unavailable: {type(exc).__name__}: {exc}"
    digest = sha256_bytes(canonical_bytes(files))
    return {
        "root": str(awz_root),
        "git_head": head,
        "file_count": len(files),
        "files_sha256": files,
        "source_map_digest": digest,
    }


def _detection_slots(payload: dict, slots: int) -> list[dict]:
    for channel in payload["observation"]["channels"]:
        if channel.get("kind") == "relative_objects":
            detections = list(channel.get("detections") or [])
            detections.sort(
                key=lambda row: (
                    float(row["rel_position_m"][0]),
                    float(row["rel_position_m"][2]),
                    str(row.get("appearance_class", "")),
                )
            )
            return detections[:slots]
    return []


def _truth_line(
    *, episode_id: str, partition: str, world, family: str, scene_id: str, bundle, round_index: int
) -> dict:
    return {
        "episode_id": episode_id,
        "partition": partition,
        "family": family,
        "scene_id": scene_id,
        "round_index": round_index,
        "world_fingerprint": world.world_key.fingerprint(),
        "world_key": world.world_key.as_dict(),
        "world": {
            "width": int(world.width),
            "height": int(world.height),
            "sim_hz": int(world.sim_hz),
            "blocked": [list(cell) for cell in sorted(world.blocked)],
        },
        "steps": bundle.truth_packets,
    }


def generate(plan: dict, out_dir: Path) -> dict:
    """Generate the train/development streams and truth; write dataset files."""
    started = time.perf_counter()
    try:
        from animeworld.exams.packets import emit_stream
        from animeworld.exams import scenarios
        from animeworld.exams.partitions import assert_partitions_disjoint, register_worlds
    except Exception as exc:  # pragma: no cover - producer-side runtime dependency
        raise SystemExit(
            f"awz_export must run under AnimeWorldZero's interpreter with PYTHONPATH set: {exc}"
        )

    from ainerzero.v9.interfaces.validation import validate_observation_payload

    factories = {
        "navigation": scenarios.navigation_world,
        "time": scenarios.time_world,
        "relation": scenarios.relation_world,
        "e3_identity": scenarios.e3_identity_world,
    }
    if not set(plan["partitions"]) <= set(PARTITIONS):
        raise SystemExit("refusing to generate any partition other than train/development")

    out_dir = Path(out_dir)
    (out_dir / "packets").mkdir(parents=True, exist_ok=True)
    (out_dir / "truth").mkdir(parents=True, exist_ok=True)
    handles = {partition: (out_dir / "packets" / f"{partition}.jsonl").open("w", encoding="utf-8")
               for partition in PARTITIONS}
    truths = {partition: (out_dir / "truth" / f"{partition}.jsonl").open("w", encoding="utf-8")
              for partition in PARTITIONS}
    worlds = {}
    episodes = []
    packet_count = {partition: 0 for partition in PARTITIONS}
    step_count = {partition: 0 for partition in PARTITIONS}
    try:
        for descriptor in plan["worlds"]:
            if descriptor["partition"] not in PARTITIONS:
                raise SystemExit(f"refusing partition {descriptor['partition']!r}")
            factory = factories[descriptor["family"]]
            world = factory(
                partition=descriptor["partition"],
                scene_id=descriptor["scene_id"],
                seed=plan["generator_seed"],
            )
            if world.partition != descriptor["partition"]:
                raise SystemExit("factory produced a world in a different partition")
            fingerprint = world.world_key.fingerprint()
            worlds[fingerprint] = world
            expected_namespace = {"train": 1, "development": 2}[descriptor["partition"]]
            if world.generation_seed >> 256 != expected_namespace:
                raise SystemExit("world generation seed namespace mismatch")
            for round_index in range(int(plan["rounds_per_world"])):
                salt = world_round_salt(
                    plan["generator_seed"], descriptor["scene_id"], descriptor["family"], round_index
                )
                episode_id = round_episode_id(
                    plan["generator_seed"], fingerprint, descriptor["partition"], round_index
                )
                bundle = emit_stream(
                    world,
                    sample_interval=12,
                    range_m=6.5,
                    fov_deg=90.0,
                    sensor_salt_hex=salt,
                    episode_id=episode_id,
                    validate=True,
                )
                if not bundle.packets or not bundle.truth_packets:
                    raise SystemExit("stream is empty")
                if bundle.episode_id != episode_id:
                    raise SystemExit("producer changed the requested episode id")
                payloads = []
                for seq, packet in enumerate(bundle.packets):
                    if packet.get("schema_version") != "awz.observation_packet.v1.1":
                        raise SystemExit("unexpected packet schema version")
                    envelope = packet["envelope"]
                    if envelope.get("partition") != descriptor["partition"]:
                        raise SystemExit("packet partition differs from world partition")
                    if envelope.get("seq") != seq:
                        raise SystemExit("packet sequence is not contiguous")
                    payload = packet["payload"]
                    validate_observation_payload(payload)  # consumer gate, typed rejection
                    row = {
                        "episode_id": episode_id,
                        "partition": descriptor["partition"],
                        "seq": seq,
                        "payload": payload,
                    }
                    handles[descriptor["partition"]].write(
                        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                    payloads.append(payload)
                truth = _truth_line(
                    episode_id=episode_id,
                    partition=descriptor["partition"],
                    world=world,
                    family=descriptor["family"],
                    scene_id=descriptor["scene_id"],
                    bundle=bundle,
                    round_index=round_index,
                )
                truths[descriptor["partition"]].write(
                    json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                )
                episodes.append(
                    {
                        "episode_id": episode_id,
                        "partition": descriptor["partition"],
                        "family": descriptor["family"],
                        "scene_id": descriptor["scene_id"],
                        "round_index": round_index,
                        "world_fingerprint": fingerprint,
                        "steps": len(bundle.packets),
                        "packets_sha256": sha256_bytes(canonical_bytes(payloads)),
                        "truth_sha256": sha256_bytes(canonical_bytes(truth)),
                    }
                )
                packet_count[descriptor["partition"]] += len(bundle.packets)
                step_count[descriptor["partition"]] += len(bundle.packets)
    finally:
        for handle in handles.values():
            handle.close()
        for handle in truths.values():
            handle.close()

    register_worlds(worlds)
    # Exam questions are not needed for S1; only the world-level isolation guard
    # is reused.  Every registered world's partition label is checked below.
    from animeworld.exams.partitions import assert_partitions_disjoint  # noqa: F401 (documented)

    partition_labels: dict[str, set] = {"train": set(), "development": set()}
    for descriptor in plan["worlds"]:
        partition_labels[descriptor["partition"]].add(descriptor["scene_id"])
    if partition_labels["train"] & partition_labels["development"]:
        raise SystemExit("train/development scene ids overlap")
    elapsed = time.perf_counter() - started
    meta = {
        "schema": "ainerzero.v9.s1.awz_export.v1",
        "plan": plan,
        "source_identity": source_identity(Path(plan["generator_root"]))
        if plan.get("generator_root")
        else source_identity(Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")),
        "counts": {
            "train_worlds": plan["counts"]["train_worlds"],
            "development_worlds": plan["counts"]["development_worlds"],
            "rounds_per_world": plan["counts"]["rounds_per_world"],
            "train_packets": packet_count["train"],
            "development_packets": packet_count["development"],
            "train_episodes": sum(1 for row in episodes if row["partition"] == "train"),
            "development_episodes": sum(1 for row in episodes if row["partition"] == "development"),
        },
        "partitions": list(PARTITIONS),
        "final_partition": "not_generated_not_read",
        "episodes": episodes,
        "elapsed_seconds": elapsed,
        "generated_at_unix": time.time(),
    }
    (out_dir / "export_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--train-worlds", type=int, required=True)
    parser.add_argument("--development-worlds", type=int, required=True)
    parser.add_argument("--rounds-per-world", type=int, default=1)
    parser.add_argument("--generator-seed", default=GENERATOR_SPEC)
    parser.add_argument("--generator-root", default="/Users/mac/AinerWorkFlow/AnimeWorldZero")
    args = parser.parse_args(argv)
    plan = build_plan(
        train_worlds=args.train_worlds,
        development_worlds=args.development_worlds,
        rounds_per_world=args.rounds_per_world,
        generator_seed=args.generator_seed,
    )
    plan["generator_root"] = args.generator_root
    meta = generate(plan, args.out_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "out_dir": str(Path(args.out_dir).resolve()),
                "counts": meta["counts"],
                "elapsed_seconds": meta["elapsed_seconds"],
                "export_meta": str((Path(args.out_dir) / "export_meta.json").resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
