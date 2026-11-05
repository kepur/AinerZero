#!/usr/bin/env python3
"""V9-R5 注册表校验器（2026-10-16）：全部判定用 assert，脚本真实非零退出。

覆盖范围：
1. 完整保留 V9-R1/R3 全部 28 条目及定点断言（THICK TF2+thix、Stable WorldModel 2026-05-20、V-JEPA 2.1、BlenderWorld 评测基准非世界模型、FAR 非商业等）；
2. 校验 V9_FRONTIER_COST_SURVEY.md §7 增补的 14 篇前沿论文（DINO-WM、V-JEPA 2-AC、PLDM、LeJEPA、解析规范化、
   RLT、Theia、REPA、Pushforward、epinet、Titans、Nested Learning、CUT3R、SlotSSMs）；
3. 校验 7 个重点仓库（DA3、map-anything、dinov3、sam2、tapnet、genesis-world、kubric）；
4. 校验 5 项未核清单核实结论（Muon/Moonlight 约 2× 计算效率、tapnet 检查点全量 Apache 2.0、CUT3R 官方代码 CC BY-NC-SA 4.0、
   Kubric Apache-2.0、AM-RADIO 非商业限制）；
5. 校验 MD 与 JSON 51 条条目逐条同步；
6. 校验顶层元数据（revision、r5_summary、r3_summary 历史快照）；
7. 附 --mutate 22 项改坏变红对照（M19–M22 为 R9 四条 MIT 代码许可专属反例，必须由 R9-LIC[*] 专属断言
   捕获，不得靠其他检查顺带变红；设置环境变量 AINER_V9_R9_DISABLE_R9LIC=1 可关闭该守卫用于漏检证明，
   此时 M19–M22 必须不再变红，否则视为他处规则顺带捕获）。

用法：
  python3 reports/V9-R5/validate_registry_r5.py docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md
  python3 reports/V9-R5/validate_registry_r5.py --mutate docs/research/adapter_registry.json docs/research/ADAPTER_REGISTRY.md
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

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

R5_NEW_IDS = [
    "am-radio",
    "canonicalization",
    "cut3r",
    "depth-anything-3",
    "dino-wm",
    "dinov3",
    "epinet",
    "genesis-world",
    "kubric",
    "lejepa",
    "map-anything",
    "muon-moonlight",
    "nested-learning",
    "pldm",
    "pushforward",
    "repa",
    "rlt",
    "sam2",
    "slotssms",
    "tapnet",
    "theia",
    "titans",
    "vjepa2-ac",
]

EXPECTED_51_IDS = sorted(
    R1_IDS + R3_SURVEY_VERIFIED_IDS + R3_SURVEY_UNVERIFIED_NEW_IDS + R3_ADDENDUM_IDS + R5_NEW_IDS
)

# R9（2026-10-17）四条 MIT 代码许可定点守卫：R8 指出缺口——MIT 条目此前没有专属许可断言，
# dino-wm / pldm / pushforward / slotssms 被擅改成其他许可（如 Apache）时可靠其余检查直穿。
# 每条断言以唯一标记 R9-LIC[<id>] 开头，便于 --mutate 期末核确『M19–M22 恰由专属断言捕获』。
# 漏检模式：环境变量 AINER_V9_R9_DISABLE_R9LIC=1 关闭该守卫（仅用于漏检证明，正常跑不设）。
R9_MIT_LICENSE_IDS = {
    "dino-wm": "DINO-WM",
    "pldm": "PLDM",
    "pushforward": "Pushforward",
    "slotssms": "SlotSSMs",
}
R9_LIC_DISABLE_ENV = "AINER_V9_R9_DISABLE_R9LIC"


def _r9lic_guard_disabled() -> bool:
    return os.environ.get(R9_LIC_DISABLE_ENV, "") == "1"


def _assert_r9_mit_licenses(entry_map) -> None:
    for eid, label in R9_MIT_LICENSE_IDS.items():
        value = entry_map[eid].get("license", {}).get("license", "")
        assert "MIT" in value, (
            f"R9-LIC[{eid}] {label} 代码许可登记须为 MIT（当前值：{value}）；许可变更须走许可政策修订流程"
        )

# Paper URLs for verification
EXPECTED_PAPER_URLS = {
    # R3
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
    # R5
    "dino-wm": "https://arxiv.org/abs/2411.04983",
    "vjepa2-ac": "https://arxiv.org/abs/2506.09985",
    "pldm": "https://arxiv.org/abs/2502.14819",
    "lejepa": "https://arxiv.org/abs/2511.08544",
    "canonicalization": "https://arxiv.org/abs/2211.06489",
    "rlt": "https://arxiv.org/abs/2411.05222",
    "theia": "https://arxiv.org/abs/2407.20179",
    "repa": "https://arxiv.org/abs/2410.06940",
    "pushforward": "https://arxiv.org/abs/2202.03376",
    "epinet": "https://arxiv.org/abs/2107.08924",
    "titans": "https://arxiv.org/abs/2501.00663",
    "nested-learning": "https://arxiv.org/abs/2512.24695",
    "cut3r": "https://arxiv.org/abs/2501.12387",
    "slotssms": "https://arxiv.org/abs/2406.12272",
    "depth-anything-3": "https://github.com/ByteDance-Seed/Depth-Anything-3",
    "map-anything": "https://github.com/facebookresearch/map-anything",
    "dinov3": "https://github.com/facebookresearch/dinov3",
    "sam2": "https://arxiv.org/abs/2408.00714",
    "tapnet": "https://arxiv.org/abs/2306.08637",
    "genesis-world": "https://github.com/Genesis-Embodied-AI/genesis-world",
    "kubric": "https://arxiv.org/abs/2203.03570",
    "muon-moonlight": "https://github.com/MoonshotAI/Moonlight",
    "am-radio": "https://arxiv.org/abs/2312.06709",
}

# Expected repo URLs
EXPECTED_REPO_URLS = {
    # R3
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
    # R5
    "dino-wm": "https://github.com/gaoyuezhou/dino_wm",
    "vjepa2-ac": "https://github.com/facebookresearch/vjepa2",
    "pldm": "https://github.com/vladisai/PLDM",
    "lejepa": "https://github.com/rbalestr-lab/lejepa",
    "rlt": "https://github.com/rccchoudhury/rlt",
    "theia": "https://github.com/rai-opensource/theia",
    "repa": "https://github.com/sihyun-yu/REPA",
    "pushforward": "https://github.com/brandstetter-johannes/MP-Neural-PDE-Solvers",
    "epinet": "https://github.com/google-deepmind/enn",
    "cut3r": "https://github.com/CUT3R/CUT3R",
    "slotssms": "https://github.com/JindongJiang/SlotSSMs",
    "depth-anything-3": "https://github.com/ByteDance-Seed/Depth-Anything-3",
    "map-anything": "https://github.com/facebookresearch/map-anything",
    "dinov3": "https://github.com/facebookresearch/dinov3",
    "sam2": "https://github.com/facebookresearch/sam2",
    "tapnet": "https://github.com/google-deepmind/tapnet",
    "genesis-world": "https://github.com/Genesis-Embodied-AI/genesis-world",
    "kubric": "https://github.com/google-research/kubric",
    "muon-moonlight": "https://github.com/MoonshotAI/Moonlight",
    "am-radio": "https://github.com/NVlabs/RADIO",
}

# Paper-only entries whose official code repo is unverified ("无法核")
PAPER_ONLY_IDS = {
    # R3
    "eswm",
    "equivariant-trust-horizons",
    "swap-equivariant-wm",
    "cls",
    "nec",
    "cueva-wei-2018",
    "barrau-bonnabel-2017",
    # R5
    "titans",
    "nested-learning",
    "canonicalization",
}

# Entries that have a repo URL but the repo license is unverified ("无法核") on GitHub
UNVERIFIED_REPO_LICENSE_IDS = {
    "schaeffer-grid-cells",
    "tem",
    "director",
}

LEGACY_SPECIAL_DATES = {
    "thick": "ICLR 2024（spotlight）",
    "cls": "1995-07（Psychological Review 102(3), 419-457）与 2016-07（Trends in Cognitive Sciences 20(7), 512-534）",
    "blenderworld": "2026-10（GitHub pushed_at 2026-10-16）",
}

THICK_PRIMARY = "https://github.com/CognitiveModeling/THICK"
THIX = "https://github.com/CognitiveModeling/thix"
VJEPA21_PAPER = "https://arxiv.org/abs/2603.14482"
VJEPA2_REPO = "https://github.com/facebookresearch/vjepa2"
SWM_PAPER_DATE = "2026-05-20"


def by_id(entries: list) -> dict:
    return {e["id"]: e for e in entries}


def validate_registry(json_path: Path, md_path: Path):
    assert json_path.exists(), f"JSON 文件不存在: {json_path}"
    assert md_path.exists(), f"MD 文件不存在: {md_path}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 顶层结构
    assert "access_date" in data, "缺少 access_date"
    assert data["access_date"] == "2026-10-16", f"access_date 应为 2026-10-16，实际: {data['access_date']}"
    assert "entries" in data, "缺少 entries"
    entries = data["entries"]
    assert len(entries) == 51, f"期望 entries 共 51 项，实际: {len(entries)}"

    actual_ids = [e["id"] for e in entries]
    assert actual_ids == EXPECTED_51_IDS, f"条目 ID 列表或排序不符！\n缺少: {set(EXPECTED_51_IDS) - set(actual_ids)}\n多出: {set(actual_ids) - set(EXPECTED_51_IDS)}"

    assert "revision" in data, "缺少 revision"
    assert f"{len(entries)} 条" in data["revision"], f"revision 必须提及当前条数 ({len(entries)} 条)，实际: {data['revision']}"

    assert "r5_summary" in data, "缺少 r5_summary"
    r5_sum = data["r5_summary"]
    assert isinstance(r5_sum, dict), "r5_summary 须为字典"
    assert r5_sum.get("total_entries") == len(entries), f"r5_summary.total_entries ({r5_sum.get('total_entries')}) 不等于 len(entries) ({len(entries)})"
    r1_pres = r5_sum.get("r1_preserved_ids", [])
    r3_pres = r5_sum.get("r3_preserved_ids", [])
    r5_added = r5_sum.get("r5_added_ids", [])
    assert len(r1_pres) == 8, f"r1_preserved_ids 应为 8，实际 {len(r1_pres)}"
    assert len(r3_pres) == 20, f"r3_preserved_ids 应为 20，实际 {len(r3_pres)}"
    assert len(r5_added) == 23, f"r5_added_ids 应为 23，实际 {len(r5_added)}"
    assert sorted(r1_pres + r3_pres + r5_added) == EXPECTED_51_IDS, "r5_summary 中条目 ID 集合不符"

    assert "r3_summary" in data, "缺少 r3_summary"
    r3_sum = data["r3_summary"]
    assert "snapshot_note" in r3_sum, "r3_summary 缺少 snapshot_note 快照标注"
    assert r3_sum.get("total_entries") == 28, "r3_summary.total_entries 须保留历史 28 条"

    entry_map = by_id(entries)

    # 2. 逐条公共字段校验
    for eid, e in entry_map.items():
        assert "name" in e and e["name"], f"{eid} 缺少 name"
        assert e.get("status") in ("verified", "verified-paper-only"), f"{eid} status 无效: {e.get('status')}"
        assert "2026-10-16" in e.get("access_date", ""), f"{eid} access_date 须包含 2026-10-16: {e.get('access_date')}"
        assert e.get("borrowable_mechanisms") and len(e["borrowable_mechanisms"]) >= 1, f"{eid} 缺少可借鉴机制"
        assert e.get("non_inferables") and len(e["non_inferables"]) >= 1, f"{eid} 缺少不可推断项"

        # paper 校验
        p = e.get("paper", {})
        assert p.get("title"), f"{eid} 缺少 paper.title"
        assert p.get("authors") and len(p["authors"]) >= 1, f"{eid} 缺少 paper.authors"
        assert p.get("url") and p["url"].startswith("http"), f"{eid} paper.url 无效: {p.get('url')}"
        if eid in LEGACY_SPECIAL_DATES:
            assert p.get("date") == LEGACY_SPECIAL_DATES[eid], f"{eid} 特殊日期不符: {p.get('date')}"
        else:
            assert p.get("date") and DATE_RE.match(p["date"]), f"{eid} paper.date 格式无效: {p.get('date')}"

        # repo 与 license 校验
        r = e.get("repo", {})
        lic = e.get("license", {})
        assert "url" in r, f"{eid} 缺少 repo.url"
        assert lic.get("license"), f"{eid} 缺少 license.license"
        assert lic.get("source"), f"{eid} 缺少 license.source"

        if eid in PAPER_ONLY_IDS:
            assert e["status"] == "verified-paper-only", f"{eid} 无官方代码仓库，status 须为 verified-paper-only"
            assert r.get("url", "").startswith("无法核"), f"{eid} 无官方代码仓库，repo.url 须以『无法核』开头"
            assert "无法核" in lic["license"], f"{eid} 无官方代码仓库，license.license 须标明代码许可『无法核』"
            assert any("无法核" in n for n in e["non_inferables"]), f"{eid} non_inferables 须包含『无法核』说明"
        else:
            assert e["status"] == "verified", f"{eid} 有官方代码仓库，status 须为 verified"
            assert r.get("url", "").startswith("https://"), f"{eid} repo.url 须以 https:// 开头: {r.get('url')}"

        if eid in UNVERIFIED_REPO_LICENSE_IDS:
            assert "无法核" in lic["license"], f"{eid} 官方代码仓库无 LICENSE，license.license 须标明『无法核』"
            assert any("无法核" in n for n in e["non_inferables"]), f"{eid} non_inferables 须包含仓库许可『无法核』警告"

        # mlx_feasibility 校验
        mlx = e.get("mlx_feasibility", {})
        assert mlx.get("rating"), f"{eid} 缺少 mlx_feasibility.rating"
        assert "deps" in mlx and isinstance(mlx["deps"], list) and len(mlx["deps"]) >= 1, f"{eid} 缺少 mlx_feasibility.deps"
        assert mlx.get("notes"), f"{eid} 缺少 mlx_feasibility.notes"

    # 3. 继承自 R1/R2/R3 的定点断言
    # 3.1 THICK
    t = entry_map["thick"]
    assert t["repo"]["url"] == THICK_PRIMARY, f"THICK 主仓库须为 {THICK_PRIMARY}"
    thick_repos = [x.get("url") for x in t["repo"].get("repos", [])]
    assert THICK_PRIMARY in thick_repos and THIX in thick_repos, "THICK 须同时列 TF2 与 JAX (thix) 仓库"
    assert "MIT" in t["license"]["license"], "THICK 许可须记 MIT"
    assert any("thix" in n and "未" in n for n in t["non_inferables"]), "须保留 thix 许可未核的不可推断项"

    # 3.2 Stable WorldModel
    s = entry_map["stable-worldmodel"]
    assert s["paper"]["date"].startswith(SWM_PAPER_DATE), f"Stable WorldModel v1 日期须为 {SWM_PAPER_DATE}"

    # 3.3 V-JEPA 2.1
    v = entry_map["vjepa2"]
    assert v["paper"]["url"] == VJEPA21_PAPER, f"V-JEPA 2.1 论文直链须为 {VJEPA21_PAPER}"
    assert v["repo"]["url"] == VJEPA2_REPO, "V-JEPA 2 仓库须为 facebookresearch/vjepa2"
    assert v["repo"].get("release_date") == "2026-03-16", "V-JEPA 2.1 仓库发布日 2026-03-16 须保留"

    # 3.4 FAR
    far_entry = entry_map["far"]
    assert "CC BY-NC 4.0" in far_entry["license"]["license"], "FAR 须标明 sony/far 仓库的 CC BY-NC 4.0 非商业限制"
    assert any("CC BY-NC 4.0" in n for n in far_entry["non_inferables"]), "FAR non_inferables 须警示 CC BY-NC 4.0 非商业限制"

    # 3.5 TEM
    tem_entry = entry_map["tem"]
    tem_repos = [x.get("url") for x in tem_entry["repo"].get("repos", [])]
    assert "https://github.com/djcrw/generalising-structural-knowledge" in tem_repos, "TEM 须含 Cell 论文官方 TF 仓库"
    assert "https://github.com/jbakermans/torch_tem" in tem_repos, "TEM 须含官方 README 指向的 PyTorch 仓库"

    # 3.6 CLS
    cls_entry = entry_map["cls"]
    cls_pids = " ".join(cls_entry["paper"].get("paper_ids", []))
    assert "10.1037/0033-295X.102.3.419" in cls_pids and "10.1016/j.tics.2016.05.004" in cls_pids, "CLS 须同时记录 1995 与 2016 两篇论文 DOI"

    # 3.7 Barrau & Bonnabel 2017
    bb_entry = entry_map["barrau-bonnabel-2017"]
    assert bb_entry["paper"].get("doi_url") == "https://doi.org/10.1109/TAC.2016.2594085", "Barrau & Bonnabel 2017 须记录 IEEE TAC DOI"

    # 3.8 BlenderWorld 严密定点
    bw = entry_map["blenderworld"]
    assert bw.get("role_type") == "evaluation_benchmark_not_world_model", "BlenderWorld role_type 须为 evaluation_benchmark_not_world_model"
    spec = bw.get("benchmark_spec")
    assert isinstance(spec, dict), "BlenderWorld 须含 benchmark_spec 对象"
    assert spec.get("is_world_model") is False, "BlenderWorld is_world_model 须为 False（非世界模型）"
    assert "非世界模型" in bw["name"], "BlenderWorld name 须明写『非世界模型』"
    ts = spec.get("task_scale", {})
    assert ts.get("total_tasks") == 223, f"BlenderWorld 总任务数须为 223，得 {ts.get('total_tasks')}"
    assert ts.get("total_binary_criteria") == 2651, f"BlenderWorld 二元判据总数须为 2651"
    mods = ts.get("by_input_modality", {})
    assert mods == {"text": 78, "image_text": 130, "video_text": 15}, f"BlenderWorld 模态分布不符：{mods}"
    env = spec.get("official_eval_env", {})
    assert env.get("blender") == "Blender 4.2.10", "BlenderWorld 官方评测须注明 Blender 4.2.10"
    assert "Claude Code CLI" in env.get("agent_cli", ""), "BlenderWorld 官方评测须注明 Claude Code CLI"
    assert "付费" in env.get("paid_vlm_api", "") and "VLM" in env.get("paid_vlm_api", ""), "BlenderWorld 官方评测须注明付费 VLM 接口"

    # 4. URL 预言机校验（新旧全量）
    for tag, expected_purl in EXPECTED_PAPER_URLS.items():
        actual_purl = entry_map[tag]["paper"]["url"]
        assert actual_purl == expected_purl, f"{tag} 论文链接不符：{actual_purl} != {expected_purl}"

    for tag, expected_rurl in EXPECTED_REPO_URLS.items():
        actual_rurl = entry_map[tag]["repo"]["url"]
        assert actual_rurl == expected_rurl, f"{tag} 仓库链接不符：{actual_rurl} != {expected_rurl}"

    # 5. R5 核心增补断言
    # 5.1 Depth-Anything-3 逐模型许可
    da3 = entry_map["depth-anything-3"]
    assert "ByteDance-Seed/Depth-Anything-3" in da3["repo"]["url"]
    assert "Apache" in da3["license"]["license"] and "CC BY-NC 4.0" in da3["license"]["license"], "DA3 必须体现 Small/Base Apache 与 Large CC BY-NC 4.0 分级"

    # 5.2 MapAnything 权重许可
    ma = entry_map["map-anything"]
    assert "facebookresearch/map-anything" in ma["repo"]["url"]
    assert "Apache-2.0" in ma["license"]["license"], "MapAnything 必须明确 Apache-2.0"

    # 5.3 DINOv3 自定义许可与限制
    dinov3 = entry_map["dinov3"]
    assert "DINOv3 License" in dinov3["license"]["license"], "DINOv3 必须为 DINOv3 License 自定义许可"
    assert "ITAR" in dinov3["license"]["license"] or "出口管制" in dinov3["license"]["license"], "DINOv3 必须指明出口管制/ITAR 限制"

    # 5.4 SAM 2.1 许可
    sam2 = entry_map["sam2"]
    assert "Apache-2.0" in sam2["license"]["license"], "SAM 2.1 代码与权重必须为 Apache-2.0"

    # 5.5 tapnet 检查点全量 Apache 2.0
    tapnet = entry_map["tapnet"]
    assert "Apache-2.0" in tapnet["license"]["license"] and "全部预训练" in tapnet["license"]["license"], "tapnet 必须明确全部权重为 Apache 2.0"

    # 5.6 Genesis World 硬件与许可
    genesis = entry_map["genesis-world"]
    assert "Apache-2.0" in genesis["license"]["license"]
    assert "Metal" in genesis["mlx_feasibility"]["notes"] or "Metal" in genesis["mlx_feasibility"]["rating"], "Genesis 必须包含 Apple Metal 支持"

    # 5.7 Kubric 许可
    kubric = entry_map["kubric"]
    assert "Apache-2.0" in kubric["license"]["license"], "Kubric 必须明确为 Apache-2.0"

    # 5.8 Muon / Moonlight 效率
    muon = entry_map["muon-moonlight"]
    assert "MoonshotAI/Moonlight" in muon["repo"]["url"]
    assert "MIT" in muon["license"]["license"]
    assert "2×" in " ".join(muon["borrowable_mechanisms"]) or "2 倍" in " ".join(muon["borrowable_mechanisms"]), "Muon/Moonlight 必须明确约 2 倍计算效率结论"

    # 5.9 CUT3R 许可
    cut3r = entry_map["cut3r"]
    assert "CUT3R/CUT3R" in cut3r["repo"]["url"]
    assert "CC BY-NC-SA 4.0" in cut3r["license"]["license"], "CUT3R 必须明确为 CC BY-NC-SA 4.0"

    # 5.10 AM-RADIO 许可
    radio = entry_map["am-radio"]
    assert "NVlabs/RADIO" in radio["repo"]["url"]
    assert "Non-Commercial" in radio["license"]["license"] or "非商业" in radio["license"]["license"], "AM-RADIO 必须明确非商业限制"

    # 5.11 LeJEPA CC BY-NC 4.0
    lejepa = entry_map["lejepa"]
    assert "CC BY-NC 4.0" in lejepa["license"]["license"], "LeJEPA 必须明确为 CC BY-NC 4.0"

    # 5.12 R9 四条 MIT 代码许可定点守卫（漏洞补齐；见顶部 R9_MIT_LICENSE_IDS 说明）
    if not _r9lic_guard_disabled():
        _assert_r9_mit_licenses(entry_map)

    # 6. MD 与 JSON 逐条同步校验
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    assert "51 条" in md_text, "MD 中必须明确 51 条条目记录"
    assert "2026-10-16" in md_text, "MD 中缺少 2026-10-16 访问日期"
    assert THICK_PRIMARY in md_text and THIX in md_text, "MD 须包含 THICK 与 thix 链接"
    assert SWM_PAPER_DATE in md_text, f"MD 须出现 {SWM_PAPER_DATE}"
    assert VJEPA21_PAPER in md_text and "2026-03-16" in md_text, "MD 须出现 V-JEPA 2.1 直链与 2026-03-16"
    assert "https://github.com/jbakermans/torch_tem" in md_text, "MD 须出现 torch_tem"
    assert "https://doi.org/10.1016/j.tics.2016.05.004" in md_text, "MD 须出现 CLS 2016 DOI"
    assert "https://doi.org/10.1109/TAC.2016.2594085" in md_text, "MD 须出现 Barrau 2017 DOI"
    for token in ("223", "2,651", "78", "130", "15", "Blender 4.2.10", "Claude Code"):
        assert token in md_text, f"MD 缺 BlenderWorld 关键规格词 {token}"

    for eid in EXPECTED_51_IDS:
        assert f"| {eid} |" in md_text, f"MD 总表中缺少条目 ID: {eid}"
        assert f"**{eid}**" in md_text, f"MD 机制汇总中缺少条目: {eid}"
        p_url = entry_map[eid]["paper"]["url"]
        assert p_url in md_text, f"MD 缺 {eid} 论文链接: {p_url}"
        r_url = entry_map[eid]["repo"]["url"]
        if r_url.startswith("https://"):
            assert r_url in md_text, f"MD 缺 {eid} 仓库链接: {r_url}"
        else:
            assert "无法核" in md_text, f"MD 缺 {eid} 的『无法核』说明"

    print(f"REGISTRY R5 OK: 全部 {len(entries)} 条目校验通过，MD/JSON 逐条同步，访问日期 2026-10-16；R9-LIC 四条 MIT 代码许可定点通过。")


def mutate_and_test(json_path: Path, md_path: Path):
    """故意改坏受检物，断言每种破坏都必须触发 AssertionError 并变红。"""
    with open(json_path, "r", encoding="utf-8") as f:
        base_data = json.load(f)

    mutations = [
        # 1. 删掉一个条目
        ("M01 删掉一个条目 (dreamerv3)", lambda d: d["entries"].pop(0)),
        # 2. 改坏 access_date
        ("M02 顶层 access_date 篡改为 2025-10-16", lambda d: d.update({"access_date": "2025-10-16"})),
        # 3. 回退 Stable WorldModel 日期为 2026-05-26
        ("M03 回退 Stable WorldModel 日期为 2026-05-26", lambda d: _set_entry(d, "stable-worldmodel", "paper", {"title": "SWM", "authors": ["A"], "date": "2026-05-26", "url": "https://arxiv.org/abs/2605.21800"})),
        # 4. 编造 titans 官方代码仓库 (原本应为 无法核)
        ("M04 编造 titans 官方代码仓库", lambda d: _set_entry(d, "titans", "repo", {"url": "https://github.com/google/titans"})),
        # 5. 篡改 CUT3R CC BY-NC-SA 4.0 为 MIT 许可
        ("M05 篡改 CUT3R 为 MIT 许可", lambda d: _set_entry(d, "cut3r", "license", {"license": "MIT", "source": "fake"})),
        # 6. 抹去 AM-RADIO 的非商业限制
        ("M06 抹去 AM-RADIO 的非商业限制", lambda d: _set_entry(d, "am-radio", "license", {"license": "Apache-2.0", "source": "fake"})),
        # 7. 抹去 DA3 逐模型分级 CC BY-NC 4.0 声明
        ("M07 抹去 DA3 逐模型分级 CC BY-NC 4.0 声明", lambda d: _set_entry(d, "depth-anything-3", "license", {"license": "Apache 2.0", "source": "fake"})),
        # 8. 抹去 DINOv3 自定义许可 / ITAR 限制
        ("M08 抹去 DINOv3 自定义许可警告", lambda d: _set_entry(d, "dinov3", "license", {"license": "Apache-2.0", "source": "fake"})),
        # 9. 抹去 Muon 2 倍计算效率
        ("M09 抹去 Muon 2 倍计算效率", lambda d: _set_entry(d, "muon-moonlight", "borrowable_mechanisms", ["普通优化器"])),
        # 10. 抹去 tapnet 权重 Apache 2.0 结论
        ("M10 抹去 tapnet 权重 Apache 2.0 结论", lambda d: _set_entry(d, "tapnet", "license", {"license": "Apache-2.0 代码，权重未核", "source": "fake"})),
        # 11. 清空一个条目的 borrowable_mechanisms
        ("M11 清空 rlt 的 borrowable_mechanisms", lambda d: _set_entry(d, "rlt", "borrowable_mechanisms", [])),
        # 12. 清空一个条目的 non_inferables
        ("M12 清空 repa 的 non_inferables", lambda d: _set_entry(d, "repa", "non_inferables", [])),
        # 13. 破坏 paper.date 格式 (用斜杠)
        ("M13 破坏 pldm 的 paper.date 格式", lambda d: _set_entry(d, "pldm", "paper", {"title": "PLDM", "authors": ["A"], "date": "2025/02/19", "url": "https://arxiv.org/abs/2502.14819"})),
        # 14. 篡改 BlenderWorld is_world_model 为 True
        ("M14 篡改 BlenderWorld is_world_model 为 True", lambda d: _set_bw_wm(d, True)),
        # 15. 把 LeJEPA 的 CC BY-NC 4.0 篡改为 MIT
        ("M15 把 LeJEPA 的 CC BY-NC 4.0 篡改为 MIT", lambda d: _set_entry(d, "lejepa", "license", {"license": "MIT", "source": "fake"})),
        # 16. 给 canonicalization 编造仓库链接 (原本应为 无法核)
        ("M16 给 canonicalization 编造仓库链接", lambda d: _set_entry(d, "canonicalization", "repo", {"url": "https://github.com/kaba/canonicalization"})),
        # 17. 篡改 r5_summary.total_entries 为 50（与 len(entries)=51 不符）
        ("M17 篡改 r5_summary.total_entries 为 50", lambda d: d["r5_summary"].update({"total_entries": 50})),
        # 18. 篡改 revision 抹去 51 条说明
        ("M18 篡改 revision 抹去 51 条说明", lambda d: d.update({"revision": "r3: 删除了条数说明"})),
        # 19–22 R9 专属反例：四条 MIT 代码许可改回 Apache，必须由 R9-LIC[*] 专属断言捕获
        ("M19 把 DINO-WM 的 MIT 代码许可篡改为 Apache-2.0", lambda d: _set_entry(d, "dino-wm", "license", {"license": "Apache-2.0", "source": "fake"})),
        ("M20 把 PLDM 的 MIT 代码许可篡改为 Apache-2.0", lambda d: _set_entry(d, "pldm", "license", {"license": "Apache-2.0", "source": "fake"})),
        ("M21 把 Pushforward 的 MIT 代码许可篡改为 Apache-2.0", lambda d: _set_entry(d, "pushforward", "license", {"license": "Apache-2.0", "source": "fake"})),
        ("M22 把 SlotSSMs 的 MIT 代码许可篡改为 Apache-2.0", lambda d: _set_entry(d, "slotssms", "license", {"license": "Apache-2.0", "source": "fake"})),
    ]

    R9_MUT_EID_BY_IDX = {19: "dino-wm", 20: "pldm", 21: "pushforward", 22: "slotssms"}
    guard_disabled = _r9lic_guard_disabled()

    red_count = 0
    with tempfile.TemporaryDirectory() as td:
        t_json = Path(td) / "adapter_registry.json"
        for idx, (m_name, m_func) in enumerate(mutations, 1):
            mutated = copy.deepcopy(base_data)
            m_func(mutated)
            with open(t_json, "w", encoding="utf-8") as f:
                json.dump(mutated, f)

            if idx in R9_MUT_EID_BY_IDX and guard_disabled:
                # 漏检模式：R9-LIC 守卫已关，M19–M22 必须不再变红；若仍变红说明他处规则顺带捕获
                try:
                    validate_registry(t_json, md_path)
                except AssertionError as e:
                    print(f"FAILED MUTATION CHECK: {m_name} 守卫关闭时仍变红（他处规则顺带捕获）-> {e}", file=sys.stderr)
                    sys.exit(1)
                print(f"LEAK OK[{idx:02d}]: {m_name} 守卫关闭时未变红（专属守卫漏检确认）")
                continue

            try:
                validate_registry(t_json, md_path)
                print(f"FAILED MUTATION CHECK: {m_name} 未变红！", file=sys.stderr)
                sys.exit(1)
            except AssertionError as e:
                if idx in R9_MUT_EID_BY_IDX:
                    eid = R9_MUT_EID_BY_IDX[idx]
                    marker = f"R9-LIC[{eid}]"
                    if marker not in str(e):
                        print(
                            f"FAILED MUTATION CHECK: {m_name} 未由专属断言 {marker} 捕获（他处规则顺带变红）-> {e}",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                red_count += 1
                print(f"RED OK[{idx:02d}]: {m_name} 捕获预期失败 -> {e}")

    print(f"=== 全部 {red_count} 项改坏变红对照均生效 ===")
    return red_count


def _set_entry(d: dict, eid: str, key: str, val: any):
    for e in d["entries"]:
        if e["id"] == eid:
            e[key] = val
            break


def _set_bw_wm(d: dict, val: bool):
    for e in d["entries"]:
        if e["id"] == "blenderworld":
            e["benchmark_spec"]["is_world_model"] = val
            break


def main():
    if len(sys.argv) < 3:
        print("用法: python3 validate_registry_r5.py [--mutate] <json_file> <md_file>")
        sys.exit(1)

    if sys.argv[1] == "--mutate":
        json_path = Path(sys.argv[2])
        md_path = Path(sys.argv[3])
        mutate_and_test(json_path, md_path)
        sys.exit(0)
    else:
        json_path = Path(sys.argv[1])
        md_path = Path(sys.argv[2])
        validate_registry(json_path, md_path)


if __name__ == "__main__":
    main()
