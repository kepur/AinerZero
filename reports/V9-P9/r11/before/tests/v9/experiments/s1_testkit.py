"""Pure-CPU helpers for the S1 phase-1 tests (synthetic producer staging)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ainerzero.v9.experiments.s1 import data, prereg

SIM_HZ = 120

FAKE_COUNTS = {"arm1": 393_232, "arm2": 207_519, "arm3": 159_455, "arm4": 274_031}
FAKE_IDENTITY = {
    "schema": "ainerzero.v9.s1.dataset_manifest.v1",
    "dataset_digest": "a" * 64,
    "plan": {
        "train": {"worlds": 2_000, "rounds_per_world": 1},
        "development": {"worlds": 200, "rounds_per_world": 1},
        "partitions": ["train", "development"],
        "final_partition": "not_generated_not_read",
        "generator_seed": "awz-v9-b3-v0",
    },
    "counts": {"train_packets": 9_500, "development_packets": 950},
    "source_identity": {"source_map_digest": "b" * 64},
    "episode_count": 2_200,
    "generation_seconds": 61.5,
}


def fake_smoke(step_seconds: float = 0.01) -> dict:
    return {
        "schema": "ainerzero.v9.s1.smoke.v1",
        "no_update": True,
        "gradients_computed": False,
        "updated_parameters": False,
        "parameters_unchanged": True,
        "batch_size": 16,
        "repeats": 5,
        "dataset": {"dataset_digest": FAKE_IDENTITY["dataset_digest"], "train_windows": 5_500},
        "trainable_arms": {
            arm_id: {
                "forward_loss_step_seconds": step_seconds,
                "parameter_count": FAKE_COUNTS[arm_id],
                "parameters_unchanged": True,
                "loss": 1.0,
                "parameter_sha256_before": "c" * 64,
                "parameter_sha256_after": "c" * 64,
                "peak_mlx_gib": 0.1,
            }
            for arm_id in ("arm2", "arm3", "arm4")
        },
        "d_candidate": {
            "forward_loss_step_seconds": step_seconds,
            "parameter_count": FAKE_COUNTS["arm1"],
            "parameters_unchanged": True,
            "loss": 1.0,
            "peak_mlx_gib": 0.1,
        },
        "peak_process_rss_gib": 1.2,
        "peak_mlx_gib": 0.1,
        "data_generation_seconds": 61.5,
        "measurement_note": "synthetic fixture",
    }


def frozen_document() -> dict:
    return prereg.build_frozen(
        prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS),
        smoke=fake_smoke(),
        data_identity=FAKE_IDENTITY,
        created_unix=1_000.0,
    )


def write_frozen(path: Path, *, document: dict | None = None) -> tuple[Path, str, dict]:
    """Write a frozen preregistration plus its companion SHA256 file."""
    document = document or frozen_document()
    path = Path(path)
    path.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    digest = prereg.document_sha256(document)
    prereg.write_sha256_file(path, digest)
    return path, digest, document


SECTION_HEADING = "## R20261021-P1-stageA-budget：S1 第一阶段训练预算登记（test fixture）"


def research_log_text(
    *,
    approval_sha: str | None = None,
    extra_lines: tuple[str, ...] = (),
    heading: str = SECTION_HEADING,
    tail: str = "",
) -> str:
    """A research-log fixture with the registered approval section.

    ``approval_sha`` puts one bare approval line inside the section; callers that
    need code-block / blockquote / duplicate cases build their own text and use
    :func:`write_raw_log`.
    """
    lines = [heading, "", "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。"]
    if approval_sha is not None:
        lines.append(prereg.APPROVAL_TEMPLATE.format(document_sha256=approval_sha))
    lines.extend(extra_lines)
    if tail:
        lines.append(tail)
    return "\n".join(lines) + "\n"


def write_raw_log(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_research_log(path: Path, *, approval_sha: str | None = None, extra_lines: tuple[str, ...] = ()) -> Path:
    """Write a temporary research log; only the coordinator writes approval lines."""
    return write_raw_log(path, research_log_text(approval_sha=approval_sha, extra_lines=extra_lines))


def canonical_bytes(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def install_test_host(monkeypatch, tmp_path, *, create_ledger: bool = False) -> Path:
    """Declare ``tmp_path`` as the registered host anchor for a unit test (r7).

    The anchor is a single dictionary: the host root, the phase-1 directory, the
    approval log, the central RunStore and the shared lock.  Tests must never
    patch ``PHASE1_ROOT`` alone, because then the phase-1 root and the anchor
    disagree and every bounded path refuses (that is the r7 invariant, not a
    test accident).  Returns the phase-1 root.
    """
    from ainerzero.v9.experiments.s1 import spec

    host = Path(tmp_path)
    root = host / "artifacts" / "v9" / "s1" / "phase1"
    root.mkdir(parents=True, exist_ok=True)
    (host / "RESEARCH_LOG.md").write_text(
        "# isolated S1 test host (no approval lines)\n", encoding="utf-8"
    )
    monkeypatch.setattr(spec, "REGISTERED_HOST_ROOT", host.resolve())
    monkeypatch.setattr(spec, "PHASE1_ROOT", root)
    if create_ledger:
        from ainerzero.v9.experiments.s1 import worker

        ledger = worker.PrepLedger(root / "control.sqlite3")
        try:
            ledger.store.create_experiment(
                worker.prep_experiment_manifest(),
                worker.PREP_REQUEST_ID,
                worker.PREP_EXPERIMENT_ID,
            )
        finally:
            ledger.close()
    return root


def make_source_checkout(dst: Path) -> Path:
    """Copy the real ``src/ainerzero`` tree into ``dst`` (an independent checkout).

    Used by the r7 anchor/lock tests: two real source checkouts must resolve the
    same registered host anchor, never one anchor each.
    """
    import shutil

    from ainerzero.v9.experiments.s1 import spec

    dst = Path(dst)
    (dst / "src").mkdir(parents=True, exist_ok=True)
    shutil.copytree(spec.REPO_ROOT / "src" / "ainerzero", dst / "src" / "ainerzero")
    return dst


def checkout_anchor(dst: Path) -> dict:
    """Import ``spec``/``worker`` *from* the checkout in a subprocess and report the anchor."""
    import json
    import os
    import subprocess
    import sys

    script = (
        "import json;"
        "from ainerzero.v9.experiments.s1 import spec, worker, commands;"
        "print(json.dumps({"
        "'root': str(spec.REGISTERED_HOST_ROOT),"
        "'phase1': str(spec.PHASE1_ROOT),"
        "'ledger': str(worker.canonical_ledger_path()),"
        "'lock': str(commands._lock_path()),"
        "'anchor': spec.host_anchor_state(),"
        "'spec_file': spec.__file__,"
        "}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(dst) / "src")
    for key in ("AINERZERO_S1_PHASE1_ROOT", "AINERZERO_S1_LEDGER", "AINERZERO_PHASE1_ROOT"):
        env.pop(key, None)
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(dst),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)

def build_payload(
    *,
    seq: int,
    t_ticks: int | None = None,
    dt_ticks: int = 12,
    episode_start: bool = False,
    detections: list[dict] | None = None,
) -> dict:
    t_ticks = seq * dt_ticks if t_ticks is None else t_ticks
    detections = detections if detections is not None else [
        {
            "handle": f"h-{(seq % 2) + 1}",
            "appearance_class": "prop/chair",
            "rel_position_m": [0.0, 0.0, 2.0],
            "rel_yaw_deg": None,
            "confidence": 0.9,
        }
    ]
    return {
        "time": {
            "sim_hz": SIM_HZ,
            "t_ticks": int(t_ticks),
            "dt_ticks": int(0 if seq == 0 else dt_ticks),
            "dt_s": float(0 if seq == 0 else dt_ticks) / SIM_HZ,
        },
        "episode_start": bool(episode_start or seq == 0),
        "observation": {
            "channels": [
                {"kind": "relative_objects", "detections": detections},
                {
                    "kind": "ego_motion",
                    "delta": {
                        "dx_m": 0.0,
                        "dy_m": 0.0,
                        "dz_m": 1.0,
                        "dyaw_deg": 3.0 if seq else 0.0,
                    },
                },
            ]
        },
        "pose_sensor_if_allowed": None,
        "visibility": {"fov_deg": 90.0, "range_m": 6.5, "occlusion": "hidden_objects_absent"},
        "sensor_noise": {
            "relative_objects": {"model": "gaussian", "params": {"sigma_m": 0.02}},
            "ego_motion": {"model": "gaussian", "params": {"sigma_m": 0.005}},
        },
        "last_action_result": None,
        "task_instruction": {"text": "走到椅子旁并坐下。", "goal": {"kind": "symbolic"}},
    }


def truth_row(*, episode_id: str, partition: str, scene_id: str, steps: int, family: str = "navigation") -> dict:
    return {
        "episode_id": episode_id,
        "partition": partition,
        "family": family,
        "scene_id": scene_id,
        "round_index": 0,
        "world_fingerprint": hashlib.sha256(scene_id.encode()).hexdigest(),
        "world_key": {"world_version": 1, "scene_id": scene_id, "revision": 0},
        "world": {"width": 5, "height": 4, "sim_hz": SIM_HZ, "blocked": [[2, 1]]},
        "steps": [
            {
                "seq": index,
                "tick": index * 12,
                "agent_world_pose": {"position": [float(index), 0.0, 0.0], "yaw_deg": 0.0},
                "handle_to_entity": {"h-1": "obj.chair"},
                "entities": {"obj.chair": {"position": [0.0, 0.0, 2.0], "appearance_class": "prop/chair"}},
                "relations": [],
                "events": [],
            }
            for index in range(steps)
        ],
    }


def make_plan(*, train_worlds: int = 4, development_worlds: int = 4, rounds: int = 1) -> dict:
    return {
        "schema": "ainerzero.v9.s1.data_plan.v1",
        "spec": "s1-phase1-v1",
        "generator": "awz.V9.B3 r2 synthetic fixture",
        "generator_commit": "0" * 40,
        "generator_root": "/synthetic/AnimeWorldZero",
        "generator_seed": "awz-v9-b3-v0",
        "restricted_exit": "fixture",
        "families": list(data.spec.DATA_PLAN["families"]),
        "scene_id_format": data.spec.DATA_PLAN["scene_id_format"],
        "partitions": ["train", "development"],
        "final_partition": "not_generated_not_read",
        "train": {"worlds": train_worlds, "rounds_per_world": rounds},
        "development": {"worlds": development_worlds, "rounds_per_world": rounds},
        "sample_interval": 12,
        "range_m": 6.5,
        "fov_deg": 90.0,
    }


def write_staging(root: Path, *, plan: dict | None = None, steps_per_world: int = 4) -> dict:
    """Write the producer staging layout (packets/truth/export_meta)."""
    plan = plan or make_plan()
    root = Path(root)
    (root / "packets").mkdir(parents=True, exist_ok=True)
    (root / "truth").mkdir(parents=True, exist_ok=True)
    episodes = []
    counts = {
        "train_packets": 0,
        "development_packets": 0,
        "train_episodes": 0,
        "development_episodes": 0,
    }
    for partition in ("train", "development"):
        count = int(plan[partition]["worlds"])
        packets_path = root / "packets" / f"{partition}.jsonl"
        truth_path = root / "truth" / f"{partition}.jsonl"
        packets_handle = packets_path.open("w", encoding="utf-8")
        truth_handle = truth_path.open("w", encoding="utf-8")
        try:
            for index in range(count):
                episode_id = hashlib.sha256(f"{partition}:{index}".encode()).hexdigest()[:32]
                scene_id = f"s1-{partition}-nav-{index:05d}"
                payloads = [
                    build_payload(seq=seq, episode_start=(seq == 0))
                    for seq in range(steps_per_world)
                ]
                for seq, payload in enumerate(payloads):
                    row = {
                        "episode_id": episode_id,
                        "partition": partition,
                        "seq": seq,
                        "payload": payload,
                    }
                    packets_handle.write(
                        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                truth = truth_row(
                    episode_id=episode_id,
                    partition=partition,
                    scene_id=scene_id,
                    steps=steps_per_world,
                )
                truth_handle.write(
                    json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                )
                episodes.append(
                    {
                        "episode_id": episode_id,
                        "partition": partition,
                        "family": "navigation",
                        "scene_id": scene_id,
                        "round_index": 0,
                        "world_fingerprint": truth["world_fingerprint"],
                        "steps": steps_per_world,
                        "packets_sha256": hashlib.sha256(canonical_bytes(payloads)).hexdigest(),
                        "truth_sha256": hashlib.sha256(canonical_bytes(truth)).hexdigest(),
                    }
                )
                counts[f"{partition}_packets"] += steps_per_world
                counts[f"{partition}_episodes"] += 1
        finally:
            packets_handle.close()
            truth_handle.close()
    meta = {
        "schema": "ainerzero.v9.s1.awz_export.v1",
        "plan": plan,
        "source_identity": {
            "root": "/synthetic/AnimeWorldZero",
            "git_head": "0" * 40,
            "file_count": 1,
            "files_sha256": {"python/animeworld/exams/packets.py": "1" * 64},
            "source_map_digest": "2" * 64,
        },
        "counts": {
            "train_worlds": int(plan["train"]["worlds"]),
            "development_worlds": int(plan["development"]["worlds"]),
            "rounds_per_world": int(plan["train"]["rounds_per_world"]),
            **counts,
        },
        "partitions": ["train", "development"],
        "final_partition": "not_generated_not_read",
        "episodes": episodes,
    }
    (root / "export_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return meta


