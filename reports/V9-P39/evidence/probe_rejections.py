#!/usr/bin/env python3
"""P39 必做 3：每个拒绝分支都要有对抗验收（副本台账字节不变）。

覆盖 train 的 5 个拒绝分支与 eval 的 4 个拒绝分支（含 P31 事故那条）。每个用例：
隔离副本 → 施加一处前置条件破坏 → 跑真实入口 → 断言 ``status=refused`` +
``refused_stage`` 命中 + 副本 ``control.sqlite3`` SHA 前后完全一致。

另加两个判定用例：
  * ``wip_stale_sidecar``：只改文档、**不**同步 sidecar —— 复现 WIP 探针的
    ``ValueError: preregistration SHA256 mismatch``，用来判定那是探针构造缺陷
    而不是拒绝分支缺陷；
  * ``stale_sidecar_then_synced``：同样的改动，同步 sidecar 并重新批准后，
    同一条分支给出干净的 ``refused / source_binding_drift``。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path("/Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments")))

import p39common as C

WORK = Path("/tmp/p39-rejections")
DOC_SHA = "1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30"
BOGUS = "0" * 64


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _prereg():
    if str(C.SRC) not in sys.path:
        sys.path.insert(0, str(C.SRC))
    from ainerzero.v9.experiments.s1 import prereg

    return prereg


def _host(name: str, *, approve: bool = False) -> Path:
    host = WORK / name
    if host.exists():
        shutil.rmtree(host)
    C.copy_phase1(host)
    C.write_research_log(host, DOC_SHA if approve else None)
    return host


def _doc_path(host: Path) -> Path:
    return host / "artifacts/v9/s1/phase1/r13/pre_registration.json"


def _mutate_doc(host: Path, mutator, *, sync_sidecar: bool, approve: bool) -> str:
    prereg = _prereg()
    path = _doc_path(host)
    document = json.loads(path.read_text(encoding="utf-8"))
    mutator(document)
    path.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    digest = prereg.document_sha256(document)
    if sync_sidecar:
        prereg.write_sha256_file(path, digest)
    if approve:
        C.write_research_log(host, digest)
    return digest


def _case(name: str, host: Path, args: tuple[str, ...], expected_stage: str,
          *, baseline: str | None = None) -> dict:
    ledger = host / "artifacts/v9/s1/phase1/control.sqlite3"
    before = baseline or _sha(ledger)
    result = C.run_driver(C.EVIDENCE / "driver_entry.py", host, *args)
    payload = result["payload"] or {}
    report = payload.get("report") or {}
    after = _sha(ledger)
    ok = (
        report.get("status") == "refused"
        and report.get("refused_stage") == expected_stage
        and before == after
    )
    return {
        "case": name,
        "args": list(args),
        "expected_stage": expected_stage,
        "actual_status": report.get("status"),
        "actual_stage": report.get("refused_stage"),
        "ledger_before": before,
        "ledger_after": after,
        "ledger_bytes_unchanged": before == after,
        "registered_run_id": report.get("run_id"),
        "ok": ok,
        "stderr_tail": result["stderr_tail"][-400:] if not ok else "",
    }


def main() -> dict:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    cases: list[dict] = []

    # ---- train 分支 ------------------------------------------------------
    h = _host("train-no-approval")
    cases.append(_case("train/preregistration_not_approved", h, ("train", "--arm", "arm2", "--seed", "0"),
                       "preregistration_not_approved"))

    h = _host("train-source-drift")
    _mutate_doc(
        h,
        lambda d: d["source_identity"]["package_files"].__setitem__(
            "src/ainerzero/v9/experiments/s1/worker.py", BOGUS
        ),
        sync_sidecar=True,
        approve=True,
    )
    cases.append(_case("train/source_binding_drift", h, ("train", "--arm", "arm2", "--seed", "0"),
                       "source_binding_drift"))

    h = _host("train-dataset-mismatch")
    _mutate_doc(
        h,
        lambda d: d["data_identity"].__setitem__("dataset_digest", BOGUS),
        sync_sidecar=True,
        approve=True,
    )
    cases.append(_case("train/dataset_identity_mismatch", h, ("train", "--arm", "arm2", "--seed", "0"),
                       "dataset_identity_mismatch"))

    h = _host("train-already-attempted", approve=True)
    seeded = (C.run_driver(C.EVIDENCE / "driver_entry.py", h, "seed-attempt", "--arm", "arm2", "--seed", "0")["payload"] or {})
    cases.append(_case("train/already_attempted", h, ("train", "--arm", "arm2", "--seed", "0"),
                       "already_attempted", baseline=seeded.get("ledger_sha256_after")))

    h = _host("train-phase-wall", approve=True)
    seeded = (C.run_driver(C.EVIDENCE / "driver_entry.py", h, "seed-attempt", "--arm", "arm3", "--seed", "1",
                           "--age", "14300")["payload"] or {})
    cases.append(_case("train/phase_budget_exceeded", h, ("train", "--arm", "arm2", "--seed", "0"),
                       "phase_budget_exceeded", baseline=seeded.get("ledger_sha256_after")))

    # ---- eval 分支 -------------------------------------------------------
    h = _host("eval-source-drift")
    _mutate_doc(
        h,
        lambda d: d["source_identity"]["package_files"].__setitem__(
            "src/ainerzero/v9/experiments/s1/prereg.py", BOGUS
        ),
        sync_sidecar=True,
        approve=False,
    )
    cases.append(_case("eval/source_binding_drift", h, ("eval", "--arm", "arm2", "--seed", "0"),
                       "source_binding_drift"))

    h = _host("eval-d-guard")
    seeded = (C.run_driver(C.EVIDENCE / "driver_entry.py", h, "seed-attempt", "--arm", "arm1", "--seed", "0")["payload"] or {})
    cases.append(_case("eval/already_attempted(D guard)", h, ("eval", "--arm", "arm1", "--seed", "0"),
                       "already_attempted", baseline=seeded.get("ledger_sha256_after")))

    h = _host("eval-binding-unavailable")
    cases.append(_case("eval/eval_binding_unavailable", h, ("eval", "--arm", "arm2", "--seed", "0"),
                       "eval_binding_unavailable"))

    # eval_call_budget_exceeded：需要 development windows 多到 window_batches > 175。
    # 用 s1_testkit 造一个 100 个 development world 的合成 host（600 windows -> 38 batches/ckpt
    # -> 5 x 38 = 190 > 175）。
    from s1_testkit import make_plan, stage_phase1_host  # noqa: E402

    from ainerzero.v9.experiments.s1 import spec  # noqa: E402

    budget_host = WORK / "eval-call-budget"
    staged = stage_phase1_host(
        budget_host,
        plan=make_plan(train_worlds=4, development_worlds=100, rounds=1),
        experiment_id=spec.R13_EXPERIMENT_ID,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )
    budget_case = _case("eval/eval_call_budget_exceeded", budget_host,
                        ("eval", "--arm", "arm3", "--seed", "1"), "eval_call_budget_exceeded")
    budget_case["synthetic_host"] = {
        "phase1": str(staged["phase1"]),
        "development_worlds": 100,
        "note": "合成 host（s1_testkit.stage_phase1_host），不是生产副本；只用于触发调用预算门",
    }
    cases.append(budget_case)

    # ---- 判定用例：WIP 的 ValueError 是探针构造缺陷 -----------------------
    h = _host("wip-stale-sidecar", approve=True)
    _mutate_doc(
        h,
        lambda d: d["source_identity"]["package_files"].__setitem__(
            "src/ainerzero/v9/experiments/s1/worker.py", BOGUS
        ),
        sync_sidecar=False,   # 故意不同步 sidecar：WIP 探针就是这么写的
        approve=False,
    )
    ledger = h / "artifacts/v9/s1/phase1/control.sqlite3"
    before = _sha(ledger)
    res = C.run_driver(C.EVIDENCE / "driver_entry.py", h, "train", "--arm", "arm2", "--seed", "0")
    payload = res["payload"] or {}
    report = payload.get("report") or {}
    wip_case = {
        "case": "judgement/wip_stale_sidecar_reproduces_ValueError",
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "error": report.get("error"),
        "ledger_before": before,
        "ledger_after": _sha(ledger),
        "ledger_bytes_unchanged": before == _sha(ledger),
        "verdict": (
            "WIP 的 train_source_drift / train_dataset_mismatch 以 failed+ValueError 结束，"
            "是因为它改了文档却没同步 pre_registration.json.sha256：入口在 verify_frozen_file "
            "就抛 ValueError，还没走到 source_binding / dataset 判定。这是探针构造缺陷，"
            "不是 P34 拒绝分支的缺陷（同一改动同步 sidecar 后即得干净 refused）。"
        ),
    }
    wip_case["ok"] = (
        report.get("status") == "failed"
        and "preregistration SHA256 mismatch" in str(report.get("error"))
        and wip_case["ledger_bytes_unchanged"]
    )

    checks = {c["case"]: c["ok"] for c in cases}
    checks[wip_case["case"]] = wip_case["ok"]
    return {
        "purpose": "每个 CPU-only 拒绝分支都在隔离副本上断言台账字节不变",
        "cases": cases,
        "judgement_case": wip_case,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "branches_covered": sorted(checks),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("rejections", main))
