"""V9-R1 注册表校验器：全部判定用断言，真实非零退出。

用法：
  python3 validate_registry.py docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md   # 绿（exit 0）
  python3 validate_registry.py --mutate <json> <md>   # 故意改坏对照：往 /tmp 写破损副本并校验，期望 AssertionError（exit 3）
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


def load(json_path: Path, md_path: Path) -> tuple[dict, str]:
    reg = json.loads(json_path.read_text(encoding="utf-8"))
    md = md_path.read_text(encoding="utf-8")
    return reg, md


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
        assert r.get("url", "").startswith(("https://", "未找到")), f"{tag} 仓库链接非法"
        lic = e["license"]
        assert lic.get("license") and lic.get("source"), f"{tag} 许可与许可来源不缺"
        assert isinstance(e["borrowable_mechanisms"], list) and len(e["borrowable_mechanisms"]) >= 1, f"{tag} 可借鉴机制≥1"
        m = e["mlx_feasibility"]
        assert m.get("rating") and m.get("notes"), f"{tag} MLX 可行性须有评级与依据"
        assert "deps" in m, f"{tag} MLX 须列依赖（未知亦须明写）"
        assert isinstance(e["non_inferables"], list) and len(e["non_inferables"]) >= 1, f"{tag} 不可推断项不缺"
        assert e["status"] in ("verified", "verified-paper-only"), f"{tag} 状态非法"
        # MD 与 JSON 一致：MD 须出现该条目 id 与论文链接
        assert tag in md, f"MD 缺条目 {tag}"
        if p["url"].startswith("https://"):
            assert p["url"] in md, f"MD 缺 {tag} 论文链接"
    print(f"REGISTRY OK: {len(entries)} entries, access {reg['access_date']}")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--mutate"]:
        _, json_path, md_path = argv
        reg = json.loads(Path(json_path).read_text(encoding="utf-8"))
        bad = copy.deepcopy(reg)
        bad["entries"][0]["license"]["license"] = ""  # 故意改坏：许可置空
        bad["entries"][1]["non_inferables"] = []  # 故意改坏：不可推断项清空
        tmp = Path(tempfile.mkdtemp(prefix="v9r1-red-"))
        bj = tmp / "adapter_registry.json"
        bj.write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")
        md = Path(md_path).read_text(encoding="utf-8")
        try:
            validate(bad, md)
        except AssertionError as ex:
            print(f"RED OK（改坏已变红）: {ex}")
            return 3
        print("RED FAIL：改坏后仍通过")
        return 1
    json_path, md_path = argv
    reg, md = load(Path(json_path), Path(md_path))
    validate(reg, md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
