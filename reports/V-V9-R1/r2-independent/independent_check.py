#!/usr/bin/env python3
"""R7 独立复核脚本：不导入/执行 R1 的 validate_registry.py。

判定全部用 assert；真实非零退出。只读 JSON+MD，不联网。Oracle 值来自本轮
webfetch 公开源记录（见 source_review.json），此处为固定可核对值，不是自动结论。

用法：
  python3 independent_check.py <json> <md>            # 绿/红单次判定，exit 0/1
  python3 independent_check.py --mutate <json> <md>   # 9 个不利 против例，exit 3 全红
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DATE_RE_OK = "2026"  # 检查日期包含年份的弱前置，具体由条目断言落实

EXPECTED_IDS = ["dreamerv3", "egnn", "h-jepa", "lewm", "slot-attention",
                "stable-worldmodel", "thick", "vjepa2"]
THICK_PRIMARY = "https://github.com/CognitiveModeling/THICK"
THIX = "https://github.com/CognitiveModeling/thix"
VJEPA21_PAPER = "https://arxiv.org/abs/2603.14482"
VJEPA2_REPO = "https://github.com/facebookresearch/vjepa2"
SWM_PAPER_DATE = "2026-05-20"


def load(json_path: Path, md_path: Path):
    reg = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    return reg, md


def by_id(entries):
    return {e["id"]: e for e in entries}


def validate(reg, md) -> None:
    assert isinstance(reg, dict), "根必须为对象"
    entries = reg.get("entries")
    assert isinstance(entries, list) and len(entries) == 8, \
        f"条目数必须为 8，当前 {len(entries) if isinstance(entries, list) else type(entries)}"
    ids = sorted(e["id"] for e in entries)
    assert ids == EXPECTED_IDS, f"ID 集合不符：{ids}"

    assert reg.get("access_date", "").startswith("2026-"), "access_date 必须为 2026 年内日期"

    for e in entries:
        tag = e["id"]
        for k in ("name", "paper", "repo", "license", "borrowable_mechanisms",
                  "mlx_feasibility", "non_inferables", "status"):
            assert k in e, f"{tag} 缺键 {k}"
        p = e["paper"]
        assert isinstance(p.get("authors"), list) and p["authors"], f"{tag} 作者缺失"
        assert p.get("url", "").startswith("https://"), f"{tag} 论文链接必须 https"
        assert "20" in p.get("date", ""), f"{tag} 论文日期/版本缺失"
        r = e["repo"]
        assert r.get("url", "").startswith("https://"), f"{tag} 仓库主链接必须 https"
        lic = e["license"]
        assert lic.get("license") and lic.get("source"), f"{tag} 许可或许可来源缺失"
        assert isinstance(e["borrowable_mechanisms"], list) and len(e["borrowable_mechanisms"]) >= 1, \
            f"{tag} 可借鉴机制必须 >=1"
        m = e["mlx_feasibility"]
        assert m.get("rating") and m.get("notes") and "deps" in m, f"{tag} MLX 可行性字段不完整"
        assert isinstance(e["non_inferables"], list) and len(e["non_inferables"]) >= 1, \
            f"{tag} 不可推断项必须 >=1"
        assert e["status"] in ("verified", "verified-paper-only"), f"{tag} 状态非法"
        # MD/JSON 同步：id、论文链接、仓库主链接必须出现在 MD
        assert tag in md, f"MD 缺条目 id {tag}"
        assert p["url"] in md, f"MD 缺 {tag} 论文链接 {p['url']}"
        assert r["url"] in md, f"MD 缺 {tag} 仓库主链接 {r['url']}"

    reg_by_id = by_id(entries)

    # R2 修正 1：THICK 官方代码与许可
    t = reg_by_id["thick"]
    assert t["repo"]["url"] == THICK_PRIMARY, f"THICK 主仓库必须为 {THICK_PRIMARY}"
    repos = [x.get("url") for x in t["repo"].get("repos", [])]
    assert THICK_PRIMARY in repos, "THICK 必须列出官方 TF2 仓库"
    assert THIX in repos, "THICK 必须列出官方 JAX 重实现 thix（R2 修正）"
    assert "MIT" in t["license"]["license"], "THICK 许可必须记录 MIT"
    assert any(("thix" in n) and ("未" in n) for n in t["non_inferables"]), \
        "必须保留 thix 许可未核不可推断项"
    assert THICK_PRIMARY in md and THIX in md, "MD 必须同时出现 THICK 与 thix 仓库链接"
    for repo_url in repos:
        assert repo_url in md, f"MD 缺 THICK 子仓库链接 {repo_url}"

    # R2 修正 2：Stable WorldModel v1 日期
    s = reg_by_id["stable-worldmodel"]
    assert s["paper"]["date"].startswith(SWM_PAPER_DATE), \
        f"Stable WorldModel v1 必须为 {SWM_PAPER_DATE}（当前 {s['paper']['date']}）"
    assert SWM_PAPER_DATE in md, f"MD 必须出现 {SWM_PAPER_DATE}"

    # R2 修正 3：V-JEPA 2.1 直链、仓库、发布日期
    v = reg_by_id["vjepa2"]
    assert v["paper"]["url"] == VJEPA21_PAPER, \
        f"V-JEPA 2.1 论文直链必须为 {VJEPA21_PAPER}（当前 {v['paper']['url']}）"
    assert v["repo"]["url"] == VJEPA2_REPO, "V-JEPA 仓库主链接必须为 facebookresearch/vjepa2"
    assert v["repo"].get("release_date") == "2026-03-16", \
        "V-JEPA 2.1 仓库发布日期 2026-03-16 必须保留"
    assert VJEPA21_PAPER in md, "MD 必须出现 V-JEPA 2.1 直链"
    assert "2026-03-16" in md, "MD 必须保留 2026-03-16 仓库发布日期"

    print(f"REGISTRY OK (R7): {len(entries)} entries, access {reg['access_date']}")


def make_mutations(reg: dict, md: str):
    cases = []

    def deepcopy_reg():
        return copy.deepcopy(reg)

    # 1. THICK repos 缺 thix
    r = deepcopy_reg()
    t = by_id(r["entries"])["thick"]
    t["repo"]["repos"] = [x for x in t["repo"]["repos"] if x.get("url") != THIX]
    cases.append(("R7-M1 THICK repos 缺 thix（R2修正回退）", r, md))

    # 2. THICK 许可字段丢失 MIT
    r = deepcopy_reg()
    t = by_id(r["entries"])["thick"]
    t["license"]["license"] = "Apache-2.0（假设，未核实）"
    cases.append(("R7-M2 THICK 许可丢失 MIT", r, md))

    # 3. THICK 清空 thix 许可未核不可推断项
    r = deepcopy_reg()
    t = by_id(r["entries"])["thick"]
    t["non_inferables"] = [n for n in t["non_inferables"] if "thix" not in n]
    cases.append(("R7-M3 清空 thix 许可未核不可推断项", r, md))

    # 4. Stable WorldModel 日期改回 2026-05-26
    r = deepcopy_reg()
    s = by_id(r["entries"])["stable-worldmodel"]
    s["paper"]["date"] = "2026-05-26（arXiv 2605.21800）"
    cases.append(("R7-M4 Stable WorldModel 日期改回 05-26", r, md))

    # 5. MD 缺 Stable 日期
    r = deepcopy_reg()
    md_broken = md.replace(SWM_PAPER_DATE, "（缺日期）")
    cases.append(("R7-M5 MD 缺 Stable 日期（MD/JSON 失同步）", r, md_broken))

    # 6. V-JEPA 直链退化为仓库链接
    r = deepcopy_reg()
    v = by_id(r["entries"])["vjepa2"]
    v["paper"]["url"] = VJEPA2_REPO
    cases.append(("R7-M6 V-JEPA 2.1 直链退化为仓库链接", r, md))

    # 7. V-JEPA 仓库发布日期改为 03-17（与 v2 混淆）
    r = deepcopy_reg()
    v = by_id(r["entries"])["vjepa2"]
    v["repo"]["release_date"] = "2026-03-17"
    cases.append(("R7-M7 V-JEPA release_date 改为 03-17", r, md))

    # 8. MD 缺 V-JEPA 直链
    r = deepcopy_reg()
    md_broken2 = md.replace(VJEPA21_PAPER, "（缺直链）")
    cases.append(("R7-M8 MD 缺 V-JEPA 直链（MD/JSON 失同步）", r, md_broken2))

    # 9. MD 缺 thix 链接
    r = deepcopy_reg()
    md_broken3 = md.replace(THIX, "（缺 thix）")
    cases.append(("R7-M9 MD 缺 thix 链接（MD/JSON 失同步）", r, md_broken3))

    return cases


def mutate(json_path: Path, md_path: Path) -> int:
    original_reg = json.loads(json_path.read_text(encoding="utf-8"))
    original_md = md_path.read_text(encoding="utf-8")
    cases = make_mutations(original_reg, original_md)
    tmp = Path(tempfile.mkdtemp(prefix="v9r1-r7-red-"))
    all_red = True
    results = []
    for i, (name, bad_reg, bad_md) in enumerate(cases, 1):
        case_dir = tmp / f"case{i}"
        case_dir.mkdir()
        bj = case_dir / "registry.json"
        bm = case_dir / "registry.md"
        bj.write_text(json.dumps(bad_reg, ensure_ascii=False, indent=2), encoding="utf-8")
        bm.write_text(bad_md, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(bj), str(bm)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            msg = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
            msg = msg[-1] if msg else "assertion failed"
            print(f"RED OK[{i}] {name}: {msg}")
            results.append((i, name, proc.returncode, msg))
        else:
            print(f"RED FAIL[{i}] {name}: 改坏后仍通过 (exit 0)")
            all_red = False
            results.append((i, name, proc.returncode, "still passes"))
    out = tmp / "r7_mutations.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mutation case files: {tmp}")
    return 3 if all_red else 1


def main(argv):
    if argv[:1] == ["--mutate"]:
        _, json_path, md_path = argv
        return mutate(Path(json_path), Path(md_path))
    json_path, md_path = argv
    reg, md = load(Path(json_path), Path(md_path))
    try:
        validate(reg, md)
    except AssertionError as ex:
        print(f"RED: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
