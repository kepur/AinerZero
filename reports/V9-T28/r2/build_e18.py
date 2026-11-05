"""E18 (2026-10-28, tier-1 claude, relay.P2.E46): line-wide view/wall accounting decided by the user.

The E17 numbers (81 used / cap 131, 1170 s / cap 1290 s) were read from the ``ainerzero.V9.T6`` counter
only; ``envs/teachers/t6/sitecustomize.py`` had split the central RunStore by DA3_TASK_ID.  The user chose
line-wide accounting: every DA3 run in the central RunStore counts, whatever its ``task`` field.
Seals the reviewed E17 version (1694ed30..., ainerzero.V9.T50) into pre-E18-1694ed30/ and changes ONLY
amendment, budget.view_accounting, budget.cumulative_wall_seconds_max, budget.wall_accounting, open_items.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREV_SHA = "1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5"
SEAL = HERE / "pre-E18-1694ed30"
VERBATIM = "Whole line, 249/1440"
PROPOSAL_TEXT = ("Which counter should the DA3 quota use? | option: DA3 配额按全线合计记账：累计视图上限 249（已用 199 + 50）、"
                 "累计墙钟上限 1440 s（已用 1320 + 120），单次 120 s，只跑一次不重试；并修掉 sitecustomize 按任务 ID 分账的漏洞。")
LEDGER = {"ainerzero.V9.T6": {"views": 81, "active_seconds": 1170.0},
          "ainerzero.V9.T33": {"views": 82, "active_seconds": 140.0},
          "ainerzero.V9.T33.r2": {"views": 36, "active_seconds": 10.0}}
SEALED_FILES = ("proposal.json", "proposal.sha256", "PROTOCOL.md", "AMENDMENT.md", "SHA256SUMS.txt", "diff_r1_r2.json",
                "build_proposal_r2.py", "build_docs_r2.py", "check_r2.py", "check_r2.out", "build_e17.py", "check_e17.py",
                "check_e17.out")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    assert sha(HERE / "proposal.json") == PREV_SHA, "proposal.json is not the T50-reviewed E17 version"
    assert not SEAL.exists(), f"{SEAL} already exists; E18 was already built"
    SEAL.mkdir()
    for name in SEALED_FILES:
        shutil.copy2(HERE / name, SEAL / name)
    p = json.loads((HERE / "proposal.json").read_text(encoding="utf-8"))
    a, b = p["amendment"], p["budget"]
    used_v = sum(v["views"] for v in LEDGER.values())
    used_s = sum(v["active_seconds"] for v in LEDGER.values())
    assert (used_v, used_s) == (199, 1320.0)
    a["approved_by_user_fifth"] = {
        "date": "2026-10-28", "verbatim": VERBATIM, "approved_proposal": PROPOSAL_TEXT,
        "where": "一级 claude 会话（relay.P2.E46），回复一级的提问",
        "decisions": ["line-wide accounting: every DA3 run in the central RunStore counts, whatever its task field",
                      "cumulative forward-view cap 249 (199 used + 50)", "cumulative wall cap 1440 s (1320 used + 120)",
                      "this run --wall-budget-seconds 120; exactly one run, no retry, no refund",
                      "fix the sitecustomize task-id rebinding that split the ledger"]}
    a["changes"].append("E18 (2026-10-28, user: line-wide accounting; author claude) view_accounting scope line-wide, "
                        "used 199 / cap 249; cumulative_wall_seconds_max 1440; wall_accounting used 1320 + 120; "
                        "E17's T6-counter figures (81 / 1170) kept as history; nothing else changed")
    a["previous_revisions"].append({"kept_at": "reports/V9-T28/r2/pre-E18-1694ed30/",
                                    "note": "after E17; reviewed by V9.T50 (pass); before E18", "sha256": PREV_SHA})
    a["review_history"].append({"review_task": "ainerzero.V9.T50", "reviewed_sha256": PREV_SHA, "reviewer": "gemini-b5r8",
                                "verdict": "pass", "applied": [], "reviewer_says_new_math_review_needed": False})
    a["revision_authors"]["E18"] = "claude"
    va = b["view_accounting"]
    va["scope"] = "line_wide_all_da3_runs_in_central_runstore"
    va["scope_note"] = ("counts every run in artifacts/v9/teachers/benchmark/runs.db whose config model is a DA3 variant, "
                        "whatever its task field; per-task counters had been split by envs/teachers/t6/sitecustomize.py "
                        "rebinding T6_TASK_ID from DA3_TASK_ID")
    va["ledger_by_task_2026_10_28"] = LEDGER
    va["e17_t6_counter_figures"] = {"ledger_views_used_before_run": va["ledger_views_used_before_run"],
                                    "cumulative_view_cap": va["cumulative_view_cap"]}
    va["ledger_views_used_before_run"] = used_v
    va["cumulative_view_cap"] = used_v + va["charge_per_complete_run"]
    va["ledger_views_after_this_run"] = used_v + va["charge_per_complete_run"]
    va["decided_numbers_by_user"] = {"date": "2026-10-28", "verbatim": VERBATIM, "approved_proposal": PROPOSAL_TEXT,
                                     "where": "一级 claude 会话（relay.P2.E46），回复一级的提问",
                                     "supersedes": "E17 numbers (Approve as proposed: cap 131 / 1290 s on the T6 counter)"}
    va["ledger_mechanism"] = va["ledger_mechanism"].replace("the 131 override", "the 249 override")
    wa = b["wall_accounting"]
    wa["e17_t6_counter_figures"] = {"ledger_reserved_s": wa["ledger_reserved_s"], "cumulative_cap_s": wa["cumulative_cap_s"]}
    wa["ledger_reserved_s"] = used_s
    wa["cumulative_cap_s"] = used_s + wa["approved_run_wall_budget_seconds"]
    wa["ledger_reserved_after_this_run_s"] = wa["cumulative_cap_s"]
    wa["note"] = ("user decided 2026-10-28 (E18): line-wide, cumulative 1440 s (1320 used + 120), this run 120 s, one run, "
                  "no retry; the cumulative cap is derived from this bound proposal (ainerzero.V9.T51)")
    b["cumulative_wall_seconds_max"] = wa["cumulative_cap_s"]
    p["open_items"] = [
        "quota decided by the user on 2026-10-28 (E18): line-wide forward views, cap 249 (199 used + 50), wall cap 1440 s "
        "(1320 used + 120), one run, no retry",
        "code before the run: line-wide ledger query (every DA3 run, whatever its task) and removal of the sitecustomize "
        "task-id rebinding; then the runner default PROPOSAL_PATH -> r2 at registration",
        "independent review: a different-author confirmation of E18 before the lead's immutable SHA registration",
        "after registration: runs.db view override 249 (backup + SHA before/after), --preflight-only, then the single run",
    ]
    text = json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    (HERE / "proposal.json").write_text(text, encoding="utf-8")
    digest = sha(HERE / "proposal.json")
    (HERE / "proposal.sha256").write_text(f"{digest}  proposal.json\n", encoding="utf-8")
    with open(HERE / "AMENDMENT.md", "a", encoding="utf-8") as f:
        f.write("\n## E18（2026-10-28，一级 claude）：用户定按全线合计记账\n\n"
                f"- 用户原话：「{VERBATIM}」（回复一级的提问：{PROPOSAL_TEXT}）\n"
                "- 原因：`envs/teachers/t6/sitecustomize.py` 按 `DA3_TASK_ID` 改写任务 ID，中央台账因此按任务分开累计：T6 81 视 / 1170 s，T33 82 视 / 140 s，T33.r2 36 视 / 10 s。E17 的 81 / 1170 只是 T6 计数器。\n"
                "- 现在全线合计 199 视 / 1320 s；累计视图上限 249，累计墙钟上限 1440 s；单次 120 s；只跑一次。\n"
                f"- 上一版 `{PREV_SHA}`（经 ainerzero.V9.T50 复核通过）封存在 `pre-E18-1694ed30/`。新 SHA256 `{digest}`。\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
