#!/usr/bin/env python3
"""P25 独立复核 R2：_complete_run 的完成前置条件 + 拆守卫坏控。

step5p-9q4t 自写探针（不导入、不调用 r9 作者测试 test_s1_r9_* 的任何断言）。
全部使用临时卡内 RunStore（reports/V9-P25/.tmp-r2/），不碰中央台账、无模型工作。

场景（对应 P15-R8-DECISION R2 与 P24 F1 探针的 before/inside/after 三个截断点）：
  before  首次调用被拒（截止前超时）并写下 completion_invalid.json 后，
          再次调用内部 _complete_run 不得报 completed，并如实报告账本状态
  inside/after  提交已落地（行已 completed）且标记已写，再次调用必须拒绝
  terminal_without_marker  无标记但账本已是 failed 终态，必须拒绝
  sabotage 坏控：隔离源码副本里只拆 _completion_precondition 守卫，
          P24 F1 缺陷必须复现（报 completed 而行仍是 failed）——守卫必须变红
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRATCH = REPO / "reports/V9-P25/.tmp-r2"
LOGS = REPO / "reports/V9-P25/logs"

_parser = argparse.ArgumentParser()
_parser.add_argument("--sabotage-child", type=str, default=None)
_args = _parser.parse_args()

if _args.sabotage_child:
    sys.path.insert(0, str(Path(_args.sabotage_child)))
else:
    sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import completion, worker  # noqa: E402

UPDATES = 3510
DEADLINE = 450.0
DOCUMENT = {
    "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
    "timing": {"deadline_seconds": DEADLINE},
    "data_identity": {"dataset_digest": "e" * 64},
}
APPROVAL = {"document_sha256": "d" * 64, "line": "p25 probe", "line_number": 1}

OUT_JSON = LOGS / "r2-completion-precondition.json"


def _ledger(name: str):
    root = SCRATCH / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    run_id = worker._open_train_run(DOCUMENT, ledger, APPROVAL, arm_id="arm2", seed=0)
    ledger.begin_work(run_id, work_state="training")
    return root, ledger, run_id


def _complete(ledger, run_id, root, *, protocol):
    return worker._complete_run(
        report={"schema": "ainerzero.v9.s1.p25.r2_probe.v1", "mode": "train"},
        ledger=ledger,
        run_id=run_id,
        protocol=protocol,
        output_root=root,
        reason="s1_train_completed",
        kind="train",
    )


def _markers(root: Path, run_id: str) -> list[str]:
    return [str(p) for p in completion.invalid_markers(Path(root) / "runs" / run_id)]


def _summary(report: dict) -> dict:
    return {
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "ledger_state": report.get("ledger_state"),
        "ledger_state_is_completed": report.get("ledger_state_is_completed"),
        "completion_invalid_markers": report.get("completion_invalid_markers"),
        "rolled_back": report.get("rolled_back"),
        "message": report.get("message"),
    }


def _before_truncation() -> dict:
    """before 截断点：首次被拒后，第二次调用不得报 completed。"""
    root, ledger, run_id = _ledger("before")
    try:
        protocol = completion.CompletionProtocol(deadline_seconds=20.0)
        fired: list[int] = []

        def _seam(phase: str, elapsed: float) -> None:
            # 仅在 pre_terminal_commit 第一次触发：把计时起点往前推 21 s，
            # 于是截止检查在提交前失败（P24 F1 的 before 截断点）。
            if phase == "train:pre_terminal_commit" and not fired:
                fired.append(1)
                protocol.started -= 21.0

        completion.TEST_SEAM = _seam
        try:
            first = _complete(ledger, run_id, root, protocol=protocol)
        finally:
            completion.TEST_SEAM = None
        second = _complete(
            ledger, run_id, root,
            protocol=completion.CompletionProtocol(deadline_seconds=20.0),
        )
        return {
            "truncation_point": "before the terminal commit (deadline already crossed)",
            "first_call": _summary(first),
            "ledger_state_after_first": ledger.get(run_id)["state"],
            "markers_after_first": _markers(root, run_id),
            "second_call": _summary(second),
            "ledger_state_after_second": ledger.get(run_id)["state"],
            "markers_after_second": _markers(root, run_id),
            "second_call_claims_completed": second.get("status") == "completed",
            "verdict": (
                "PASS" if second.get("status") != "completed"
                and second.get("refused_stage") == "completion_already_invalid"
                and second.get("ledger_state") == "failed"
                and ledger.get(run_id)["state"] == "failed"
                else "FAIL"
            ),
        }
    finally:
        ledger.close()


def _after_truncation() -> dict:
    """inside/after 截断点：提交已落地、标记已写，第二次调用必须拒绝。"""
    root, ledger, run_id = _ledger("after")
    try:
        run_dir = Path(root) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        protocol = completion.CompletionProtocol(deadline_seconds=10.0)
        protocol.check("train_receipt")
        completion.write_invalid_marker(
            run_dir,
            protocol=protocol,
            phase="train:terminal_commit",
            reason="deadline_exceeded_in_commit",
            ledger_state="completed",
            detail="injected: the commit landed after the deadline",
        )
        ledger.finish(run_id, "completed", "s1_train_completed")
        second = _complete(
            ledger, run_id, root,
            protocol=completion.CompletionProtocol(deadline_seconds=10.0),
        )
        return {
            "truncation_point": "inside/after the terminal commit (row already completed)",
            "second_call": _summary(second),
            "ledger_state_after_second": ledger.get(run_id)["state"],
            "markers_after_second": _markers(root, run_id),
            "second_call_claims_completed": second.get("status") == "completed",
            "verdict": (
                "PASS" if second.get("status") != "completed"
                and second.get("refused_stage") == "completion_already_invalid"
                and ledger.get(run_id)["state"] == "completed"
                else "FAIL"
            ),
        }
    finally:
        ledger.close()


def _terminal_without_marker() -> dict:
    """无标记的 failed 终态：完成声称必须被拒。"""
    root, ledger, run_id = _ledger("terminal-no-marker")
    try:
        ledger.finish(run_id, "failed", "worker_failure")
        second = _complete(
            ledger, run_id, root,
            protocol=completion.CompletionProtocol(deadline_seconds=10.0),
        )
        return {
            "truncation_point": "no marker; ledger row already failed",
            "second_call": _summary(second),
            "ledger_state_after_second": ledger.get(run_id)["state"],
            "second_call_claims_completed": second.get("status") == "completed",
            "verdict": (
                "PASS" if second.get("status") != "completed"
                and second.get("refused_stage") == "ledger_terminal_not_completed"
                and second.get("ledger_state") == "failed"
                else "FAIL"
            ),
        }
    finally:
        ledger.close()


def _make_sabotaged_copy() -> tuple[Path, str]:
    """隔离源码副本：只把 _completion_precondition 改成直接放行（拆掉该守卫）。"""
    copy_root = SCRATCH / "sabotage-src"
    if copy_root.exists():
        shutil.rmtree(copy_root)
    copy_root.mkdir(parents=True)
    shutil.copytree(REPO / "src" / "ainerzero", copy_root / "ainerzero")
    target = copy_root / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"
    text = target.read_text()
    old = '''    run_dir = _run_dir_for(output_root, run_id)
    markers = completion.invalid_markers(run_dir)
    try:
        state = ledger.get(run_id).get("state")
    except Exception:  # pragma: no cover - ledger unreadable
        state = None
'''
    new = '''    return None  # P25 sabotage: the completion precondition guard is removed
    run_dir = _run_dir_for(output_root, run_id)
    markers = completion.invalid_markers(run_dir)
    try:
        state = ledger.get(run_id).get("state")
    except Exception:  # pragma: no cover - ledger unreadable
        state = None
'''
    assert text.count(old) == 1, "sabotage anchor not unique"
    target.write_text(text.replace(old, new))
    diff = subprocess.run(
        ["diff", "-u",
         str(REPO / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"),
         str(target)],
        capture_output=True, text=True,
    ).stdout
    tree_diff = subprocess.run(
        ["diff", "-r", str(REPO / "src" / "ainerzero"), str(copy_root / "ainerzero")],
        capture_output=True, text=True,
    ).stdout
    assert tree_diff.count("diff -r") == 1 and "worker.py" in tree_diff, (
        f"sabotaged copy must differ in exactly one file:\n{tree_diff}"
    )
    return copy_root, diff + "\n# whole-tree check (diff -r): exactly one file differs\n" + tree_diff


def _sabotage_before_child() -> dict:
    """坏控子进程：守卫已拆，复跑 before 场景，P24 F1 缺陷必须复现。"""
    payload = _before_truncation()
    payload["imported_worker_from"] = worker.__file__
    payload["bug_reproduced"] = (
        payload["second_call"]["status"] == "completed"
        and payload["ledger_state_after_second"] == "failed"
    )
    return payload


def main() -> int:
    if _args.sabotage_child:
        print(json.dumps(_sabotage_before_child(), ensure_ascii=False, indent=1))
        return 0

    payload = {
        "schema": "ainerzero.v9.s1.p25.r2_probe.v1",
        "probe_by": "step5p-9q4t (P25 非作者复核)",
        "note": "temporary card-local RunStore files under reports/V9-P25/.tmp-r2; "
                "central ledger untouched; no model work",
        "frozen": {"updates": UPDATES, "deadline_seconds": DEADLINE},
        "before_truncation": _before_truncation(),
        "after_truncation": _after_truncation(),
        "terminal_without_marker": _terminal_without_marker(),
    }

    copy_src, diff = _make_sabotaged_copy()
    payload["sabotage_control"] = {
        "method": "isolated source copy; only _completion_precondition neutered "
                  "(returns None immediately)",
        "diff": diff,
    }
    env = {"PYTHONPATH": str(copy_src), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    child = subprocess.run(
        [sys.executable, str(HERE), "--sabotage-child", str(copy_src)],
        capture_output=True, text=True, cwd=str(REPO), env=env,
    )
    if child.returncode != 0:
        payload["sabotage_control"]["child_error"] = child.stderr[-3000:]
    else:
        payload["sabotage_control"]["child"] = json.loads(child.stdout)

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    for key in ("before_truncation", "after_truncation", "terminal_without_marker"):
        print(f"{key}: verdict={payload[key]['verdict']} "
              f"second={payload[key]['second_call']['status']}/"
              f"{payload[key]['second_call']['refused_stage']} "
              f"ledger={payload[key]['ledger_state_after_second']}")
    s = payload["sabotage_control"].get("child", {})
    print(f"sabotage_control: imported_from={s.get('imported_worker_from')} "
          f"second_status={s.get('second_call', {}).get('status')} "
          f"ledger={s.get('ledger_state_after_second')} "
          f"bug_reproduced={s.get('bug_reproduced')}")
    print(f"json -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
