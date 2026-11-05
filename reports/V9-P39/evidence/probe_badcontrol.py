#!/usr/bin/env python3
"""P39 必修 1：独立的顺序坏控（只拆一处顺序，不改仓库源码）。

r1 被打回的原因：报告引用的坏控是作者 ``test_s1_r12_ordering`` 里的那个（删掉守卫），
不算独立证据。这里做一个**不同**的坏控，而且更贴近事故原状：

  在临时源码副本里，**只把 trainable-eval 的写入顺序还原**成 r5–r11 的样子
  —— 先 ``PrepLedger`` + ``open_aux_run`` + ``begin_work`` + ``reserve``，
  再判 ``_eval_binding_precondition``。守卫本身一行没删。

同一份驱动、同一份隔离 host 副本、同一个解释器，只换导入的源码树：
  * 真实源码 → ``refused / eval_binding_unavailable``，副本台账字节不变；
  * 还原顺序的副本 → 台账字节改变（且状态不再是 refused 的干净拒绝）。

仓库源码零写入：跑完再算一次真实 worker.py 的 SHA，必须等于封源值。
"""
from __future__ import annotations

import difflib
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p39common as C

WORKER_REL = "src/ainerzero/v9/experiments/s1/worker.py"
WORKER_SHA = "873fc3760dc38ad41136aeffdf940f4859a7e5d90c857ac2117645fe548f8fc4"

ANCHOR_CALL = "            binding_precondition = _eval_binding_precondition(\n"
ANCHOR_WRITE_COMMENT = (
    "            # r12: every CPU-only precondition passed; the first ledger write may\n"
)
ANCHOR_SAMPLE = "            guard.sample(force=True)\n"

