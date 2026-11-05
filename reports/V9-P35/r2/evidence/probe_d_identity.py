#!/usr/bin/env python3
"""P35 r2 必修 3：运行时 D 身份来自 ``spec.ARM_SPECS``（源码绑定），不是文档 arm1 行。

r1 被打回的原因：只做了源码字符串 grep，不是证据。这里做双向的运行时取证：

  A. 隔离副本里把**文档** arm1 行的 identity 改坏（tensors_sha256 / manifest_sha256 /
     checkpoint_id 全部换成假值），同步 sidecar 并重新批准，再跑 eval arm1：
     运行时仍通过 D 身份校验并走到 MLX 哨兵 —— 文档 arm1 行不参与 D 判定；
     同时打印运行时实际校验出的 digest，逐项等于 ``spec.ARM_SPECS["arm1"]["identity"]``。

  B. 反过来，在临时源码副本里只改 ``spec.ARM_SPECS["arm1"]["identity"]["tensors_sha256"]``：
     eval arm1 立刻 ``source_binding_drift`` —— spec.py 在文档的 package_files 里被绑，
     所以 D 身份的真正信任根是受源码绑定的 spec，而不是可被重写的文档行。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

WORK = Path("/tmp/p35r2-didentity")
DOC_SHA_ORIGINAL = "044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd"
BOGUS = "0" * 64


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> dict:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    # ---------- A. 文档 arm1 行改坏，运行时仍按 spec 校验 ----------
    host = WORK / "doc-mutated"
    phase1 = C.copy_phase1(host)
    doc_path = phase1 / "r12" / "pre_registration.json"
    document = json.loads(doc_path.read_text(encoding="utf-8"))
    doc_identity_before = dict(document["arms"]["arm1"]["identity"])
    document["arms"]["arm1"]["identity"].update(
        {
            "tensors_sha256": BOGUS,
            "manifest_sha256": BOGUS,
            "metadata_sha256": BOGUS,
            "checkpoint_id": "00000000-0000-0000-0000-000000000000",
            "pilot_dir": "artifacts/pilot/pilot-DOES-NOT-EXIST",
            "experiment_id": "not-the-registered-experiment",
        }
    )
    document["arms"]["arm1"]["name"] = "P35 r2 tampered arm1 row (isolated copy only)"
    doc_path.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")

    # 同步 sidecar（否则 verify_frozen_file 会先报哈希失配），再重新批准
    sys.path.insert(0, str(C.SRC))
    from ainerzero.v9.experiments.s1 import prereg  # noqa: E402

    new_doc_sha = prereg.document_sha256(document)
    prereg.write_sha256_file(doc_path, new_doc_sha)
    C.write_research_log(host, new_doc_sha)

    identity_run = C.run_driver(C.EVIDENCE / "driver_entry.py", host, "identity")
    identity_payload = (identity_run["payload"] or {}).get("identity") or {}

    d_run = C.run_driver(C.EVIDENCE / "driver_entry.py", host, "eval", "--arm", "arm1", "--seed", "0")
    d_payload = d_run["payload"] or {}
    d_report = d_payload.get("report") or {}

    # ---------- B. 只改源码副本里的 spec.ARM_SPECS ----------
    checkout = WORK / "spec-mutated-src"
    shutil.copytree(C.SRC, checkout)
    spec_copy = checkout / "ainerzero/v9/experiments/s1/spec.py"
    spec_text = spec_copy.read_text(encoding="utf-8")
    needle = '"tensors_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a"'
    assert spec_text.count(needle) == 1, "spec.ARM_SPECS 的 arm1 tensors_sha256 不在预期位置"
    spec_copy.write_text(spec_text.replace(needle, f'"tensors_sha256": "{BOGUS}"'), encoding="utf-8")

    host_b = WORK / "spec-mutated-host"
    C.copy_phase1(host_b)
    C.write_research_log(host_b, DOC_SHA_ORIGINAL)
    b_run = C.run_driver(
        C.EVIDENCE / "driver_entry.py", host_b, "eval", "--arm", "arm1", "--seed", "0",
        source_root=checkout,
    )
    b_payload = b_run["payload"] or {}
    b_report = b_payload.get("report") or {}

    # ---------- B2. 文档里的 spec.py 绑定值改坏 -> source_binding_drift ----------
    host_b2 = WORK / "spec-binding-host"
    phase1_b2 = C.copy_phase1(host_b2)
    doc_b2_path = phase1_b2 / "r12" / "pre_registration.json"
    doc_b2 = json.loads(doc_b2_path.read_text(encoding="utf-8"))
    bound_spec_key = "src/ainerzero/v9/experiments/s1/spec.py"
    original_bound = doc_b2["source_identity"]["package_files"][bound_spec_key]
    doc_b2["source_identity"]["package_files"][bound_spec_key] = BOGUS
    doc_b2_path.write_text(json.dumps(doc_b2, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    doc_b2_sha = prereg.document_sha256(doc_b2)
    prereg.write_sha256_file(doc_b2_path, doc_b2_sha)
    C.write_research_log(host_b2, doc_b2_sha)
    b2_run = C.run_driver(C.EVIDENCE / "driver_entry.py", host_b2, "eval", "--arm", "arm1", "--seed", "0")
    b2_payload = b2_run["payload"] or {}
    b2_report = b2_payload.get("report") or {}

    checks = {
        "document_arm1_row_actually_tampered": identity_payload.get("document_differs_from_spec"),
        "runtime_identity_matches_spec_all_fields": all(
            (identity_payload.get("runtime_matches_spec") or {}).values()
        ),
        "spec_py_is_bound_in_document": (
            identity_payload.get("spec_py_bound_in_document")
            == identity_payload.get("spec_py_actual_sha256")
        ),
        "eval_arm1_still_reaches_sentinel_with_tampered_doc_row": d_payload.get("sentinel_stopped")
        is True,
        "eval_arm1_not_refused_for_identity": d_report.get("status") != "refused",
        "mutating_spec_changes_the_D_verdict": b_report.get("refused_stage")
        == "arm1_identity_verification_failed",
        "spec_mutation_error_names_the_mutated_field": "tensors_sha256" in str(b_report.get("message")),
        "spec_mutation_run_is_from_checkout": str(checkout) in str(b_payload.get("worker_module")),
        "tampering_the_bound_spec_hash_refuses_source_binding": b2_report.get("refused_stage")
        == "source_binding_drift",
    }
    return {
        "purpose": "运行时 D 身份 = spec.ARM_SPECS（源码绑定），不是文档 arm1 行",
        "A_document_arm1_tampered": {
            "isolated_document": str(doc_path),
            "original_document_sha256": DOC_SHA_ORIGINAL,
            "tampered_document_sha256": new_doc_sha,
            "sidecar_synced": True,
            "reapproved_in_isolated_research_log": True,
            "document_arm1_identity_original": doc_identity_before,
            "document_differs_from_spec": identity_payload.get("document_differs_from_spec"),
            "runtime_verified": identity_payload.get("runtime_verified"),
            "runtime_matches_spec": identity_payload.get("runtime_matches_spec"),
            "eval_arm1": {
                "status": d_report.get("status"),
                "refused_stage": d_report.get("refused_stage"),
                "error": d_report.get("error"),
                "d_candidate_attempts": d_report.get("d_candidate_attempts"),
                "sentinel_stopped": d_payload.get("sentinel_stopped"),
                "sentinel_stop_at": [
                    e for e in d_payload.get("sentinel", []) if e["action"] == "sentinel_stop"
                ],
                "mlx_loaded": d_payload.get("mlx_loaded"),
            },
        },
        "B1_spec_arm1_identity_mutated_in_source_copy": {
            "checkout": str(checkout),
            "field": "spec.ARM_SPECS['arm1']['identity']['tensors_sha256']",
            "new_value": BOGUS,
            "eval_arm1": {
                "status": b_report.get("status"),
                "refused_stage": b_report.get("refused_stage"),
                "message": b_report.get("message"),
                "sentinel_stopped": b_payload.get("sentinel_stopped"),
            },
            "note": (
                "只改副本里的 spec.ARM_SPECS，运行时的 D 判定当场翻脸 —— 说明 D 身份的**值**"
                "确实来自 spec.ARM_SPECS。注意 source_binding_state 哈希的是已登记 host root"
                "（spec.REPO_ROOT）下的文件，所以外来 checkout 的 spec.py 副本不归它管，"
                "真正拦住的是 D 身份校验本身；这一点如实记录。"
            ),
        },
        "B2_document_bound_spec_hash_tampered": {
            "field": f"source_identity.package_files[{bound_spec_key}]",
            "original_value": original_bound,
            "new_value": BOGUS,
            "eval_arm1": {
                "status": b2_report.get("status"),
                "refused_stage": b2_report.get("refused_stage"),
                "message": b2_report.get("message"),
                "sentinel_stopped": b2_payload.get("sentinel_stopped"),
            },
        },
        "trust_chain": [
            "identity._identity() -> spec.ARM_SPECS['arm1']['identity']",
            "spec.py 的 SHA256 在文档 source_identity.package_files 里被绑定（B2 证明它承重）",
            "文档 arms.arm1.identity 只出现在文档里，运行时任何代码路径都不读它做 D 判定（A 证明）",
        ],
        "checks": checks,
        "all_checks_pass": all(bool(v) for v in checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("d-identity-runtime", main))
