#!/usr/bin/env python3
"""P35 r2 必做 4/5：登记值逐项核对 + r11→r12 逐叶差异 + commands.py 是否真的没改。

三件事都独立复算，不引用 P34 的 harness 输出：
  1. 登记值 3510 / 1200（fail-closed）/ 1250 / 175 / 种子 / phase 14400 逐项定位；
  2. r11 与 r12 两份冻结件展平成叶，逐叶比对；变化只允许 experiment_id、来源绑定
     与时间派生字段，白名单外的变化必须为 0；
  3. commands.py 与 ``reports/V9-P9/r12/before/`` 的副本、以及 r11 文档里的绑定值对照。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

COMMANDS_REL = "src/ainerzero/v9/experiments/s1/commands.py"
BEFORE = C.REPO / "reports/V9-P9/r12/before" / COMMANDS_REL
SOURCE_FILES = (
    "src/ainerzero/v9/experiments/s1/spec.py",
    "src/ainerzero/v9/experiments/s1/prereg.py",
    "src/ainerzero/v9/experiments/s1/worker.py",
    "src/ainerzero/v9/experiments/s1/commands.py",
)
ALLOWED_EXACT = {
    "/experiment_id",
    "/created_unix",
    "/source_identity/package_map_digest",
    "/source_identity/spec",
    "/source_identity/spec/sha256",
}
ALLOWED_PREFIX = (
    "/source_identity/package_files/",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from flatten(value, f"{prefix}/{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from flatten(value, f"{prefix}[{index}]")
    else:
        yield prefix, obj


def main() -> dict:
    r11 = json.loads(C.R11_DOC.read_text(encoding="utf-8"))
    r12 = json.loads(C.R12_DOC.read_text(encoding="utf-8"))

    # ---------- 1. 登记值 ----------
    registration = {
        "updates_3510": {
            "training_protocol.updates": r12["training_protocol"]["updates"],
            "timing.registered_updates": r12["timing"]["registered_updates"],
            "budget_estimate.updates": r12["budget_estimate"]["updates"],
            "arms.arm2.training_updates": r12["arms"]["arm2"]["training_updates"],
            "arms.arm3.training_updates": r12["arms"]["arm3"]["training_updates"],
            "arms.arm4.training_updates": r12["arms"]["arm4"]["training_updates"],
            "checkpoint_updates[-1]": r12["training_protocol"]["checkpoint_updates"][-1],
        },
        "deadline_1200": {
            "timing.deadline_seconds": r12["timing"]["deadline_seconds"],
            "timing.registered_deadline_seconds": r12["timing"]["registered_deadline_seconds"],
            "timing.deadline_source": r12["timing"]["deadline_source"],
            "budget_estimate.registered_deadline_seconds": r12["budget_estimate"][
                "registered_deadline_seconds"
            ],
        },
        "supervision_1250": {
            "timing.supervision_seconds": r12["timing"]["supervision_seconds"],
            "timing.registered_supervision_seconds": r12["timing"][
                "registered_supervision_seconds"
            ],
        },
        "eval_batches_175": {"training_protocol.eval_batches": r12["training_protocol"]["eval_batches"]},
        "seeds": {"training_protocol.seeds": r12["training_protocol"]["seeds"]},
        "phase_wall_14400": {"timing.phase_wall_max_seconds": r12["timing"]["phase_wall_max_seconds"]},
        "checkpoint_updates": {"training_protocol.checkpoint_updates": r12["training_protocol"]["checkpoint_updates"]},
    }
    expect = {
        "updates_3510": 3510,
        "deadline_1200": 1200,
        "supervision_1250": 1250,
        "eval_batches_175": 175,
        "seeds": [0, 1, 2],
        "phase_wall_14400": 14400.0,
        "checkpoint_updates": [0, 439, 878, 1755, 3510],
    }
    registration_ok = {}
    for key, want in expect.items():
        values = registration[key]
        bad = {path: value for path, value in values.items() if value != want}
        # deadline_source 是字符串字段，单独判
        if key == "deadline_1200":
            bad = {
                path: value
                for path, value in values.items()
                if path.endswith("deadline_source")
                and "R20261023-S1-phase1-r11-budget" not in str(value)
                or (not path.endswith("deadline_source") and value != want)
            }
        registration_ok[key] = {"expected": want, "values": values, "mismatches": bad, "ok": not bad}

    # ---------- 2. 逐叶差异 ----------
    leaves_r11 = dict(flatten(r11))
    leaves_r12 = dict(flatten(r12))
    only_r11 = sorted(set(leaves_r11) - set(leaves_r12))
    only_r12 = sorted(set(leaves_r12) - set(leaves_r11))
    changed = [
        {"path": path, "r11": leaves_r11[path], "r12": leaves_r12[path]}
        for path in sorted(set(leaves_r11) & set(leaves_r12))
        if leaves_r11[path] != leaves_r12[path]
    ]

    def allowed(path: str) -> bool:
        return path in ALLOWED_EXACT or path.startswith(ALLOWED_PREFIX)

    outside = [item for item in changed if not allowed(item["path"])]
    # 绑定的 4 个源文件里，哪些在 r11→r12 之间真的变了
    bound_changes = {}
    for rel in SOURCE_FILES:
        key = f"/source_identity/package_files/{rel}"
        if leaves_r11.get(key) != leaves_r12.get(key):
            bound_changes[rel] = {"r11": leaves_r11.get(key), "r12": leaves_r12.get(key)}

    # ---------- 3. commands.py ----------
    commands_now = _sha(C.REPO / COMMANDS_REL)
    commands_before = _sha(BEFORE) if BEFORE.is_file() else None
    commands_in_r11_doc = r11["source_identity"]["package_files"].get(COMMANDS_REL)
    commands_in_r12_doc = r12["source_identity"]["package_files"].get(COMMANDS_REL)
    commands_check = {
        "current_sha256": commands_now,
        "before_copy_sha256": commands_before,
        "r11_document_bound_sha256": commands_in_r11_doc,
        "r12_document_bound_sha256": commands_in_r12_doc,
        "unchanged_vs_before_copy": commands_now == commands_before,
        "unchanged_vs_r11_document": commands_now == commands_in_r11_doc,
        "r12_document_binds_current_bytes": commands_now == commands_in_r12_doc,
        "equals_seal_value": commands_now
        == "c66e02c383a13ae30ad7ea509e2ad8f991200cdee1d528b7d58903d420cfb91a",
    }

    checks = {
        "registration_values_all_match": all(v["ok"] for v in registration_ok.values()),
        "no_leaf_only_in_r11": not only_r11,
        "no_leaf_only_in_r12": not only_r12,
        "leaf_changes_all_inside_allowlist": not outside,
        "commands_py_unchanged_vs_before": commands_check["unchanged_vs_before_copy"],
        "commands_py_unchanged_vs_r11": commands_check["unchanged_vs_r11_document"],
        "r12_document_binds_current_commands_py": commands_check["r12_document_binds_current_bytes"],
    }
    return {
        "purpose": "登记值逐项 + r11→r12 叶差异 + commands.py 未改",
        "r11_document_sha256": _sha(C.R11_DOC),
        "r12_document_sha256": _sha(C.R12_DOC),
        "registration_values": registration_ok,
        "leaf_diff": {
            "leaves_r11": len(leaves_r11),
            "leaves_r12": len(leaves_r12),
            "changed_count": len(changed),
            "changed": changed,
            "only_in_r11": only_r11,
            "only_in_r12": only_r12,
            "outside_allowlist": outside,
            "allowlist": {"exact": sorted(ALLOWED_EXACT), "prefix": list(ALLOWED_PREFIX)},
            "bound_source_files_changed": bound_changes,
        },
        "commands_py": commands_check,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("registration-leaf-commands", main))
