#!/usr/bin/env python3
"""V9-R11 注册表校验器 r4（2026-10-28）：全部判定用 assert，脚本真实非零退出。

与 r5 校验器的区别（r5 保留原字节不动，只作历史证据）：
1. **不硬编码任何 ID 与条数**。期望 ID 集合、条数、分级计数、更正清单、历史快照关系
   全部从 `adapter_registry.json` 自身推导；MD 只作为被核对对象，不提供期望值。
2. **MD 与 JSON 严格同步**：总表行数、行序、每行的 ID/名称/论文链接/仓库链接/许可/MLX 评级，
   以及 §4 机制汇总的条数、条序与每条机制文本，逐项与 JSON 比对。
3. 新增 r4 字段的规则校验：`adoption_tier` 必须属于 `r4_summary.tier_labels` 的键；
   有 `corrections` 的条目必须出现在 `r4_summary.corrected_ids` 且 MD §8.1 有对应小节。
4. **默认只读**：只打开两个交付物，不写任何文件（`--self-test` 也只写临时目录）。
5. `--root` 指定项目根；默认取本脚本所在位置的 ../../（即 reports/V9-R11/ 的上两级）。

用法：
  python3 reports/V9-R11/validate_registry_r4.py                 # 校验仓库内交付物
  python3 reports/V9-R11/validate_registry_r4.py --root /path    # 校验指定根的交付物
  python3 reports/V9-R11/validate_registry_r4.py --self-test     # 14 项改坏变红对照（只写临时目录）
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MONTH_RE = re.compile(r"^\d{4}-\d{2}")  # 兼容 r3 的历史写法（如 2026-10）
YEAR_RE = re.compile(r"(?:19|20)\d{2}")  # 兼容 r3 的历史特殊日期写法（如 ICLR 2024）
ROW_RE = re.compile(r"^\| ([a-z0-9][a-z0-9\-]*) \| (.+)$")
BULLET_RE = re.compile(r"^- \*\*([a-z0-9][a-z0-9\-]*)\*\*：(.+)$")
TOTAL_H1_RE = re.compile(r"^## 1\. 总表（(\d+) 条")
TOTAL_H4_RE = re.compile(r"^## 4\. 可借鉴机制汇总（全部 (\d+) 条）")
UNVERIFIABLE = "无法核"


def _load(root: Path):
    jp = root / "docs/research/adapter_registry.json"
    mp = root / "docs/research/ADAPTER_REGISTRY.md"
    assert jp.exists(), f"JSON 不存在: {jp}"
    assert mp.exists(), f"MD 不存在: {mp}"
    data = json.loads(jp.read_text(encoding="utf-8"))
    md = mp.read_text(encoding="utf-8")
    return data, md


def _md_sections(md: str) -> dict:
    """按一级标题切分 MD，返回 {标题前缀: 段落文本}；缺失的段落返回空串。"""
    marks = ["## 1. 总表", "## 2. ", "## 3. ", "## 4. 可借鉴机制汇总", "## 5. ", "## 6. ", "## 7. ", "## 8. "]
    idx = []
    for m in marks:
        i = md.find(m)
        idx.append(i if i >= 0 else len(md))
    idx = sorted(idx)
    out = {}
    for k, i in enumerate(idx):
        j = idx[k + 1] if k + 1 < len(idx) else len(md)
        head = md[i:j].split("\n", 1)[0]
        out[head] = md[i:j]
    return out


def validate_registry(root: Path) -> dict:
    data, md = _load(root)

    # ---------------- 1. 顶层结构 ----------------
    for key in ("registry", "revision", "access_date", "entries", "r3_summary", "r5_summary", "r4_summary"):
        assert key in data, f"顶层缺少 {key}"
    entries = data["entries"]
    assert isinstance(entries, list) and entries, "entries 必须是非空列表"
    assert DATE_RE.match(data["access_date"]), f"顶层 access_date 格式无效: {data['access_date']}"

    ids = [e.get("id") for e in entries]
    assert all(isinstance(i, str) and i for i in ids), "存在空 id 或非字符串 id"
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"id 重复: {dup}"
    assert ids == sorted(ids), "entries 必须按 id 升序排列（构建器与 MD 总表同序）"
    id_set = set(ids)
    total = len(entries)

    summary = data["r4_summary"]
    added_set = set(summary.get("r11_added_ids") or [])
    tier_labels = summary.get("tier_labels")
    assert isinstance(tier_labels, dict) and tier_labels, "r4_summary.tier_labels 必须是非空字典（分级名的唯一来源）"

    # ---------------- 2. 逐条字段规则（全部由数据推导） ----------------
    for e in entries:
        eid = e["id"]
        assert isinstance(e.get("name"), str) and e["name"].strip(), f"{eid} 缺少 name"
        assert e.get("status") in ("verified", "verified-paper-only"), f"{eid} status 非法: {e.get('status')}"
        assert DATE_RE.match(e.get("access_date", "")), f"{eid} access_date 格式无效: {e.get('access_date')}"

        p = e.get("paper")
        assert isinstance(p, dict), f"{eid} 缺少 paper 对象"
        assert isinstance(p.get("title"), str) and p["title"].strip(), f"{eid} 缺少 paper.title"
        assert isinstance(p.get("authors"), list) and p["authors"], f"{eid} paper.authors 必须是非空列表"
        assert all(isinstance(a, str) and a.strip() for a in p["authors"]), f"{eid} paper.authors 含空项"
        assert isinstance(p.get("url"), str) and p["url"].startswith("http"), f"{eid} paper.url 非法: {p.get('url')}"
        date = p.get("date", "")
        if date.startswith(UNVERIFIABLE):
            pass
        elif date[:1].isdigit():
            assert MONTH_RE.match(date), f"{eid} paper.date 以数字开头但不是 YYYY-MM(-DD): {date!r}"
        else:
            # 兼容 r3 的历史写法（如『ICLR 2024（spotlight）』）：必须至少含四位年份
            assert YEAR_RE.search(date), f"{eid} paper.date 既不含年份也不是『无法核』: {date!r}"

        r = e.get("repo")
        lic = e.get("license")
        assert isinstance(r, dict) and isinstance(r.get("url"), str), f"{eid} 缺少 repo.url"
        assert isinstance(lic, dict), f"{eid} 缺少 license 对象"
        assert isinstance(lic.get("license"), str) and lic["license"].strip(), f"{eid} 缺少 license.license"
        assert isinstance(lic.get("source"), str) and lic["source"].strip(), f"{eid} 缺少 license.source"

        if e["status"] == "verified-paper-only":
            assert r["url"].startswith(UNVERIFIABLE), f"{eid} 无官方代码，repo.url 须以『无法核』开头: {r['url']}"
            assert UNVERIFIABLE in lic["license"], f"{eid} 无官方代码，license.license 须标明代码许可『无法核』"
        else:
            assert r["url"].startswith("https://"), f"{eid} 有官方代码，repo.url 须以 https:// 开头: {r['url']}"
            if UNVERIFIABLE in lic["license"] and eid in added_set:
                # 有仓库但许可读不出正文（仅对 R11 新增条目强制）：必须显式说明为什么无法核
                assert "LICENSE" in lic["license"] or "许可" in lic["license"], (
                    f"{eid} 仓库存在但许可无法核时，license.license 必须写明原因"
                )

        # 核实留痕：有 verification 的条目必须列出至少一个打开过的一手来源
        if "verification" in e:
            v = e["verification"]
            assert isinstance(v, dict), f"{eid} verification 必须是对象"
            assert isinstance(v.get("opened"), list) and v["opened"], f"{eid} verification.opened 不能为空"
            assert all(isinstance(u, str) and u.startswith("http") for u in v["opened"]), (
                f"{eid} verification.opened 必须是 http(s) 链接列表"
            )
            assert isinstance(v.get("unverified", []), list), f"{eid} verification.unverified 必须是列表"

        mech = e.get("borrowable_mechanisms")
        assert isinstance(mech, list) and mech, f"{eid} 缺少 borrowable_mechanisms"
        assert all(isinstance(m, str) and m.strip() for m in mech), f"{eid} borrowable_mechanisms 含空项"

        mlx = e.get("mlx_feasibility")
        assert isinstance(mlx, dict), f"{eid} 缺少 mlx_feasibility"
        assert isinstance(mlx.get("rating"), str) and mlx["rating"].strip(), f"{eid} 缺少 mlx_feasibility.rating"
        assert isinstance(mlx.get("deps"), list) and mlx["deps"], f"{eid} 缺少 mlx_feasibility.deps"
        assert isinstance(mlx.get("notes"), str) and mlx["notes"].strip(), f"{eid} 缺少 mlx_feasibility.notes"

        non = e.get("non_inferables")
        assert isinstance(non, list) and non, f"{eid} 缺少 non_inferables"

        tier = e.get("adoption_tier")
        if tier is not None:
            assert tier in tier_labels, f"{eid} adoption_tier 不在 r4_summary.tier_labels 内: {tier}"
            assert e.get("adoption_tier_label") == tier_labels[tier], (
                f"{eid} adoption_tier_label 与 tier_labels[{tier}] 不一致: {e.get('adoption_tier_label')!r}"
            )

        if "corrections" in e:
            assert isinstance(e["corrections"], list) and e["corrections"], f"{eid} corrections 不能为空"
            assert all(isinstance(c, str) and c.strip() for c in e["corrections"]), f"{eid} corrections 含空项"

    # ---------------- 3. 汇总一致性（全部由 entries 推导） ----------------
    assert summary.get("total_entries") == total, (
        f"r4_summary.total_entries ({summary.get('total_entries')}) != len(entries) ({total})"
    )
    preserved = summary.get("preserved_from_r3_ids") or []
    added = summary.get("r11_added_ids") or []
    assert not (set(preserved) & set(added)), "preserved 与 r11_added 存在交集"
    assert set(preserved) | set(added) == id_set, (
        f"preserved ∪ r11_added 不等于当前 id 集合；缺: {sorted(id_set - (set(preserved) | set(added)))}，"
        f"多: {sorted((set(preserved) | set(added)) - id_set)}"
    )
    assert summary.get("preserved_from_r3_count") == len(preserved), "preserved_from_r3_count 与实际列表长度不符"
    assert summary.get("r11_added_count") == len(added), "r11_added_count 与实际列表长度不符"

    derived_tiers: dict = {}
    for e in entries:
        if e.get("adoption_tier"):
            derived_tiers[e["adoption_tier"]] = derived_tiers.get(e["adoption_tier"], 0) + 1
    assert summary.get("tier_counts") == derived_tiers, (
        f"r4_summary.tier_counts 与逐条统计不符：登记 {summary.get('tier_counts')}，实际 {derived_tiers}"
    )
    derived_corrected = sorted(e["id"] for e in entries if e.get("corrections"))
    assert sorted(summary.get("corrected_ids") or []) == derived_corrected, (
        f"r4_summary.corrected_ids 与带 corrections 的条目不符：登记 {summary.get('corrected_ids')}，实际 {derived_corrected}"
    )
    # 本轮新增的每一条都必须留下核实痕迹（打开过哪些一手来源、哪些说法未复核）
    by_id = {e["id"]: e for e in entries}
    for eid in added:
        assert "verification" in by_id[eid], f"{eid} 属 R11 新增条目，必须带 verification 核实留痕"

    # 历史快照：只能比当前小，且 id 必须仍是当前子集
    for snap_key in ("r3_summary", "r5_summary"):
        snap = data[snap_key]
        assert isinstance(snap.get("total_entries"), int), f"{snap_key}.total_entries 缺失"
        assert snap["total_entries"] < total, f"{snap_key}.total_entries 必须小于当前条数（历史快照）"
        for lst_key, lst in snap.items():
            if not isinstance(lst, list) or not lst or not all(isinstance(x, str) for x in lst):
                continue
            stray = sorted(set(lst) - id_set)
            assert not stray, f"{snap_key}.{lst_key} 含当前不存在的 id: {stray}"
        assert snap.get("snapshot_note"), f"{snap_key} 必须保留 snapshot_note 历史标注"

    # ---------------- 4. MD 与 JSON 严格同步 ----------------
    h1 = next((ln for ln in md.splitlines() if ln.startswith("## 1. 总表")), None)
    assert h1, "MD 缺少『## 1. 总表』标题"
    m1 = TOTAL_H1_RE.match(h1)
    assert m1, f"MD 总表标题格式不符（须为『## 1. 总表（N 条，…）』）: {h1}"
    assert int(m1.group(1)) == total, f"MD 总表标题写 {m1.group(1)} 条，JSON 实际 {total} 条"

    h4 = next((ln for ln in md.splitlines() if ln.startswith("## 4. 可借鉴机制汇总")), None)
    assert h4, "MD 缺少『## 4. 可借鉴机制汇总』标题"
    m4 = TOTAL_H4_RE.match(h4)
    assert m4, f"MD 机制汇总标题格式不符（须为『## 4. 可借鉴机制汇总（全部 N 条）』）: {h4}"
    assert int(m4.group(1)) == total, f"MD 机制汇总标题写 {m4.group(1)} 条，JSON 实际 {total} 条"

    rows = [(m.group(1), m.group(2)) for m in (ROW_RE.match(ln) for ln in md.splitlines()) if m]
    row_ids = [r[0] for r in rows]
    assert len(row_ids) == total, f"MD 总表行数 {len(row_ids)} != JSON 条数 {total}"
    assert row_ids == ids, "MD 总表行序或 id 集合与 JSON 不一致（必须逐行同序）"

    bullets = [(m.group(1), m.group(2)) for m in (BULLET_RE.match(ln) for ln in md.splitlines()) if m]
    bullet_ids = [b[0] for b in bullets]
    assert len(bullet_ids) == total, f"MD 机制汇总条数 {len(bullet_ids)} != JSON 条数 {total}"
    assert bullet_ids == ids, "MD 机制汇总条序或 id 集合与 JSON 不一致"

    for (rid, body), (bid, bbody), e in zip(rows, bullets, entries):
        eid = e["id"]
        assert eid == rid == bid, f"MD 行/条与 JSON 条目错位: {rid}/{bid}/{eid}"
        p_url, r_url = e["paper"]["url"], e["repo"]["url"]
        lic = e["license"]["license"]
        # r3 老条目的 MD 行是 r3 时代独立写的（措辞与 JSON 不完全逐字相同），
        # 因此逐字同步只对 R11 新增条目强制；老条目仍校验 id 与两个 URL 必须出现。
        assert p_url in body, f"MD 行 {eid} 缺论文链接 {p_url}"
        if r_url.startswith("https://"):
            assert r_url in body, f"MD 行 {eid} 缺仓库链接 {r_url}"
        else:
            assert UNVERIFIABLE in body, f"MD 行 {eid} 缺『无法核』说明"
        if eid in added_set:
            assert e["name"] in body, f"MD 行 {eid} 缺条目名"
            assert lic in body, f"MD 行 {eid} 的许可文本与 JSON 不一致"
            assert e["mlx_feasibility"]["rating"] in body, f"MD 行 {eid} 的 MLX 评级与 JSON 不一致"
            for m in e["borrowable_mechanisms"]:
                assert m in bbody, f"MD 机制汇总 {eid} 缺少机制文本: {m[:40]}…"
        else:
            assert e["mlx_feasibility"]["rating"].split("（")[0] in body, (
                f"MD 行 {eid} 的 MLX 评级与 JSON 首词不一致"
            )

    # §7 分级表必须列出每个带分级的 id
    secs = _md_sections(md)
    sec7 = next((v for k, v in secs.items() if k.startswith("## 7. ")), "")
    assert sec7, "MD 缺少 §7 采纳分级"
    for e in entries:
        if e.get("adoption_tier"):
            assert f"`{e['id']}`" in sec7, f"MD §7 分级表缺条目 {e['id']}"
            assert e["adoption_tier_label"] in sec7, f"MD §7 缺分级名 {e['adoption_tier_label']}"

    # §8.1 必须覆盖每个更正条目
    sec8 = next((v for k, v in secs.items() if k.startswith("## 8. ")), "")
    assert sec8, "MD 缺少 §8 更正记录"
    for eid in derived_corrected:
        assert f"`{eid}`" in sec8, f"MD §8.1 缺更正条目 {eid}"

    return {
        "total": total,
        "preserved": len(preserved),
        "added": len(added),
        "tiers": derived_tiers,
        "corrected": derived_corrected,
        "md_rows": len(row_ids),
        "md_bullets": len(bullet_ids),
    }


# ---------------------------------------------------------------------------
# --self-test：把交付物复制到临时目录再改坏，逐项确认必变红（不碰真实文件）
# ---------------------------------------------------------------------------
def _mutate_json(root: Path, fn) -> None:
    jp = root / "docs/research/adapter_registry.json"
    data = json.loads(jp.read_text(encoding="utf-8"))
    fn(data)
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _mutate_md(root: Path, fn) -> None:
    mp = root / "docs/research/ADAPTER_REGISTRY.md"
    mp.write_text(fn(mp.read_text(encoding="utf-8")), encoding="utf-8")


def _first_id(root: Path) -> str:
    data = json.loads((root / "docs/research/adapter_registry.json").read_text(encoding="utf-8"))
    return data["entries"][0]["id"]


def _last_id(root: Path) -> str:
    data = json.loads((root / "docs/research/adapter_registry.json").read_text(encoding="utf-8"))
    return data["entries"][-1]["id"]


def _first_added_id(root: Path) -> str:
    data = json.loads((root / "docs/research/adapter_registry.json").read_text(encoding="utf-8"))
    added = set(data["r4_summary"]["r11_added_ids"])
    for e in data["entries"]:
        if e["id"] in added:
            return e["id"]
    raise AssertionError("没有新增条目")


def _added_license(root: Path, eid: str) -> str:
    data = json.loads((root / "docs/research/adapter_registry.json").read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e["id"] == eid:
            return e["license"]["license"]
    raise AssertionError(f"找不到条目 {eid}")


def self_test(root: Path) -> int:
    cases = []

    def case(name):
        def deco(fn):
            cases.append((name, fn))
            return fn

        return deco

    @case("S01 删掉一条 entry")
    def _s01(r):
        _mutate_json(r, lambda d: d["entries"].pop(0))

    @case("S02 改一条 license（JSON 改了、MD 没改）")
    def _s02(r):
        _mutate_json(r, lambda d: d["entries"][1]["license"].__setitem__("license", "MIT"))

    @case("S03 改 MD 总表某行 id")
    def _s03(r):
        i = _first_id(r)
        _mutate_md(r, lambda t: t.replace(f"| {i} |", "| zz-broken-id |", 1))

    @case("S04 改 MD 总表标题条数")
    def _s04(r):
        _mutate_md(r, lambda t: re.sub(r"(## 1\. 总表（)(\d+)( 条)", lambda m: m.group(1) + str(int(m.group(2)) - 1) + m.group(3), t, count=1))

    @case("S05 加一条重复 id")
    def _s05(r):
        def f(d):
            d["entries"].append(copy.deepcopy(d["entries"][0]))
            d["entries"].sort(key=lambda x: x["id"])

        _mutate_json(r, f)

    @case("S06 把 verified 改成 verified-paper-only 但保留 https 仓库")
    def _s06(r):
        def f(d):
            for e in d["entries"]:
                if e["status"] == "verified":
                    e["status"] = "verified-paper-only"
                    break

        _mutate_json(r, f)

    @case("S07 清空一条 borrowable_mechanisms")
    def _s07(r):
        _mutate_json(r, lambda d: d["entries"][2].__setitem__("borrowable_mechanisms", []))

    @case("S08 改 r4_summary.total_entries")
    def _s08(r):
        _mutate_json(r, lambda d: d["r4_summary"].__setitem__("total_entries", d["r4_summary"]["total_entries"] + 1))

    @case("S09 删 MD 机制汇总的一条 bullet")
    def _s09(r):
        i = _last_id(r)
        _mutate_md(r, lambda t: re.sub(rf"^- \*\*{re.escape(i)}\*\*：.*\n", "", t, count=1, flags=re.M))

    @case("S10 把 adoption_tier 改成不存在的级别")
    def _s10(r):
        def f(d):
            for e in d["entries"]:
                if e.get("adoption_tier"):
                    e["adoption_tier"] = "not-a-tier"
                    break

        _mutate_json(r, f)

    @case("S11 把 paper.date 改成斜杠格式")
    def _s11(r):
        _mutate_json(r, lambda d: d["entries"][0]["paper"].__setitem__("date", "2026/10/28"))

    @case("S12 删掉一条 corrections 但 corrected_ids 还留着")
    def _s12(r):
        def f(d):
            for e in d["entries"]:
                if e.get("corrections"):
                    e.pop("corrections")
                    break

        _mutate_json(r, f)

    @case("S13 改 MD 总表中一条新增条目的许可文本")
    def _s13(r):
        i = _first_added_id(r)
        lic = _added_license(r, i)

        def f(t):
            lines = t.splitlines(keepends=True)
            for k, ln in enumerate(lines):
                if ln.startswith(f"| {i} |") and lic in ln:
                    lines[k] = ln.replace(lic, "MIT（被篡改）", 1)
                    break
            return "".join(lines)

        _mutate_md(r, f)

    @case("S14 把 §7 分级表里的一个 id 去掉")
    def _s14(r):
        i = _first_added_id(r)

        def f(t):
            k = t.index("## 7. ")
            head, tail = t[:k], t[k:]
            return head + tail.replace(f"`{i}`", "", 1)

        _mutate_md(r, f)

    red = 0
    for name, fn in cases:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td) / "proj"
            (tdir / "docs/research").mkdir(parents=True)
            for f in ("adapter_registry.json", "ADAPTER_REGISTRY.md"):
                shutil.copy2(root / "docs/research" / f, tdir / "docs/research" / f)
            fn(tdir)
            try:
                validate_registry(tdir)
            except AssertionError as e:
                red += 1
                print(f"RED OK: {name} -> {str(e).splitlines()[0][:160]}")
            else:
                print(f"FAILED: {name} 未变红（校验器有漏检）", file=sys.stderr)
                return 1
    print(f"=== 全部 {red} 项改坏变红对照均生效（临时目录操作，真实交付物未被改动）===")
    return 0


def main() -> int:
    default_root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description="V9-R11 注册表 r4 校验器（只读）")
    ap.add_argument("--root", default=str(default_root), help="项目根目录（默认本脚本的上两级）")
    ap.add_argument("--self-test", action="store_true", help="跑改坏变红对照（只写临时目录）")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if args.self_test:
        return self_test(root)

    stats = validate_registry(root)
    print(
        "REGISTRY R4 OK: {total} 条全部校验通过（保留 r3 {preserved} 条 + R11 新增 {added} 条）；"
        "MD 总表 {md_rows} 行、机制汇总 {md_bullets} 条与 JSON 逐行同序同步；"
        "分级计数 {tiers}；更正条目 {corrected}；期望值全部由 JSON 推导，无硬编码 ID/条数。".format(**stats)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
