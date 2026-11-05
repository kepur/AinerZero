"""V9.P12 independent re-run of the V9.P11 F1 approval cases (C1-C12).

Written by the P12 reviewer (not a P9 author).  Re-implements the P11 case set
against the current frozen preregistration inside /private/tmp copies:

* C1 forged status field (self-consistent SHA + sidecar)
* C2 no approval line at all
* C3 approval line one hex digit off
* C4 approval line for the r1 document
* C5a --research-log pointing at an executor-writable forged log (must exit 3)
* C5b forged APPROVAL.json / .approved side files next to the preregistration
* C6 the positive case: exact line inside the canonical log's registered
  section, RunStore records line/line_number/document SHA/log SHA
* C7 matching line but a swapped dataset_digest (P-3)
* C8-C11 the P-4 negative variants (fenced / blockquote / two lines / other
  section)
* C12 a bound source file drifted (P-2)

The training loop is replaced by a sitecustomize shim (no bound file is
edited); no optimizer step runs, nothing is written to the real tree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
ROOT = Path("/private/tmp/v9p12/f1")
TREE = Path("/private/tmp/v9p12/sandbox")
DRIFT = Path("/private/tmp/v9p12/f1_drift")
SITE = Path("/private/tmp/v9p12/site")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P12" / "harness"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
DATASET_REF = REAL / "artifacts" / "v9" / "s1" / "phase1" / "dataset_ref.json"
OLD_DOC = REAL / "reports" / "V9-P9" / "r1-archive" / "pre_registration.json"
PREFIX = "APPROVED s1-phase1 prereg document_sha256="
SECTION = "## R20261021-P1-stageA-budget：S1 第一阶段训练预算登记（reviewer sandbox）"

SITECUSTOMIZE = '''"""P12 reviewer shim: replace the registered training loop, edit no bound file.

