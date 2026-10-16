#!/usr/bin/env python3
"""V9-R3 注册表校验器（r2，2026-10-16）：全部判定用 assert，脚本真实非零退出。

覆盖范围：
1. 保留 V9-R1 r1 / R7 的全部 8 条目及定点断言（THICK TF2+thix、Stable WorldModel 2026-05-20、V-JEPA 2.1 直链与 2026-03-16）；
2. 校验 V9_RESEARCH_SURVEY.md §8 已核/仅标题检索补入条目（gradCSCG 2607.12382、ESWM 2505.13696、FAR 2609.34677、
   Flow Equivariant WM 2601.01075、Schaeffer 2312.03954、seq-JEPA 2505.03176、Equivariant WM Trust Horizons 2606.24946、
   S5 2208.04933、SWAP 2606.19928）；
3. 校验 V9_RESEARCH_SURVEY.md §8 未核清单全部 12 项（CSCG 原文、TEM、CLS、NEC、Banino 2018、Cueva & Wei 2018、
   Plan2Explore、Director、THICK、Solà 2018、Barrau & Bonnabel 2017、Slot Attention），查不到的代码链接或许可必须显式标「无法核」；
4. 校验 9.1 增补 BlenderWorld（评测基准而非世界模型、223 任务 = 78 纯文 + 130 图文 + 15 视频文、2,651 加权二元判据、
   50% 判据 + 50% 八维质量、Linux + Blender 4.2.10 + Claude Code CLI + 付费 VLM 接口、代码与 HF 数据集卡许可均为 MIT）；
5. 校验 MD 与 JSON 逐条同步。

用法：
  python3 reports/V9-R3/validate_registry_r3.py docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md
  python3 reports/V9-R3/validate_registry_r3.py --mutate docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

R1_IDS = [
    "dreamerv3",
    "egnn",
    "h-jepa",
    "lewm",
    "slot-attention",
    "stable-worldmodel",
    "thick",
    "vjepa2",
]

R3_SURVEY_VERIFIED_IDS = [
    "equivariant-trust-horizons",
    "eswm",
    "far",
    "flow-equivariant-wm",
    "gradcscg",
    "s5",
    "schaeffer-grid-cells",
    "seq-jepa",
    "swap-equivariant-wm",
]

R3_SURVEY_UNVERIFIED_NEW_IDS = [
    "banino-2018",
    "barrau-bonnabel-2017",
    "cls",
    "cscg",
    "cueva-wei-2018",
    "director",
    "nec",
    "plan2explore",
    "sola-2018",
    "tem",
]

R3_ADDENDUM_IDS = ["blenderworld"]

EXPECTED_ALL_IDS = sorted(
    R1_IDS + R3_SURVEY_VERIFIED_IDS + R3_SURVEY_UNVERIFIED_NEW_IDS + R3_ADDENDUM_IDS
)

# Paper URL oracle map for R3 added entries
EXPECTED_PAPER_URLS = {
    "gradcscg": "https://arxiv.org/abs/2607.12382",
    "eswm": "https://arxiv.org/abs/2505.13696",
    "far": "https://arxiv.org/abs/2609.34677",
    "flow-equivariant-wm": "https://arxiv.org/abs/2601.01075",
    "schaeffer-grid-cells": "https://arxiv.org/abs/2312.03954",
    "seq-jepa": "https://arxiv.org/abs/2505.03176",
    "equivariant-trust-horizons": "https://arxiv.org/abs/2606.24946",
    "s5": "https://arxiv.org/abs/2208.04933",
    "swap-equivariant-wm": "https://arxiv.org/abs/2606.19928",
    "cscg": "https://doi.org/10.1038/s41467-021-22559-5",
    "tem": "https://doi.org/10.1016/j.cell.2020.10.024",
    "cls": "https://doi.org/10.1037/0033-295X.102.3.419",
    "nec": "https://arxiv.org/abs/1703.01988",
    "banino-2018": "https://doi.org/10.1038/s41586-018-0102-6",
    "cueva-wei-2018": "https://arxiv.org/abs/1803.07770",
    "plan2explore": "https://arxiv.org/abs/2005.05960",
    "director": "https://arxiv.org/abs/2206.04114",
    "sola-2018": "https://arxiv.org/abs/1812.01537",
    "barrau-bonnabel-2017": "https://arxiv.org/abs/1410.1465",
    "blenderworld": "https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf",
}

# Verified repos for R3 entries that have official repos
EXPECTED_REPO_URLS = {
    "gradcscg": "https://github.com/tristanstoeber/gradCSCG",
    "far": "https://github.com/sony/far",
    "flow-equivariant-wm": "https://github.com/hlillemark/flowm",
    "schaeffer-grid-cells": "https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction",
    "seq-jepa": "https://github.com/hafezgh/seq-jepa",
    "s5": "https://github.com/lindermanlab/S5",
    "cscg": "https://github.com/vicariousinc/naturecomm_cscg",
    "tem": "https://github.com/djcrw/generalising-structural-knowledge",
    "banino-2018": "https://github.com/google-deepmind/grid-cells",
    "plan2explore": "https://github.com/ramanans1/plan2explore",
    "director": "https://github.com/danijar/director",
    "sola-2018": "https://github.com/artivis/manif",
    "blenderworld": "https://github.com/QwenLM/BlenderWorld",
}

# Paper-only entries whose official code repo is unverified ("无法核")
PAPER_ONLY_IDS = {
    "eswm",
    "equivariant-trust-horizons",
    "swap-equivariant-wm",
    "cls",
    "nec",
    "cueva-wei-2018",
    "barrau-bonnabel-2017",
}

# Entries that have a repo URL but the repo license is unverified ("无法核") on GitHub (license=null)
UNVERIFIED_REPO_LICENSE_IDS = {
    "schaeffer-grid-cells",
    "tem",
    "director",
}

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
    assert reg.get("access_date") == "2026-10-16", f"顶层 access_date 须为 2026-10-16，得 {reg.get('access_date')}"
    assert DATE_RE.match(reg.get("access_date", "")), "access_date 须匹配 YYYY-MM-DD"

    entries = reg.get("entries")
    assert isinstance(entries, list) and len(entries) == 28, (
        f"须恰 28 条（R1 8 条 + R3 新增 20 条），得 {len(entries) if isinstance(entries, list) else type(entries)}"
    )
    ids = [e.get("id") for e in entries]
    assert len(ids) == len(set(ids)), f"存在重复条目 ID：{ids}"
    assert sorted(ids) == EXPECTED_ALL_IDS, f"条目 ID 集合不符：{sorted(ids)} != {EXPECTED_ALL_IDS}"

    for e in entries:
        tag = e["id"]
        for k in (
            "name",
            "access_date",
            "paper",
            "repo",
            "license",
            "borrowable_mechanisms",
            "mlx_feasibility",
            "non_inferables",
            "status",
        ):
            assert k in e, f"{tag} 缺必填键 {k}"
        assert "2026-10-1" in e["access_date"], f"{tag} access_date 非法：{e['access_date']}"
        p = e["paper"]
        assert p.get("url", "").startswith("https://"), f"{tag} 论文链接须以 https:// 开头"
        assert p.get("title"), f"{tag} 论文标题缺失"
        assert any(y in p.get("date", "") for y in ("1995", "2014", "2016", "2017", "2018", "2020", "2021", "2022", "2023", "2024", "2025", "2026")), (
            f"{tag} 论文须有有效年份/日期：{p.get('date')}"
        )
        assert isinstance(p.get("authors"), list) and len(p["authors"]) >= 1, f"{tag} 须有作者列表"

        r = e["repo"]
        lic = e["license"]
        assert lic.get("license") and lic.get("source"), f"{tag} 许可与许可来源不可为空"
        assert isinstance(e["borrowable_mechanisms"], list) and len(e["borrowable_mechanisms"]) >= 1, (
            f"{tag} 可借鉴机制须 >= 1"
        )
        m = e["mlx_feasibility"]
        assert m.get("rating") and m.get("notes") and isinstance(m.get("deps"), list) and len(m["deps"]) >= 1, (
            f"{tag} MLX 可行性字段（rating/notes/deps）不完整"
        )
        assert isinstance(e["non_inferables"], list) and len(e["non_inferables"]) >= 1, (
            f"{tag} 不可推断项须 >= 1"
        )
        assert e["status"] in ("verified", "verified-paper-only"), f"{tag} 状态非法：{e['status']}"

        # Check status vs repo URL and license rules
        if tag in PAPER_ONLY_IDS:
            assert e["status"] == "verified-paper-only", f"{tag} 无官方代码仓库，status 须为 verified-paper-only"
            assert r.get("url", "").startswith("无法核"), f"{tag} 无官方代码仓库，repo.url 须以『无法核』开头"
            assert "无法核" in lic["license"], f"{tag} 无官方代码仓库，license.license 须标明代码许可『无法核』"
            assert any("无法核" in n for n in e["non_inferables"]), f"{tag} non_inferables 须包含『无法核』说明"
        else:
            assert e["status"] == "verified", f"{tag} 有官方代码仓库，status 须为 verified"
            assert r.get("url", "").startswith("https://"), f"{tag} repo.url 须以 https:// 开头"

        if tag in UNVERIFIED_REPO_LICENSE_IDS:
            assert "无法核" in lic["license"], f"{tag} 官方代码仓库无 LICENSE，license.license 须标明『无法核』"
            assert any("无法核" in n for n in e["non_inferables"]), f"{tag} non_inferables 须包含仓库许可『无法核』警告"

        # MD/JSON synchronization check
        assert f"| {tag} |" in md or f"**{tag}**" in md, f"MD 缺条目 ID {tag}"
        assert p["url"] in md, f"MD 缺 {tag} 论文链接 {p['url']}"
        if r["url"].startswith("https://"):
            assert r["url"] in md, f"MD 缺 {tag} 仓库链接 {r['url']}"
        else:
            assert "无法核" in md, f"MD 缺 {tag} 的『无法核』标记"

    reg_by_id = by_id(entries)

    # --- Preserve R1/R2/R7 assertions on the original 8 entries ---
    t = reg_by_id["thick"]
    assert t["repo"]["url"] == THICK_PRIMARY, f"THICK 主仓库须为 {THICK_PRIMARY}"
    thick_repos = [x.get("url") for x in t["repo"].get("repos", [])]
    assert THICK_PRIMARY in thick_repos and THIX in thick_repos, "THICK 须同时列 TF2 与 JAX (thix) 仓库"
    assert "MIT" in t["license"]["license"], "THICK 许可须记 MIT"
    assert any("thix" in n and "未" in n for n in t["non_inferables"]), "须保留 thix 许可未核的不可推断项"
    assert THICK_PRIMARY in md and THIX in md, "MD 须同时出现 THICK 与 thix 仓库链接"

    s = reg_by_id["stable-worldmodel"]
    assert s["paper"]["date"].startswith(SWM_PAPER_DATE), f"Stable WorldModel v1 日期须为 {SWM_PAPER_DATE}"
    assert SWM_PAPER_DATE in md, f"MD 须出现 {SWM_PAPER_DATE}"

    v = reg_by_id["vjepa2"]
    assert v["paper"]["url"] == VJEPA21_PAPER, f"V-JEPA 2.1 论文直链须为 {VJEPA21_PAPER}"
    assert v["repo"]["url"] == VJEPA2_REPO, "V-JEPA 2 仓库须为 facebookresearch/vjepa2"
    assert v["repo"].get("release_date") == "2026-03-16", "V-JEPA 2.1 仓库发布日 2026-03-16 须保留"
    assert VJEPA21_PAPER in md and "2026-03-16" in md, "MD 须出现 V-JEPA 2.1 直链与 2026-03-16"

    # --- R3 Oracle assertions on newly added entries ---
    for tag, expected_purl in EXPECTED_PAPER_URLS.items():
        actual_purl = reg_by_id[tag]["paper"]["url"]
        assert actual_purl == expected_purl, f"{tag} 论文链接不符：{actual_purl} != {expected_purl}"

    for tag, expected_rurl in EXPECTED_REPO_URLS.items():
        actual_rurl = reg_by_id[tag]["repo"]["url"]
        assert actual_rurl == expected_rurl, f"{tag} 仓库链接不符：{actual_rurl} != {expected_rurl}"

    # Specific check for FAR non-commercial license
    far_entry = reg_by_id["far"]
    assert "CC BY-NC 4.0" in far_entry["license"]["license"], "FAR 须标明 sony/far 仓库的 CC BY-NC 4.0 非商业限制"
    assert any("CC BY-NC 4.0" in n for n in far_entry["non_inferables"]), "FAR non_inferables 须警示 CC BY-NC 4.0 非商业限制"

    # Specific check for TEM two repos and unverified licenses
    tem_entry = reg_by_id["tem"]
    tem_repos = [x.get("url") for x in tem_entry["repo"].get("repos", [])]
    assert "https://github.com/djcrw/generalising-structural-knowledge" in tem_repos, "TEM 须含 Cell 论文官方 TF 仓库"
    assert "https://github.com/jbakermans/torch_tem" in tem_repos, "TEM 须含官方 README 指向的 PyTorch 仓库"
    assert "https://github.com/jbakermans/torch_tem" in md, "MD 须同步出现 jbakermans/torch_tem"

    # Specific check for CLS dual papers (1995 & 2016)
    cls_entry = reg_by_id["cls"]
    cls_pids = " ".join(cls_entry["paper"].get("paper_ids", []))
    assert "10.1037/0033-295X.102.3.419" in cls_pids and "10.1016/j.tics.2016.05.004" in cls_pids, (
        "CLS 须同时记录 1995 与 2016 两篇论文 DOI"
    )
    assert "https://doi.org/10.1016/j.tics.2016.05.004" in md, "MD 须同步出现 CLS 2016 DOI 链接"

    # Specific check for Barrau & Bonnabel 2017 arXiv + IEEE TAC DOI
    bb_entry = reg_by_id["barrau-bonnabel-2017"]
    assert bb_entry["paper"].get("doi_url") == "https://doi.org/10.1109/TAC.2016.2594085", (
        "Barrau & Bonnabel 2017 须记录 IEEE TAC DOI"
    )
    assert "https://doi.org/10.1109/TAC.2016.2594085" in md, "MD 须同步出现 Barrau 2017 DOI 链接"

    # --- 9.1 Addendum: BlenderWorld strict checks ---
    bw = reg_by_id["blenderworld"]
    assert bw.get("role_type") == "evaluation_benchmark_not_world_model", (
        "BlenderWorld role_type 须为 evaluation_benchmark_not_world_model"
    )
    spec = bw.get("benchmark_spec")
    assert isinstance(spec, dict), "BlenderWorld 须含 benchmark_spec 对象"
    assert spec.get("is_world_model") is False, "BlenderWorld is_world_model 须为 False（非世界模型）"
    assert "非世界模型" in bw["name"] and "非世界模型" in md, "BlenderWorld 在 JSON 与 MD 中均须明写『非世界模型』"

    ts = spec.get("task_scale", {})
    assert ts.get("total_tasks") == 223, f"BlenderWorld 总任务数须为 223，得 {ts.get('total_tasks')}"
    assert ts.get("total_binary_criteria") == 2651, f"BlenderWorld 二元判据总数须为 2651，得 {ts.get('total_binary_criteria')}"
    mods = ts.get("by_input_modality", {})
    assert mods == {"text": 78, "image_text": 130, "video_text": 15}, f"BlenderWorld 模态分布不符：{mods}"
    assert sum(mods.values()) == ts["total_tasks"], "BlenderWorld 模态任务数之和须等于 223"

    sc = spec.get("scoring_method", {})
    assert "0.5" in sc.get("final_score_formula", "") and "50%" in sc.get("final_score_formula", ""), (
        "BlenderWorld 计分公式须含 0.5 / 50% 判据 + 50% 八维质量"
    )
    env = spec.get("official_eval_env", {})
    assert "Linux" in env.get("os", ""), "BlenderWorld 官方评测环境须注明 Linux"
    assert env.get("blender") == "Blender 4.2.10", "BlenderWorld 官方评测须注明 Blender 4.2.10"
    assert "Claude Code CLI" in env.get("agent_cli", ""), "BlenderWorld 官方评测须注明 Claude Code CLI"
    assert "付费" in env.get("paid_vlm_api", "") and "VLM" in env.get("paid_vlm_api", ""), (
        "BlenderWorld 官方评测须注明付费 VLM 接口"
    )
    dlic = spec.get("dataset_license", {})
    assert dlic.get("dataset_url") == "https://huggingface.co/datasets/Qwen/BlenderWorld", (
        "BlenderWorld 须记录 HuggingFace 数据集卡 URL"
    )
    assert dlic.get("license") == "MIT", "BlenderWorld HuggingFace 数据集卡许可须为核实后的 MIT"
    assert "https://huggingface.co/datasets/Qwen/BlenderWorld" in md, "MD 须包含 BlenderWorld HF 数据集链接"
    for token in ("223", "2,651", "78", "130", "15", "Blender 4.2.10", "Claude Code"):
        assert token in md, f"MD 缺 BlenderWorld 关键规格词 {token}"

    print(f"REGISTRY R3 OK: {len(entries)} entries verified, access_date={reg['access_date']}")


def make_mutations(reg: dict, md: str) -> list[tuple[str, dict, str]]:
    cases: list[tuple[str, dict, str]] = []

    def clone() -> dict:
        return copy.deepcopy(reg)

    # 1. Remove an R3 entry (28 -> 27)
    r = clone()
    r["entries"] = [e for e in r["entries"] if e["id"] != "gradcscg"]
    cases.append(("M01 删减 gradcscg 条目（28->27）", r, md))

    # 2. Tamper access_date
    r = clone()
    r["access_date"] = "2025-10-16"
    cases.append(("M02 顶层 access_date 篡改为 2025-10-16", r, md))

    # 3. Fabricate a repo link for ESWM (which has no official repo -> must be 无法核)
    r = clone()
    by_id(r["entries"])["eswm"]["repo"]["url"] = "https://github.com/BashivanLab/eswm-fake"
    cases.append(("M03 为无官方代码的 ESWM 编造仓库链接", r, md))

    # 4. Remove "无法核" from TEM code license (fabricating MIT)
    r = clone()
    by_id(r["entries"])["tem"]["license"]["license"] = "MIT（假设，未核实）"
    cases.append(("M04 将 TEM 未声明的代码许可篡改为 MIT（抹去无法核）", r, md))

    # 5. Remove "无法核" from Director code license
    r = clone()
    by_id(r["entries"])["director"]["license"]["license"] = "MIT（由 dreamerv3 外推）"
    cases.append(("M05 将 Director 未声明的代码许可外推为 MIT（抹去无法核）", r, md))

    # 6. Tamper FAR CC BY-NC 4.0 non-commercial license into MIT
    r = clone()
    by_id(r["entries"])["far"]["license"]["license"] = "MIT"
    cases.append(("M06 将 FAR (sony/far) 的 CC BY-NC 4.0 非商业许可篡改为 MIT", r, md))

    # 7. Flip BlenderWorld is_world_model to True
    r = clone()
    by_id(r["entries"])["blenderworld"]["benchmark_spec"]["is_world_model"] = True
    cases.append(("M07 将 BlenderWorld is_world_model 篡改为 True（混淆评测基准与世界模型）", r, md))

    # 8. Tamper BlenderWorld task scale (223 -> 200)
    r = clone()
    by_id(r["entries"])["blenderworld"]["benchmark_spec"]["task_scale"]["total_tasks"] = 200
    cases.append(("M08 篡改 BlenderWorld 任务数 223 -> 200", r, md))

    # 9. Tamper BlenderWorld modality breakdown (78/130/15 -> 80/130/13)
    r = clone()
    by_id(r["entries"])["blenderworld"]["benchmark_spec"]["task_scale"]["by_input_modality"]["text"] = 80
    r["entries"] = r["entries"]
    cases.append(("M09 篡改 BlenderWorld 纯文任务数 78 -> 80", r, md))

    # 10. Tamper BlenderWorld official Blender version (4.2.10 -> 5.2.2)
    r = clone()
    by_id(r["entries"])["blenderworld"]["benchmark_spec"]["official_eval_env"]["blender"] = "Blender 5.2.2"
    cases.append(("M10 篡改 BlenderWorld 官方评测 Blender 版本 4.2.10 -> 5.2.2", r, md))

    # 11. Empty borrowable_mechanisms on seq-jepa
    r = clone()
    by_id(r["entries"])["seq-jepa"]["borrowable_mechanisms"] = []
    cases.append(("M11 清空 seq-jepa 的可借鉴机制", r, md))

    # 12. Empty non_inferables on flow-equivariant-wm
    r = clone()
    by_id(r["entries"])["flow-equivariant-wm"]["non_inferables"] = []
    cases.append(("M12 清空 flow-equivariant-wm 的不可推断项", r, md))

    # 13. Break MD/JSON sync by removing gradCSCG repo URL from MD
    r = clone()
    md_bad1 = md.replace("https://github.com/tristanstoeber/gradCSCG", "（缺失仓库链接）")
    cases.append(("M13 MD 删去 gradCSCG 仓库链接（MD/JSON 失同步）", r, md_bad1))

    # 14. Break MD/JSON sync by removing BlenderWorld HF dataset URL from MD
    r = clone()
    md_bad2 = md.replace("https://huggingface.co/datasets/Qwen/BlenderWorld", "（缺失数据集链接）")
    cases.append(("M14 MD 删去 BlenderWorld HF 数据集链接（MD/JSON 失同步）", r, md_bad2))

    # 15. R1/R2 regression: revert Stable WorldModel v1 date to 2026-05-26
    r = clone()
    by_id(r["entries"])["stable-worldmodel"]["paper"]["date"] = "2026-05-26"
    cases.append(("M15 回退 R2 修正：Stable WorldModel 日期改回 2026-05-26", r, md))

    # 16. R1/R2 regression: remove thix from THICK repos
    r = clone()
    t = by_id(r["entries"])["thick"]
    t["repo"]["repos"] = [x for x in t["repo"]["repos"] if x.get("url") != THIX]
    cases.append(("M16 回退 R2 修正：THICK 删去 thix 仓库", r, md))

    return cases


def mutate(json_path: Path, md_path: Path) -> int:
    reg, md = load(json_path, md_path)
    cases = make_mutations(reg, md)
    tmp = Path(tempfile.mkdtemp(prefix="v9r3-red-"))
    all_red = True
    for i, (name, bad_reg, bad_md) in enumerate(cases, 1):
        case_dir = tmp / f"case{i:02d}"
        case_dir.mkdir()
        bj = case_dir / "adapter_registry.json"
        bm = case_dir / "ADAPTER_REGISTRY.md"
        bj.write_text(json.dumps(bad_reg, ensure_ascii=False, indent=1), encoding="utf-8")
        bm.write_text(bad_md, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(bj), str(bm)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err_line = (proc.stderr.strip() or proc.stdout.strip()).splitlines()[-1]
            print(f"RED OK[{i:02d}] {name}: {err_line}")
        else:
            print(f"RED FAIL[{i:02d}] {name}: 故意改坏后仍通过 (exit 0)")
            all_red = False
    return 3 if all_red else 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["--mutate"]:
        _, json_path, md_path = argv
        return mutate(Path(json_path), Path(md_path))
    json_path, md_path = argv
    reg, md = load(Path(json_path), Path(md_path))
    try:
        validate(reg, md)
    except AssertionError as ex:
        print(f"ASSERTION FAILED: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
