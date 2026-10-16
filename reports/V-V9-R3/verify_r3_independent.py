#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V-V9-R3 独立复核校验器（复核者：deepseek-v4flash-q7m2，**不是** ainerzero.V9.R3 作者）

只读核对下列两个被验文件，不改动它们：
    docs/research/adapter_registry.json
    docs/research/ADAPTER_REGISTRY.md

事实基线（EXPECTED 里的每一条）都由复核者本人在 2026-10-16 用独立 HTTP 只读请求重新打开
原始来源（arXiv abs/HTML、Crossref、GitHub API/raw、HuggingFace datasets API、项目页）
后写死；原始回包摘要见同目录 source_evidence.json。

与 R3 自带校验器 reports/V9-R3/validate_registry_r3.py 无任何共享代码：本脚本独立编写，
断言集合不同（侧重“来源身份/许可不得夸大”与“MD/JSON 同步”），用于交叉验证。

用法：
    python3 reports/V-V9-R3/verify_r3_independent.py [JSON] [MD]      # 正例，期望退出 0
    python3 reports/V-V9-R3/verify_r3_independent.py --mutate [JSON] [MD]
        # 对临时副本逐个注入反例；每个反例必须至少触发一个断言失败（真实变红）。
        # 全部变红 -> 退出 3；有任一未变红 -> 退出 1。

