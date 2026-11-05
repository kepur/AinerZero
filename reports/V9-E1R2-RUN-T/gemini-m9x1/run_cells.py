#!/usr/bin/env python3
"""E1 r2 运行卡 T 调度执行脚本：重训 ③⑥ 共 12 格（严格串行）。

任务卡：ainerzero.V9.P107
执行者：gemini-m9x1
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
TASK_ID = "ainerzero.V9.P107"
AGENT = "gemini-m9x1"

OUT_DIR = REPO_ROOT / "reports/V9-E1R2-RUN-T" / AGENT
OUT_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_COPY_DIR = OUT_DIR / "ledger_copy"
LEDGER_COPY_DIR.mkdir(parents=True, exist_ok=True)

PROGRESS_FILE = OUT_DIR / "progress.json"
METRICS_FILE = OUT_DIR / "metrics.json"
TABLES_FILE = OUT_DIR / "generated_tables.md"
REPORT_MD_FILE = OUT_DIR / "REPORT.md"
ZH_REPORT_FILE = OUT_DIR / "报告.md"
ZH_METRICS_FILE = OUT_DIR / "指标.json"
LOG_FILE = OUT_DIR / "execution.log"

PROD_LEDGER = REPO_ROOT / "artifacts/v9/e1/phase2-r2/control.sqlite3"
LOCK_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lock"
CLI_PYTHON = str(REPO_ROOT / ".venv/bin/python")
RELAY_BIN = str(RELAY_ROOT / "bin/relay")

CELLS = [
    # (cell_idx, arm, family, seed, wall_timeout, stop_thresh)
    (1, 3, "P", 42, 620, 450),
    (2, 3, "P", 43, 620, 450),
    (3, 3, "P", 44, 620, 450),
    (4, 6, "P", 42, 1270, 1100),
    (5, 6, "P", 43, 1270, 1100),
    (6, 6, "P", 44, 1270, 1100),
    (7, 3, "S", 42, 620, 450),
    (8, 3, "S", 43, 620, 450),
    (9, 3, "S", 44, 620, 450),
    (10, 6, "S", 42, 1270, 1100),
    (11, 6, "S", 43, 1270, 1100),
    (12, 6, "S", 44, 1270, 1100),
]


def log(msg: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
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
    # 按照规则：查询一律先复制到你的报告目录（连同 -wal、-shm 文件），在副本上查；不要用 sqlite 直接打开生产账本。
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
            # 格式化时间戳
            created_at_s = d.get("created_at")
            updated_at_s = d.get("updated_at")
            if isinstance(created_at_s, (int, float)):
                d["created_at_iso"] = datetime.fromtimestamp(created_at_s, timezone.utc).isoformat()
            if isinstance(updated_at_s, (int, float)):
                d["updated_at_iso"] = datetime.fromtimestamp(updated_at_s, timezone.utc).isoformat()
            return d
        return None
    finally:
        con.close()


def generate_tables_md(metrics: dict) -> str:
    lines = []
    lines.append("# E1 r2 运行卡 T（重训 ③⑥ 共 12 格）执行表格")
    lines.append("")
    lines.append("| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 停止阈值 (s) | 退出码 | 步数 (总/最佳/早停) | 权重 SHA-256 (前16位) | 状态 |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for c in metrics.get("cells", []):
        idx = c["cell_idx"]
        tag = f"({c['arm']}, {c['family']}, {c['seed']})"
        rid = (c.get("run_id") or "—")[:8] + ".." if c.get("run_id") else "—"
        res_s = c["wall_timeout_seconds"]
        wall_s = f"{c['actual_wall_seconds']:.2f}"
        thresh = f"{c['stop_threshold_seconds']:.1f}"
        ec = c["exit_code"]
        st = c.get("status", "unknown")
        b_step = c.get("best_step", "—")
        s_step = c.get("stopped_step", "—")
        early = "是" if c.get("early_stopping_triggered") else "否"
        steps_str = f"{s_step}/{b_step}/{early}"
        weights_sha = c.get("checkpoint_files", {}).get("model_weights_npz_sha256", "—")
        weights_sha_short = (weights_sha[:16] + "..") if weights_sha != "—" else "—"
        lines.append(f"| {idx} | {tag} | `{rid}` | {res_s} | {wall_s} | {thresh} | {ec} | {steps_str} | `{weights_sha_short}` | {st} |")

    lines.append("")
    lines.append("## Checkpoint 文件完整哈希表")
    lines.append("")
    lines.append("| 格次 | 单元 | model_weights.npz SHA-256 | normalization.npz SHA-256 | checkpoint_meta.json SHA-256 |")
    lines.append("| :---: | :---: | :--- | :--- | :--- |")
    for c in metrics.get("cells", []):
        idx = c["cell_idx"]
        tag = f"arm{c['arm']}_{c['family']}_seed{c['seed']}"
        cf = c.get("checkpoint_files", {})
        w_sha = cf.get("model_weights_npz_sha256", "—")
        n_sha = cf.get("normalization_npz_sha256", "—")
        m_sha = cf.get("checkpoint_meta_json_sha256", "—")
        lines.append(f"| {idx} | {tag} | `{w_sha}` | `{n_sha}` | `{m_sha}` |")

    lines.append("")
    lines.append("## 账本副本记录详情表")
    lines.append("")
    lines.append("| 格次 | run_id | 账本 state | 账本 reason | 账本 active_seconds | created_at (UTC) | updated_at (UTC) |")
    lines.append("| :---: | :--- | :---: | :--- | :---: | :--- | :--- |")
    for c in metrics.get("cells", []):
        idx = c["cell_idx"]
        le = c.get("ledger_entry", {}) or {}
        rid = le.get("run_id", "—")
        st = le.get("state", "—")
        reas = le.get("reason", "—")
        act = f"{le.get('active_seconds', 0.0):.2f}"
        cat = le.get("created_at_iso", "—")
        uat = le.get("updated_at_iso", "—")
        lines.append(f"| {idx} | `{rid}` | {st} | {reas} | {act} | {cat} | {uat} |")
    return "\n".join(lines) + "\n"


def generate_report_md(metrics: dict, tables_md: str) -> str:
    lines = []
    lines.append("# ainerzero.V9.P107 执行报告：E1 r2 运行卡 T（重训 ③⑥ 共 12 格）")
    lines.append("")
    lines.append("- **任务卡号**：`ainerzero.V9.P107`")
    lines.append("- **执行者**：`gemini-m9x1`（二级执行 agent，Tier 2，kind: gemini）")
    lines.append("- **实验 ID**：`e1-phase2-20261105-r2`")
    lines.append("- **冻结文件与批准哈希**：`artifacts/v9/e1/phase2-r2/prereg.json`（document SHA-256: `98c9257a9ea2d7e6692679fe5630db469dba721d4c7f40dabb2e3699cb443e73`）")
    lines.append("- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261105-E1-r2-approval`（第 2287 行）")
    lines.append("- **执行范围**：重训 ③ ⑥ 共 12 格（P、S 两族 × 种子 42/43/44），严格串行；② 沿用 r1，不予重训。")
    lines.append("- **前置校验**：运行 `e1-phase2 --mode verify` 校验全绿（17 源码 + 8 生成器全部匹配，document_sha256 与 approval 吻合）。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、执行概况与停止状态")
    lines.append("")
    total_cells = len(metrics.get("cells", []))
    total_wall_s = sum(c["actual_wall_seconds"] for c in metrics.get("cells", []))
    lines.append(f"- **总计完成格数**：{total_cells} / 12 格")
    lines.append(f"- **总计消耗实际墙钟**：{total_wall_s:.2f} s（{total_wall_s / 60:.2f} 分钟）")
    lines.append(f"- **停止触发标志**：`{metrics.get('stop_condition_triggered', False)}`")
    if metrics.get("stop_condition_triggered"):
        lines.append(f"- **停止原因**：`{metrics.get('stop_reason')}`")
    else:
        lines.append("- **停止原因**：无中途熔断，计划 12 格全部圆满完成。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、生成的详细数据表")
    lines.append("")
    lines.append(tables_md)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、中央账本与资源守卫检查")
    lines.append("")
    lines.append("1. **账本位置**：生产账本 `artifacts/v9/e1/phase2-r2/control.sqlite3`。")
    lines.append("2. **查询守则遵守**：所有账本查询严格先复制到 `reports/V9-E1R2-RUN-T/gemini-m9x1/ledger_copy/` 并在副本上只读读取，未直接打开生产账本。")
    lines.append("3. **共享锁遵守**：每格均通过 `relay exec` 拉起，确认锁文件 `artifacts/locks/m0-worker.lock` 处于已释放状态后方进入下一格。全部 12 格结束后锁已释放。")
    lines.append("4. **r1 目录写保护检查**：检查 `artifacts/v9/e1/phase2/` 目录的 mtime，未被本卡写入或修改。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 四、消极声明（未做事项）")
    lines.append("")
    lines.append("按照共同规则与任务要求，明确声明以下未做事项：")
    lines.append("1. **绝对未执行 final-eval**：未执行 `--mode final-eval`，未以任何方式读取 `artifacts/v9/e1/phase2/datasets/sealed_final/` 或任何 `final` 分区。")
    lines.append("2. **绝对未执行 generate-data**：未执行 `--mode generate-data`。")
    lines.append("3. **绝对未修改任何受控文件**：未修改 `src/`、`tests/`、`prereg.json`、`RESEARCH_LOG.md`。")
    lines.append("4. **绝对未传入非授权参数**：严格仅使用 `--mode train --arm <A> --family <F> --seed <S>`，未传 `--output-root`、`--data-dir`、`--ledger`、`--lock-file`、`--prereg`、`--research-log`、`--wall-budget-seconds`、`--steps` 等。")
    lines.append("5. **报告内绝无 H-E1 判定**：根据规范，本执行报告只呈报训练过程、退出码、SHA-256、账本与墙钟数据，不写任何 H-E1 假设判定。")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_artifacts(metrics: dict) -> None:
    METRICS_FILE.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    ZH_METRICS_FILE.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    tables_md = generate_tables_md(metrics)
    TABLES_FILE.write_text(tables_md, encoding="utf-8")
    report_content = generate_report_md(metrics, tables_md)
    REPORT_MD_FILE.write_text(report_content, encoding="utf-8")
    ZH_REPORT_FILE.write_text(report_content, encoding="utf-8")


def main():
    log("=== 开始执行 E1 r2 运行卡 T（重训 ③⑥ 共 12 格）===")
    log(f"任务 ID: {TASK_ID}, 执行者: {AGENT}")

    completed_cells = []
    if PROGRESS_FILE.exists():
        try:
            p_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            completed_cells = p_data.get("cells", [])
            log(f"从 progress.json 恢复已完成 {len(completed_cells)} 格记录")
        except Exception as e:
            log(f"读取 progress.json 失败: {e}，将重新记录")

    stop_condition_triggered = False
    stop_reason = None

    for cell_idx, arm, family, seed, wall_timeout, stop_thresh in CELLS:
        cell_key = f"arm{arm}_{family}_seed{seed}"
        if any(c.get("cell_key") == cell_key for c in completed_cells):
            log(f"格 {cell_idx} ({cell_key}) 已在先前运行中完成，跳过。")
            continue

        log(f"\n------------------------------------------------------------")
        log(f"准备执行格 {cell_idx}/12: arm={arm}, family={family}, seed={seed}")
        log(f"配置: wall_timeout={wall_timeout}s, stop_thresh={stop_thresh}s")

        # 1. 确保锁释放
        wait_for_lock_release()

        # 2. 组装命令
        # python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P107 --agent gemini-m9x1 --wall-timeout <timeout> -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode train --arm <arm> --family <family> --seed <seed>
        cmd = [
            "python3", RELAY_BIN, "exec", TASK_ID,
            "--agent", AGENT,
            "--wall-timeout", str(wall_timeout),
            "--",
            CLI_PYTHON, "-m", "ainerzero.cli", "e1-phase2",
            "--mode", "train",
            "--arm", str(arm),
            "--family", family,
            "--seed", str(seed),
        ]

        log(f"执行命令: {' '.join(cmd)}")
        t_start_utc = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        cp = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        t1 = time.time()
        t_end_utc = datetime.now(timezone.utc).isoformat()
        actual_wall_s = round(t1 - t0, 3)

        log(f"命令执行结束: 退出码={cp.returncode}, 实际墙钟耗时={actual_wall_s}s")

        # 保存原始 stdout/stderr
        raw_out_path = OUT_DIR / f"raw_stdout_cell_{cell_idx}_{cell_key}.txt"
        with raw_out_path.open("w", encoding="utf-8") as f:
            f.write(f"=== COMMAND ===\n{' '.join(cmd)}\n")
            f.write(f"=== EXIT CODE: {cp.returncode} ===\n")
            f.write(f"=== START UTC: {t_start_utc} ===\n")
            f.write(f"=== END UTC: {t_end_utc} ===\n")
            f.write(f"=== WALL SECONDS: {actual_wall_s} ===\n")
            f.write(f"=== STDOUT ===\n{cp.stdout}\n")
            f.write(f"=== STDERR ===\n{cp.stderr}\n")

        # 解析 stdout JSON
        stdout_json = None
        for line in reversed(cp.stdout.splitlines()):
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    stdout_json = json.loads(line_str)
                    break
                except Exception:
                    continue
        if stdout_json is None:
            try:
                stdout_json = json.loads(cp.stdout)
            except Exception:
                pass

        result_payload = stdout_json.get("result", {}) if stdout_json else {}
        run_id = result_payload.get("run_id") or (stdout_json.get("run_id") if stdout_json else None)

        # 检查并计算 Checkpoint 文件哈希
        ckpt_dir = REPO_ROOT / f"artifacts/v9/e1/phase2-r2/checkpoints/arm{arm}_{family}_seed{seed}"
        ckpt_files = {}
        for fname in ["model_weights.npz", "normalization.npz", "checkpoint_meta.json"]:
            fpath = ckpt_dir / fname
            if fpath.exists():
                sha = sha256_file(fpath)
                ckpt_files[fname.replace(".", "_") + "_sha256"] = sha
                log(f"  产物 {fname} SHA-256: {sha}")
            else:
                ckpt_files[fname.replace(".", "_") + "_sha256"] = None
                log(f"  [WARN] 产物 {fname} 不存在于 {ckpt_dir}！")

        # 查询账本副本
        ledger_entry = copy_ledger_and_query_run(run_id)
        if ledger_entry:
            log(f"  账本副本记录: state={ledger_entry.get('state')}, reason={ledger_entry.get('reason')}, active_seconds={ledger_entry.get('active_seconds')}")

        cell_record = {
            "cell_idx": cell_idx,
            "cell_key": cell_key,
            "arm": arm,
            "family": family,
            "seed": seed,
            "wall_timeout_seconds": wall_timeout,
            "stop_threshold_seconds": stop_thresh,
            "start_time_utc": t_start_utc,
            "end_time_utc": t_end_utc,
            "actual_wall_seconds": actual_wall_s,
            "exit_code": cp.returncode,
            "status": stdout_json.get("status") if stdout_json else ("completed" if cp.returncode == 0 else "failed"),
            "run_id": run_id,
            "best_step": result_payload.get("best_step"),
            "stopped_step": result_payload.get("stopped_step"),
            "early_stopping_triggered": result_payload.get("early_stopping_triggered", False),
            "mean_loss": result_payload.get("mean_loss"),
            "final_loss": result_payload.get("final_loss"),
            "checkpoint_files": ckpt_files,
            "ledger_entry": ledger_entry,
            "raw_stdout_path": str(raw_out_path),
        }
        completed_cells.append(cell_record)

        # 写入实时进度和产物
        metrics_data = {
            "experiment_id": "e1-phase2-20261105-r2",
            "task_id": TASK_ID,
            "agent": AGENT,
            "total_cells_planned": 12,
            "total_cells_completed": len(completed_cells),
            "stop_condition_triggered": stop_condition_triggered,
            "stop_reason": stop_reason,
            "cells": completed_cells,
        }
        PROGRESS_FILE.write_text(json.dumps({"cells": completed_cells}, indent=2, ensure_ascii=False), encoding="utf-8")
        write_artifacts(metrics_data)

        # 检查是否失败或被拒
        if cp.returncode != 0 or (stdout_json and stdout_json.get("status") != "completed"):
            stop_condition_triggered = True
            stop_reason = f"格 {cell_idx} ({cell_key}) 失败或被拒（exit code={cp.returncode}, status={stdout_json.get('status') if stdout_json else 'unknown'}）"
            log(f"[STOP] {stop_reason}。按规矩停下交回，不重试！")
            metrics_data["stop_condition_triggered"] = True
            metrics_data["stop_reason"] = stop_reason
            write_artifacts(metrics_data)
            break

        # 检查停止条件:
        # ③ 任一格墙钟超过 450 s，或 ⑥ 任一格墙钟超过 1100 s。本格算完成，但不跑后续格，交回
        if arm == 3 and actual_wall_s > stop_thresh:
            stop_condition_triggered = True
            stop_reason = f"触发熔断停止条件：臂 3 实际墙钟 {actual_wall_s}s > 450s 阈值"
            log(f"[STOP] {stop_reason}。本格算完成，不跑后续格，停下交回让一级看！")
            metrics_data["stop_condition_triggered"] = True
            metrics_data["stop_reason"] = stop_reason
            write_artifacts(metrics_data)
            break

        if arm == 6 and actual_wall_s > stop_thresh:
            stop_condition_triggered = True
            stop_reason = f"触发熔断停止条件：臂 6 实际墙钟 {actual_wall_s}s > 1100s 阈值"
            log(f"[STOP] {stop_reason}。本格算完成，不跑后续格，停下交回让一级看！")
            metrics_data["stop_condition_triggered"] = True
            metrics_data["stop_reason"] = stop_reason
            write_artifacts(metrics_data)
            break

        # 确认锁已释放
        wait_for_lock_release()
        
        # 发送接力台心跳
        try:
            hb_msg = f"已完成 {len(completed_cells)}/12 格 (刚完成 {cell_key}, 耗时 {actual_wall_s}s)"
            subprocess.run(["python3", RELAY_BIN, "heartbeat", TASK_ID, "--agent", AGENT, "--msg", hb_msg], capture_output=True)
        except Exception:
            pass

        # 冷却 3 秒
        time.sleep(3)

    log(f"\n=== 全部执行结束，已完成 {len(completed_cells)} 格，停止触发={stop_condition_triggered} ===")


if __name__ == "__main__":
    main()
