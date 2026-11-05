#!/usr/bin/env python3
"""R8 独立补核脚本（只读，不原地重生成，不写 docs/ 与 reports/V9-R5/）。

核对对象：ainerzero.V9.R5 修订版（r2），固定 SHA：
  docs/research/adapter_registry.json  5c1564b0332f1d4ccf82e13c342490b716c88683fb1633db5f64d34e6958b6b5
  docs/research/ADAPTER_REGISTRY.md    332c503632953c3cb66fb9ee3f4993d0319fd935be8141920740ed642e334ca1
闭合对象：R6 两条发现（19:36 打回意见）。
用法（只读）：
  python3 reports/V-V9-R5/r2-independent/verify_r8_independent.py
  返回 0 = 正向全过且全部新反例变红；非零 = 有失败（真实非零退出）。
副作用：仅读文件 + 打印；不写任何受检文件。--mutate 风格的变异只在内存 deepcopy 上做。
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JSON_PATH = ROOT / "docs" / "research" / "adapter_registry.json"
MD_PATH = ROOT / "docs" / "research" / "ADAPTER_REGISTRY.md"
REPORT_PATH = ROOT / "reports" / "V9-R5" / "报告.md"
ARCHIVE_JSON = ROOT / "reports" / "V9-R5" / "r2-archive" / "adapter_registry.json"

EXP_JSON_SHA = "5c1564b0332f1d4ccf82e13c342490b716c88683fb1633db5f64d34e6958b6b5"
EXP_MD_SHA = "332c503632953c3cb66fb9ee3f4993d0319fd935be8141920740ed642e334ca1"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(p: Path) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def check_positive(reg, md_text, rep_text) -> list:
    """正向断言，全部用 assert；返回通过的检查名列表。"""
    passed = []
    # P00 SHA 固定
    assert sha256(JSON_PATH) == EXP_JSON_SHA, f"JSON SHA 不符: {sha256(JSON_PATH)}"
    passed.append("P00_json_sha_5c1564b0")
    assert sha256(MD_PATH) == EXP_MD_SHA, f"MD SHA 不符: {sha256(MD_PATH)}"
    passed.append("P00_md_sha_332c5036")
    # P01 51 条
    entries = reg.get("entries", [])
    assert len(entries) == 51, f"期望 51 条，实 {len(entries)}"
    passed.append("P01_51_entries")
    assert reg.get("access_date") == "2026-10-16", "access_date 须为 2026-10-16"
    passed.append("P01_access_date")
    emap = {e["id"]: e for e in entries}
    assert len(emap) == 51, "entry id 有重复"
    passed.append("P01_unique_ids")
    # P02 revision 提到 51（R6 发现 1 闭合一半）
    rev = reg.get("revision", "")
    assert "51" in rev, f"revision 必须提及 51，实: {rev[:120]}"
    assert "28" in rev or "R3" in rev, "revision 应保留 R3 历史脉络"
    passed.append("P02_revision_mentions_51")
    # P03 r5_summary（R6 发现 1 闭合）
    r5 = reg.get("r5_summary")
    assert isinstance(r5, dict), "缺少 r5_summary"
    assert r5.get("total_entries") == 51 == len(entries), "r5_summary.total_entries 须 ==51==len(entries)"
    assert len(r5.get("r1_preserved_ids", [])) == 8, "r1 须 8 条"
    assert len(r5.get("r3_preserved_ids", [])) == 20, "r3 须 20 条"
    assert len(r5.get("r5_added_ids", [])) == 23, "r5 新增须 23 条"
    union = set(r5["r1_preserved_ids"]) | set(r5["r3_preserved_ids"]) | set(r5["r5_added_ids"])
    assert union == set(emap.keys()), "r5_summary 三组并集须恰为 51 个 entry id"
    passed.append("P03_r5_summary_8_20_23_union51")
    # P04 r3_summary 历史标注（R6 发现 1 闭合另一半）
    r3 = reg.get("r3_summary")
    assert isinstance(r3, dict), "r3_summary 被删（须保留作历史）"
    assert r3.get("total_entries") == 28, "r3_summary.total_entries 须保持历史 28"
    snap = r3.get("snapshot_note", "")
    assert "历史" in snap or "快照" in snap, f"r3_summary 须注明历史快照，实: {snap}"
    passed.append("P04_r3_summary_historical_28")
    # P05 4 处许可勘误均为 MIT（R6 发现 2 闭合）：JSON
    for eid in ["dino-wm", "pldm", "pushforward", "slotssms"]:
        lic = emap[eid].get("license", {}).get("license", "")
        assert lic == "MIT" or lic.startswith("MIT"), f"{eid} JSON 许可须为 MIT，实: {lic}"
    passed.append("P05_json_4x_MIT")
    # P06 MD 同步且为 MIT
    for eid in ["dino-wm", "pldm", "pushforward", "slotssms"]:
        m = re.search(rf"\| {re.escape(eid)} \|[^\n]*", md_text)
        assert m is not None, f"MD 缺 {eid} 行"
        row = m.group(0)
        assert "MIT" in row, f"MD {eid} 行须含 MIT"
        assert "Apache" not in row, f"MD {eid} 行不应含 Apache（旧笔误回归）"
    passed.append("P06_md_4x_MIT_no_apache")
    # P07 报告 Table 3.3 为 MIT
    for eid in ["dino-wm", "pldm", "pushforward", "slotssms"]:
        m = re.search(rf"\| \`{re.escape(eid)}\`[^\n]*", rep_text)
        assert m is not None, f"报告缺 {eid} 行"
        assert "MIT" in m.group(0), f"报告 {eid} 行须为 MIT"
    passed.append("P07_report_4x_MIT")
    # P08 MD 全量 51 同步
    missing = [e["id"] for e in entries if f"| {e['id']} |" not in md_text]
    assert not missing, f"MD 缺条目: {missing}"
    passed.append("P08_md_sync_51")
    # P09 28 条历史字节未偷换（archive 可证部分）
    arc = load_json(ARCHIVE_JSON)
    arc_map = {e["id"]: e for e in arc.get("entries", [])}
    assert len(arc_map) == 28, "archive 须 28 条"
    for eid, ae in arc_map.items():
        assert eid in emap, f"archive 条目 {eid} 在现行中丢失"
        assert ae == emap[eid], f"archive 条目 {eid} 字节被改动（偷换）"
    passed.append("P09_28_preserved_byte_identical")
    return passed


def run_r8_adverse(reg, md_text):
    """R8 新反例：针对本次真实差异（4 MIT + 元数据），改坏必红。"""
    cases = [
        ("R8-A01_dino_wm_falsely_apache",
         lambda r, m: r["entries"][[e["id"] for e in r["entries"]].index("dino-wm")]["license"].update({"license": "Apache-2.0"}),
         "dino-wm JSON 许可须为 MIT"),
        ("R8-A02_pldm_falsely_apache",
         lambda r, m: r["entries"][[e["id"] for e in r["entries"]].index("pldm")]["license"].update({"license": "Apache-2.0"}),
         None),
        ("R8-A03_pushforward_falsely_apache",
         lambda r, m: r["entries"][[e["id"] for e in r["entries"]].index("pushforward")]["license"].update({"license": "Apache-2.0"}),
         None),
        ("R8-A04_slotssms_falsely_apache",
         lambda r, m: r["entries"][[e["id"] for e in r["entries"]].index("slotssms")]["license"].update({"license": "Apache-2.0"}),
         None),
        ("R8-A05_r5_summary_regress_to_28",
         lambda r, m: r["r5_summary"].update({"total_entries": 28}),
         "r5_summary.total_entries 须"),
        ("R8-A06_revision_strips_51",
         lambda r, m: r.update({"revision": "r2（R3 补登记）共 28 条"}),
         "revision 必须提及"),
    ]
    results = []
    red = 0
    for name, mut, _ in cases:
        mr = copy.deepcopy(reg)
        mm = md_text
        res = mut(mr, mm)
        if isinstance(res, str):
            mm = res
        # 用本脚本的正向断言检验（只取与变异相关的子集即可，但直接全量更严）
        try:
            # 为给出精确错误信息，这里用轻量断言复刻 check_positive 的对应分支
            if any(k in name for k in ("dino", "pldm", "pushforward", "slotssms")):
                eid = {"dino": "dino-wm", "pldm": "pldm", "pushforward": "pushforward", "slotssms": "slotssms"}[
                    "dino" if "dino" in name else ("pldm" if "pldm" in name else ("pushforward" if "pushforward" in name else "slotssms"))
                ]
                em = {e["id"]: e for e in mr["entries"]}
                lic = em[eid].get("license", {}).get("license", "")
                assert lic == "MIT" or lic.startswith("MIT"), f"{eid} JSON 许可须为 MIT，实: {lic}"
            elif "r5_summary" in name:
                assert mr["r5_summary"].get("total_entries") == 51 == len(mr["entries"]), "r5_summary 回退未被捕获"
            elif "revision" in name:
                assert "51" in mr.get("revision", ""), "revision 抹 51 未被捕获"
            else:
                raise AssertionError("未知反例分支")
            print(f"  [RED FAIL] {name}: 未变红（反例无效）")
            results.append({"name": name, "status": "failed", "caught": None})
        except AssertionError as e:
            red += 1
            print(f"  [RED PASS] {name}: 捕获 -> {e}")
            results.append({"name": name, "status": "red_passed", "caught": str(e)})
    assert red == len(cases), f"R8 反例未全部变红：{red}/{len(cases)}"
    print(f"=== R8 {red}/{len(cases)} 新反例全部真实变红 ===")
    return results


def main():
    print("=== [R8 1/3] SHA 固定与正向断言（只读）===")
    reg = load_json(JSON_PATH)
    md = load_text(MD_PATH)
    rep = load_text(REPORT_PATH)
    passed = check_positive(reg, md, rep)
    for p in passed:
        print(f"  [PASS] {p}")
    print(f"  => 正向 {len(passed)} 组通过：51 条、revision/r5_summary/r3_snapshot、4xMIT 三方一致、MD 同步、28 条字节一致。\n")
    print("=== [R8 2/3] 新反例矩阵（内存变异，真实非零）===")
    adv = run_r8_adverse(reg, md)
    print("\n=== [R8 3/3] 完成（未写受检文件）===")
    return {"passed": passed, "adverse": adv}


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"R8 FAIL: {e}", file=sys.stderr)
        sys.exit(1)
