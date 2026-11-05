#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R10 差分复核：归档 r1 校验器 vs 现行 r2 校验器，同一自建语料、同一调用口径。

用途：证明 r2 的确切字符串断言的增益（r1 直穿的子串/非字符串类），以及“关闭 R9-LIC 后
      r2 退化为 r1 行为（漏检）”的独立性事实。语料由本复核自建，判据为本进程实测输出，
      不引用统筹探针文件的结论作为判据。
只读：r1 取自 reports/V9-R5/r2-license-r1/archive/（只读归档），r2 取现行源码；均不修改。
"""
import copy, hashlib, importlib.util, io, json, os, sys, tempfile, contextlib
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
R1 = ROOT / "reports/V9-R5/r2-license-r1/archive/validate_registry_r5_r1.py"
R2 = ROOT / "reports/V9-R5/validate_registry_r5.py"
SRC_JSON = ROOT / "docs/research/adapter_registry.json"
SRC_MD = ROOT / "docs/research/ADAPTER_REGISTRY.md"
BASE = json.loads(SRC_JSON.read_text(encoding="utf-8"))
TARGETS = ["dino-wm", "pldm", "pushforward", "slotssms"]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def probe(mod, value, eid):
    d = copy.deepcopy(BASE)
    for e in d["entries"]:
        if e["id"] == eid:
            e["license"] = {"license": value, "source": "r10-differential-probe"}
    env = mod.R9_LIC_DISABLE_ENV
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "adapter_registry.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        try:
            with contextlib.redirect_stdout(buf):
                mod.validate_registry(p, SRC_MD)
            return "ACCEPTED"
        except AssertionError as e:
            return "REJECTED" if "R9-LIC[" in str(e) else "REJECTED_OTHER"
        except Exception as e:
            return f"ERROR:{type(e).__name__}"


CORPUS = [
    ("Apache-2.0", "MIT→Apache 整值"),
    ("Apache-2.0 WITH MIT exception", "含 MIT 子串的复合许可"),
    ("MIT OR Apache-2.0", "双许可表达式"),
    ("NOT-MIT", "前缀伪许可"),
    (["MIT"], "非字符串列表"),
    (None, "空值"),
    ("", "空串"),
    ("mit", "小写"),
    (" MIT", "前导空格"),
    ("MIT\n", "尾随换行"),
    ("MIT, source: github", "带后缀"),
    (1, "整数"),
    (True, "布尔"),
]


def main():
    m1, m2 = load("r1_val", R1), load("r2_val", R2)
    out = {"tool": "R10 差分复核",
           "r1_sha256": hashlib.sha256(R1.read_bytes()).hexdigest(),
           "r2_sha256": hashlib.sha256(R2.read_bytes()).hexdigest(),
           "r1_assert_semantics": 'isinstance 无；"MIT" in value（子串）',
           "r2_assert_semantics": 'isinstance(value, str) and value == "MIT"（确切）',
           "matrix": [], "summary": {}}
    for eid in TARGETS:
        for val, label in CORPUS:
            r1_on = probe(m1, val, eid)
            r2_on = probe(m2, val, eid)
            os.environ[m2.R9_LIC_DISABLE_ENV] = "1"
            try:
                r2_off = probe(m2, val, eid)
            finally:
                os.environ.pop(m2.R9_LIC_DISABLE_ENV, None)
            out["matrix"].append({"id": eid, "case": label, "value": repr(val),
                                  "r1_guard_on": r1_on, "r2_guard_on": r2_on,
                                  "r2_guard_off": r2_off,
                                  "r1_leaked": r1_on == "ACCEPTED",
                                  "r2_fixed": r1_on == "ACCEPTED" and r2_on.startswith("REJECTED"),
                                  "r2_off_matches_r1": (r2_off == "ACCEPTED") == (r1_on == "ACCEPTED")})
    mt = out["matrix"]
    out["summary"] = {
        "cases": len(mt),
        "r1_accepted_leaks": sum(1 for r in mt if r["r1_leaked"]),
        "r2_rejects_where_r1_leaked": sum(1 for r in mt if r["r2_fixed"]),
        "r2_still_accepts_true_leaks": sum(1 for r in mt if r["r2_guard_on"] == "ACCEPTED"),
        "r2_guard_off_behaviour_matches_r1": sum(1 for r in mt if r["r2_off_matches_r1"]),
        "all_fixed": all(r["r2_fixed"] for r in mt if r["r1_leaked"]),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
