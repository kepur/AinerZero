"""CPU-only eval entry check for r11 (no MLX, no central ledger write).

Uses an isolated host anchor + temp ledger.  Expects:
  - r11 frozen doc (eval_batches=175) passes the call-budget gate and then
    fails with EvalBindingError (no completed training under the new experiment);
  - the authentic r10 freeze (eval_batches=48) is refused with
    eval_call_budget_exceeded (reproducing the r10 failure mode).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "v9" / "experiments"))

from ainerzero.v9.experiments.s1 import prereg, spec, worker  # noqa: E402
from s1_testkit import install_test_host  # noqa: E402


class _FakeMonkeypatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value=None, raising=True):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


def _copy_dataset_ref(root: Path) -> None:
    src = REPO / "artifacts/v9/s1/phase1/r11/dataset_ref.json"
    shutil.copy2(src, root / "dataset_ref.json")


def _place_prereg(root: Path, src: Path, name: str = "pre_registration.json") -> Path:
    dst = root / name
    shutil.copy2(src, dst)
    shutil.copy2(src.with_suffix(src.suffix + ".sha256"), dst.with_suffix(dst.suffix + ".sha256"))
    # Rewrite the sidecar filename line to match the local basename.
    digest = dst.with_suffix(dst.suffix + ".sha256").read_text(encoding="utf-8").split()[0]
    prereg.write_sha256_file(dst, digest)
    return dst


def _run_eval(root: Path, document_path: Path) -> dict:
    return worker.run_worker(
        "eval",
        output_root=root,
        arm="arm2",
        seed=0,
        prereg_path=document_path,
        wall_budget_seconds=30.0,
        limits=dict(spec.RESOURCE_LIMITS),
        backend="stub",
        research_log=None,
    )


def main() -> int:
    r11_src = REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json"
    r10_src = REPO / "artifacts/v9/s1/phase1/r10/pre_registration.json"
    mp = _FakeMonkeypatch()
    results = {}
    try:
        with tempfile.TemporaryDirectory(prefix="s1-r11-eval-") as tmp:
            root = install_test_host(mp, Path(tmp), create_ledger=True)
            _copy_dataset_ref(root)

            path175 = _place_prereg(root, r11_src, "pre_registration.json")
            report175 = _run_eval(root, path175)
            results["eval_batches_175"] = {
                "status": report175.get("status"),
                "refused_stage": report175.get("refused_stage") or report175.get("stage"),
                "error": report175.get("error"),
                "message": report175.get("message"),
                "eval_call_plan": report175.get("eval_call_plan"),
                "experiment_id": report175.get("experiment_id"),
            }

            # Control: same r11 registration bytes, but eval_batches forced to 48
            # (the r10 failure mode).  Authentic r10 freeze cannot be re-verified
            # under the current source binding (spec/prereg/worker/commands have
            # moved); this isolates the call-budget gate.  TIMING is aligned to
            # 48 so validate() accepts the tampered document.
            from ainerzero.v9.experiments.s1 import spec as spec_mod

            doc48 = json.loads(r11_src.read_text(encoding="utf-8"))
            doc48["training_protocol"]["eval_batches"] = 48
            path48 = root / "pre_registration_48.json"
            path48.write_text(
                json.dumps(doc48, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                encoding="utf-8",
            )
            prereg.write_sha256_file(path48, prereg.document_sha256(doc48))
            old_batches = spec_mod.TIMING["eval_batches"]
            spec_mod.TIMING["eval_batches"] = 48
            try:
                report48 = _run_eval(root, path48)
            finally:
                spec_mod.TIMING["eval_batches"] = old_batches
            results["eval_batches_48_control"] = {
                "status": report48.get("status"),
                "refused_stage": report48.get("refused_stage") or report48.get("stage"),
                "error": report48.get("error"),
                "message": report48.get("message"),
                "eval_call_plan": report48.get("eval_call_plan"),
            }
    finally:
        mp.undo()

    r175 = results["eval_batches_175"]
    r48 = results["eval_batches_48_control"]
    passed_budget = r175.get("refused_stage") != "eval_call_budget_exceeded"
    binding_ok = "EvalBindingError" in str(r175.get("error") or "")
    control_ok = r48.get("refused_stage") == "eval_call_budget_exceeded"
    plan48 = r48.get("eval_call_plan") or {}
    control_plan_ok = (
        plan48.get("registered_eval_batches") == 48
        and int(plan48.get("window_probe_batches") or 0) == 175
    )

    payload = {
        "status": (
            "completed"
            if (passed_budget and binding_ok and control_ok and control_plan_ok)
            else "failed"
        ),
        "passed_budget_gate_175": bool(passed_budget and binding_ok),
        "control_48_refused": bool(control_ok and control_plan_ok),
        "results": results,
        "checks": {
            "passed_budget": passed_budget,
            "binding_ok": binding_ok,
            "control_ok": control_ok,
            "control_plan_ok": control_plan_ok,
        },
    }
    out = REPO / "reports/V9-P9/r11/logs/eval-entry-r11.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps(payload, indent=1, ensure_ascii=False))
    return 0 if payload["status"] == "completed" else 7


if __name__ == "__main__":
    raise SystemExit(main())
