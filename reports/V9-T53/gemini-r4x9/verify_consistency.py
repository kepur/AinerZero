#!/usr/bin/env python3
"""Numerical consistency and RESEARCH_LOG verbatim verification for E18."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "verify_consistency.log"

PROPOSAL_PATH = REPO / "reports" / "V9-T28" / "r2" / "proposal.json"
PROPOSAL_SHA_PATH = REPO / "reports" / "V9-T28" / "r2" / "proposal.sha256"
RESEARCH_LOG_PATH = REPO / "RESEARCH_LOG.md"
PREV_SEALED_PATH = REPO / "reports" / "V9-T28" / "r2" / "pre-E18-1694ed30" / "proposal.json"

EXPECTED_PREV_SHA = "1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5"
EXPECTED_CUR_SHA = "31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278"


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    log = []
    log.append("=== Numerical Consistency & Log Verbatim Verification ===")

    cur_bytes = PROPOSAL_PATH.read_bytes()
    cur_sha = sha256_of_bytes(cur_bytes)
    log.append(f"Current proposal.json SHA256: {cur_sha}")
    assert cur_sha == EXPECTED_CUR_SHA, f"Unexpected proposal.json SHA: {cur_sha} vs {EXPECTED_CUR_SHA}"

    declared_sha = PROPOSAL_SHA_PATH.read_text(encoding="utf-8").split()[0]
    log.append(f"Declared proposal.sha256: {declared_sha}")
    assert declared_sha == cur_sha, f"Declared SHA mismatch: {declared_sha} vs {cur_sha}"

    prev_bytes = PREV_SEALED_PATH.read_bytes()
    prev_sha = sha256_of_bytes(prev_bytes)
    log.append(f"Sealed pre-E18 proposal.json SHA256: {prev_sha}")
    assert prev_sha == EXPECTED_PREV_SHA, f"Unexpected sealed pre-E18 SHA: {prev_sha} vs {EXPECTED_PREV_SHA}"

    proposal = json.loads(cur_bytes.decode("utf-8"))
    b = proposal["budget"]
    va = b["view_accounting"]
    wa = b["wall_accounting"]

    # 1. View accounting consistency: 199 + 50 = 249
    log.append("\n1. View Accounting Verification:")
    used_views = va["ledger_views_used_before_run"]
    charge_views = va["charge_per_complete_run"]
    cap_views = va["cumulative_view_cap"]
    after_views = va["ledger_views_after_this_run"]
    scope = va["scope"]

    log.append(f"  ledger_views_used_before_run: {used_views}")
    log.append(f"  charge_per_complete_run: {charge_views}")
    log.append(f"  cumulative_view_cap: {cap_views}")
    log.append(f"  ledger_views_after_this_run: {after_views}")
    log.append(f"  scope: {scope}")

    assert used_views == 199, f"used_views != 199 ({used_views})"
    assert charge_views == 50, f"charge_views != 50 ({charge_views})"
    assert cap_views == 249, f"cap_views != 249 ({cap_views})"
    assert after_views == 249, f"after_views != 249 ({after_views})"
    assert used_views + charge_views == cap_views == after_views == 249
    assert scope == "line_wide_all_da3_runs_in_central_runstore"

    # Forward views per model sum
    models = b["models"]
    model_views_sum = sum(m["forward_views"] for m in models)
    planned_views = b["total_planned_forward_views"]
    log.append(f"  models forward_views sum: {model_views_sum}, total_planned_forward_views: {planned_views}")
    assert model_views_sum == planned_views == charge_views == 50

    # 2. Wall accounting consistency: 1320 + 120 = 1440
    log.append("\n2. Wall Accounting Verification:")
    reserved_s = wa["ledger_reserved_s"]
    approved_run_s = wa["approved_run_wall_budget_seconds"]
    cum_wall_max = b["cumulative_wall_seconds_max"]
    wa_cap_s = wa["cumulative_cap_s"]
    reserved_after_s = wa["ledger_reserved_after_this_run_s"]
    single_run_max = b["single_run_wall_seconds_max"]

    log.append(f"  ledger_reserved_s: {reserved_s}")
    log.append(f"  approved_run_wall_budget_seconds: {approved_run_s}")
    log.append(f"  cumulative_wall_seconds_max: {cum_wall_max}")
    log.append(f"  wall_accounting cumulative_cap_s: {wa_cap_s}")
    log.append(f"  ledger_reserved_after_this_run_s: {reserved_after_s}")
    log.append(f"  single_run_wall_seconds_max: {single_run_max}")

    assert reserved_s == 1320.0, f"reserved_s != 1320.0 ({reserved_s})"
    assert approved_run_s == 120, f"approved_run_s != 120 ({approved_run_s})"
    assert cum_wall_max == 1440.0, f"cum_wall_max != 1440.0 ({cum_wall_max})"
    assert wa_cap_s == 1440.0, f"wa_cap_s != 1440.0 ({wa_cap_s})"
    assert reserved_after_s == 1440.0, f"reserved_after_s != 1440.0 ({reserved_after_s})"
    assert reserved_s + approved_run_s == cum_wall_max == wa_cap_s == reserved_after_s == 1440.0

    # 120 <= single_run_wall_seconds_max
    assert approved_run_s <= single_run_max, f"approved {approved_run_s} > single max {single_run_max}"
    log.append(f"  Check passed: approved_run_wall_budget_seconds ({approved_run_s}) <= single_run_wall_seconds_max ({single_run_max})")

    # 3. Retry and status checks
    log.append("\n3. Execution & Safety Controls:")
    retry_allowed = b["retry_allowed"]
    status = proposal["status"]
    exec_permitted = proposal["execution_permitted"]
    log.append(f"  retry_allowed: {retry_allowed}")
    log.append(f"  status: {status}")
    log.append(f"  execution_permitted: {exec_permitted}")
    assert retry_allowed is False, f"retry_allowed is not False ({retry_allowed})"
    assert status == "proposal_unapproved", f"status != proposal_unapproved ({status})"
    assert exec_permitted is False, f"execution_permitted is not False ({exec_permitted})"

    # 4. E17 history preservation
    log.append("\n4. E17 Historical Numbers Preservation:")
    va_e17 = va["e17_t6_counter_figures"]
    wa_e17 = wa["e17_t6_counter_figures"]
    log.append(f"  view_accounting.e17_t6_counter_figures: {va_e17}")
    log.append(f"  wall_accounting.e17_t6_counter_figures: {wa_e17}")
    assert va_e17 == {"ledger_views_used_before_run": 81, "cumulative_view_cap": 131}
    assert wa_e17 == {"ledger_reserved_s": 1170, "cumulative_cap_s": 1290}

    # Previous revisions history
    prev_revs = proposal["amendment"]["previous_revisions"]
    found_e17 = False
    for r in prev_revs:
        if r.get("sha256") == EXPECTED_PREV_SHA:
            found_e17 = True
            log.append(f"  Found E17 in previous_revisions: {r}")
            break
    assert found_e17, f"Previous revision with SHA {EXPECTED_PREV_SHA} not found in proposal amendment!"

    # 5. RESEARCH_LOG verbatim check
    log.append("\n5. Verbatim and Proposal Text Verification with RESEARCH_LOG.md:")
    log_text = RESEARCH_LOG_PATH.read_text(encoding="utf-8")

    verbatim_amend = proposal["amendment"]["approved_by_user_fifth"]["verbatim"]
    verbatim_va = va["decided_numbers_by_user"]["verbatim"]
    log.append(f"  amendment verbatim: '{verbatim_amend}'")
    log.append(f"  view_accounting verbatim: '{verbatim_va}'")
    assert verbatim_amend == "Whole line, 249/1440"
    assert verbatim_va == "Whole line, 249/1440"

    expected_log_verbatim_quote = "「Whole line, 249/1440」"
    assert expected_log_verbatim_quote in log_text, f"Verbatim quote '{expected_log_verbatim_quote}' not found in RESEARCH_LOG.md!"
    log.append(f"  Found exact verbatim quote '{expected_log_verbatim_quote}' in RESEARCH_LOG.md")

    approved_prop_amend = proposal["amendment"]["approved_by_user_fifth"]["approved_proposal"]
    approved_prop_va = va["decided_numbers_by_user"]["approved_proposal"]
    assert approved_prop_amend == approved_prop_va
    log.append(f"  approved_proposal text:\n    {approved_prop_amend}")

    # Key elements in RESEARCH_LOG
    assert "DA3 配额按全线合计记账" in log_text
    assert "累计视图上限 249（已用 199 + 50）" in log_text
    assert "累计墙钟上限 1440 s（已用 1320 + 120）" in log_text
    assert "单次 120 s，只跑一次，不重试" in log_text
    assert "修掉 sitecustomize 按任务 ID 分账的漏洞" in log_text
    log.append("  All approved proposal items verified in RESEARCH_LOG.md (lines 1500-1506).")

    res_str = "\n".join(log)
    print(res_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(res_str + "\n", encoding="utf-8")
    print("\nVERIFY CONSISTENCY STATUS: PASS")


if __name__ == "__main__":
    main()
