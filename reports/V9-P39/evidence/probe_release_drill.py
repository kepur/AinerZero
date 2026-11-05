#!/usr/bin/env python3
"""P39 必修 2：批准后放行演练，必须停在 MLX 哨兵处（train / eval arm2-4 / arm1 D 路径）。

r1 被打回的原因：eval 停在 ``eval_binding_unavailable``，根本没走到 MLX 哨兵；arm1 的
D 路径没有演练。这里补齐：

  1. 隔离副本里放一份临时 RESEARCH_LOG，stageA 节内**只有一条**指向 r12 doc 的合格批准行；
  2. train 对 1 个 arm×seed 放行，走到第一次真实 MLX 导入（``arms.py`` 模块级
     ``import mlx.core``）时被哨兵拦住；
  3. 借产品自己的 API（``_open_train_run`` + ``reserve`` + ``_complete_run``）在**副本**里
     伪造 1 个 arm×seed 的完成训练记录（含 completion receipt 与 params.npz），
     让 ``_eval_binding_precondition`` 真正成立，再让 eval 走到哨兵；
  4. arm1 的 D 路径同样走到哨兵。

对照：同一 host、同一源码，把批准行去掉，train 必须回到
``preregistration_not_approved``（证明这条批准行是承重的，不是摆设）。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p39common as C

DOC_SHA = "1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30"
WORK = Path("/tmp/p39-release")


def _fresh(name: str, *, approve: bool) -> Path:
    host = WORK / name
    if host.exists():
        shutil.rmtree(host)
    C.copy_phase1(host)
    C.write_research_log(host, DOC_SHA if approve else None)
    return host


def _run(host: Path, *args: str) -> dict:
    return C.run_driver(C.EVIDENCE / "driver_entry.py", host, *args)


def main() -> dict:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    cases: dict[str, dict] = {}

    # --- 对照：没有批准行，train 必须被拒 ---------------------------------
    host_noappr = _fresh("no-approval", approve=False)
    r = _run(host_noappr, "train", "--arm", "arm2", "--seed", "0")
    cases["control_train_without_approval"] = {
        "status": (r["payload"] or {}).get("report", {}).get("status"),
        "refused_stage": (r["payload"] or {}).get("report", {}).get("refused_stage"),
        "ledger_unchanged": (r["payload"] or {}).get("ledger_unchanged"),
        "sentinel_stopped": (r["payload"] or {}).get("sentinel_stopped"),
    }

    # --- 1. train：批准后放行，停在 MLX 哨兵 ------------------------------
    host_train = _fresh("train", approve=True)
    r = _run(host_train, "train", "--arm", "arm2", "--seed", "0")
    p = r["payload"] or {}
    rep = p.get("report") or {}
    cases["train_arm2_seed0"] = {
        "approval_approved": rep.get("approval_approved"),
        "source_binding": rep.get("source_binding"),
        "dataset": rep.get("dataset"),
        "status": rep.get("status"),
        "error": rep.get("error"),
        "run_id": rep.get("run_id"),
        "sentinel_stopped": p.get("sentinel_stopped"),
        "sentinel_stop_at": [e for e in p.get("sentinel", []) if e["action"] == "sentinel_stop"],
        "mlx_loaded": p.get("mlx_loaded"),
        "ledger_changed": p.get("ledger_unchanged") is False,
    }

    # --- 2. eval arm2 / arm4：伪造完成记录后放行，停在哨兵 ----------------
    for arm, seed in (("arm2", 0), ("arm4", 1)):
        host = _fresh(f"eval-{arm}", approve=True)
        fab = _run(host, "fabricate", "--arm", arm, "--seed", str(seed))
        fab_payload = fab["payload"] or {}
        ev = _run(host, "eval", "--arm", arm, "--seed", str(seed))
        ep = ev["payload"] or {}
        erep = ep.get("report") or {}
        cases[f"eval_{arm}_seed{seed}"] = {
            "fabricated_run": fab_payload.get("fabricated"),
            "eval_binding": erep.get("eval_binding"),
            "status": erep.get("status"),
            "error": erep.get("error"),
            "run_id": erep.get("run_id"),
            "sentinel_stopped": ep.get("sentinel_stopped"),
            "sentinel_stop_at": [e for e in ep.get("sentinel", []) if e["action"] == "sentinel_stop"],
            "mlx_loaded": ep.get("mlx_loaded"),
        }

    # --- 3. arm1 的 D 路径：放行到哨兵 -----------------------------------
    host_d = _fresh("eval-arm1", approve=True)
    ev = _run(host_d, "eval", "--arm", "arm1", "--seed", "0")
    ep = ev["payload"] or {}
    erep = ep.get("report") or {}
    cases["eval_arm1_d_path"] = {
        "d_candidate_attempts": erep.get("d_candidate_attempts"),
        "status": erep.get("status"),
        "error": erep.get("error"),
        "run_id": erep.get("run_id"),
        "experiment_id": erep.get("experiment_id"),
        "sentinel_stopped": ep.get("sentinel_stopped"),
        "sentinel_stop_at": [e for e in ep.get("sentinel", []) if e["action"] == "sentinel_stop"],
        "mlx_loaded": ep.get("mlx_loaded"),
    }

    checks = {
        "control_refused_without_approval": (
            cases["control_train_without_approval"]["status"] == "refused"
            and cases["control_train_without_approval"]["refused_stage"]
            == "preregistration_not_approved"
            and cases["control_train_without_approval"]["ledger_unchanged"] is True
        ),
        "train_approved_and_stopped_at_sentinel": (
            cases["train_arm2_seed0"]["approval_approved"] is True
            and cases["train_arm2_seed0"]["sentinel_stopped"] is True
        ),
        "train_sentinel_at_arms_module_import": any(
            e["caller_file"].endswith("experiments/s1/arms.py")
            for e in cases["train_arm2_seed0"]["sentinel_stop_at"]
        ),
        "eval_arm2_binding_ok_and_sentinel": (
            (cases["eval_arm2_seed0"]["eval_binding"] or {}).get("status") == "ok"
            and cases["eval_arm2_seed0"]["sentinel_stopped"] is True
        ),
        "eval_arm4_binding_ok_and_sentinel": (
            (cases["eval_arm4_seed1"]["eval_binding"] or {}).get("status") == "ok"
            and cases["eval_arm4_seed1"]["sentinel_stopped"] is True
        ),
        "arm1_d_path_sentinel": cases["eval_arm1_d_path"]["sentinel_stopped"] is True,
        "arm1_d_guard_passed": (cases["eval_arm1_d_path"]["d_candidate_attempts"] or {}).get(
            "status"
        ) == "ok",
        "mlx_never_loaded_anywhere": all(
            not case.get("mlx_loaded")
            for case in cases.values()
            if isinstance(case, dict) and "mlx_loaded" in case
        ),
    }
    return {
        "purpose": "批准后放行演练：train / eval(arm2,arm4) / arm1 D 路径都必须停在 MLX 哨兵",
        "approval_line_document_sha256": DOC_SHA,
        "approval_line_written_only_in_isolated_hosts": True,
        "sentinel_rule": (
            "拦截 mlx / mlx.* 的导入：resource_gate 的尽力探测处抛 ImportError（该处本就 "
            "except Exception 报 unavailable，不伪造数值）；其他调用方抛 MlxSentinel，"
            "入口停在那里。mlx 从未进入 sys.modules。"
        ),
        "cases": cases,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("release-drill", main))
