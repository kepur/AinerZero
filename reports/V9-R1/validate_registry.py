"""V9-R1 注册表校验器 r1：全部判定用断言，脚本真实非零退出。

r1（2026-10-16）在 r0 基础上加入 R2 复核要求的定点断言：
- THICK 必须有官方代码（THICK TF2 + thix JAX），许可与 thix 未核项保留；
- stable-worldmodel 论文 v1 日期必须为 2026-05-20；
- V-JEPA 2.1 必须有直接论文链接 arXiv:2603.14482，且保留仓库 2026-03-16 发布日期；
- 每条 MD 必须出现条目 id、论文链接与仓库链接（MD/JSON 同步）。

用法：
  python3 validate_registry.py docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md   # 绿（exit 0）
  python3 validate_registry.py --mutate <json> <md>   # 故意改坏对照：逐项改坏，全部变红才 exit 3
"""
from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPECTED_IDS = ["dreamerv3", "egnn", "h-jepa", "lewm", "slot-attention",
                "stable-worldmodel", "thick", "vjepa2"]
THICK_PRIMARY = "https://github.com/CognitiveModeling/THICK"
THIX = "https://github.com/CognitiveModeling/thix"
VJEPA21_PAPER = "https://arxiv.org/abs/2603.14482"
VJEPA2_REPO = "https://github.com/facebookresearch/vjepa2"
SWM_PAPER_DATE = "2026-05-20"


def load(json_path: Path, md_path: Path) -> tuple[dict, str]:
    reg = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    return reg, md


def by_id(entries: list) -> dict:
    return {e["id"]: e for e in entries}


def validate(reg: dict, md: str) -> None:
    assert isinstance(reg, dict), "根须为对象"
    entries = reg.get("entries")
    assert isinstance(entries, list) and len(entries) == 8, f"须恰 8 条，得 {len(entries) if isinstance(entries, list) else type(entries)}"
    ids = sorted(e["id"] for e in entries)
    assert ids == EXPECTED_IDS, f"条目 ID 不符：{ids}"
    assert DATE_RE.match(reg.get("access_date", "")), "access_date 须为 YYYY-MM-DD"
    for e in entries:
        tag = e["id"]
        for k in ("name", "paper", "repo", "license", "borrowable_mechanisms",
                  "mlx_feasibility", "non_inferables", "status"):
            assert k in e, f"{tag} 缺键 {k}"
        p = e["paper"]
        assert p.get("url", "").startswith("https://"), f"{tag} 论文链接须 https"
        assert "20" in p.get("date", ""), f"{tag} 论文须有版本/日期"
        assert isinstance(p.get("authors"), list) and p["authors"], f"{tag} 须有作者"
        r = e["repo"]
        # R2：不再接受「未找到」，每条须有真实仓库链接
        assert r.get("url", "").startswith("https://"), f"{tag} 仓库链接须为 https（不接受未找到）"
        lic = e["license"]
        assert lic.get("license") and lic.get("source"), f"{tag} 许可与许可来源不缺"
        assert isinstance(e["borrowable_mechanisms"], list) and len(e["borrowable_mechanisms"]) >= 1, f"{tag} 可借鉴机制≥1"
        m = e["mlx_feasibility"]
        assert m.get("rating") and m.get("notes"), f"{tag} MLX 可行性须有评级与依据"
        assert "deps" in m, f"{tag} MLX 须列依赖（未知亦须明写）"
        assert isinstance(e["non_inferables"], list) and len(e["non_inferables"]) >= 1, f"{tag} 不可推断项不缺"
        assert e["status"] in ("verified", "verified-paper-only"), f"{tag} 状态非法"
        # MD 与 JSON 一致：MD 须出现该条目 id、论文链接与仓库链接
        assert tag in md, f"MD 缺条目 {tag}"
        assert p["url"] in md, f"MD 缺 {tag} 论文链接 {p['url']}"
        assert r["url"] in md, f"MD 缺 {tag} 仓库链接 {r['url']}"

    reg_by_id = by_id(entries)

    # --- R2 定点修正 1：THICK 官方代码 ---
    t = reg_by_id["thick"]
    assert t["repo"]["url"] == THICK_PRIMARY, f"THICK 主仓库须为 {THICK_PRIMARY}"
    thick_repos = [x.get("url") for x in t["repo"].get("repos", [])]
    assert THICK_PRIMARY in thick_repos, "THICK 须列官方 TF2 仓库"
    assert THIX in thick_repos, "THICK 须列官方 JAX 重实现 thix（R2 修正）"
    assert "MIT" in t["license"]["license"], "THICK 许可须记 MIT"
    assert any("thix" in n and "未" in n for n in t["non_inferables"]), "须保留 thix 许可未核的不可推断项"
    assert THICK_PRIMARY in md and THIX in md, "MD 须同时出现 THICK 与 thix 仓库链接"

    # --- R2 定点修正 2：Stable WorldModel v1 日期 ---
    s = reg_by_id["stable-worldmodel"]
    assert s["paper"]["date"].startswith(SWM_PAPER_DATE), f"Stable WorldModel v1 须为 {SWM_PAPER_DATE}（R2 修正）"
    assert SWM_PAPER_DATE in md, f"MD 须出现 {SWM_PAPER_DATE}"

    # --- R2 定点修正 3：V-JEPA 2.1 直链与版本 ---
    v = reg_by_id["vjepa2"]
    assert v["paper"]["url"] == VJEPA21_PAPER, f"V-JEPA 2.1 论文直链须为 {VJEPA21_PAPER}（R2 修正）"
    assert v["repo"]["url"] == VJEPA2_REPO, "V-JEPA 2 仓库链接须为 facebookresearch/vjepa2"
    assert v["repo"].get("release_date") == "2026-03-16", "V-JEPA 2.1 仓库发布日期 2026-03-16 须保留"
    assert VJEPA21_PAPER in md, "MD 须出现 V-JEPA 2.1 直链"
    assert "2026-03-16" in md, "MD 须保留 2026-03-16 仓库发布日期"

    print(f"REGISTRY OK: {len(entries)} entries, access {reg['access_date']}")