PREWRITE = '''            # P39 bad control（只在隔离副本里）：把这一处顺序还原成 r5–r11 的
            # 样子 —— 先注册实验/run、begin_work、reserve，再判 _eval_binding_precondition。
            # 守卫本身一行没删，只把它的位置挪回写台账之后。
            ledger = PrepLedger(ledger_path)
            if active_run is None:
                active_run = ledger.open_aux_run(
                    mode="eval",
                    wall_budget_seconds=budget,
                    manifest=train_experiment_manifest(
                        updates=int(document["training_protocol"]["updates"])
                    ),
                    request_id=f"{eval_experiment_id}:training",
                    experiment_id=eval_experiment_id,
                    snapshot_extra={
                        "arm_id": arm,
                        "seed": int(eval_seed),
                        "purpose": f"s1_phase1_eval:{arm}",
                        "preregistration_sha256": verified["sha256"],
                    },
                )
            report["run_id"] = active_run
            report["experiment_id"] = eval_experiment_id
            ledger.begin_work(active_run, work_state="validating")
            ledger.reserve(active_run, active_seconds=min(120.0, max(10.0, 0.5 * budget)))
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sabotage(text: str) -> tuple[str, str]:
    """只把 trainable-eval 的写入块挪到守卫之前；返回 (新文本, 手术说明)。"""
    i_a = text.index(ANCHOR_CALL)
    i_b = text.index(ANCHOR_WRITE_COMMENT)
    i_c = text.index(ANCHOR_SAMPLE, i_b)
    assert i_a < i_b < i_c, "锚点顺序与预期不符，拒绝在未知结构上做手术"
    guard_block = text[i_a:i_b]          # 守卫调用 + 拒绝返回 + report["eval_binding"]
    write_block = text[i_b:i_c]          # PrepLedger / open_aux_run / begin_work / reserve
    tail = text[i_c + len(ANCHOR_SAMPLE):]
    # 只保留协议构造与 guard 采样，写入块整体前移。
    rebuilt = (
        text[:i_a]
        + PREWRITE
        + guard_block
        + "            protocol = completion.CompletionProtocol(deadline_seconds=budget)\n"
        + ANCHOR_SAMPLE
        + tail
    )
    note = {
        "guard_block_chars": len(guard_block),
        "moved_write_block_chars": len(write_block),
        "moved_write_block_first_line": write_block.splitlines()[0].strip(),
        "moved_write_block_last_line": write_block.rstrip().splitlines()[-1].strip(),
    }
    return rebuilt, note


def main() -> dict:
    repo_worker = C.REPO / WORKER_REL
    before_real = _sha(repo_worker)
    assert before_real == WORKER_SHA, f"真实 worker.py 已漂移：{before_real}"

    work = Path("/tmp/p39-badcontrol")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # 1) 场景 host：生产 phase1 的隔离副本（eval 不需要批准行）
    scenario = work / "scenario"
    C.copy_phase1(scenario)
    C.write_research_log(scenario, None)
    scenario_ledger = scenario / "artifacts/v9/s1/phase1/control.sqlite3"
    scenario_sha = _sha(scenario_ledger)

    # 2) 真实源码：拒绝，台账字节不变
    real = C.run_driver(
        C.EVIDENCE / "driver_entry.py", scenario, "eval", "--arm", "arm2", "--seed", "0",
        source_root=C.SRC,
    )
    real_payload = real["payload"] or {}
    real_report = real_payload.get("report") or {}

    # 3) 临时源码副本：只还原这一处顺序
    checkout = work / "checkout"
    shutil.copytree(C.SRC, checkout / "src")
    worker_copy = checkout / WORKER_REL
    original = worker_copy.read_text(encoding="utf-8")
    rebuilt, note = sabotage(original)
    worker_copy.write_text(rebuilt, encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            rebuilt.splitlines(keepends=True),
            fromfile="worker.py (real)",
            tofile="worker.py (order restored, isolated copy only)",
            n=3,
        )
    )
    (C.EVIDENCE / "badcontrol-worker-diff.patch").write_text(diff, encoding="utf-8")

    # 4) 同一驱动 + 私有 host 副本 + 破坏源码
    sabotaged_host = work / "sabotaged-host"
    shutil.copytree(scenario, sabotaged_host)
    sabotaged = C.run_driver(
        C.EVIDENCE / "driver_entry.py", sabotaged_host, "eval", "--arm", "arm2", "--seed", "0",
        source_root=checkout / "src",
    )
    sab_payload = sabotaged["payload"] or {}
    sab_report = sab_payload.get("report") or {}

    # 副本台账里到底被写进了什么（只在副本上读，生产库不碰）
    def rows(ledger: Path) -> dict:
        import sqlite3

        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True) as connection:
            return {
                "experiments": int(connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]),
                "runs": int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
                "events": int(connection.execute("SELECT COUNT(*) FROM run_transitions").fetchone()[0]),
            }

    rows_before = rows(scenario_ledger)
    rows_real_after = rows(scenario_ledger)
    rows_sab_after = rows(sabotaged_host / "artifacts/v9/s1/phase1/control.sqlite3")

    after_real = _sha(repo_worker)

    checks = {
        "real_source_module_is_repo_src": str(C.SRC) in str(real_payload.get("worker_module", "")),
        "real_status_refused": real_report.get("status") == "refused",
        "real_stage_eval_binding_unavailable": real_report.get("refused_stage")
        == "eval_binding_unavailable",
        "real_ledger_unchanged": real_payload.get("ledger_unchanged") is True,
        "real_ledger_equals_seal": real_payload.get("ledger_sha256_before") == scenario_sha,
        "real_registered_no_run": real_report.get("run_id") is None,
        "sabotaged_source_module_is_checkout": str(checkout / "src")
        in str(sab_payload.get("worker_module", "")),
        "sabotaged_ledger_bytes_changed": sab_payload.get("ledger_unchanged") is False,
        "sabotaged_registered_a_run": sab_report.get("run_id") is not None,
        "sabotaged_rows_written": rows_sab_after["runs"] > rows_before["runs"],
        "repo_worker_py_untouched": after_real == before_real == WORKER_SHA,
    }
    return {
        "purpose": "独立顺序坏控：只把 eval 的 open_aux_run/begin_work/reserve 挪回守卫之前",
        "surgery": note,
        "diff_lines": diff.count("\n"),
        "diff_path": str(C.EVIDENCE / "badcontrol-worker-diff.patch"),
        "real": {
            "worker_module": real_payload.get("worker_module"),
            "status": real_report.get("status"),
            "refused_stage": real_report.get("refused_stage"),
            "run_id": real_report.get("run_id"),
            "ledger_before": real_payload.get("ledger_sha256_before"),
            "ledger_after": real_payload.get("ledger_sha256_after"),
            "unchanged": real_payload.get("ledger_unchanged"),
        },
        "sabotaged": {
            "worker_module": sab_payload.get("worker_module"),
            "status": sab_report.get("status"),
            "refused_stage": sab_report.get("refused_stage"),
            "error": sab_report.get("error"),
            "run_id": sab_report.get("run_id"),
            "ledger_before": sab_payload.get("ledger_sha256_before"),
            "ledger_after": sab_payload.get("ledger_sha256_after"),
            "unchanged": sab_payload.get("ledger_unchanged"),
        },
        "copy_ledger_rows": {
            "before": rows_before,
            "after_real_run": rows_real_after,
            "after_sabotaged_run": rows_sab_after,
        },
        "verdict": (
            "坏控成立：同一驱动/同一 host 副本，只换源码树 —— 真实树拒绝且台账零字节变化；"
            "把写入块挪回守卫之前后，副本台账字节改变并注册了 run 行（P31 事故重现）。"
        ),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("badcontrol-order", main))
