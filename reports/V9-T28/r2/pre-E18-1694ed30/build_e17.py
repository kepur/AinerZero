"""E17 (2026-10-28, tier-1 claude, relay.P2.E46): write the user's approved quota numbers into T28 r2.

Seals the reviewed E16 version (2a984531..., reviewed by ainerzero.V9.T48) into pre-E17-2a984531/,
then changes ONLY amendment, budget.view_accounting, budget.cumulative_wall_seconds_max,
budget.wall_accounting and open_items.  Everything else is byte-for-byte the E16 content.
Refuses to run twice (the sealed directory must not exist yet).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREV_SHA = "2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0"
SEAL = HERE / "pre-E17-2a984531"
VERBATIM = "Approve as proposed"
PROPOSAL_TEXT = ("Approve the DA3 quota: view cap 131, wall cap 1290 s, 120 s per run? | reports/coordination/PENDING-USER-20261028.md §1: 建议：视图上限 131、墙钟上限 1290 s、单次 120 s，只跑一次，不重试")
SEALED_FILES = ("proposal.json", "proposal.sha256", "PROTOCOL.md", "AMENDMENT.md", "SHA256SUMS.txt",
                "diff_r1_r2.json", "build_proposal_r2.py", "build_docs_r2.py", "check_r2.py", "check_r2.out")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    assert sha(HERE / "proposal.json") == PREV_SHA, "proposal.json is not the T48-reviewed E16 version"
    assert not SEAL.exists(), f"{SEAL} already exists; E17 was already built"
    SEAL.mkdir()
    for name in SEALED_FILES:
        shutil.copy2(HERE / name, SEAL / name)
    p = json.loads((HERE / "proposal.json").read_text(encoding="utf-8"))
    a, b = p["amendment"], p["budget"]
    a["approved_by_user_fourth"] = {
        "date": "2026-10-28", "verbatim": VERBATIM, "approved_proposal": PROPOSAL_TEXT,
        "where": "一级 claude 会话（relay.P2.E46），回复一级的提议",
        "decisions": ["cumulative forward-view cap 82 -> 131 (81 used; this run charges 50)",
                      "cumulative wall cap 1200 -> 1290 s (1170 s reserved; this run --wall-budget-seconds 120)",
                      "exactly one run, no retry, no refund on failure"]}
    a["changes"].append("E17 (2026-10-28, user numbers; author claude) budget.view_accounting numbers decided "
                        "(cap 131), budget.cumulative_wall_seconds_max 1290, budget.wall_accounting decided "
                        "(run budget 120 s), open_items updated; nothing else changed")
    a["previous_revisions"].append({"kept_at": "reports/V9-T28/r2/pre-E17-2a984531/",
                                    "note": "after E16; reviewed by V9.T48 (pass); before E17", "sha256": PREV_SHA})
    a["review_history"].append({"review_task": "ainerzero.V9.T48", "reviewed_sha256": PREV_SHA, "reviewer": "gemini-b5r8",
                                "verdict": "pass", "applied": [], "reviewer_says_new_math_review_needed": False})
    a["revision_authors"] = {"E1-E16": "claude-az", "E17": "claude"}
    va = b["view_accounting"]
    va["status"] = "BASIS_AND_NUMBERS_DECIDED"
    va.pop("numbers_pending")
    va["decided_numbers_by_user"] = {"date": "2026-10-28", "verbatim": VERBATIM, "approved_proposal": PROPOSAL_TEXT,
                                     "where": "一级 claude 会话（relay.P2.E46），回复一级的提议"}
    va["cumulative_view_cap"] = 131
    va["ledger_views_used_before_run"] = 81
    va["ledger_views_after_this_run"] = 131
    va["ledger_mechanism"] = ("runs.db metadata view override (as on 2026-10-27, keys t6_views_override_20261027 / "
                              "t35_views_override_20261027 = 82); the lead writes the 131 override only after the "
                              "final r2 SHA is registered, with a backup and SHA before/after")
    b["cumulative_wall_seconds_max"] = 1290
    wa = b["wall_accounting"]
    wa["status"] = "DECIDED"
    wa["cumulative_cap_s"] = 1290
    wa["approved_run_wall_budget_seconds"] = 120
    wa["ledger_reserved_after_this_run_s"] = 1290
    wa["note"] = ("user decided 2026-10-28: cumulative 1290 s, this run 120 s, one run, no retry. The code constant "
                  "benchmark_protocol.T6_MAX_CUMULATIVE_WALL_SECONDS (1200.0) must follow this bound value before the run")
    p["open_items"] = [
        "quota numbers decided by the user on 2026-10-28 (E17): forward views, cap 131 (81 used + 50), wall cap 1290 s "
        "(1170 reserved + 120), one run, no retry",
        "code follow-up before the run: da3_worker.REGISTERED_CALIBRATION_VIEWS 18 -> 50 and the cumulative wall cap "
        "1200 -> 1290, both derived from this bound proposal instead of literals; runner default PROPOSAL_PATH -> r2 "
        "only after the lead's SHA registration",
        "independent review: a different-author confirmation of E17 is needed before the lead's immutable SHA "
        "registration of the final r2 SHA",
        "after registration: runs.db view override 131 (backup + SHA before/after), then --preflight-only (zero "
        "model, zero ledger), then the single run",
    ]
    text = json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    (HERE / "proposal.json").write_text(text, encoding="utf-8")
    digest = sha(HERE / "proposal.json")
    (HERE / "proposal.sha256").write_text(f"{digest}  proposal.json\n", encoding="utf-8")
    with open(HERE / "AMENDMENT.md", "a", encoding="utf-8") as f:
        f.write("\n## E17（2026-10-28，一级 claude）：写入用户批准的配额数字\n\n"
                f"- 用户原话：「{VERBATIM}」（回复一级的提议：{PROPOSAL_TEXT}）\n"
                "- 只动了 `amendment`、`budget.view_accounting`、`budget.cumulative_wall_seconds_max`、`budget.wall_accounting`、`open_items`。\n"
                "- 累计视图上限 131（已用 81 + 本次 50）；累计墙钟上限 1290 s（已预留 1170 + 本次 120）；只跑一次，不重试。\n"
                f"- 上一版 `{PREV_SHA}`（经 ainerzero.V9.T48 复核通过）封存在 `pre-E17-2a984531/`。新 SHA256 `{digest}`。\n"
                "- 仍为 `proposal_unapproved`、`execution_permitted=false`，等不同作者确认 E17 之后，一级才登记 SHA。\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
