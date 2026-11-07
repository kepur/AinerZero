"""Data generation runner for S2 GridLab multi-room experiments (ainerzero.V9.P133).

Orchestrates pure-CPU partition data generation (train, dev, final) inside the
central RunStore lifecycle. Zero GPU framework imports. No real production data is generated.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2, §6.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence

from ainerzero.v9.experiments.s2 import data, spec
from ainerzero.v9.experiments.s2.spec import (
    DEV_PAIRS_PER_WORLD,
    DEV_WORLDS_COUNT,
    EPISODE_STEPS,
    EXPERIMENT_ID,
    FINAL_PAIRS_PER_WORLD,
    FINAL_WORLDS_COUNT,
)
from ainerzero.v9.experiments.s2.worker import S2Ledger

__all__ = [
    "run_generate_data",
    "check_partition_already_completed",
    "assert_output_root_is_permitted",
    "assert_output_root_is_temporary",
    "REGISTERED_HOST_ROOT",
    "REGISTERED_OUTPUT_ROOT",
    "DEFAULT_SEED_NAMESPACES",
]

DEFAULT_SEED_NAMESPACES: dict[str, str] = {
    "train": "s2-phase1-train-v1",
    "dev": "s2-phase1-dev-v1",
    "final": "s2-phase1-final-v1",
}

# Pending merge into spec.py once P125 is accepted
REGISTERED_HOST_ROOT: Path = getattr(
    spec, "REGISTERED_HOST_ROOT", Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
)
REGISTERED_OUTPUT_ROOT: Path = getattr(
    spec,
    "REGISTERED_OUTPUT_ROOT",
    (REGISTERED_HOST_ROOT / "artifacts" / "v9" / "s2" / "phase1").resolve(),
)


def assert_output_root_is_permitted(output_root: str | Path) -> Path:
    """Assert output_root is either the registered production path or a valid non-artifacts path.

    Rules per ainerzero.V9.P138:
    1. Permitted: output_root resolves exactly to REGISTERED_HOST_ROOT / "artifacts/v9/s2/phase1".
    2. Permitted: Any path outside REGISTERED_HOST_ROOT / "artifacts" (e.g. test tmp_path).
    3. Refused: Any other path under REGISTERED_HOST_ROOT / "artifacts" (e.g. e1, s1, or other s2 dirs).
    4. Refused: Symlinks resolving into non-registered artifacts paths (resolved prior to comparison).
    """
    out_path = Path(output_root).resolve()

    host_root = Path(
        getattr(spec, "REGISTERED_HOST_ROOT", None) or REGISTERED_HOST_ROOT
    ).resolve()
    artifacts_root = (host_root / "artifacts").resolve()
    registered_output = (artifacts_root / "v9" / "s2" / "phase1").resolve()

    # Rule 1: Exact match with registered production path is permitted
    if out_path == registered_output:
        return out_path

    # Rule 2 & 3: Refuse any other path under artifacts
    if out_path == artifacts_root or out_path.is_relative_to(artifacts_root):
        raise ValueError(
            f"output_root cannot point to non-registered artifacts directory: {out_path} (registered is {registered_output})"
        )

    # Rule 4: Outside artifacts (e.g. tmp_path) is permitted
    return out_path


# Backward compatibility alias
assert_output_root_is_temporary = assert_output_root_is_permitted


def check_partition_already_completed(
    ledger: S2Ledger,
    partition: str,
    experiment_id: str = EXPERIMENT_ID,
) -> str | None:
    """Query the ledger to check if the partition has already completed.

    Returns:
        The run_id of the completed run if found, else None.
    """
    cursor = ledger.store._conn.execute(
        "SELECT run_id, config_json, state FROM runs WHERE experiment_id = ? AND state = 'completed'",
        (experiment_id,),
    )
    for row in cursor.fetchall():
        try:
            cfg = json.loads(row["config_json"])
        except Exception:
            continue
        if cfg.get("mode") == "generate-data" and cfg.get("partition") == partition:
            return str(row["run_id"])
    return None


def run_generate_data(
    partition: str = "dev",
    output_root: str | Path | None = None,
    ledger: S2Ledger | None = None,
    *,
    n_worlds: int | None = None,
    episodes_per_world: int | None = None,
    seed_namespace: str | None = None,
    clock: Callable[[], float] | None = None,
    run_id: str | None = None,
    experiment_id: str = EXPERIMENT_ID,
    cell_wall_budget: float | None = None,
    force_bfs_only: bool = False,
    enforce_rejection_redraw: bool = True,
    max_steps_per_episode: int = EPISODE_STEPS,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute S2 data generation for a specified partition inside the work cell lifecycle.

    Can be invoked directly or passed as a runner into execute_work_cell.

    Args:
        partition: 'train', 'dev', or 'final'.
        output_root: Root directory under which datasets/<partition> is written. Must be temporary.
        ledger: S2Ledger instance for lifecycle and run recording.
        n_worlds: Number of multi-room worlds to generate.
        episodes_per_world: Number of episodes per world.
        seed_namespace: Deterministic seed namespace.
        clock: Monotonic clock callable (defaults to time.time).
        run_id: Active ledger run_id if already opened by execute_work_cell.
        experiment_id: Target experiment identifier.
        cell_wall_budget: Budget in seconds.
        force_bfs_only: Whether to force pure BFS exploration.
        enforce_rejection_redraw: Whether to enforce redraw when ambiguity exceeds 30%.
        max_steps_per_episode: Steps per episode.
    """
    # 1. Partition specification check
    if not partition:
        raise ValueError("generate-data requires explicit partition ('train', 'dev', or 'final')")
    part = partition.lower()
    if part not in ("train", "dev", "final"):
        raise ValueError(
            f"Invalid partition {partition!r}; must be one of ('train', 'dev', 'final')"
        )

    if output_root is None:
        raise ValueError("output_root must be explicitly specified and non-empty")

    # 2. Output root permission check
    out_path = assert_output_root_is_permitted(output_root)

    # Scale resolution
    if part == "train":
        if n_worlds is None or episodes_per_world is None:
            raise ValueError(
                "train partition scale (n_worlds and episodes_per_world) must be explicitly provided"
            )
        actual_n_worlds = int(n_worlds)
        actual_episodes_per_world = int(episodes_per_world)
    elif part == "dev":
        actual_n_worlds = int(n_worlds) if n_worlds is not None else DEV_WORLDS_COUNT
        actual_episodes_per_world = (
            int(episodes_per_world)
            if episodes_per_world is not None
            else DEV_PAIRS_PER_WORLD
        )
    else:  # final
        actual_n_worlds = int(n_worlds) if n_worlds is not None else FINAL_WORLDS_COUNT
        actual_episodes_per_world = (
            int(episodes_per_world)
            if episodes_per_world is not None
            else FINAL_PAIRS_PER_WORLD
        )

    actual_seed_namespace = (
        seed_namespace
        if seed_namespace is not None
        else spec.SEED_NAMESPACES[part]
    )

    # 3. Duplicate execution check against ledger
    if ledger is not None:
        completed_run_id = check_partition_already_completed(
            ledger, partition=part, experiment_id=experiment_id
        )
        if completed_run_id is not None:
            return {
                "status": "duplicate_execution",
                "partition": part,
                "message": f"Partition {part!r} has already completed in ledger run {completed_run_id}",
                "run_id": completed_run_id,
            }

    clock_fn = clock or time.time
    t0 = clock_fn()

    # Manage ledger run lifecycle if not provided by caller
    owns_run = False
    current_run_id = run_id
    if ledger is not None and current_run_id is None:
        budget = (
            float(cell_wall_budget)
            if cell_wall_budget is not None
            else float(spec.BUDGET_DATA_MAX_SECONDS)
        )
        current_run_id = ledger.open_run(
            mode="generate-data",
            arm=None,
            seed=None,
            cell_wall_budget=budget,
            experiment_id=experiment_id,
            runner_name="run_generate_data",
            snapshot_extra={"partition": part},
        )
        ledger.begin_run(current_run_id, state="collecting")
        owns_run = True

    datasets_dir = out_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)

    # 4. Generate partition using data.generate_partition
    try:
        manifest_data = data.generate_partition(
            partition=part,
            n_worlds=actual_n_worlds,
            episodes_per_world=actual_episodes_per_world,
            output_root=datasets_dir,
            seed_namespace=actual_seed_namespace,
            max_steps_per_episode=max_steps_per_episode,
            enforce_rejection_redraw=enforce_rejection_redraw,
            force_bfs_only=force_bfs_only,
        )

        # 5. Handle write directory and sealed_final sealing
        if part == "final":
            final_raw_dir = datasets_dir / "final"
            target_part_dir = datasets_dir / "sealed_final"
            if target_part_dir.exists():
                shutil.rmtree(target_part_dir)
            if final_raw_dir.exists():
                final_raw_dir.rename(target_part_dir)

            # Write sealed_final/LAYOUT_DIGESTS.json using in-memory manifest_data
            layout_digests_payload = {
                "partition": manifest_data.get("partition", "final"),
                "seed_namespace": manifest_data.get("seed_namespace", actual_seed_namespace),
                "layout_digests": list(manifest_data.get("layout_digests", [])),
            }
            layout_file = target_part_dir / "LAYOUT_DIGESTS.json"
            layout_file.write_text(
                json.dumps(layout_digests_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            target_part_dir = datasets_dir / part

        sums_file = target_part_dir / "SHA256SUMS.txt"
        if not sums_file.is_file():
            raise FileNotFoundError(f"Missing SHA256SUMS.txt in {target_part_dir}")

        # Compute SHA of SHA256SUMS.txt without reading back sequence JSON contents
        sums_raw_bytes = sums_file.read_bytes()
        sha256sums_digest = hashlib.sha256(sums_raw_bytes).hexdigest()

        # 6. Verify disjointness against other existing partitions
        other_manifests: list[dict[str, Any]] = []
        for candidate_name in ("train", "dev", "sealed_final"):
            cand_dir = datasets_dir / candidate_name
            if candidate_name == part or (part == "final" and candidate_name == "sealed_final"):
                continue

            if candidate_name == "sealed_final":
                # For sealed_final, strictly read ONLY LAYOUT_DIGESTS.json without opening manifest.json
                cand_layout = cand_dir / "LAYOUT_DIGESTS.json"
                if cand_layout.is_file():
                    other_manifests.append(
                        json.loads(cand_layout.read_text(encoding="utf-8"))
                    )
            else:
                cand_manifest = cand_dir / "manifest.json"
                if cand_manifest.is_file():
                    other_manifests.append(
                        json.loads(cand_manifest.read_text(encoding="utf-8"))
                    )

        # Check disjointness with all existing partitions
        if other_manifests:
            data.assert_partitions_disjoint([manifest_data, *other_manifests])

        elapsed_s = clock_fn() - t0

        # Calculate metrics
        redraw_count = sum(
            int(ws.get("prep_summary", {}).get("redraw_retries", 0))
            for ws in manifest_data.get("world_summaries", [])
        )
        non_bfs_ratio = float(
            manifest_data.get("segment_stats", {}).get("non_bfs_ratio", 0.0)
        )

        result_payload = {
            "status": "completed",
            "partition": part,
            "target_dir": str(target_part_dir),
            "n_worlds": actual_n_worlds,
            "episodes_per_world": actual_episodes_per_world,
            "total_episodes": actual_n_worlds * actual_episodes_per_world,
            "non_bfs_ratio": non_bfs_ratio,
            "world_redraw_count": redraw_count,
            "sha256sums_hash": sha256sums_digest,
            "elapsed_s": round(elapsed_s, 4),
            "manifest_file": str(target_part_dir / "manifest.json"),
        }

        if ledger is not None and current_run_id is not None:
            ledger.complete_run(
                current_run_id,
                active_seconds=elapsed_s,
                optimizer_steps=0,
                metrics=result_payload,
            )

        return result_payload

    except Exception as exc:
        if ledger is not None and current_run_id is not None and owns_run:
            ledger.fail_run(current_run_id, reason=str(exc))
        raise