``python -m pkg.mod`` executes the module body as ``__main__`` (runpy), so a
plain import-time patch is discarded.  The shim intercepts the worker entry
itself, imports the module unchanged, replaces ``_train`` and calls
``worker.main()`` with the original argv.  The sandbox source therefore stays
byte-identical to the frozen source binding and the optimizer never runs.
"""
import sys

_ORIG = list(getattr(sys, "orig_argv", sys.argv))
if _ORIG[1:3] == ["-m", "ainerzero.v9.experiments.s1.worker"]:
    from ainerzero.v9.experiments.s1 import worker as _w

    _w._train = lambda *a, **k: {"stub": "p12_reviewer_no_training", "updates": 0}
    raise SystemExit(_w.main(_ORIG[3:]))
'''


def canonical_sha(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_trees() -> None:
    """Sandbox tree (clean) + a drifted copy for the P-2 case."""
    if DRIFT.exists():
        shutil.rmtree(DRIFT)
    subprocess.run(["rsync", "-a", f"{TREE}/src/", f"{DRIFT}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{TREE}/RESEARCH_LOG.md", f"{DRIFT}/RESEARCH_LOG.md"], check=True)
    (DRIFT / "artifacts" / "locks").mkdir(parents=True, exist_ok=True)
    (DRIFT / "artifacts" / "v9" / "s1").mkdir(parents=True, exist_ok=True)
    (DRIFT / "artifacts" / "v9" / "s1" / "datasets").symlink_to(
        REAL / "artifacts" / "v9" / "s1" / "datasets")
    arms = DRIFT / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "arms.py"
    arms.write_text(arms.read_text(encoding="utf-8") + "\n# p12 reviewer drift marker\n",
                    encoding="utf-8")
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    (SITE / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")


def fresh_case(name: str) -> Path:
    case = ROOT / name
    if case.exists():
        shutil.rmtree(case)
    (case / "phase1").mkdir(parents=True)
    shutil.copy2(DOC, case / "phase1" / "pre_registration.json")
    shutil.copy2(DOC.with_suffix(".json.sha256"), case / "phase1" / "pre_registration.json.sha256")
    shutil.copy2(DATASET_REF, case / "phase1" / "dataset_ref.json")
    return case


def write_log(path: Path, *extra: str) -> Path:
    body = "# RESEARCH_LOG copy (p12 reviewer sandbox)\n\n" + SECTION + "\n\n"
    body += "- 预算与资源线：进程 8 GiB、MLX 4 GiB、系统余量 16 GiB、占空比 0.25。\n"
    body += "\n".join(extra) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def reset_canonical_log(tree: Path, *extra: str) -> Path:
    return write_log(tree / "RESEARCH_LOG.md", *extra)


def run_cli(tree: Path, case: Path, log: Path | None, prereg: Path | None = None) -> dict:
    command = [
        PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train",
        "--output-root", str(case / "phase1"),
        "--prereg", str(prereg or (case / "phase1" / "pre_registration.json")),
    ]
    if log is not None:
        command += ["--research-log", str(log)]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": f"{tree / 'src'}:{SITE}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/private/tmp/v9p12",
    }
    proc = subprocess.run(command, cwd=str(tree), capture_output=True, text=True, timeout=600, env=env)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed_stdout": proc.stdout[-2000:]}
    approval = report.get("approval") or {}
    return {
        "exit_code": proc.returncode,
        "stage": report.get("stage") or report.get("refused_stage") or report.get("status"),
        "status": report.get("status"),
        "preregistration_sha256": report.get("preregistration_sha256") or report.get("prereg_sha256"),
        "approval_reasons": approval.get("reasons"),
        "dataset_status": (report.get("dataset") or {}).get("status"),
        "source_binding_status": (report.get("source_binding") or {}).get("status"),
        "run_id": report.get("run_id"),
        "error": report.get("error"),
        "stderr_tail": proc.stderr.strip()[-400:],
    }


def runstore_approval(case: Path, run_id: str | None) -> dict:
    db = case / "phase1" / "control.sqlite3"
    if not db.is_file() or not run_id:
        return {"available": False}
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            return {"available": False, "reason": "run_id not in ledger"}
        snapshot = json.loads(row["config_json"]) if row["config_json"] else {}
        states = [r[0] for r in conn.execute(
            "select to_state from run_transitions where run_id = ? order by id", (run_id,))]
    return {
        "available": True,
        "state": row["state"],
        "approval": snapshot.get("approval"),
        "transitions": states,
        "optimizer_steps": row["optimizer_steps"],
    }


def main() -> int:
    build_trees()
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    digest = canonical_sha(doc)
    old_digest = canonical_sha(json.loads(OLD_DOC.read_text(encoding="utf-8")))
    assert digest == DOC.with_suffix(".json.sha256").read_text().split()[0], "frozen SHA mismatch"
    approval_line = PREFIX + digest
    cases: list[dict] = []

    # C1: status-only forgery with self-consistent SHA and sidecar
    case = fresh_case("C1_forged_status")
    forged = dict(doc, status="approved")
    forged_digest = canonical_sha(forged)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(forged, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{forged_digest}  pre_registration.json\n", encoding="utf-8")
    reset_canonical_log(TREE)
    r = run_cli(TREE, case, None)
    r.update(id="C1", label="只改预登记 status=approved 并重算 SHA/侧车，日志无批准行",
             expectation="refused exit 3", forged_document_sha256=forged_digest,
             self_consistent=(forged_digest == (case / "phase1" / "pre_registration.json.sha256").read_text().split()[0]))
    cases.append(r)

    # C2: no approval line
    case = fresh_case("C2_no_line")
    reset_canonical_log(TREE, "APPROVED s1-phase1 prereg (format without sha)")
    r = run_cli(TREE, case, None)
    r.update(id="C2", label="批准行缺失（只有说明性文字）", expectation="refused exit 3")
    cases.append(r)

    # C3: one hex digit off
    case = fresh_case("C3_one_digit_off")
    broken = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    reset_canonical_log(TREE, PREFIX + broken)
    r = run_cli(TREE, case, None)
    r.update(id="C3", label="批准行 SHA 差一位", expectation="refused exit 3", line_sha=broken)
    cases.append(r)

    # C4: line for the older (r1) document
    case = fresh_case("C4_old_document")
    reset_canonical_log(TREE, PREFIX + old_digest)
    r = run_cli(TREE, case, None)
    r.update(id="C4", label="批准行指向 r1 旧文档", expectation="refused exit 3",
             old_document_sha256=old_digest)
    cases.append(r)

    # C5a: relocated --research-log with the exact line (P-1) -- must exit 3 now
    case = fresh_case("C5a_relocated_log")
    reset_canonical_log(TREE)  # canonical log carries no line
    forged_log = write_log(ROOT / "forged" / "RESEARCH_LOG.md", approval_line)
    r = run_cli(TREE, case, forged_log)
    r.update(id="C5a", label="执行层可写位置伪造批准文件（--research-log 指向自己的日志）",
             expectation="refused exit 3 (research_log_not_canonical)", forged_log=str(forged_log),
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    # C5b: approval-looking side files next to the preregistration are ignored
    case = fresh_case("C5b_side_files")
    (case / "phase1" / "APPROVAL.json").write_text(
        json.dumps({"approved": True, "document_sha256": digest}) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.approved").write_text(approval_line + "\n", encoding="utf-8")
    reset_canonical_log(TREE)
    r = run_cli(TREE, case, None)
    r.update(id="C5b", label="预登记旁伪造 APPROVAL.json / .approved 侧车", expectation="refused exit 3")
    cases.append(r)

    # C6: the real positive case
    case = fresh_case("C6_exact_line")
    canonical = reset_canonical_log(TREE, approval_line)
    r = run_cli(TREE, case, None)
    evidence = runstore_approval(case, r.get("run_id"))
    declared = (evidence.get("approval") or {}) if evidence.get("available") else {}
    lines = (
        Path(declared["research_log"]).read_text(encoding="utf-8").splitlines()
        if declared.get("research_log") and Path(declared["research_log"]).is_file()
        else []
    )
    pointed = lines[declared["line_number"] - 1].strip() if declared.get("line_number") and len(lines) >= declared["line_number"] else None
    r.update(id="C6", label="批准行与 document SHA 完全一致（写在 spec.RESEARCH_LOG 的注册节内）",
             expectation="released (exit 0) + RunStore 记录",
             canonical_log=str(canonical), runstore=evidence,
             line_points_at_approval=(pointed == approval_line),
             recorded_line_matches=(declared.get("line") == approval_line),
             recorded_document_sha_matches=(declared.get("document_sha256") == digest),
             recorded_log_sha_matches=(declared.get("research_log_sha256") == sha_file(canonical)))
    cases.append(r)

    # C7: swapped dataset digest with a matching line (P-3 must refuse)
    case = fresh_case("C7_swapped_digest")
    swapped = json.loads(json.dumps(doc))
    swapped["data_identity"]["dataset_digest"] = "de" * 32
    swapped_digest = canonical_sha(swapped)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(swapped, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{swapped_digest}  pre_registration.json\n", encoding="utf-8")
    reset_canonical_log(TREE, PREFIX + swapped_digest)
    r = run_cli(TREE, case, None)
    r.update(id="C7", label="批准行匹配、但文档里的 dataset_digest 被换成别的（P-3 数据集绑定）",
             expectation="refused exit 3 (dataset_identity_mismatch)", swapped_digest=swapped_digest,
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    # C8: line inside a fenced code block in the section (P-4)
    case = fresh_case("C8_fenced_line")
    reset_canonical_log(TREE, "格式示例：", "", "```", approval_line, "```")
    r = run_cli(TREE, case, None)
    r.update(id="C8", label="批准行写在注册节的围栏代码块里", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C9: line inside a blockquote in the section (P-4)
    case = fresh_case("C9_blockquote_line")
    reset_canonical_log(TREE, "> 别人引用过的行：", f"> {approval_line}")
    r = run_cli(TREE, case, None)
    r.update(id="C9", label="批准行写在注册节的引用块里", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C10: two qualifying lines in the section (P-4)
    case = fresh_case("C10_two_lines")
    reset_canonical_log(TREE, approval_line, "", approval_line)
    r = run_cli(TREE, case, None)
    r.update(id="C10", label="注册节里同时有两条合格批准行", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C11: the line sits in another section (P-4)
    case = fresh_case("C11_other_section")
    other = write_log(ROOT / "other" / "RESEARCH_LOG.md")
    text = other.read_text(encoding="utf-8").replace(SECTION, "## D20261012-01：别的条目")
    other.write_text(text + "\n" + approval_line + "\n", encoding="utf-8")
    reset_canonical_log(TREE)
    shutil.copy2(other, TREE / "RESEARCH_LOG.md")
    r = run_cli(TREE, case, None)
    r.update(id="C11", label="批准行写在另一个条目的小节里", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C12: a bound source file drifted (P-2)
    case = fresh_case("C12_source_drift")
    reset_canonical_log(DRIFT, approval_line)
    r = run_cli(DRIFT, case, None)
    r.update(id="C12", label="绑定源文件被改（arms.py 多一行注释）",
             expectation="refused exit 3 (source_binding_drift)", tree=str(DRIFT),
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    result = {
        "harness": "reports/V9-P12/harness/f1_approval_p12.py",
        "reviewer": "p12 independent re-run of the P11 F1 case set",
        "real_tree": str(REAL),
        "sandbox": str(TREE),
        "drift_sandbox": str(DRIFT),
        "frozen_document_sha256": digest,
        "r1_document_sha256": old_digest,
        "train_stub": "sitecustomize replaces worker._train; no bound file is edited",
        "note": "worker._train is replaced at interpreter start-up in the sandbox only; "
                "no optimizer step runs and no real log/preregistration is written",
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "f1-approval-p12.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in cases:
        print(f"{c['id']:4s} exit={c['exit_code']} stage={c['stage']}  {c['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
