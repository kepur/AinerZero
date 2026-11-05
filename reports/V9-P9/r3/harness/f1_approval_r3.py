"""V9.P9 r3 harness: re-run of the V9.P11 F1 cases (C5a, C5b, C6) plus the new
P-1/P-2/P-3/P-4 counterexamples.

Why this harness differs from ``reports/V-V9-P9/r2/harness/f1_approval.py``
-----------------------------------------------------------------------
1. **No source edit for the training stub.**  r3 added the P-2 source-binding
   gate, which re-hashes the files the frozen document binds -- including
   ``worker.py``.  The r2 harness stubbed ``worker._train`` by *editing*
   ``worker.py`` inside its sandbox copy, which would now (correctly) trip the
   binding gate.  This harness instead installs a ``sitecustomize.py`` on
   ``PYTHONPATH``: it intercepts ``python -m ainerzero.v9.experiments.s1.worker``,
   imports the module unchanged, replaces ``_train`` and calls ``worker.main()``
   (``-m`` executes the body as ``__main__``, so a plain import-time patch would
   be discarded).  The sandbox source therefore stays byte-identical to the
   frozen binding and the optimizer still never runs.
2. **The log fixture follows the P-4 section rule.**  The r2 harness wrote a log
   whose section marker was the bare text ``R20261021-P1-stageA-budget`` (no
   ``##`` heading), which the new rule does not accept.  Every fixture here uses
   the registered ``## R20261021-P1-stageA-budget`` heading, and the negative
   cases add the fenced / blockquoted / duplicated / other-section variants.
3. **C5c is retired into C6.**  r2 had C5c "write the line into the writable
   default log" as a *design* case that was released.  P-1 makes the default log
   the only accepted location, so C5c and C6 are the same run: the approval line
   is written into the sandbox copy of ``spec.RESEARCH_LOG``.  The residual risk
   (whoever can write the real log can approve) is R-6, accepted by level 1 and
   mitigated by the relay notice, not by code.
4. **C7 now refuses.**  In r2, C7 showed the credential pinned only the document
   SHA: a swapped ``dataset_digest`` with a matching line was released.  P-3
   binds the dataset, so C7 must now be refused at the dataset gate.
5. **The dataset must exist** for the positive case: each case root gets the
   real ``dataset_ref.json`` and the sandbox resolves the real dataset bytes
   through a symlink.

Nothing here trains, writes to the real RESEARCH_LOG.md or touches the real
preregistration; the real tree is only read.
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
ROOT = Path("/private/tmp/v9p9r3/f1")
BASE = Path("/private/tmp/v9p9r3/sandbox")
STUB = Path("/private/tmp/v9p9r3/train_stub")
DRIFT = Path("/private/tmp/v9p9r3/train_stub_drift")
SITE = Path("/private/tmp/v9p9r3/site")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P9" / "r3" / "harness"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
DATASET_REF = REAL / "artifacts" / "v9" / "s1" / "phase1" / "dataset_ref.json"
OLD_DOC = REAL / "reports" / "V9-P9" / "r1-archive" / "pre_registration.json"
PREFIX = "APPROVED s1-phase1 prereg document_sha256="
SECTION = "## R20261021-P1-stageA-budget：S1 第一阶段训练预算登记（reviewer sandbox）"

SITECUSTOMIZE = '''"""Reviewer stub: replace the registered training loop, edit no bound file.

