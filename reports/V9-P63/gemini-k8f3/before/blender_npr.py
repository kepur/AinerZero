"""Blender NPR 表现层最小切片执行器与 CPU 判官（线稿、卡通着色、ACIS 分区光影）。

依据：
- AGENT_TASKS.md P3-D2 任务卡（ADR-0010 B-3, claude-awz 2026-10-28）
- STYLE_PACKAGE_V2.md §3（美术控制面）与 CHARACTER_PACKAGE_V2.md §2（分区光影）
- python/animeworld/style_v2/loader.py (load_style_v2_package)
- python/animeworld/style_v2/planner.py (plan_backend_capabilities, KNOWN_FEATURE_REGISTRY)
- python/animeworld/render_backend/blender_adapter.py（只 import，不改动）
- tools/blender/backend/eevee_slice.py（只 import，不改动）

严守：
- 严格单场景流水线复用：同一 take.blend 运行两遍正式跑 + 诊断跑
- 预登记候选门：line_mask / band_mask / object_id 逐位一致；CPU 判官一致率 >= 0.97；线宽落在 [min, max] 比例 100%
- 逐特性实测证据 (feature_evidence.json)：状态只由实测推出；planner 被真实调用并原样记录其决定，
  其证据表是 planner.py 里的常量，本模块不改它，只列建议增补清单
- 冻结 SHA-256 开工与收尾对拍
"""

from __future__ import annotations

import collections
import itertools
import json
import math
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animeworld.render_backend.blender_adapter import (
    RESOLUTION,
    file_sha256,
    hub_worker_paths,
    mean_abs_rgb,
    pixel_sha256,
    read_png_rgb8,
)
from animeworld.style_v2.errors import StyleV2CapabilityError
from animeworld.style_v2.loader import load_style_v2_package
from animeworld.style_v2.planner import (
    FEATURE_BACKEND_EVIDENCE,
    KNOWN_FEATURE_REGISTRY,
    plan_backend_capabilities,
)

ROOT = Path(__file__).resolve().parents[3]
NPR_SLICE_SCRIPT = ROOT / "tools/blender/backend/npr_slice.py"
BLENDER_BIN = Path("/Applications/Blender.app/Contents/MacOS/Blender")

# 冻结权威输入 SHA256 绑定
FROZEN_SHA256_REGISTRY = {
    "reports/T04/replay.json": "8d3f8441cb9f163aa96fa1acd2d4bef6207db40f05514916ec1cd443c9252b30",
    "python/animeworld/render_backend/blender_adapter.py": "b04e73fceb2290f717608c454a835f3117d7a0d2982185fcca4d540639931085",
    "tools/blender/backend/eevee_slice.py": "ecf94efa810ca83b4c8a89c8bf49679fdf1e4adfee44c2a30d511672896fab33",
    "python/animeworld/style_v2/loader.py": "db762a1f7874843f0d761cd3f30437802c7b0d1b69097360ccdfc453acaee60d",
    "python/animeworld/style_v2/planner.py": "be2f3f94e5bdcd92f1e54a81648c93bb98182f65634bee24583bbdfbe3f0a866",
    "contracts/backend_capabilities.v1.json": "2c7509719ce6a506b5f0c0576b6c99890ea56df9b50ba2cb81156008310f5dab",
    "AinerHub world_multicam.py": "38daf3471a36c4de650590b95de4e7d90b4c38634aed6d8776ced149afbb8c61",
}

# 预登记候选门阈值
BAND_ORACLE_AGREEMENT_MIN = 0.97
BOUNDARY_EXCLUSION_PX = 2
TRANSITION_BAND_HALF_WIDTH = 0.05
LINE_WIDTH_IN_RANGE_RATIO_MIN = 1.0

# 太阳平行光朝向光源的单位向量 (Sun Euler: 0.5, 0.2, 0.0)
SUN_VECTOR_TO_LIGHT = (0.1743048, -0.4794255, 0.8601004)


def verify_frozen_inputs(repo_root: Path = ROOT) -> dict[str, str]:
    """严格核对所有冻结输入的 SHA256，任一不符立刻阻断。"""
    results = {}
    hub_script_path = Path(hub_worker_paths()["worker_script"])
    for rel_or_alias, expected in FROZEN_SHA256_REGISTRY.items():
        if rel_or_alias == "AinerHub world_multicam.py":
            actual_path = hub_script_path
        else:
            actual_path = repo_root / rel_or_alias

        if not actual_path.is_file():
            raise RuntimeError(f"冻结输入文件不存在: {actual_path}")
        actual_sha = file_sha256(actual_path)
        if actual_sha != expected:
            raise RuntimeError(
                f"冻结输入 SHA256 不符! 文件: {rel_or_alias}, 期望: {expected}, 实际: {actual_sha}"
            )
        results[rel_or_alias] = actual_sha
    return results


