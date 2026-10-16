"""T18 独立资格 oracle（非作者实现）。

不复用作者 `check_teacher_cache_v2.py` 的任何函数（store_problems / train_eligible）。
本文件从零按 T1 r3 文档 §2.5 / §10 与 schema 重写 B1–B4 规则，作为独立判据：

- B1 来源保留：AWZ→external_derived 由 schema 强制；每条 entry 的 source.manifest_ref
  必须解析到调用方冻结清单（trusted context）里的**原来源**，world_key/partition/upstream
  逐项相同；资格不得从同 blob 的另一来源继承。
- B2 时间绑定：source.timestamps_* 必须与所引用 blob.key_material.input.timestamps_* 逐项
  相同；source/blob/原来源/Observation 的 time_domain 一致；tick/秒 = t/120（容差 1e-9）；
  截止只取可信 Observation；use=input 不得含未来帧，target 可含。
- B3 批准：当前获批集合为空；registry 必须是固定空登记；任何非空/错登记/未批准 revision 拒训。
- B4 指纹：derivation.teacher_id / 有序 weights_sha256 / preprocess_spec_sha256 与引用 blob 逐项一致。

`disabled` 只用于隔离对照（关掉某条规则，看其专用反例是否漏检），不是生产开关。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "contracts/v9/teacher_cache.v2.schema.json"
REGISTRY_ID = "adr-0005-current-approved-empty-20261016"
EPS = 1e-9


def canon_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canon_sha(obj) -> str:
    return hashlib.sha256(canon_bytes(obj)).hexdigest()


def near(a, b) -> bool:
    return isinstance(a, (int, float)) and not isinstance(a, bool) and \
        isinstance(b, (int, float)) and not isinstance(b, bool) and math.isclose(a, b, abs_tol=EPS, rel_tol=0)


def load_schema(disabled=()) -> dict:
    s = json.loads(SCHEMA_PATH.read_text())
    if "awz_schema" in disabled:
        s = copy.deepcopy(s)
        up = s["$defs"]["teacher_entry"]["properties"]["provenance"]["properties"]["upstream"]
        up.pop("allOf", None)
    return s


def entry_id(e: dict) -> str:
    return canon_sha({
        "cache_key": e["cache_key"],
        "world_key": e["source"]["world_key"],
        "partition": e["source"]["partition"],
        "input_sha256": e["provenance"]["upstream"]["input_ref"]["sha256"],
        "use": e["provenance"]["derivation"]["use"],
    })


def validate(records, context, expected_sha, disabled=()) -> list:
    d = set(disabled)
    if not isinstance(records, list) or not records:
        return ["records_structure"]

    if "schema" not in d:
        v = Draft202012Validator(load_schema(d))
        if any(not v.is_valid(r) for r in records):
            return ["schema"]

    if context is None:
        return ["trusted_context_missing"]
    if "context_identity" not in d and (not expected_sha or canon_sha(context) != expected_sha):
        return ["trusted_context_identity"]
    if "schema" not in d:
        vc = Draft202012Validator({"$defs": load_schema(d)["$defs"], "$ref": "#/$defs/trusted_context"})
        if not vc.is_valid(context):
            return ["trusted_context_schema"]

    P = []
    reg = context["approval_registry"]
    if "registry" not in d and (reg.get("registry_id") != REGISTRY_ID or reg.get("entries")):
        P.append("approval_registry_not_current_empty")

    manifest = context["source_manifest"]
    srcs = manifest["sources"]
    if len({s["source_id"] for s in srcs}) != len(srcs):
        P.append("duplicate_source_identity")
    by_id = {s["source_id"]: s for s in srcs}
    obs = context["observation"]
    if not near(obs["t_s"], obs["t_ticks"] / 120):
        P.append("trusted_observation_clock")

    blobs = {}
    dup = False
    for r in records:
        if r["record_type"] == "teacher_blob":
            if r["cache_key"] in blobs:
                dup = True
            blobs[r["cache_key"]] = r
    if dup:
        P.append("duplicate_blob_key")

    for b in blobs.values():
        k = b["key_material"]
        inp = k["input"]
        if "key" not in d and canon_sha(k) != b["cache_key"]:
            P.append("cache_key_mismatch")
        if "tick_seconds" not in d and (
            len(inp["timestamps_ticks"]) != len(inp["timestamps_s"])
            or any(not near(t / 120, s) for t, s in zip(inp["timestamps_ticks"], inp["timestamps_s"]))
        ):
            P.append("blob_tick_seconds_mismatch")

    parts = {}
    for e in (r for r in records if r["record_type"] == "teacher_entry"):
        b = blobs.get(e["cache_key"])
        if b is None:
            P.append("orphan_entry")
            continue
        k = b["key_material"]
        inp = k["input"]
        src = e["source"]
        up = e["provenance"]["upstream"]
        dv = e["provenance"]["derivation"]

        if "eid" not in d and entry_id(e) != e["entry_id"]:
            P.append("entry_id_mismatch")
        if "input" not in d and up["input_ref"]["sha256"] != inp["sha256"]:
            P.append("input_mismatch")
        if "teacher" not in d and dv["teacher_id"] != k["teacher"]["teacher_id"]:
            P.append("derivation_teacher_mismatch")
        if "weights" not in d and dv["weights_sha256"] != [w["sha256"] for w in k["teacher"]["weights"]]:
            P.append("derivation_weights_mismatch")
        if "preprocess" not in d and dv["preprocess_spec_sha256"] != k["preprocess"]["spec_sha256"]:
            P.append("derivation_preprocess_mismatch")
        if "noise" not in d and k["teacher"]["teacher_kind"] == "feature" and e["noise_model_ref"] is not None:
            P.append("feature_with_noise_model")

        ref = src["manifest_ref"]
        original = by_id.get(ref["source_id"]) if ref["manifest_id"] == manifest["manifest_id"] else None
        if "binding" not in d and (
            original is None
            or original["world_key"] != src["world_key"]
            or original["partition"] != src["partition"]
            or original["upstream"] != up
        ):
            P.append("original_source_binding_mismatch")
        if "domain" not in d and (
            src["time_domain"] != inp["time_domain"]
            or inp["time_domain"] != obs["time_domain"]
            or original is None
            or original["time_domain"] != inp["time_domain"]
        ):
            P.append("observation_time_domain_mismatch")
        if "source_times" not in d and (
            src["timestamps_ticks"] != inp["timestamps_ticks"] or src["timestamps_s"] != inp["timestamps_s"]
        ):
            P.append("source_blob_timestamps_mismatch")
        if "cutoff" not in d and (
            e["as_of_t_ticks"] != obs["t_ticks"] or not near(e["as_of_t_s"], obs["t_ticks"] / 120)
        ):
            P.append("current_observation_cutoff_mismatch")
        if "asof" not in d and dv["use"] == "input" and (
            max(inp["timestamps_ticks"]) > obs["t_ticks"] or max(inp["timestamps_s"]) > obs["t_s"] + EPS
        ):
            P.append("input_after_trusted_observation")
        if "approval" not in d and up["eligibility"]["basis"] == "adr_0005_revision":
            P.append("unapproved_adr_revision")
        if src["partition"] in ("train", "development", "final"):
            parts.setdefault(e["cache_key"], set()).add(src["partition"])

    if "cross" not in d and any(len(v) > 1 for v in parts.values()):
        P.append("cross_partition_blob")
    return sorted(set(P))


def eligible(e, records, context, expected_sha, disabled=()) -> bool:
    d = set(disabled)
    if "admission" not in d and validate(records, context, expected_sha, disabled):
        return False
    if e not in records:
        return False
    b = next((r for r in records if r.get("record_type") == "teacher_blob" and r["cache_key"] == e["cache_key"]), None)
    if b is None:
        return False
    try:
        if "intersection" in d:
            return bool(b["teacher_license"]["scope"]["train"])
        return bool(
            e["provenance"]["upstream"]["eligibility"]["train"]
            and b["teacher_license"]["scope"]["train"]
            and e["license"]["scope"]["train"]
            and b["reproducibility"] != "unverified"
            and e["source"]["partition"] == "train"
        )
    except (KeyError, TypeError):
        return False


def main(argv) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", nargs="?", choices=["validate", "eligible"], default="validate")
    p.add_argument("--records", required=True)
    p.add_argument("--context")
    p.add_argument("--expected-context-sha256")
    p.add_argument("--disable", action="append", default=[])
    a = p.parse_args(argv)
    records = json.loads(Path(a.records).read_text())
    context = json.loads(Path(a.context).read_text()) if a.context else None
    if a.mode == "eligible":
        e = next((r for r in records if r.get("record_type") == "teacher_entry"), {})
        ok = eligible(e, records, context, a.expected_context_sha256, a.disable)
        errors = [] if ok else ["not_train_eligible"]
    else:
        errors = validate(records, context, a.expected_context_sha256, a.disable)
    print(json.dumps({"errors": errors, "ok": not errors}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
