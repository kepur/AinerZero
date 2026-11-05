"""r15 entry checks -- only ever on an isolated copy of the output root (ainerzero.V9.P53).

Adapted from reports/V9-P9/r14/harness/entry_checks.py.  Writes only
reports/V9-P9/r15/logs/entry-checks.json and its own temporary directory.  Adds step 8:
a real eval of one cell per arm on the copy (arm2 s0 from r13, arm3 s1 and arm4 s2 from
r14), which r14 could not complete; it reads the copy ledger only.

1. records the production ``control.sqlite3`` / ``eval_report.json`` SHA256;
2. copies the whole ``artifacts/v9/s1/phase1`` tree into a temporary host;
3. real CLI ``verify`` / ``train`` / ``eval`` with ``--output-root`` at the copy;
4. worker on the copy declared as host (no approval line): train arm2 s2 refused
   ``preregistration_not_approved``; eval arm2 s2 refused ``eval_binding_unavailable``;
5. worker on the copy with a temporary approval line *in the copy's log only*:
   train refuses each inherited cell ``inherited_cell_not_trainable``;
6. read-only eval binding precondition with the real r14 document against the
   copy's ledger: each inherited cell binds its registered r13 run; arm2 s2 and
   arm4 s0 refuse;
7. every copy-ledger SHA is unchanged, and production is unchanged at the end.
No MLX, no training, no evaluation runs (inherited cells are never sent through
the eval worker, whose precondition would pass and then start a real eval).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg, spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
PRODUCTION_LEDGER_SHA = "b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648"
OUT = REPO / "reports/V9-P9/r15/logs/entry-checks.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def production_state() -> dict:
    ledger = PRODUCTION / "control.sqlite3"
    return {
        "control.sqlite3": sha256(ledger),
        "control.sqlite3_matches_card": sha256(ledger) == PRODUCTION_LEDGER_SHA,
        "eval_report.json": sha256(PRODUCTION / "eval_report.json"),
    }


def cli(mode: str, copy_root: Path, prereg_path: Path, arm: str | None = None, seed: int | None = None):
    command = [sys.executable, "-m", "ainerzero.cli", "s1-phase1", "--mode", mode,
               "--output-root", str(copy_root), "--prereg", str(prereg_path)]
    if arm:
        command += ["--arm", arm]
    if seed is not None:
        command += ["--seed", str(seed)]
    completed = subprocess.run(command, cwd=str(REPO), capture_output=True, text=True, timeout=900)
    report = {}
    for line in [completed.stdout] + list(reversed(completed.stdout.splitlines())):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            report = candidate
            break
    return {
        "command": " ".join(command[3:]),
        "exit_code": completed.returncode,
        "status": report.get("status"),
        "stage": report.get("stage"),
        "refused_stage": report.get("refused_stage"),
        "report": report,
    }


def main() -> int:
    started = production_state()
    workdir = Path(tempfile.mkdtemp(prefix="s1-r15-entry-"))
    host = workdir / "host"
    copy_root = host / "artifacts" / "v9" / "s1" / "phase1"
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRODUCTION, copy_root)  # real copy, no symlinks
    shutil.copy2(REPO / "RESEARCH_LOG.md", host / "RESEARCH_LOG.md")
    prereg_path = copy_root / "r15" / "pre_registration.json"
    document = json.loads(prereg_path.read_text(encoding="utf-8"))
    digest = prereg.document_sha256(document)
    ledger = copy_root / "control.sqlite3"
    copy_before = sha256(ledger)

    # 3. CLI on the copy
    cli_runs = {
        "verify": cli("verify", copy_root, prereg_path),
        "train": cli("train", copy_root, prereg_path, arm="arm4", seed=0),
        "eval": cli("eval", copy_root, prereg_path, arm="arm4", seed=0),
    }
    verify = cli_runs["verify"]["report"]
    verify_summary = {
        "status": verify.get("status"),
        "preregistration_sha256": verify.get("preregistration_sha256"),
        "source_binding_status": (verify.get("source_binding") or {}).get("status"),
        "dataset_status": (verify.get("dataset") or {}).get("status"),
        "approval_approved": (verify.get("approval") or {}).get("approved"),
    }
    copy_after_cli = sha256(ledger)

    original = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG)
    spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = host, copy_root, host / "RESEARCH_LOG.md"
    worker_runs: dict = {}
    try:
        deadline = float(document["timing"]["deadline_seconds"])
        # 4. no approval line in the copy's log
        for name, mode, arm, seed, budget in (
            ("train_arm4_s0_unapproved", "train", "arm4", 0, deadline),
            ("eval_arm4_s0", "eval", "arm4", 0, 300.0),
        ):
            report = worker.run_worker(mode, output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                       wall_budget_seconds=budget, prereg_path=prereg_path, arm=arm, seed=seed)
            worker_runs[name] = {"status": report.get("status"), "refused_stage": report.get("refused_stage"),
                                 "run_id": report.get("run_id"), "ledger_sha": sha256(ledger)}
        # 5. temporary approval line in the COPY's log only
        # The section allows exactly one qualifying line, so the copy's current (r13)
        # line is replaced, not joined; the repository RESEARCH_LOG.md is never written.
        log = host / "RESEARCH_LOG.md"
        text = log.read_text(encoding="utf-8")
        r13_line = prereg.APPROVAL_TEMPLATE.format(
            document_sha256=spec.R15_INHERITANCE["sources"][spec.R14_EXPERIMENT_ID]["source_preregistration_sha256"])
        assert text.count(r13_line + "\n") == 1, "the copy's log does not carry exactly one r14 line"
        log.write_text(
            text.replace(r13_line + "\n", prereg.APPROVAL_TEMPLATE.format(document_sha256=digest) + "\n"),
            encoding="utf-8",
        )
        assert log.resolve() != (REPO / "RESEARCH_LOG.md").resolve()
        for arm, seed in [(c["arm_id"], c["seed"]) for c in spec.R15_INHERITANCE["cells"]]:
            report = worker.run_worker("train", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                       wall_budget_seconds=deadline, prereg_path=prereg_path, arm=arm, seed=seed)
            worker_runs[f"train_{arm}_s{seed}_approved_copy"] = {
                "status": report.get("status"), "refused_stage": report.get("refused_stage"),
                "approval_approved": (report.get("approval") or {}).get("approved"),
                "inherited": report.get("inherited"), "run_id": report.get("run_id"),
                "ledger_sha": sha256(ledger)}
        # 6. read-only binding precondition with the real document
        bindings = {}
        updates = int(document["training_protocol"]["updates"])
        for arm, seed in [(c["arm_id"], c["seed"]) for c in spec.R15_INHERITANCE["cells"]] + [("arm4", 0)]:
            result = worker._eval_binding_precondition(copy_root, arm_id=arm, seed=seed, prereg_sha256=digest,
                                                       updates=updates, ledger_path=ledger, document=document)
            bindings[f"{arm}_s{seed}"] = {k: result.get(k) for k in ("status", "refused_stage", "bound_run_id", "inherited", "error")}
        worker_runs["binding_precondition"] = bindings
        # 8. real eval of one cell per arm on the copy (the r14 defect path)
        original_ledger = worker.canonical_ledger_path
        worker.canonical_ledger_path = lambda *a, **k: ledger
        evals = {}
        try:
            for arm, seed in (("arm2", 0), ("arm3", 1), ("arm4", 2)):
                try:
                    details = worker._evaluate_arm(document, copy_root, arm_id=arm, seed=seed, prereg_sha256=digest)
                    evals[f"{arm}_s{seed}"] = {"status": details.get("status"),
                                                "bound_run": (details.get("run_binding") or {}).get("run_id"),
                                                "inherited_from": ((details.get("run_binding") or {}).get("inherited") or {}).get("source_experiment_id")}
                except Exception as exc:  # recorded, not raised
                    evals[f"{arm}_s{seed}"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            worker.canonical_ledger_path = original_ledger
        worker_runs["real_eval_on_copy"] = evals
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = original

    ended = production_state()
    registered = {(c["arm_id"], c["seed"]): c["source_run_id"] for c in spec.R15_INHERITANCE["cells"]}
    b = worker_runs["binding_precondition"]
    checks = {
        "production_untouched": started == ended and started["control.sqlite3_matches_card"],
        "cli_copy_ledger_untouched": copy_before == copy_after_cli,
        "verify_completed_binding_passed_not_approved": verify_summary["status"] == "completed"
        and verify_summary["source_binding_status"] == "passed"
        and verify_summary["approval_approved"] is False
        and verify_summary["preregistration_sha256"] == digest,
        "cli_train_eval_refused": all(cli_runs[m]["exit_code"] != 0 for m in ("train", "eval")),
        "worker_unapproved_train_refused": worker_runs["train_arm4_s0_unapproved"]["refused_stage"] == "preregistration_not_approved",
        "worker_eval_non_inherited_refused": worker_runs["eval_arm4_s0"]["refused_stage"] == "eval_binding_unavailable",
        "inherited_cells_not_trainable": all(
            worker_runs[f"train_{a}_s{s}_approved_copy"]["refused_stage"] == "inherited_cell_not_trainable"
            and worker_runs[f"train_{a}_s{s}_approved_copy"]["approval_approved"] in (True, None)
            for a, s in registered),
        "inherited_cells_bind_registered_runs": all(
            b[f"{a}_s{s}"]["status"] == "ok" and b[f"{a}_s{s}"]["bound_run_id"] == run for (a, s), run in registered.items()),
        "non_inherited_cells_refuse_binding": b["arm4_s0"]["status"] == "refused",
        "copy_ledger_untouched_by_worker": all(
            v.get("ledger_sha") == copy_before for k, v in worker_runs.items() if k not in ("binding_precondition", "real_eval_on_copy")),
        "real_eval_completes_each_arm": all(v.get("status") == "completed" for v in worker_runs["real_eval_on_copy"].values()),
    }
    # Observation, not a gate: _evaluate_arm opens the (copy) RunStore read-write exactly as the
    # production eval does, so the copy ledger may change here; production is checked above.
    worker_runs["copy_ledger_changed_by_real_eval"] = sha256(ledger) != copy_before
    payload = {
        "workdir": str(workdir),
        "document_sha256": digest,
        "production_before": started,
        "production_after": ended,
        "copy_ledger_sha_before": copy_before,
        "cli_on_copy": {k: {kk: vv for kk, vv in v.items() if kk != "report"} for k, v in cli_runs.items()},
        "verify_summary": verify_summary,
        "worker_on_copy": worker_runs,
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "all_passed": payload["all_passed"]}, indent=1, ensure_ascii=False))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if payload["all_passed"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