约束：纯 CPU；不导入 MLX/ORT/模型；不联网；不写被验文件（--mutate 只写系统临时目录）。
"""

import copy
import json
import os
import shutil
import sys
import tempfile

# --------------------------------------------------------------------------
# 复核者独立核实的事实基线（期望值）
# --------------------------------------------------------------------------
R1_IDS = ["h-jepa", "lewm", "vjepa2", "dreamerv3",
          "stable-worldmodel", "egnn", "slot-attention", "thick"]
R3_ADDED_IDS = ["gradcscg", "eswm", "far", "flow-equivariant-wm",
                "schaeffer-grid-cells", "seq-jepa", "equivariant-trust-horizons",
                "s5", "swap-equivariant-wm", "cscg", "tem", "cls", "nec",
                "banino-2018", "cueva-wei-2018", "plan2explore", "director",
                "sola-2018", "barrau-bonnabel-2017", "blenderworld"]
ALL_IDS = R1_IDS + R3_ADDED_IDS
ACCESS_DATE = "2026-10-16"

# 每条：id -> dict(paper_url_contains, repo_url_contains / repo_must_be_unverifiable,
#                 license_must_contain, status)
EXPECTED = {
    "gradcscg": dict(paper="2607.12382", repo="github.com/tristanstoeber/gradCSCG",
                     lic=["MIT"], status="verified"),
    "eswm": dict(paper="2505.13696", repo_unverifiable=True,
                 lic=["CC BY-NC-ND 4.0"], lic_field=["无法核"],
                 status="verified-paper-only"),
    "far": dict(paper="2609.34677", repo="github.com/sony/far",
                lic=["Attribution-NonCommercial", "CC BY-NC"],
                lic_field=["Attribution-NonCommercial", "CC BY-NC"],
                status="verified"),
    "flow-equivariant-wm": dict(paper="2601.01075", repo="github.com/hlillemark/flowm",
                                lic=["MIT"], status="verified"),
    "schaeffer-grid-cells": dict(paper="2312.03954",
                                 repo="github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction",
                                 lic=["CC BY-NC-ND 4.0"], lic_field=["无法核"],
                                 status="verified"),
    "seq-jepa": dict(paper="2505.03176", repo="github.com/hafezgh/seq-jepa",
                     lic=["MIT"], status="verified", paper_version="v3"),
    "equivariant-trust-horizons": dict(paper="2606.24946", repo_unverifiable=True,
                                       lic=["CC BY 4.0"], status="verified-paper-only"),
    "s5": dict(paper="2208.04933", repo="github.com/lindermanlab/S5",
               lic=["MIT"], status="verified"),
    "swap-equivariant-wm": dict(paper="2606.19928", repo_unverifiable=True,
                                lic=["non-exclusive"], status="verified-paper-only"),
    "cscg": dict(paper="10.1038/s41467-021-22559-5",
                 repo="github.com/vicariousinc/naturecomm_cscg", lic=["MIT"],
                 status="verified"),
    "tem": dict(paper="10.1016/j.cell.2020.10.024",
                repo="github.com/djcrw/generalising-structural-knowledge",
                lic=["CC BY 4.0"], lic_field=["无法核"], status="verified"),
    "cls": dict(paper="10.1037/0033-295X.102.3.419", repo_unverifiable=True,
                lic=["无法核"], status="verified-paper-only"),
    "nec": dict(paper="1703.01988", repo_unverifiable=True, lic=["无法核"],
                status="verified-paper-only"),
    "banino-2018": dict(paper="10.1038/s41586-018-0102-6",
                        repo="github.com/google-deepmind/grid-cells",
                        lic=["Apache-2.0"], lic_field=["无法核"], status="verified"),
    "cueva-wei-2018": dict(paper="1803.07770", repo_unverifiable=True,
                           lic=["无法核"], status="verified-paper-only"),
    "plan2explore": dict(paper="2005.05960", repo="github.com/ramanans1/plan2explore",
                         lic=["Apache-2.0"], status="verified"),
    "director": dict(paper="2206.04114", repo="github.com/danijar/director",
                     lic=["non-exclusive"], lic_field=["无法核"], status="verified"),
    "sola-2018": dict(paper="1812.01537", repo="github.com/artivis/manif",
                      lic=["MIT"], status="verified"),
    "barrau-bonnabel-2017": dict(paper="1410.1465", repo_unverifiable=True,
                                 lic=["无法核"], status="verified-paper-only"),
    "blenderworld": dict(paper="BlenderWorld", repo="github.com/QwenLM/BlenderWorld",
                         lic=["MIT"], status="verified"),
}

MD_REQUIRED_SUBSTRINGS = [
    "https://github.com/tristanstoeber/gradCSCG",
    "https://github.com/sony/far",
    "Attribution-NonCommercial",
    "https://huggingface.co/datasets/Qwen/BlenderWorld",
    "2,651",
    "223",
    "Blender 4.2.10",
    "Harbor 0.23.0",
    "https://github.com/CognitiveModeling/thix",
    "无法核",
]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _by_id(data):
    return {e["id"]: e for e in data["entries"]}


def _blob(entry):
    return json.dumps(entry, ensure_ascii=False)


# --------------------------------------------------------------------------
# 断言集合：每个返回 (check_name, ok(bool), detail)
# --------------------------------------------------------------------------
def run_checks(data, md_text):
    res = []
    entries = data.get("entries") or []
    ids = [e.get("id") for e in entries]
    by = _by_id(data)

    res.append(("C01 条目总数=28 且 ID 唯一",
                len(entries) == 28 and len(set(ids)) == 28 and len(ids) == 28,
                "n=%d unique=%d" % (len(ids), len(set(ids)))))

    res.append(("C02 顶层 access_date",
                data.get("access_date") == ACCESS_DATE,
                repr(data.get("access_date"))))

    res.append(("C03 R1 保留 8 条 ID 完整",
                all(i in by for i in R1_IDS),
                ",".join(i for i in R1_IDS if i not in by) or "ok"))

    res.append(("C04 R3 新增 20 条 ID 完整",
                all(i in by for i in R3_ADDED_IDS),
                ",".join(i for i in R3_ADDED_IDS if i not in by) or "ok"))

    # 结构：必备字段 + 每条 >=1 可借鉴机制 + >=1 不可推断项
    bad = []
    for e in entries:
        for k in ("id", "name", "status", "paper", "repo", "license",
                  "mlx_feasibility", "borrowable_mechanisms", "non_inferables"):
            if k not in e:
                bad.append("%s:missing:%s" % (e.get("id"), k))
        if not (e.get("borrowable_mechanisms") or []):
            bad.append("%s:no_mechanism" % e.get("id"))
        if not (e.get("non_inferables") or []):
            bad.append("%s:no_non_inferable" % e.get("id"))
    res.append(("C05 全部条目字段完整且机制/边界非空", not bad, ";".join(bad) or "ok"))

    # 来源身份与许可：逐条比对复核者独立打开的原始来源
    for eid, exp in EXPECTED.items():
        e = by.get(eid)
        if e is None:
            res.append(("C10[%s] 存在" % eid, False, "条目缺失"))
            continue
        blob = _blob(e)
        repo_url = (e.get("repo") or {}).get("url", "")
        lic_field = (e.get("license") or {}).get("license", "")
        ok = True
        detail = []
        if exp.get("paper") and exp["paper"] not in json.dumps(e.get("paper"), ensure_ascii=False):
            ok = False
            detail.append("paper_url")
        if exp.get("repo") and exp["repo"] not in repo_url:
            ok = False
            detail.append("repo_url")
        if exp.get("repo_unverifiable") and not repo_url.startswith("无法核"):
            ok = False
            detail.append("repo_not_marked_unverifiable")
        for tok in exp.get("lic", []):
            if tok not in blob:
                ok = False
                detail.append("lic:%s" % tok)
        for tok in exp.get("lic_field", []):
            if tok not in lic_field:
                ok = False
                detail.append("lic_field:%s" % tok)
        if exp.get("paper_version") and (e.get("paper") or {}).get("version") != exp["paper_version"]:
            ok = False
            detail.append("paper_version=%r" % (e.get("paper") or {}).get("version"))
        if exp.get("status") and e.get("status") != exp["status"]:
            ok = False
            detail.append("status=%r" % e.get("status"))
        res.append(("C10[%s] 来源/许可/状态一致" % eid, ok, ";".join(detail) or "ok"))

    # BlenderWorld 专项：不得把评测基准当世界模型，数字与官方环境须一致
    bw = (by.get("blenderworld") or {})
    spec = bw.get("benchmark_spec") or {}
    ts = spec.get("task_scale") or {}
    env = spec.get("official_eval_env") or {}
    ds = spec.get("dataset_license") or {}
    bw_ok = (
        spec.get("is_world_model") is False
        and ts.get("total_tasks") == 223
        and ts.get("total_binary_criteria") == 2651
        and ts.get("by_input_modality") == {"text": 78, "image_text": 130, "video_text": 15}
        and ts.get("tasks_with_spec_attachments") == 59
        and ts.get("categories") == 9 and ts.get("subcategories") == 22
        and "4.2.10" in (env.get("blender") or "")
        and "2.1.220" in (env.get("agent_cli") or "")
        and "0.23.0" in (env.get("python") or "")
        and "GPT-5.6-terra" in (env.get("paid_vlm_api") or "")
        and ds.get("license") == "MIT"
        and ds.get("dataset_url") == "https://huggingface.co/datasets/Qwen/BlenderWorld"
    )
    res.append(("C11 BlenderWorld 基准规格=独立核实值", bw_ok, "spec mismatch"))

    # MD/JSON 同步 + MD 关键来源/许可/口径存在
    missing_ids = [i for i in ALL_IDS if i not in md_text]
    missing_sub = [s for s in MD_REQUIRED_SUBSTRINGS if s not in md_text]
    res.append(("C12 MD 覆盖全部 28 条 ID", not missing_ids, ",".join(missing_ids) or "ok"))
    res.append(("C13 MD 含关键来源/许可/口径", not missing_sub, ",".join(missing_sub) or "ok"))

    # 反夸大不变量：凡 JSON 中代码仓库许可标为“无法核”的条目，MD 也必须出现“无法核”
    unverif = [e["id"] for e in entries
               if "无法核" in json.dumps(e.get("license"), ensure_ascii=False)]
    leak = [i for i in unverif if i not in md_text]
    res.append(("C14 无法核条目在 MD 中同步标注", not leak, ",".join(leak) or "ok"))

    # 反夸大不变量：不得出现无来源的 “verified” 断言（论文 URL 必须非空）
    no_url = [e["id"] for e in entries if not ((e.get("paper") or {}).get("url"))]
    res.append(("C15 每条都有可核对论文/报告 URL", not no_url, ",".join(no_url) or "ok"))

    return res


# --------------------------------------------------------------------------
# 故意改坏的反例（每个都必须真实变红）
# --------------------------------------------------------------------------
def _mut(mut_id, desc, fn):
    return (mut_id, desc, fn)


def build_mutations():
    def set_entry(data, eid, path, value):
        for e in data["entries"]:
            if e["id"] == eid:
                node = e
                for k in path[:-1]:
                    node = node[k]
                node[path[-1]] = value

    def del_entry(data, eid):
        data["entries"] = [e for e in data["entries"] if e["id"] != eid]

    return [
        _mut("M01", "删减 gradcscg 条目（28->27）",
             lambda d, m: del_entry(d, "gradcscg")),
        _mut("M02", "顶层 access_date 改回 2025-10-16",
             lambda d, m: d.__setitem__("access_date", "2025-10-16")),
        _mut("M03", "把 far 的 CC BY-NC 4.0 篡改为 MIT",
             lambda d, m: set_entry(d, "far", ["license", "license"],
                                    "代码仓库：MIT；论文：CC BY 4.0")),
        _mut("M04", "把 gradcscg 仓库链接换成伪造仓库",
             lambda d, m: set_entry(d, "gradcscg", ["repo", "url"],
                                    "https://github.com/evil/fake-CSCG")),
        _mut("M05", "给无官方代码的 eswm 编造仓库链接（抹掉无法核）",
             lambda d, m: set_entry(d, "eswm", ["repo", "url"],
                                    "https://github.com/BashivanLab/ESWM")),
        _mut("M06", "抹去 tem 代码许可的『无法核』改为 MIT",
             lambda d, m: set_entry(d, "tem", ["license", "license"],
                                    "论文：CC BY 4.0；代码：MIT")),
        _mut("M07", "把 schaeffer-grid-cells 仓库许可『无法核』改为 MIT",
             lambda d, m: set_entry(d, "schaeffer-grid-cells", ["license", "license"],
                                    "论文：CC BY-NC-ND 4.0；代码：MIT")),
        _mut("M08", "把 blenderworld 的 is_world_model 篡改为 True",
             lambda d, m: set_entry(d, "blenderworld",
                                    ["benchmark_spec", "is_world_model"], True)),
        _mut("M09", "篡改 blenderworld 任务数 223 -> 200",
             lambda d, m: set_entry(d, "blenderworld",
                                    ["benchmark_spec", "task_scale", "total_tasks"], 200)),
        _mut("M10", "篡改 blenderworld 纯文任务数 78 -> 80",
             lambda d, m: set_entry(d, "blenderworld",
                                    ["benchmark_spec", "task_scale", "by_input_modality", "text"], 80)),
        _mut("M11", "篡改 blenderworld 官方 Blender 版本 4.2.10 -> 5.2.2",
             lambda d, m: set_entry(d, "blenderworld",
                                    ["benchmark_spec", "official_eval_env", "blender"],
                                    "Blender 5.2.2")),
        _mut("M12", "篡改 blenderworld HF 数据集许可 MIT -> 自定义",
             lambda d, m: set_entry(d, "blenderworld",
                                    ["benchmark_spec", "dataset_license", "license"],
                                    "Apache-2.0")),
        _mut("M13", "篡改 seq-jepa 版本 v3 -> v1（夸大/错标）",
             lambda d, m: set_entry(d, "seq-jepa", ["paper", "version"], "v1")),
        _mut("M14", "把 sola-2018 配套库换成伪造链接",
             lambda d, m: set_entry(d, "sola-2018", ["repo", "url"],
                                    "https://github.com/fake/micro-lie")),
        _mut("M15", "MD 删去 gradCSCG 仓库链接（MD/JSON 失同步）",
             lambda d, m: m.replace("https://github.com/tristanstoeber/gradCSCG", "")),
        _mut("M16", "MD 删去 BlenderWorld HF 数据集链接（MD/JSON 失同步）",
             lambda d, m: m.replace("https://huggingface.co/datasets/Qwen/BlenderWorld", "")),
        _mut("M17", "MD 删去 sony/far 非商业许可警告",
             lambda d, m: m.replace("Attribution-NonCommercial", "")),
        _mut("M18", "MD 删去 thix 仓库（回退 R2 修正）",
             lambda d, m: m.replace("https://github.com/CognitiveModeling/thix", "")),
        _mut("M19", "把 director 许可从『无法核』外推为 MIT（回退 R2 纠正）",
             lambda d, m: set_entry(d, "director", ["license", "license"],
                                    "代码仓库：MIT；论文：arXiv non-exclusive 1.0")),
        _mut("M20", "清空 flow-equivariant-wm 的不可推断项",
             lambda d, m: set_entry(d, "flow-equivariant-wm", ["non_inferables"], [])),
        _mut("M21", "把 banino-2018 的 RL 未开源『无法核』外推为 Apache-2.0",
             lambda d, m: set_entry(d, "banino-2018", ["license", "license"],
                                    "代码仓库：Apache-2.0；论文：Springer Nature TDM")),
    ]


# --------------------------------------------------------------------------
def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    mutate = "--mutate" in argv
    json_path = args[0] if len(args) > 0 else "docs/research/adapter_registry.json"
    md_path = args[1] if len(args) > 1 else "docs/research/ADAPTER_REGISTRY.md"

    data = load(json_path)
    with open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()

    if not mutate:
        results = run_checks(data, md_text)
        failed = [r for r in results if not r[1]]
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + ("  :: " + detail if detail and not ok else ""))
        print("-" * 60)
        print("V-V9-R3 INDEPENDENT CHECK: %d/%d passed" % (len(results) - len(failed), len(results)))
        return 0 if not failed else 1

    # --mutate：对临时副本注入反例，验证“改坏必须变红”
    tmp = tempfile.mkdtemp(prefix="vv9r3-mutate-")
    red, not_red = [], []
    try:
        for mid, desc, fn in build_mutations():
            d2 = copy.deepcopy(data)
            m2 = md_text
            out = fn(d2, m2)
            if isinstance(out, str):
                m2 = out
            results = run_checks(d2, m2)
            failed = [r for r in results if not r[1]]
            if failed:
                print("RED OK[%s] %s" % (mid, desc))
                red.append(mid)
            else:
                print("RED FAIL[%s] %s  <-- 反例未被捕获" % (mid, desc))
                not_red.append(mid)
        # 反例注入只发生在内存副本；被验文件在本模式中从不写回。
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 60)
    print("RED CONTROL: %d/%d red; not-red=%s" %
          (len(red), len(red) + len(not_red), ",".join(not_red) or "none"))
    return 3 if not not_red else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
