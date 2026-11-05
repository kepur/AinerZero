"""End-to-end dry run of the final-eval pipeline on an isolated copy (ainerzero.V9.P60 reviewer gemini-b4e7).

The real sealed final dataset is never opened: ``spec.FINAL_SEALED_ROOT`` is pointed at a temporary
root holding a *fixture* sealed dataset made from the development split relabelled ``final``.
Everything else is real: the copied phase-1 host and ledger, the 9 inherited checkpoints, the arm1
D candidate, MLX scoring, READ_ONCE, the second-read refusal. Writes only dryrun.json and
its own temporary directory. Production ledger and the real sealed dataset are hashed before/after.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import data, prereg, spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
REAL_SEALED_ROOT = REPO / "artifacts/v9/s1/final-sealed"
OUT = Path(__file__).resolve().parent / "dryrun.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def real_seal_state() -> dict:
    return {p.name: {"files": {str(f.relative_to(p)): (sha256(f) if os.access(f, os.R_OK) else f"mode_{oct(f.stat().st_mode)}")
                               for f in sorted(p.rglob("*")) if f.is_file()},
                     "marker": data.final_marker_path(p).exists()}
            for p in sorted(REAL_SEALED_ROOT.iterdir()) if p.is_dir()}


def fixture_from_development(dataset_dir: Path, staging: Path) -> dict:
    for kind in ("packets", "truth"):
        (staging / kind).mkdir(parents=True, exist_ok=True)
        with open(staging / kind / "final.jsonl", "w", encoding="utf-8") as out:
            for line in (dataset_dir / kind / "development.jsonl").read_text(encoding="utf-8").splitlines():
                if line:
                    row = json.loads(line)
                    row["partition"] = "final"
                    out.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    rows = (staging / "packets/final.jsonl").read_text(encoding="utf-8").splitlines()
    episodes = {json.loads(r)["episode_id"] for r in rows}
    counts = {"final_worlds": len(episodes), "final_episodes": len(episodes), "final_packets": len(rows)}
    (staging / "export_meta.json").write_text(json.dumps({"counts": counts, "fixture": "development relabelled final"}))
    return counts


def build_document(r15: dict, section: dict) -> dict:
    counts = {arm: r15["arms"][arm]["parameter_count"] for arm in ("arm1", "arm2", "arm3", "arm4")}
    draft = prereg.build_draft(data_identity=r15["data_identity"], parameter_counts=counts, created_unix=time.time(),
                               experiment_id=spec.FINAL_EXPERIMENT_ID, budget_registration=spec.R11_BUDGET_REGISTRATION)
    draft["arms"] = json.loads(json.dumps(r15["arms"]))
    draft["evaluation"] = json.loads(json.dumps(r15["evaluation"]))
    draft["training_protocol"]["eval_batches"] = int(spec.TIMING["eval_batches"])
    draft["final_eval"] = section
    smoke = json.loads((REPO / "reports/V9-P9/r1-archive/smoke_metrics.json").read_text())
    return prereg.build_frozen(draft, smoke=smoke, data_identity=r15["data_identity"])


def main() -> int:
    production_before = sha256(PRODUCTION / "control.sqlite3")
    real_before = real_seal_state()
    workdir = Path(tempfile.mkdtemp(prefix="s1-final-dryrun-"))
    host = workdir / "host"
    copy_root = host / "artifacts/v9/s1/phase1"
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRODUCTION, copy_root)
    shutil.copy2(REPO / "RESEARCH_LOG.md", host / "RESEARCH_LOG.md")
    original = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG, spec.FINAL_SEALED_ROOT, spec.FINAL_DATA_PLAN)
    result: dict = {}
    try:
        spec.FINAL_SEALED_ROOT = workdir / "fixture-sealed"
        counts = fixture_from_development(data.resolve_dataset_dir(PRODUCTION), workdir / "fixture-staging")
        record = data.seal_final_dataset(workdir / "fixture-staging", sealed_root=spec.FINAL_SEALED_ROOT,
                                         sealed_by="dryrun", counts=counts)
        spec.FINAL_DATA_PLAN = dict(spec.FINAL_DATA_PLAN, worlds=counts["final_worlds"])
        section = {"sealed_dataset_digest": record["dataset_digest"], "wall_seconds": spec.FINAL_EVAL_WALL_SECONDS,
                   "expected_counts": counts,
                   "data_plan": dict(spec.FINAL_DATA_PLAN, families=list(spec.FINAL_DATA_PLAN["families"])),
                   "registration": "dry run fixture (development relabelled final)"}
        r15 = json.loads((PRODUCTION / "r15/pre_registration.json").read_text(encoding="utf-8"))
        document = build_document(r15, section)
        doc_path = copy_root / "dryrun_final_pre_registration.json"
        doc_path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        digest = prereg.document_sha256(document)
        prereg.write_sha256_file(doc_path, digest)
        log = host / "RESEARCH_LOG.md"
        text = log.read_text(encoding="utf-8")
        current = prereg.APPROVAL_TEMPLATE.format(document_sha256=spec.FINAL_INHERITANCE["sources"][spec.R15_EXPERIMENT_ID]["source_preregistration_sha256"])
        assert text.count(current + "\n") == 1
        log.write_text(text.replace(current + "\n", prereg.APPROVAL_TEMPLATE.format(document_sha256=digest) + "\n"), encoding="utf-8")
        assert log.resolve() != (REPO / "RESEARCH_LOG.md").resolve()
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = host, copy_root, log
        started = time.perf_counter()
        first = worker.run_worker("final-eval", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                  wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS, prereg_path=doc_path)
        elapsed = time.perf_counter() - started
        second = worker.run_worker("final-eval", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                   wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS, prereg_path=doc_path)
        details = first.get("details") or {}
        cells = details.get("cells") or {}
        result = {
            "first": {"status": first.get("status"), "refused_stage": first.get("refused_stage"), "error": first.get("error"),
                      "run_id": first.get("run_id"), "elapsed_s": elapsed,
                      "completed_cells": details.get("completed_cells"), "error_cells": details.get("error_cells"),
                      "call_plan": details.get("call_plan"),
                      "cells": {k: {"status": v.get("status"), "partition": v.get("partition"),
                                    "nll": (v.get("unseen_map_generalization") or {}).get("prediction_nll_mean")
                                    if isinstance(v.get("unseen_map_generalization"), dict) else None,
                                    "error": v.get("error")} for k, v in cells.items()}},
            "second": {"status": second.get("status"), "refused_stage": second.get("refused_stage")},
            "fixture_marker_created": data.final_marker_path(spec.FINAL_SEALED_ROOT / record["dataset_digest"]).exists(),
        }
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG, spec.FINAL_SEALED_ROOT, spec.FINAL_DATA_PLAN = original
        for path in (workdir / "fixture-sealed").rglob("*") if (workdir / "fixture-sealed").exists() else []:
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
        if (workdir / "fixture-sealed").exists():
            os.chmod(workdir / "fixture-sealed", 0o755)
    result["production_untouched"] = sha256(PRODUCTION / "control.sqlite3") == production_before
    result["real_seal_untouched"] = real_seal_state() == real_before and not any(v["marker"] for v in real_before.values())
    checks = {
        "first_completed": result["first"]["status"] == "completed",
        "ten_cells_completed": result["first"]["completed_cells"] == 10 and not result["first"]["error_cells"],
        "all_trainable_cells_on_final": all(v["partition"] == "final" for k, v in result["first"]["cells"].items() if k != "arm1"),
        "second_refused": result["second"]["status"] == "refused",
        "fixture_marker_created": result["fixture_marker_created"],
        "production_untouched": result["production_untouched"],
        "real_seal_untouched": result["real_seal_untouched"],
    }
    result["checks"] = checks
    result["all_passed"] = all(checks.values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "second": result["second"], "elapsed_s": result["first"]["elapsed_s"],
                      "error": result["first"]["error"], "error_cells": result["first"]["error_cells"]}, indent=1))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if result["all_passed"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
