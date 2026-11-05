#!/usr/bin/env python3
"""生成 F3 的 r2 输入重登记与逐节差异证据（reports/V9-G1/r2/）。

- 只读 G1 r1 登记/证据与 git 历史，不改 r1 任何文件；
- 旧哈希必须能从登记的 git 提交逐字节重建，新哈希必须等于当前树；
- 文档输入在 r2 登记里**不豁免**：消费门要求当前哈希等于 new_sha256；
- 代码输入保持 r1 登记哈希并继续强制核对；
- 逐节比较 ARCHITECTURE_V9 r3→r5 与 V9_RESEARCH_SURVEY，逐节标注 S0 数学影响。

退出码 0 = 全部核对通过并写出登记；任何前提不成立即退 1（不写半成品）。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R1_DIR = ROOT / "reports" / "V9-G1" / "r1-codex-20261016"
R1_REGISTRATION = R1_DIR / "cpu_registration.json"

R1_REGISTRATION_SHA256 = "5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6"
OLD_GIT_COMMIT = "995db72e6c9663083600a5096b1735153d8c0c7b"  # v9 architecture r3 + surveys
NEW_GIT_COMMIT = "2de6caef0820894520271a8943761cc0b3cf8c22"  # HEAD: published baseline

# r1 登记里的四个输入；两个文档已漂移，两个代码输入仍需强制核对。
R1_SOURCE_SHA256 = {
    "ARCHITECTURE_V9.md": "ebaf1c4bcf23ad8fcac7fc9424c1f4c384c912a8535b0dbe37a648cbe977ac91",
    "docs/research/V9_RESEARCH_SURVEY.md": "51f6a984b009d0a0d54884cf938425dee76af9ca91b0c3e8b99377693d378b29",
    "src/ainerzero/environments/gridlab2d.py": "baea7cb605ca26a9e6c4bd5004dd36f3bbcef0888bc80a8c6a65f582359bc395",
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/kernel/motion.py":
        "c21cd8a2950cf668008b836a2522b9ba50c4fb10757a43187207ad46e2b47db1",
}
DOCUMENT_PATHS = ("ARCHITECTURE_V9.md", "docs/research/V9_RESEARCH_SURVEY.md")

# 旧→新之间还存在两个中间修订；登记把链一起写清，消费门只强制"当前=新哈希"。
INTERMEDIATE_REVISIONS = {
    "ARCHITECTURE_V9.md": [
        {
            "label": "r4",
            "sha256": "e69a0e1ce7cb92187961de387fc84d4fb390aab84ed2e4682601f39566521dda",
            "archive": "reports/V9-A1/r5-revision/r4-archive/ARCHITECTURE_V9.r4.md",
            "archive_sha256sums": "reports/V9-A1/r5-revision/r4-archive/SHA256SUMS.txt",
        },
        {
            "label": "r5 预发布候选（ainerzero.V9.A5 r2 交付件，非当前终稿）",
            "sha256": "ea786389bcbab33686544c7fb20b2f54ac2a6a7f56bea60bad8eb3e6b19c634d",
            "archive": "reports/architecture-finalization-20261016/pre-publication/ARCHITECTURE_V9.md",
            "archive_sha256sums": "reports/architecture-finalization-20261016/pre-publication/identities.json",
        },
    ],
    "docs/research/V9_RESEARCH_SURVEY.md": [],
}

# 逐节 S0 数学影响。impact:
#   no_change              与 S0 数学/ G1 实现的公式、容差、接口无关
#   g1_reference_added     新增“以 G1 为准/引用 G1”的表述，不改变 G1 行为
#   outside_g1_scope       落在 G1 之外（学习侧、世界侧、G3/S1/S5 等）
SECTION_ANNOTATIONS = {
    "ARCHITECTURE_V9.md": {
        "TITLE": ("no_change", "文档标题与版本链（r3→r5）；非数学内容。"),
        "0": ("no_change", "研究原则：拆段并新增“最优=比较目标”的口径，非 S0 数学。"),
        "1": ("no_change", "设计决定表重写：对称性表述改为“默认保持重力方向 SE(2)×高度”并区分主动旋转/被动换系；新增持久世界权威、稀疏更新、记忆分层、模型从小起步等决定，均不改 G1 已实现的公式。"),
        "1.1": ("outside_g1_scope", "新增三系统与三平面职责视图（r5 F1 持久世界权威），属世界侧/接口治理。"),
        "2": ("no_change", "结构图：NeuroGeometry 核心标注“含规范与锚点”，残差只作用连续状态量；与 G1 的显式 anchor/gauge 语义一致，无公式变化。"),
        "3": ("no_change", "P0 接口：GeometryCore 增列 adjoint（G1 已实现）、canonicalize 限定为已定义群作用的量、并写明按 §4 约定；新增 UpdateScheduler。G1 geometry 模块的公开接口不改。"),
        "4": ("g1_reference_added", "新增“约定”块直接引用 G1 belief.py：右扰动、Adjoint 只用于左右误差改写、显式锚点/规范，并写死“B2、G3 的实现以 G1 为准”；这是把既有 G1 语义写进架构，不改 G1 公式。式 1、5、6、7 逐字保留，式 2 仅句末标点变化且四条公式片段不变并新增误差界前提注解（与 G1 的条件界声明一致）；式 3、4、8、9、10、11、12、13 的改动属学习侧、世界侧、G3 规范化、RLT 与稀疏更新，超出 G1 范围。"),
        "5": ("no_change", "研究顺序：S0 行补 D-019 总门、“G1 已登记的 CPU 容差与 fixture 不改”、误差界前提与“CPU 工程界不能替代 S1 科学门”；其余为 S1/V0 口径。属流程/门槛措辞，S0 数学不变。"),
        "6": ("no_change", "验收维度表新增稀疏更新/持久身份等行；未改 S0 数学验收项。"),
        "7": ("no_change", "标题去掉日期括注；内容为集成与教师安排，非 S0 数学。"),
        "7.1": ("no_change", "运行模式指向教师/缓存 r2 候选文档，非 S0 数学。"),
        "7.2": ("outside_g1_scope", "教师=带噪声的传感器：教师侧措辞，非 S0 数学。"),
        "7.3": ("outside_g1_scope", "教师清单许可/来源更新，非 S0 数学。"),
        "7.4": ("outside_g1_scope", "数据与监督通道更新，非 S0 数学。"),
        "7.5": ("outside_g1_scope", "成本验收措辞，非 S0 数学。"),
        "7.6": ("outside_g1_scope", "降本手段清单保留，非 S0 数学。"),
        "8": ("outside_g1_scope", "r4 新增 v10 工程验证层入口，非 S0 数学。"),
        "8.1": ("outside_g1_scope", "v10 模块对应，非 S0 数学。"),
        "8.2": ("outside_g1_scope", "v10 接口对应，非 S0 数学。"),
        "8.3": ("outside_g1_scope", "V10-E0–E6 预登记实验，非 S0 数学。"),
        "8.4": ("outside_g1_scope", "v10 成本模型，非 S0 数学。"),
        "8.5": ("outside_g1_scope", "v10 不做事项，非 S0 数学。"),
        "8.6": ("outside_g1_scope", "学习侧信息边界（r5 F2），非 S0 数学。"),
        "9": ("no_change", "r4 关闭表（回应 Codex 审议），流程记录。"),
        "10": ("outside_g1_scope", "v10 吸收与改正，非 S0 数学。"),
        "11": ("g1_reference_added", "r5 关闭表含 C1：以“引用 G1 约定”关闭右扰动协方差表述；确认 G1 为实现权威，无 G1 变更。"),
    },
    "docs/research/V9_RESEARCH_SURVEY.md": {
        "TITLE": ("no_change", "调研标题与日期未改。"),
        "0": ("no_change", "逐字节未改（旧文为新文前缀）。"),
        "1": ("no_change", "空间几何/SE(3) 调研：逐字节未改；S0 数学的直接文献依据不变。"),
        "2": ("no_change", "逐字节未改。"),
        "3": ("no_change", "逐字节未改。"),
        "4": ("no_change", "逐字节未改。"),
        "5": ("no_change", "逐字节未改。"),
        "6": ("no_change", "逐字节未改。"),
        "7": ("no_change", "逐字节未改。"),
        "8": ("no_change", "来源清单正文未改；差异只是新增 §9 前的空行。"),
        "9": ("outside_g1_scope", "新增 r4 勘误（THICK 官方代码、V-JEPA 2.1 论文、通用口径），属文献/来源勘误，不含 S0 数学或 G1 实现变化。"),
    },
}

# 这几句是“S0 数学没变”的可机器核对证据（builder 与 verify 都断言存在）。
S0_MATH_CHECKS = {
    "ARCHITECTURE_V9.md": {
        "g1_authority_sentence": "B2、G3 的实现以 G1 为准，不另作解释",
        "g1_source_reference": "src/ainerzero/v9/geometry/belief.py",
        "g1_tolerance_fixture_unchanged": "G1 已登记的 CPU 容差与 fixture 不改",
        "right_perturbation": "右误差 `X = μ · Exp(ξ_r)`",
        "adjoint_restriction": "不能当作任意换世界坐标系时右误差协方差的变换",
        "explicit_anchor": "规范与锚点",
        "preserved_formula_lines": [
            "1. 相对位姿：`T_AB = T_WA^{-1} T_WB`；旋转在 SO(3)/SO(2) 上合法更新。",
            "5. 等变地图记忆：`M_{t+dt} = g(Δpose) · M_t ⊕ write(o_{t+dt})`，`g` 为 SE(2) 作用。",
            "6. 学习保护：`min L_new(θ)` s.t. `L_old(θ) ≤ L_old(θ_baseline) + ε`（ε、基线在登记时冻结）。",
            "7. 信息增益：`a* = argmax_a I(S; O_next | a)`（近似）。",
            "10. RLT 停帧去重：同一位置的图块若 `‖p_t − p_{t−1}‖_∞ < τ` 就并入上一个 token，并以游程长度编码位置；`τ` 在登记时冻结，报告 token 保留率与精度损失。",
        ],
        "preserved_formula_fragments": [
            "`x = μ ⊕ ξ, ξ ~ N(0, Σ)`",
            "`μ' = μ ⊕ f(u, dt)`",
            "`Σ' = F Σ Fᵀ + Q(dt)`",
            "更新按不变 EKF 形式",
        ],
    },
    "docs/research/V9_RESEARCH_SURVEY.md": {},
}

TOLERATED_SOURCE_DELTA = (
    "src/ainerzero/v9/geometry/README.md",
    "src/ainerzero/v9/geometry/belief.py",
    "src/ainerzero/v9/geometry/gravity.py",
    "src/ainerzero/v9/geometry/pose_graph.py",
)

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)[.、]?\s")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def git_blob(path: str, commit: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-p", f"{commit}:{path}"],
                          capture_output=True)
    if proc.returncode != 0:
        fail(f"git 无法取出 {commit}:{path}: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


def _trim(body: list[str]) -> list[str]:
    while body and not body[-1].strip():
        body.pop()
    return body


def split_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current = {"level": 0, "title": "<preamble>", "key": "TITLE", "body": []}
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            current["body"] = _trim(current["body"])
            sections.append(current)
            title = match.group(2).strip()
            number = NUMBER_RE.match(title)
            current = {"level": len(match.group(1)), "title": title,
                       "key": number.group(1) if number else None, "body": []}
        else:
            current["body"].append(line)
    current["body"] = _trim(current["body"])
    sections.append(current)
    if sections and sections[0]["title"] == "<preamble>" and not sections[0]["body"]:
        sections = sections[1:]
    return sections


def match_sections(old_sections: list[dict], new_sections: list[dict]) -> tuple[list[dict], list[dict]]:
    old_used = set()
    rows: list[dict] = []
    for new in new_sections:
        match_index = None
        if new["key"] is None and new["level"] == 1:
            for index, old in enumerate(old_sections):
                if index not in old_used and old["key"] is None and old["level"] == 1:
                    match_index = index
                    break
        if match_index is None and new["key"] is not None:
            for index, old in enumerate(old_sections):
                if index not in old_used and old["key"] == new["key"]:
                    match_index = index
                    break
        if match_index is None:
            for index, old in enumerate(old_sections):
                if index not in old_used and old["title"] == new["title"]:
                    match_index = index
                    break
        row = {"title": new["title"], "key": new["key"] or "TITLE",
               "level": new["level"], "old_title": None,
               "new_lines": len(new["body"]), "old_lines": 0,
               "changed": True, "renamed": False, "new": match_index is None}
        if match_index is not None:
            old = old_sections[match_index]
            old_used.add(match_index)
            row.update(old_title=old["title"], old_lines=len(old["body"]),
                       changed=old["body"] != new["body"],
                       renamed=old["title"] != new["title"], new=False)
        rows.append(row)
    removed = [{"title": old["title"], "key": old["key"] or "TITLE", "old_lines": len(old["body"])}
               for index, old in enumerate(old_sections) if index not in old_used]
    return rows, removed


def annotation(doc: str, key: str) -> tuple[str, str]:
    table = SECTION_ANNOTATIONS[doc]
    if key not in table:
        fail(f"{doc} 小节 {key!r} 缺少 S0 影响标注；文档结构变了就必须补标注再登记")
    return table[key]


def build_document_entry(doc: str) -> tuple[dict, list[dict], list[dict]]:
    old_bytes = git_blob(doc, OLD_GIT_COMMIT)
    new_bytes = (ROOT / doc).read_bytes()
    old_sha, new_sha = sha256_bytes(old_bytes), sha256_bytes(new_bytes)
    if old_sha != R1_SOURCE_SHA256[doc]:
        fail(f"{doc} 旧哈希不符：git {OLD_GIT_COMMIT} 得 {old_sha}，r1 登记 {R1_SOURCE_SHA256[doc]}")
    head_blob = git_blob(doc, NEW_GIT_COMMIT)
    if sha256_bytes(head_blob) != new_sha:
        fail(f"{doc} 当前工作树与 git {NEW_GIT_COMMIT} 不一致，先确认身份再登记")
    old_sections = split_sections(old_bytes.decode("utf-8"))
    new_sections = split_sections(new_bytes.decode("utf-8"))
    rows, removed = match_sections(old_sections, new_sections)
    for row in rows:
        impact, note = annotation(doc, row["key"])
        row["s0_math_impact"] = impact
        row["s0_math_note"] = note
    # 关键 S0 断言句必须原样存在，否则“S0 数学没变”的结论不成立。
    checks = S0_MATH_CHECKS.get(doc, {})
    for name, needle in checks.items():
        if name in ("preserved_formula_lines", "preserved_formula_fragments"):
            for line in needle:
                if line not in new_bytes.decode("utf-8"):
                    fail(f"{doc} 缺少 r3 数学式片段（S0 数学可能被改了）：{line[:60]}")
            continue
        if needle not in new_bytes.decode("utf-8"):
            fail(f"{doc} 缺少 S0 核对句 {name}: {needle[:60]}")
    entry = {
        "path": doc,
        "old_sha256": old_sha,
        "old_revision_label": {"ARCHITECTURE_V9.md": "r3 内容（文件首行“状态：设计草案 r3”）",
                               "docs/research/V9_RESEARCH_SURVEY.md":
                                   "G1 登记时的 r3 配套调研（2026-10-16）"}[doc],
        "old_provenance": [
            {"kind": "git_blob", "commit": OLD_GIT_COMMIT, "spec": f"{OLD_GIT_COMMIT}:{doc}",
             "note": "与 r1 cpu_registration.json 登记哈希逐字节一致"}
        ],
        "new_sha256": new_sha,
        "new_revision_label": {"ARCHITECTURE_V9.md": "published r5（基线 ID V9-r5-20261016）",
                               "docs/research/V9_RESEARCH_SURVEY.md": "r5 配套调研（仅追加 §9 r4 勘误）"}[doc],
        "new_provenance": [
            {"kind": "git_blob", "commit": NEW_GIT_COMMIT, "spec": f"{NEW_GIT_COMMIT}:{doc}"},
            {"kind": "working_tree", "path": doc},
        ],
        "intermediate_revisions": INTERMEDIATE_REVISIONS[doc],
        "section_diff": {"file": "section_changes.json", "document_key": doc},
        "s0_math_changed": False,
        "s0_math_conclusion": (
            "S0 数学（GeometryCore：位姿/李群、切空间高斯、重力框架、位姿图）的公式、容差、接口均未变。"
            "r5 新增的 §4 约定块显式引用 G1 belief.py 并写明 B2/G3 以 G1 为准；"
            "§5 S0 行写明 G1 登记的 CPU 容差与 fixture 不改。其余改动属世界侧/学习侧/G3/S1/S5 或流程措辞。"
        ),
        "consumer_gate": "当前文件哈希必须等于 new_sha256（文档不豁免）",
    }
    return entry, rows, removed


def build_survey_prefix_check(doc: str) -> dict:
    old_text = git_blob(doc, OLD_GIT_COMMIT).decode("utf-8")
    new_text = (ROOT / doc).read_text(encoding="utf-8")
    if not new_text.startswith(old_text):
        fail(f"{doc} 旧文不是新文前缀（说明 §1–§8 被改动，需要逐节重标 S0 影响）")
    appended = new_text[len(old_text):]
    return {
        "old_text_is_prefix_of_new": True,
        "appended_lines": len(appended.splitlines()),
        "appended_nonempty_lines": sum(1 for line in appended.splitlines() if line.strip()),
        "appended_heading": next((line for line in appended.splitlines() if line.startswith("## ")), None),
    }


def main() -> None:
    if sha256_file(R1_REGISTRATION) != R1_REGISTRATION_SHA256:
        fail("r1 登记文件哈希不是 5aa8199f…，不能重登记")
    r1 = json.loads(R1_REGISTRATION.read_text(encoding="utf-8"))
    for path, sha in R1_SOURCE_SHA256.items():
        if r1["source_sha256"].get(path) != sha:
            fail(f"r1 登记里 {path} 的哈希与预期不一致")

    documents = []
    section_documents = {}
    for doc in DOCUMENT_PATHS:
        entry, rows, removed = build_document_entry(doc)
        documents.append(entry)
        section_documents[doc] = {
            "old_sha256": entry["old_sha256"],
            "new_sha256": entry["new_sha256"],
            "old_git_commit": OLD_GIT_COMMIT,
            "new_git_commit": NEW_GIT_COMMIT,
            "sections": rows,
            "removed_or_renamed": removed,
            "s0_math_changed": False,
            "s0_math_checks": S0_MATH_CHECKS.get(doc, {}),
        }

    survey_reconstruction = build_survey_prefix_check("docs/research/V9_RESEARCH_SURVEY.md")

    # 中间修订与 r4 归档证据必须真实存在且哈希一致。
    for doc, revisions in INTERMEDIATE_REVISIONS.items():
        for revision in revisions:
            archive = ROOT / revision["archive"]
            if not archive.is_file():
                fail(f"中间修订归档缺失：{revision['archive']}")
            if sha256_file(archive) != revision["sha256"]:
                fail(f"中间修订哈希不符：{revision['archive']}")

    code_inputs = {}
    for path, sha in R1_SOURCE_SHA256.items():
        if path in DOCUMENT_PATHS:
            continue
        actual = sha256_file(Path(path)) if Path(path).is_absolute() else sha256_file(ROOT / path)
        if actual != sha:
            fail(f"代码输入已变化，r2 无权重登记代码输入：{path}")
        code_inputs[path] = {"sha256": sha, "status": "unchanged_from_r1_registration_and_enforced"}

    r1_evidence_sha = sha256_file(R1_DIR / "SHA256SUMS.txt")
    registration = {
        "task": "ainerzero.V9.G5",
        "project": "ainerzero",
        "agent": "deepseek-flash-a7k2",
        "created": "2026-10-20",
        "purpose": "G1 r2 小修：把 r1 登记里已漂移的两份文档输入重登记到当前 published r5，并逐节核对 S0 数学未变；代码输入仍按 r1 哈希强制核对。",
        "r1_registration": {
            "path": str(R1_REGISTRATION.relative_to(ROOT)),
            "sha256": R1_REGISTRATION_SHA256,
            "status": "unchanged（r1 登记与全部证据原样保留）",
        },
        "supersedes_scope": "只替代 r1 登记中 ARCHITECTURE_V9.md 与 docs/research/V9_RESEARCH_SURVEY.md 两个文档输入的消费哈希；G1 全部数值行为、容差、fixture 与代码输入不变。",
        "documents": documents,
        "code_inputs": {
            "policy": "仍强制按 r1 登记哈希核对；r2 不重登记、不豁免代码输入。",
            "inputs": code_inputs,
        },
        "consumer_gate": {
            "implementation": "reports/V9-G1/r2/verify_registration_r2.py",
            "document_policy": "对 documents[].path 重算 sha256，必须等于 documents[].new_sha256；不得豁免文档哈希",
            "code_policy": "对 code_inputs.inputs 重算 sha256，必须等于登记的 r1 哈希",
            "r1_evidence_policy": "r1 SHA256SUMS.txt 中 reports/ 下 28 条证据必须全部 OK；src/ 下仅允许 r2 声明的 4 个文件变化",
            "tolerated_r2_source_delta": list(TOLERATED_SOURCE_DELTA),
        },
        "survey_old_text_prefix_check": survey_reconstruction,
        "scope": {
            "cpu_only": True,
            "model_calls": 0, "training_runs": 0, "downloads": 0, "installs": 0, "paid_calls": 0,
            "files_written": ["reports/V9-G1/r2/"],
        },
    }

    section_changes = {
        "task": "ainerzero.V9.G5",
        "old_git_commit": OLD_GIT_COMMIT,
        "new_git_commit": NEW_GIT_COMMIT,
        "documents": section_documents,
        "survey_old_text_prefix_check": survey_reconstruction,
    }

    (HERE / "section_changes.json").write_text(
        json.dumps(section_changes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registration["section_changes_sha256"] = sha256_file(HERE / "section_changes.json")
    (HERE / "input_registration_r2.json").write_text(
        json.dumps(registration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 人类可读的逐节差异表
    lines = ["# G1 r2 输入重登记：ARCHITECTURE_V9 与 V9_RESEARCH_SURVEY 逐节差异", ""]
    lines += ["- 旧身份（r1 登记）：`ARCHITECTURE_V9.md` = `ebaf1c4b…`（r3 内容，git `995db72`）；"
              "`docs/research/V9_RESEARCH_SURVEY.md` = `51f6a984…`（同提交）。",
              "- 新身份（当前 published r5）：`ARCHITECTURE_V9.md` = `0f54a96a…`（git `2de6caef`，"
              "`V9-r5-20261016`）；`V9_RESEARCH_SURVEY.md` = `1dc744ea…`。",
              "- 中间修订：ARCHITECTURE r4 = `e69a0e1c…`（归档于 `reports/V9-A1/r5-revision/r4-archive/`）；"
              "r5 预发布候选 = `ea786389…`（`reports/architecture-finalization-20261016/pre-publication/`）。",
              "- 结论：**S0 数学没有变化**。r5 的 §4 约定块显式引用 G1 `belief.py` 并写明 B2/G3 以 G1 为准；"
              "§5 S0 行写明 G1 登记的 CPU 容差与 fixture 不改。新增/修改内容属世界侧、学习侧、G3/S1/S5 或流程措辞。",
              "- 消费门：文档按**新哈希**强制核对（不豁免），代码输入按 r1 哈希强制核对。",
              ""]
    for doc, data in section_documents.items():
        lines += [f"## {doc}", "",
                  f"- 旧哈希 `{data['old_sha256']}` → 新哈希 `{data['new_sha256']}`",
                  f"- 小节数：旧 {len(data['sections'])} 个匹配 + {len(data['removed_or_renamed'])} 个改名/消失；"
                  f"新 {len(data['sections'])} 个。",
                  "",
                  "| # | 小节（新标题） | 状态 | 行数 旧→新 | S0 数学影响 | 说明 |",
                  "|---|---|---|---|---|---|"]
        for index, row in enumerate(data["sections"], 1):
            if row["new"]:
                status = "新增"
            elif row["renamed"] and row["changed"]:
                status = "改名+改动"
            elif row["renamed"]:
                status = "改名"
            elif row["changed"]:
                status = "改动"
            else:
                status = "相同"
            title = row["title"].replace("|", "\\|")
            note = row["s0_math_note"].replace("|", "\\|")
            lines.append(f"| {index} | {title} | {status} | {row['old_lines']}→{row['new_lines']} | "
                         f"{row['s0_math_impact']} | {note} |")
        if data["removed_or_renamed"]:
            lines += ["", "旧标题中未匹配到新小节（标题被改写）："]
            for row in data["removed_or_renamed"]:
                lines.append(f"- `{row['title']}`（旧 {row['old_lines']} 行）")
        lines.append("")
    survey = section_documents["docs/research/V9_RESEARCH_SURVEY.md"]
    lines += ["## V9_RESEARCH_SURVEY 前缀核对", "",
              f"- 旧文逐字节是新文前缀：`{json.dumps(survey_reconstruction, ensure_ascii=False)}`",
              "- 即 §1–§8 的全部正文未改，唯一新增是 §9「r4 勘误」（13 行）；S0 数学相关 §1 未变。", ""]
    (HERE / "section_diff_r3_r5.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    changed_sections = sum(1 for doc in section_documents.values()
                           for row in doc["sections"] if row["changed"] or row["new"] or row["renamed"])
    print(json.dumps({
        "documents": {doc: {"old": data["old_sha256"][:12], "new": data["new_sha256"][:12],
                            "sections": len(data["sections"]),
                            "changed_or_new_or_renamed": sum(
                                1 for row in data["sections"] if row["changed"] or row["new"] or row["renamed"])}
                      for doc, data in section_documents.items()},
        "changed_sections_total": changed_sections,
        "s0_math_changed": False,
        "r2_registration": "input_registration_r2.json",
        "section_changes": "section_changes.json",
        "section_diff_markdown": "section_diff_r3_r5.md",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
