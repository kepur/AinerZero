#!/usr/bin/env python3
"""P25 must_also ①：两进程并发 ensure_shared_experiment 实测。

作者自述并发注册分支只覆盖了 LifecycleError 重读的代码路径、没有多进程竞争。
本探针用两个真实进程并发调用 r9 的 worker.ensure_shared_experiment：

  same    同 manifest、不同 request_id（模拟 D 的 :eval:arm1 与训练的 :training）
  foreign 异 manifest（其中一个带外来 manifest）

每个场景跑多轮，报告实际行为：谁创建、谁在 LifecycleError 后重读复用/拒绝、
最终实验行数与 manifest_hash、是否有异常逃逸。
只写 reports/V9-P25/.tmp-conc/ 临时卡内 RunStore，不碰中央台账。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRATCH = REPO / "reports/V9-P25/.tmp-conc"
LOGS = REPO / "reports/V9-P25/logs"
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import worker  # noqa: E402

UPDATES = 3510
ROUNDS = 10
OUT_JSON = LOGS / "r1-concurrency.json"

_parser = argparse.ArgumentParser()
_parser.add_argument("--child", action="store_true")
_parser.add_argument("--db", type=str, default=None)
_parser.add_argument("--manifest-role", type=str, default=None, help="same | foreign")
_parser.add_argument("--request-id", type=str, default=None)
_parser.add_argument("--ready", type=str, default=None)
_parser.add_argument("--gate", type=str, default=None)
_args = _parser.parse_args()


def _manifest(role: str) -> dict:
    manifest = worker.train_experiment_manifest(updates=UPDATES)
    if role == "foreign":
        manifest["purpose"] = "p25 concurrency probe: foreign registration"
    return manifest


def _child() -> dict:
    from ainerzero.runtime.lifecycle import RunStore

    Path(_args.ready).write_text(json.dumps({"pid": os.getpid()}))
    gate = Path(_args.gate)
    while not gate.exists():
        time.sleep(0.001)
    # 注：生产环境里 commands.py 持项目级共享锁串行化有界运行，两进程不会
    # 同时开中央台账。本探针刻意绕开该锁直测守卫，因此 RunStore 初始化
    # （WAL pragma）本身可能撞锁——这发生在任何守卫逻辑之前，单独计数。
    store = None
    init_attempts = 0
    init_locked = 0
    for _ in range(100):
        init_attempts += 1
        try:
            store = RunStore(_args.db)
            break
        except Exception as exc:
            if "locked" not in str(exc):
                raise
            init_locked += 1
            time.sleep(0.05)
    outcome = {
        "manifest_role": _args.manifest_role,
        "request_id": _args.request_id,
        "pid": os.getpid(),
        "runstore_init_attempts": init_attempts,
        "runstore_init_locked_retries": init_locked,
    }
    if store is None:
        outcome["result"] = "runstore_init_failed"
        return outcome
    started = time.perf_counter()
    try:
        experiment = worker.ensure_shared_experiment(
            store,
            manifest=_manifest(_args.manifest_role),
            request_id=_args.request_id,
            experiment_id=worker.TRAIN_EXPERIMENT_ID,
        )
        outcome.update({
            "result": "returned",
            "experiment_id": experiment.experiment_id,
            "manifest_hash": experiment.manifest_hash,
            "stored_request_id": experiment.request_id,
        })
    except worker.ExperimentManifestMismatch as exc:
        outcome.update({"result": "ExperimentManifestMismatch", "error": str(exc)})
    except Exception as exc:  # 任何其他逃逸都如实记录
        outcome.update({"result": f"unexpected:{type(exc).__name__}", "error": str(exc)})
    outcome["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    store.close()
    return outcome


def _round(index: int, roles: tuple[str, str]) -> dict:
    """两进程真实并发：各自 ready 后由父进程放行。"""
    root = SCRATCH / f"round-{index:02d}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    db = root / "control.sqlite3"
    gate = root / "go"
    request_ids = (
        f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1",
        f"{worker.TRAIN_EXPERIMENT_ID}:training",
    )
    procs = []
    for slot, role in enumerate(roles):
        ready = root / f"ready-{slot}"
        proc = subprocess.Popen(
            [sys.executable, str(HERE), "--child",
             "--db", str(db),
             "--manifest-role", role,
             "--request-id", request_ids[slot],
             "--ready", str(ready),
             "--gate", str(gate)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        procs.append((slot, role, proc, ready))
    deadline = time.time() + 30
    while time.time() < deadline:
        if all(p[3].exists() for p in procs):
            break
        if any(p[2].poll() is not None for p in procs):
            break
        time.sleep(0.01)
    gate.write_text("go")
    children = {}
    for slot, role, proc, _ready in procs:
        stdout, stderr = proc.communicate(timeout=60)
        try:
            children[f"slot{slot}({role})"] = json.loads(stdout)
        except json.JSONDecodeError:
            children[f"slot{slot}({role})"] = {
                "result": "child_crash", "stderr": stderr[-1500:],
            }
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT experiment_id, request_id, manifest_hash FROM experiments"
            )
        ]
    return {"round": index, "roles": list(roles), "children": children,
            "experiment_rows": rows}


def _tally(rounds: list[dict]) -> dict:
    tally: dict[str, int] = {}
    for r in rounds:
        key = "|".join(
            f"{name}:{r['children'][name]['result']}" for name in sorted(r["children"])
        )
        tally[key] = tally.get(key, 0) + 1
    return tally


def main() -> int:
    if _args.child:
        print(json.dumps(_child(), ensure_ascii=False))
        return 0

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)

    payload = {
        "schema": "ainerzero.v9.s1.p25.concurrency_probe.v1",
        "probe_by": "step5p-9q4t (P25 非作者复核)",
        "note": "two real processes race on worker.ensure_shared_experiment; "
                "temporary card-local RunStore only; central ledger untouched",
        "rounds_per_scenario": ROUNDS,
        "frozen": {"updates": UPDATES, "experiment_id": worker.TRAIN_EXPERIMENT_ID},
    }

    same_rounds = [_round(i, ("same", "same")) for i in range(ROUNDS)]
    foreign_rounds = [_round(100 + i, ("same", "foreign")) for i in range(ROUNDS)]

    payload["same_manifest"] = {
        "rounds": same_rounds,
        "tally": _tally(same_rounds),
        "all_both_returned": all(
            c["result"] == "returned"
            for r in same_rounds for c in r["children"].values()
        ),
        "exactly_one_experiment_row": all(
            len(r["experiment_rows"]) == 1 for r in same_rounds
        ),
        "one_row_manifest_hashes": sorted(
            {r["experiment_rows"][0]["manifest_hash"] for r in same_rounds
             if len(r["experiment_rows"]) == 1}
        ),
    }
    payload["foreign_manifest"] = {
        "rounds": foreign_rounds,
        "tally": _tally(foreign_rounds),
        "no_unexpected_escapes": all(
            not str(c["result"]).startswith("unexpected")
            for r in foreign_rounds for c in r["children"].values()
        ),
        "exactly_one_experiment_row": all(
            len(r["experiment_rows"]) == 1 for r in foreign_rounds
        ),
        "foreign_row_is_the_registered_manifest": all(
            len(r["experiment_rows"]) == 1
            and r["experiment_rows"][0]["request_id"]
            == f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1"
            for r in foreign_rounds
        ),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print("same_manifest tally:", json.dumps(payload["same_manifest"]["tally"]))
    print("same: all_both_returned =", payload["same_manifest"]["all_both_returned"],
          " exactly_one_row =", payload["same_manifest"]["exactly_one_experiment_row"])
    print("foreign_manifest tally:", json.dumps(payload["foreign_manifest"]["tally"]))
    print("foreign: no_unexpected_escapes =",
          payload["foreign_manifest"]["no_unexpected_escapes"],
          " exactly_one_row =", payload["foreign_manifest"]["exactly_one_experiment_row"])
    print(f"json -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