def check_power_and_blender_guards() -> dict[str, Any]:
    """环境守护：AC 供电、Blender 版本、/tmp/ainer_blender.lock 状态。"""
    # 1. 检查电源
    res_ps = subprocess.run(
        ["pmset", "-g", "ps"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "AC Power" not in res_ps.stdout and "AC" not in res_ps.stdout:
        raise RuntimeError(f"非 AC 供电环境，依规停手: {res_ps.stdout.strip()}")

    # 2. 检查 Blender 版本
    if not BLENDER_BIN.is_file():
        raise RuntimeError(f"Blender 未安装在指定路径: {BLENDER_BIN}")
    res_b = subprocess.run(
        [str(BLENDER_BIN), "-b", "--factory-startup", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "5.2.2" not in res_b.stdout:
        raise RuntimeError(f"Blender 版本不是 5.2.2: {res_b.stdout.strip()}")

    # 3. 检查全局锁
    lock_file = Path("/tmp/ainer_blender.lock")
    if lock_file.exists():
        raise RuntimeError(f"全局锁被占: {lock_file}")

    return {
        "power": "AC Power",
        "blender_version": "5.2.2",
        "lock_free": True,
    }


def load_style_package_authoritative(
    rel_path: str = "reports/P3-D1/formalization/examples/day_cel/style.v2.json",
    repo_root: Path = ROOT,
) -> tuple[Any, Any]:
    """通过权威 style_v2 loader 加载风格包并生成 target_backend 计划。"""
    pkg = load_style_v2_package(package_root=repo_root, manifest_filename=rel_path)
    plan = plan_backend_capabilities(pkg, target_backend="blender-eevee")
    return pkg, plan


def compute_cpu_band_oracle(
    normal_png_path: Path,
    id_png_path: Path,
    bands: int = 2,
    thresholds: list[float] | None = None,
    sun_vector: tuple[float, float, float] = SUN_VECTOR_TO_LIGHT,
) -> dict[tuple[int, int], int]:
    """CPU 独立判官：利用 normal 通道与太阳平行光向量计算每像素期望明暗档位。

    判官完全独立运行，不读取 Blender 渲染的 band_mask。
    返回值：{(x, y): expected_band_value (0, 255 或 0, 127, 255)}
    """
    if thresholds is None:
        thresholds = [0.0] if bands == 2 else [0.35, 0.70]

    w_n, h_n, n_rows = read_png_rgb8(normal_png_path)
    w_id, h_id, id_rows = read_png_rgb8(id_png_path)
    if (w_n, h_n) != (w_id, h_id):
        raise ValueError(f"尺寸不匹配: normal ({w_n}x{h_n}) vs id ({w_id}x{h_id})")

    lx, ly, lz = sun_vector
    oracle_map: dict[tuple[int, int], int] = {}

    for y in range(h_n):
        n_row = n_rows[y]
        id_row = id_rows[y]
        for x in range(w_n):
            idx = x * 3
            # heroine 蓝色标识: R < 50, G < 50, B > 200
            if id_row[idx] < 50 and id_row[idx + 1] < 50 and id_row[idx + 2] > 200:
                nx = (n_row[idx] / 255.0) * 2.0 - 1.0
                ny = (n_row[idx + 1] / 255.0) * 2.0 - 1.0
                nz = (n_row[idx + 2] / 255.0) * 2.0 - 1.0
                mag = math.sqrt(nx * nx + ny * ny + nz * nz)
                if mag > 0:
                    nx, ny, nz = nx / mag, ny / mag, nz / mag

                dot = nx * lx + ny * ly + nz * lz

                if bands == 2:
                    t0 = thresholds[0]
                    band_val = 255 if dot > t0 else 0
                elif bands == 3:
                    t0, t1 = thresholds[0], thresholds[1]
                    if dot <= t0:
                        band_val = 0
                    elif dot <= t1:
                        band_val = 127
                    else:
                        band_val = 255
                else:
                    band_val = 255 if dot > 0.0 else 0

                oracle_map[(x, y)] = band_val

    return oracle_map


def evaluate_band_oracle_agreement(
    band_png_path: Path,
    normal_png_path: Path,
    id_png_path: Path,
    bands: int = 2,
    thresholds: list[float] | None = None,
    boundary_exclusion_px: int = BOUNDARY_EXCLUSION_PX,
    transition_half_width: float = TRANSITION_BAND_HALF_WIDTH,
) -> dict[str, Any]:
    """对比 Blender 渲染的 band_mask 与 CPU 判官的逐像素一致率，两种口径一并给出。

    - 卡面口径（用于判门）：只排除剪影内侧 ``boundary_exclusion_px`` 像素带。
    - 加严对照口径：再排除 ``|dot - 阈值| < transition_half_width`` 的明暗过渡带。
    两份都报告排除的像素数；顶层字段（``agreement_ratio`` / ``passed`` 等）是卡面口径。
    """
    w_b, h_b, b_rows = read_png_rgb8(band_png_path)
    w_id, h_id, id_rows = read_png_rgb8(id_png_path)
    w_n, h_n, n_rows = read_png_rgb8(normal_png_path)
    if (w_b, h_b) != (w_id, h_id) or (w_b, h_b) != (w_n, h_n):
        raise ValueError("band / object_id / normal 尺寸不一致")

    oracle_map = compute_cpu_band_oracle(normal_png_path, id_png_path, bands=bands, thresholds=thresholds)
    t_refs = [0.0] if bands == 2 else (thresholds or [0.35, 0.70])
    if bands == 2 and thresholds:
        t_refs = [thresholds[0]]

    hero_grid = [[False] * w_b for _ in range(h_b)]
    dot_grid = [[0.0] * w_b for _ in range(h_b)]
    lx, ly, lz = SUN_VECTOR_TO_LIGHT
    for y in range(h_b):
        for x in range(w_b):
            idx = x * 3
            if id_rows[y][idx] < 50 and id_rows[y][idx + 1] < 50 and id_rows[y][idx + 2] > 200:
                hero_grid[y][x] = True
                nx = (n_rows[y][idx] / 255.0) * 2.0 - 1.0
                ny = (n_rows[y][idx + 1] / 255.0) * 2.0 - 1.0
                nz = (n_rows[y][idx + 2] / 255.0) * 2.0 - 1.0
                mag = math.sqrt(nx * nx + ny * ny + nz * nz)
                if mag > 0:
                    dot_grid[y][x] = (nx * lx + ny * ly + nz * lz) / mag

    card = {"matching": 0, "evaluated": 0, "excluded": 0}
    strict = {"matching": 0, "evaluated": 0, "excluded": 0}
    mismatches: list[dict[str, Any]] = []
    for (x, y), expected_band in oracle_map.items():
        near_edge = False
        for dy in range(-boundary_exclusion_px, boundary_exclusion_px + 1):
            for dx in range(-boundary_exclusion_px, boundary_exclusion_px + 1):
                ny_, nx_ = y + dy, x + dx
                if not (0 <= ny_ < h_b and 0 <= nx_ < w_b) or not hero_grid[ny_][nx_]:
                    near_edge = True
                    break
            if near_edge:
                break
        in_transition = any(abs(dot_grid[y][x] - tr) < transition_half_width for tr in t_refs)

        actual_pixel = b_rows[y][x * 3]
        if bands == 2:
            rendered_band = 255 if actual_pixel > 128 else 0
        elif actual_pixel < 64:
            rendered_band = 0
        elif actual_pixel < 192:
            rendered_band = 127
        else:
            rendered_band = 255
        agree = rendered_band == expected_band

        if near_edge:
            card["excluded"] += 1
            strict["excluded"] += 1
            continue
        card["evaluated"] += 1
        card["matching"] += agree
        if not agree and len(mismatches) < 10:
            mismatches.append(
                {"x": x, "y": y, "expected": expected_band, "rendered": rendered_band, "dot": round(dot_grid[y][x], 4)}
            )
        if in_transition:
            strict["excluded"] += 1
        else:
            strict["evaluated"] += 1
            strict["matching"] += agree

    def ratio(part: dict[str, int]) -> float:
        return round(part["matching"] / part["evaluated"], 6) if part["evaluated"] else 0.0

    card_ratio = ratio(card)
    return {
        "basis": f"card: exclude silhouette {boundary_exclusion_px}px band only",
        "matching": card["matching"],
        "total_evaluated": card["evaluated"],
        "excluded_boundary_pixels": card["excluded"],
        "agreement_ratio": card_ratio,
        "min_threshold": BAND_ORACLE_AGREEMENT_MIN,
        "passed": card["evaluated"] > 0 and card_ratio >= BAND_ORACLE_AGREEMENT_MIN,
        "mismatch_samples": mismatches,
        "with_transition_band": {
            "basis": f"stricter-excluding: also exclude |dot - threshold| < {transition_half_width}",
            "matching": strict["matching"],
            "total_evaluated": strict["evaluated"],
            "excluded_pixels": strict["excluded"],
            "excluded_transition_only": strict["excluded"] - card["excluded"],
            "agreement_ratio": ratio(strict),
        },
    }


def measure_line_width(
    line_png_path: Path,
    min_width_px: float = 1.0,
    max_width_px: float = 3.0,
) -> dict[str, Any]:
    """逐像素实测局部笔触线宽：min(horizontal_run, vertical_run)。

    门控验证：落在 [min_width_px, max_width_px] 区间的比例是否为 100%。
    """
    w, h, rows = read_png_rgb8(line_png_path)
    mask = [[rows[y][x * 3] > 128 for x in range(w)] for y in range(h)]

    local_widths = []
    out_of_range = []

    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                # 水平 run
                x0 = x
                while x0 > 0 and mask[y][x0 - 1]:
                    x0 -= 1
                x1 = x
                while x1 < w - 1 and mask[y][x1 + 1]:
                    x1 += 1
                h_len = x1 - x0 + 1

                # 垂直 run
                y0 = y
                while y0 > 0 and mask[y0 - 1][x]:
                    y0 -= 1
                y1 = y
                while y1 < h - 1 and mask[y1 + 1][x]:
                    y1 += 1
                v_len = y1 - y0 + 1

                stroke_w = min(h_len, v_len)
                local_widths.append(stroke_w)
                if not (min_width_px <= stroke_w <= max_width_px):
                    out_of_range.append({"x": x, "y": y, "width_px": stroke_w})

    total_px = len(local_widths)
    if total_px == 0:
        return {
            "total_line_pixels": 0,
            "in_range_pixels": 0,
            "in_range_ratio": 1.0,
            "distribution": {},
            "out_of_range": [],
            "passed": True,
        }

    in_range_count = total_px - len(out_of_range)
    in_range_ratio = in_range_count / total_px
    dist = dict(collections.Counter(local_widths))

    return {
        "total_line_pixels": total_px,
        "in_range_pixels": in_range_count,
        "in_range_ratio": round(in_range_ratio, 6),
        "min_width_px": min_width_px,
        "max_width_px": max_width_px,
        "distribution": dist,
        "out_of_range": out_of_range,
        "passed": in_range_ratio >= LINE_WIDTH_IN_RANGE_RATIO_MIN,
    }


def compare_npr_runs(run_a_dir: Path, run_b_dir: Path, frames: int = 8) -> dict[str, Any]:
    """对比 Run A 与 Run B：line_mask, band_mask, object_id 是否 100% 逐位一致，rgb 差异如实报告。"""
    channels_to_check = [
        "line_mask",
        "line_outer",
        "line_inner",
        "band_mask",
        "object_id",
        "acis_partition",
        "normal",
    ]

    channel_results = {}
    gated_bit_exact = True

    for ch in channels_to_check:
        ch_a = run_a_dir / ch
        ch_b = run_b_dir / ch
        mismatches = []
        for i in range(frames):
            fname = f"{i:04d}.png"
            pa = ch_a / fname
            pb = ch_b / fname
            if not pa.is_file() or not pb.is_file():
                mismatches.append(i)
                continue
            sha_a = pixel_sha256(pa)
            sha_b = pixel_sha256(pb)
            if sha_a != sha_b:
                mismatches.append(i)

        ch_bit_exact = (len(mismatches) == 0)
        channel_results[ch] = {
            "bit_exact": ch_bit_exact,
            "mismatch_frames": mismatches,
        }
        if ch in ("line_mask", "band_mask", "object_id") and not ch_bit_exact:
            gated_bit_exact = False

    # 对比 rgb 通道
    rgb_a = run_a_dir / "rgb"
    rgb_b = run_b_dir / "rgb"
    rgb_diffs = []
    max_rgb_diff = 0
    for i in range(frames):
        fname = f"{i:04d}.png"
        pa = rgb_a / fname
        pb = rgb_b / fname
        if pa.is_file() and pb.is_file():
            res = mean_abs_rgb(pa, pb)
            rgb_diffs.append(res["mean_abs"])
            max_rgb_diff = max(max_rgb_diff, res["max_abs"])

    avg_rgb_diff = (sum(rgb_diffs) / len(rgb_diffs)) if rgb_diffs else 0.0

    return {
        "gated_bit_exact": gated_bit_exact,
        "channels": channel_results,
        "rgb": {
            "mean_abs_diff": avg_rgb_diff,
            "max_pixel_diff": max_rgb_diff,
            "note": "EEVEE 光栅化微小颜色差异符合预期",
        },
    }


RENDERER_DEFAULT_PALETTE = {
    "palette_lit": (0.85, 0.62, 0.52),
    "palette_mid": (0.72, 0.54, 0.46),
    "palette_shadow": (0.60, 0.45, 0.40),
}


def style_params_from_package(pkg: Any, repo_root: Path = ROOT) -> dict[str, Any]:
    """从已由权威 loader 校验的风格包里读出线稿与着色参数。

    读的是 sections 引用的文件，并再核对一次 sha256；调色板在这批夹具里是 mode=none，
    所以颜色用渲染器默认值，并在结果里标明不是来自风格包。
    """

    def section_json(name: str) -> dict[str, Any]:
        spec = pkg.sections.get(name)
        if spec is None or spec.mode != "referenced" or not spec.file_refs:
            raise RuntimeError(f"风格包 section {name!r} 没有引用文件")
        ref = spec.file_refs[0]
        path = repo_root / ref.uri
        if file_sha256(path) != ref.sha256:
            raise RuntimeError(f"section 文件 sha256 与风格包引用不符: {ref.uri}")
        return json.loads(path.read_text(encoding="utf-8"))

    lines = section_json("lines")["outer"]
    shading = section_json("shading")
    return {
        "style_id": pkg.style_id,
        "bands": int(shading["bands"]),
        "band_thresholds": [float(t) for t in shading["band_thresholds"]],
        "width_scale": float(lines["width_scale"]),
        "taper": float(lines["taper"]),
        "min_width_px": float(lines["min_width_px"]),
        "max_width_px": float(lines["max_width_px"]),
        "color_override": lines["color_override"],
        **{k: list(v) for k, v in RENDERER_DEFAULT_PALETTE.items()},
        "palette_source": "renderer_default (style package palette section is mode=none)",
    }


def modal_width(distribution: dict[Any, int]) -> int | None:
    """出现次数最多的线宽（并列取较小者）。"""
    if not distribution:
        return None
    items = sorted(((int(w), int(c)) for w, c in distribution.items()), key=lambda wc: (-wc[1], wc[0]))
    return items[0][0]


def evaluate_width_sweep(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """线宽参数扫描的判定（纯函数）。

    每项需含 ``name``、``target_width_px``、``distribution``（实测线宽 -> 像素数）。
    - 单调：不同目标宽度按目标升序，其实测众数必须严格递增（至少 3 个不同目标）。
    - 夹取等价：目标宽度相同的各项（例如 width_scale 越界被 min/max 夹到同一目标），实测众数必须相等。
    """
    if len(entries) < 2:
        raise ValueError("width sweep needs at least 2 entries")
    rows = []
    for e in entries:
        rows.append(
            {
                "name": e["name"],
                "target_width_px": float(e["target_width_px"]),
                "modal_width_px": modal_width(e["distribution"]),
                "line_pixels": sum(int(c) for c in e["distribution"].values()),
                "in_range_ratio": e.get("in_range_ratio"),
            }
        )
    by_target: dict[float, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        by_target[r["target_width_px"]].append(r)
    targets = sorted(by_target)
    modal_by_target = [by_target[t][0]["modal_width_px"] for t in targets]
    monotonic = (
        len(targets) >= 3
        and all(m is not None for m in modal_by_target)
        and all(b > a for a, b in itertools.pairwise(modal_by_target))
    )
    clamp_equivalent = all(
        len({r["modal_width_px"] for r in group}) == 1 for group in by_target.values()
    )
    return {
        "entries": rows,
        "distinct_targets": targets,
        "modal_by_target": modal_by_target,
        "monotonic_across_targets": monotonic,
        "clamp_equivalent": clamp_equivalent,
        "parameter_response_passed": bool(monotonic and clamp_equivalent),
    }


ALLOWED_EVIDENCE_STATUS = ("supported", "approximate", "unsupported")
PLANNER_BACKEND = "blender-eevee"


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def generate_feature_evidence(
    out_root: Path,
    style_ids: list[str],
    measured: dict[str, Any],
) -> dict[str, Any]:
    """逐特性证据（r2）：状态只由实测推出，没有实测的一律 unsupported 并写明原因类别。

    ``measured`` 由 ``execute`` 从产物重算得到：repeat（两次运行比较）、bands（各配置判官一致率）、
    sweep（线宽扫描判定）、formal_line（正式配置线宽）、inner_pixels、partition_pixels。
    每个 supported / approximate 特性的 ``measurements.computed_by`` 写明计算它的函数。
    """
    features: dict[str, Any] = {}
    repeat = measured["repeat"]["channels"]
    run_a = out_root / "run-a"

    def entry(feature_id: str, status: str, evidence: Path | None, measurements: dict[str, Any], note: str,
              reason_class: str | None = None) -> None:
        if status not in ALLOWED_EVIDENCE_STATUS:
            raise ValueError(f"illegal evidence status {status!r}")
        item: dict[str, Any] = {
            "feature_id": feature_id,
            "status": status,
            "target_backend": PLANNER_BACKEND,
            "evidence_file": _rel(evidence) if evidence is not None else None,
            "sha256": file_sha256(evidence) if evidence is not None and evidence.is_file() else None,
            "measurements": measurements,
            "degradation_note": note,
        }
        if reason_class:
            item["reason_class"] = reason_class
        features[feature_id] = item

    sweep = measured["sweep"]
    formal_ratio = measured["formal_line"]["in_range_ratio"]
    sweep_in_range = [row["in_range_ratio"] for row in sweep["entries"] if row["in_range_ratio"] is not None]
    outer_ok = repeat["line_outer"]["bit_exact"] and sweep["parameter_response_passed"]
    all_in_range = formal_ratio == 1.0 and all(r == 1.0 for r in sweep_in_range)
    entry(
        "lines.outer",
        "supported" if outer_ok and all_in_range else ("approximate" if outer_ok else "unsupported"),
        run_a / "line_outer" / "0000.png",
        {
            "computed_by": ["compare_npr_runs", "measure_line_width", "evaluate_width_sweep"],
            "method": "inverted_hull_solidify",
            "line_outer_bit_exact": repeat["line_outer"]["bit_exact"],
            "formal_in_range_ratio": formal_ratio,
            "sweep_parameter_response_passed": sweep["parameter_response_passed"],
            "sweep_in_range_ratios": {row["name"]: row["in_range_ratio"] for row in sweep["entries"]},
            "sweep_modal_widths_px": {row["name"]: row["modal_width_px"] for row in sweep["entries"]},
        },
        "宽度随 width_scale 与 min/max 夹取单调变化；"
        + ("各配置线宽均在各自 [min,max] 内" if all_in_range else "宽线配置下部分像素的实测线宽超出各自 [min,max]（见 sweep_in_range_ratios），故只记 approximate")
        + "；taper 与 distance_falloff 未实现",
    )
    entry(
        "lines.inner",
        "approximate" if repeat["line_inner"]["bit_exact"] and measured["inner_pixels"] > 0 else "unsupported",
        run_a / "line_inner" / "0000.png",
        {
            "computed_by": ["compare_npr_runs", "separate_outer_inner_lines"],
            "method": "part_silhouette_intersection",
            "line_inner_bit_exact": repeat["line_inner"]["bit_exact"],
            "inner_line_pixels_total": measured["inner_pixels"],
        },
        "内线是部件剪影相交处，不是折痕或材质边；宽度未单独测量",
    )
    entry("lines.face", "unsupported", None, {"facial_features_found": False},
          "worker 白模是程序化胶囊体，没有五官网格，无法生成脸线", "measured_unsupported")
    entry("lines.ink", "unsupported", None, {"line_color_override_in_rgb": False},
          "线只出现在线掩码通道，没有合成进 rgb；color_override 没有落点（ink_bold 夹具要求 #000000）", "not_implemented")

    band_rows = measured["bands"]
    band_ok = (
        repeat["band_mask"]["bit_exact"]
        and band_rows
        and all(row["card_basis"]["passed"] for row in band_rows)
    )
    entry(
        "shading.bands",
        "supported" if band_ok else "unsupported",
        run_a / "band_mask" / "0000.png",
        {
            "computed_by": ["compare_npr_runs", "evaluate_band_oracle_agreement"],
            "band_mask_bit_exact": repeat["band_mask"]["bit_exact"],
            "configs": {
                row["run"]: {
                    "style_id": row["style_id"],
                    "bands": row["bands"],
                    "thresholds": row["thresholds"],
                    "card_basis_ratio": row["card_basis"]["agreement_ratio"],
                    "card_basis_evaluated": row["card_basis"]["total_evaluated"],
                    "card_basis_excluded": row["card_basis"]["excluded_boundary_pixels"],
                    "with_transition_band_ratio": row["card_basis"]["with_transition_band"]["agreement_ratio"],
                    "with_transition_band_evaluated": row["card_basis"]["with_transition_band"]["total_evaluated"],
                }
                for row in band_rows
            },
        },
        "离散明暗档位与 CPU 判官在 2 档、3 档及另一组阈值上的一致率（卡面口径与加严口径都已报告）",
    )
    for fid, why in (
        ("shading.cel", "调色板映射没有测量；rgb 里的色值未与档位逐档对照"),
        ("shading.base", "基础自发光底色没有单独测量"),
        ("lighting.basic", "只有一盏平行光的配置值，没有测量灯光行为"),
    ):
        entry(fid, "unsupported", None, {"measured": False}, why, "not_measured")
    entry(
        "lighting.light_groups",
        "approximate" if repeat["acis_partition"]["bit_exact"] else "unsupported",
        run_a / "acis_partition" / "0000.png",
        {
            "computed_by": ["compare_npr_runs"],
            "acis_partition_bit_exact": repeat["acis_partition"]["bit_exact"],
            "partitions": ["Head", "Torso", "Limbs"],
            "partition_pixels_frame0": measured["partition_pixels"],
        },
        "只有按 rig 部件的 ID 分区掩码；没有测量不同灯组对明暗的影响，也没有 receiver / caster / link_mode",
    )
    entry("normals.character_normal", "unsupported", None, {"d5_normal_profile": False},
          "输出的是渲染法线通道，不是 D5 的头部局部空间艺术法线", "not_implemented")
    entry("depth_layers.character_layer", "unsupported", None, {"measured": False},
          "只有对象 ID 掩码，没有深度分层或偏移", "not_implemented")
    entry("shading.cast_vs_self", "unsupported", None, {"native_eevee_split": False},
          "Shader to RGB 只给总辐照度，投影与自身背光无法原生分开", "measured_unsupported")
    entry("normals.facial_normal_proxy", "unsupported", None, {"glb_imported": False},
          "worker 不能导入 heroine_001.glb，没有脸部代理网格", "measured_unsupported")
    entry("depth_layers.see_through_hair", "unsupported", None, {"hair_mesh_found": False},
          "程序化白模没有头发网格", "measured_unsupported")

    return {
        "schema_version": "animeworld.style_v2.feature_evidence.v1",
        "target_backend": PLANNER_BACKEND,
        "round": "r2",
        "style_packages_used": style_ids,
        "non_registry_parameters": {
            "lines.taper": {"status": "unsupported", "note": "单一厚度的反向外壳无法沿笔画收尖，taper 不生效"},
            "lines.distance_falloff": {"status": "unsupported", "note": "未实现随距离变细"},
        },
        "features": features,
    }


def _manifest_file_uris(node: Any) -> list[str]:
    """清单里所有 file_ref 的 uri（带 uri + sha256 + size_bytes 的字典）。"""
    found: list[str] = []
    if isinstance(node, dict):
        if {"uri", "sha256", "size_bytes"} <= set(node):
            found.append(str(node["uri"]))
        for value in node.values():
            found.extend(_manifest_file_uris(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_manifest_file_uris(value))
    return found


def build_planner_probe_package(
    features: list[str], out_root: Path, mode: str = "optional", name: str = "optional_all"
) -> Any:
    """把 day_cel 夹具的 backend_requirements 换成给定特性清单，让 planner 对每个特性给出决定。

    三份夹具的 backend_requirements 都是空的，planner 对它们返回 0 条决定；要看它对具体特性怎么判，
    只能提出具体要求。探针是自包含的：把清单引用的文件按原相对路径复制到探针根目录（字节不变，
    sha256 照旧），清单里只改 backend_requirements。
    """
    if mode not in ("optional", "required"):
        raise ValueError(mode)
    base = json.loads((ROOT / STYLE_FIXTURE_DIR / "day_cel" / "style.v2.json").read_text(encoding="utf-8"))
    required = [{"feature": f, "backends": [PLANNER_BACKEND]} for f in features]
    optional = [{"feature": f, "backends": [PLANNER_BACKEND], "allow_approximate": False} for f in features]
    base["backend_requirements"] = {
        "required": required if mode == "required" else [],
        "optional": optional if mode == "optional" else [],
    }
    probe_root = out_root / "planner_probe" / name
    probe_root.mkdir(parents=True, exist_ok=True)
    for uri in sorted(set(_manifest_file_uris(base))):
        dest = probe_root / uri
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / uri, dest)
    (probe_root / "style.v2.json").write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
    return load_style_v2_package(package_root=probe_root, manifest_filename="style.v2.json")


def planner_required_probe(feature: str, out_root: Path) -> dict[str, Any]:
    """若风格包把该特性列为 required，planner 现在会怎样（通常是 REQUIRED_FEATURE_UNSUPPORTED）。"""
    pkg = build_planner_probe_package([feature], out_root, "required", "required_" + feature.replace(".", "_"))
    try:
        plan = plan_backend_capabilities(pkg, PLANNER_BACKEND)
    except StyleV2CapabilityError as exc:
        return {"outcome": "rejected", "code": exc.code}
    return {"outcome": "planned", "decisions": [{k: d.get(k) for k in ("feature", "status", "decision")} for d in plan.decisions]}


def verify_feature_evidence_against_planner(
    evidence_data: dict[str, Any],
    pkg: Any | None = None,
    plan_fn: Any = plan_backend_capabilities,
    backend: str = PLANNER_BACKEND,
) -> dict[str, Any]:
    """真实调用 planner，并把证据文件放在它的决定旁边对照。

    planner 的证据表 ``FEATURE_BACKEND_EVIDENCE`` 是代码里的常量，不读外部证据文件；
    因此这里的结论是「planner 现在怎么判」加「若要增补，建议增补哪些」，不是「planner 接受了本证据」。
    ``valid`` 只表示：planner 确实被调用并返回了决定，且证据文件自身结构合法。
    """
    problems: list[str] = []
    features = evidence_data.get("features")
    if not isinstance(features, dict) or not features:
        problems.append("evidence has no features")
        features = {}
    for fid, item in features.items():
        if item.get("status") not in ALLOWED_EVIDENCE_STATUS:
            problems.append(f"{fid}: illegal status {item.get('status')!r}")
        if item.get("status") in ("supported", "approximate"):
            m = item.get("measurements") or {}
            if not m.get("computed_by"):
                problems.append(f"{fid}: {item.get('status')} without measurements.computed_by")
            if not item.get("sha256"):
                problems.append(f"{fid}: {item.get('status')} without evidence file sha256")

    if pkg is None:
        pkg, _plan = load_style_package_authoritative()
    plan = plan_fn(pkg, backend)
    decisions = getattr(plan, "decisions", None)
    planner_called = isinstance(decisions, list) and len(decisions) > 0
    if not planner_called:
        problems.append("planner returned no decisions (call was a no-op or failed)")
        decisions = []

    by_feature = {d["feature"]: d for d in decisions}
    registry_hits = [fid for fid in features if fid in KNOWN_FEATURE_REGISTRY]
    planner_supported = sorted(
        fid for fid in registry_hits if by_feature.get(fid, {}).get("status") == "supported"
    )
    proposed = [
        {
            "feature": fid,
            "backend": backend,
            "evidence_ref": f"P3-D2:r2:{features[fid].get('sha256')}",
            "evidence_status": features[fid]["status"],
        }
        for fid in sorted(features)
        if fid in KNOWN_FEATURE_REGISTRY and features[fid].get("status") == "supported"
    ]
    return {
        "valid": planner_called and not problems,
        "problems": problems,
        "planner_called": planner_called,
        "planner_plan_id": getattr(plan, "plan_id", None),
        "planner_decisions": [
            {k: d.get(k) for k in ("feature", "kind", "status", "decision", "note")} for d in decisions
        ],
        "planner_evidence_table_size": len(FEATURE_BACKEND_EVIDENCE),
        "evidence_features_in_planner_registry": sorted(registry_hits),
        "planner_marks_supported": planner_supported,
        "proposed_feature_backend_evidence_additions": proposed,
        "note": "增补 FEATURE_BACKEND_EVIDENCE 需要改 planner.py，属另一张 CPU 卡，本卡不改",
    }


def count_white_pixels(png_path: Path, threshold: int = 128) -> int:
    """掩码里亮于阈值的像素数（红通道）。"""
    w, h, rows = read_png_rgb8(png_path)
    return sum(1 for y in range(h) for x in range(w) if rows[y][x * 3] > threshold)


def count_nonblack_pixels(png_path: Path) -> int:
    w, h, rows = read_png_rgb8(png_path)
    return sum(1 for y in range(h) for x in range(w) if any(rows[y][x * 3 : x * 3 + 3]))


def aggregate_band_oracle(
    run_dir: Path, bands: int, thresholds: list[float], frames: int = 8
) -> dict[str, Any]:
    """八帧合计的判官一致率（卡面口径为顶层，加严口径在 ``with_transition_band``）。"""
    per_frame = []
    card = collections.Counter()
    strict = collections.Counter()
    mismatches: list[dict[str, Any]] = []
    for f in range(frames):
        r = evaluate_band_oracle_agreement(
            run_dir / "band_mask" / f"{f:04d}.png",
            run_dir / "normal" / f"{f:04d}.png",
            run_dir / "object_id" / f"{f:04d}.png",
            bands=bands,
            thresholds=thresholds,
        )
        per_frame.append({"frame": f, "agreement_ratio": r["agreement_ratio"], "total_evaluated": r["total_evaluated"]})
        card.update(matching=r["matching"], evaluated=r["total_evaluated"], excluded=r["excluded_boundary_pixels"])
        s = r["with_transition_band"]
        strict.update(matching=s["matching"], evaluated=s["total_evaluated"], excluded=s["excluded_pixels"])
        mismatches.extend(dict(m, frame=f) for m in r["mismatch_samples"])

    def ratio(c: collections.Counter) -> float:
        return round(c["matching"] / c["evaluated"], 6) if c["evaluated"] else 0.0

    card_ratio = ratio(card)
    return {
        "bands": bands,
        "thresholds": thresholds,
        "matching": card["matching"],
        "total_evaluated": card["evaluated"],
        "excluded_boundary_pixels": card["excluded"],
        "agreement_ratio": card_ratio,
        "min_threshold": BAND_ORACLE_AGREEMENT_MIN,
        "passed": card["evaluated"] > 0 and card_ratio >= BAND_ORACLE_AGREEMENT_MIN,
        "mismatch_samples": mismatches[:10],
        "per_frame": per_frame,
        "with_transition_band": {
            "matching": strict["matching"],
            "total_evaluated": strict["evaluated"],
            "excluded_pixels": strict["excluded"],
            "agreement_ratio": ratio(strict),
        },
    }


def aggregate_line_widths(
    run_dir: Path, min_width_px: float, max_width_px: float, frames: int = 8
) -> dict[str, Any]:
    """八帧合计的外轮廓线宽分布（对 ``line_outer`` 实测）。"""
    dist: collections.Counter[int] = collections.Counter()
    out_of_range: list[dict[str, Any]] = []
    for f in range(frames):
        r = measure_line_width(run_dir / "line_outer" / f"{f:04d}.png", min_width_px, max_width_px)
        for w_val, cnt in r["distribution"].items():
            dist[int(w_val)] += cnt
        out_of_range.extend(dict(o, frame=f) for o in r["out_of_range"][:5])
    total = sum(dist.values())
    in_range = sum(c for w_val, c in dist.items() if min_width_px <= w_val <= max_width_px)
    return {
        "total_line_pixels": total,
        "in_range_pixels": in_range,
        "in_range_ratio": round(in_range / total, 6) if total else 1.0,
        "min_width_px": min_width_px,
        "max_width_px": max_width_px,
        "distribution": dict(sorted(dist.items())),
        "modal_width_px": modal_width(dict(dist)),
        "out_of_range_samples": out_of_range[:10],
        "passed": (in_range / total if total else 1.0) >= LINE_WIDTH_IN_RANGE_RATIO_MIN,
    }


STYLE_FIXTURE_DIR = "reports/P3-D1/formalization/examples"
#: 运行计划：(运行名, 风格夹具, 覆盖项, 用途)。覆盖项都写进该运行的 config.json，报告里原样列出。
RUN_PLAN: tuple[tuple[str, str, dict[str, float], str], ...] = (
    ("run-a", "day_cel", {}, "formal"),
    ("run-b", "day_cel", {}, "formal-repeat"),
    ("dusk_soft-3band", "dusk_soft", {}, "bands-3"),
    ("ink_bold-0.15", "ink_bold", {}, "bands-2-other-threshold"),
    ("sweep-scale2.0", "day_cel", {"width_scale": 2.0}, "width-sweep"),
    ("sweep-scale3.0", "day_cel", {"width_scale": 3.0}, "width-sweep"),
    ("sweep-scale3.0-max2.0", "day_cel", {"width_scale": 3.0, "max_width_px": 2.0}, "width-clamp-max"),
    ("sweep-scale0.3-min1.0", "day_cel", {"width_scale": 0.3}, "width-clamp-min"),
)


def _run_slice(name: str, config: dict[str, Any], take_blend: Path, payload_file: Path, out_root: Path) -> dict[str, Any]:
    run_dir = out_root / name
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = run_dir / "config.json"
    cfg_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    cmd = [
        str(BLENDER_BIN), "-b", str(take_blend.resolve()), "--python", str(NPR_SLICE_SCRIPT.resolve()), "--",
        "--scene-blend", str(take_blend.resolve()), "--payload", str(payload_file.resolve()),
        "--out-dir", str(run_dir.resolve()), "--config", str(cfg_file.resolve()),
    ]
    t0 = time.monotonic()
    start_iso = datetime.now(UTC).isoformat()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
    wall = round(time.monotonic() - t0, 3)
    end_iso = datetime.now(UTC).isoformat()
    if proc.returncode != 0:
        raise RuntimeError(f"Blender NPR slice failed ({name}):\n{proc.stderr}\n{proc.stdout}")
    res_file = run_dir / "npr_slice_result.json"
    result = json.loads(res_file.read_text(encoding="utf-8"))
    return {
        "run": name,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "wall_s": wall,
        "returncode": proc.returncode,
        "artifact_sha256": {
            "npr_slice_result.json": file_sha256(res_file),
            "config.json": file_sha256(cfg_file),
        },
        "slice_result": result,
    }


def execute(
    out_root: Path | None = None,
    take_blend_path: Path | None = None,
    new_call_limit: int = 12,
    new_wall_limit_s: float = 600.0,
    reuse_runs_from_metrics: Path | None = None,
) -> dict[str, Any]:
    """P3-D2 r2：守卫、八次无头运行、从产物重算全部指标、真实调用 planner、产出逐特性证据。

    r2 的输出写到 ``reports/P3-D2/r2``，不覆盖 r1 的任何文件。
    ``reuse_runs_from_metrics`` 给定时不再起 Blender：读取先前那次运行留下的指标文件里的调用记录，
    只重新跑 CPU 侧的全部分析（用于修正分析代码而不多耗 Blender 预算）。
    """
    out_root = out_root or (ROOT / "reports/P3-D2/r2")
    t_start = time.monotonic()
    out_root.mkdir(parents=True, exist_ok=True)
    sha_start = verify_frozen_inputs(ROOT)
    guards = check_power_and_blender_guards()

    pkgs = {
        name: load_style_package_authoritative(f"{STYLE_FIXTURE_DIR}/{name}/style.v2.json", ROOT)[0]
        for name in ("day_cel", "dusk_soft", "ink_bold")
    }
    style_params = {name: style_params_from_package(pkg, ROOT) for name, pkg in pkgs.items()}

    take_blend_path = take_blend_path or (ROOT / "reports/P3-A3/r5/run-a/take.blend")
    if not take_blend_path.is_file():
        raise RuntimeError(f"A3 验收 take.blend 不存在: {take_blend_path}")
    scene_sha = file_sha256(take_blend_path)
    payload = {"engine_enum": "BLENDER_EEVEE", "resolution": list(RESOLUTION), "frames": [{"frame": i} for i in range(8)]}
    payload_file = out_root / "payload.json"
    payload_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    invocations: list[dict[str, Any]] = []
    run_configs: dict[str, dict[str, Any]] = {}
    prior = {}
    if reuse_runs_from_metrics is not None:
        prior = {i["run"]: i for i in json.loads(reuse_runs_from_metrics.read_text(encoding="utf-8"))["blender_invocations"]}
    for name, style_name, overrides, purpose in RUN_PLAN:
        if len(invocations) >= new_call_limit:
            raise RuntimeError("超出登记的 Blender 调用预算，停手")
        if sum(i["wall_s"] for i in invocations) > new_wall_limit_s:
            raise RuntimeError("超出登记的渲染墙钟预算，停手")
        cfg = {**style_params[style_name], **overrides}
        if name in prior:
            res_file = out_root / name / "npr_slice_result.json"
            cfg_file = out_root / name / "config.json"
            if json.loads(cfg_file.read_text(encoding="utf-8")) != json.loads(json.dumps(cfg)):
                raise RuntimeError(f"复用的运行 {name} 的 config 与当前计划不符")
            inv = {k: v for k, v in prior[name].items() if k not in ("purpose", "style_fixture", "overrides")}
            inv["artifact_sha256"] = {"npr_slice_result.json": file_sha256(res_file), "config.json": file_sha256(cfg_file)}
            inv["slice_result"] = json.loads(res_file.read_text(encoding="utf-8"))
            inv["reused_from_earlier_invocation"] = True
        else:
            inv = _run_slice(name, cfg, take_blend_path, payload_file, out_root)
        inv["purpose"] = purpose
        inv["style_fixture"] = style_name
        inv["overrides"] = overrides
        invocations.append(inv)
        run_configs[name] = cfg

    run_a, run_b = out_root / "run-a", out_root / "run-b"
    repeat = compare_npr_runs(run_a, run_b, frames=8)

    band_rows = []
    for name in ("run-a", "dusk_soft-3band", "ink_bold-0.15"):
        cfg = run_configs[name]
        agg = aggregate_band_oracle(out_root / name, cfg["bands"], cfg["band_thresholds"])
        band_rows.append(
            {"run": name, "style_id": cfg["style_id"], "bands": cfg["bands"],
             "thresholds": cfg["band_thresholds"], "card_basis": agg}
        )

    sweep_entries = []
    sweep_runs = {}
    for name in ("run-a", "sweep-scale2.0", "sweep-scale3.0", "sweep-scale3.0-max2.0", "sweep-scale0.3-min1.0"):
        inv = next(i for i in invocations if i["run"] == name)
        cfg_res = inv["slice_result"]["config"]
        agg = aggregate_line_widths(out_root / name, cfg_res["min_width_px"], cfg_res["max_width_px"])
        sweep_runs[name] = {"config": cfg_res, "line_outer_widths": agg}
        sweep_entries.append(
            {"name": name, "target_width_px": cfg_res["target_width_px"],
             "distribution": agg["distribution"], "in_range_ratio": agg["in_range_ratio"]}
        )
    sweep = evaluate_width_sweep(sweep_entries)
    formal_line = sweep_runs["run-a"]["line_outer_widths"]

    inner_pixels = sum(count_white_pixels(run_a / "line_inner" / f"{f:04d}.png") for f in range(8))
    partition_pixels = count_nonblack_pixels(run_a / "acis_partition" / "0000.png")

    measured = {
        "repeat": repeat,
        "bands": band_rows,
        "sweep": sweep,
        "formal_line": formal_line,
        "inner_pixels": inner_pixels,
        "partition_pixels": partition_pixels,
    }
    evidence = generate_feature_evidence(out_root, sorted(pkgs), measured)
    (out_root / "feature_evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    registry_feats = sorted(f for f in evidence["features"] if f in KNOWN_FEATURE_REGISTRY)
    probe_pkg = build_planner_probe_package(registry_feats, out_root, "optional", "optional_all")
    planner_check = verify_feature_evidence_against_planner(evidence, probe_pkg)
    claimed = [f for f in registry_feats if evidence["features"][f]["status"] in ("supported", "approximate")]
    planner_check["required_probe"] = {f: planner_required_probe(f, out_root) for f in claimed}
    (out_root / "planner_check.json").write_text(
        json.dumps(planner_check, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    sha_end = verify_frozen_inputs(ROOT)
    wall_total = round(sum(i["wall_s"] for i in invocations), 3)
    summary = {
        "task": "awz.P3.D2",
        "round": "r2",
        "scene_blend_sha256": scene_sha,
        "guards": guards,
        "resolution": list(RESOLUTION),
        "frames": 8,
        "blender_calls": {"r1": 3, "r2_new": len(invocations), "r2_new_limit": new_call_limit, "total_limit": 24},
        "render_wall_s_r2": wall_total,
        "render_wall_limit_s_r2": new_wall_limit_s,
        "within_budget": len(invocations) <= new_call_limit and wall_total <= new_wall_limit_s,
        "candidate_gates": {
            "repeat_runs_bit_exact_pixels": {
                ch: repeat["channels"][ch]["bit_exact"]
                for ch in ("line_mask", "line_outer", "line_inner", "band_mask", "object_id", "acis_partition", "normal")
            },
            "repeat_gate_passed": repeat["gated_bit_exact"],
            "band_oracle_card_basis": {
                row["run"]: {
                    "ratio": row["card_basis"]["agreement_ratio"],
                    "evaluated": row["card_basis"]["total_evaluated"],
                    "excluded": row["card_basis"]["excluded_boundary_pixels"],
                    "with_transition_band_ratio": row["card_basis"]["with_transition_band"]["agreement_ratio"],
                    "with_transition_band_evaluated": row["card_basis"]["with_transition_band"]["total_evaluated"],
                    "passed": row["card_basis"]["passed"],
                }
                for row in band_rows
            },
            "line_width_formal_in_range": {"ratio": formal_line["in_range_ratio"], "passed": formal_line["passed"]},
            "line_width_sweep": sweep,
        },
        "rgb_repeat": repeat["rgb"],
        "sweep_runs": sweep_runs,
        "band_oracle": band_rows,
        "planner_check": {k: planner_check[k] for k in ("valid", "planner_called", "planner_plan_id",
                                                        "planner_evidence_table_size", "planner_marks_supported")},
        "frozen_sha256": {"start": sha_start, "end": sha_end, "verified": sha_start == sha_end},
        "blender_invocations": [{k: v for k, v in i.items() if k != "slice_result"} for i in invocations],
        "runs": [
            {"run": i["run"], "peak_memory_mb": i["slice_result"].get("peak_memory_mb"),
             "window_count": i["slice_result"].get("window_count"), "background": i["slice_result"].get("background"),
             "taper_applied": i["slice_result"]["config"].get("taper_applied")}
            for i in invocations
        ],
        "total_wall_s_including_cpu": round(time.monotonic() - t_start, 3),
    }
    (out_root / "指标.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    execute()


if __name__ == "__main__":
    main()
