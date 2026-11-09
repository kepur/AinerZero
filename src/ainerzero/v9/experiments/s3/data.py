"""GridLab-S3 Dataset and Episode Generation.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §2, §6.
Pure CPU, NumPy / standard library only. Zero MLX imports.
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Sequence

from ainerzero.v9.experiments.s2.world import make_layout
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import generate_content_state
from ainerzero.v9.experiments.s3.tour import run_tour


def derive_seed(namespace: str, *keys: Any) -> int:
    """Derive deterministic 31-bit positive integer seed from namespace and keys."""
    raw = f"{namespace}:" + ":".join(str(k) for k in keys)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(h[:16], 16) & 0x7FFFFFFF


def generate_episode(
    world_seed: int,
    episode_seed: int,
    family: str = "F1",
    *,
    t_max: int = spec.T,
    p_slip: float = spec.P_SLIP,
    noise: float = spec.NOISE,
) -> dict[str, Any]:
    """Generate one GridLab-S3 exploration episode.

    Output structure:
    - Each step contains:
      - 'obs': 198-d student observation vector (no absolute coords or truth)
      - 'action': action integer
      - 'est_pose': [ex, ey, eh] odometry estimate
      - 'truth': ground-truth position, heading, wall bumps, and cell token
    - 'events': readout event list with t, cell, prev_visit_t, lag, bucket, swapped, answer
    """
    layout = make_layout(world_seed)
    rng = random.Random(episode_seed)

    content_state = generate_content_state(layout, family, rng, m=spec.M)
    raw_episode = run_tour(
        layout,
        content_state,
        rng,
        t_max=t_max,
        p_slip=p_slip,
        noise=noise,
    )

    positions = raw_episode["trajectory_positions"]
    pos_counts = collections.Counter(positions)
    events = raw_episode["events"]

    swapped_count = sum(1 for e in events if e["swapped"])
    long_swapped_count = sum(1 for e in events if e["bucket"] == spec.BUCKET_LONG and e["swapped"])

    summary = {
        "world_seed": world_seed,
        "episode_seed": episode_seed,
        "family": family,
        "steps_count": len(raw_episode["steps"]),
        "unique_cells_visited": len(pos_counts),
        "most_frequent_cell_ratio": (
            pos_counts.most_common(1)[0][1] / len(positions) if positions else 0.0
        ),
        "total_events": len(events),
        "swapped_events": swapped_count,
        "long_swapped_events": long_swapped_count,
    }

    return {
        "world_seed": world_seed,
        "episode_seed": episode_seed,
        "family": family,
        "layout_sha256": raw_episode["layout_sha256"],
        "content_state": raw_episode["content_state"],
        "steps": raw_episode["steps"],
        "events": events,
        "summary": summary,
    }


def resolve_partition_namespace(name: str) -> str:
    """Resolve short name or namespace string to official registered namespace."""
    mapping = {
        "train": spec.NAMESPACE_TRAIN,
        "dev": spec.NAMESPACE_DEV,
        "final": spec.NAMESPACE_FINAL,
        "probe": spec.NAMESPACE_PROBE,
        spec.NAMESPACE_TRAIN: spec.NAMESPACE_TRAIN,
        spec.NAMESPACE_DEV: spec.NAMESPACE_DEV,
        spec.NAMESPACE_FINAL: spec.NAMESPACE_FINAL,
        spec.NAMESPACE_PROBE: spec.NAMESPACE_PROBE,
    }
    if name not in mapping:
        raise ValueError(
            f"Unknown partition name: '{name}'. Expected one of {list(mapping.keys())}"
        )
    return mapping[name]


def generate_partition(
    name: str,
    n_worlds: int,
    episodes_per_world: int,
    family: str = "F1",
    *,
    allow_final: bool = False,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate dataset partition with strict preregistration safeguards.

    Safeguards:
    - 'final' partition is refused by default unless allow_final=True is passed.
    - Output path cannot be located under 'artifacts/' directly from execution.
    - Default is in-memory generation (output_path=None).
    """
    namespace = resolve_partition_namespace(name)

    if namespace == spec.NAMESPACE_FINAL and not allow_final:
        raise PermissionError(
            "Generation of final partition is refused by default. "
            "Requires explicit allow_final=True per frozen preregistration protocol."
        )

    episodes_meta: list[dict[str, Any]] = []
    total_events = 0
    total_swapped = 0
    bucket_counts: dict[str, int] = collections.defaultdict(int)

    for w_idx in range(n_worlds):
        world_seed = derive_seed(namespace, "world", w_idx)
        for ep_idx in range(episodes_per_world):
            ep_seed = derive_seed(namespace, "ep", w_idx, ep_idx)
            ep = generate_episode(world_seed, ep_seed, family=family)

            episodes_meta.append(
                {
                    "world_index": w_idx,
                    "episode_index": ep_idx,
                    "world_seed": world_seed,
                    "episode_seed": ep_seed,
                    "summary": ep["summary"],
                }
            )
            total_events += ep["summary"]["total_events"]
            total_swapped += ep["summary"]["swapped_events"]
            for ev in ep["events"]:
                bk = ev.get("bucket")
                if bk:
                    bucket_counts[bk] += 1

    partition_summary = {
        "namespace": namespace,
        "family": family,
        "n_worlds": n_worlds,
        "episodes_per_world": episodes_per_world,
        "total_episodes": len(episodes_meta),
        "total_events": total_events,
        "total_swapped": total_swapped,
        "swapped_ratio": (total_swapped / total_events) if total_events else 0.0,
        "bucket_counts": dict(bucket_counts),
        "episodes": episodes_meta,
    }

    if output_path is not None:
        out_p = Path(output_path).resolve()
        if "artifacts" in out_p.parts:
            raise PermissionError(
                f"Writing dataset to artifacts/ is strictly prohibited: {out_p}"
            )
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(partition_summary, f, indent=2)

    return partition_summary
