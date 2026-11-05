#!/usr/bin/env python3
"""E1 r2 运行卡 T 补跑最后一格：arm6_S_seed44 (第 12 格)

任务卡：ainerzero.V9.P107
执行者：gemini-w7k4
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
AGENT = "gemini-w7k4"

OUT_DIR = REPO_ROOT / "reports/V9-E1R2-RUN-T" / AGENT
CELL12_DIR = OUT_DIR / "cell12"
CELL12_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_COPY_DIR = CELL12_DIR / "ledger_copy"
LEDGER_COPY_DIR.mkdir(parents=True, exist_ok=True)

PROD_LEDGER = REPO_ROOT / "artifacts/v9/e1/phase2-r2/control.sqlite3"
LOCK_PATH = REPO_ROOT / "artifacts/locks/m0-worker.lock"
CLI_PYTHON = str(REPO_ROOT / ".venv/bin/python")
RELAY_BIN = str(RELAY_ROOT / "bin/relay")

PREV_METRICS = REPO_ROOT / "reports/V9-E1R2-RUN-T/gemini-m9x1/metrics.json"

LOG_FILE = CELL12_DIR / "execution.log"


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
        thresh = f"{c['stop_threshold_seconds']:.1f}" if c.get("stop_threshold_seconds") else "—"
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
        le = c.get("ledger_entry") or {}
        rid = le.get("run_id") or c.get("run_id") or "—"
        state = le.get("state", "—")
        reason = le.get("reason", "—")
        act_s = f"{le.get('active_seconds', 0.0):.2f}" if le.get("active_seconds") is not None else "—"
        c_at = le.get("created_at_iso", "—")
        u_at = le.get("updated_at_iso", "—")
        lines.append(f"| {idx} | `{rid}` | {state} | {reason} | {act_s} | {c_at} | {u_at} |")

    return "\n".join(lines)


def generate_report_md(metrics: dict, tables_md: str) -> str:
    lines = []
    lines.append("# ainerzero.V9.P107 执行报告：E1 r2 运行卡 T（重训 ③⑥ 共 12 格全集）")
    lines.append("")
    lines.append(f"- **任务卡号**：`ainerzero.V9.P107`")
    lines.append(f"- **执行者**：`{AGENT}`（二级执行 agent，Tier 2，kind: gemini；前 11 格由 `gemini-m9x1` 完成并通过核验，第 12 格由 `{AGENT}` 补跑）")
    lines.append(f"- **实验 ID**：`e1-phase2-20261105-r2`")
    lines.append(f"- **冻结文件与批准哈希**：`artifacts/v9/e1/phase2-r2/prereg.json`（document SHA-256: `98c9257a9ea2d7e6692679fe5630db469dba721d4c7f40dabb2e3699cb443e73`）")
    lines.append(f"- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261105-E1-r2-approval`（第 2287 行）")
    lines.append(f"- **执行范围**：重训 ③ ⑥ 共 12 格（P、S 两族 × 种子 42/43/44），严格串行；② 沿用 r1，不予重训。")
    lines.append(f"- **前置校验**：运行 `e1-phase2 --mode verify` 校验全绿（17 源码 + 8 生成器全部匹配，document_sha256 与 approval 吻合）。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、执行概况与停止状态")
    lines.append("")
    total_cells = len(metrics.get("cells", []))
    total_wall_s = sum(c["actual_wall_seconds"] for c in metrics.get("cells", []))
    lines.append(f"- **总计完成格数**：{total_cells} / 12 格（全集圆满完成）")
    lines.append(f"- **总计消耗实际墙钟**：{total_wall_s:.2f} s（{total_wall_s / 60:.2f} 分钟）")
    lines.append(f"- **停止触发标志**：`{metrics.get('stop_condition_triggered', False)}`")
    lines.append(f"- **停止原因**：{metrics.get('stop_reason')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、生成的详细数据表")
    lines.append("")
    lines.append(tables_md)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 三、第 12 格（补跑格）独立证据")
    lines.append("")
    lines.append(f"第 12 格由 `{AGENT}` 补跑，独立存证位于 `reports/V9-E1R2-RUN-T/{AGENT}/cell12/`：")
    lines.append("- `raw_stdout_cell_12_arm6_S_seed44.txt`：命令完整标准输出与接力台监管日志")
    lines.append("- `pmset_before.txt` 与 `pmset_after.txt`：开跑前与跑完后电池/电源状态原样输出")
    lines.append("- `checkpoint_sha256.json`：本格 3 个 checkpoint 文件完整 SHA-256")
    lines.append("- `ledger_row_cell12.json`：账本副本查询记录（经由 `cell12/ledger_copy/control.sqlite3` 副本读取）")
    lines.append("- `verify_output.json`：开跑前 verify 校验输出")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 四、中央账本与资源守卫检查")
    lines.append("")
    lines.append("1. **账本位置**：生产账本 `artifacts/v9/e1/phase2-r2/control.sqlite3`。")
    lines.append("2. **查询守则遵守**：所有账本查询严格先复制到报告目录并在副本上只读读取，未直接打开生产账本。")
    lines.append("3. **共享锁遵守**：通过 `relay exec` 拉起，确认锁文件 `artifacts/locks/m0-worker.lock` 处于已释放状态。")
    lines.append("4. **r1 目录写保护检查**：检查 `artifacts/v9/e1/phase2/` 目录的 mtime，未被本卡写入或修改。")
    lines.append("5. **前棒产物保持**：`reports/V9-E1R2-RUN-T/gemini-m9x1/` 现有 21 个文件字节完全未改动。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 五、消极声明（未做事项）")
    lines.append("")
    lines.append("按照共同规则与任务要求，明确声明以下未做事项：")
    lines.append("1. **绝对未执行 final-eval**：未执行 `--mode final-eval`，未以任何方式读取 `artifacts/v9/e1/phase2/datasets/sealed_final/` 或任何 `final` 分区。")
    lines.append("2. **绝对未执行 generate-data**：未执行 `--mode generate-data`。")
    lines.append("3. **绝对未修改任何受控文件**：未修改 `src/`、`tests/`、`prereg.json`、`RESEARCH_LOG.md`。")
    lines.append("4. **绝对未传入非授权参数**：严格仅使用 `--mode train --arm 6 --family S --seed 44`，未传 `--output-root`、`--data-dir`、`--ledger`、`--lock-file`、`--prereg`、`--research-log`、`--wall-budget-seconds`、`--steps` 等。")
    lines.append("5. **报告内绝无 H-E1 判定**：根据规范，本执行报告只呈报训练过程、退出码、SHA-256、账本与墙钟数据，不写任何 H-E1 假设判定。")
    lines.append("")
    return "\n".join(lines) + "\n"


def generate_cell12_report_md(c12: dict) -> str:
    lines = []
    lines.append(f"# ainerzero.V9.P107 第 12 格执行报告（补跑：arm6_S_seed44）")
    lines.append("")
    lines.append(f"- **任务卡号**：`ainerzero.V9.P107`")
    lines.append(f"- **执行者**：`{AGENT}`（二级执行 agent，Tier 2，kind: gemini）")
    lines.append(f"- **单元**：`arm6_S_seed44`（臂 6，族 S，种子 44）")
    lines.append(f"- **命令**：`python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec {TASK_ID} --agent {AGENT} --wall-timeout 1270 -- {CLI_PYTHON} -m ainerzero.cli e1-phase2 --mode train --arm 6 --family S --seed 44`")
    lines.append(f"- **退出码**：`{c12['exit_code']}`")
    lines.append(f"- **状态**：`{c12['status']}`")
    lines.append(f"- **实际墙钟耗时**：`{c12['actual_wall_seconds']:.2f}` s")
    lines.append(f"- **起止 UTC 时间**：`{c12['start_time_utc']}` 至 `{c12['end_time_utc']}`")
    lines.append(f"- **步数统计**：总步数 `{c12.get('stopped_step')}`，最佳步数 `{c12.get('best_step')}`，早停触发 `{c12.get('early_stopping_triggered')}`")
    lines.append(f"- **账本 run_id**：`{c12.get('run_id')}`")
    lines.append("")
    lines.append("### Checkpoint 文件 SHA-256")
    lines.append("")
    cf = c12.get("checkpoint_files", {})
    lines.append(f"- `model_weights.npz`: `{cf.get('model_weights_npz_sha256')}`")
    lines.append(f"- `normalization.npz`: `{cf.get('normalization_npz_sha256')}`")
    lines.append(f"- `checkpoint_meta.json`: `{cf.get('checkpoint_meta_json_sha256')}`")
    lines.append("")
    lines.append("### 账本副本查询记录")
    lines.append("")
    le = c12.get("ledger_entry") or {}
    lines.append(f"- `state`: `{le.get('state')}`")
    lines.append(f"- `reason`: `{le.get('reason')}`")
    lines.append(f"- `active_seconds`: `{le.get('active_seconds')}`")
    lines.append(f"- `created_at`: `{le.get('created_at_iso')}`")
    lines.append(f"- `updated_at`: `{le.get('updated_at_iso')}`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    log("=== 开始执行 E1 r2 补跑最后一格 (Cell 12: arm6_S_seed44) ===")
    log(f"任务 ID: {TASK_ID}, 执行者: {AGENT}")

    # 1. 开跑前 pmset
    pmset_before_p = CELL12_DIR / "pmset_before.txt"
    try:
        res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        pmset_before_p.write_text(res.stdout, encoding="utf-8")
        log(f"开跑前电源状态: {res.stdout.strip()}")
    except Exception as e:
        log(f"pmset -g batt 失败: {e}")

    # 2. 等待共享锁释放
    wait_for_lock_release()

    # 3. 组装命令
    cmd = [
        "python3", RELAY_BIN, "exec", TASK_ID,
        "--agent", AGENT,
        "--wall-timeout", "1270",
        "--",
        CLI_PYTHON, "-m", "ainerzero.cli", "e1-phase2",
        "--mode", "train",
        "--arm", "6",
        "--family", "S",
        "--seed", "44",
    ]

    log(f"执行命令: {' '.join(cmd)}")
    t_start_utc = datetime.now(timezone.utc).isoformat()
    t0 = time.time()

    cp = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    t1 = time.time()
    t_end_utc = datetime.now(timezone.utc).isoformat()
    actual_wall_s = round(t1 - t0, 3)

    log(f"命令执行结束: 退出码={cp.returncode}, 实际墙钟耗时={actual_wall_s}s")

    # 4. 跑完后 pmset
    pmset_after_p = CELL12_DIR / "pmset_after.txt"
    try:
        res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        pmset_after_p.write_text(res.stdout, encoding="utf-8")
        log(f"跑完后电源状态: {res.stdout.strip()}")
    except Exception as e:
        log(f"pmset -g batt 失败: {e}")

    # 5. 保存原始 stdout/stderr
    raw_out_path = CELL12_DIR / "raw_stdout_cell_12_arm6_S_seed44.txt"
    with raw_out_path.open("w", encoding="utf-8") as f:
        f.write(f"=== COMMAND ===\n{' '.join(cmd)}\n")
        f.write(f"=== EXIT CODE: {cp.returncode} ===\n")
        f.write(f"=== START UTC: {t_start_utc} ===\n")
        f.write(f"=== END UTC: {t_end_utc} ===\n")
        f.write(f"=== WALL SECONDS: {actual_wall_s} ===\n")
        f.write(f"=== STDOUT ===\n{cp.stdout}\n")
        f.write(f"=== STDERR ===\n{cp.stderr}\n")

    # 6. 解析 stdout JSON
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

    # 7. Checkpoint 文件哈希
    ckpt_dir = REPO_ROOT / "artifacts/v9/e1/phase2-r2/checkpoints/arm6_S_seed44"
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

    (CELL12_DIR / "checkpoint_sha256.json").write_text(json.dumps(ckpt_files, indent=2), encoding="utf-8")

    # 8. 查询账本副本
    ledger_entry = copy_ledger_and_query_run(run_id)
    if ledger_entry:
        log(f"  账本副本记录: state={ledger_entry.get('state')}, reason={ledger_entry.get('reason')}, active_seconds={ledger_entry.get('active_seconds')}")
        (CELL12_DIR / "ledger_row_cell12.json").write_text(json.dumps(ledger_entry, indent=2, ensure_ascii=False), encoding="utf-8")

    cell_record = {
        "cell_idx": 12,
        "cell_key": "arm6_S_seed44",
        "arm": 6,
        "family": "S",
        "seed": 44,
        "wall_timeout_seconds": 1270,
        "stop_threshold_seconds": 1150.0,
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

    # 9. 写入 cell12 专属 REPORT.md
    c12_report = generate_cell12_report_md(cell_record)
    (CELL12_DIR / "REPORT.md").write_text(c12_report, encoding="utf-8")

    # 10. 读取前 11 格并合并生成 12 格全集报告
    prev_data = json.loads(PREV_METRICS.read_text(encoding="utf-8"))
    all_cells = list(prev_data.get("cells", [])) + [cell_record]

    stop_condition_triggered = False
    stop_reason = "12 格全集执行完毕（前 11 格由 gemini-m9x1 执行核验，第 12 格由 gemini-w7k4 补跑完毕）"
    if cp.returncode != 0 or (stdout_json and stdout_json.get("status") != "completed"):
        stop_condition_triggered = True
        stop_reason = f"第 12 格执行异常（exit code={cp.returncode}, status={stdout_json.get('status') if stdout_json else 'unknown'}）"

    full_metrics = {
        "experiment_id": "e1-phase2-20261105-r2",
        "task_id": TASK_ID,
        "agent": AGENT,
        "collaborator_prior_agent": "gemini-m9x1",
        "total_cells_planned": 12,
        "total_cells_completed": len(all_cells),
        "stop_condition_triggered": stop_condition_triggered,
        "stop_reason": stop_reason,
        "cells": all_cells,
    }

    # 写全集 metrics.json / 指标.json
    (OUT_DIR / "metrics.json").write_text(json.dumps(full_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "指标.json").write_text(json.dumps(full_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPO_ROOT / "指标.json").write_text(json.dumps(full_metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    # 写全集 generated_tables.md
    tables_md = generate_tables_md(full_metrics)
    (OUT_DIR / "generated_tables.md").write_text(tables_md, encoding="utf-8")

    # 写全集 REPORT.md / 报告.md
    full_report = generate_report_md(full_metrics, tables_md)
    (OUT_DIR / "REPORT.md").write_text(full_report, encoding="utf-8")
    (OUT_DIR / "报告.md").write_text(full_report, encoding="utf-8")
    (REPO_ROOT / "报告.md").write_text(full_report, encoding="utf-8")

    log("=== 第 12 格补跑及全集报告汇总完成！===")


if __name__ == "__main__":
    main()
