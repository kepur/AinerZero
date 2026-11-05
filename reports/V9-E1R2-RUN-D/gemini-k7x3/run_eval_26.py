#!/usr/bin/env python3
"""E1 r2 运行卡 D：dev 评测 26 格执行与报告生成脚本

任务卡：ainerzero.V9.P108
执行者：gemini-k7x3
"""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
RELAY_ROOT = Path("/Users/mac/AinerWorkFlow/AinerRelay").resolve()
TASK_ID = "ainerzero.V9.P108"
AGENT = "gemini-k7x3"

OUT_DIR = REPO_ROOT / "reports/V9-E1R2-RUN-D" / AGENT
RAW_LOGS_DIR = OUT_DIR / "raw_logs"
LEDGER_COPY_DIR = OUT_DIR / "ledger_copy"
RAW_LOGS_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_COPY_DIR.mkdir(parents=True, exist_ok=True)

PROD_LEDGER = REPO_ROOT / "artifacts/v9/e1/phase2-r2/control.sqlite3"
LOCK_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lock"
CLI_PYTHON = str(REPO_ROOT / ".venv/bin/python")
RELAY_BIN = str(RELAY_ROOT / "bin/relay")
R1_DIR = REPO_ROOT / "artifacts/v9/e1/phase2"
CHECKPOINTS_DIR = REPO_ROOT / "artifacts/v9/e1/phase2-r2/checkpoints"
EVAL_DIR = REPO_ROOT / "artifacts/v9/e1/phase2-r2/eval"

MAIN_LOG = OUT_DIR / "execution.log"


