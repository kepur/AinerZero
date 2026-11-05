"""E17 checker (tier-1 claude): only the allowed subtrees changed vs the sealed 2a984531, numbers add up,
the user's verbatim matches RESEARCH_LOG, and the real runner still loads the proposal (zero model,
zero ledger).  Writes only check_e17.out next to this file."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = REPO / "reports/V9-T28/r2"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "src"))
PREV_SHA = "2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0"
ALLOWED = (("amendment",), ("budget", "view_accounting"), ("budget", "cumulative_wall_seconds_max"),
           ("budget", "wall_accounting"), ("open_items",))
results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def leaves(x, p=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, p + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from leaves(v, p + (i,))
    else:
        yield p, x


prev = json.loads((HERE / "pre-E17-2a984531/proposal.json").read_text(encoding="utf-8"))
cur = json.loads((HERE / "proposal.json").read_text(encoding="utf-8"))
check("封存的上一版 SHA 为 2a984531", sha(HERE / "pre-E17-2a984531/proposal.json") == PREV_SHA)
check("proposal.sha256 与文件一致", (HERE / "proposal.sha256").read_text().split()[0] == sha(HERE / "proposal.json"))
lp, lc = dict(leaves(prev)), dict(leaves(cur))
changed = sorted(k for k in lp.keys() | lc.keys() if lp.get(k, "<MISSING>") != lc.get(k, "<MISSING>"))
outside = [k for k in changed if not any(k[:len(a)] == a for a in ALLOWED)]
check("变化只在 amendment / view_accounting / cumulative_wall_seconds_max / wall_accounting / open_items",
      not outside, f"{len(changed)} changed leaves; outside={outside[:5]}")
b, va, wa = cur["budget"], cur["budget"]["view_accounting"], cur["budget"]["wall_accounting"]
check("视图账：81 + 50 = 131 = 上限", va["ledger_views_used_before_run"] + va["charge_per_complete_run"] == va["cumulative_view_cap"] == 131
      and va["ledger_views_after_this_run"] == 131)
check("每次完整运行记 50 = 两型号前向视图之和", va["charge_per_complete_run"] == b["total_planned_forward_views"] == sum(m["forward_views"] for m in b["models"]) == 50)
check("墙钟账：1170 + 120 = 1290 = 上限", wa["ledger_reserved_s"] + wa["approved_run_wall_budget_seconds"] == b["cumulative_wall_seconds_max"] == wa["cumulative_cap_s"] == 1290)
check("单次 120 s 不超过单次上限", wa["approved_run_wall_budget_seconds"] <= b["single_run_wall_seconds_max"])
check("不重试", b["retry_allowed"] is False)
check("状态仍为 proposal_unapproved / 不可执行", cur["status"] == "proposal_unapproved" and cur["execution_permitted"] is False)
verbatim = cur["amendment"]["approved_by_user_fourth"]["verbatim"]
log_text = (REPO / "RESEARCH_LOG.md").read_text(encoding="utf-8")
check("用户原话与 RESEARCH_LOG 逐字一致（原话与所批提议都在日志里）", verbatim == va["decided_numbers_by_user"]["verbatim"] == "Approve as proposed"
      and f"「{verbatim}」" in log_text and "view cap 131, wall cap 1290 s, 120 s per run" in log_text)
check("上一版登记在 previous_revisions", any(r.get("sha256") == PREV_SHA for r in cur["amendment"]["previous_revisions"]))
check("其余顶层节逐字未变", all(prev[k] == cur[k] for k in prev if k not in ("amendment", "budget", "open_items")))
check("budget 内只动了 view_accounting / cumulative_wall_seconds_max / wall_accounting",
      sorted(k for k in prev["budget"] if prev["budget"][k] != cur["budget"].get(k)) == ["cumulative_wall_seconds_max", "view_accounting", "wall_accounting"])
try:
    from ainerzero.v9.teachers import da3_calibration_runner as R
    plan = R.load_plan(HERE / "proposal.json")
    check("真实 runner 能加载 E17 提案（零模型、零账本）", plan.process_res == 280, f"process_res={plan.process_res}")
except Exception as exc:  # noqa: BLE001
    check("真实 runner 能加载 E17 提案（零模型、零账本）", False, f"{type(exc).__name__}: {exc}")
lines = [f"{'PASS' if ok else 'FAIL'} {name}" + (f"  [{d}]" if d else "") for ok, name, d in results]
lines.append("ALL PASS" if all(ok for ok, _, _ in results) else "SOME FAILED")
(Path(__file__).resolve().parent / "logs/check_e17.out").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
raise SystemExit(0 if all(ok for ok, _, _ in results) else 1)
