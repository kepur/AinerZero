"""V9.P14 rerun of the P13(r4)/P11 F1 harness.

Adapted by the P14 reviewer: only the sandbox root (/private/tmp/v9p9r4 -> a P14 temp
dir), OUT (reports/V9-P9/r4/harness -> reports/V9-P14/evidence) and the output file
name changed; every case body is unchanged.

Original docstring: V9.P9 r4 harness: re-run of the V9.P11 F1 cases (C5a, C5b, C6) plus the P-1..P-4 counterexamples.

Updated for r4 (V9.P13):
- train CLI invocations include required `--arm arm2 --seed 0`
- sandbox points at /private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/
- OUT points at reports/V9-P9/r4/harness/
- sitecustomize stub provides compliant return dict for _train
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
ROOT = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/f1")
BASE = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/sandbox")
STUB = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/train_stub")
DRIFT = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/train_stub_drift")
SITE = Path("/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run/site")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P14" / "evidence"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
DATASET_REF = REAL / "artifacts" / "v9" / "s1" / "phase1" / "dataset_ref.json"
OLD_DOC = REAL / "reports" / "V9-P9" / "r3" / "pre_registration.json"
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

    _w._train = lambda *a, **k: {
        "stub": "reviewer_stub_no_training",
        "updates": 0,
        "status": "completed",
        "arm_id": "arm2",
        "seed": 0,
        "wall_seconds": 0.01,
    }
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
    datasets.parent.mkdir(parents=True, exist_ok=True)
    if (REAL / "artifacts" / "v9" / "s1" / "datasets").exists():
        datasets.symlink_to(REAL / "artifacts" / "v9" / "s1" / "datasets")
    subprocess.run(
        ["find", str(target), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def make_sitecustomize() -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")


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
        "--arm", "arm2", "--seed", "0",
        "--output-root", str(case / "phase1"),
        "--prereg", str(prereg or (case / "phase1" / "pre_registration.json")),
    ]
    if log is not None:
        command += ["--research-log", str(log)]
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": f"{tree / 'src'}:{SITE}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/p14/f1run",
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
        "approval_detail": approval.get("detail"),
        "run_id": (report.get("run") or {}).get("run_id"),
        "worker_exit_code": report.get("worker_exit_code"),
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


def fresh_case(name: str) -> Path:
    case = ROOT / name
    if case.exists():
        shutil.rmtree(case)
    (case / "phase1").mkdir(parents=True)
    if DATASET_REF.is_file():
        shutil.copy2(DATASET_REF, case / "phase1" / "dataset_ref.json")
    shutil.copy2(DOC, case / "phase1" / "pre_registration.json")
    shutil.copy2(DOC.with_suffix(".json.sha256"), case / "phase1" / "pre_registration.json.sha256")
    return case


def main() -> int:
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    digest = canonical_sha(doc)
    old_digest = canonical_sha(json.loads(OLD_DOC.read_text(encoding="utf-8"))) if OLD_DOC.is_file() else "none"
    approval_line = PREFIX + digest

    build_tree(STUB)
    build_tree(DRIFT)
    make_sitecustomize()

    # Drift the binding tree slightly (arms.py gets one extra comment line)
    drift_target = DRIFT / "src" / "ainerzero" / "v9" / "experiments" / "s1" / "arms.py"
    drift_target.write_text(drift_target.read_text(encoding="utf-8") + "\n# drifted by reviewer harness\n", encoding="utf-8")

    cases = []

    # C5a: log missing the approval line
    case = fresh_case("C5a_no_line")
    log = write_log(case / "RESEARCH_LOG.md")
    r = run_cli(STUB, case, log)
    r.update(id="C5a", label="日志内无批准行，但传了 --research-log（P-1 优先拒绝改道）",
             expectation="refused exit 3 (research_log_not_canonical)")
    cases.append(r)

    # C5b: log has the line for the older document
    case = fresh_case("C5b_wrong_doc_sha")
    reset_canonical_log(STUB, PREFIX + old_digest)
    r = run_cli(STUB, case, None)
    r.update(id="C5b", label="批准行指向上一轮文档（SHA 不匹配）", expectation="refused exit 3 (approval gate)")
    cases.append(r)

    # C6: the positive case (written into the canonical log section)
    case = fresh_case("C6_matching_line_in_canonical")
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
        "harness": "reports/V9-P14/harness/f1_approval_rerun.py (adapted copy of reports/V9-P9/r4/harness/f1_approval_r4.py)",
        "real_tree": str(REAL),
        "sandbox": str(STUB),
        "drift_sandbox": str(DRIFT),
        "frozen_document_sha256": digest,
        "r3_document_sha256": old_digest,
        "train_stub": "sitecustomize replaces worker._train; no bound file is edited",
        "note": "worker._train is replaced at interpreter start-up in the sandbox only; "
        "no optimizer step runs and no real log/preregistration is written",
        "cases": cases,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "f1-approval-r4-rerun-p14.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in cases:
        print(f"{c['id']:4s} exit={c['exit_code']} stage={c['stage']}  {c['label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
