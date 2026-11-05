#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R10 非作者独立复核探针 v2（判据全部本进程实测；不读根统筹输出作判据）。

受理范围（严格按任务卡四条 MIT 任务）：
  A. 正向：现行 registry 四条 = 确切字符串 'MIT'，整表校验通过。
  B. 四项各自 MIT→Apache 反例（M19–M22 同类）与子串/非字符串反例（M23–M26 同类）必须
     由 _assert_r9_mit_licenses 专属捕获（traceback 末帧判定，非字符串匹配）。
  C. 独立性：关闭 AINER_V9_R9_DISABLE_R9LIC=1 后，同一批反例必须漏检；且不得把
     “本来就由他处规则（如全局 license 非空）拦下”的输入冒充为 R9-LIC 专属捕获。
  D. 关闭守卫的正向输出不得出现「R9-LIC …通过」，须打印 LEAK-MODE 漏检声明。

不扩测其余 47 项许可，不抓网，不写源码/docs。
"""
import copy, hashlib, io, json, os, sys, tempfile, contextlib
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "reports" / "V9-R5"))
import validate_registry_r5 as V  # noqa: E402
import traceback  # noqa: E402

SRC_JSON = ROOT / "docs/research/adapter_registry.json"
SRC_MD = ROOT / "docs/research/ADAPTER_REGISTRY.md"
BASE = json.loads(SRC_JSON.read_text(encoding="utf-8"))
TARGETS = ["dino-wm", "pldm", "pushforward", "slotssms"]
R9_ASSERT = "_assert_r9_mit_licenses"


def set_lic(d, eid, val):
    for e in d["entries"]:
        if e["id"] == eid:
            e["license"] = {"license": val, "source": "r10-independent-probe"}
            return


def del_lic_field(d, eid):
    for e in d["entries"]:
        if e["id"] == eid:
            e.pop("license")
            return


def run(json_obj, guard_disabled):
    old = os.environ.get(V.R9_LIC_DISABLE_ENV)
    if guard_disabled:
        os.environ[V.R9_LIC_DISABLE_ENV] = "1"
    else:
        os.environ.pop(V.R9_LIC_DISABLE_ENV, None)
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "adapter_registry.json"
            p.write_text(json.dumps(json_obj, ensure_ascii=False), encoding="utf-8")
            try:
                with contextlib.redirect_stdout(buf):
                    V.validate_registry(p, SRC_MD)
                return {"raised": False, "exc": "", "final_fn": None, "msg": "", "stdout": buf.getvalue()}
            except AssertionError as e:
                tb, frames = sys.exc_info()[2], []
                while tb is not None:
                    frames.append(tb.tb_frame.f_code.co_name)
                    tb = tb.tb_next
                fin = [f for f in frames if f not in ("run", "<module>", "main")]
                return {"raised": True, "exc": "AssertionError", "final_fn": fin[-1] if fin else None,
                        "frames": fin, "msg": str(e), "stdout": buf.getvalue()}
            except Exception as e:
                return {"raised": True, "exc": type(e).__name__, "final_fn": None, "msg": str(e),
                        "stdout": buf.getvalue()}
    finally:
        if old is None:
            os.environ.pop(V.R9_LIC_DISABLE_ENV, None)
        else:
            os.environ[V.R9_LIC_DISABLE_ENV] = old


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    out = {"probe": "R10-independent-v2", "scope": "四条 MIT 代码许可定点守卫",
           "shas": {"validator": sha(ROOT / "reports/V9-R5/validate_registry_r5.py"),
                    "registry_json": sha(SRC_JSON), "registry_md": sha(SRC_MD)}}

    # ---------- A 正向 ----------
    pos = run(BASE, False)
    out["A_positive"] = {"raised": pos["raised"], "final_fn": pos["final_fn"],
                         "stdout": pos["stdout"].strip(),
                         "claims_exact_string_MIT": "确切字符串 'MIT'" in pos["stdout"],
                         "claims_pass": "R9-LIC 四条 MIT" in pos["stdout"]}

    # 四条现行登记值
    em = {e["id"]: e for e in BASE["entries"]}
    out["A_registry_values"] = {e: {"value": em[e]["license"]["license"],
                                    "type": type(em[e]["license"]["license"]).__name__,
                                    "== 'MIT'": em[e]["license"]["license"] == "MIT"} for e in TARGETS}

    # ---------- B 反例 ----------
    corpus = [
        # (名称, 值, 组别)  组别 in_scope=任务卡 M19–M26 同类；extra=本次独立加测的边缘型
        ("MIT_to_Apache-2.0", "Apache-2.0", "in_scope"),
        ("Apache-2.0 WITH MIT exception", "Apache-2.0 WITH MIT exception", "in_scope"),
        ("MIT OR Apache-2.0", "MIT OR Apache-2.0", "in_scope"),
        ("NOT-MIT", "NOT-MIT", "in_scope"),
        ('["MIT"] 列表', ["MIT"], "in_scope"),
        ("None", None, "extra"),
        ("空字符串", "", "extra"),
        ("mit 小写", "mit", "extra"),
        ("' MIT' 前导空格", " MIT", "extra"),
        ("'MIT ' 尾随空格", "MIT ", "extra"),
        ("'MIT\\n' 尾随换行", "MIT\n", "extra"),
        ("'MIT, source: github'", "MIT, source: github", "extra"),
        ("布尔 True", True, "extra"),
        ("整数 1", 1, "extra"),
        ("字典 {'license':'MIT'}", {"license": "MIT"}, "extra"),
    ]
    recs = []
    for eid in TARGETS:
        for name, val, grp in corpus:
            d = copy.deepcopy(BASE)
            set_lic(d, eid, val)
            r_on = run(d, False)
            r_off = run(d, True)
            r9_exclusive = r_on["final_fn"] == R9_ASSERT
            other_rule = r_on["raised"] and not r9_exclusive
            recs.append({
                "id": eid, "case": name, "group": grp, "value_repr": repr(val),
                "guard_on_raised": r_on["raised"], "guard_on_final_fn": r_on["final_fn"],
                "r9_exclusive_capture": bool(r9_exclusive),
                "caught_by_other_rule": bool(other_rule),
                "guard_off_raised": r_off["raised"], "leaked_when_off": (not r_off["raised"]),
                "marker_in_msg": f"R9-LIC[{eid}]" in r_on["msg"],
            })
    out["B_counterexamples"] = recs

    # ---------- 结构化边缘（缺键/非字典）----------
    struct = []
    for eid in TARGETS:
        d1 = copy.deepcopy(BASE); del_lic_field(d1, eid)
        r1 = run(d1, False); r1o = run(d1, True)
        struct.append({"id": eid, "case": "license 键整体缺失", "guard_on_raised": r1["raised"],
                       "final_fn": r1["final_fn"], "r9_exclusive": r1["final_fn"] == R9_ASSERT,
                       "leaked_when_off": not r1o["raised"]})
        d2 = copy.deepcopy(BASE)
        for e in d2["entries"]:
            if e["id"] == eid:
                e["license"] = "MIT"
        r2 = run(d2, False); r2o = run(d2, True)
        struct.append({"id": eid, "case": "license 值非 dict（字符串 MIT）", "guard_on_raised": r2["raised"],
                       "final_fn": r2["final_fn"], "r9_exclusive": r2["final_fn"] == R9_ASSERT,
                       "leaked_when_off": not r2o["raised"]})
    out["B_struct_edges"] = struct

    # ---------- C 独立性 ----------
    ins = [r for r in recs if r["group"] == "in_scope"]
    extra = [r for r in recs if r["group"] == "extra"]
    pos_off = run(BASE, True)
    out["C_independence"] = {
        "in_scope_total": len(ins),
        "in_scope_r9_exclusive": sum(1 for r in ins if r["r9_exclusive_capture"]),
        "in_scope_leaked_when_guard_off": sum(1 for r in ins if r["leaked_when_off"]),
        "in_scope_all_exclusive_and_leak": all(r["r9_exclusive_capture"] and r["leaked_when_off"] for r in ins),
        "extra_total": len(extra),
        "extra_r9_exclusive": sum(1 for r in extra if r["r9_exclusive_capture"]),
        "extra_leaked_when_guard_off": sum(1 for r in extra if r["leaked_when_off"]),
        "extra_caught_by_other_rule": sum(1 for r in extra if r["caught_by_other_rule"]),
        "extra_note": "None/空字符串由既有通用规则 validate_registry 第 322 行 falsy 断言拦下，"
                      "非 R9-LIC 专属；故关闭 R9-LIC 后仍变红属正常，不计为漏检缺口",
        "guard_off_positive": {"raised": pos_off["raised"], "stdout": pos_off["stdout"].strip(),
                               "has_LEAK_MODE": "LEAK-MODE" in pos_off["stdout"],
                               "claims_R9LIC_pass": "R9-LIC 四条 MIT" in pos_off["stdout"]},
    }

    v = out["C_independence"]
    out["verdict"] = {
        "A_positive_ok": not out["A_positive"]["raised"] and out["A_positive"]["claims_exact_string_MIT"],
        "A_values_exact_MIT": all(x["== 'MIT'"] for x in out["A_registry_values"].values()),
        "B_in_scope_all_exclusive": v["in_scope_r9_exclusive"] == v["in_scope_total"] == 20,
        "C_in_scope_all_leak_when_off": v["in_scope_leaked_when_guard_off"] == v["in_scope_total"],
        "D_guard_off_no_pass_claim": not v["guard_off_positive"]["claims_R9LIC_pass"]
                                     and v["guard_off_positive"]["has_LEAK_MODE"],
    }
    out["verdict"]["ALL"] = all(out["verdict"].values())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["verdict"]["ALL"] else 1


if __name__ == "__main__":
    sys.exit(main())
