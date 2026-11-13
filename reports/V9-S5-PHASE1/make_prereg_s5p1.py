"""S5 冻结前预登记生成器 make_prereg_s5p1.py（纯 CPU，不拿锁，只读 dev-distill 与 tune 产物）。

依据 reports/V9-S5-FINAL/SPEC.md §1 与 reports/V9-S5-DESIGN/DESIGN-r1.md §§3-7 实现：
- 校验 dev-distill 运行目录（stage.json 含 selection.a_star 与 selection.power，failed 为 None）；
- 校验 events.jsonl 与 weights/ 下全部 66 个权重文件（6 个蒸馏学生、54 个读出头、3 个 A0-L64 学生与 3 个 A0-L64 读出头）存在且 SHA256 与 cell_end 登记一致；
- 校验 tune 文件（含 distill_lr、supervised_lr、eta，且在设计网格内）；
- 计算 n_final（未传 --n-final 时取 min(96, max(48, selection.power.n_capped / n_worlds))）；
- 生成 run_s5p1_final.py 的代码传递闭包 manifest，并附 dry-run 逐格墙钟估算与 budget_h 对比；
- 写出 PREREG.json（若目标文件已存在则拒绝覆盖）并输出其 SHA256。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
import plan_s5p1 as plan  # noqa: E402
import run_s5p1_final as final_runner  # noqa: E402

DEFAULT_TUNE_FILE = REPO / "reports/V9-S5-PHASE1/tune-devtune-20261112.json"
DEFAULT_OUT_FILE = REPO / "reports/V9-S5-FINAL/PREREG.json"


def _read_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "events.jsonl"
    if not events_path.is_file():
        raise GD.GuardError(f"dev-distill run missing events.jsonl: {events_path}")
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_tune_file(tune_path: Path) -> dict[str, Any]:
    if not tune_path.is_file():
        raise GD.GuardError(f"tune file not found: {tune_path}")
    try:
        tune = json.loads(tune_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GD.GuardError(f"malformed tune JSON: {tune_path}") from exc
    if not isinstance(tune, dict):
        raise GD.GuardError(f"tune JSON must be an object: {tune_path}")
    for key in ("distill_lr", "supervised_lr", "eta"):
        if key not in tune:
            raise GD.GuardError(f"tune file missing required key {key!r}: {tune_path}")
        val = tune[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or float(val) <= 0.0:
            raise GD.GuardError(f"tune key {key}={val!r} must be a positive number")
    if float(tune["distill_lr"]) not in [float(x) for x in plan.DISTILL_LRS]:
        raise GD.GuardError(f"distill_lr {tune['distill_lr']} not in design grid {plan.DISTILL_LRS}")
    if float(tune["supervised_lr"]) not in [float(x) for x in plan.SUPER_LRS]:
        raise GD.GuardError(f"supervised_lr {tune['supervised_lr']} not in design grid {plan.SUPER_LRS}")
    if float(tune["eta"]) not in [float(x) for x in plan.ETAS]:
        raise GD.GuardError(f"eta {tune['eta']} not in design grid {plan.ETAS}")
    return tune


def build_prereg(
    dev_distill_run: Path,
    *,
    tune_file: Path = DEFAULT_TUNE_FILE,
    n_final: int | None = None,
    budget_h: float,
    repo: Path = REPO,
    standin_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验输入并构造完整 PREREG 字典（不拿锁）。"""
    if isinstance(budget_h, bool) or not isinstance(budget_h, (int, float)) or float(budget_h) <= 0.0:
        raise GD.GuardError(f"budget_h must be a positive number, got {budget_h!r}")

    dev_run = Path(dev_distill_run).resolve()
    tune_path = Path(tune_file).resolve()
    repo_root = Path(repo).resolve()

    stage_file = dev_run / "stage.json"
    if not stage_file.is_file():
        raise GD.GuardError(f"dev-distill stage.json missing: {stage_file}")
    stage_doc = json.loads(stage_file.read_text(encoding="utf-8"))
    if stage_doc.get("stage") != "dev-distill":
        raise GD.GuardError(f"expected stage='dev-distill', got {stage_doc.get('stage')!r}")
    if stage_doc.get("failed") is not None:
        raise GD.GuardError(f"dev-distill run failed ({stage_doc.get('failed')}); cannot build PREREG")

    selection = stage_doc.get("selection")
    if not isinstance(selection, dict):
        raise GD.GuardError("dev-distill stage.json missing selection object")
    a_star_obj = selection.get("a_star")
    if not isinstance(a_star_obj, dict) or a_star_obj.get("arm") not in ("A1", "A2", "A3"):
        raise GD.GuardError(f"invalid selection.a_star in dev-distill stage.json: {a_star_obj!r}")
    a_star = str(a_star_obj["arm"])

    power_obj = selection.get("power")
    if not isinstance(power_obj, dict):
        raise GD.GuardError(f"invalid selection.power in dev-distill stage.json: {power_obj!r}")
    power_n = power_obj.get("n_capped", power_obj.get("n_worlds"))
    if power_n is None or int(power_n) <= 0:
        raise GD.GuardError(f"selection.power missing valid n_capped / n_worlds: {power_obj!r}")

    is_standin = bool(standin_overrides and standin_overrides.get("standin_test"))
    if n_final is None:
        resolved_n_final = min(96, max(48, int(power_n)))
    else:
        resolved_n_final = int(n_final)
        if not is_standin and not (48 <= resolved_n_final <= 96):
            raise GD.GuardError(f"--n-final must be in [48, 96], got {resolved_n_final}")

    tune = _validate_tune_file(tune_path)

    events = _read_events(dev_run)
    starts = [e for e in events if e.get("event") == "stage_start"]
    if len(starts) != 1 or starts[0].get("stage") != "dev-distill":
        raise GD.GuardError(f"events.jsonl in {dev_run} is not a single dev-distill run")

    registered_files: dict[str, str] = {}
    cell_end_by_id: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.get("event") == "cell_end":
            cid = str(ev.get("cell_id", ""))
            cell_end_by_id[cid] = ev
            for fname, fsha in (ev.get("files") or {}).items():
                registered_files[str(fname)] = str(fsha)

    weights_dir = dev_run / "weights"
    if not weights_dir.is_dir():
        raise GD.GuardError(f"dev-distill weights directory missing: {weights_dir}")

    def _check_and_pin(fname: str) -> str:
        fpath = weights_dir / fname
        if not fpath.is_file():
            raise GD.GuardError(f"missing weight file in dev-distill: {fpath}")
        if fname not in registered_files:
            raise GD.GuardError(f"weight file {fname} was not registered in dev-distill cell_end events")
        got = final_runner.sha256_file(fpath)
        want = registered_files[fname]
        if got != want:
            raise GD.GuardError(f"weight file {fname} SHA mismatch vs events.jsonl: got {got} != {want}")
        return got

    distill_students: dict[str, str] = {}
    distill_proj_heads: dict[str, str] = {}
    for arm in ("A1", "A2", "A3"):
        for d_seed in (0, 1):
            s_name = f"distill-{arm}-s{d_seed}-student.npz"
            h_name = f"distill-{arm}-s{d_seed}-heads.npz"
            distill_students[s_name] = _check_and_pin(s_name)
            if (weights_dir / h_name).is_file() and h_name in registered_files:
                distill_proj_heads[h_name] = _check_and_pin(h_name)

    readout_heads: dict[str, str] = {}
    for arm in ("A1", "A2", "A3"):
        for d_seed in (0, 1):
            for label_n in (64, 512, 2048):
                for r_seed in (0, 1, 2):
                    h_name = f"heads-{arm}-d{d_seed}-L{label_n}-r{r_seed}.npz"
                    readout_heads[h_name] = _check_and_pin(h_name)

    a0_l64_students: dict[str, str] = {}
    a0_l64_heads: dict[str, str] = {}
    for seed in (0, 1, 2):
        s_name = f"A0-L64-s{seed}-student.npz"
        h_name = f"A0-L64-s{seed}-heads.npz"
        a0_l64_students[s_name] = _check_and_pin(s_name)
        a0_l64_heads[h_name] = _check_and_pin(h_name)

    dev_astar_step_s: dict[str, float] = {}
    for d_seed in (0, 1):
        cid = f"distill-{a_star}-s{d_seed}"
        if cid in cell_end_by_id:
            ev = cell_end_by_id[cid]
            w_s = float(ev.get("wall_s", 0.0))
            st_n = max(1, int(ev.get("steps_logged", 1)))
            dev_astar_step_s[cid] = float(w_s / st_n)

    manifest = final_runner._manifest(repo_root)
    dev_run_str = (
        str(dev_run.relative_to(repo_root))
        if dev_run.is_relative_to(repo_root)
        else str(dev_run)
    )
    tune_str = (
        str(tune_path.relative_to(repo_root))
        if tune_path.is_relative_to(repo_root)
        else str(tune_path)
    )

    frozen_section: dict[str, Any] = {
        "a_star": a_star,
        "a_star_selection": a_star_obj,
        "power_selection": power_obj,
        "distill_lr": float(tune["distill_lr"]),
        "supervised_lr": float(tune["supervised_lr"]),
        "eta": float(tune["eta"]),
        "align_layer": 3,
        "tau": final_runner.RLT_TAU,
        "distill_epochs": plan.DISTILL_EPOCHS,
        "super_epochs": {str(k): int(v) for k, v in plan.SUPER_EPOCHS.items()},
        "readout_epochs": {str(k): int(v) for k, v in plan.SUPER_EPOCHS.items()},
        "batch_size": plan.BATCH,
        "ckpt_every_frac": final_runner.CKPT_EVERY_FRAC,
        "ga_num_checkpoints": 16,
        "eval_threshold": final_runner.EVAL_THRESHOLD,
        "seeds": {
            "distill": [0, 1],
            "readout": [0, 1, 2],
            "A0": [0, 1, 2],
            "A4": [0, 1, 2],
            "A0-R": [0, 1, 2],
            "FT": [0, 1, 2],
        },
        "lab_subset_seed": final_runner.LAB_SUBSET_SEED,
        "csh_perm_seed": final_runner.CSH_PERM_SEED,
        "boot_seed": final_runner.BOOT_SEED,
        "n_boot": final_runner.N_BOOT,
        "n_final": resolved_n_final,
        "partitions": dict(final_runner.REAL_FINAL_PARTITIONS),
    }
    if standin_overrides:
        frozen_section.update(standin_overrides)

    seeds_cfg = frozen_section["seeds"]
    eff_512 = int(frozen_section.get("effective_l_clips", {}).get("512", 512))
    ga_cap = max(
        1,
        int(frozen_section["super_epochs"]["512"]) * (eff_512 // int(frozen_section["batch_size"])),
    )

    gates_section: dict[str, Any] = {
        "family_gt": {
            "bonferroni_m": final_runner.GT_BONFERRONI_M,
            "alpha": final_runner.GT_ALPHA,
            "ci_level": final_runner.GT_LEVEL,
        },
        "GT1": {
            "label_n": 64,
            "metric": "r2_ap",
            "comparison": "A* (frozen+heads) - A0",
            "min_diff": 0.05,
            "effect": 0.05,
            "ci_level": final_runner.GT_LEVEL,
            "level": final_runner.GT_LEVEL,
            "ci_lower_gt": 0.0,
        },
        "GT2": {
            "label_n": 64,
            "metric": "r2_ap",
            "comparison": "A* (frozen+heads) - C-sh (frozen+heads)",
            "min_diff": 0.03,
            "effect": 0.03,
            "ci_level": final_runner.GT_LEVEL,
            "level": final_runner.GT_LEVEL,
            "ci_lower_gt": 0.0,
        },
        "GT3": {
            "label_n": 64,
            "metric": "r1_rmse",
            "comparison": "A* (frozen+heads) - A0",
            "non_inferiority_frac": 0.05,
            "margin_frac": 0.05,
            "ci_level": final_runner.GT_LEVEL,
            "level": final_runner.GT_LEVEL,
            "rule": "ci_upper <= 0.05 * A0_r1_rmse",
        },
        "GA": {
            "label_n": 512,
            "metric": "r2_ap",
            "target_frac_of_a0_final_median": 0.95,
            "target_frac": 0.95,
            "num_checkpoints": int(frozen_section.get("ga_num_checkpoints", 16)),
            "total_steps": ga_cap,
            "interpolation": "linear_from_step0_to_first_crossing",
            "censored_value": ga_cap,
            "max_median_step_ratio": 0.7,
            "ratio_max": 0.7,
        },
        "GR": {
            "label_n": 512,
            "max_keep_rate": 0.8,
            "keep_max": 0.8,
            "min_distill_step_wall_reduction": 0.15,
            "wall_drop_min": 0.15,
            "step_wall_reference": "median_of_2_C_sh_distill_runs_in_same_registered_run",
            "descriptive_step_wall_reference": "dev_distill_A_star",
            "max_r2_ap_drop_ci95_upper": 0.03,
            "ap_drop_ci_max": 0.03,
            "ci_level": final_runner.GR_LEVEL,
            "ap_level": final_runner.GR_LEVEL,
        },
        "seed_averaging_rule": (
            "First average readout seeds (0,1,2) within each distill seed (0,1), "
            "then average across distill seeds (0,1); paired world bootstrap resamples worlds after seed averaging."
        ),
    }

    pinned_section: dict[str, Any] = {
        "dev_distill_run": dev_run_str,
        "dev_distill_stage_sha256": final_runner.sha256_file(stage_file),
        "tune_file": tune_str,
        "tune_sha256": final_runner.sha256_file(tune_path),
        "distill_students": distill_students,
        "distill_proj_heads": distill_proj_heads,
        "readout_heads": readout_heads,
        "a0_l64_students": a0_l64_students,
        "a0_l64_heads": a0_l64_heads,
        "dev_distill_a_star_step_s": dev_astar_step_s,
    }

    partial_prereg = {
        "schema": "s5.phase1.prereg.v1",
        "design": "reports/V9-S5-DESIGN/DESIGN-r1.md",
        "a_star": a_star,
        "boot_seed": int(frozen_section["boot_seed"]),
        "n_boot": int(frozen_section["n_boot"]),
        "gt_level": final_runner.GT_LEVEL,
        "distill_seeds": list(seeds_cfg["distill"]),
        "readout_seeds": list(seeds_cfg["readout"]),
        "supervised_seeds": list(seeds_cfg["A0"]),
        "ga_cap": ga_cap,
        "frozen": frozen_section,
        "gates": gates_section,
        "pinned_artifacts": pinned_section,
        "manifest": manifest,
        "manifest_sha256": final_runner.manifest_sha256(manifest),
        "budget": {
            "budget_h": float(budget_h),
            "budget_s": float(budget_h) * 3600.0,
            "cell_limit_s": final_runner.CELL_LIMIT_S,
        },
    }
    est = final_runner.dry_run_plan(partial_prereg, budget_h=float(budget_h), n_final=resolved_n_final)
    partial_prereg["budget"]["dry_run_estimate"] = {
        "n_cells": est["n_cells"],
        "n_models_evaluated": est["n_models_evaluated"],
        "n_ga_checkpoints": est["n_ga_checkpoints"],
        "estimated_training_s": est["estimated_training_s"],
        "estimated_training_h": est["estimated_training_h"],
        "estimated_evaluation_breakdown_s": est["estimated_evaluation_breakdown_s"],
        "estimated_total_s": est["estimated_total_s"],
        "estimated_total_h": est["estimated_total_h"],
        "within_budget": est["within_budget"],
        "exceeds_budget": est["exceeds_budget"],
        "exceeds_budget_by_h": est["exceeds_budget_by_h"],
        "budget_warning": est["budget_warning"],
        "group_totals_s": est["group_totals_s"],
        "cells": [
            {
                "cell_id": c["cell_id"],
                "group": c["group"],
                "kind": c["kind"],
                "steps": c["steps"],
                "estimated_wall_s": c["estimated_wall_s"],
            }
            for c in est["cells"]
        ],
    }
    return partial_prereg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate frozen PREREG.json for S5 Phase 1 final run")
    parser.add_argument("--dev-distill-run", "--distill-run", dest="dev_distill_run", required=True)
    parser.add_argument("--tune-file", default=str(DEFAULT_TUNE_FILE))
    parser.add_argument("--n-final", type=int, default=None)
    parser.add_argument("--budget-h", type=float, required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT_FILE))
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if out_path.exists():
        print(f"refusing to overwrite existing PREREG file: {out_path}", file=sys.stderr)
        return 1

    try:
        doc = build_prereg(
            Path(args.dev_distill_run),
            tune_file=Path(args.tune_file),
            n_final=args.n_final,
            budget_h=float(args.budget_h),
            repo=REPO,
        )
    except GD.GuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    sha = final_runner.sha256_file(out_path)
    est = doc["budget"]["dry_run_estimate"]
    summary_line = {
        "out": str(out_path),
        "prereg_sha256": sha,
        "a_star": doc["frozen"]["a_star"],
        "n_final": doc["frozen"]["n_final"],
        "budget_h": doc["budget"]["budget_h"],
        "estimated_total_h": est["estimated_total_h"],
        "within_budget": est["within_budget"],
        "budget_warning": est["budget_warning"],
    }
    print(json.dumps(summary_line, ensure_ascii=False))
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
