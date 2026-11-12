"""S5 冻结前运行器：smoke、probe、dev-tune、dev-distill。

真实的 probe / dev-tune / dev-distill 不由本卡启动。``--dry-run`` 只打印格清单，不拿锁、不训练。
smoke 在临时目录物化 ``s5test-smoke-*``，不读 ``s5p1-pool/lab/dev``，不记 dev 使用次数。
本运行器不生成、不读取 ``s5p1-final`` 与 ``s5p1-final-shift``。

启动顺序：先拿 ``artifacts/locks/m0-worker.lock``，再检查字节码与 git，然后才写 ``events.jsonl``。
锁被占时退出码 75，且不写运行目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import resource
import sys
import time
from pathlib import Path
from typing import Callable

STARTED = time.time()

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from ainerzero.v9.experiments.s3 import run_guard as GD
from ainerzero.v9.experiments.s5.data import ClipIndex
from ainerzero.v9.experiments.s5.materialize import materialize_partition
from ainerzero.v9.experiments.s5.world import PARTITIONS, REGISTERED

import plan_s5p1 as plan

LOCK = REPO / "artifacts/locks/m0-worker.lock"
RUNS = REPO / "artifacts/v9/s5/runs"
LEDGER = REPO / "artifacts/v9/s5/dev-uses.json"
DATA_ROOT = REPO / "artifacts/v9/s5/data"
TEACHERS = REPO / "artifacts/v9/s5/teachers"
DEV_MAX_USES = 8
LAB_SUBSET_SEED = 20261112
CELL_LIMIT_S = 45 * 60
STAGE_LIMIT_S = {
    "smoke": 15 * 60,
    "probe": int(1.5 * 3600),
    # Raised after probe-20261112c measured real step times; user approved a 22 h lock budget on 2026-11-12
    # (design r1 implementation-stage addendum 6).
    "dev-tune": 3 * 3600,
    "dev-distill": 8 * 3600,
    # dev-tune measured 0.27-0.40 s/step and stops at its 3 h limit before finishing the eta cells; the user
    # approved about one more hour on 2026-11-12 ("追加 1 小时调 η"). dev-tune-b reads out the two distill-lr
    # candidates on dev (dev-tune trained them but never evaluated them) and re-runs the missing eta cells.
    "dev-tune-b": 1 * 3600,
}
# Stages that read the dev-tune result, and the tune keys each one needs.
TUNE_KEYS = {
    "dev-distill": ("distill_lr", "supervised_lr"),
    "dev-tune-b": ("supervised_lr",),
}
SMOKE_PARTITIONS = {
    "pool": "s5test-smoke-pool",
    "lab": "s5test-smoke-lab",
    "dev": "s5test-smoke-dev",
}
SMOKE_WORLDS = {"pool": 2, "lab": 2, "dev": 1}
SMOKE_CLIPS = (0, 1)
SMOKE_STUDENT = {"d": 16, "depth": 1, "heads": 1}
REAL_PARTITIONS = {"pool": "s5p1-pool", "lab": "s5p1-lab", "dev": "s5p1-dev"}
# Teacher features are extracted per partition: teachers/<teacher>/<partition>/world_XXXX/...
# (extract_teachers.py --out artifacts/v9/s5/teachers/<teacher>/<partition>; tier-1 fix 11-12).
REAL_TEACHERS = {
    "pool": {"vjepa": TEACHERS / "vjepa" / "s5p1-pool", "da2": TEACHERS / "da2" / "s5p1-pool"},
    "lab": {"vjepa": TEACHERS / "vjepa" / "s5p1-lab"},
}


def _preflight_real_inputs() -> None:
    """Every real data partition and teacher directory must exist with a manifest before a dev use is spent."""
    missing = []
    for name in REAL_PARTITIONS.values():
        d = DATA_ROOT / name
        if not (d / "manifest.json").is_file() or not any(d.glob("world_*/clip_*.npy")):
            missing.append(str(d))
    for group in REAL_TEACHERS.values():
        for teacher, d in group.items():
            pattern = "world_*/clip_*.vjepa.npy" if teacher == "vjepa" else "world_*/da2_*.da2.npy"
            if not (d / "manifest.json").is_file() or not any(d.glob(pattern)):
                missing.append(str(d))
    if missing:
        raise GD.GuardError("preflight: missing real inputs: " + "; ".join(missing))
FORBIDDEN = tuple(sorted(REGISTERED))
THIRD_PARTY = ("numpy", "mlx")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cell_limit_seconds(cell_index: int) -> float:
    return float(CELL_LIMIT_S)


def _rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return float(rss) / (1024.0 * 1024.0)
    return float(rss) / 1024.0


def _json_default(value):
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value))


def _append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


def _refuse_final(name: str) -> None:
    if str(name).startswith("s5p1-final"):
        raise GD.GuardError(f"this runner must not touch a final partition: {name}")


def smoke_cells() -> list[dict]:
    """每个臂 2 步。蒸馏臂再各训 2 步读出头，评测才有 R1/R2/R3。"""
    pool_n = SMOKE_WORLDS["pool"] * len(SMOKE_CLIPS)
    lab_n = SMOKE_WORLDS["lab"] * len(SMOKE_CLIPS)
    batch = 2
    cells = []
    for arm in plan.ARM_ORDER:
        cells.append({
            "cell_id": f"smoke-distill-{arm}", "kind": "distill", "arm": arm, "seed": 0,
            "lr": 1e-3, "epochs": 1, "batch_size": batch, "n_clips": pool_n, "steps": 2,
            "partition": SMOKE_PARTITIONS["pool"],
        })
        cells.append({
            "cell_id": f"smoke-heads-{arm}", "kind": "heads", "arm": arm, "seed": 0,
            "distill_seed": 0, "readout_seed": 0, "lr": 1e-3, "epochs": 1, "batch_size": batch,
            "n_clips": lab_n, "steps": 2, "partition": SMOKE_PARTITIONS["lab"],
        })
    cells.append({
        "cell_id": "smoke-A0", "kind": "supervised", "arm": "A0", "seed": 0, "lr": 1e-3,
        "epochs": 1, "batch_size": batch, "n_clips": lab_n, "steps": 2,
        "partition": SMOKE_PARTITIONS["lab"],
    })
    cells.append({
        "cell_id": "smoke-A4", "kind": "supervised", "arm": "A4", "seed": 0, "lr": 1e-3,
        "eta": 0.5, "epochs": 1, "batch_size": batch, "n_clips": lab_n, "steps": 2,
        "partition": SMOKE_PARTITIONS["lab"],
    })
    cells.append({
        "cell_id": "smoke-A0R", "kind": "supervised", "arm": "A0-R", "seed": 0, "lr": 1e-3,
        "tau": 0.02, "epochs": 1, "batch_size": batch, "n_clips": lab_n, "steps": 2,
        "partition": SMOKE_PARTITIONS["lab"],
    })
    for cell in cells:
        _refuse_final(cell["partition"])
        if not str(cell["partition"]).startswith("s5test-smoke-"):
            raise GD.GuardError(f"smoke cell left the smoke namespace: {cell['partition']}")
    return cells


def _parse_etas(text) -> tuple[float, ...]:
    """``--etas 0.5,1.0`` -> 设计网格内、无重复的 η 元组；不合法时抛 GuardError。"""
    if text is None or not str(text).strip():
        raise GD.GuardError("dev-tune-b needs --etas (comma-separated values from the design grid)")
    try:
        values = [float(part) for part in str(text).split(",") if part.strip()]
        return plan.eta_values(values)
    except ValueError as exc:
        raise GD.GuardError(f"invalid --etas {text!r}: {exc}") from None


def _require_tune_keys(stage: str, tune: dict) -> None:
    missing = [key for key in TUNE_KEYS[stage] if key not in tune]
    if missing:
        raise GD.GuardError(f"dev-tune result lacks {missing} needed by {stage}")
    for key in TUNE_KEYS[stage]:
        value = tune[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value) > 0.0:
            raise GD.GuardError(f"dev-tune result {key}={value!r} is not a positive number")


def resolve_tune_students(run_dir, cells: list[dict], *, runs_root: Path) -> list[dict]:
    """给 ``student_cell`` 格补上 dev-tune 运行里该学生权重的路径与 SHA；登记、文件或 SHA 不符就抛 GuardError。

    只读：要求 ``run_dir`` 在 ``runs_root`` 之下、是一次 dev-tune 运行，且学生文件的 SHA 与该运行 cell_end 的登记一致。
    """
    needed = [cell for cell in cells if cell.get("student_cell")]
    if not needed:
        return cells
    if run_dir is None:
        raise GD.GuardError("dev-tune-b needs --tune-run (the dev-tune run directory)")
    run = Path(run_dir).resolve()
    root = Path(runs_root).resolve()
    if root not in run.parents:
        raise GD.GuardError(f"--tune-run must be a run directory under {root}: {run}")
    events_path = run / "events.jsonl"
    if not events_path.is_file():
        raise GD.GuardError(f"--tune-run has no events.jsonl: {run}")
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    starts = [e for e in events if e.get("event") == "stage_start"]
    if len(starts) != 1 or starts[0].get("stage") != "dev-tune":
        raise GD.GuardError(f"--tune-run is not a dev-tune run: {run}")
    registered: dict[str, str] = {}
    for event in events:
        if event.get("event") == "cell_end":
            for name, sha in (event.get("files") or {}).items():
                registered[name] = sha
    out = []
    for cell in cells:
        if not cell.get("student_cell"):
            out.append(cell)
            continue
        name = f"{cell['student_cell']}-student.npz"
        if name not in registered:
            raise GD.GuardError(f"dev-tune run did not finish {cell['student_cell']} (no {name} in cell_end)")
        path = run / "weights" / name
        if not path.is_file():
            raise GD.GuardError(f"student weights missing: {path}")
        got = sha256_file(path)
        if got != registered[name]:
            raise GD.GuardError(f"student weights SHA mismatch for {name}: got {got} != {registered[name]}")
        out.append(dict(cell, student_file=str(path), student_sha=got))
    return out


def stage_cells_with_tune(stage: str, tune: dict | None, etas=None) -> list[dict]:
    """真实阶段的格清单；带 tune 时，蒸馏格用 distill_lr，其余格用 supervised_lr。"""
    kwargs = {"etas": etas} if stage == "dev-tune-b" else {}
    cells = plan.stage_cells(
        stage,
        pool_worlds=int(PARTITIONS["s5p1-pool"]),
        lab_worlds=int(PARTITIONS["s5p1-lab"]),
        **kwargs,
    )
    if tune is not None:
        for cell in cells:
            key = "distill_lr" if cell["kind"] == "distill" else "supervised_lr"
            cell["lr"] = float(tune[key])
    return cells


def dry_run_plan(stage: str, etas=None) -> dict:
    if stage == "smoke":
        cells = smoke_cells()
        return {
            "stage": "smoke",
            "dry_run": True,
            "takes_lock": False,
            "dev_uses": 0,
            "student": SMOKE_STUDENT,
            "note": "smoke 只用 s5test-smoke-* 和 d=16、深 1 的学生，每臂 2 步，用来把管线跑通。",
            "n_cells": len(cells),
            "steps": int(sum(cell["steps"] for cell in cells)),
            "limit_s": STAGE_LIMIT_S["smoke"],
            "cells": cells,
        }
    cells = stage_cells_with_tune(stage, None, etas)
    for cell in cells:
        _refuse_final(cell["partition"])
    summary = plan.summarize_stage(stage, cells)
    summary["dry_run"] = True
    summary["takes_lock"] = False
    summary["dev_uses"] = 1
    summary["limit_s"] = STAGE_LIMIT_S[stage]
    summary["cell_limit_s"] = CELL_LIMIT_S
    summary["lab_subset_seed"] = LAB_SUBSET_SEED
    summary["note"] = (
        "probe 的轮数按设计步数的 1/10 取整，至少 1 轮。"
        "dev-tune 的蒸馏学习率用 A2、约 1/4 步数；监督学习和 η 用设计轮数。"
        "η 的学习率要等监督调参选出，dry-run 里记为 null。"
        "带 label_n 的格子按 LAB_SUBSET_SEED=20261112 取 4/32/128 个世界的嵌套子集。"
        "逐步墙钟按 probe 实测每步计算时间（约 0.16 s，批量 8）加进程内缓存后的读数据估算，另附设计 §6 的整段对照。"
    )
    return summary


def _manifest() -> dict[str, str]:
    entries = [
        Path(__file__).resolve(),
        REPO / "src/ainerzero/v9/experiments/s5/train.py",
        REPO / "src/ainerzero/v9/experiments/s5/evaluate.py",
        REPO / "src/ainerzero/v9/experiments/s5/data.py",
        REPO / "src/ainerzero/v9/experiments/s5/metrics.py",
        REPO / "src/ainerzero/v9/experiments/s5/tokens.py",
    ]
    return GD.build_manifest(REPO, entries, src_root=REPO / "src")


def _write_fake_teachers(index: ClipIndex, root: Path) -> dict[str, str]:
    """确定性 fp16 教师特征，并写 progress.jsonl。不调用教师模型。"""
    vjepa_root = root / "vjepa"
    da2_root = root / "da2"
    ledgers = {vjepa_root: [], da2_root: []}
    for i in range(len(index)):
        world, clip = index[i]
        rng = np.random.default_rng(10_000 + world * 100 + clip)
        vjepa = rng.standard_normal((1568, 1024)).astype(np.float16)
        da2 = rng.standard_normal((8, 56, 56)).astype(np.float16)
        v_rel = f"world_{world:04d}/clip_{clip:02d}.vjepa.npy"
        d_rel = f"world_{world:04d}/da2_{clip:02d}.da2.npy"
        v_path = vjepa_root / v_rel
        d_path = da2_root / d_rel
        v_path.parent.mkdir(parents=True, exist_ok=True)
        d_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(v_path, vjepa)
        np.save(d_path, da2)
        ledgers[vjepa_root].append({"file": v_rel, "sha256": sha256_file(v_path)})
        ledgers[da2_root].append({"file": d_rel, "sha256": sha256_file(d_path)})
    for folder, rows in ledgers.items():
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        (folder / "progress.jsonl").write_text(text, encoding="utf-8")
    return {"vjepa": str(vjepa_root), "da2": str(da2_root)}


def _save_weights(module, path: Path) -> str:
    import mlx.core as mx
    from mlx.utils import tree_flatten

    path.parent.mkdir(parents=True, exist_ok=True)
    flat = dict(tree_flatten(module.parameters()))
    mx.savez(str(path), **flat)
    return sha256_file(path)


def _data_fraction(log: dict) -> float | None:
    rows = log.get("step_logs") or []
    data_s = sum(float(row.get("data_s", 0.0)) for row in rows)
    step_s = sum(float(row.get("step_s", 0.0)) for row in rows)
    total = data_s + step_s
    if total <= 0:
        return None
    return float(data_s / total)


def _index_for(partition_dir: Path, clips, *, label_n: int | None = None) -> ClipIndex:
    if label_n is not None:
        return ClipIndex(partition_dir).subset_by_worlds(
            plan.L_WORLDS[int(label_n)], seed=LAB_SUBSET_SEED
        )
    return ClipIndex(partition_dir, clips=clips)


def _execute_cell_body(cell: dict, ctx: dict) -> dict:
    import mlx.core as mx

    from ainerzero.v9.experiments.s5.evaluate import evaluate
    from ainerzero.v9.experiments.s5.student import Student
    from ainerzero.v9.experiments.s5.train import TrainConfig, distill, train_heads, train_supervised

    kind = cell["kind"]
    smoke = ctx["stage"] == "smoke"
    clips = SMOKE_CLIPS if smoke else None
    index = _index_for(ctx["dirs"][cell["partition"]], clips, label_n=cell.get("label_n"))
    student_kw = SMOKE_STUDENT if smoke else {}
    weights_dir = ctx["weights"]
    metrics_dir = ctx["metrics"]
    cfg = TrainConfig(
        lr=float(cell.get("lr") or 1e-3),
        batch_size=int(cell["batch_size"]),
        epochs=int(cell["epochs"]),
        seed=int(cell["seed"]),
        eta=cell.get("eta"),
        tau=cell.get("tau"),
        ckpt_dir=weights_dir / cell["cell_id"],
    )
    t0 = time.perf_counter()
    files: dict[str, str] = {}
    keep_rate = None
    if kind == "distill":
        student = Student(**student_kw)
        student, heads, log = distill(cell["arm"], index, ctx["teachers"], cfg, student=student)
        files[f"{cell['cell_id']}-student.npz"] = _save_weights(student, weights_dir / f"{cell['cell_id']}-student.npz")
        files[f"{cell['cell_id']}-heads.npz"] = _save_weights(heads, weights_dir / f"{cell['cell_id']}-heads.npz")
    elif kind == "heads":
        arm = cell["arm"]
        stage = ctx["stage"]
        if cell.get("student_file"):
            student_file = Path(cell["student_file"])
            if not student_file.is_file() or sha256_file(student_file) != cell.get("student_sha"):
                raise GD.GuardError(f"student weights changed since the stage started: {student_file}")
        elif stage == "smoke":
            student_file = weights_dir / f"smoke-distill-{arm}-student.npz"
        elif stage == "probe":
            student_file = weights_dir / f"probe-distill-{arm}-s0-student.npz"
        elif stage == "dev-distill":
            distill_seed = cell.get("distill_seed", 0)
            student_file = weights_dir / f"distill-{arm}-s{distill_seed}-student.npz"
        else:
            student_file = weights_dir / f"distill-{arm}-student.npz"
        if not student_file.is_file():
            raise GD.GuardError(f"student weights file missing: {student_file}")
        student = Student(**student_kw)
        student.load_weights(str(student_file))
        heads, log = train_heads(student, index, cfg)
        files[f"{cell['cell_id']}.npz"] = _save_weights(heads, weights_dir / f"{cell['cell_id']}.npz")
    elif kind == "supervised":
        student = Student(**student_kw)
        teachers = ctx["teachers"] if cell.get("eta") is not None else None
        student, heads, log = train_supervised(index, cfg, teachers=teachers, student=student)
        files[f"{cell['cell_id']}-student.npz"] = _save_weights(student, weights_dir / f"{cell['cell_id']}-student.npz")
        files[f"{cell['cell_id']}-heads.npz"] = _save_weights(heads, weights_dir / f"{cell['cell_id']}-heads.npz")
    else:
        raise GD.GuardError(f"unknown cell kind {kind!r}")

    eval_index_name = SMOKE_PARTITIONS["dev"] if smoke else REAL_PARTITIONS["dev"]
    eval_dir = ctx["dirs"][eval_index_name]
    if kind == "heads":
        ev = evaluate(student, heads, _index_for(eval_dir, clips), tau=cell.get("tau"))
        keep_rate = ev["metrics"].get("keep_rate")
        (metrics_dir / f"{cell['cell_id']}.json").write_text(
            json.dumps({
                "r2_ap": ev["metrics"]["r2_ap"], "keep_rate": keep_rate,
                "lr": cell.get("lr"), "role": cell.get("role"), "arm": cell.get("arm"),
                "distill_seed": cell.get("distill_seed"), "readout_seed": cell.get("readout_seed"),
                "label_n": cell.get("label_n"), "distill_lr": cell.get("distill_lr"),
            }, default=_json_default),
            encoding="utf-8",
        )
        _save_l64(cell, ev, ctx)
    elif kind == "supervised":
        ev = evaluate(student, heads, _index_for(eval_dir, clips), tau=cell.get("tau"))
        keep_rate = ev["metrics"].get("keep_rate")
        (metrics_dir / f"{cell['cell_id']}.json").write_text(
            json.dumps({
                "r2_ap": ev["metrics"]["r2_ap"], "r1_rmse": ev["metrics"]["r1_rmse"],
                "keep_rate": keep_rate, "lr": cell.get("lr"), "role": cell.get("role"),
                "arm": cell.get("arm"), "label_n": cell.get("label_n"),
                "distill_seed": cell.get("distill_seed"), "readout_seed": cell.get("readout_seed"),
                "seed": cell.get("seed"),
            }, default=_json_default),
            encoding="utf-8",
        )
        _save_l64(cell, ev, ctx)
    wall = time.perf_counter() - t0
    steps_logged = len(log.get("step_logs") or [])
    return {
        "cell_id": cell["cell_id"],
        "device": str(mx.default_device()),
        "worlds": list(index.worlds),
        "n_worlds": len(index.worlds),
        "n_clips": len(index),
        "steps_logged": steps_logged,
        "steps": steps_logged,
        "wall_s": wall,
        "data_fraction": _data_fraction(log),
        "rss_mb": _rss_mb(),
        "keep_rate": keep_rate,
        "checkpoints": log.get("checkpoints") or [],
        "files": files,
    }


def _cell_worker_target(
    cell: dict,
    ctx_data: dict,
    result_json_path: str,
    err_json_path: str,
    runner_fn: Callable[[dict, dict], dict] | None = None,
) -> None:
    try:
        fn = runner_fn if runner_fn is not None else _execute_cell_body
        ctx = {
            "stage": ctx_data["stage"],
            "out": Path(ctx_data["out"]),
            "weights": Path(ctx_data["weights"]),
            "metrics": Path(ctx_data["metrics"]),
            "teachers": ctx_data["teachers"],
            "lab_teachers": ctx_data.get("lab_teachers"),
            "dirs": {k: Path(v) for k, v in ctx_data["dirs"].items()},
        }
        res = fn(cell, ctx)
        with open(result_json_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        import traceback
        with open(err_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "error": str(exc),
                    "type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                },
                f,
                ensure_ascii=False,
            )
        sys.exit(1)


def _save_l64(cell: dict, ev: dict, ctx: dict) -> None:
    if cell.get("label_n") != 64:
        return
    np.savez_compressed(
        ctx["metrics"] / f"{cell['cell_id']}.npz",
        r2_logit=np.asarray(ev["r2_logit"]),
        r2=np.asarray(ev["r2"]),
    )


def _eval_from_npz(path: Path) -> dict:
    data = np.load(path)
    n = int(data["r2"].shape[0])
    clips_per_world = 16
    if n % clips_per_world != 0:
        raise GD.GuardError(f"{path.name} is not a whole number of worlds")
    return {
        "r2_logit": data["r2_logit"],
        "r2": data["r2"],
        "clips_per_world": clips_per_world,
    }


def _finalize_distill(metrics_dir: Path) -> dict:
    """dev-distill 收尾：选 A*，再按 L=64 的逐段预测做世界级功效。"""
    from ainerzero.v9.experiments.s5.evaluate import paired_group_stat
    from ainerzero.v9.experiments.s5.metrics import paired_world_bootstrap

    rows = []
    a0_rows = []
    for path in sorted(metrics_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["_path"] = path
        if doc.get("label_n") != 64 or "r2_ap" not in doc:
            continue
        if doc.get("arm") in plan.ARM_ORDER and doc.get("distill_seed") is not None:
            rows.append(doc)
        elif doc.get("arm") == "A0":
            a0_rows.append(doc)
    if len({row["arm"] for row in rows}) < 3:
        return {"skipped": "L=64 head rows are incomplete"}
    chosen = plan.select_a_star(rows)
    result = {"a_star": chosen}
    star_npz = [metrics_dir / f"{row['_path'].stem}.npz" for row in rows if row["arm"] == chosen["arm"]]
    a0_npz = [metrics_dir / f"{row['_path'].stem}.npz" for row in a0_rows]
    if not star_npz or not a0_npz or not all(path.is_file() for path in star_npz + a0_npz):
        result["power"] = None
        return result
    group_a = [_eval_from_npz(path) for path in star_npz]
    group_b = [_eval_from_npz(path) for path in a0_npz]
    n_worlds = int(group_a[0]["r2"].shape[0] // group_a[0]["clips_per_world"])
    stat = paired_group_stat(group_a, group_b, "r2_ap")
    boot = paired_world_bootstrap(n_worlds, stat, level=plan.GT1_LEVEL)
    sigma = float(boot["bootstrap_std"]) * (n_worlds ** 0.5)
    result["bootstrap"] = {
        "point_estimate": boot["point_estimate"],
        "ci_lower": boot["ci_lower"],
        "ci_upper": boot["ci_upper"],
        "n_nan": boot["n_nan"],
        "sigma_world": sigma,
    }
    result["power"] = None if boot["n_nan"] else plan.worlds_for_power(sigma)
    return result


def _verify_tune(path: Path, expected: str) -> str:
    if not path.is_file():
        raise GD.GuardError(f"dev-tune result is missing: {path}")
    got = sha256_file(path)
    if got != expected.strip().lower():
        raise GD.GuardError(f"dev-tune result SHA mismatch: got {got} != {expected}")
    return got


def _prepare_smoke(out: Path) -> dict[str, Path]:
    dirs = {}
    for role, name in SMOKE_PARTITIONS.items():
        _refuse_final(name)
        target = out / "data" / name
        materialize_partition(name, target, world_range=(0, SMOKE_WORLDS[role]))
        dirs[name] = target
    return dirs


def run_locked(
    args,
    lock: GD.RunLock,
    *,
    cells_override: list[dict] | None = None,
    cell_runner: Callable[[dict, dict], dict] | None = None,
) -> int:
    GD._require_held(lock, LOCK)
    GD.require_fresh_pycache(STARTED)
    manifest = _manifest()
    head, dirty = GD.check_git_clean(REPO, list(manifest))
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))
    ledger_before = LEDGER.read_bytes() if LEDGER.is_file() else None
    etas = None
    etas_arg = getattr(args, "etas", None)
    if args.stage == "dev-tune-b":
        etas = _parse_etas(etas_arg)
    elif etas_arg:
        raise GD.GuardError("--etas is only valid with --stage dev-tune-b")
    tune = None
    if args.stage in TUNE_KEYS:
        if not args.tune_file or not args.tune_sha:
            raise GD.GuardError(f"{args.stage} needs --tune-file and --tune-sha")
        _verify_tune(Path(args.tune_file), args.tune_sha)
        tune = json.loads(Path(args.tune_file).read_text(encoding="utf-8"))
        if not isinstance(tune, dict):
            raise GD.GuardError("dev-tune result must be a JSON object")
        _require_tune_keys(args.stage, tune)
    tune_run_arg = getattr(args, "tune_run", None)
    if tune_run_arg and args.stage != "dev-tune-b":
        raise GD.GuardError("--tune-run is only valid with --stage dev-tune-b")
    planned = None
    if args.stage == "dev-tune-b":
        planned = resolve_tune_students(tune_run_arg, stage_cells_with_tune(args.stage, tune, etas), runs_root=RUNS)
    if args.stage != "smoke":
        _preflight_real_inputs()
        GD.consume_dev_use(
            lock, LEDGER, args.use_id, f"s5 {args.stage}",
            max_uses=DEV_MAX_USES, expected_lock=LOCK,
        )

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = RUNS / f"{args.stage}-{args.use_id}-{stamp}"
    if out.exists():
        raise GD.GuardError(f"run directory already exists: {out}")
    report = Path(args.report)
    GD.claim_report(report)
    out.mkdir(parents=True)
    events = out / "events.jsonl"
    weights = out / "weights"
    metrics_dir = out / "metrics"
    weights.mkdir()
    metrics_dir.mkdir()
    GD._require_held(lock, LOCK)
    _append(events, {"event": "stage_start", "stage": args.stage, "use_id": args.use_id, "lock": str(LOCK)})

    stage_deadline = GD.Deadline(STAGE_LIMIT_S[args.stage])
    ctx = {
        "stage": args.stage,
        "out": out,
        "weights": weights,
        "metrics": metrics_dir,
        "teachers": {},
        "dirs": {},
    }
    completed: list[dict] = []
    failed = None

    runner_name = getattr(cell_runner, "__qualname__", None) or getattr(cell_runner, "__name__", str(cell_runner)) if cell_runner else "_execute_cell_body"

    try:
        stage_deadline.check()
        if cells_override is not None:
            cells = cells_override
            if args.stage == "smoke" and (
                cell_runner is None
                or any(c.get("partition") in SMOKE_PARTITIONS.values() for c in cells)
            ):
                ctx["dirs"] = _prepare_smoke(out)
                pool = _index_for(ctx["dirs"][SMOKE_PARTITIONS["pool"]], SMOKE_CLIPS)
                lab = _index_for(ctx["dirs"][SMOKE_PARTITIONS["lab"]], SMOKE_CLIPS)
                ctx["teachers"] = _write_fake_teachers(pool, out / "teachers" / "pool")
                ctx["lab_teachers"] = _write_fake_teachers(lab, out / "teachers" / "lab")
        elif args.stage == "smoke":
            ctx["dirs"] = _prepare_smoke(out)
            pool = _index_for(ctx["dirs"][SMOKE_PARTITIONS["pool"]], SMOKE_CLIPS)
            lab = _index_for(ctx["dirs"][SMOKE_PARTITIONS["lab"]], SMOKE_CLIPS)
            ctx["teachers"] = _write_fake_teachers(pool, out / "teachers" / "pool")
            ctx["lab_teachers"] = _write_fake_teachers(lab, out / "teachers" / "lab")
            cells = smoke_cells()
        else:
            cells = planned if planned is not None else stage_cells_with_tune(args.stage, tune, etas)
            ctx["dirs"][REAL_PARTITIONS["dev"]] = DATA_ROOT / REAL_PARTITIONS["dev"]
            for cell in cells:
                _refuse_final(cell["partition"])
                ctx["dirs"][cell["partition"]] = DATA_ROOT / cell["partition"]
            ctx["teachers"] = {k: str(v) for k, v in REAL_TEACHERS["pool"].items()}
            ctx["lab_teachers"] = {k: str(v) for k, v in REAL_TEACHERS["lab"].items()}

        for index, cell in enumerate(cells):
            cell_limit = cell_limit_seconds(index)
            remaining_stage = stage_deadline.left()
            timeout_s = min(cell_limit, remaining_stage)
            if timeout_s <= 0.0:
                failed = f"timeout: stage deadline reached before cell {cell['cell_id']}"
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": "timeout", "limit_s": 0.0, "wall_s": 0.0})
                break

            # Every cell is a fresh process importing code from the working tree, so the frozen
            # manifest is re-checked before each cell (tier-1, 2026-11-12): an edit made while a stage
            # runs must stop the stage instead of silently reaching later cells.
            changed = GD.check_manifest(REPO, manifest)
            if changed:
                failed = "code changed during stage: " + "; ".join(changed[:6])
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": failed})
                break

            start_event: dict = {"event": "cell_start", "cell_id": cell["cell_id"], "index": index}
            part_name = cell.get("partition")
            if part_name in ctx["dirs"] and ctx["dirs"][part_name].exists():
                start_idx = _index_for(
                    ctx["dirs"][part_name],
                    SMOKE_CLIPS if args.stage == "smoke" else None,
                    label_n=cell.get("label_n"),
                )
                start_event["worlds"] = list(start_idx.worlds)
                start_event["n_worlds"] = len(start_idx.worlds)
                start_event["n_clips"] = len(start_idx)
                if cell.get("label_n") is not None:
                    start_event["label_n"] = int(cell["label_n"])
            _append(events, start_event)

            result_path = out / f".cell_{index}_{cell['cell_id']}.result.json"
            err_path = out / f".cell_{index}_{cell['cell_id']}.err.json"
            result_path.unlink(missing_ok=True)
            err_path.unlink(missing_ok=True)

            if cell.get("role") == "eta" and cell.get("lr") is None:
                tuned = []
                for path in sorted(ctx["metrics"].glob("tune-A0-*.json")):
                    tuned.append(json.loads(path.read_text(encoding="utf-8")))
                if tuned:
                    cell["lr"] = plan.choose_value(tuned, "lr")["value"]

            ctx_data = {
                "stage": ctx["stage"],
                "out": str(ctx["out"]),
                "weights": str(ctx["weights"]),
                "metrics": str(ctx["metrics"]),
                "teachers": ctx["lab_teachers"] if (cell.get("eta") is not None and ctx.get("lab_teachers")) else ctx["teachers"],
                "lab_teachers": ctx.get("lab_teachers"),
                "dirs": {k: str(v) for k, v in ctx["dirs"].items()},
            }

            mp_ctx = mp.get_context("spawn")
            p = mp_ctx.Process(
                target=_cell_worker_target,
                args=(cell, ctx_data, str(result_path), str(err_path), cell_runner),
            )
            t_cell0 = time.perf_counter()
            p.start()
            p.join(timeout=timeout_s)

            if p.is_alive():
                p.terminate()
                p.join(timeout=3.0)
                if p.is_alive():
                    p.kill()
                    p.join()
                cell_wall = time.perf_counter() - t_cell0
                failed = f"timeout: cell {cell['cell_id']} timed out after {timeout_s:.1f}s"
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": "timeout", "limit_s": timeout_s, "wall_s": cell_wall})
                break

            if p.exitcode != 0:
                err_msg = f"cell process exited with code {p.exitcode}"
                if err_path.is_file():
                    try:
                        err_data = json.loads(err_path.read_text(encoding="utf-8"))
                        err_msg = f"{err_data.get('type')}: {err_data.get('error')}"
                    except Exception:
                        pass
                failed = err_msg
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": failed})
                break

            if not result_path.is_file():
                failed = f"cell {cell['cell_id']} finished but result file is missing"
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": failed})
                break

            result = json.loads(result_path.read_text(encoding="utf-8"))
            result_path.unlink(missing_ok=True)

            # 核对输出文件的 SHA256
            try:
                for fname, expected_sha in result.get("files", {}).items():
                    fpath = weights / fname
                    if not fpath.is_file():
                        raise GD.GuardError(f"cell output file missing: {fname}")
                    got_sha = sha256_file(fpath)
                    if got_sha != expected_sha:
                        raise GD.GuardError(f"cell output file SHA mismatch for {fname}: got {got_sha} != {expected_sha}")
            except GD.GuardError as exc:
                failed = str(exc)
                _append(events, {"event": "cell_fail", "cell_id": cell["cell_id"], "error": failed})
                break

            completed.append(result)
            _append(events, {"event": "cell_end", **result})
    except GD.GuardError as exc:
        failed = str(exc)
        _append(events, {"event": "stage_fail", "error": failed})

    selection = _finalize_distill(metrics_dir) if args.stage == "dev-distill" else None
    versions = {}
    try:
        versions = GD.third_party_versions(REPO, ("numpy",))
    except GD.GuardError as exc:
        versions = {"error": str(exc)}
    stage_doc = {
        "stage": args.stage,
        "use_id": args.use_id,
        "git_head": head,
        "failed": failed,
        "completed": [row["cell_id"] for row in completed],
        "n_completed": len(completed),
        "cell_runner_name": runner_name,
        "manifest": manifest,
        "third_party": versions,
        "dev_ledger_written": args.stage != "smoke",
        "smoke_partitions": SMOKE_PARTITIONS if args.stage == "smoke" else None,
        "selection": selection,
    }
    (out / "stage.json").write_text(json.dumps(stage_doc, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")
    report.write_text(json.dumps({"out": str(out), "failed": failed, "n_completed": len(completed)}, ensure_ascii=False), encoding="utf-8")
    _append(events, {"event": "stage_end", "failed": failed, "n_completed": len(completed)})
    if args.stage == "smoke":
        ledger_after = LEDGER.read_bytes() if LEDGER.is_file() else None
        if ledger_before != ledger_after:
            raise GD.GuardError("smoke changed the dev ledger")
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_LIMIT_S))
    parser.add_argument("--use-id")
    parser.add_argument("--report")
    parser.add_argument("--tune-file")
    parser.add_argument("--tune-sha")
    parser.add_argument("--etas", help="dev-tune-b only: comma-separated eta values from the design grid")
    parser.add_argument("--tune-run", help="dev-tune-b only: the dev-tune run directory holding the distill-lr students")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.etas and args.stage != "dev-tune-b":
        print("--etas is only valid with --stage dev-tune-b", file=sys.stderr)
        return 1
    if args.dry_run:
        try:
            etas = _parse_etas(args.etas) if args.etas else None
        except GD.GuardError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        json.dump(dry_run_plan(args.stage, etas), sys.stdout, ensure_ascii=False, indent=1, default=_json_default)
        sys.stdout.write("\n")
        return 0
    if args.use_id is not None and not GD.valid_use_id(args.use_id):
        print(f"invalid use id: {args.use_id!r}", file=sys.stderr)
        return 1
    if not args.use_id:
        print(f"a {args.stage} run needs a use id", file=sys.stderr)
        return 1
    if not args.report:
        print("a run needs --report", file=sys.stderr)
        return 1
    for name in REAL_PARTITIONS.values():
        _refuse_final(name)
    # acquire the shared lock before any run directory
    try:
        with GD.RunLock(LOCK) as lock:
            return run_locked(args, lock)
    except GD.GuardError as exc:
        print(str(exc), file=sys.stderr)
        if "lock is busy" in str(exc):
            return 75
        return 1


if __name__ == "__main__":
    sys.exit(main())