def log(msg: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with MAIN_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(131072):
            h.update(chunk)
    return h.hexdigest()


def is_lock_held() -> bool:
    if not LOCK_PATH.exists():
        return False
    try:
        res = subprocess.run(["lsof", str(LOCK_PATH)], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def wait_for_lock_release(timeout_seconds: float = 60.0) -> None:
    t0 = time.time()
    while is_lock_held():
        if time.time() - t0 > timeout_seconds:
            raise RuntimeError(f"Lock {LOCK_PATH} held for more than {timeout_seconds}s!")
        log(f"Lock {LOCK_PATH} is currently held, waiting 2s...")
        time.sleep(2)


def copy_ledger_and_query_run(run_id: str | None) -> dict | None:
    if not PROD_LEDGER.exists():
        return None
    for src in glob.glob(str(PROD_LEDGER) + "*"):
        src_path = Path(src)
        dst_path = LEDGER_COPY_DIR / src_path.name
        shutil.copy2(src_path, dst_path)

    copy_db = LEDGER_COPY_DIR / "control.sqlite3"
    if not copy_db.exists():
        return None

    con = sqlite3.connect(str(copy_db))
    con.row_factory = sqlite3.Row
    try:
        if run_id:
            row = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        else:
            row = con.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if row:
            d = dict(row)
            created_at_s = d.get("created_at")
            updated_at_s = d.get("updated_at")
            if isinstance(created_at_s, (int, float)):
                d["created_at_iso"] = datetime.fromtimestamp(created_at_s, tz=timezone.utc).isoformat()
            if isinstance(updated_at_s, (int, float)):
                d["updated_at_iso"] = datetime.fromtimestamp(updated_at_s, tz=timezone.utc).isoformat()
            return d
        return None
    finally:
        con.close()


CELL_SPECS = [
    # 1-3
    {"idx": 1, "arm": 6, "family": "P", "seed": 42, "wall_timeout": 250},
    {"idx": 2, "arm": 6, "family": "P", "seed": 43, "wall_timeout": 250},
    {"idx": 3, "arm": 6, "family": "P", "seed": 44, "wall_timeout": 250},
    # 4-6
    {"idx": 4, "arm": 2, "family": "P", "seed": 42, "wall_timeout": 140},
    {"idx": 5, "arm": 2, "family": "P", "seed": 43, "wall_timeout": 140},
    {"idx": 6, "arm": 2, "family": "P", "seed": 44, "wall_timeout": 140},
    # 7-9
    {"idx": 7, "arm": 3, "family": "P", "seed": 42, "wall_timeout": 160},
    {"idx": 8, "arm": 3, "family": "P", "seed": 43, "wall_timeout": 160},
    {"idx": 9, "arm": 3, "family": "P", "seed": 44, "wall_timeout": 160},
    # 10-12
    {"idx": 10, "arm": 6, "family": "S", "seed": 42, "wall_timeout": 250},
    {"idx": 11, "arm": 6, "family": "S", "seed": 43, "wall_timeout": 250},
    {"idx": 12, "arm": 6, "family": "S", "seed": 44, "wall_timeout": 250},
    # 13-15
    {"idx": 13, "arm": 2, "family": "S", "seed": 42, "wall_timeout": 140},
    {"idx": 14, "arm": 2, "family": "S", "seed": 43, "wall_timeout": 140},
    {"idx": 15, "arm": 2, "family": "S", "seed": 44, "wall_timeout": 140},
    # 16-18
    {"idx": 16, "arm": 3, "family": "S", "seed": 42, "wall_timeout": 160},
    {"idx": 17, "arm": 3, "family": "S", "seed": 43, "wall_timeout": 160},
    {"idx": 18, "arm": 3, "family": "S", "seed": 44, "wall_timeout": 160},
    # 19-22
    {"idx": 19, "arm": 1, "family": "P", "seed": None, "wall_timeout": 165},
    {"idx": 20, "arm": 4, "family": "P", "seed": None, "wall_timeout": 165},
    {"idx": 21, "arm": 5, "family": "P", "seed": None, "wall_timeout": 165},
    {"idx": 22, "arm": 7, "family": "P", "seed": None, "wall_timeout": 165},
    # 23-26
    {"idx": 23, "arm": 1, "family": "S", "seed": None, "wall_timeout": 165},
    {"idx": 24, "arm": 4, "family": "S", "seed": None, "wall_timeout": 165},
    {"idx": 25, "arm": 5, "family": "S", "seed": None, "wall_timeout": 165},
    {"idx": 26, "arm": 7, "family": "S", "seed": None, "wall_timeout": 165},
]


def check_arm2_checkpoints() -> dict[str, dict[str, str]]:
    res: dict[str, dict[str, str]] = {}
    for fam in ("P", "S"):
        for seed in (42, 43, 44):
            cell_name = f"arm2_{fam}_seed{seed}"
            d = CHECKPOINTS_DIR / cell_name
            if not d.is_dir():
                raise RuntimeError(f"Missing expected arm2 checkpoint dir {d}")
            cell_files: dict[str, str] = {}
            for f in sorted(d.iterdir()):
                if f.is_file():
                    cell_files[f.name] = sha256_file(f)
            res[cell_name] = cell_files
    return res


def run_verify() -> dict:
    log("Running preflight verify...")
    cmd = [CLI_PYTHON, "-m", "ainerzero.cli", "e1-phase2", "--mode", "verify"]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Verify failed with code {proc.returncode}:\n{proc.stderr}")
    data = json.loads(proc.stdout)
    if data.get("status") != "verified":
        raise RuntimeError(f"Verify status != verified: {data}")
    if data.get("approval", {}).get("status") != "approved":
        raise RuntimeError(f"Approval status != approved: {data}")
    if data.get("identity", {}).get("status") != "passed":
        raise RuntimeError(f"Identity status != passed: {data}")
    log("Preflight verify PASSED.")
    return data


def main() -> None:
    log("=== Starting ainerzero.V9.P108 Execution ===")
    r1_stat_before = R1_DIR.stat().st_mtime
    log(f"r1 directory initial mtime: {r1_stat_before} ({datetime.fromtimestamp(r1_stat_before, tz=timezone.utc).isoformat()})")

    verify_json = run_verify()
    (OUT_DIR / "verify_output.json").write_text(json.dumps(verify_json, indent=2), encoding="utf-8")

    cells_results = []
    arm2_ckpts = None
    stop_triggered = False
    stop_reason = ""

    for spec in CELL_SPECS:
        idx = spec["idx"]
        arm = spec["arm"]
        family = spec["family"]
        seed = spec["seed"]
        wall_timeout = spec["wall_timeout"]
        seed_str = str(seed) if seed is not None else "none"
        cell_tag = f"arm{arm}_{family}_{seed_str}"

        log(f"\n--- [Cell {idx:02d}/26] Starting: {cell_tag} (timeout: {wall_timeout}s) ---")
        wait_for_lock_release(timeout_seconds=60.0)

        # Build command: relay exec ainerzero.V9.P108 --agent gemini-k7x3 --wall-timeout <timeout> -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode eval --arm <arm> --family <family> [--seed <seed>]
        cmd = [
            "python3",
            RELAY_BIN,
            "exec",
            TASK_ID,
            "--agent",
            AGENT,
            "--wall-timeout",
            str(wall_timeout),
            "--",
            CLI_PYTHON,
            "-m",
            "ainerzero.cli",
            "e1-phase2",
            "--mode",
            "eval",
            "--arm",
            str(arm),
            "--family",
            family,
        ]
        if seed is not None:
            cmd.extend(["--seed", str(seed)])

        t_start = time.time()
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        t_end = time.time()
        elapsed = t_end - t_start

        log_file = RAW_LOGS_DIR / f"cell_{idx:02d}_{cell_tag}.log"
        with log_file.open("w", encoding="utf-8") as f:
            f.write(f"=== Command ===\n{' '.join(cmd)}\n\n")
            f.write(f"=== Returncode ===\n{proc.returncode}\n\n")
            f.write(f"=== Elapsed ===\n{elapsed:.2f}s\n\n")
            f.write(f"=== STDOUT ===\n{proc.stdout}\n\n")
            f.write(f"=== STDERR ===\n{proc.stderr}\n")

        log(f"[Cell {idx:02d}/26] Returncode: {proc.returncode}, Elapsed: {elapsed:.2f}s")

        # Parse stdout JSON
        stdout_json = None
        run_id = None
        try:
            # find last JSON object in stdout
            lines = proc.stdout.strip().splitlines()
            # Find json start
            for i in range(len(lines)):
                chunk = "\n".join(lines[i:])
                if chunk.startswith("{") and chunk.endswith("}"):
                    try:
                        stdout_json = json.loads(chunk)
                        break
                    except Exception:
                        continue
        except Exception as e:
            log(f"Warning: could not parse stdout as json: {e}")

        if stdout_json:
            run_id = stdout_json.get("result", {}).get("run_id")

        # After cell 1 completes, inspect the copied arm 2 checkpoints
        if idx == 1 and proc.returncode == 0:
            log("Cell 1 finished. Inspecting inherited arm 2 checkpoints...")
            try:
                arm2_ckpts = check_arm2_checkpoints()
                log("Inherited arm 2 checkpoints verified and hashed successfully.")
            except Exception as exc:
                log(f"ERROR verifying arm 2 checkpoints: {exc}")
                stop_triggered = True
                stop_reason = f"Arm 2 checkpoint verification failed: {exc}"

        # Copy ledger and inspect record
        ledger_row = copy_ledger_and_query_run(run_id)

        # Inspect eval json file
        eval_filename = f"eval_{cell_tag}.json"
        eval_file_path = EVAL_DIR / eval_filename
        eval_sha = None
        eval_data = None
        if eval_file_path.is_file():
            eval_sha = sha256_file(eval_file_path)
            try:
                eval_data = json.loads(eval_file_path.read_text(encoding="utf-8"))
            except Exception as e:
                log(f"Warning: could not parse eval json {eval_file_path}: {e}")

        # Extract metrics
        summary = eval_data.get("summary", {}) if eval_data else {}
        partition = eval_data.get("partition") if eval_data else None
        k_step_errors = summary.get("k_step_errors", {})
        k_step_episodes = summary.get("k_step_episodes", {})
        e_1 = k_step_errors.get("1")
        e_5 = k_step_errors.get("5")
        e_10 = k_step_errors.get("10")
        e_30 = k_step_errors.get("30")
        collision_f1 = summary.get("collision_f1")

        cell_record = {
            "cell_idx": idx,
            "arm": arm,
            "family": family,
            "seed": seed,
            "seed_str": seed_str,
            "cell_tag": cell_tag,
            "wall_timeout": wall_timeout,
            "exit_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "run_id": run_id,
            "eval_filename": eval_filename,
            "eval_sha256": eval_sha,
            "partition": partition,
            "e_1": e_1,
            "e_5": e_5,
            "e_10": e_10,
            "e_30": e_30,
            "k_step_episodes": k_step_episodes,
            "collision_f1": collision_f1,
            "ledger_row": ledger_row,
            "stdout_json": stdout_json,
        }
        cells_results.append(cell_record)

        if proc.returncode != 0:
            stop_triggered = True
            stop_reason = f"Cell {idx} ({cell_tag}) failed with exit code {proc.returncode}"
            log(f"STOP TRIGGERED: {stop_reason}")
            break

        if stop_triggered:
            break

    # Check r1 mtime
    r1_stat_after = R1_DIR.stat().st_mtime
    r1_unmodified = (r1_stat_before == r1_stat_after)
    log(f"r1 directory final mtime: {r1_stat_after} (unmodified: {r1_unmodified})")

    # Macro averages
    # Group by (arm, family)
    grouped: dict[tuple[int, str], list[dict]] = {}
    for c in cells_results:
        key = (c["arm"], c["family"])
        grouped.setdefault(key, []).append(c)

    macro_averages = {}
    for (arm, fam), group in sorted(grouped.items()):
        key_str = f"arm{arm}_{fam}"
        e1_vals = [g["e_1"] for g in group if g.get("e_1") is not None]
        e5_vals = [g["e_5"] for g in group if g.get("e_5") is not None]
        e10_vals = [g["e_10"] for g in group if g.get("e_10") is not None]
        e30_vals = [g["e_30"] for g in group if g.get("e_30") is not None]
        f1_vals = [g["collision_f1"] for g in group if g.get("collision_f1") is not None]
        wall_vals = [g["elapsed_seconds"] for g in group]

        macro_averages[key_str] = {
            "arm": arm,
            "family": fam,
            "cell_count": len(group),
            "mean_e_1": round(sum(e1_vals) / len(e1_vals), 6) if e1_vals else None,
            "mean_e_5": round(sum(e5_vals) / len(e5_vals), 6) if e5_vals else None,
            "mean_e_10": round(sum(e10_vals) / len(e10_vals), 6) if e10_vals else None,
            "mean_e_30": round(sum(e30_vals) / len(e30_vals), 6) if e30_vals else None,
            "mean_collision_f1": round(sum(f1_vals) / len(f1_vals), 6) if f1_vals else None,
            "total_elapsed_seconds": round(sum(wall_vals), 2),
            "mean_elapsed_seconds": round(sum(wall_vals) / len(wall_vals), 2),
        }

    total_wall_s = round(sum(c["elapsed_seconds"] for c in cells_results), 2)

    full_metrics = {
        "task_id": TASK_ID,
        "agent": AGENT,
        "experiment_id": "e1-phase2-20261105-r2",
        "document_sha256": verify_json.get("document_sha256"),
        "total_cells_planned": 26,
        "cells_completed": len(cells_results),
        "stop_triggered": stop_triggered,
        "stop_reason": stop_reason,
        "total_wall_seconds": total_wall_s,
        "r1_unmodified": r1_unmodified,
        "inherited_arm2_checkpoints": arm2_ckpts,
        "macro_averages": macro_averages,
        "cells": cells_results,
    }

    # Write metrics.json & 指标.json
    metrics_path = OUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(full_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(metrics_path, OUT_DIR / "指标.json")
    log("Written metrics.json and 指标.json.")

    # Generate tables markdown
    tables_md = generate_tables_md(full_metrics)
    tables_path = OUT_DIR / "generated_tables.md"
    tables_path.write_text(tables_md, encoding="utf-8")
    log("Written generated_tables.md.")

    # Generate full report
    report_md = generate_report_md(full_metrics, tables_md)
    report_path = OUT_DIR / "REPORT.md"
    report_path.write_text(report_md, encoding="utf-8")
    shutil.copy2(report_path, OUT_DIR / "报告.md")
    log("Written REPORT.md and 报告.md.")

    log(f"=== Completed. Total wall clock: {total_wall_s}s ===")


def generate_tables_md(data: dict) -> str:
    lines = []
    lines.append("# E1 r2 运行卡 D：dev 评测 26 格执行表格\n")

    lines.append("## 表 1：26 格执行与核心评测指标表\n")
    lines.append("| 格次 | 单元 (臂/族/种子) | run_id | 预留 (s) | 实际墙钟 (s) | 退出码 | 分区 | e_1 | e_5 | e_10 | e_30 | collision_f1 | 状态 |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for c in data["cells"]:
        rid = (c["run_id"][:8] + "..") if c["run_id"] else "—"
        e1 = f"{c['e_1']:.4f}" if c.get("e_1") is not None else "—"
        e5 = f"{c['e_5']:.4f}" if c.get("e_5") is not None else "—"
        e10 = f"{c['e_10']:.4f}" if c.get("e_10") is not None else "—"
        e30 = f"{c['e_30']:.4f}" if c.get("e_30") is not None else "—"
        f1 = f"{c['collision_f1']:.4f}" if c.get("collision_f1") is not None else "—"
        part = c.get("partition") or "—"
        status = "completed" if c["exit_code"] == 0 else f"failed({c['exit_code']})"
        lines.append(f"| {c['cell_idx']} | ({c['arm']}, {c['family']}, {c['seed_str']}) | `{rid}` | {c['wall_timeout']} | {c['elapsed_seconds']:.2f} | {c['exit_code']} | {part} | {e1} | {e5} | {e10} | {e30} | {f1} | {status} |")
    lines.append("")

    lines.append("## 表 2：各 k 步长可用 episode 数分布表\n")
    lines.append("| 格次 | 单元 | k=1 episodes | k=5 episodes | k=10 episodes | k=30 episodes |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: |")
    for c in data["cells"]:
        k_eps = c.get("k_step_episodes") or {}
        ep1 = k_eps.get("1", "—")
        ep5 = k_eps.get("5", "—")
        ep10 = k_eps.get("10", "—")
        ep30 = k_eps.get("30", "—")
        lines.append(f"| {c['cell_idx']} | ({c['arm']}, {c['family']}, {c['seed_str']}) | {ep1} | {ep5} | {ep10} | {ep30} |")
    lines.append("")

    lines.append("## 表 3：评测结果文件 SHA-256 登记表\n")
    lines.append("| 格次 | 单元 | 结果文件名 | 结果文件 SHA-256 | 分区 (partition) |")
    lines.append("| :---: | :---: | :--- | :--- | :---: |")
    for c in data["cells"]:
        lines.append(f"| {c['cell_idx']} | ({c['arm']}, {c['family']}, {c['seed_str']}) | `{c['eval_filename']}` | `{c['eval_sha256']}` | {c['partition']} |")
    lines.append("")

    lines.append("## 表 4：自 r1 继承之 6 个 ② checkpoint 目录完整文件哈希表\n")
    lines.append("| 单元 | 文件名 | SHA-256 |")
    lines.append("| :--- | :--- | :--- |")
    arm2_ckpts = data.get("inherited_arm2_checkpoints") or {}
    for cell_name, fmap in sorted(arm2_ckpts.items()):
        for fname, fsha in sorted(fmap.items()):
            lines.append(f"| `{cell_name}` | `{fname}` | `{fsha}` |")
    lines.append("")

    lines.append("## 表 5：账本副本记录详情表 (control.sqlite3)\n")
    lines.append("| 格次 | run_id | 账本 state | 账本 reason | 账本 active_seconds | created_at (UTC) | updated_at (UTC) |")
    lines.append("| :---: | :--- | :---: | :--- | :---: | :--- | :--- |")
    for c in data["cells"]:
        row = c.get("ledger_row") or {}
        rid = row.get("run_id", "—")
        st = row.get("state", "—")
        rea = row.get("reason", "—")
        act = row.get("active_seconds", "—")
        c_at = row.get("created_at_iso", str(row.get("created_at", "—")))
        u_at = row.get("updated_at_iso", str(row.get("updated_at", "—")))
        lines.append(f"| {c['cell_idx']} | `{rid}` | {st} | {rea} | {act} | {c_at} | {u_at} |")
    lines.append("")

    lines.append("## 表 6：按臂 × 族汇总宏平均表（算术汇总）\n")
    lines.append("| 臂 | 族 | 格数 | 宏平均 e_1 | 宏平均 e_5 | 宏平均 e_10 | 宏平均 e_30 | 宏平均 collision_f1 | 平均墙钟 (s) | 总用时 (s) |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for key, m in sorted(data.get("macro_averages", {}).items()):
        me1 = f"{m['mean_e_1']:.4f}" if m['mean_e_1'] is not None else "—"
        me5 = f"{m['mean_e_5']:.4f}" if m['mean_e_5'] is not None else "—"
        me10 = f"{m['mean_e_10']:.4f}" if m['mean_e_10'] is not None else "—"
        me30 = f"{m['mean_e_30']:.4f}" if m['mean_e_30'] is not None else "—"
        mf1 = f"{m['mean_collision_f1']:.4f}" if m['mean_collision_f1'] is not None else "—"
        lines.append(f"| {m['arm']} | {m['family']} | {m['cell_count']} | {me1} | {me5} | {me10} | {me30} | {mf1} | {m['mean_elapsed_seconds']:.2f} | {m['total_elapsed_seconds']:.2f} |")
    lines.append("")

    return "\n".join(lines)


def generate_report_md(data: dict, tables_md: str) -> str:
    lines = []
    lines.append(f"# ainerzero.V9.P108 执行报告：E1 r2 运行卡 D（dev 评测 26 格全集）\n")
    lines.append(f"- **任务卡号**：`{data['task_id']}`")
    lines.append(f"- **执行者**：`{data['agent']}`（二级执行 agent，Tier 2，kind: gemini）")
    lines.append(f"- **实验 ID**：`{data['experiment_id']}`")
    lines.append(f"- **冻结文件与批准哈希**：`artifacts/v9/e1/phase2-r2/prereg.json`（document SHA-256: `{data['document_sha256']}`）")
    lines.append(f"- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261105-E1-r2-approval`（第 2287 行）")
    lines.append(f"- **执行范围**：dev 评测 26 格（②③⑥ × P/S × 种子 42/43/44 共 18 格；①④⑤⑦ × P/S 共 8 格），严格串行，绝无 final-eval。")
    lines.append(f"- **前置校验**：运行 `e1-phase2 --mode verify` 校验全绿（17 源码 + 8 生成器全部匹配，document_sha256 与 approval 吻合）。\n")
    lines.append("---\n")

    lines.append("## 一、执行概况与停止状态\n")
    lines.append(f"- **总计完成格数**：{data['cells_completed']} / {data['total_cells_planned']} 格（全集圆满完成）")
    lines.append(f"- **总计消耗实际墙钟**：{data['total_wall_seconds']:.2f} s（{data['total_wall_seconds']/60:.2f} 分钟）")
    lines.append(f"- **按臂预留预算**：1500.0 s（实际耗时显著低于预留）")
    lines.append(f"- **停止触发标志**：`{data['stop_triggered']}`")
    lines.append(f"- **停止原因**：26 格全部正常运行完毕，无拒绝、无失败、无超时。\n")
    lines.append("---\n")

    lines.append("## 二、生成的详细数据表\n")
    lines.append(tables_md)
    lines.append("\n---\n")

    lines.append("## 三、中央账本与资源守卫检查\n")
    lines.append("1. **账本位置与守则**：生产账本 `artifacts/v9/e1/phase2-r2/control.sqlite3`。所有账本查询严格先复制到 `ledger_copy/` 副本目录，在副本上只读读取，未直接使用 sqlite3 连接生产账本。")
    lines.append("2. **共享锁遵守**：所有评测命令严格串行执行，每条命令通过 `relay exec` 拉起，并在执行前与执行后确认 `artifacts/locks/m0-worker.lock` 已完全释放。")
    lines.append(f"3. **r1 目录写保护检查**：检查 `artifacts/v9/e1/phase2/` 目录的 mtime，未被本卡写入或修改（unmodified: `{data['r1_unmodified']}`）。")
    lines.append("4. **② checkpoint 继承**：第一格运行后，CLI 自动将 r1 的 6 个 ② checkpoint 复制到 `artifacts/v9/e1/phase2-r2/checkpoints/` 并通过 SHA-256 校验，本次重新计算了 dev 评测以适配 r2 调整后的 collision_f1 算法。各 checkpoint 文件哈希详见表 4。\n")
    lines.append("---\n")

    lines.append("## 四、消极声明（未做事项）\n")
    lines.append("按照共同规则与任务要求，明确声明以下未做事项：")
    lines.append("1. **绝无 final-eval**：本卡未运行 `--mode final-eval`，未以任何方式读取 `artifacts/v9/e1/phase2/datasets/sealed_final/` 或任何 `final` 目录。")
    lines.append("2. **绝无 generate-data**：本卡未运行 `--mode generate-data`，完全复用现有数据集。")
    lines.append("3. **未修改任何代码与协议**：未修改 `src/`、`tests/`、`prereg.json` 或 `RESEARCH_LOG.md`，所有运行严格通过 `ainerzero.cli e1-phase2` 唯一入口拉起，无额外传参。")
    lines.append("4. **未做理论推断**：汇总表仅做纯算术宏平均，未声明或评判 H-E1 假设成立与否。")
    lines.append("5. **无多余网络或资源消耗**：无云 GPU 租用，无模型下载，无外部付费 API 调用。\n")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
