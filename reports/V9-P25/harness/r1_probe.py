#!/usr/bin/env python3
"""P25 独立复核 R1：共享 TRAIN 实验的两种注册顺序 + manifest 比对 + 坏控。

step5p-9q4t 自写探针（不导入、不调用 r9 作者测试 test_s1_r9_* 的任何断言；
只复用仓库既有的 r8 CPU 替身与 s1_testkit 夹具助手——它们都是钉扎的既有文件）。

场景（全部走真实公开入口 worker.run_worker，CPU 替身，不碰中央台账、不跑 MLX）：
  A 先 D 后 train：同一实验 ID 下都成功，阶段合计同时看到 D 的 2 s 与训练的 450 s
  B 先 train 后 D：同上
  C 预建同 ID 不同 manifest 的实验：D 与 train 两路都必须拒绝，且不新增 run 行
  D 坏控（隔离源码副本里只删 manifest 比对）：C 的反向用例必须变成通过

坏控在隔离子进程里完成：把 src/ainerzero 复制到 scratch，只把
_manifest_digest_matches 改成恒真（即删掉"是否可复用"的唯一比较），
diff 证明只有这一处变化，再用该副本复跑 C 的 D/train 两路。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRATCH = REPO / "reports/V9-P25/.tmp-r1"
LOGS = REPO / "reports/V9-P25/logs"
TESTS = REPO / "tests/v9/experiments"

# --- 先解析参数，再决定 import 路径（坏控子进程必须导入被拆掉比对的副本） -----
_parser = argparse.ArgumentParser()
_parser.add_argument("--sabotage-child", type=str, default=None,
                     help="internal: run the foreign-manifest scenario against a sabotaged copy")
_parser.add_argument("--name", type=str, default="sabotage-child")
_args = _parser.parse_args()

if _args.sabotage_child:
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(Path(_args.sabotage_child)))
else:
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import data, prereg, spec, worker  # noqa: E402
from s1_testkit import (  # noqa: E402
    FAKE_COUNTS,
    fake_smoke,
    make_plan,
    write_frozen,
    write_research_log,
    write_staging,
)

# r8 CPU 替身（既有钉扎测试基础设施，只读复用）
from test_s1_r8_completion import _CpuBackend, _ScriptedClock  # noqa: E402
from test_s1_r8_d_budget import _DCpuBackend  # noqa: E402

UPDATES = 3510
DEADLINE = 450.0
D_DEADLINE = 2.0
# 冻结的生产形态步时（r8 登记的 smoke 步时，非测试魔法值）
TRAIN_STEP = 0.0069624580000891
D_STEP = 0.0013035410001975833

OUT_JSON = LOGS / "r1-shared-experiment.json"


class _Patch:
    """最小 monkeypatch 替身：记录旧值以便还原。"""

    def __init__(self) -> None:
        self._undo: list[tuple[object, str, object]] = []

    def setattr(self, obj, name, value) -> None:
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo = []


class _LoopClock(_ScriptedClock):
    """脚本化循环时钟，但 time.time() 保持真实（阶段合计会读它）。"""

    def time(self) -> float:
        return time.time()


def _document(identity: dict) -> dict:
    """绑定合成数据集的冻结文档：3510 updates / 450 s / arm1 2 s。"""
    smoke = fake_smoke(TRAIN_STEP)
    smoke["d_candidate"]["forward_loss_step_seconds"] = D_STEP
    document = prereg.build_frozen(
        prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS),
        smoke=smoke,
        data_identity=identity,
        created_unix=1_000.0,
    )
    assert int(document["training_protocol"]["updates"]) == UPDATES
    assert float(document["timing"]["deadline_seconds"]) == DEADLINE
    assert float(document["timing"]["arm1_deadline_seconds"]) == D_DEADLINE
    return document


def _setup_host(name: str) -> tuple[Path, Path, Path]:
    """隔离 canonical host：合成数据集 + 冻结文档 + 批准行 + prep 实验。"""
    host = SCRATCH / name
    if host.exists():
        shutil.rmtree(host)
    host.mkdir(parents=True)
    root = host / "artifacts" / "v9" / "s1" / "phase1"
    root.mkdir(parents=True)
    (host / "RESEARCH_LOG.md").write_text("# isolated P25 probe host\n", encoding="utf-8")

    plan = make_plan()
    staging = host / "staging"
    write_staging(staging, plan=plan)
    final_dir = host / "dataset"
    manifest = data.finalize_dataset(
        staging, final_dir, plan=plan, generation_seconds=12.5,
        generation_command=["p25-synthetic-producer"],
    )
    identity = data.dataset_identity(manifest)
    target = host / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(final_dir, target)
    data.write_dataset_ref(root, manifest, target)

    document = _document(identity)
    path, digest, _doc = write_frozen(root / "pre_registration.json", document=document)
    log = write_research_log(host / "RESEARCH_LOG.md", approval_sha=digest)

    patch = _Patch()
    patch.setattr(spec, "REGISTERED_HOST_ROOT", host.resolve())
    patch.setattr(spec, "PHASE1_ROOT", root)
    patch.setattr(spec, "RESEARCH_LOG", log)
    # prep 实验：让中央台账的 fail-closed 身份识别认得这个隔离 host
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
    finally:
        ledger.close()
    return root, path, log


def _run_d(root: Path, path: Path) -> dict:
    return worker.run_worker(
        "eval",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=path,
        arm="arm1",
        seed=0,
        backend=_DCpuBackend(),
    )


def _run_train(root: Path, path: Path, log: Path, patch: _Patch) -> dict:
    clock = _LoopClock()
    patch.setattr(worker, "time", clock)

    def _batches(*args, **kwargs):
        while True:
            yield {"obs": None}

    patch.setattr(worker.data, "iter_batches", _batches)
    return worker.run_worker(
        "train",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=log,
        arm="arm2",
        seed=0,
        backend=_CpuBackend(clock),
    )


def _experiment_rows(root: Path) -> list[dict]:
    with sqlite3.connect(root / "control.sqlite3") as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in conn.execute(
                "SELECT experiment_id, request_id, manifest_hash FROM experiments "
                "WHERE experiment_id=?",
                (worker.TRAIN_EXPERIMENT_ID,),
            )
        ]


def _phase_view(root: Path) -> dict:
    """阶段合计：两个 run 都要在同一实验 ID 下，且各自带 2 s / 450 s 预算。"""
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        runs = {r.run_id: r for r in ledger.store.list_runs()}
        breakdown = worker.phase_ledger_breakdown(ledger.store.list_runs(), instant=time.time())
    finally:
        ledger.close()
    return {
        "runs": {
            rid: {
                "experiment_id": r.experiment_id,
                "state": r.state,
                "wall_budget_seconds": float(r.config_snapshot["budget"]["max_wall_seconds"]),
                "arm_id": r.config_snapshot.get("arm_id"),
            }
            for rid, r in runs.items()
        },
        "breakdown_rows": [
            {k: row[k] for k in ("run_id", "state", "reserved_active_seconds", "counted_seconds")}
            for row in breakdown["rows"]
        ],
        "breakdown_total_seconds": breakdown["total_seconds"],
        "experiment_rows": _experiment_rows(root),
    }


def _order(name: str, first: str) -> dict:
    root, path, log = _setup_host(name)
    patch = _Patch()
    try:
        d_report = t_report = None
        error = None
        try:
            if first == "D":
                d_report = _run_d(root, path)
                t_report = _run_train(root, path, log, patch)
            else:
                t_report = _run_train(root, path, log, patch)
                d_report = _run_d(root, path)
        except Exception as exc:  # r8 缺陷就会在这里冒出来
            error = f"{type(exc).__name__}: {exc}"
        payload = {
            "order": f"{first}_first",
            "error": error,
            "d_status": (d_report or {}).get("status"),
            "d_message": (d_report or {}).get("message"),
            "d_run_id": (d_report or {}).get("run_id"),
            "train_status": (t_report or {}).get("status"),
            "train_message": (t_report or {}).get("message"),
            "train_run_id": (t_report or {}).get("run_id"),
        }
        if d_report and t_report and d_report.get("run_id") and t_report.get("run_id"):
            view = _phase_view(root)
            payload["phase_view"] = view
            payload["same_experiment"] = (
                view["runs"][d_report["run_id"]]["experiment_id"]
                == view["runs"][t_report["run_id"]]["experiment_id"]
                == worker.TRAIN_EXPERIMENT_ID
            )
            payload["budgets"] = {
                "d": view["runs"][d_report["run_id"]]["wall_budget_seconds"],
                "train": view["runs"][t_report["run_id"]]["wall_budget_seconds"],
            }
            payload["one_experiment_row"] = len(view["experiment_rows"]) == 1
            payload["breakdown_sees_both"] = {
                rid: any(row["run_id"] == rid for row in view["breakdown_rows"])
                for rid in (d_report["run_id"], t_report["run_id"])
            }
        return payload
    finally:
        patch.undo()


def _foreign_manifest() -> dict:
    manifest = worker.train_experiment_manifest(updates=UPDATES)
    manifest["purpose"] = "p25 probe: foreign registration under the shared ID"
    return manifest


def _prebuild_foreign(root: Path) -> None:
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            _foreign_manifest(), "p25-foreign-request", worker.TRAIN_EXPERIMENT_ID
        )
    finally:
        ledger.close()


def _foreign(name: str) -> dict:
    """反向用例：预建同 ID 不同 manifest，两路都必须拒绝。"""
    root, path, log = _setup_host(name)
    patch = _Patch()
    try:
        _prebuild_foreign(root)
        d_report = _run_d(root, path)
        t_report = _run_train(root, path, log, patch)
        ledger = worker.PrepLedger(root / "control.sqlite3")
        try:
            runs = ledger.store.list_runs()
        finally:
            ledger.close()
        return {
            "d": {
                "status": d_report.get("status"),
                "refused_stage": d_report.get("refused_stage"),
                "error": d_report.get("error"),
            },
            "train": {
                "status": t_report.get("status"),
                "refused_stage": t_report.get("refused_stage"),
                "error": t_report.get("error"),
            },
            "runs_registered": len(runs),
            "experiment_rows": _experiment_rows(root),
        }
    finally:
        patch.undo()


def _make_sabotaged_copy() -> tuple[Path, str]:
    """隔离源码副本：按 repo 形态布局，只把 manifest 比对改成恒真。

    副本布局为 <scratch>/sabotage-host/src/ainerzero/...（与真仓库同构），
    子进程再把 spec.REPO_ROOT 指向该宿主——这样身份链核对的是副本自己的
    字节，而副本相对真仓库仍只有 worker.py 一处变化（即坏控对象）。
    返回 (副本src路径, diff文本)。
    """
    host = SCRATCH / "sabotage-host"
    if host.exists():
        shutil.rmtree(host)
    copy_src = host / "src"
    copy_src.mkdir(parents=True)
    shutil.copytree(REPO / "src" / "ainerzero", copy_src / "ainerzero")
    # D 身份链按 REPO_ROOT 解析 A2 钉扎文件；只读软链真实 artifacts，
    # 让 D 路径能到达（并被拆掉比对的）manifest 检查。src 树不受影响。
    (host / "artifacts").symlink_to(REPO / "artifacts")
    target = copy_src / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"
    text = target.read_text()
    old = "    return existing_hash == expected_hash\n"
    new = "    return True  # P25 sabotage: the manifest comparison is removed\n"
    assert text.count(old) == 1, "sabotage anchor not unique"
    target.write_text(text.replace(old, new))
    diff = subprocess.run(
        ["diff", "-u",
         str(REPO / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"),
         str(target)],
        capture_output=True, text=True,
    ).stdout
    # 全树核对：除 worker.py 外副本与真仓库逐字节一致
    tree_diff = subprocess.run(
        ["diff", "-r", str(REPO / "src" / "ainerzero"), str(copy_src / "ainerzero")],
        capture_output=True, text=True,
    ).stdout
    assert "worker.py" in tree_diff and tree_diff.count("diff -r") == 1, (
        f"sabotaged copy must differ in exactly one file:\n{tree_diff}"
    )
    return copy_src, diff + "\n# whole-tree check (diff -r): exactly one file differs\n" + tree_diff


def _sabotage_child(copy_src: Path, name: str) -> dict:
    """用被拆掉比对的源码复跑反向用例（本进程导入的已是被破坏副本）。"""
    # 身份链按 repo 形态解析：把 REPO_ROOT 指向副本宿主，使绑定核对的是副本字节
    spec.REPO_ROOT = copy_src.parent
    root, path, log = _setup_host(name)
    patch = _Patch()
    try:
        _prebuild_foreign(root)
        d_report = _run_d(root, path)
        t_report = _run_train(root, path, log, patch)
        return {
            "imported_worker_from": worker.__file__,
            "sabotage_host": str(copy_src.parent),
            "d": {"status": d_report.get("status"), "message": d_report.get("message"),
                  "run_id": d_report.get("run_id")},
            "train": {"status": t_report.get("status"), "message": t_report.get("message"),
                      "run_id": t_report.get("run_id")},
            "experiment_rows": _experiment_rows(root),
        }
    finally:
        patch.undo()


def main() -> int:
    if _args.sabotage_child:
        payload = _sabotage_child(Path(_args.sabotage_child), _args.name)
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    payload = {
        "schema": "ainerzero.v9.s1.p25.r1_probe.v1",
        "probe_by": "step5p-9q4t (P25 非作者复核)",
        "note": "temporary card-local RunStore files under reports/V9-P25/.tmp-r1; "
                "central ledger untouched; no MLX, no model work",
        "frozen": {
            "updates": UPDATES, "train_deadline_seconds": DEADLINE,
            "d_deadline_seconds": D_DEADLINE, "experiment_id": worker.TRAIN_EXPERIMENT_ID,
        },
    }

    payload["A_d_then_train"] = _order("A-d-then-train", "D")
    payload["B_train_then_d"] = _order("B-train-then-d", "T")
    payload["C_foreign_manifest"] = _foreign("C-foreign")

    copy_src, diff = _make_sabotaged_copy()
    payload["D_sabotage"] = {
        "method": "isolated source copy; only _manifest_digest_matches forced True",
        "diff": diff,
    }
    env = {"PYTHONPATH": str(copy_src), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    child = subprocess.run(
        [sys.executable, str(HERE), "--sabotage-child", str(copy_src), "--name", "D-sabotage"],
        capture_output=True, text=True, cwd=str(REPO), env=env,
    )
    if child.returncode != 0:
        payload["D_sabotage"]["child_error"] = child.stderr[-3000:]
    else:
        payload["D_sabotage"]["child"] = json.loads(child.stdout)

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")

    for key in ("A_d_then_train", "B_train_then_d"):
        p = payload[key]
        print(f"{key}: error={p['error']} d={p['d_status']} train={p['train_status']} "
              f"same_experiment={p.get('same_experiment')} budgets={p.get('budgets')} "
              f"one_experiment_row={p.get('one_experiment_row')} "
              f"breakdown_sees_both={p.get('breakdown_sees_both')}")
    c = payload["C_foreign_manifest"]
    print(f"C_foreign_manifest: d={c['d']['status']}/{c['d']['refused_stage']} "
          f"train={c['train']['status']}/{c['train']['refused_stage']} "
          f"runs_registered={c['runs_registered']}")
    d = payload["D_sabotage"].get("child", {})
    print(f"D_sabotage: imported_from={d.get('imported_worker_from')} "
          f"d={d.get('d', {}).get('status')} train={d.get('train', {}).get('status')}")
    print(f"json -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
