#!/usr/bin/env python3
"""P35 r2 隔离入口驱动（同一份驱动用于真实源码与破坏副本）。

用法：
  driver_entry.py <host> train   --arm arm2 --seed 0 [--no-sentinel]
  driver_entry.py <host> eval    --arm arm2 --seed 0
  driver_entry.py <host> fabricate --arm arm2 --seed 0
  driver_entry.py <host> seed-attempt --arm arm2 --seed 0 [--age 14300]

驱动只做三件事：
  1. 把 ``spec`` 指到隔离 host（REGISTERED_HOST_ROOT / PHASE1_ROOT / RESEARCH_LOG）；
  2. 装上 MLX 哨兵（拦截 mlx / mlx.* 的导入）；
  3. 调 ``worker.run_worker`` 并把结果、台账前后 SHA、哨兵日志打印成一行 JSON。

生产目录：驱动只读生产台账的字节（不算），写入一律落在 host 副本里。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import sys
import time
from pathlib import Path

HOST = Path(sys.argv[1]).resolve()

from ainerzero.v9.experiments.s1 import spec  # noqa: E402

spec.REGISTERED_HOST_ROOT = HOST
spec.PHASE1_ROOT = HOST / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = HOST / "RESEARCH_LOG.md"

from ainerzero.v9.experiments.s1 import completion, prereg, worker  # noqa: E402

SENTINEL_LOG: list[dict] = []
PHASE1 = spec.PHASE1_ROOT
LEDGER = PHASE1 / "control.sqlite3"
# r12 的冻结件在 phase1/r12/ 下；顶层 pre_registration.json 是 r10 时代的旧件。
_R12 = PHASE1 / "r12" / "pre_registration.json"
PREREG = _R12 if _R12.is_file() else PHASE1 / "pre_registration.json"


class MlxSentinel(BaseException):
    """在第一次真实 MLX 导入处停住（BaseException：不被 ``except Exception`` 吞）。"""


_SELF_FILE = str(Path(__file__).resolve())


def _caller() -> tuple[str, str, int]:
    """跳过 importlib 与本驱动自身的栈帧，返回真正发起 import 的调用方。"""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if "importlib" not in name and name != _SELF_FILE:
            return (
                str(frame.f_globals.get("__name__", "?")),
                name,
                int(frame.f_lineno),
            )
        frame = frame.f_back
    return ("?", "?", -1)


class SentinelFinder(importlib.abc.MetaPathFinder):
    """拦截 ``mlx`` / ``mlx.*``。

    * 调用方是 ``resource_gate`` 的尽力探测（该处本就 ``except Exception`` 后报
      "unavailable"）→ 抛 ImportError，让探测如实报告不可用，而不是伪造数值；
    * 其他任何调用方（真正要跑模型的地方）→ 抛 :class:`MlxSentinel`，入口停在哨兵处。
    """

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102
        if not (fullname == "mlx" or fullname.startswith("mlx.")):
            return None
        module, filename, lineno = _caller()
        entry = {
            "import": fullname,
            "caller_module": module,
            "caller_file": filename,
            "caller_line": lineno,
            "at": time.strftime("%H:%M:%S"),
        }
        if module == "ainerzero.v9.experiments.s1.resource_gate":
            entry["action"] = "deny_import_error"
            SENTINEL_LOG.append(entry)
            raise ImportError("P35 sentinel: MLX denied at the best-effort resource probe")
        entry["action"] = "sentinel_stop"
        SENTINEL_LOG.append(entry)
        raise MlxSentinel(json.dumps(entry, ensure_ascii=False))


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _checkpoint() -> None:
    """把副本台账的 WAL 收进主文件，避免"前后 SHA"读到半截状态。"""
    import sqlite3

    connection = sqlite3.connect(LEDGER)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def _document() -> dict:
    return json.loads(PREREG.read_text(encoding="utf-8"))


def _doc_sha() -> str:
    return prereg.document_sha256(_document())


def fabricate_completed(arm: str, seed: int) -> dict:
    """在副本台账里造 1 个 arm×seed 的完成训练记录（含 completion receipt）。

    只用产品自己的 API（``_open_train_run`` / ``reserve`` / ``_complete_run``），
    在**隔离副本**里跑，不训练、不评测、不碰生产库。
    """
    document = _document()
    updates = int(document["training_protocol"]["updates"])
    deadline = float(document["timing"]["deadline_seconds"])
    ledger = worker.PrepLedger(LEDGER)
    try:
        run_id = worker._open_train_run(
            document,
            ledger,
            {"document_sha256": _doc_sha(), "line": "P35 r2 drill", "line_number": 1},
            arm_id=arm,
            seed=seed,
        )
        ledger.begin_work(run_id, work_state="training")
        ledger.reserve(run_id, active_seconds=1.0, optimizer_steps=updates)
        run_dir = PHASE1 / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        params = run_dir / "params.npz"
        params.write_bytes(b"P35-r2-drill-fake-params-" + run_id.encode())
        params_sha = _sha(params)
        receipt = {
            "run_id": run_id,
            "arm_id": arm,
            "seed": int(seed),
            "updates": updates,
            "preregistration_sha256": _doc_sha(),
            "dataset_digest": (document.get("data_identity") or {}).get("dataset_digest"),
            "final_checkpoint_sha256": params_sha,
            "checkpoints": [
                {
                    "updates": updates,
                    "path": "params.npz",
                    "sha256": params_sha,
                    "parameter_sha256": "f" * 64,
                }
            ],
            "completion_protocol": {
                "schema": completion.SCHEMA,
                "elapsed_at_record_seconds": 1.0,
                "deadline_seconds": deadline,
                "expired_in_flight": False,
            },
            "note": "P35 r2 isolated drill: synthetic completion record, not a training result",
        }
        reason = worker.TRAIN_RECEIPT_PREFIX + json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        report = worker._complete_run(
            report={"schema": "p35.drill", "mode": "train"},
            ledger=ledger,
            run_id=run_id,
            protocol=completion.CompletionProtocol(deadline_seconds=deadline),
            output_root=PHASE1,
            reason=reason,
            kind="train",
        )
        _checkpoint()
        return {
            "run_id": run_id,
            "status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "params_sha256": params_sha,
            "ledger_sha256_after": _sha(LEDGER),
        }
    finally:
        ledger.close()


def seed_attempt(arm: str, seed: int, age: float | None) -> dict:
    """在副本台账里放一条已开始的 attempt（可选把时间戳往前推）。"""
    document = _document()
    ledger = worker.PrepLedger(LEDGER)
    try:
        run_id = worker._open_train_run(
            document,
            ledger,
            {"document_sha256": _doc_sha()},
            arm_id=arm,
            seed=seed,
        )
        ledger.begin_work(run_id, work_state="training")
    finally:
        ledger.close()
    if age:
        import sqlite3

        # 注意：``with sqlite3.connect(...)`` 只提交事务、不关闭连接；不显式 close 的话
        # 改动会留在 WAL 里，进程退出时才 checkpoint 进主文件，导致"前后 SHA"读到半截状态。
        connection = sqlite3.connect(LEDGER)
        try:
            connection.execute(
                "UPDATE runs SET created_at = created_at - ?, updated_at = updated_at - ? "
                "WHERE run_id = ?",
                (float(age), float(age), run_id),
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    return {"run_id": run_id, "aged_seconds": age, "ledger_sha256_after": _sha(LEDGER)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("mode", choices=("train", "eval", "fabricate", "seed-attempt", "identity"))
    parser.add_argument("--arm", default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-sentinel", action="store_true")
    parser.add_argument("--age", type=float, default=None)
    args = parser.parse_args()

    if not args.no_sentinel:
        sys.meta_path.insert(0, SentinelFinder())

    out: dict = {
        "mode": args.mode,
        "arm": args.arm,
        "seed": args.seed,
        "host": str(HOST),
        "worker_module": worker.__file__,
        "spec_module": spec.__file__,
        "phase1_root": str(spec.PHASE1_ROOT),
        "research_log": str(spec.RESEARCH_LOG),
        "prereg_sha256": _doc_sha(),
        "ledger_sha256_before": _sha(LEDGER),
    }

    if args.mode == "identity":
        from ainerzero.v9.experiments.s1 import identity as identity_module

        spec_identity = dict(spec.ARM_SPECS["arm1"]["identity"])
        runtime = identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
        doc_identity = dict(((_document().get("arms") or {}).get("arm1") or {}).get("identity") or {})
        out["identity"] = {
            "spec_module": spec.__file__,
            "identity_module": identity_module.__file__,
            "spec_arm1_identity": spec_identity,
            "runtime_verified": runtime,
            "document_arm1_identity": doc_identity,
            "document_differs_from_spec": {
                key: {"document": doc_identity.get(key), "spec": spec_identity.get(key)}
                for key in sorted(set(doc_identity) | set(spec_identity))
                if doc_identity.get(key) != spec_identity.get(key)
            },
            "runtime_matches_spec": {
                "tensors_sha256": runtime["tensors_sha256"] == spec_identity.get("tensors_sha256"),
                "manifest_sha256": runtime["manifest_sha256"] == spec_identity.get("manifest_sha256"),
                "metadata_sha256": runtime["metadata_sha256"] == spec_identity.get("metadata_sha256"),
                "checkpoint_id": runtime["checkpoint_id"] == spec_identity.get("checkpoint_id"),
                "pilot_dir": runtime["pilot_dir"] == spec_identity.get("pilot_dir"),
            },
            "spec_py_bound_in_document": (
                (_document().get("source_identity") or {}).get("package_files") or {}
            ).get("src/ainerzero/v9/experiments/s1/spec.py"),
            "spec_py_actual_sha256": _sha(Path(spec.__file__).resolve()),
        }
    elif args.mode == "fabricate":
        out["fabricated"] = fabricate_completed(args.arm, args.seed)
    elif args.mode == "seed-attempt":
        out["seeded"] = seed_attempt(args.arm, args.seed, args.age)
    else:
        report = worker.run_worker(
            args.mode,
            output_root=PHASE1,
            limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=(
                300.0
                if args.mode == "eval"
                else float(_document()["timing"]["deadline_seconds"])
            ),
            prereg_path=PREREG,
            arm=args.arm,
            seed=args.seed,
        )
        out["report"] = {
            "status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "error": report.get("error"),
            "run_id": report.get("run_id"),
            "experiment_id": report.get("experiment_id"),
            "eval_binding": report.get("eval_binding"),
            "d_candidate_attempts": report.get("d_candidate_attempts"),
            "approval_approved": (report.get("approval") or {}).get("approved"),
            "source_binding": (report.get("source_binding") or {}).get("status"),
            "dataset": (report.get("dataset") or {}).get("status"),
            "message": report.get("message"),
        }

    out["ledger_sha256_after"] = _sha(LEDGER)
    out["ledger_unchanged"] = out["ledger_sha256_before"] == out["ledger_sha256_after"]
    out["sentinel"] = SENTINEL_LOG
    out["sentinel_stopped"] = any(e["action"] == "sentinel_stop" for e in SENTINEL_LOG)
    # 哨兵拦在 import 之前：mlx 从未真正进入 sys.modules（没有加载、没有计算）。
    out["mlx_loaded"] = sorted(
        name for name in sys.modules if name == "mlx" or name.startswith("mlx.")
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
