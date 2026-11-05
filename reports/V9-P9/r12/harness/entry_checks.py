"""r12 entry checks -- only ever on an isolated copy of the output root.

The card (and P31-LEDGER-INCIDENT-RULING item 4) forbids running any entry
against the production output root: the P31 incident happened exactly because a
review ran the real CLI eval there.  This harness therefore

1. records the production ``control.sqlite3`` and ``eval_report.json`` SHA256,
2. copies the whole ``artifacts/v9/s1/phase1`` tree into a temporary directory,
3. runs the real CLI entries (``verify``, ``train``, ``eval``) with
   ``--output-root`` pointing at that copy -- the isolation guard refuses the
   bounded modes before they read anything, and nothing can reach production,
4. then, still on the same copy, declares the copy as the host anchor in-process
   (the same way the test fixtures declare an isolated host) and runs the worker
   entries there, so the *approval* gate and the new *binding* precondition are
   actually exercised against the real frozen r12 document,
5. re-records the production SHA256 values and fails if either moved.

Nothing here writes approval lines, starts MLX, trains or evaluates a model.
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

from ainerzero.v9.experiments.s1 import spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
PRODUCTION_LEDGER_SHA = "36426891021c9bfcdb9cb25a3adef30f1d2dbfb3d84b3c124b908bd7aeadb67d"
PRODUCTION_EVAL_REPORT_SHA = "4d958d1ad59db1a897245d1acb000dda14a4db08dd0ccb069760061511e0c2cc"
OUT = REPO / "reports/V9-P9/r12/logs/entry-checks.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def production_state() -> dict:
    ledger = PRODUCTION / "control.sqlite3"
    report = PRODUCTION / "eval_report.json"
    return {
        "control.sqlite3": sha256(ledger),
        "control.sqlite3_matches_card": sha256(ledger) == PRODUCTION_LEDGER_SHA,
        "eval_report.json": sha256(report),
        "eval_report_matches_card": sha256(report) == PRODUCTION_EVAL_REPORT_SHA,
    }


def cli(mode: str, copy_root: Path, prereg: Path, arm: str | None = None, seed: int | None = None):
    command = [
        sys.executable,
        "-m",
        "ainerzero.cli",
        "s1-phase1",
        "--mode",
        mode,
        "--output-root",
        str(copy_root),
        "--prereg",
        str(prereg),
    ]
    if arm:
        command += ["--arm", arm]
    if seed is not None:
        command += ["--seed", str(seed)]
    completed = subprocess.run(command, cwd=str(REPO), capture_output=True, text=True, timeout=900)
    report = {}
    try:
        # the CLI prints the whole report as one indented JSON document
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        for line in reversed(completed.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    report = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if not isinstance(report, dict):
        report = {}
    return {
        "command": " ".join(command[1:]),
        "exit_code": completed.returncode,
        "status": report.get("status"),
        "stage": report.get("stage"),
        "refused_stage": report.get("refused_stage"),
        "message": report.get("message"),
        "stdout_tail": completed.stdout[-1500:],
        "report": report,
    }


def main() -> int:
    started = production_state()
    workdir = Path(tempfile.mkdtemp(prefix="s1-r12-entry-"))
    host = workdir / "host"
    copy_root = host / "artifacts" / "v9" / "s1" / "phase1"
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRODUCTION, copy_root)
    # The copy is the host anchor: same layout, its own approval log (a copy of
    # the repository log, which carries no r12 approval line).
    shutil.copy2(REPO / "RESEARCH_LOG.md", host / "RESEARCH_LOG.md")
    prereg = copy_root / "r12" / "pre_registration.json"
    copy_ledger_sha_before = sha256(copy_root / "control.sqlite3")

    # 1. the literal card command: --output-root points at the copy
    cli_runs = {
        "verify": cli("verify", copy_root, prereg),
        "train": cli("train", copy_root, prereg, arm="arm2", seed=0),
        "eval": cli("eval", copy_root, prereg, arm="arm2", seed=0),
    }
    verify_report = cli_runs["verify"].get("report") or {}
    verify_summary = {
        "status": verify_report.get("status"),
        "preregistration_sha256": verify_report.get("preregistration_sha256"),
        "preregistration_status": verify_report.get("preregistration_status"),
        "source_binding_status": (verify_report.get("source_binding") or {}).get("status"),
        "source_binding_drifted": (verify_report.get("source_binding") or {}).get("drifted"),
        "dataset_status": (verify_report.get("dataset") or {}).get("status"),
        "approval_approved": (verify_report.get("approval") or {}).get("approved"),
        "approval_reasons": (verify_report.get("approval") or {}).get("reasons"),
        "final_partition": verify_report.get("final_partition"),
    }
    copy_ledger_sha_after_cli = sha256(copy_root / "control.sqlite3")

    # 2. the same copy declared as the host anchor, so the approval gate and the
    #    binding precondition are exercised against the real frozen document.
    original = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG)
    spec.REGISTERED_HOST_ROOT = host
    spec.PHASE1_ROOT = copy_root
    spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
    try:
        worker_ledger_sha_before = sha256(copy_root / "control.sqlite3")
        train_report = worker.run_worker(
            "train",
            output_root=copy_root,
            limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=float(
                json.loads(prereg.read_text(encoding="utf-8"))["timing"]["deadline_seconds"]
            ),
            prereg_path=prereg,
            arm="arm2",
            seed=0,
        )
        worker_ledger_sha_after_train = sha256(copy_root / "control.sqlite3")
        eval_report = worker.run_worker(
            "eval",
            output_root=copy_root,
            limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=300.0,
            prereg_path=prereg,
            arm="arm2",
            seed=0,
        )
        worker_ledger_sha_after_eval = sha256(copy_root / "control.sqlite3")
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = original

    ended = production_state()
    payload = {
        "workdir": str(workdir),
        "copy_root": str(copy_root),
        "production_before": started,
        "production_after": ended,
        "production_untouched": started == ended,
        "cli_on_copy": {
            name: {key: value for key, value in run.items() if key != "report"}
            for name, run in cli_runs.items()
        },
        "verify_summary": verify_summary,
        "cli_copy_ledger_sha_before": copy_ledger_sha_before,        "cli_copy_ledger_sha_after": copy_ledger_sha_after_cli,
        "cli_copy_ledger_untouched": copy_ledger_sha_before == copy_ledger_sha_after_cli,
        "worker_on_copy_declared_host": {
            "train": {
                "status": train_report.get("status"),
                "refused_stage": train_report.get("refused_stage"),
                "prereg_sha256": train_report.get("prereg_sha256"),
                "approval_approved": (train_report.get("approval") or {}).get("approved"),
            },
            "eval": {
                "status": eval_report.get("status"),
                "refused_stage": eval_report.get("refused_stage"),
                "eval_binding": eval_report.get("eval_binding"),
                "experiment_id": eval_report.get("experiment_id"),
            },
            "copy_ledger_sha_before": worker_ledger_sha_before,
            "copy_ledger_sha_after_train": worker_ledger_sha_after_train,
            "copy_ledger_sha_after_eval": worker_ledger_sha_after_eval,
            "copy_ledger_untouched": worker_ledger_sha_before
            == worker_ledger_sha_after_train
            == worker_ledger_sha_after_eval,
        },
        "production_ledger_expected": PRODUCTION_LEDGER_SHA,
        "production_eval_report_expected": PRODUCTION_EVAL_REPORT_SHA,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "cli_on_copy"},
            indent=1,
            ensure_ascii=False,
        )
    )
    print("cli_on_copy:", json.dumps(payload["cli_on_copy"], ensure_ascii=False))
    ok = (
        payload["production_untouched"]
        and payload["production_before"]["control.sqlite3_matches_card"]
        and payload["production_before"]["eval_report_matches_card"]
        and payload["cli_copy_ledger_untouched"]
        and payload["worker_on_copy_declared_host"]["train"]["refused_stage"]
        == "preregistration_not_approved"
        and payload["worker_on_copy_declared_host"]["eval"]["refused_stage"]
        == "eval_binding_unavailable"
        and payload["worker_on_copy_declared_host"]["copy_ledger_untouched"]
    )
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if ok else 9


if __name__ == "__main__":
    raise SystemExit(main())
