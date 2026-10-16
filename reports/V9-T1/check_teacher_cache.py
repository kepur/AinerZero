"""核对 teacher_cache.v0 schema 与正反例（ainerzero.V9.T1）。

用法：<带 jsonschema 的 python> -I reports/V9-T1/check_teacher_cache.py <repo_root> <result.json>
- 正例：顶层 schema 通过，跨字段语义检查通过；
- 反例：顶层 schema 拒绝，且在对应记录类型上出现预期关键字和路径的错误（防止“因为别的原因被拒”）；
- 语义反例：schema 通过，但跨字段检查按预期理由拒绝；
- 破坏自检：逐个改坏 schema 或语义检查，整套核对必须变红。
任一不符就以非零退出。只读 schema 与示例，只写 result.json。
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def semantic_problems(rec, disabled=()):
    """跨字段规则（TEACHERS_AND_CACHE.md §2.1、§2.5、§5）。T2 的写入代码必须实现同样的规则。"""
    out = []
    if rec.get("record_type") != "cache_entry":
        return out
    km = rec["key_material"]
    if "cache_key" not in disabled and hashlib.sha256(canon(km)).hexdigest() != rec["cache_key"]:
        out.append("cache_key_mismatch")
    if "derived_by" not in disabled and rec["provenance"]["origin_native"]["derived_by"] != km["teacher"]["teacher_id"]:
        out.append("derived_by_mismatch")
    if "approval" not in disabled and rec["license"]["approval_ref"] is None:
        out.append("unapproved")
    ts = km["input"]["timestamps_s"]
    if "monotonic" not in disabled and any(b < a for a, b in zip(ts, ts[1:])):
        out.append("timestamps_not_monotonic")
    return out


def sub_validator(schema, record_type):
    s = copy.deepcopy(schema)
    s.pop("oneOf")
    s["$ref"] = "#/$defs/" + record_type
    return Draft202012Validator(s)


def run_suite(schema, root, disabled=()):
    Draft202012Validator.check_schema(schema)
    top = Draft202012Validator(schema)
    subs = {rt: sub_validator(schema, rt) for rt in ("cache_entry", "noise_calibration")}
    base = Path(root) / "contracts/v9/examples/teacher_cache"
    exp = json.loads((base / "EXPECTATIONS.json").read_text(encoding="utf-8"))
    fails, rows = [], []
    for name in exp["valid"]:
        rec = json.loads((base / "valid" / f"{name}.json").read_text(encoding="utf-8"))
        errs = [e.message for e in top.iter_errors(rec)]
        sem = semantic_problems(rec, disabled)
        ok = not errs and not sem
        rows.append({"set": "valid", "name": name, "ok": ok, "schema_errors": errs[:3], "semantic": sem})
        if not ok:
            fails.append(f"valid/{name}")
    for item in exp["invalid"]:
        rec = json.loads((base / "invalid" / f"{item['name']}.json").read_text(encoding="utf-8"))
        rejected = not top.is_valid(rec)
        sub = subs[rec["record_type"]]
        hits = [e for e in sub.iter_errors(rec)
                if e.validator == item["keyword"] and item["path_part"] in e.json_path]
        if not hits:  # 错误可能嵌在 oneOf/allOf 的上下文里
            for e in sub.iter_errors(rec):
                for c in e.context or []:
                    if c.validator == item["keyword"] and item["path_part"] in c.json_path:
                        hits.append(c)
        ok = rejected and bool(hits)
        rows.append({"set": "invalid", "name": item["name"], "ok": ok, "rejected": rejected,
                     "expected": [item["keyword"], item["path_part"]],
                     "matched": [f"{e.validator}@{e.json_path}" for e in hits[:2]]})
        if not ok:
            fails.append(f"invalid/{item['name']}")
    for item in exp["semantic"]:
        rec = json.loads((base / "invalid" / f"{item['name']}.json").read_text(encoding="utf-8"))
        schema_ok = top.is_valid(rec)
        sem = semantic_problems(rec, disabled)
        ok = schema_ok and item["reason"] in sem
        rows.append({"set": "semantic", "name": item["name"], "ok": ok, "schema_ok": schema_ok, "semantic": sem})
        if not ok:
            fails.append(f"semantic/{item['name']}")
    return fails, rows


def sabotages(schema):
    """每个破坏都对应一条规范规则；核对必须因此变红。"""
    out = []
    s = copy.deepcopy(schema)
    s["$defs"]["partition"]["enum"].append("final")
    out.append(("partition_allows_final", s, ()))
    s = copy.deepcopy(schema)
    s["$defs"]["cache_entry"]["properties"]["provenance"]["properties"]["source_type"] = {"type": "string"}
    out.append(("source_type_any_string", s, ()))
    s = copy.deepcopy(schema)
    s["$defs"]["noise_calibration"]["allOf"][1]["then"] = {}
    out.append(("no_coverage_band", s, ()))
    s = copy.deepcopy(schema)
    s["$defs"]["cache_entry"]["properties"]["output"].pop("allOf")
    out.append(("feature_scale_unchecked", s, ()))
    s = copy.deepcopy(schema)
    s["$defs"]["cache_entry"]["allOf"].pop(2)
    out.append(("rlt_stats_unchecked", s, ()))
    out.append(("semantic_cache_key_off", copy.deepcopy(schema), ("cache_key",)))
    out.append(("semantic_monotonic_off", copy.deepcopy(schema), ("monotonic",)))
    out.append(("semantic_approval_off", copy.deepcopy(schema), ("approval",)))
    return out


def main(root, result_path):
    schema_path = Path(root) / "contracts/v9/teacher_cache.v0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fails, rows = run_suite(schema, root)
    sab_rows, sab_fail = [], []
    for name, s, disabled in sabotages(schema):
        try:
            f, _ = run_suite(s, root, disabled)
            red = bool(f)
            detail = f[:3]
        except Exception as exc:  # schema 本身被改坏到无法编译，也算变红
            red, detail = True, [f"{type(exc).__name__}: {exc}"[:120]]
        sab_rows.append({"sabotage": name, "turned_red": red, "caught_by": detail})
        if not red:
            sab_fail.append(name)
    result = {
        "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "counts": {s: sum(1 for r in rows if r["set"] == s) for s in ("valid", "invalid", "semantic")},
        "failures": fails,
        "sabotage_not_caught": sab_fail,
        "rows": rows,
        "sabotage": sab_rows,
    }
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "failures": fails, "sabotage_not_caught": sab_fail,
                      "sabotage_total": len(sab_rows)}, ensure_ascii=False))
    return 1 if (fails or sab_fail) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
