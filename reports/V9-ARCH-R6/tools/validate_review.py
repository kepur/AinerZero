#!/usr/bin/env python3
"""证据核对交付物的验证器（纯 CPU，只读，不写任何文件）。

用法（仓库根目录）：
    python3 reports/V9-ARCH-R6/tools/validate_review.py <claims.json> [--candidate-sha256 <sha>]

它只检查能用机器检查的三件事，查不了「回答得对不对」：
1. 逐字：每条 candidate_quote 必须是候选稿的子串；每条证据的 text 必须等于 file 第 line 行去掉首尾空白后的全文。
2. 完整：每条 claim 的五个回答（subset、metric、partition、status、replicates）都要有 value，
   并且要么附一条逐字证据，要么写明 "not_stated": true（出处没有写）。
3. 覆盖：r6 相对 r5 新增的文字里，每个带小数、百分号或分数的数字，都要落在某条 candidate_quote 里，
   或者列进 not_evidence 并写明理由（例如版本号、门槛的重复出现）。标题行和 r5 原有的文字不算。

任何一项不满足就以非零码退出。复核者交回前自己跑通；一级验收时重跑。

claims.json 的格式：
{
  "candidate_sha256": "...",
  "claims": [
    {
      "id": "任意唯一的名字",
      "candidate_quote": "候选稿里逐字的一句或半句",
      "source": {"file": "reports/…/REPORT.md", "line": 39, "text": "该行逐字全文"},
      "answers": {
        "subset":     {"value": "…", "evidence": {"file": "…", "line": 1, "text": "…"}},
        "metric":     {"value": "…", "evidence": {…}},
        "partition":  {"value": "dev / final / 摸底 / 事后诊断", "evidence": {…}},
        "status":     {"value": "登记的门 / 登记的描述量 / 只报告项 / 诊断", "evidence": {…}},
        "replicates": {"value": "…", "not_stated": true}
      },
      "verdict": "一致" | "候选稿比出处强" | "数字不符",
      "note": "verdict 不是一致时必填：候选稿丢了什么，建议怎么改"
    }
  ],
  "not_evidence": [
    {"line_contains": "该行里一段能唯一定位的文字", "token": "2.1", "reason": "V-JEPA 的版本号"}
  ]
}
文件路径相对仓库根目录；AWZ 的文件写成 ../AnimeWorldZero/…。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
R5 = ROOT / "ARCHITECTURE_V9.md"
CAND = ROOT / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
ANSWER_KEYS = ("subset", "metric", "partition", "status", "replicates")
VERDICTS = ("一致", "候选稿比出处强", "数字不符")
TOKEN = re.compile(
    r"(?<![\d.§vV])[+−-]?\d+\.\d+(?![\d.])%?"   # 小数，可带符号和百分号
    r"|(?<![\d.])\d+%"                          # 整数百分比
    r"|(?<![\d./])\d+/\d+(?![\d/])"             # 分数
)
ARXIV = re.compile(r"^\d{4}\.\d{5}$")


def line_of(path_str: str, n: int) -> str | None:
    p = (ROOT / path_str).resolve()
    if not p.is_file():
        return None
    lines = p.read_text(encoding="utf-8").split("\n")
    return lines[n - 1].strip() if 1 <= n <= len(lines) else None


def check_evidence(tag: str, ev, errors: list[str]) -> None:
    if not isinstance(ev, dict) or not all(k in ev for k in ("file", "line", "text")):
        errors.append(f"{tag}：证据缺 file / line / text")
        return
    actual = line_of(str(ev["file"]), int(ev["line"]))
    if actual is None:
        errors.append(f"{tag}：{ev['file']}:{ev['line']} 不存在")
    elif actual != str(ev["text"]).strip():
        errors.append(f"{tag}：{ev['file']}:{ev['line']} 的原文与 text 不同\n      实际：{actual[:90]}\n      交付：{str(ev['text'])[:90]}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    claims_path = Path(args[0])
    want_sha = args[args.index("--candidate-sha256") + 1] if "--candidate-sha256" in args else None

    cand_bytes = CAND.read_bytes()
    cand_sha = hashlib.sha256(cand_bytes).hexdigest()
    cand = cand_bytes.decode("utf-8")
    data = json.loads(claims_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    declared = data.get("candidate_sha256")
    if declared != cand_sha:
        errors.append(f"claims.json 写的候选稿 sha256 是 {declared}，盘上是 {cand_sha}")
    if want_sha and want_sha != cand_sha:
        errors.append(f"卡面要求的候选稿 sha256 是 {want_sha}，盘上是 {cand_sha}")

    claims = data.get("claims", [])
    ids = [c.get("id") for c in claims]
    if len(set(ids)) != len(ids):
        errors.append("claim 的 id 有重复")

    for c in claims:
        cid = c.get("id", "?")
        quote = c.get("candidate_quote", "")
        if not quote or quote not in cand:
            errors.append(f"[{cid}] candidate_quote 不是候选稿的子串：{quote[:60]}")
        elif "\n" in quote:
            errors.append(f"[{cid}] candidate_quote 不能跨行")
        check_evidence(f"[{cid}] source", c.get("source"), errors)
        answers = c.get("answers", {})
        for k in ANSWER_KEYS:
            a = answers.get(k)
            if not isinstance(a, dict) or not str(a.get("value", "")).strip():
                errors.append(f"[{cid}] 回答 {k} 缺 value")
                continue
            if a.get("not_stated") is True:
                continue
            check_evidence(f"[{cid}] 回答 {k}", a.get("evidence"), errors)
        verdict = c.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"[{cid}] verdict 必须是 {' / '.join(VERDICTS)}")
        elif verdict != "一致" and not str(c.get("note", "")).strip():
            errors.append(f"[{cid}] verdict 不是一致时必须写 note")

    # 覆盖：r6 相对 r5 新增的行
    r5_lines = R5.read_text(encoding="utf-8").split("\n")
    r6_lines = cand.split("\n")
    added = [l[2:] for l in difflib.ndiff(r5_lines, r6_lines) if l.startswith("+ ")]
    quotes = [c.get("candidate_quote", "") for c in claims]
    skips = data.get("not_evidence", [])
    for s in skips:
        if not str(s.get("reason", "")).strip():
            errors.append(f"not_evidence 条目缺 reason：{s}")
    total = covered = skipped = 0
    uncovered: list[str] = []
    r5_long = sorted((l for l in set(r5_lines) if len(l) >= 30), key=len, reverse=True)
    for line in added:
        if line.startswith("#"):
            continue  # 标题里的章节号不是证据
        # 新行如果是「r5 原行 + r6 追加」，只看追加的部分
        scan = line
        for old_line in r5_long:
            stem = old_line[:-2] if old_line.endswith(" |") else old_line
            if line.startswith(stem):
                scan = line[len(stem):]
                break
        for m in TOKEN.finditer(scan):
            tok = m.group(0)
            if ARXIV.match(tok.lstrip("+−-")):
                continue
            total += 1
            if any(q and q in line and tok in q for q in quotes):
                covered += 1
            elif any(s.get("token") == tok and s.get("line_contains") and s["line_contains"] in line for s in skips):
                skipped += 1
            else:
                uncovered.append(f"{tok}  ←  {line.strip()[:70]}")
    for u in uncovered:
        errors.append(f"数字没有被任何 claim 覆盖：{u}")

    by_verdict = {v: sum(1 for c in claims if c.get("verdict") == v) for v in VERDICTS}
    print(f"候选稿 sha256 {cand_sha}")
    print(f"claims {len(claims)} 条：" + "，".join(f"{k} {v}" for k, v in by_verdict.items()))
    print(f"新增行里的数字 {total} 个：claim 覆盖 {covered}，列为非证据 {skipped}，没有覆盖 {len(uncovered)}")
    print(f"错误 {len(errors)} 条")
    for e in errors:
        print("  -", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
