"""生成并核对 teacher_cache.v2 的正反例（ainerzero.V9.T1 r2，回应 ainerzero.V9.T14）。

用法：<带 jsonschema 的 python> -I reports/V9-T1/r2/check_teacher_cache_v2.py <AinerZero 根> <result.json>
写 contracts/v9/examples/teacher_cache_v2/；核对：
- 单记录结构正反例；
- 库级规则：块/条目身份、上游输入摘要一致、同块跨分区、derivation.teacher_id 与块一致、特征教师无噪声模型、批准、
  use=input 的输入片段不晚于 as_of_t_s；
- 训练资格 = 上游资格 ∧ 教师许可 ∧ 条目许可 ∧ 可复现等级非 unverified ∧ 分区为 train，同块多来源逐条独立判定；
- 破坏自检：改坏 schema 或库级规则，整套必须变红。任一不符即非零退出。只写示例目录与 result.json。
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


def km(teacher_id="vjepa2.1-vitl", kind="feature", inp="clip-0001"):
    return {
        "teacher": {"teacher_id": teacher_id, "variant": "example", "teacher_kind": kind,
                    "weights": [{"file": "w.safetensors", "sha256": h("w:" + teacher_id)}], "code_revision": "0000000example",
                    "runtime": {"framework": "mlx", "framework_version": "0.32.4", "compute_units": "gpu", "dtype": "float32"}},
        "preprocess": {"spec_sha256": h("pre:" + teacher_id), "resolution": [384, 384], "frames": 16, "normalization": "imagenet",
                       "token_policy": {"kind": "none"}},
        "input": {"sha256": h("input:" + inp), "media_type": "video/x-raw-rgb24", "timestamps_s": TS},
    }


def blob(k, repro="numeric"):
    feat = k["teacher"]["teacher_kind"] == "feature"
    return {
        "schema_version": "az.v9.teacher_cache.v2", "record_type": "teacher_blob", "cache_key": sha(k), "key_material": k,
        "output": {"kind": "video_latent" if feat else "camera_pose",
                   "files": [{"name": "output.safetensors", "bytes": 1024, "sha256": h("out:" + sha(k)), "media_type": "application/octet-stream"}],
                   "shape": [8, 576, 1024] if feat else [16, 3, 4], "dtype": "float16" if feat else "float32",
                   "scale": "not_applicable" if feat else "up_to_scale",
                   "coordinate_frame": {"camera_convention": "none" if feat else "opencv", "to_world": None},
                   "time_stride_s": 0.083333 if feat else None, "token_stats": None},
        "confidence": {"kind": "none", "file": None},
        "reproducibility": repro, "tolerance": {"metric": "cosine_min", "value": 0.9999} if repro == "numeric" else None,
        "teacher_license": copy.deepcopy(LIC),
        "generation": {"mode": "teacher", "argv": ["python3", "-I", "extract.py"], "started_at": "2026-10-16T09:00:00+03:00",
                       "wall_s": 1.0, "peak_memory_bytes": {"mlx": 1, "rss": 2}, "host": "m2max",
                       "lease": {"lock": "artifacts/locks/m0-worker.lock", "held_from_start_to_end": True}},
    }


def entry(b, world, part, system="awz", origin="external_derived", use="input", as_of=None, noise=None, train=None, basis=None):
    k = b["key_material"]
    if train is None:
        train = (origin == "observed" and part == "train")
    if basis is None:
        basis = ("adr_0005_default_deny" if origin == "external_derived" else
                 ("admit_training" if part == "train" else "not_train_partition"))
    eid = sha({"cache_key": b["cache_key"], "world_key": world, "partition": part, "input_sha256": k["input"]["sha256"], "use": use})
    return {
        "schema_version": "az.v9.teacher_cache.v2", "record_type": "teacher_entry", "entry_id": eid, "cache_key": b["cache_key"],
        "source": {"world_key": world, "partition": part, "timestamps_s": list(k["input"]["timestamps_s"])},
        "as_of_t_s": max(k["input"]["timestamps_s"]) if as_of is None else as_of,
        "provenance": {"source_type": "teacher_feature",
                       "upstream": {"system": system, "origin": origin,
                                    "actor": {"kind": "student", "actor_id": "az-student", "policy_revision": "r1"},
                                    "input_ref": {"uri": f"obs/{world}.raw", "sha256": k["input"]["sha256"]},
                                    "eligibility": {"train": train, "basis": basis, "revision_ref": None}},
                       "derivation": {"teacher_id": k["teacher"]["teacher_id"], "use": use,
                                      "weights_sha256": [w["sha256"] for w in k["teacher"]["weights"]],
                                      "preprocess_spec_sha256": k["preprocess"]["spec_sha256"]}},
        "license": copy.deepcopy(LIC), "noise_model_ref": noise, "store": "sealed_eval" if part == "final" else "shared",
    }


B1 = blob(km())                                   # 同一块：一个来自 AWZ（external_derived），一个来自 AinerZero 自身环境（observed）
B2 = blob(km(teacher_id="da3-small", kind="geometry", inp="kf-0001"))
B3 = blob(km(inp="clip-0003"), repro="unverified")


def valid_store():
    return [B1, B2, B3,
            entry(B1, "awz:w1", "train", system="awz", origin="external_derived"),
            entry(B1, "gridlab:w2", "train", system="ainerzero", origin="observed"),
            entry(B2, "gridlab:w3", "train", system="ainerzero", origin="observed", noise="nc-da3-small-pose@1.0"),
            entry(B3, "gridlab:w4", "train", system="ainerzero", origin="observed")]


# 训练资格期望：逐条独立判定
EXPECT_TRAIN = {"awz:w1": False, "gridlab:w2": True, "gridlab:w3": True, "gridlab:w4": False}

INVALID = [
    ("external_derived_claims_train", lambda: entry(B1, "awz:w1", "train"),
     [(["provenance", "upstream", "eligibility", "train"], True), (["provenance", "upstream", "eligibility", "basis"], "admit_training")], ["const", "train"]),
    ("revision_basis_without_ref", lambda: entry(B1, "awz:w1", "train"),
     [(["provenance", "upstream", "eligibility", "basis"], "adr_0005_revision"), (["provenance", "upstream", "eligibility", "train"], True)],
     ["type", "revision_ref"]),
    ("default_deny_but_train", lambda: entry(B1, "gridlab:w2", "train", system="ainerzero", origin="observed"),
     [(["provenance", "upstream", "eligibility", "basis"], "adr_0005_default_deny")], ["const", "train"]),
    ("old_v1_origin_native", lambda: entry(B1, "awz:w1", "train"),
     [(["provenance", "origin_native"], {"system": "ainerzero", "origin": "observed", "derived_by": "x", "use": "input"})],
     ["additionalProperties", "provenance"]),
    ("upstream_missing_actor", lambda: entry(B1, "awz:w1", "train"), [(["provenance", "upstream", "actor"], DELETE)], ["required", "upstream"]),
    ("missing_as_of", lambda: entry(B1, "awz:w1", "train"), [(["as_of_t_s"], DELETE)], ["required", ""]),
    ("final_in_shared_store", lambda: entry(B1, "awz:exam", "final"), [(["store"], "shared")], ["const", "store"]),
    ("partition_sim_truth", lambda: entry(B1, "awz:w1", "train"), [(["source", "partition"], "sim_truth")], ["enum", "partition"]),
]

STORE_INVALID = [
    ("input_after_as_of", lambda s: s + [entry(B1, "gridlab:w9", "train", system="ainerzero", origin="observed", as_of=0.2)], "input_after_as_of"),
    ("cross_partition_blob", lambda s: s + [entry(B1, "gridlab:w8", "development", system="ainerzero", origin="observed")], "cross_partition_blob"),
    ("derivation_teacher_wrong", lambda s: s + [json.loads(json.dumps(entry(B1, "gridlab:w7", "train", system="ainerzero", origin="observed"))
                                                            .replace('"teacher_id": "vjepa2.1-vitl", "use"', '"teacher_id": "other", "use"'))],
     "derivation_mismatch"),
    ("upstream_input_mismatch", lambda s: s + [json.loads(json.dumps(entry(B1, "gridlab:w6", "train", system="ainerzero", origin="observed"))
                                                           .replace(h("input:clip-0001"), h("other-input"), 1))], "input_mismatch"),
    ("orphan_entry", lambda s: s + [dict(entry(B1, "gridlab:w5", "train", system="ainerzero", origin="observed"), cache_key=h("nothing"))],
     "orphan_entry"),
    ("feature_entry_with_noise", lambda s: s + [entry(B1, "gridlab:w10", "train", system="ainerzero", origin="observed", noise="nc-x@1.0")],
     "feature_with_noise_model"),
]


def store_problems(records, disabled=()):
    out = []
    blobs = {r["cache_key"]: r for r in records if r["record_type"] == "teacher_blob"}
    parts = {}
    for b in blobs.values():
        if "key" not in disabled and sha(b["key_material"]) != b["cache_key"]:
            out.append("cache_key_mismatch")
    for e in (r for r in records if r["record_type"] == "teacher_entry"):
        b = blobs.get(e["cache_key"])
        if b is None:
            out.append("orphan_entry")
            continue
        k = b["key_material"]
        up, dv = e["provenance"]["upstream"], e["provenance"]["derivation"]
        want = sha({"cache_key": e["cache_key"], "world_key": e["source"]["world_key"], "partition": e["source"]["partition"],
                    "input_sha256": up["input_ref"]["sha256"], "use": dv["use"]})
        if "eid" not in disabled and want != e["entry_id"]:
            out.append("entry_id_mismatch")
        if "input" not in disabled and up["input_ref"]["sha256"] != k["input"]["sha256"]:
            out.append("input_mismatch")
        if "derived" not in disabled and dv["teacher_id"] != k["teacher"]["teacher_id"]:
            out.append("derivation_mismatch")
        if "noise" not in disabled and k["teacher"]["teacher_kind"] == "feature" and e["noise_model_ref"] is not None:
            out.append("feature_with_noise_model")
        if "asof" not in disabled and dv["use"] == "input" and max(e["source"]["timestamps_s"]) > e["as_of_t_s"]:
            out.append("input_after_as_of")
        if e["source"]["partition"] in ("train", "development", "final"):
            parts.setdefault(e["cache_key"], set()).add(e["source"]["partition"])
    if "cross" not in disabled and any(len(p) > 1 for p in parts.values()):
        out.append("cross_partition_blob")
    return out


def train_eligible(e, blobs, disabled=()):
    b = blobs[e["cache_key"]]
    up = e["provenance"]["upstream"]["eligibility"]["train"]
    if "intersection" in disabled:
        return bool(b["teacher_license"]["scope"]["train"])  # 改坏：只看教师许可
    return bool(up and b["teacher_license"]["scope"]["train"] and e["license"]["scope"]["train"]
                and b["reproducibility"] != "unverified" and e["source"]["partition"] == "train")


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
    b = Path(root) / "contracts/v9/examples/teacher_cache_v2"
    write(b / "valid/store.json", valid_store())
    for n, mk, edits, _ in INVALID:
        d = mk()
        for p, v in edits:
            set_path(d, p, v)
        write(b / f"invalid/{n}.json", d)
    for n, fn, _ in STORE_INVALID:
        write(b / f"invalid/store_{n}.json", fn(valid_store()))
    return b


def run(b, schema, disabled=()):
    Draft202012Validator.check_schema(schema)
    top = Draft202012Validator(schema)
    subs = {n: sub(schema, n) for n in ("teacher_blob", "teacher_entry", "noise_calibration")}
    rows, fails = [], []

    def rec(kind, name, ok, **kw):
        rows.append({"set": kind, "name": name, "ok": ok, **kw})
        if not ok:
            fails.append(f"{kind}/{name}")

    st = json.loads((b / "valid/store.json").read_text(encoding="utf-8"))
    errs = [e.message for r in st for e in top.iter_errors(r)]
    pr = store_problems(st, disabled)
    rec("valid_store", "store", not errs and not pr, errors=errs[:3], problems=pr)
    blobs = {r["cache_key"]: r for r in st if r["record_type"] == "teacher_blob"}
    for e in (r for r in st if r["record_type"] == "teacher_entry"):
        w = e["source"]["world_key"]
        got = train_eligible(e, blobs, disabled)
        rec("eligibility", w, got == EXPECT_TRAIN[w], got=got, want=EXPECT_TRAIN[w])
    for n, _, _, (kw, part) in INVALID:
        d = json.loads((b / f"invalid/{n}.json").read_text(encoding="utf-8"))
        rec("invalid", n, (not top.is_valid(d)) and hit(subs[d["record_type"]], d, kw, part), expected=[kw, part])
    for n, _, reason in STORE_INVALID:
        s = json.loads((b / f"invalid/store_{n}.json").read_text(encoding="utf-8"))
        ok_schema = all(top.is_valid(r) for r in s)
        pr = store_problems(s, disabled)
        rec("store_invalid", n, ok_schema and reason in pr, schema_ok=ok_schema, problems=pr)
    return fails, rows


def sabotages(schema):
    out = []
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["properties"]["provenance"]["allOf"][0] = {}
    out.append(("external_derived_may_train", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["properties"]["provenance"]["allOf"][1] = {}
    out.append(("revision_ref_optional", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["properties"]["provenance"]["allOf"][2] = {}
    out.append(("default_deny_unchecked", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["properties"]["provenance"]["additionalProperties"] = True
    out.append(("old_origin_native_allowed", s, ()))
    s = copy.deepcopy(schema); s["$defs"]["teacher_entry"]["required"].remove("as_of_t_s")
    out.append(("as_of_optional", s, ()))
    for n, f in [("asof_check_off", "asof"), ("cross_off", "cross"), ("derived_off", "derived"), ("input_off", "input"),
                 ("noise_off", "noise"), ("intersection_off", "intersection")]:
        out.append((n, copy.deepcopy(schema), (f,)))
    return out


def main(root, result):
    schema = json.loads((Path(root) / "contracts/v9/teacher_cache.v2.schema.json").read_text(encoding="utf-8"))
    b = make(root)
    fails, rows = run(b, schema)
    sab, miss = [], []
    for n, s, dis in sabotages(schema):
        try:
            f, _ = run(b, s, dis)
            red, det = bool(f), f[:3]
        except Exception as exc:
            red, det = True, [f"{type(exc).__name__}: {exc}"[:120]]
        sab.append({"sabotage": n, "turned_red": red, "caught_by": det})
        if not red:
            miss.append(n)
    counts = {}
    for x in rows:
        counts[x["set"]] = counts.get(x["set"], 0) + 1
    Path(result).write_text(json.dumps({"counts": counts, "failures": fails, "sabotage_not_caught": miss, "rows": rows, "sabotage": sab},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "failures": fails, "sabotage_total": len(sab), "sabotage_not_caught": miss}, ensure_ascii=False))
    return 1 if fails or miss else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
