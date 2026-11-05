#!/usr/bin/env python3
"""r2 消费门：重登记后的输入身份核对（reports/V9-G1/r2/）。

规则（一级裁决 F3）：
- 文档输入**不豁免**：当前文件 sha256 必须等于 r2 登记的 new_sha256；
- 代码输入仍强制核对：必须等于 r1 登记的哈希；
- r1 登记文件与 r1 证据原样保留：r1 SHA256SUMS 中 reports/ 下证据逐条 OK，
  src/ 下只允许 r2 声明的 4 个文件变化（README/belief/gravity/pose_graph）；
- 旧哈希必须能从登记的 git 提交逐字节重建；中间修订归档哈希一致；
- 逐节差异文件与当前文档重新推导的结构一致，且“以 G1 为准”等 S0 核对句存在。

退出码 0 = 全部通过；1 = 任一核对失败（fail-closed）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_R1_REGISTRATION_SHA256 = "5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6"
EXPECTED_R1_SOURCE_SHA256 = {
    "ARCHITECTURE_V9.md": "ebaf1c4bcf23ad8fcac7fc9424c1f4c384c912a8535b0dbe37a648cbe977ac91",
    "docs/research/V9_RESEARCH_SURVEY.md": "51f6a984b009d0a0d54884cf938425dee76af9ca91b0c3e8b99377693d378b29",
    "src/ainerzero/environments/gridlab2d.py": "baea7cb605ca26a9e6c4bd5004dd36f3bbcef0888bc80a8c6a65f582359bc395",
    "/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/kernel/motion.py":
        "c21cd8a2950cf668008b836a2522b9ba50c4fb10757a43187207ad46e2b47db1",
}
DOCUMENT_PATHS = ("ARCHITECTURE_V9.md", "docs/research/V9_RESEARCH_SURVEY.md")
TOLERATED_SOURCE_DELTA = (
    "src/ainerzero/v9/geometry/README.md",
    "src/ainerzero/v9/geometry/belief.py",
    "src/ainerzero/v9/geometry/gravity.py",
    "src/ainerzero/v9/geometry/pose_graph.py",
)
OLD_GIT_COMMIT = "995db72e6c9663083600a5096b1735153d8c0c7b"
NEW_GIT_COMMIT = "2de6caef0820894520271a8943761cc0b3cf8c22"
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)[.、]?\s")


class GateFailure(AssertionError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def check(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def git_blob(root: Path, path: str, commit: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(root), "cat-file", "-p", f"{commit}:{path}"],
                          capture_output=True)
    check(proc.returncode == 0, f"git 取不出 {commit}:{path}")
    return proc.stdout


def split_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current = {"level": 0, "title": "<preamble>", "key": "TITLE", "body": []}
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            while current["body"] and not current["body"][-1].strip():
                current["body"].pop()
            sections.append(current)
            title = match.group(2).strip()
            number = NUMBER_RE.match(title)
            current = {"level": len(match.group(1)), "title": title,
                       "key": number.group(1) if number else None, "body": []}
        else:
            current["body"].append(line)
    while current["body"] and not current["body"][-1].strip():
        current["body"].pop()
    sections.append(current)
    if sections and sections[0]["title"] == "<preamble>" and not sections[0]["body"]:
        sections = sections[1:]
    return sections


def derive_sections(old_text: str, new_text: str) -> tuple[list[dict], list[dict]]:
    old_sections = split_sections(old_text)
    new_sections = split_sections(new_text)
    old_used: set[int] = set()
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
        row = {"key": new["key"] or "TITLE", "title": new["title"],
               "new_lines": len(new["body"]), "old_lines": 0,
               "changed": True, "renamed": False, "new": match_index is None}
        if match_index is not None:
            old = old_sections[match_index]
            old_used.add(match_index)
            row.update(old_title=old["title"], old_lines=len(old["body"]),
                       changed=old["body"] != new["body"],
                       renamed=old["title"] != new["title"], new=False)
        rows.append(row)
    removed = [{"key": old["key"] or "TITLE", "title": old["title"], "old_lines": len(old["body"])}
               for index, old in enumerate(old_sections) if index not in old_used]
    return rows, removed


def load_shasums(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        check(len(parts) == 2, f"r1 SHA256SUMS 行格式异常：{line[:80]}")
        entries[parts[1].strip()] = parts[0]
    return entries


def verify(root: Path, registration_path: Path, section_changes_path: Path) -> dict:
    r1_dir = root / "reports" / "V9-G1" / "r1-codex-20261016"
    r1_registration_path = r1_dir / "cpu_registration.json"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    section_changes = json.loads(section_changes_path.read_text(encoding="utf-8"))
    details: dict = {"documents": {}, "code_inputs": {}, "r1_evidence": {}, "sections": {}}

    # 1) r1 登记与 r1 证据原样保留
    check(sha256_file(r1_registration_path) == EXPECTED_R1_REGISTRATION_SHA256,
          "r1 登记文件被改：sha256 不是 5aa8199f…")
    check(registration["r1_registration"]["sha256"] == EXPECTED_R1_REGISTRATION_SHA256,
          "r2 登记记录的 r1 登记哈希不对")
    r1 = json.loads(r1_registration_path.read_text(encoding="utf-8"))
    r1_sum_path = r1_dir / "SHA256SUMS.txt"
    r1_sums = load_shasums(r1_sum_path)
    evidence_entries = {path: sha for path, sha in r1_sums.items()
                        if path.startswith("reports/V9-G1/r1-codex-20261016/")}
    source_entries = {path: sha for path, sha in r1_sums.items() if path not in evidence_entries}
    check(len(evidence_entries) == 28, f"r1 evidence 条目数应为 28，实际 {len(evidence_entries)}")
    check(len(r1_sums) == 35, f"r1 SHA256SUMS 应有 35 条，实际 {len(r1_sums)}")
    for path, expected in evidence_entries.items():
        check(sha256_file(root / path) == expected, f"r1 证据被改：{path}")
    for path, expected in source_entries.items():
        actual = sha256_file(root / path)
        if path in TOLERATED_SOURCE_DELTA:
            check(actual != expected, f"r2 声明改动的文件实际未变：{path}")
        else:
            check(actual == expected, f"r1 源码快照文件被越权改动：{path}")
    details["r1_evidence"] = {
        "sha256sums_sha256": sha256_file(r1_sum_path),
        "evidence_entries": len(evidence_entries),
        "evidence_entries_ok": len(evidence_entries),
        "source_snapshot_entries": len(source_entries),
        "r2_changed_source_entries": len(TOLERATED_SOURCE_DELTA),
        "unchanged_source_entries": len(source_entries) - len(TOLERATED_SOURCE_DELTA),
    }
    check(r1["source_sha256"] == EXPECTED_R1_SOURCE_SHA256, "r1 登记源码哈希与预期不一致")

    # 2) 文档输入：旧哈希可由 git 重建，当前哈希必须等于 new_sha256（不豁免）
    registered_docs = {doc["path"]: doc for doc in registration["documents"]}
    check(set(registered_docs) == set(DOCUMENT_PATHS), "r2 登记文档集合不是两份文档输入")
    for path in DOCUMENT_PATHS:
        entry = registered_docs[path]
        check(entry["old_sha256"] == EXPECTED_R1_SOURCE_SHA256[path],
              f"{path} 旧哈希与 r1 登记不一致")
        old_blob = git_blob(root, path, OLD_GIT_COMMIT)
        check(sha256_bytes(old_blob) == entry["old_sha256"],
              f"{path} 旧哈希无法从 git {OLD_GIT_COMMIT} 逐字节重建")
        actual = sha256_file(root / path)
        check(actual == entry["new_sha256"],
              f"{path} 当前哈希 {actual} != 登记的 new_sha256 {entry['new_sha256']}（文档不豁免）")
        new_blob = git_blob(root, path, NEW_GIT_COMMIT)
        check(sha256_bytes(new_blob) == entry["new_sha256"],
              f"{path} 当前文件与 git {NEW_GIT_COMMIT} 不一致")
        for revision in entry.get("intermediate_revisions", []):
            archive = root / revision["archive"]
            check(archive.is_file(), f"中间修订归档缺失：{revision['archive']}")
            check(sha256_file(archive) == revision["sha256"],
                  f"中间修订哈希不符：{revision['archive']}")
        details["documents"][path] = {"old_sha256": entry["old_sha256"],
                                      "new_sha256": actual, "enforced": True}

    # 3) 代码输入：仍按 r1 登记哈希强制核对
    code_inputs = registration["code_inputs"]["inputs"]
    expected_code = {path: sha for path, sha in EXPECTED_R1_SOURCE_SHA256.items()
                     if path not in DOCUMENT_PATHS}
    check(set(code_inputs) == set(expected_code), "r2 登记代码输入集合与 r1 四个输入不符")
    for path, expected in expected_code.items():
        target = Path(path) if Path(path).is_absolute() else root / path
        actual = sha256_file(target)
        check(actual == expected, f"代码输入被改：{path}")
        check(code_inputs[path]["sha256"] == expected, f"r2 登记代码输入哈希不对：{path}")
        details["code_inputs"][path] = {"sha256": actual, "unchanged": True, "enforced": True}

    # 4) 逐节差异必须与当前文档重新推导的结构一致
    check(registration["section_changes_sha256"] == sha256_file(section_changes_path),
          "section_changes.json 被改：与 r2 登记记录的哈希不符")
    check(section_changes["old_git_commit"] == OLD_GIT_COMMIT
          and section_changes["new_git_commit"] == NEW_GIT_COMMIT,
          "section_changes 的 git 提交与 r2 登记不一致")
    for path in DOCUMENT_PATHS:
        stored = section_changes["documents"][path]
        old_text = git_blob(root, path, OLD_GIT_COMMIT).decode("utf-8")
        new_text = (root / path).read_text(encoding="utf-8")
        rows, removed = derive_sections(old_text, new_text)
        stored_rows = stored["sections"]
        check(len(rows) == len(stored_rows), f"{path} 小节数变了：现在 {len(rows)} != 登记 {len(stored_rows)}")
        for index, (row, kept) in enumerate(zip(rows, stored_rows), 1):
            for field in ("key", "title", "old_lines", "new_lines", "changed", "renamed", "new"):
                check(row[field] == kept[field],
                      f"{path} 第 {index} 节 {field} 变了：{row[field]!r} != {kept[field]!r}")
            check(kept["s0_math_impact"] in {"no_change", "g1_reference_added", "outside_g1_scope"},
                  f"{path} 第 {index} 节缺少合法 S0 影响标注")
            check(bool(kept["s0_math_note"].strip()), f"{path} 第 {index} 节缺少 S0 影响说明")
        check(removed == stored["removed_or_renamed"], f"{path} 旧小节未匹配列表变了")
        check(stored["s0_math_changed"] is False, f"{path} S0 数学影响登记不是 false")
        # 文档里“S0 数学没变”的可核对句必须仍存在
        for name, needle in stored["s0_math_checks"].items():
            needles = needle if isinstance(needle, list) else [needle]
            for item in needles:
                check(item in new_text, f"{path} 缺少 S0 核对句 {name}：{item[:60]}")
        details["sections"][path] = {"sections": len(rows), "s0_math_changed": False}

    # 5) 调研文档：旧文必须是新文前缀（§1–§8 未改，只追加 §9）
    prefix = section_changes["survey_old_text_prefix_check"]
    survey_path = "docs/research/V9_RESEARCH_SURVEY.md"
    survey_old = git_blob(root, survey_path, OLD_GIT_COMMIT).decode("utf-8")
    survey_new = (root / survey_path).read_text(encoding="utf-8")
    check(survey_new.startswith(survey_old), "调研文档旧文不是新文前缀：§1–§8 被改了")
    appended = survey_new[len(survey_old):]
    check(len(appended.splitlines()) == prefix["appended_lines"],
          "调研文档追加行数与登记不一致")
    details["survey_appended_lines"] = len(appended.splitlines())

    # 6) r2 登记与范围自检
    check(registration["task"] == "ainerzero.V9.G5", "r2 登记的任务 ID 不对")
    check(set(registration["consumer_gate"]["tolerated_r2_source_delta"]) == set(TOLERATED_SOURCE_DELTA),
          "r2 登记声明的源码改动范围不对")
    details["registration_sha256"] = sha256_file(registration_path)
    details["section_changes_sha256"] = sha256_file(section_changes_path)
    return details


def main() -> None:
    parser = argparse.ArgumentParser(description="r2 输入重登记消费门")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--registration", default=None)
    parser.add_argument("--section-changes", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registration_path = Path(args.registration) if args.registration else root / "reports/V9-G1/r2/input_registration_r2.json"
    section_changes_path = (Path(args.section_changes) if args.section_changes
                            else root / "reports/V9-G1/r2/section_changes.json")
    try:
        details = verify(root, registration_path, section_changes_path)
    except GateFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print("PASS: r2 输入重登记核对通过")
    print(f"  r1 登记: {EXPECTED_R1_REGISTRATION_SHA256[:16]}…（未改）")
    for path, data in details["documents"].items():
        print(f"  文档 {path}: 旧 {data['old_sha256'][:12]}… → 新 {data['new_sha256'][:12]}…（强制核对）")
    for path, data in details["code_inputs"].items():
        print(f"  代码 {path}: {data['sha256'][:12]}…（r1 哈希，强制核对）")
    print(f"  r1 证据: {details['r1_evidence']['evidence_entries']}/"
          f"{details['r1_evidence']['evidence_entries']} OK；r1 源码快照允许改动 "
          f"{details['r1_evidence']['r2_changed_source_entries']} 个、其余 "
          f"{details['r1_evidence']['unchanged_source_entries']} 个未变")
    print(f"  逐节差异: ARCHITECTURE_V9 {details['sections']['ARCHITECTURE_V9.md']['sections']} 节、"
          f"SURVEY {details['sections']['docs/research/V9_RESEARCH_SURVEY.md']['sections']} 节；"
          f"追加 {details['survey_appended_lines']} 行；S0 数学未变")
    print(f"  登记件 sha256: registration={details['registration_sha256']} "
          f"section_changes={details['section_changes_sha256']}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"ok": True, **details}, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")


if __name__ == "__main__":
    main()
