#!/usr/bin/env python3
"""E1 运行卡 B-P: 训练 P 族 9 格自动化调度执行脚本。

执行者: gemini-v9m3
任务卡: ainerzero.V9.P100
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
RELAY_ROOT = Path("/Users/mac/AinerWorkFlow/AinerRelay").resolve()
TASK_ID = "ainerzero.V9.P100"
AGENT = "gemini-v9m3"

OUT_DIR = REPO_ROOT / "reports/V9-E1RUN-B-P" / AGENT
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_FILE = OUT_DIR / "progress.json"
LOG_FILE = OUT_DIR / "execution.log"

DB_PATH = REPO_ROOT / "artifacts/v9/e1/phase2/control.sqlite3"
LOCK_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lock"
CLI_PYTHON = str(REPO_ROOT / ".venv/bin/python")
RELAY_BIN = str(RELAY_ROOT / "bin/relay")

CELLS = [
    # (arm, seed, budget_seconds, stop_threshold_seconds)
    (6, 42, 1100, 1000),
    (6, 43, 1100, 1000),
    (6, 44, 1100, 1000),
    (2, 42, 450, 400),
    (2, 43, 450, 400),
    (2, 44, 450, 400),
    (3, 42, 450, 400),
    (3, 43, 450, 400),
    (3, 44, 450, 400),
]


def log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(131072):
            h.update(chunk)
    return h.hexdigest()


def get_latest_run_entry(run_id: str | None = None) -> dict | None:
    if not DB_PATH.exists():
        return None
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    if run_id:
        row = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    else:
        row = con.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
    res = dict(row) if row else None
    con.close()
    return res


def main():
    log(f"开始执行 E1 运行卡 B-P 训练流程，计划 9 格...")
    
    # 读取已有进度（断点续训/恢复保护）
    completed_cells = []
    if PROGRESS_FILE.exists():
        try:
            progress_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            completed_cells = progress_data.get("cells", [])
            log(f"从 progress.json 恢复已完成 {len(completed_cells)} 格记录")
        except Exception as e:
            log(f"读取 progress.json 失败: {e}，将重新建立")

    for arm, seed, budget, stop_thresh in CELLS:
        cell_key = f"arm_{arm}_seed_{seed}"
        if any(c.get("cell_key") == cell_key for c in completed_cells):
            log(f"格 ({arm}, {seed}) 已在先前运行中完成，跳过")
            continue

        log(f"\n==========================================")
        log(f"准备运行格: arm={arm}, seed={seed}, wall_budget={budget}s, stop_thresh={stop_thresh}s")
        
        # 确认锁状态
        if LOCK_PATH.exists() and LOCK_PATH.read_text().strip():
            log(f"[WARN] 锁文件存在残留: {LOCK_PATH.read_text().strip()}，等待 3s 确认...")
            time.sleep(3)

        cmd = [
            "python3", RELAY_BIN, "exec", TASK_ID, "--agent", AGENT, "--",
            CLI_PYTHON, "-m", "ainerzero.cli", "e1-phase2",
            "--mode", "train",
            "--arm", str(arm),
            "--family", "P",
            "--seed", str(seed),
            "--wall-budget-seconds", str(budget),
        ]
        log(f"执行命令: {' '.join(cmd)}")
        
        t0 = time.time()
        cp = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        wall_time = round(time.time() - t0, 3)
        log(f"执行结束，耗时 {wall_time}s，退出码 {cp.returncode}")

        # 解析输出
        stdout_json = None
        for line in reversed(cp.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    stdout_json = json.loads(line)
                    break
                except Exception:
                    continue
        if stdout_json is None:
            try:
                stdout_json = json.loads(cp.stdout)
            except Exception:
                pass

        log(f"stdout 片段: {cp.stdout[-300:].strip()}")
        if cp.stderr:
            log(f"stderr 片段: {cp.stderr[-300:].strip()}")

        run_id = None
        result_payload = {}
        if stdout_json:
            result_payload = stdout_json.get("result", {})
            run_id = result_payload.get("run_id") or stdout_json.get("run_id")

        ledger_entry = get_latest_run_entry(run_id)

        # 检查 checkpoint 路径与 SHA
        ckpt_path_str = result_payload.get("checkpoint_path")
        ckpt_sha = None
        if ckpt_path_str:
            ckpt_path = Path(ckpt_path_str)
            if ckpt_path.exists():
                ckpt_sha = sha256_file(ckpt_path)
                log(f"Checkpoint 文件就绪: {ckpt_path.name}, SHA: {ckpt_sha[:16]}...")
            else:
                log(f"[WARN] Checkpoint 文件不存在: {ckpt_path_str}")

        cell_record = {
            "cell_key": cell_key,
            "arm": arm,
            "family": "P",
            "seed": seed,
            "wall_budget_seconds": budget,
            "stop_threshold_seconds": stop_thresh,
            "actual_wall_seconds": wall_time,
            "exit_code": cp.returncode,
            "stdout_json": stdout_json,
            "run_id": run_id,
            "best_step": result_payload.get("best_step"),
            "early_stopping_triggered": result_payload.get("early_stopping_triggered", False),
            "active_seconds": result_payload.get("active_seconds") or (ledger_entry.get("active_seconds") if ledger_entry else None),
            "checkpoint_path": ckpt_path_str,
            "checkpoint_sha256": ckpt_sha,
            "ledger_entry": ledger_entry,
        }
        completed_cells.append(cell_record)
        
        # 实时保存进度
        PROGRESS_FILE.write_text(json.dumps({"cells": completed_cells}, indent=2, ensure_ascii=False), encoding="utf-8")

        # 检查失败或被拒
        if cp.returncode != 0 or (stdout_json and stdout_json.get("status") != "completed"):
            log(f"[STOP] 格 ({arm}, {seed}) 失败或被拒（exit code={cp.returncode}）。按照规则立即停下交回，不重试！")
            break

        # 检查熔断停跑条件:
        # ⑥ 任一格实际墙钟超过 1000 s，或 ②③ 任一格超过 400 s
        if arm == 6 and wall_time > 1000:
            log(f"[STOP] 触发熔断条件: 臂 6 实际墙钟 {wall_time}s > 1000s。停下上报，不跑后续格！")
            break
        if arm in (2, 3) and wall_time > 400:
            log(f"[STOP] 触发熔断条件: 臂 {arm} 实际墙钟 {wall_time}s > 400s。停下上报，不跑后续格！")
            break

        # 短暂休息 2 秒，确保锁释放与状态机同步
        time.sleep(2)

    log(f"\n全部执行循环结束，总计完成 {len(completed_cells)} 格记录。")


if __name__ == "__main__":
    main()
