"""V9.P11 reviewer harness: F1 approval-binding adversarial matrix.

Everything runs on a byte-identical sandbox copy of ``src/`` (``spec.REPO_ROOT``
resolves into ``/private/tmp/v9p11/...``) plus a *stub* copy in which
``worker._train`` returns immediately.  No MLX work, no real lock, no real
ledger and no real ``RESEARCH_LOG.md`` write ever happens: the real tree is only
read.

Each case is driven through the real CLI entry point
(``python -m ainerzero.cli s1-phase1 --mode train``) so the verdict is an exit
code, not a unit-test assertion.

Cases
  C1  status -> approved, canonical SHA recomputed, sidecar rewritten  (no log line)
  C2  no approval line at all
  C3  approval line one hex digit off
  C4  approval line points at the r1 (older) frozen document
  C5a forged approval file in an executor-writable location, passed with
      ``--research-log``                                        <-- F1 class 5
  C5b extra approval-looking files next to the prereg (json/sidecar) are ignored
  C5c approval line appended to the *default* log inside the sandbox tree
      (i.e. whoever may write RESEARCH_LOG.md approves themselves)
  C6  correct line  -> released, RunStore records line text + SHA
  C7  correct line but the frozen document carries a swapped dataset digest
      (shows what the credential actually pins)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
ROOT = Path("/private/tmp/v9p11/f1")
BASE = Path("/private/tmp/v9p11/sandbox")
STUB = Path("/private/tmp/v9p11/train_stub")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V-V9-P9" / "r2" / "evidence"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
OLD_DOC = REAL / "reports" / "V9-P9" / "r1-archive" / "pre_registration.json"
PREFIX = "APPROVED s1-phase1 prereg document_sha256="
STUB_MARK = '    """Registered training loop for V9.P1 (not executed by this card)."""\n    import mlx.core as mx'
STUB_BODY = (
    '    """V9.P11 reviewer stub: the gate is under test, never the optimizer."""\n'
    '    return {"stub": "reviewer_stub_no_training", "updates": 0}\n'
    "    import mlx.core as mx"
)


def canonical_sha(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_stub() -> None:
    if STUB.exists():
        shutil.rmtree(STUB)
    subprocess.run(["rsync", "-a", f"{BASE}/src/", f"{STUB}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{BASE}/RESEARCH_LOG.md", f"{STUB}/RESEARCH_LOG.md"], check=True)
    (STUB / "artifacts" / "locks").mkdir(parents=True)
    worker = STUB / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "worker.py"
    text = worker.read_text()
    assert STUB_MARK in text, "stub anchor not found; the reviewer must not train"
    worker.write_text(text.replace(STUB_MARK, STUB_BODY, 1))
    subprocess.run(
        ["find", str(STUB), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def fresh_case(name: str) -> Path:
    case = ROOT / name
    if case.exists():
        shutil.rmtree(case)
    (case / "phase1").mkdir(parents=True)
    shutil.copy2(DOC, case / "phase1" / "pre_registration.json")
    shutil.copy2(DOC.with_suffix(".json.sha256"), case / "phase1" / "pre_registration.json.sha256")
    return case


def write_log(path: Path, *extra: str) -> Path:
    body = "# RESEARCH_LOG copy (reviewer sandbox)\n\nR20261021-P1-stageA-budget\n"
    body += "\n".join(extra) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def run_cli(case: Path, log: Path | None, prereg: Path | None = None) -> dict:
    command = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train",
               "--output-root", str(case / "phase1"),
               "--prereg", str(prereg or (case / "phase1" / "pre_registration.json"))]
    if log is not None:
        command += ["--research-log", str(log)]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(STUB / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/private/tmp/v9p11",
    }
    proc = subprocess.run(command, cwd=str(STUB), capture_output=True, text=True, timeout=300, env=env)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed_stdout": proc.stdout[-2000:]}
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "stage": report.get("stage") or report.get("refused_stage") or report.get("status"),
        "status": report.get("status"),
        "preregistration_sha256": report.get("preregistration_sha256") or report.get("prereg_sha256"),
        "preregistration_status": report.get("preregistration_status"),
        "approval": report.get("approval"),
        "run_id": report.get("run_id"),
        "error": report.get("error"),
        "stderr_tail": proc.stderr.strip()[-600:],
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
            "select to_state from run_transitions where run_id = ? order by id", (run_id,)
        )]
    return {
        "available": True,
        "state": row["state"],
        "role": row["role"],
        "approval": snapshot.get("approval"),
        "transitions": states,
        "optimizer_steps": row["optimizer_steps"],
    }


def main() -> int:
    build_stub()
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    digest = canonical_sha(doc)
    old_digest = canonical_sha(json.loads(OLD_DOC.read_text(encoding="utf-8")))
    assert digest == DOC.with_suffix(".json.sha256").read_text().split()[0]
    approval_line = PREFIX + digest
    cases: list[dict] = []

    # C1: status only -> approved, SHA recomputed, sidecar rewritten
    case = fresh_case("C1_forged_status")
    forged = dict(doc, status="approved")
    forged_digest = canonical_sha(forged)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(forged, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{forged_digest}  pre_registration.json\n", encoding="utf-8")
    log = write_log(case / "logs" / "RESEARCH_LOG.md")
    r = run_cli(case, log)
    r.update(id="C1", label="只改预登记 status=approved 并重算 SHA/侧车，日志无批准行",
             expectation="refused exit 3", forged_document_sha256=forged_digest,
             self_consistent=(forged_digest == (case / "phase1" / "pre_registration.json.sha256").read_text().split()[0]))
    cases.append(r)

    # C2: no approval line
    case = fresh_case("C2_no_line")
    log = write_log(case / "logs" / "RESEARCH_LOG.md", "APPROVED s1-phase1 prereg (format without sha)")
    r = run_cli(case, log)
    r.update(id="C2", label="批准行缺失（只有说明性文字）", expectation="refused exit 3")
    cases.append(r)

    # C3: one hex digit off
    case = fresh_case("C3_one_digit_off")
    broken = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    log = write_log(case / "logs" / "RESEARCH_LOG.md", PREFIX + broken)
    r = run_cli(case, log)
    log_approvals = ((r.get("approval") or {}).get("detail") or {}).get("log_approval_sha256")
    r.update(id="C3", label="批准行 SHA 差一位", expectation="refused exit 3",
             line_sha=broken, log_approval_sha256=log_approvals)
    cases.append(r)

    # C4: approval line for the older (r1) document
    case = fresh_case("C4_old_document")
    log = write_log(case / "logs" / "RESEARCH_LOG.md", PREFIX + old_digest)
    r = run_cli(case, log)
    r.update(id="C4", label="批准行指向 r1 旧文档", expectation="refused exit 3",
             old_document_sha256=old_digest)
    cases.append(r)

    # C5a: forged approval file in an executor-writable location via --research-log
    case = fresh_case("C5a_relocated_log")
    forged_log = write_log(ROOT / "forged" / "RESEARCH_LOG.md", approval_line)
    r = run_cli(case, forged_log)
    r.update(id="C5a", label="执行层可写位置伪造批准文件（--research-log 指向自己的日志）",
             expectation="refused exit 3", forged_log=str(forged_log),
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    # C5b: approval-looking side files next to the prereg are ignored
    case = fresh_case("C5b_side_files")
    (case / "phase1" / "APPROVAL.json").write_text(
        json.dumps({"approved": True, "document_sha256": digest}) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.approved").write_text(approval_line + "\n", encoding="utf-8")
    log = write_log(case / "logs" / "RESEARCH_LOG.md")
    r = run_cli(case, log)
    r.update(id="C5b", label="预登记旁伪造 APPROVAL.json / .approved 侧车", expectation="refused exit 3")
    cases.append(r)

    # C5c: line appended to the default log inside the writable tree
    case = fresh_case("C5c_default_log")
    default_log = write_log(STUB / "RESEARCH_LOG.md", approval_line)
    r = run_cli(case, None)
    r.update(id="C5c", label="默认 RESEARCH_LOG.md（可写副本）被写入批准行，不传 --research-log",
             expectation="released if the log is written by someone allowed to write it (design)",
             default_log=str(default_log))
    cases.append(r)

    # C6: the real positive case
    case = fresh_case("C6_exact_line")
    log = write_log(case / "logs" / "RESEARCH_LOG.md", approval_line)
    r = run_cli(case, log)
    evidence = runstore_approval(case, r.get("run_id"))
    declared = (evidence.get("approval") or {}) if evidence.get("available") else {}
    lines = Path(evidence.get("approval", {}).get("research_log") or "").read_text().splitlines() if evidence.get("available") and declared.get("research_log") else []
    pointed = lines[declared["line_number"] - 1].strip() if declared.get("line_number") and len(lines) >= declared["line_number"] else None
    r.update(id="C6", label="批准行与 document SHA 完全一致", expectation="released (exit 0) + RunStore 记录",
             runstore=evidence, line_points_at_approval=(pointed == approval_line),
             recorded_line_matches=(declared.get("line") == approval_line),
             recorded_document_sha_matches=(declared.get("document_sha256") == digest),
             recorded_log_sha_matches=(declared.get("research_log_sha256") == sha_file(log)))
    cases.append(r)

    # C7: what the credential actually pins -- swapped dataset digest, matching log
    case = fresh_case("C7_swapped_digest")
    swapped = json.loads(json.dumps(doc))
    swapped["data_identity"]["dataset_digest"] = "de" * 32
    swapped_digest = canonical_sha(swapped)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(swapped, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{swapped_digest}  pre_registration.json\n", encoding="utf-8")
    log = write_log(case / "logs" / "RESEARCH_LOG.md", PREFIX + swapped_digest)
    r = run_cli(case, log)
    r.update(id="C7", label="同一个伪造日志+换掉 dataset_digest 的文档（看凭据到底钉住什么）",
             expectation="released -> 凭证只钉文档 SHA，不钉数据/参数来源", swapped_digest=swapped_digest)
    cases.append(r)

    result = {
        "harness": "reports/V-V9-P9/r2/harness/f1_approval.py",
        "real_tree": str(REAL),
        "sandbox": str(STUB),
        "frozen_document_sha256": digest,
        "r1_document_sha256": old_digest,
        "train_stub": True,
        "note": "worker._train replaced by a stub in the sandbox copy only; no optimizer step runs",
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "f1-approval.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in cases:
        print(f"{c['id']:4s} exit={c['exit_code']} stage={c['stage']}  {c['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
