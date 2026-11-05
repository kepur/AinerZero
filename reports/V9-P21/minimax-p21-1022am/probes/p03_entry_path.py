"""P21 probe 03: the actual train entry path is anchored to one host.

Cases (all CPU, no model work, no MLX import):

A. isolated host anchor + a *valid* coordinator approval line (real approval
   format, real frozen r7 document SHA) + a central ledger that already holds
   started attempts (completed / failed / stopped) for arm2 seed0
   -> the entry must refuse with ``already_attempted`` (i.e. the approval gate
   passed and the attempt guard fired against the central ledger).
B. same isolated host, but the run root is a *clone* root that carries its own
   empty but legal preparation RunStore and its own approval log
   -> the entry must refuse with ``output_root_not_canonical`` and the clone
   ledger must stay empty: the clone never becomes the central ledger.
C. control: the isolated host without the approval line
   -> the entry must refuse with ``preregistration_not_approved``; this shows the
   approval gate is real and that case A is not masked by "no approval".
D. the real registered host, canonical root, real frozen document
   -> the entry must refuse with ``preregistration_not_approved`` (the real
   RESEARCH_LOG.md carries no valid approval line for the r7 document) and the
   real central ledger must not change.
E. a second *real* source checkout with its own root
   -> the entry must refuse with ``output_root_not_canonical``.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

REAL_LOG = lib.REPO / "RESEARCH_LOG.md"
R7_PREREG = lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
REAL_PHASE1 = lib.REPO / "artifacts/v9/s1/phase1"


def args_for(output_root: Path, *, arm="arm2", seed=0, prereg=R7_PREREG, research_log=None):
    return SimpleNamespace(
        mode="train",
        output_root=Path(output_root),
        limits_file=None,
        prereg=Path(prereg) if prereg else None,
        research_log=Path(research_log) if research_log else None,
        arm=arm,
        seed=seed,
        wall_budget_seconds=None,
        smoke_metrics=None,
    )


def approval_log_with_line(document_sha: str) -> str:
    """The real log plus one bare approval line inside the registered section."""
    text = REAL_LOG.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading = None
    end = None
    for index, line in enumerate(lines):
        if heading is None:
            if line.startswith("## ") and "R20261021-P1-stageA-budget" in line:
                heading = index
            continue
        if line.startswith("## "):
            end = index
            break
    if heading is None:
        raise RuntimeError("the real log has no registered approval section")
    if end is None:
        end = len(lines)
    line = f"APPROVED s1-phase1 prereg document_sha256={document_sha}"
    lines.insert(end, line)
    return "\n".join(lines) + "\n"


def seed_attempts(ledger_path: Path, *, arm="arm2", seed=0, updates=3510, deadline=450.0):
    """Create real RunStore attempts in completed / failed / stopped states."""
    from ainerzero.runtime.lifecycle import RunStore

    from ainerzero.v9.experiments.s1 import worker

    with RunStore(ledger_path) as store:
        store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
        store.create_experiment(
            worker.train_experiment_manifest(deadline_seconds=deadline, updates=updates),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        created = []
        for index, terminal in enumerate(("completed", "failed", "stopped")):
            run_id = f"p21-seeded-{terminal}"
            snapshot = worker.run_config_snapshot(
                wall_budget_seconds=deadline,
                purpose=f"p21-seeded-attempt:{terminal}",
                max_optimizer_steps=updates,
            )
            snapshot.update({"arm_id": arm, "seed": int(seed), "updates": int(updates)})
            store.create_run(
                snapshot,
                f"{worker.TRAIN_EXPERIMENT_ID}:{arm}:{seed}:{run_id}",
                run_id,
                experiment_id=worker.TRAIN_EXPERIMENT_ID,
                role="model",
            )
            store.transition(run_id, "initializing", reason="p21_seed")
            store.transition(run_id, "training", reason="p21_seed")
            if terminal == "stopped":
                store.transition(run_id, "stopping", reason="p21_seed")
            store.transition(run_id, terminal, reason="p21_seed")
            created.append((run_id, terminal))
        states = {run.run_id: run.state for run in store.list_runs()}
    return {"created": created, "states": states, "ledger": str(ledger_path)}


@contextlib.contextmanager
def isolated_host(scratch: Path, *, approval: bool, document_sha: str, seed_attempts_=True):
    """Declare an isolated host anchor (the project's own controlled CPU seam)."""
    from ainerzero.v9.experiments.s1 import spec

    host = scratch / "host"
    phase1 = host / "artifacts/v9/s1/phase1"
    phase1.mkdir(parents=True, exist_ok=True)
    (host / "RESEARCH_LOG.md").write_text(
        approval_log_with_line(document_sha) if approval else REAL_LOG.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (phase1 / "dataset_ref.json").write_text(
        (REAL_PHASE1 / "dataset_ref.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    ledger_path = phase1 / "control.sqlite3"
    if seed_attempts_:
        seed_attempts(ledger_path)
    else:
        from ainerzero.runtime.lifecycle import RunStore

        from ainerzero.v9.experiments.s1 import worker

        with RunStore(ledger_path) as store:
            store.create_experiment(
                worker.prep_experiment_manifest(),
                worker.PREP_REQUEST_ID,
                worker.PREP_EXPERIMENT_ID,
            )
    saved = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG)
    spec.REGISTERED_HOST_ROOT = host.resolve()
    spec.PHASE1_ROOT = phase1
    spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
    try:
        yield {"host": host, "phase1": phase1, "ledger": ledger_path}
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = saved


def run_case(label: str, fn) -> dict:
    try:
        report = fn()
    except BaseException as exc:  # noqa: BLE001 - the probe must not die silently
        return {"label": label, "exception": f"{type(exc).__name__}: {exc}"}
    return {
        "label": label,
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage") or report.get("stage"),
        "message": report.get("message"),
        "attempt_states": report.get("attempt_states"),
        "attempt_run_ids": report.get("attempt_run_ids"),
        "approval": report.get("approval"),
        "host_anchor_status": (report.get("host_anchor") or {}).get("status"),
        "report": report,
    }


def main() -> int:
    from ainerzero.runtime.lifecycle import RunStore
    from ainerzero.v9.experiments.s1 import commands, prereg, spec

    document = json.loads(R7_PREREG.read_text(encoding="utf-8"))
    document_sha = prereg.document_sha256(document)
    scratch = lib.scratch_dir("p21-entry")
    cases = []

    # --- A: valid approval + existing attempts -----------------------------
    with isolated_host(scratch / "a", approval=True, document_sha=document_sha) as host:
        approval_record = prereg.require_coordinator_approval(
            document, document_sha, log_path=host["host"] / "RESEARCH_LOG.md"
        )
        case_a = run_case(
            "A isolated host + valid approval + completed/failed/stopped attempts",
            lambda: commands.mode_train(args_for(host["phase1"])),
        )
        case_a["approval_parsed"] = {
            "approved": True,
            "line_number": approval_record.get("line_number"),
            "document_sha256": approval_record.get("document_sha256"),
        }
        with RunStore(host["ledger"]) as store:
            case_a["central_ledger_states"] = {
                run.run_id: run.state for run in store.list_runs()
            }
        cases.append(case_a)

    # --- B: clone root with its own legal empty ledger ----------------------
    with isolated_host(scratch / "b", approval=True, document_sha=document_sha) as host:
        clone = scratch / "b" / "clone-root"
        (clone / "artifacts/v9/s1/phase1").mkdir(parents=True, exist_ok=True)
        clone_phase1 = clone / "artifacts/v9/s1/phase1"
        clone_log = clone / "RESEARCH_LOG.md"
        clone_log.write_text(
            approval_log_with_line(document_sha), encoding="utf-8"
        )
        (clone_phase1 / "dataset_ref.json").write_text(
            (REAL_PHASE1 / "dataset_ref.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        clone_ledger = clone_phase1 / "control.sqlite3"
        seed_attempts(clone_ledger, arm="arm2", seed=1)
        with RunStore(clone_ledger) as store:
            clone_runs_before = {run.run_id: run.state for run in store.list_runs()}
        clone_sha_before = lib.sha256_file(clone_ledger)
        case_b = run_case(
            "B clone root (own legal ledger + own approval log) must be refused",
            lambda: commands.mode_train(
                args_for(clone_phase1, research_log=clone_log)
            ),
        )
        with RunStore(clone_ledger) as store:
            clone_runs_after = {run.run_id: run.state for run in store.list_runs()}
        case_b["clone_ledger_runs_before"] = clone_runs_before
        case_b["clone_ledger_runs_after"] = clone_runs_after
        case_b["clone_ledger_sha_before"] = clone_sha_before
        case_b["clone_ledger_sha_after"] = lib.sha256_file(clone_ledger)
        cases.append(case_b)

    # --- C: control without the approval line -------------------------------
    with isolated_host(scratch / "c", approval=False, document_sha=document_sha) as host:
        case_c = run_case(
            "C control: same host without an approval line",
            lambda: commands.mode_train(args_for(host["phase1"])),
        )
        cases.append(case_c)

    # --- D: the real registered host ---------------------------------------
    before = lib.host_ledger_identities()
    case_d = run_case(
        "D real registered host, canonical root, real frozen r7 document",
        lambda: commands.mode_train(args_for(REAL_PHASE1)),
    )
    after = lib.host_ledger_identities()
    case_d["real_ledger_before"] = before
    case_d["real_ledger_after"] = after
    case_d["real_ledger_unchanged"] = before == after
    cases.append(case_d)

    # --- E: a second real checkout with its own root -----------------------
    checkout = lib.make_checkout(scratch / "checkout-e")
    clone_root = scratch / "e" / "foreign-root"
    (clone_root / "artifacts/v9/s1/phase1").mkdir(parents=True, exist_ok=True)
    foreign_phase1 = clone_root / "artifacts/v9/s1/phase1"
    foreign_ledger = foreign_phase1 / "control.sqlite3"
    seed_attempts(foreign_ledger, arm="arm2", seed=2)
    foreign_sha_before = lib.sha256_file(foreign_ledger)
    script = (
        "import json,sys;"
        "from types import SimpleNamespace;"
        "from ainerzero.v9.experiments.s1 import commands;"
        "a=SimpleNamespace(mode='train',output_root=__import__('pathlib').Path(sys.argv[1]),"
        "limits_file=None,prereg=__import__('pathlib').Path(sys.argv[2]),research_log=None,"
        "arm='arm2',seed=0,wall_budget_seconds=None,smoke_metrics=None);"
        "r=commands.mode_train(a);"
        "print(json.dumps({'status':r.get('status'),'refused_stage':r.get('refused_stage') or r.get('stage'),"
        "'message':r.get('message'),'anchor':(r.get('host_anchor') or {}).get('root')}))"
    )
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(checkout / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script, str(foreign_phase1), str(R7_PREREG)],
        cwd=str(checkout),
        env=env,
        capture_output=True,
        text=True,
    )
    foreign_sha_after = lib.sha256_file(foreign_ledger)
    case_e = {
        "label": "E second real checkout with a foreign root",
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
        "foreign_ledger_sha_before": foreign_sha_before,
        "foreign_ledger_sha_after": foreign_sha_after,
    }
    if proc.returncode == 0 and proc.stdout.strip():
        case_e.update(json.loads(proc.stdout.strip().splitlines()[-1]))
    cases.append(case_e)

    payload = {
        "schema": "ainerzero.v9.p21.probe03_entry_path.v1",
        "frozen_document": str(R7_PREREG),
        "frozen_document_sha256": document_sha,
        "approval_line_format": prereg.APPROVAL_TEMPLATE.format(document_sha256=document_sha),
        "cases": cases,
        "mlx_imported": lib.mlx_imported(),
        "verdict": {
            "A_attempt_guard_after_valid_approval": (
                cases[0].get("refused_stage") == "already_attempted"
            ),
            "B_clone_refused_and_ledger_untouched": (
                cases[1].get("refused_stage") == "output_root_not_canonical"
                and cases[1].get("clone_ledger_runs_before")
                == cases[1].get("clone_ledger_runs_after")
            ),
            "C_approval_gate_is_real": (
                cases[2].get("refused_stage") == "preregistration_not_approved"
            ),
            "D_real_host_refused_without_approval_and_ledger_unchanged": (
                cases[3].get("refused_stage") == "preregistration_not_approved"
                and cases[3].get("real_ledger_unchanged")
            ),
            "E_second_checkout_refused": (
                cases[4].get("refused_stage") == "output_root_not_canonical"
                and cases[4].get("foreign_ledger_sha_before")
                == cases[4].get("foreign_ledger_sha_after")
            ),
        },
    }
    out = lib.write_json("03-entry-path.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    for case in cases:
        print(case.get("label"), "->", case.get("refused_stage"), "|", case.get("status"))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
