"""Prepare the final-evaluation draft from the r15 draft of record (ainerzero.V9.P59).

Same scientific rows as r15 (arms, data identity, metrics, query limit, notes); identity
s1-phase1-20261028-final; nine inherited cells (spec.FINAL_INHERITANCE); and the final_eval
section bound to the sealed dataset recorded in ../logs/sealed-record.json (digest/counts only).
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import prereg, spec  # noqa: E402

SRC = REPO / "artifacts/v9/s1/phase1"
DST = SRC / "final"
BASE = SRC / "r15"
SEALED = Path(__file__).resolve().parents[1] / "logs" / "sealed-record.json"


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / "dataset_ref.json", DST / "dataset_ref.json")
    old = json.loads((BASE / "draft_preregistration.json").read_text(encoding="utf-8"))
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))["record"]
    counts = {arm: old["arms"][arm]["parameter_count"] for arm in ("arm1", "arm2", "arm3", "arm4")}
    draft = prereg.build_draft(data_identity=old["data_identity"], parameter_counts=counts, created_unix=time.time(),
                               experiment_id=spec.FINAL_EXPERIMENT_ID, budget_registration=spec.R11_BUDGET_REGISTRATION)
    draft["arms"] = copy.deepcopy(old["arms"])
    draft["evaluation"] = {"query_limit": int(old["evaluation"]["query_limit"]),
                           "reporting_notes": list(old["evaluation"]["reporting_notes"])}
    draft["training_protocol"]["eval_batches"] = int(spec.TIMING["eval_batches"])
    draft["final_eval"] = {
        "sealed_dataset_digest": sealed["dataset_digest"],
        "sealed_dir": f"artifacts/v9/s1/final-sealed/{sealed['dataset_digest']}",
        "sealed_files": sealed["files"],
        "wall_seconds": spec.FINAL_EVAL_WALL_SECONDS,
        "expected_counts": sealed["counts"],
        "data_plan": dict(spec.FINAL_DATA_PLAN, families=list(spec.FINAL_DATA_PLAN["families"])),
        "registration": "RESEARCH_LOG R20261028-S1-phase1-final-eval",
        "read_once": "final-eval creates <digest>.READ_ONCE.json exclusively before the first read; any later "
        "final-eval invocation is refused; no other code path reads the final partition",
    }
    out = DST / "draft_preregistration.json"
    out.write_text(json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    ok = (draft["experiment_id"] == spec.FINAL_EXPERIMENT_ID and draft["arms"] == old["arms"]
          and draft["inheritance"] == json.loads(json.dumps(spec.FINAL_INHERITANCE))
          and draft["final_eval"]["expected_counts"] == {"final_worlds": 200, "final_episodes": 200, "final_packets": 950})
    print(json.dumps({"ok": ok, "draft": str(out), "sealed_digest": sealed["dataset_digest"]}))
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