def _mutations(reg: dict, md: str) -> list[tuple[str, dict, str]]:
    """每个返回 (说明, 改坏后的 reg, 改坏后的 md)，全部必须变红。"""
    cases: list[tuple[str, dict, str]] = []

    def r0():
        return copy.deepcopy(reg)

    a = r0(); a["entries"][0]["license"]["license"] = ""
    cases.append(("许可置空", a, md))

    b = r0(); b["entries"][1]["non_inferables"] = []
    cases.append(("不可推断项清空", b, md))

    c = r0()
    thick = by_id(c["entries"])["thick"]
    thick["repo"]["url"] = "未找到"
    thick["repo"]["repos"] = []
    cases.append(("THICK 官方代码回退成未找到", c, md))

    d = r0(); by_id(d["entries"])["stable-worldmodel"]["paper"]["date"] = "2026-05-26（arXiv 2605.21800）"
    cases.append(("Stable WorldModel 日期改回 2026-05-26", d, md))

    e = r0(); by_id(e["entries"])["vjepa2"]["paper"]["url"] = VJEPA2_REPO
    cases.append(("V-JEPA 2.1 直链退成仓库链接", e, md))

    f = r0()
    md_broken = md.replace("https://arxiv.org/abs/2603.14482", "（缺直链）")
    cases.append(("MD 缺 V-JEPA 2.1 直链（MD/JSON 失同步）", f, md_broken))

    g = r0()
    md_broken2 = md.replace("https://github.com/CognitiveModeling/thix", "（缺 thix）")
    cases.append(("MD 缺 thix 链接（MD/JSON 失同步）", g, md_broken2))

    return cases


def mutate(json_path: Path, md_path: Path) -> int:
    reg = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="v9r1-red-"))
    all_red = True
    for i, (name, bad, bad_md) in enumerate(_mutations(reg, md), 1):
        bj = tmp / f"case{i}.json"
        bj.write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            validate(bad, bad_md)
        except AssertionError as ex:
            print(f"RED OK[{i}] {name}: {ex}")
        else:
            print(f"RED FAIL[{i}] {name}: 改坏后仍通过")
            all_red = False
    return 3 if all_red else 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["--mutate"]:
        _, json_path, md_path = argv
        return mutate(Path(json_path), Path(md_path))
    json_path, md_path = argv
    reg, md = load(Path(json_path), Path(md_path))
    validate(reg, md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
