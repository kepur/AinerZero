"""V9.P11 reviewer harness: does the frozen identity bind the code that trains?

``verify`` re-hashes the 12 bound source files and fails on drift.  ``train``
only checks the coordinator approval line.  This harness measures the gap:

  D1  a tree whose bound ``worker.py`` no longer matches the freeze, driven
      through the real CLI ``--mode train`` with the correct approval line
      (train body stubbed, as in the F1 harness -- no optimizer step runs)
  D2  the same tree through ``--mode verify`` -> source_binding_drift
  D3  AST/grep facts: ``mode_train`` never calls the binding check and
      ``worker._train`` never reads ``document["data_identity"]``; plus a probe
      showing ``resolve_dataset_dir`` resolves a dataset without ever comparing
      it to the digest the frozen document names.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
STUB = Path("/private/tmp/v9p11/train_stub")          # src/ with worker._train stubbed
SANDBOX = Path("/private/tmp/v9p11/sandbox")          # byte-identical src/ + live artifacts copy
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V-V9-P9" / "r2" / "evidence"
S1 = "src/ainerzero/v9/experiments/s1"
DOC = REAL / "artifacts" / "v9" / "s1" / "phase1" / "pre_registration.json"
PREFIX = "APPROVED s1-phase1 prereg document_sha256="


def canonical_sha(document: dict) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cli(tree: Path, args: list[str]) -> dict:
    proc = subprocess.run(
        [PY, "-m", "ainerzero.cli", "s1-phase1", *args],
        cwd=str(tree), capture_output=True, text=True, timeout=300,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(tree / "src"),
             "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/private/tmp/v9p11"},
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed": proc.stdout[-1500:]}
    return {
        "exit_code": proc.returncode,
        "status": report.get("status"),
        "stage": report.get("stage") or report.get("refused_stage"),
        "error": report.get("error"),
        "source_binding_status": (report.get("source_binding") or {}).get("status"),
        "approval_approved": (report.get("approval") or {}).get("approved"),
        "run_id": report.get("run_id"),
    }


def main() -> int:
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    digest = canonical_sha(doc)
    case = Path("/private/tmp/v9p11/drift")
    if case.exists():
        shutil.rmtree(case)
    (case / "phase1").mkdir(parents=True)
    shutil.copy2(DOC, case / "phase1" / "pre_registration.json")
    shutil.copy2(DOC.with_suffix(".json.sha256"), case / "phase1" / "pre_registration.json.sha256")
    log = case / "RESEARCH_LOG.md"
    log.write_text("# sandbox log\n" + PREFIX + digest + "\n", encoding="utf-8")

    # the stub tree's worker.py is NOT the file the freeze binds
    bound = json.loads(DOC.read_text(encoding="utf-8"))["source_identity"]["package_files"]
    import hashlib

    actual = hashlib.sha256((STUB / f"{S1}/worker.py").read_bytes()).hexdigest()
    drift = {
        "bound_worker_sha256": bound[f"{S1}/worker.py"],
        "tree_worker_sha256": actual,
        "worker_drifted": bound[f"{S1}/worker.py"] != actual,
    }

    d1 = cli(STUB, ["--mode", "train", "--output-root", str(case / "phase1"),
                    "--prereg", str(case / "phase1" / "pre_registration.json"),
                    "--research-log", str(log)])

    d2 = cli(STUB, ["--mode", "verify", "--output-root", str(case / "phase1"),
                    "--prereg", str(case / "phase1" / "pre_registration.json"),
                    "--research-log", str(log)])

    # D3: static facts
    commands_src = (SANDBOX / S1 / "commands.py").read_text()
    worker_src = (SANDBOX / S1 / "worker.py").read_text()
    commands_tree = ast.parse(commands_src)
    worker_tree = ast.parse(worker_src)

    def function_node(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    train_fn = function_node(commands_tree, "mode_train")
    worker_train = function_node(worker_tree, "_train")
    calls_in = lambda node, attr: sorted({
        n.func.attr for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    })
    facts = {
        "mode_train_calls_source_binding": "_source_binding_state" in ast.dump(train_fn),
        "worker_train_mentions_data_identity": 'data_identity' in ast.dump(worker_train),
        "worker_train_reads_dataset_digest": "dataset_digest" in ast.dump(worker_train),
        "verify_calls_source_binding": "_source_binding_state" in commands_src,
        "worker_train_calls": sorted({
            n.func.attr for n in ast.walk(worker_train)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }),
    }

    # D3b: resolve_dataset_dir accepts the live dataset while the document names another digest
    sys.path.insert(0, str(SANDBOX / "src"))
    from ainerzero.v9.experiments.s1 import data as data_module

    resolved = data_module.resolve_dataset_dir(SANDBOX / "artifacts" / "v9" / "s1" / "phase1")
    facts["resolve_dataset_dir_returns"] = resolved.name
    facts["document_dataset_digest"] = doc["data_identity"]["dataset_digest"]
    facts["resolve_compares_document"] = False  # no document argument is even accepted

    payload = {
        "harness": "reports/V-V9-P9/r2/harness/drift_check.py",
        "worker_drift": drift,
        "D1_train_with_drifted_bound_file": d1,
        "D2_verify_same_tree": d2,
        "D3_static_facts": facts,
        "note": "D1 uses the stubbed train body; it proves the gate releases and the run "
                "opens, not that an optimizer step ran (no training was performed)",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "train-binding-gap.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"D1": d1, "D2": d2, "facts": facts, "drift": drift}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
