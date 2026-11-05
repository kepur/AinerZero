"""S1 dataset identity, feature/target view and strict partition guards.

Layout (level-1 notice #297): the dataset bytes live under
``artifacts/v9/s1/datasets/<dataset_digest>/`` and the run root
``artifacts/v9/s1/phase1/`` only carries a ``dataset_ref.json`` pointing at it.
``reports/`` keeps manifests and their SHA256 only.

Inside a dataset directory:

- ``packets/{train,development}.jsonl`` -- one payload-only row per observation
  (episode_id + partition + seq + payload).  This is the only file the training
  path may read; it never contains truth fields.
- ``truth/{train,development}.jsonl`` -- evaluator-only truth (agent pose,
  entities, handle map, world occupancy).  Only ``load_truth_view`` reads it.
- ``dataset_manifest.json`` -- plan, counts, per-episode digests, generator
  source identity (SHA-256 map; the arena code is uncommitted), byte sizes and
  the dataset digest.

The ``final`` partition has no directory, no loader and no code path that could
create it: every public function asserts the partition is train/development.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from . import spec

# Reuse the v9 ObservationPacket/v1.1 payload gate (pure numpy/stdlib).
from ainerzero.v9.interfaces.validation import validate_observation_payload

PARTITIONS = ("train", "development")
ALLOWED_PARTITIONS = frozenset(PARTITIONS)
K = spec.OBSERVATION["detection_slots"]
FEATURE_DIM = spec.OBSERVATION["feature_dim"]
TARGET_DIM = spec.OBSERVATION["target_dim"]
CLASSES = tuple(spec.OBSERVATION["appearance_classes"])


class DatasetError(RuntimeError):
    """The dataset is missing, inconsistent, or a sealed partition was requested."""


class FinalPartitionSealed(DatasetError):
    """Phase 1 never materialises or reads the final partition."""


def canonical_bytes(payload: object) -> bytes:
    return spec.canonical_json(payload)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_partition(partition: str) -> str:
    if partition == "final":
        raise FinalPartitionSealed(
            "final partition is sealed and must be read once through the sealed channel "
            "only after all phase-1 training; S1 phase 1 does not read it"
        )
    if partition not in ALLOWED_PARTITIONS:
        raise DatasetError(f"unknown partition {partition!r}; only {PARTITIONS} exist in phase 1")
    return partition


# --- plan -----------------------------------------------------------------
def build_plan() -> dict:
    """World/round counts frozen in the preregistration, within the caps."""
    plan = {
        "schema": "ainerzero.v9.s1.data_plan.v1",
        "spec": spec.SPEC_NAME,
        "generator": spec.DATA_PLAN["generator"],
        "generator_commit": spec.DATA_PLAN["generator_commit"],
        "generator_root": str(spec.AWZ_ROOT),
        "generator_seed": spec.DATA_PLAN["generator_seed"],
        "restricted_exit": spec.DATA_PLAN["restricted_exit"],
        "families": list(spec.DATA_PLAN["families"]),
        "scene_id_format": spec.DATA_PLAN["scene_id_format"],
        "partitions": list(PARTITIONS),
        "final_partition": "not_generated_not_read",
        "train": dict(spec.DATA_PLAN["train"]),
        "development": dict(spec.DATA_PLAN["development"]),
        "sample_interval": spec.DATA_PLAN["sample_interval"],
        "range_m": spec.DATA_PLAN["range_m"],
        "fov_deg": spec.DATA_PLAN["fov_deg"],
    }
    validate_plan(plan)
    return plan


def validate_plan(plan: Mapping[str, Any]) -> None:
    reasons = plan_problems(plan)
    if reasons:
        raise DatasetError("; ".join(reasons))


def plan_problems(plan: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    caps = spec.DATA_CAPS
    try:
        train = plan["train"]
        development = plan["development"]
        train_worlds = int(train["worlds"])
        development_worlds = int(development["worlds"])
        rounds = int(train["rounds_per_world"])
        dev_rounds = int(development["rounds_per_world"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"data plan is malformed: {type(exc).__name__}: {exc}"]
    if not 1 <= train_worlds <= caps["train_worlds_max"]:
        reasons.append(
            f"train worlds {train_worlds} outside registered cap 1..{caps['train_worlds_max']}"
        )
    if not 1 <= development_worlds <= caps["development_worlds_max"]:
        reasons.append(
            "development worlds "
            f"{development_worlds} outside registered cap 1..{caps['development_worlds_max']}"
        )
    if not 1 <= rounds <= caps["rounds_per_world_max"]:
        reasons.append(f"rounds per world {rounds} outside registered cap 1..{caps['rounds_per_world_max']}")
    if dev_rounds != rounds:
        reasons.append("development rounds per world differ from train rounds per world")
    if "final" in (plan.get("partitions") or ()):
        reasons.append("data plan must not include the sealed final partition")
    if plan.get("final_partition") != "not_generated_not_read":
        reasons.append("data plan must record final_partition=not_generated_not_read")
    return reasons


# --- generation -----------------------------------------------------------
def generation_command(staging_dir: Path, plan: Mapping[str, Any]) -> list[str]:
    return [
        str(spec.AWZ_PYTHON),
        "-m",
        "ainerzero.v9.experiments.s1.awz_export",
        "--out-dir",
        str(staging_dir),
        "--train-worlds",
        str(plan["train"]["worlds"]),
        "--development-worlds",
        str(plan["development"]["worlds"]),
        "--rounds-per-world",
        str(plan["train"]["rounds_per_world"]),
        "--generator-seed",
        str(plan["generator_seed"]),
        "--generator-root",
        str(spec.AWZ_ROOT),
    ]


def generation_environment() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{spec.REPO_ROOT / 'src'}:{spec.AWZ_PYTHONPATH}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path}:{number} is not valid JSON") from exc
    return rows


def finalize_dataset(
    staging_dir: Path,
    final_dir: Path,
    *,
    plan: Mapping[str, Any],
    generation_seconds: float,
    generation_command: Iterable[str] | None = None,
) -> dict:
    """Validate the producer output, recompute identities and publish the dataset."""
    validate_plan(plan)
    staging_dir = Path(staging_dir)
    final_dir = Path(final_dir)
    meta_path = staging_dir / "export_meta.json"
    if not meta_path.is_file():
        raise DatasetError("producer did not write export_meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    counts = meta.get("counts", {})
    expected = {
        "train_worlds": int(plan["train"]["worlds"]),
        "development_worlds": int(plan["development"]["worlds"]),
        "rounds_per_world": int(plan["train"]["rounds_per_world"]),
    }
    for key, value in expected.items():
        if int(counts.get(key, -1)) != value:
            raise DatasetError(f"producer count {key}={counts.get(key)!r} != plan {value}")

    episodes_by_id: dict[str, dict] = {}
    packets_digest: dict[str, dict[str, bytes]] = {p: {} for p in PARTITIONS}
    payload_rows: dict[str, list[dict]] = {p: [] for p in PARTITIONS}
    truth_rows: dict[str, list[dict]] = {p: [] for p in PARTITIONS}
    packet_counts = {p: 0 for p in PARTITIONS}
    for partition in PARTITIONS:
        packets_path = staging_dir / "packets" / f"{partition}.jsonl"
        truth_path = staging_dir / "truth" / f"{partition}.jsonl"
        if not packets_path.is_file() or not truth_path.is_file():
            raise DatasetError(f"producer is missing the {partition} packets/truth files")
        by_episode: dict[str, list[dict]] = {}
        for row in _read_jsonl(packets_path):
            if row.get("partition") != partition:
                raise DatasetError("packet row carries a mismatched partition")
            payload = row.get("payload")
            validate_observation_payload(payload)  # typed consumer gate again
            by_episode.setdefault(row["episode_id"], []).append(row)
        for row in _read_jsonl(truth_path):
            if row.get("partition") != partition:
                raise DatasetError("truth row carries a mismatched partition")
            truth_rows[partition].append(row)
            truth_id = row.get("episode_id")
            if truth_id not in by_episode:
                raise DatasetError("truth row without a packet stream")
            episodes_by_id[truth_id] = {
                "episode_id": truth_id,
                "partition": partition,
                "family": row.get("family"),
                "scene_id": row.get("scene_id"),
                "round_index": row.get("round_index", 0),
                "steps": len(by_episode[truth_id]),
            }
        for episode_id, rows in by_episode.items():
            rows.sort(key=lambda row: row["seq"])
            if [row["seq"] for row in rows] != list(range(len(rows))):
                raise DatasetError(f"episode {episode_id} has a non-contiguous sequence")
            payload_rows[partition].extend(rows)
            packet_counts[partition] += len(rows)
            packets_digest[partition][episode_id] = canonical_bytes(
                [row["payload"] for row in rows]
            )
    if packet_counts["train"] != int(counts.get("train_packets", -1)):
        raise DatasetError("train packet count differs between producer metadata and files")
    if packet_counts["development"] != int(counts.get("development_packets", -1)):
        raise DatasetError("development packet count differs between producer metadata and files")

    # Recompute the per-episode digests and bind them to the producer list.
    producer_episodes = {row["episode_id"]: row for row in meta.get("episodes", [])}
    if set(producer_episodes) != set(episodes_by_id):
        raise DatasetError("producer episode list and files disagree")
    episodes: list[dict] = []
    for episode_id in sorted(producer_episodes, key=lambda value: producer_episodes[value]["scene_id"]):
        row = dict(producer_episodes[episode_id])
        partition = row["partition"]
        require_partition(partition)
        digest = hashlib.sha256(packets_digest[partition][episode_id]).hexdigest()
        if digest != row["packets_sha256"]:
            raise DatasetError(f"episode {episode_id} payload digest differs from producer list")
        truth_file_digest = hashlib.sha256(
            canonical_bytes(next(t for t in truth_rows[partition] if t["episode_id"] == episode_id))
        ).hexdigest()
        if truth_file_digest != row["truth_sha256"]:
            raise DatasetError(f"episode {episode_id} truth digest differs from producer list")
        episodes.append(row)

    checks = {
        "partitions": list(PARTITIONS),
        "final_absent": not any(
            "final" in json.dumps(row).lower()
            for row in ([episodes_by_id[key] for key in episodes_by_id])
        ),
        "payload_gate": "passed for every row",
        "train_development_scene_ids_disjoint": not (
            {row["scene_id"] for row in episodes if row["partition"] == "train"}
            & {row["scene_id"] for row in episodes if row["partition"] == "development"}
        ),
        "final_partition_expected": "not_generated_not_read",
    }
    dataset_digest = hashlib.sha256(
        canonical_bytes(
            {
                "plan": {**plan, "partitions": list(PARTITIONS)},
                "source_identity": meta["source_identity"],
                "counts": counts,
                "episodes": episodes,
            }
        )
    ).hexdigest()
    manifest = {
        "schema": "ainerzero.v9.s1.dataset_manifest.v1",
        "spec": spec.SPEC_NAME,
        "task": spec.TASK_ID,
        "created_unix": time.time(),
        "plan": plan,
        "counts": {
            **counts,
            "train_packets": packet_counts["train"],
            "development_packets": packet_counts["development"],
        },
        "episodes": episodes,
        "source_identity": meta["source_identity"],
        "checks": checks,
        "generation_seconds": generation_seconds,
        "generation_command": list(generation_command or generation_command(Path("<staging>"), plan)),
        "files": {},
        "dataset_digest": dataset_digest,
        "digest_rule": "sha256(canonical_json({plan, source_identity, counts, episodes}))",
    }
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists():
        raise DatasetError(f"refusing to overwrite an existing dataset directory {final_dir}")
    shutil.copytree(staging_dir, final_dir)
    file_rows = {}
    for path in sorted(final_dir.rglob("*")):
        if path.is_file() and path.name != "dataset_manifest.json":
            file_rows[path.relative_to(final_dir).as_posix()] = {
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
    manifest["files"] = file_rows
    manifest["total_bytes"] = sum(row["size_bytes"] for row in file_rows.values())
    (final_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    verify_dataset(final_dir, expected_digest=dataset_digest)
    return manifest


def generate_dataset(
    output_root: Path,
    *,
    timeout_seconds: float | None = None,
    plan: Mapping[str, Any] | None = None,
) -> dict:
    """Run the AWZ producer (frozen arena) and publish a verified dataset.

    The bytes are published under ``artifacts/v9/s1/datasets/<digest>/``; the run
    root receives only ``dataset_ref.json`` (notice #297).
    """
    plan = dict(plan or build_plan())
    validate_plan(plan)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    ref_path = dataset_ref_path(output_root)
    if ref_path.exists():
        raise DatasetError(
            f"a dataset reference already exists at {ref_path}; regenerate into a clean "
            "output root"
        )
    staging = Path(tempfile.mkdtemp(prefix=".dataset-staging-", dir=output_root))
    published = Path(tempfile.mkdtemp(prefix=".dataset-final-", dir=output_root)) / "dataset"
    command = generation_command(staging, plan)
    env = generation_environment()
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(spec.AWZ_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds
            or max(120.0, float(spec.TIMING["data_generation_budget_seconds"])),
        )
    finally:
        elapsed = time.perf_counter() - started
    if result.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise DatasetError(
            "arena producer failed: "
            f"exit {result.returncode}; stderr tail: {result.stderr.strip()[-2000:]}"
        )
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    try:
        produced = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise DatasetError("arena producer did not print a JSON summary") from exc
    if not produced.get("ok"):
        shutil.rmtree(staging, ignore_errors=True)
        raise DatasetError("arena producer reported failure")
    manifest = finalize_dataset(
        staging,
        published,
        plan=plan,
        generation_seconds=elapsed,
        generation_command=command,
    )
    shutil.rmtree(staging, ignore_errors=True)
    dataset_dir = publish_dataset(published, manifest["dataset_digest"])
    write_dataset_ref(output_root, manifest, dataset_dir)
    return manifest


# --- dataset reference (notice #297) --------------------------------------
def dataset_ref_path(output_root: Path) -> Path:
    return Path(output_root) / "dataset_ref.json"


def _repo_relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(spec.REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def publish_dataset(staged_dir: Path, dataset_digest: str) -> Path:
    """Move a verified dataset into ``datasets/<digest>/`` (idempotent)."""
    staged_dir = Path(staged_dir)
    target = spec.DATASETS_DIR / dataset_digest
    if target.exists():
        verify_dataset(target, expected_digest=dataset_digest)
        shutil.rmtree(staged_dir.parent if staged_dir.name == "dataset" else staged_dir,
                      ignore_errors=True)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged_dir), str(target))
    parent = staged_dir.parent
    if parent.exists() and parent != target:
        shutil.rmtree(parent, ignore_errors=True)
    verify_dataset(target, expected_digest=dataset_digest)
    return target


def write_dataset_ref(output_root: Path, manifest: Mapping[str, Any], dataset_dir: Path) -> Path:
    dataset_dir = Path(dataset_dir)
    ref = {
        "schema": "ainerzero.v9.s1.dataset_ref.v1",
        "spec": spec.SPEC_NAME,
        "dataset_digest": manifest["dataset_digest"],
        "dataset_dir": _repo_relative(dataset_dir),
        "manifest_sha256": sha256_file(dataset_dir / "dataset_manifest.json"),
        "rule": "level-1 notice #297: dataset bytes live under "
        "artifacts/v9/s1/datasets/<dataset_digest>/; reports/ keeps manifests and SHA256 only",
    }
    path = dataset_ref_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ref, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return path


def resolve_dataset_dir(output_root: Path) -> Path:
    """Resolve and validate the dataset a run root points at (fail closed)."""
    root = Path(output_root)
    ref_path = dataset_ref_path(root)
    if not ref_path.is_file():
        raise DatasetError(f"missing dataset reference {ref_path}; run --mode data first")
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    digest = ref.get("dataset_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise DatasetError("dataset reference carries no 64-hex dataset_digest")
    raw = ref.get("dataset_dir")
    if not isinstance(raw, str) or not raw:
        raise DatasetError("dataset reference carries no dataset_dir")
    dataset_dir = Path(raw)
    if not dataset_dir.is_absolute():
        dataset_dir = spec.REPO_ROOT / dataset_dir
    if dataset_dir.name != digest:
        raise DatasetError(
            f"dataset directory {dataset_dir} is not named after the referenced digest {digest}"
        )
    manifest_path = dataset_dir / "dataset_manifest.json"
    if not manifest_path.is_file():
        raise DatasetError(f"dataset manifest is missing at {manifest_path}")
    expected_manifest_sha = ref.get("manifest_sha256")
    if expected_manifest_sha and sha256_file(manifest_path) != expected_manifest_sha:
        raise DatasetError("dataset manifest SHA256 differs from the dataset reference")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_digest") != digest:
        raise DatasetError("dataset manifest digest differs from the dataset reference")
    return dataset_dir


# --- identity / verification ---------------------------------------------
def load_manifest(dataset_dir: Path) -> dict:
    path = Path(dataset_dir) / "dataset_manifest.json"
    if not path.is_file():
        raise DatasetError(f"missing dataset manifest at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_dataset(dataset_dir: Path, *, expected_digest: str | None = None) -> dict:
    manifest = load_manifest(dataset_dir)
    reasons: list[str] = []
    if manifest.get("schema") != "ainerzero.v9.s1.dataset_manifest.v1":
        reasons.append("unexpected dataset manifest schema")
    if manifest.get("plan", {}).get("final_partition") != "not_generated_not_read":
        reasons.append("dataset plan does not seal the final partition")
    digest = hashlib.sha256(
        canonical_bytes(
            {
                "plan": {**manifest["plan"], "partitions": list(manifest["plan"].get("partitions", PARTITIONS))},
                "source_identity": manifest["source_identity"],
                "counts": manifest["counts"],
                "episodes": manifest["episodes"],
            }
        )
    ).hexdigest()
    if digest != manifest.get("dataset_digest"):
        reasons.append("dataset digest does not match the manifest body")
    if expected_digest is not None and digest != expected_digest:
        reasons.append("dataset digest differs from the expected frozen identity")
    for rel, row in (manifest.get("files") or {}).items():
        path = Path(dataset_dir) / rel
        if not path.is_file():
            reasons.append(f"dataset file missing: {rel}")
            continue
        if sha256_file(path) != row["sha256"]:
            reasons.append(f"dataset file digest mismatch: {rel}")
    if reasons:
        raise DatasetError("; ".join(reasons))
    return {"dataset_digest": digest, "files": len(manifest.get("files") or {})}


def dataset_binding_state(output_root: Path, expected_digest: str | None) -> dict:
    """Bind the run root's dataset to the frozen ``data_identity`` digest (P-3).

    Fail closed: a missing reference, a different digest, or a dataset whose
    bytes no longer hash to the manifest all mean the run must not start.
    """
    try:
        dataset_dir = resolve_dataset_dir(output_root)
        manifest = load_manifest(dataset_dir)
        verified = verify_dataset(dataset_dir)
    except DatasetError as exc:
        return {
            "status": "failed",
            "rule": "the run root's dataset reference, manifest and file digests must equal "
            "data_identity.dataset_digest in the frozen preregistration",
            "expected_dataset_digest": expected_digest,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    actual = manifest.get("dataset_digest")
    ok = isinstance(expected_digest, str) and actual == expected_digest and verified["dataset_digest"] == expected_digest
    return {
        "status": "passed" if ok else "failed",
        "rule": "the run root's dataset reference, manifest and file digests must equal "
        "data_identity.dataset_digest in the frozen preregistration",
        "expected_dataset_digest": expected_digest,
        "actual_dataset_digest": actual,
        "dataset_dir": str(dataset_dir),
        "files": verified["files"],
        "reason": None if ok else "dataset digest differs from data_identity.dataset_digest",
    }


# --- views ----------------------------------------------------------------
@dataclass(frozen=True)
class TrainingEpisode:
    episode_id: str
    partition: str
    payloads: tuple[dict, ...]


@dataclass(frozen=True)
class TruthEpisode:
    episode_id: str
    partition: str
    family: str
    scene_id: str
    world: dict
    steps: tuple[dict, ...]


def load_training_episodes(dataset_dir: Path, partition: str) -> list[TrainingEpisode]:
    """Payload-only view used by the training path; never touches truth files."""
    partition = require_partition(partition)
    path = Path(dataset_dir) / "packets" / f"{partition}.jsonl"
    if not path.is_file():
        raise DatasetError(f"missing packets file {path}")
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for row in _read_jsonl(path):
        if row.get("partition") != partition:
            raise DatasetError("training view saw a row from another partition")
        grouped.setdefault(row["episode_id"], []).append((int(row["seq"]), row["payload"]))
    episodes = []
    for episode_id in sorted(grouped):
        rows = sorted(grouped[episode_id])
        payloads = tuple(payload for _, payload in rows)
        for expected_seq, (seq, _) in enumerate(rows):
            if seq != expected_seq:
                raise DatasetError(f"episode {episode_id} sequence is not contiguous")
            validate_observation_payload(payloads[expected_seq])
        episodes.append(TrainingEpisode(episode_id, partition, payloads))
    if not episodes:
        raise DatasetError(f"no episodes in partition {partition}")
    return episodes


def load_truth_view(dataset_dir: Path, partition: str) -> list[TruthEpisode]:
    """Evaluator-only view; the training path must not call this function."""
    partition = require_partition(partition)
    path = Path(dataset_dir) / "truth" / f"{partition}.jsonl"
    if not path.is_file():
        raise DatasetError(f"missing truth file {path}")
    episodes = []
    for row in _read_jsonl(path):
        if row.get("partition") != partition:
            raise DatasetError("truth view saw a row from another partition")
        world = row.get("world") or {}
        if world.get("sim_hz") != 120:
            raise DatasetError("truth world is not on the registered 120 Hz clock")
        episodes.append(
            TruthEpisode(
                episode_id=row["episode_id"],
                partition=partition,
                family=row.get("family", ""),
                scene_id=row.get("scene_id", ""),
                world=world,
                steps=tuple(row.get("steps") or ()),
            )
        )
    return episodes


# --- featurisation --------------------------------------------------------
def _class_index(name: str) -> int:
    try:
        return CLASSES.index(name)
    except ValueError:
        return CLASSES.index("other")


def payload_detections(payload: dict) -> np.ndarray:
    """[K,3] agent-frame detections (x, up, z) plus a presence mask [K]."""
    rows = []
    for channel in payload["observation"]["channels"]:
        if channel.get("kind") != "relative_objects":
            continue
        detections = list(channel.get("detections") or [])
        detections.sort(
            key=lambda row: (
                float(row["rel_position_m"][0]),
                float(row["rel_position_m"][2]),
                str(row.get("appearance_class", "")),
            )
        )
        rows = detections[:K]
        break
    out = np.zeros((K, 3), dtype=np.float32)
    present = np.zeros((K,), dtype=np.float32)
    for index, detection in enumerate(rows):
        position = detection["rel_position_m"]
        out[index] = (float(position[0]), float(position[1]), float(position[2]))
        present[index] = 1.0
    return out, present


def payload_features(payload: dict) -> np.ndarray:
    detections = np.zeros((K, 11), dtype=np.float32)
    rows = []
    for channel in payload["observation"]["channels"]:
        if channel.get("kind") == "relative_objects":
            rows = list(channel.get("detections") or [])
        if channel.get("kind") == "ego_motion":
            ego = channel.get("delta") or {}
    rows.sort(
        key=lambda row: (
            float(row["rel_position_m"][0]),
            float(row["rel_position_m"][2]),
            str(row.get("appearance_class", "")),
        )
    )
    for index, detection in enumerate(rows[:K]):
        position = detection["rel_position_m"]
        one_hot = np.zeros((len(CLASSES),), dtype=np.float32)
        one_hot[_class_index(str(detection.get("appearance_class", "other")))] = 1.0
        detections[index, 0:3] = (float(position[0]), float(position[1]), float(position[2]))
        detections[index, 3] = 1.0
        detections[index, 4] = float(detection.get("confidence", 0.0))
        detections[index, 5:] = one_hot
    ego_vector = np.zeros((6,), dtype=np.float32)
    ego_vector[0] = float(ego.get("dx_m", 0.0))
    ego_vector[1] = float(ego.get("dy_m", 0.0))
    ego_vector[2] = float(ego.get("dz_m", 0.0))
    ego_vector[3] = float(ego.get("dyaw_deg", 0.0)) / 180.0
    ego_vector[4] = float(payload["time"]["dt_ticks"]) / 120.0
    ego_vector[5] = 1.0 if payload.get("episode_start") else 0.0
    features = np.concatenate([detections.reshape(-1), ego_vector])
    if features.shape != (FEATURE_DIM,):
        raise DatasetError(f"feature vector has shape {features.shape}, expected ({FEATURE_DIM},)")
    return features.astype(np.float32)


def payload_target(payload: dict) -> np.ndarray:
    target = np.zeros((K, 10), dtype=np.float32)
    rows = []
    for channel in payload["observation"]["channels"]:
        if channel.get("kind") == "relative_objects":
            rows = list(channel.get("detections") or [])
            break
    rows.sort(
        key=lambda row: (
            float(row["rel_position_m"][0]),
            float(row["rel_position_m"][2]),
            str(row.get("appearance_class", "")),
        )
    )
    for index, detection in enumerate(rows[:K]):
        position = detection["rel_position_m"]
        target[index, 0:3] = (float(position[0]), float(position[1]), float(position[2]))
        target[index, 3] = 1.0
        one_hot = np.zeros((len(CLASSES),), dtype=np.float32)
        one_hot[_class_index(str(detection.get("appearance_class", "other")))] = 1.0
        target[index, 4:] = one_hot
    vector = target.reshape(-1)
    if vector.shape != (TARGET_DIM,):
        raise DatasetError(f"target has shape {vector.shape}, expected ({TARGET_DIM},)")
    return vector.astype(np.float32)


def action_of(payload: dict) -> np.ndarray:
    ego = {}
    for channel in payload["observation"]["channels"]:
        if channel.get("kind") == "ego_motion":
            ego = channel.get("delta") or {}
    return np.asarray(
        [
            float(ego.get("dx_m", 0.0)),
            float(ego.get("dy_m", 0.0)),
            float(ego.get("dz_m", 0.0)),
            float(ego.get("dyaw_deg", 0.0)) / 180.0,
        ],
        dtype=np.float32,
    )


def build_windows(
    episodes: Iterable[TrainingEpisode],
    *,
    sequence_steps: int = spec.TRAIN_COMMON["sequence_steps"],
) -> dict:
    """Deterministic one-step prediction windows.

    ``obs`` [W, T+1, D], ``actions`` [W, T, 4] (logged ego motion into the next
    frame), ``targets`` [W, T, 60], plus per-step detection geometry for the
    memory arms (``det_xy`` [W, T+1, K, 2], ``det_present`` [W, T+1, K]).
    """
    steps = int(sequence_steps)
    if steps < 1:
        raise ValueError("sequence_steps must be positive")
    obs_rows, action_rows, target_rows, xy_rows, present_rows, episode_rows = [], [], [], [], [], []
    for episode in episodes:
        payloads = episode.payloads
        if len(payloads) < steps + 1:
            continue
        for start in range(0, len(payloads) - steps):
            window = payloads[start : start + steps + 1]
            obs_rows.append(np.stack([payload_features(row) for row in window]))
            action_rows.append(np.stack([action_of(row) for row in window[1:]]))
            target_rows.append(np.stack([payload_target(row) for row in window[1:]]))
            geometry = [payload_detections(row) for row in window]
            xy_rows.append(np.stack([row[0][:, [0, 2]] for row in geometry]))
            present_rows.append(np.stack([row[1] for row in geometry]))
            episode_rows.append(
                {
                    "episode_id": episode.episode_id,
                    "start": start,
                    "partition": episode.partition,
                }
            )
    if not obs_rows:
        raise DatasetError("no episode is long enough to build a training window")
    return {
        "obs": np.stack(obs_rows).astype(np.float32),
        "actions": np.stack(action_rows).astype(np.float32),
        "targets": np.stack(target_rows).astype(np.float32),
        "det_xy": np.stack(xy_rows).astype(np.float32),
        "det_present": np.stack(present_rows).astype(np.float32),
        "windows": episode_rows,
    }


def build_episode_sequence(episode: TrainingEpisode) -> dict:
    """One episode as an unbatched sequence (for episodic memory probes).

    Shapes: ``obs`` [N, D], ``actions`` [N-1, 4], ``targets`` [N-1, 60],
    ``det_xy`` [N, K, 2], ``det_present`` [N, K].  Frame ``t`` carries packet
    ``seq == t`` and the prediction at step ``t`` targets packet ``t+1``; the
    evaluator aligns it with truth step ``t+1``.
    """
    payloads = episode.payloads
    if len(payloads) < 2:
        raise DatasetError(f"episode {episode.episode_id} is too short for a transition")
    obs = np.stack([payload_features(row) for row in payloads])
    actions = np.stack([action_of(row) for row in payloads[1:]])
    targets = np.stack([payload_target(row) for row in payloads[1:]])
    geometry = [payload_detections(row) for row in payloads]
    det_xy = np.stack([row[0][:, [0, 2]] for row in geometry])
    det_present = np.stack([row[1] for row in geometry])
    return {
        "episode_id": episode.episode_id,
        "obs": obs.astype(np.float32),
        "actions": actions.astype(np.float32),
        "targets": targets.astype(np.float32),
        "det_xy": det_xy.astype(np.float32),
        "det_present": det_present.astype(np.float32),
    }


def sequence_batch(sequence: Mapping[str, Any], start: int, stop: int) -> dict:
    """A batch-of-one slice of an episode sequence covering frames [start, stop)."""
    start, stop = int(start), int(stop)
    if not (0 <= start < stop <= len(sequence["obs"])):
        raise DatasetError(f"sequence slice [{start}, {stop}) is outside the episode")
    steps = stop - start - 1
    if steps < 1:
        raise DatasetError("a probe slice needs at least two frames")
    return {
        "obs": np.asarray(sequence["obs"][start:stop])[None, ...],
        "actions": np.asarray(sequence["actions"][start : stop - 1])[None, ...],
        "targets": np.asarray(sequence["targets"][start : stop - 1])[None, ...],
        "det_xy": np.asarray(sequence["det_xy"][start:stop])[None, ...],
        "det_present": np.asarray(sequence["det_present"][start:stop])[None, ...],
    }


def sample_batch(windows: dict, indices: np.ndarray) -> dict:
    idx = np.asarray(indices, dtype=np.int64)
    return {
        "obs": windows["obs"][idx],
        "actions": windows["actions"][idx],
        "targets": windows["targets"][idx],
        "det_xy": windows["det_xy"][idx],
        "det_present": windows["det_present"][idx],
    }


def fixed_batch(windows: dict, batch_size: int, *, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    count = len(windows["obs"])
    indices = rng.choice(count, size=min(batch_size, count), replace=False)
    if len(indices) < batch_size:
        indices = np.resize(indices, batch_size)
    return sample_batch(windows, np.asarray(indices))


def iter_batches(
    windows: dict, batch_size: int, *, seed: int, shuffle: bool = True
) -> Iterable[dict]:
    rng = np.random.default_rng(seed)
    count = len(windows["obs"])
    while True:
        if shuffle:
            order = rng.permutation(count)
        else:
            order = np.arange(count)
        for start in range(0, count - batch_size + 1, batch_size):
            yield sample_batch(windows, order[start : start + batch_size])


def load_training_windows(dataset_dir: Path, *, sequence_steps: int = spec.TRAIN_COMMON["sequence_steps"]) -> dict:
    return build_windows(
        load_training_episodes(dataset_dir, "train"), sequence_steps=sequence_steps
    )


def load_development_windows(
    dataset_dir: Path, *, sequence_steps: int = spec.TRAIN_COMMON["sequence_steps"]
) -> dict:
    return build_windows(
        load_training_episodes(dataset_dir, "development"), sequence_steps=sequence_steps
    )


def dataset_identity(manifest: Mapping[str, Any]) -> dict:
    """The frozen data identity recorded inside the preregistration."""
    return {
        "schema": manifest["schema"],
        "dataset_digest": manifest["dataset_digest"],
        "plan": manifest["plan"],
        "counts": manifest["counts"],
        "source_identity": {
            "root": manifest["source_identity"]["root"],
            "git_head": manifest["source_identity"]["git_head"],
            "file_count": manifest["source_identity"]["file_count"],
            "source_map_digest": manifest["source_identity"]["source_map_digest"],
        },
        "episode_count": len(manifest["episodes"]),
        "generation_seconds": manifest["generation_seconds"],
        "total_bytes": manifest.get("total_bytes"),
        "files": {
            rel: row["sha256"] for rel, row in (manifest.get("files") or {}).items()
        },
    }


def truth_pose_sequence(episode: TruthEpisode) -> np.ndarray:
    """[N,4] evaluator truth pose (x, y, z, yaw_deg) per stored step."""
    rows = []
    for step in episode.steps:
        pose = step["agent_world_pose"]
        position = pose["position"]
        rows.append(
            [float(position[0]), float(position[1]), float(position[2]), float(pose["yaw_deg"])]
        )
    return np.asarray(rows, dtype=np.float64)


def truth_visited_cells(episode: TruthEpisode) -> list[tuple[int, int]]:
    """Visited integer grid cells implied by the true agent trajectory."""
    cells = []
    for step in episode.steps:
        position = step["agent_world_pose"]["position"]
        cell = (int(round(float(position[0]))), int(round(float(position[2]))))
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return cells


def truth_free_adjacency(episode: TruthEpisode) -> set[tuple[tuple[int, int], tuple[int, int]]]:
    """True free-space adjacency restricted to the visited cells of the episode."""
    width = int(episode.world["width"])
    height = int(episode.world["height"])
    blocked = {(int(x), int(z)) for x, z in episode.world["blocked"]}
    visited = set(truth_visited_cells(episode))
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for cell in visited:
        x, z = cell
        for nx, nz in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            if (nx, nz) in visited and 0 <= nx < width and 0 <= nz < height and (nx, nz) not in blocked:
                edges.add(tuple(sorted((cell, (nx, nz)))))
    return edges
