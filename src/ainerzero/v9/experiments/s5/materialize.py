"""S5 数据分区物化落盘 CLI 模块（纯 CPU）。

CLI: python -m ainerzero.v9.experiments.s5.materialize --partition <名> --out <目录> [--worlds a:b] [--registered-run-id <ID>]
- 生成学生段、DA2 帧（仅 pool 分区）、全部标签（R1, R2, R3, disk_groups, ordering_pairs）；
- CLI 一律拒绝 REGISTERED 分区；
- 目标目录存在且非空时抛出 FileExistsError；
- 单帧渲染复用：避免重复渲染，大幅提升物化性能；
- 生成包含代码身份（git HEAD、源文件 SHA256）与各文件校验和的 manifest.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np

from ainerzero.v9.experiments.s5.labels import (
    disk_groups,
    ordering_pairs,
    r1,
    r2,
    r3,
)
from ainerzero.v9.experiments.s5.render import (
    DEFAULT,
    SHIFT_ALL,
    SHIFT_BG,
    Appearance,
    render,
    to_uint8,
)
from ainerzero.v9.experiments.s5.world import (
    PARTITIONS,
    REGISTERED,
    da2_frames,
    episode,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _get_code_identity() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[5]
    try:
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
    except Exception:
        git_head = "unknown"

    s5_dir = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s5"
    s4_world_file = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s4" / "world.py"
    sources = {}
    if s5_dir.exists():
        for p in sorted(s5_dir.glob("*.py")):
            rel = str(p.relative_to(repo_root))
            sources[rel] = _sha256_file(p)
    if s4_world_file.exists():
        rel = str(s4_world_file.relative_to(repo_root))
        sources[rel] = _sha256_file(s4_world_file)

    return {
        "git_head": git_head,
        "source_digests": sources,
    }


def materialize_partition(
    partition: str,
    out_dir: str | Path,
    *,
    world_range: tuple[int, int] | None = None,
    registered_run_id: str | None = None,
) -> dict[str, Any]:
    """物化指定分区的数据到 out_dir。"""
    out_path = Path(out_dir)
    if out_path.exists() and any(out_path.iterdir()):
        raise FileExistsError(f"Output directory '{out_path}' exists and is not empty; refusing to overwrite")
    out_path.mkdir(parents=True, exist_ok=True)

    if partition.startswith("s5p1-") and partition not in PARTITIONS:
        raise ValueError(
            f"Unknown s5p1 partition '{partition}'; registered partitions are {sorted(PARTITIONS.keys())}"
        )

    is_registered = partition in REGISTERED
    allow_registered = False
    if is_registered:
        if not registered_run_id or not registered_run_id.strip():
            raise PermissionError(
                f"{partition} is in REGISTERED; must provide a valid --registered-run-id"
            )
        allow_registered = True

    total_worlds = PARTITIONS.get(partition)
    if total_worlds is None:
        if partition.startswith("s5test-") or partition.startswith("s5x-"):
            total_worlds = 4
        else:
            raise ValueError(f"Unknown partition: {partition}")

    if world_range is not None:
        start_w, end_w = world_range
        if not (0 <= start_w < end_w <= total_worlds):
            raise IndexError(
                f"world_range [{start_w}, {end_w}) out of bounds [0, {total_worlds}) for partition {partition}"
            )
    else:
        start_w, end_w = 0, total_worlds

    # 确定渲染外观列表
    # "final-shift 分区的世界要渲染 SHIFT_BG、SHIFT_ALL 两套。其余分区只用 DEFAULT。"
    if "final-shift" in partition:
        appearances: list[tuple[str, Appearance]] = [
            ("shift_bg", SHIFT_BG),
            ("shift_all", SHIFT_ALL),
        ]
    else:
        appearances = [("default", DEFAULT)]

    file_manifest: dict[str, dict[str, Any]] = {}
    world_indices: list[int] = list(range(start_w, end_w))

    for w in world_indices:
        ep = episode(
            partition,
            w,
            allow_registered=allow_registered,
            registered_run_id=registered_run_id,
        )
        w_dir = out_path / f"world_{w:04d}"
        w_dir.mkdir(parents=True, exist_ok=True)

        for c in range(16):
            base_t = c * 16

            # 1. 渲染学生片段与标签输入帧（单次渲染复用）
            for app_name, app in appearances:
                rendered_frames = []
                for k in range(16):
                    st = ep.steps[base_t + k]
                    rendered = render(
                        st.agent,
                        st.positions,
                        ep.pillars,
                        width=224,
                        height=224,
                        appearance=app,
                        return_ids=True,
                    )
                    rendered_frames.append(rendered)

                clip = np.stack([to_uint8(r[0]) for r in rendered_frames], axis=0)
                suffix = f"_{app_name}" if len(appearances) > 1 else ""
                clip_file = w_dir / f"clip_{c:02d}{suffix}.npy"
                np.save(clip_file, clip)
                file_manifest[str(clip_file.relative_to(out_path))] = {
                    "bytes": clip_file.stat().st_size,
                    "sha256": _sha256_file(clip_file),
                }

                # 仅对主外观生成标签
                if app_name in ("default", "shift_bg"):
                    lbl_r1 = r1(ep, c, precomputed_frames=rendered_frames)
                    lbl_r2 = r2(ep, c, precomputed_frame=rendered_frames[15])
                    st_r3 = ep.steps[base_t + 15 + 8]
                    r3_rendered = render(
                        st_r3.agent,
                        st_r3.positions,
                        ep.pillars,
                        width=224,
                        height=224,
                        appearance=app,
                        return_ids=True,
                    )
                    lbl_r3 = r3(ep, c, precomputed_frame=r3_rendered)
                    groups = disk_groups(ep, c, precomputed_frame=rendered_frames[15])
                    ordering = ordering_pairs(ep, c, precomputed_frame=rendered_frames[15])

                    labels_file = w_dir / f"labels_{c:02d}.npz"
                    np.savez_compressed(
                        labels_file,
                        r1_logd=lbl_r1["logd"],
                        r1_sky=lbl_r1["sky"],
                        r2=lbl_r2,
                        r3=lbl_r3,
                        disk_groups_json=json.dumps(groups),
                        ordering_pairs_json=json.dumps(ordering),
                    )
                    file_manifest[str(labels_file.relative_to(out_path))] = {
                        "bytes": labels_file.stat().st_size,
                        "sha256": _sha256_file(labels_file),
                    }

            # 2. 若是 pool 分区，渲染 DA2 帧
            if "pool" in partition:
                da2 = da2_frames(ep, c, appearance=DEFAULT)
                da2_file = w_dir / f"da2_{c:02d}.npy"
                np.save(da2_file, da2)
                file_manifest[str(da2_file.relative_to(out_path))] = {
                    "bytes": da2_file.stat().st_size,
                    "sha256": _sha256_file(da2_file),
                }

    manifest = {
        "partition": partition,
        "world_range": [start_w, end_w],
        "registered_run_id": registered_run_id,
        "code_identity": _get_code_identity(),
        "num_files": len(file_manifest),
        "files": file_manifest,
    }

    manifest_file = out_path / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Materialize S5 data partition.")
    parser.add_argument("--partition", required=True, help="Partition name (e.g. s5p1-pool, s5test-demo)")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--worlds", default=None, help="World range as 'a:b' (e.g. 0:4)")
    parser.add_argument("--registered-run-id", default=None, help="Required for REGISTERED partitions")

    parsed = parser.parse_args(args)

    if parsed.partition in REGISTERED:
        raise PermissionError(
            f"CLI cannot materialize registered partition '{parsed.partition}'. Registered data can only be generated by registered runners."
        )

    world_range = None
    if parsed.worlds:
        parts = parsed.worlds.split(":")
        world_range = (int(parts[0]), int(parts[1]))

    manifest = materialize_partition(
        parsed.partition,
        parsed.out,
        world_range=world_range,
        registered_run_id=parsed.registered_run_id,
    )
    print(f"Materialized partition '{parsed.partition}' ({manifest['num_files']} files) to {parsed.out}")


if __name__ == "__main__":
    main()