``python -m pkg.mod`` executes the module body as ``__main__`` (runpy), so a
plain ``import ...; module._train = ...`` patch is discarded.  The shim instead
intercepts the worker entry itself, imports the module normally, replaces
``_train`` and then calls ``worker.main()`` -- the same JSON-on-stdout contract.
"""
import sys

_ORIG = getattr(sys, "orig_argv", sys.argv)
if _ORIG[1:3] == ["-m", "ainerzero.v9.experiments.s1.worker"]:
    from ainerzero.v9.experiments.s1 import worker as _w

    _w._train = lambda *a, **k: {"stub": "reviewer_stub_no_training", "updates": 0}
    raise SystemExit(_w.main(_ORIG[3:]))
'''


def canonical_sha(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_tree(target: Path) -> None:
    """A sandbox copy of the real tree: sources, canonical log, dataset link."""
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(["rsync", "-a", f"{REAL}/src/", f"{target}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/RESEARCH_LOG.md", f"{target}/RESEARCH_LOG.md"], check=True)
    (target / "artifacts" / "locks").mkdir(parents=True)
    datasets = target / "artifacts" / "v9" / "s1" / "datasets"
    datasets.parent.mkdir(parents=True)
    datasets.symlink_to(REAL / "artifacts" / "v9" / "s1" / "datasets")
    subprocess.run(
        ["find", str(target), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def build_stub() -> None:
    build_tree(STUB)
    if DRIFT.exists():
        shutil.rmtree(DRIFT)
    shutil.copytree(STUB, DRIFT, symlinks=True)
    # P-2 counterexample: one byte of a bound source file changes.
    arms = DRIFT / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "arms.py"
    arms.write_text(arms.read_text() + "\n# reviewer drift marker\n", encoding="utf-8")
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
    body = "# RESEARCH_LOG copy (reviewer sandbox)\n\n" + SECTION + "\n\n"
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
        "HOME": "/private/tmp/v9p9r3",
    }
    proc = subprocess.run(command, cwd=str(tree), capture_output=True, text=True, timeout=600, env=env)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed_stdout": proc.stdout[-2000:]}
    approval = report.get("approval") or {}
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "stage": report.get("stage") or report.get("refused_stage") or report.get("status"),
        "status": report.get("status"),
        "preregistration_sha256": report.get("preregistration_sha256") or report.get("prereg_sha256"),
        "preregistration_status": report.get("preregistration_status"),
        "approval_reasons": approval.get("reasons"),
        "approval_detail_keys": sorted((approval.get("detail") or {}).keys()),
        "dataset_status": (report.get("dataset") or {}).get("status"),
        "source_binding_status": (report.get("source_binding") or {}).get("status"),
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
    assert digest == DOC.with_suffix(".json.sha256").read_text().split()[0], "frozen SHA mismatch"
    approval_line = PREFIX + digest
    cases: list[dict] = []

    # C1: status only -> approved, SHA recomputed, sidecar rewritten, no log line
    case = fresh_case("C1_forged_status")
    forged = dict(doc, status="approved")
    forged_digest = canonical_sha(forged)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(forged, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{forged_digest}  pre_registration.json\n", encoding="utf-8")
    reset_canonical_log(STUB)
    r = run_cli(STUB, case, None)
    r.update(id="C1", label="只改预登记 status=approved 并重算 SHA/侧车，日志无批准行",
             expectation="refused exit 3", forged_document_sha256=forged_digest,
             self_consistent=(forged_digest == (case / "phase1" / "pre_registration.json.sha256").read_text().split()[0]))
    cases.append(r)

    # C2: no approval line
    case = fresh_case("C2_no_line")
    reset_canonical_log(STUB, "APPROVED s1-phase1 prereg (format without sha)")
    r = run_cli(STUB, case, None)
    r.update(id="C2", label="批准行缺失（只有说明性文字）", expectation="refused exit 3")
    cases.append(r)

    # C3: one hex digit off
    case = fresh_case("C3_one_digit_off")
    broken = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    reset_canonical_log(STUB, PREFIX + broken)
    r = run_cli(STUB, case, None)
    r.update(id="C3", label="批准行 SHA 差一位", expectation="refused exit 3", line_sha=broken)
    cases.append(r)

    # C4: approval line for the older (r1) document
    case = fresh_case("C4_old_document")
    reset_canonical_log(STUB, PREFIX + old_digest)
    r = run_cli(STUB, case, None)
    r.update(id="C4", label="批准行指向 r1 旧文档", expectation="refused exit 3",
             old_document_sha256=old_digest)
    cases.append(r)

    # C5a: relocated --research-log carrying the exact line (P-1)
    case = fresh_case("C5a_relocated_log")
    reset_canonical_log(STUB)  # canonical log carries no line
    forged_log = write_log(ROOT / "forged" / "RESEARCH_LOG.md", approval_line)
    r = run_cli(STUB, case, forged_log)
    r.update(id="C5a", label="执行层可写位置伪造批准文件（--research-log 指向自己的日志）",
             expectation="refused exit 3 (research_log_not_canonical)", forged_log=str(forged_log),
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    # C5b: approval-looking side files next to the prereg are ignored
    case = fresh_case("C5b_side_files")
    (case / "phase1" / "APPROVAL.json").write_text(
        json.dumps({"approved": True, "document_sha256": digest}) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.approved").write_text(approval_line + "\n", encoding="utf-8")
    reset_canonical_log(STUB)
    r = run_cli(STUB, case, None)
    r.update(id="C5b", label="预登记旁伪造 APPROVAL.json / .approved 侧车", expectation="refused exit 3")
    cases.append(r)

    # C6: the real positive case -- line inside the canonical log's section
    case = fresh_case("C6_exact_line")
    canonical = reset_canonical_log(STUB, approval_line)
    r = run_cli(STUB, case, None)
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

    # C7: swapped dataset digest + matching line (P-3 now refuses)
    case = fresh_case("C7_swapped_digest")
    swapped = json.loads(json.dumps(doc))
    swapped["data_identity"]["dataset_digest"] = "de" * 32
    swapped_digest = canonical_sha(swapped)
    (case / "phase1" / "pre_registration.json").write_text(
        json.dumps(swapped, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (case / "phase1" / "pre_registration.json.sha256").write_text(
        f"{swapped_digest}  pre_registration.json\n", encoding="utf-8")
    reset_canonical_log(STUB, PREFIX + swapped_digest)
    r = run_cli(STUB, case, None)
    r.update(id="C7", label="批准行匹配、但文档里的 dataset_digest 被换成别的（P-3 数据集绑定）",
             expectation="refused exit 3 (dataset_identity_mismatch)", swapped_digest=swapped_digest,
             runstore=runstore_approval(case, r.get("run_id")))
    cases.append(r)

    # C8: the line sits inside a fenced code block in the section (P-4)
    case = fresh_case("C8_fenced_line")
    reset_canonical_log(STUB, "格式示例：", "", "```", approval_line, "```")
    r = run_cli(STUB, case, None)
    r.update(id="C8", label="批准行写在注册节的围栏代码块里", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C9: the line sits inside a blockquote in the section (P-4)
    case = fresh_case("C9_blockquote_line")
    reset_canonical_log(STUB, "> 别人引用过的行：", f"> {approval_line}")
    r = run_cli(STUB, case, None)
    r.update(id="C9", label="批准行写在注册节的引用块里", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C10: two qualifying lines in the section (P-4)
    case = fresh_case("C10_two_lines")
    reset_canonical_log(STUB, approval_line, "", approval_line)
    r = run_cli(STUB, case, None)
    r.update(id="C10", label="注册节里同时有两条合格批准行", expectation="refused exit 3 (P-4)")
    cases.append(r)

    # C11: the line sits in another section (P-4)
    case = fresh_case("C11_other_section")
    other = write_log(ROOT / "other" / "RESEARCH_LOG.md")
    text = other.read_text(encoding="utf-8").replace(SECTION, "## D20261012-01：别的条目")
    other.write_text(text + "\n" + approval_line + "\n", encoding="utf-8")
    reset_canonical_log(STUB)
    shutil.copy2(other, STUB / "RESEARCH_LOG.md")
    r = run_cli(STUB, case, None)
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
        "harness": "reports/V9-P9/r3/harness/f1_approval_r3.py",
        "real_tree": str(REAL),
        "sandbox": str(STUB),
        "drift_sandbox": str(DRIFT),
        "frozen_document_sha256": digest,
        "r1_document_sha256": old_digest,
        "train_stub": "sitecustomize replaces worker._train; no bound file is edited",
        "note": "worker._train is replaced at interpreter start-up in the sandbox only; "
        "no optimizer step runs and no real log/preregistration is written",
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "f1-approval-r3.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in cases:
        print(f"{c['id']:4s} exit={c['exit_code']} stage={c['stage']}  {c['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
