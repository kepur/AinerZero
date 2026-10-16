"""生成并核对 teacher_cache.v1 的正反例（ainerzero.V9.T1 r1）。

用法：<带 jsonschema 的 python> -I reports/V9-T1/r1/check_teacher_cache_v1.py <AinerZero 根> <result.json>
写 contracts/v9/examples/teacher_cache_v1/；核对：
- 单记录：正例过 schema；结构反例在预期字段上以预期关键字被拒；
- 库级（多条记录合在一起）：跨记录规则（块/条目身份、输入摘要一致、同块跨分区、derived_by、特征教师无噪声模型、批准）；
- 破坏自检：逐个改坏 schema 或库级规则，整套必须变红。任一不符即非零退出。只写示例目录与 result.json。
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

DELETE = object()


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha(o):
    return hashlib.sha256(canon(o)).hexdigest()


def set_path(o, p, v):
    for k in p[:-1]:
        o = o[k]
    if v is DELETE:
        del o[p[-1]]
    else:
        o[p[-1]] = v


LIC = {"license_id": "MIT", "source_url": "https://huggingface.co/dgrauet/vjepa-2.1-vitl-mlx", "verified_at": "2026-10-16",
       "scope": {"reference": True, "train": True, "eval": True, "commercial_output": True, "redistribute": False},
       "approval_ref": "R20261016-T4"}
TS = [round(i / 24, 6) for i in range(16)]


def km(teacher_id="vjepa2.1-vitl", kind="feature", inp="clip-0001", rlt=False):
    return {
        "teacher": {"teacher_id": teacher_id, "variant": "example", "teacher_kind": kind,
                    "weights": [{"file": "w.safetensors", "sha256": h("w:" + teacher_id)}], "code_revision": "0000000example",
                    "runtime": {"framework": "mlx", "framework_version": "0.32.4", "compute_units": "gpu", "dtype": "float32"}},
        "preprocess": {"spec_sha256": h("pre:" + teacher_id), "resolution": [384, 384], "frames": 16, "normalization": "imagenet",
                       "token_policy": {"kind": "rlt", "tau": 0.02, "norm": "linf", "patch": 16} if rlt else {"kind": "none"}},
        "input": {"sha256": h("input:" + inp), "media_type": "video/x-raw-rgb24", "timestamps_s": TS},
    }


def blob(k):
    feat = k["teacher"]["teacher_kind"] == "feature"
    rlt = k["preprocess"]["token_policy"]["kind"] == "rlt"
    return {
        "schema_version": "az.v9.teacher_cache.v1", "record_type": "teacher_blob", "cache_key": sha(k), "key_material": k,
        "output": {"kind": "video_latent" if feat else "camera_pose",
                   "files": [{"name": "output.safetensors", "bytes": 1024, "sha256": h("out:" + sha(k)), "media_type": "application/octet-stream"}],
                   "shape": [8, 576, 1024] if feat else [16, 3, 4], "dtype": "float16" if feat else "float32",
                   "scale": "not_applicable" if feat else "up_to_scale",
                   "coordinate_frame": {"camera_convention": "none" if feat else "opencv",
                                        "to_world": None if feat else {"matrix": [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]], "det_sign": 1}},
                   "time_stride_s": 0.083333 if feat else None,
                   "token_stats": {"kept": 2304, "total": 4608, "run_length_hist": {"1": 1800, "2": 504}} if rlt else None},
        "confidence": {"kind": "none", "file": None},
        "reproducibility": "numeric", "tolerance": {"metric": "cosine_min", "value": 0.9999},
        "teacher_license": copy.deepcopy(LIC),
        "generation": {"mode": "teacher", "argv": ["python3", "-I", "extract.py"], "started_at": "2026-10-16T09:00:00+03:00",
                       "wall_s": 1.0, "peak_memory_bytes": {"mlx": 1, "rss": 2}, "host": "m2max",
                       "lease": {"lock": "artifacts/locks/m0-worker.lock", "held_from_start_to_end": True}},
    }


def entry(b, world, part, use="input", noise=None):
    k = b["key_material"]
    eid = sha({"cache_key": b["cache_key"], "world_key": world, "partition": part, "input_sha256": k["input"]["sha256"], "use": use})
    return {
        "schema_version": "az.v9.teacher_cache.v1", "record_type": "teacher_entry", "entry_id": eid, "cache_key": b["cache_key"],
        "source": {"world_key": world, "partition": part, "input_ref": {"uri": f"obs/{world}.raw", "sha256": k["input"]["sha256"]},
                   "timestamps_s": list(k["input"]["timestamps_s"])},
        "provenance": {"source_type": "teacher_feature",
                       "origin_native": {"system": "ainerzero", "origin": "observed", "derived_by": k["teacher"]["teacher_id"], "use": use}},
        "license": copy.deepcopy(LIC), "noise_model_ref": noise, "store": "sealed_eval" if part == "final" else "shared",
    }


B1 = blob(km())
B2 = blob(km(teacher_id="da3-small", kind="geometry", inp="kf-0001"))
B3 = blob(km(inp="clip-0002", rlt=True))
B_FINAL = blob(km(inp="exam-0001"))


def valid_store():
    """同一内容块被同一分区的两个世界引用（同内容、不同来源），合法。"""
    return [B1, B2, B3, B_FINAL,
            entry(B1, "awz:w1", "train"), entry(B1, "awz:w2", "train"),
            entry(B2, "awz:w3", "train", noise="nc-da3-small-pose@1.0"),
            entry(B3, "awz:w4", "development"),
            entry(B_FINAL, "awz:exam-1", "final")]


INVALID = [  # 单记录结构反例：(名字, 记录, 修改, [关键字, 路径片段])
    ("entry_final_in_shared_store", lambda: entry(B_FINAL, "awz:exam-1", "final"), [(["store"], "shared")], ["const", "store"]),
    ("entry_train_in_sealed_store", lambda: entry(B1, "awz:w1", "train"), [(["store"], "sealed_eval")], ["const", "store"]),
    ("entry_partition_sim_truth", lambda: entry(B1, "awz:w1", "train"), [(["source", "partition"], "sim_truth")], ["enum", "partition"]),
    ("entry_source_teacher_claim", lambda: entry(B1, "awz:w1", "train"), [(["provenance", "source_type"], "teacher_claim")], ["const", "source_type"]),
    ("blob_with_world_key", lambda: copy.deepcopy(B1), [(["world_key"], "awz:w1")], ["additionalProperties", ""]),
    ("blob_lease_not_held", lambda: copy.deepcopy(B1), [(["generation", "lease", "held_from_start_to_end"], False)], ["const", "held_from_start_to_end"]),
    ("blob_other_lock", lambda: copy.deepcopy(B1), [(["generation", "lease", "lock"], "artifacts/locks/teacher-mode.lock")], ["const", "lock"]),
    ("blob_feature_metric_scale", lambda: copy.deepcopy(B1), [(["output", "scale"], "metric")], ["const", "scale"]),
    ("blob_rlt_without_stats", lambda: copy.deepcopy(B3), [(["output", "token_stats"], None)], ["type", "token_stats"]),
    ("blob_numeric_without_tolerance", lambda: copy.deepcopy(B1), [(["tolerance"], None)], ["type", "tolerance"]),
    ("entry_without_input_ref", lambda: entry(B1, "awz:w1", "train"), [(["source", "input_ref"], DELETE)], ["required", "source"]),
]

STORE_INVALID = [  # 库级反例：(名字, 修改函数, 期望理由)
    ("cross_partition_blob", lambda s: s + [entry(B1, "awz:w9", "development")], "cross_partition_blob"),
    ("cross_partition_blob_final", lambda s: s + [entry(B1, "awz:exam-9", "final")], "cross_partition_blob"),
    ("entry_input_mismatch", lambda s: s[:4] + [dict(entry(B1, "awz:w1", "train"), source=dict(entry(B1, "awz:w1", "train")["source"],
                                                    input_ref={"uri": "x", "sha256": h("other")}))] + s[5:], "input_mismatch"),
    ("entry_id_wrong", lambda s: s[:4] + [dict(entry(B1, "awz:w1", "train"), entry_id=h("wrong"))] + s[5:], "entry_id_mismatch"),
    ("blob_key_wrong", lambda s: [dict(B1, cache_key=h("wrong"))] + s[1:], "cache_key_mismatch"),
    ("entry_orphan", lambda s: s + [dict(entry(B1, "awz:w5", "train"), cache_key=h("nothing"))], "orphan_entry"),
    ("feature_entry_with_noise", lambda s: s + [entry(B1, "awz:w6", "train", noise="nc-x@1.0")], "feature_with_noise_model"),
    ("derived_by_wrong", lambda s: s + [json.loads(json.dumps(entry(B1, "awz:w7", "train")).replace('"derived_by": "vjepa2.1-vitl"', '"derived_by": "other"'))],
     "derived_by_mismatch"),
    ("unapproved_teacher", lambda s: [json.loads(json.dumps(B1).replace('"approval_ref": "R20261016-T4"', '"approval_ref": null'))] + s[1:], "unapproved"),
]


def store_problems(records, disabled=()):
    out = []
    blobs = {r["cache_key"]: r for r in records if r["record_type"] == "teacher_blob"}
    parts = {}
    for b in blobs.values():
        if "key" not in disabled and sha(b["key_material"]) != b["cache_key"]:
            out.append("cache_key_mismatch")
        if "approval" not in disabled and b["teacher_license"]["approval_ref"] is None:
            out.append("unapproved")
    for e in (r for r in records if r["record_type"] == "teacher_entry"):
        b = blobs.get(e["cache_key"])
        if b is None:
            out.append("orphan_entry")
            continue
        k = b["key_material"]
        use = e["provenance"]["origin_native"]["use"]
        want = sha({"cache_key": e["cache_key"], "world_key": e["source"]["world_key"], "partition": e["source"]["partition"],
                    "input_sha256": e["source"]["input_ref"]["sha256"], "use": use})
        if "eid" not in disabled and want != e["entry_id"]:
            out.append("entry_id_mismatch")
        if "input" not in disabled and e["source"]["input_ref"]["sha256"] != k["input"]["sha256"]:
            out.append("input_mismatch")
        if "derived" not in disabled and e["provenance"]["origin_native"]["derived_by"] != k["teacher"]["teacher_id"]:
            out.append("derived_by_mismatch")
        if "noise" not in disabled and k["teacher"]["teacher_kind"] == "feature" and e["noise_model_ref"] is not None:
            out.append("feature_with_noise_model")
        if e["source"]["partition"] in ("train", "development", "final"):
            parts.setdefault(e["cache_key"], set()).add(e["source"]["partition"])
    if "cross" not in disabled and any(len(p) > 1 for p in parts.values()):
        out.append("cross_partition_blob")
    return out


def sub(schema, name):
    s = copy.deepcopy(schema); s.pop("oneOf"); s["$ref"] = "#/$defs/" + name
    return Draft202012Validator(s)


def hit(v, d, kw, part):
    def walk(errs):
        for e in errs:
            if e.validator == kw and part in e.json_path:
                return True
            if e.context and walk(e.context):
                return True
        return False
    return walk(v.iter_errors(d))


def write(p, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make(root):
    base = Path(root) / "contracts/v9/examples/teacher_cache_v1"
    write(base / "valid/store.json", valid_store())
    for name, mk, edits, _ in INVALID:
        d = mk()
        for p, v in edits:
            set_path(d, p, v)
        write(base / f"invalid/{name}.json", d)
    for name, fn, _ in STORE_INVALID:
        write(base / f"invalid/store_{name}.json", fn(valid_store()))
    return base


def run(base, schema, disabled=()):
    Draft202012Validator.check_schema(schema)
    top = Draft202012Validator(schema)
    subs = {n: sub(schema, n) for n in ("teacher_blob", "teacher_entry", "noise_calibration")}
    rows, fails = [], []

    def rec(kind, name, ok, **kw):
        rows.append({"set": kind, "name": name, "ok": ok, **kw})
        if not ok:
            fails.append(f"{kind}/{name}")

    st = json.loads((base / "valid/store.json").read_text(encoding="utf-8"))
    errs = [e.message for r in st for e in top.iter_errors(r)]
    pr = store_problems(st, disabled)
    rec("valid_store", "store", not errs and not pr, errors=errs[:3], problems=pr)
    for name, _, _, (kw, part) in INVALID:
        d = json.loads((base / f"invalid/{name}.json").read_text(encoding="utf-8"))
        rec("invalid", name, (not top.is_valid(d)) and hit(subs[d["record_type"]], d, kw, part), expected=[kw, part])
    for name, _, reason in STORE_INVALID:
        s = json.loads((base / f"invalid/store_{name}.json").read_text(encoding="utf-8"))
        ok_schema = all(top.is_valid(r) for r in s)
        pr = store_problems(s, disabled)
        rec("store_invalid", name, ok_schema and reason in pr, schema_ok=ok_schema, problems=pr)
    return fails, rows


def sabotages(schema):
    out = []
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["allOf"] = [{}]
    out.append(("final_store_unchecked", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["partition"]["enum"].append("sim_truth")
    out.append(("sim_truth_partition_allowed", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_blob"]["properties"]["generation"]["properties"]["lease"]["properties"]["held_from_start_to_end"] = {"type": "boolean"}
    out.append(("lease_hold_optional", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_blob"]["additionalProperties"] = True
    out.append(("blob_may_carry_world", s, ()))
    for name, flag in [("cross_partition_off", "cross"), ("input_check_off", "input"), ("entry_id_off", "eid"), ("key_check_off", "key"),
                       ("noise_check_off", "noise"), ("derived_off", "derived"), ("approval_off", "approval")]:
        out.append((name, copy.deepcopy(schema), (flag,)))
    return out


def main(root, result):
    schema = json.loads((Path(root) / "contracts/v9/teacher_cache.v1.schema.json").read_text(encoding="utf-8"))
    base = make(root)
    fails, rows = run(base, schema)
    sab, miss = [], []
    for name, s, dis in sabotages(schema):
        try:
            f, _ = run(base, s, dis)
            red, det = bool(f), f[:3]
        except Exception as exc:
            red, det = True, [f"{type(exc).__name__}: {exc}"[:120]]
        sab.append({"sabotage": name, "turned_red": red, "caught_by": det})
        if not red:
            miss.append(name)
    counts = {}
    for r in rows:
        counts[r["set"]] = counts.get(r["set"], 0) + 1
    Path(result).write_text(json.dumps({"counts": counts, "failures": fails, "sabotage_not_caught": miss, "rows": rows, "sabotage": sab},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "failures": fails, "sabotage_total": len(sab), "sabotage_not_caught": miss}, ensure_ascii=False))
    return 1 if fails or miss else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
