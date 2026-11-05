"""Sealed S1 final-partition producer (ainerzero.V9.P59; run under AnimeWorldZero's interpreter).

RESEARCH_LOG R20261028-S1-phase1-final-eval.  ``awz_export.generate`` refuses every partition
other than train/development and stays byte-for-byte unchanged; this module generates only the
``final`` partition (namespace 3) with the same generator seed, sensor settings, restricted exit
and consumer gate, reusing ``awz_export``'s deterministic helpers.  It prints counts and digests
only, never content, and checks that no final world or scene id appears in the train/development
dataset it is given as reference.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .awz_export import (
    FAMILY_CODES,
    FAMILY_ORDER,
    GENERATOR_SPEC,
    _truth_line,
    canonical_bytes,
    round_episode_id,
    sha256_bytes,
    source_identity,
    world_round_salt,
)

FINAL = "final"
FINAL_NAMESPACE = 3


def build_final_plan(*, final_worlds: int, rounds_per_world: int = 1, generator_seed: str = GENERATOR_SPEC) -> dict:
    if not isinstance(final_worlds, int) or final_worlds < len(FAMILY_ORDER) or final_worlds % len(FAMILY_ORDER):
        raise ValueError("final_worlds must be a positive multiple of the four families")
    if rounds_per_world != 1:
        raise ValueError("the registered final partition has one round per world")
    per_family = final_worlds // len(FAMILY_ORDER)
    worlds = [
        {"partition": FINAL, "family": family, "index": index,
         "scene_id": f"s1-{FINAL}-{FAMILY_CODES[family]}-{index:05d}"}
        for family in FAMILY_ORDER
        for index in range(per_family)
    ]
    return {
        "generator_spec": generator_seed,
        "generator_seed": generator_seed,
        "partitions": [FINAL],
        "rounds_per_world": rounds_per_world,
        "worlds": worlds,
        "counts": {"final_worlds": final_worlds, "rounds_per_world": rounds_per_world},
    }


def _reference_identities(reference_meta: Path) -> tuple[set[str], set[str]]:
    meta = json.loads(Path(reference_meta).read_text(encoding="utf-8"))
    episodes = meta.get("episodes") or []
    if not episodes:
        raise SystemExit("reference export_meta.json lists no train/development episodes")
    return ({row["world_fingerprint"] for row in episodes}, {row["scene_id"] for row in episodes})


def generate_final(plan: dict, out_dir: Path, *, reference_meta: Path) -> dict:
    started = time.perf_counter()
    try:
        from animeworld.exams import scenarios
        from animeworld.exams.packets import emit_stream
        from animeworld.exams.partitions import register_worlds
    except Exception as exc:  # pragma: no cover - producer-side runtime dependency
        raise SystemExit(f"awz_final_export must run under AnimeWorldZero's interpreter: {exc}")
    from ainerzero.v9.interfaces.validation import validate_observation_payload

    if plan["partitions"] != [FINAL]:
        raise SystemExit("awz_final_export only generates the final partition")
    reference_fingerprints, reference_scenes = _reference_identities(reference_meta)
    factories = {
        "navigation": scenarios.navigation_world,
        "time": scenarios.time_world,
        "relation": scenarios.relation_world,
        "e3_identity": scenarios.e3_identity_world,
    }
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to write into a non-empty staging directory {out_dir}")
    (out_dir / "packets").mkdir(parents=True, exist_ok=True)
    (out_dir / "truth").mkdir(parents=True, exist_ok=True)
    worlds, episodes = {}, []
    packets = 0
    with (out_dir / "packets" / "final.jsonl").open("w", encoding="utf-8") as handle, \
            (out_dir / "truth" / "final.jsonl").open("w", encoding="utf-8") as truth_handle:
        for descriptor in plan["worlds"]:
            if descriptor["partition"] != FINAL:
                raise SystemExit(f"refusing partition {descriptor['partition']!r}")
            if descriptor["scene_id"] in reference_scenes:
                raise SystemExit("a final scene id also appears in the train/development dataset")
            world = factories[descriptor["family"]](
                partition=FINAL, scene_id=descriptor["scene_id"], seed=plan["generator_seed"]
            )
            if world.partition != FINAL or world.generation_seed >> 256 != FINAL_NAMESPACE:
                raise SystemExit("factory produced a world outside the final namespace")
            fingerprint = world.world_key.fingerprint()
            if fingerprint in reference_fingerprints:
                raise SystemExit("a final world fingerprint also appears in the train/development dataset")
            worlds[fingerprint] = world
            salt = world_round_salt(plan["generator_seed"], descriptor["scene_id"], descriptor["family"], 0)
            episode_id = round_episode_id(plan["generator_seed"], fingerprint, FINAL, 0)
            bundle = emit_stream(world, sample_interval=12, range_m=6.5, fov_deg=90.0,
                                 sensor_salt_hex=salt, episode_id=episode_id, validate=True)
            if not bundle.packets or not bundle.truth_packets or bundle.episode_id != episode_id:
                raise SystemExit("stream is empty or changed its episode id")
            payloads = []
            for seq, packet in enumerate(bundle.packets):
                envelope = packet["envelope"]
                if packet.get("schema_version") != "awz.observation_packet.v1.1" or envelope.get("partition") != FINAL \
                        or envelope.get("seq") != seq:
                    raise SystemExit("unexpected packet schema, partition or sequence")
                payload = packet["payload"]
                validate_observation_payload(payload)
                handle.write(json.dumps({"episode_id": episode_id, "partition": FINAL, "seq": seq, "payload": payload},
                                        ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                payloads.append(payload)
            truth = _truth_line(episode_id=episode_id, partition=FINAL, world=world, family=descriptor["family"],
                                scene_id=descriptor["scene_id"], bundle=bundle, round_index=0)
            truth_handle.write(json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            episodes.append({"episode_id": episode_id, "partition": FINAL, "family": descriptor["family"],
                             "scene_id": descriptor["scene_id"], "round_index": 0, "world_fingerprint": fingerprint,
                             "steps": len(bundle.packets), "packets_sha256": sha256_bytes(canonical_bytes(payloads)),
                             "truth_sha256": sha256_bytes(canonical_bytes(truth))})
            packets += len(bundle.packets)
    register_worlds(worlds)
    meta = {
        "schema": "ainerzero.v9.s1.awz_final_export.v1",
        "plan": plan,
        "source_identity": source_identity(Path(plan.get("generator_root") or "/Users/mac/AinerWorkFlow/AnimeWorldZero")),
        "counts": {"final_worlds": len(worlds), "final_episodes": len(episodes), "final_packets": packets},
        "disjoint_from_reference": {"reference_meta": str(reference_meta), "fingerprint_overlap": 0, "scene_overlap": 0},
        "episodes": episodes,
        "elapsed_seconds": time.perf_counter() - started,
        "generated_at_unix": time.time(),
    }
    (out_dir / "export_meta.json").write_text(json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                                              encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--final-worlds", type=int, required=True)
    parser.add_argument("--reference-meta", type=Path, required=True)
    parser.add_argument("--generator-seed", default=GENERATOR_SPEC)
    parser.add_argument("--generator-root", default="/Users/mac/AinerWorkFlow/AnimeWorldZero")
    args = parser.parse_args(argv)
    plan = build_final_plan(final_worlds=args.final_worlds, generator_seed=args.generator_seed)
    plan["generator_root"] = args.generator_root
    meta = generate_final(plan, args.out_dir, reference_meta=args.reference_meta)
    # Counts and timing only: no content row is printed.
    print(json.dumps({"ok": True, "counts": meta["counts"], "elapsed_seconds": meta["elapsed_seconds"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
