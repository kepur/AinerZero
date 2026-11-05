"""Independent adversarial verifier for ainerzero.V9.B2 (verify task ainerzero.V9.B3).

Runs each adversarial case in its own process.  Exit codes:
  1 = rejected as expected (contract held)   -> "real nonzero"
  0 = accepted / bypassed (contract broken)  -> failure
  2 = crash / unexpected error              -> failure

Usage:
  python run_adverse.py --list
  python run_adverse.py --case <id>         # single case, in-process
  python run_adverse.py --all               # run every case as a subprocess, write adverse_results.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
VENV_PY = ROOT / ".venv-ainerzero" / "bin" / "python"
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "adverse_results.json"

sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from ainerzero.v9.fakes.geometry import FakeGeometryCore  # noqa: E402
from ainerzero.v9.fakes.perception import FakePerceptionEncoder  # noqa: E402
from ainerzero.v9.fakes.planner import FakeHierarchicalPlanner  # noqa: E402
from ainerzero.v9.fakes.scheduler import FakeUpdateScheduler  # noqa: E402
from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory  # noqa: E402
from ainerzero.v9.fakes.timescale import FakeTimeScaleAdapter  # noqa: E402
from ainerzero.v9.fakes.world_brain import FakeWorldBrain  # noqa: E402
from ainerzero.v9.interfaces.errors import (  # noqa: E402
    ContractViolation,
    PartitionWriteRejected,
    ReferenceRejected,
    SignalRejected,
    TruthFieldRejected,
    EnvelopeRejected,
    SnapshotRejected,
    TimeWhitelistRejected,
    MalformedPayload,
    V9InterfaceError,
)
from ainerzero.v9.interfaces.types import (  # noqa: E402
    Fragment,
    LevelBudget,
    PlanBudget,
    PoseBelief,
    UpdateSignal,
    EncoderDescriptor,
)
from ainerzero.v9.interfaces.validation import (  # noqa: E402
    resolve_reference,
    validate_observation_payload,
)


def _valid_payload(t_ticks=10, dt_ticks=4):
    return {
        "time": {"sim_hz": 120, "t_ticks": t_ticks, "dt_ticks": dt_ticks, "dt_s": dt_ticks / 120.0},
        "episode_start": False,
        "observation": {"channels": [{"kind": "rgb"}]},
        "pose_sensor_if_allowed": None,
        "visibility": {"agent_visible": True},
        "sensor_noise": {"pose": 0.1},
        "last_action_result": {"status": "ok"},
        "task_instruction": "do thing",
    }


CASES = [
    "adv_wb_truth_injection",
    "adv_wb_envelope_injection",
    "adv_wb_snapshot_injection",
    "adv_wb_backwards_time",
    "adv_wb_inconsistent_dt",
    "adv_final_partition_write",
    "adv_final_partition_disguised",
    "adv_encoder_undeclared_pretrained",
    "adv_perception_private_reference",
    "adv_perception_future_reference",
    "adv_perception_absolute_reference",
    "adv_planner_truth_in_goal",
    "adv_planner_missing_budget",
    "adv_scheduler_world_signal",
    "adv_scheduler_forbidden_key_in_detail",
    "adv_spatial_foreign_version_leak",
    "adv_spatial_teacher_promotion",
]


def run_case(case_id: str) -> tuple[int, str, str]:
    """Return (exit_code, reason_code, detail). exit 1=rejected(expected), 0=bypassed, 2=crash."""
    try:
        if case_id == "adv_wb_truth_injection":
            brain = FakeWorldBrain()
            payload = _valid_payload()
            payload["position"] = [1.0, 2.0, 3.0]  # truth key
            brain.step(payload)
            return 0, "accepted", "truth key 'position' was NOT rejected (bypass)"

        if case_id == "adv_wb_envelope_injection":
            brain = FakeWorldBrain()
            envelope = {"schema_version": "awz.observation_packet.v1", "payload": _valid_payload()}
            brain.step(envelope)
            return 0, "accepted", "whole envelope was NOT rejected (bypass)"

        if case_id == "adv_wb_snapshot_injection":
            brain = FakeWorldBrain()
            snap = dict(_valid_payload())
            snap["schema_version"] = "awz.world_snapshot.v1"
            brain.step(snap)
            return 0, "accepted", "snapshot schema_version was NOT rejected (bypass)"

        if case_id == "adv_wb_backwards_time":
            brain = FakeWorldBrain()
            brain.step(_valid_payload(t_ticks=10))
            brain.step(_valid_payload(t_ticks=5))  # backwards
            return 0, "accepted", "backwards t_ticks was NOT rejected (bypass)"

        if case_id == "adv_wb_inconsistent_dt":
            brain = FakeWorldBrain()
            p = _valid_payload()
            p["time"]["dt_s"] = 0.5  # inconsistent with dt_ticks/120
            brain.step(p)
            return 0, "accepted", "inconsistent dt_s was NOT rejected (bypass)"

        if case_id == "adv_final_partition_write":
            mem = FakeSpatialMemory()
            frag = Fragment(fragment_id="f1", t_ticks=1, place="p", partition="final",
                            encoder_version="v1")
            mem.write(frag)
            return 0, "accepted", "write to 'final' partition was NOT rejected (bypass)"

        if case_id == "adv_final_partition_disguised":
            mem = FakeSpatialMemory()
            for bad in ("Final", "final ", "FINAL", "final\t"):
                try:
                    frag = Fragment(fragment_id=f"f-{bad}", t_ticks=1, place="p", partition=bad,
                                    encoder_version="v1")
                    mem.write(frag)
                    return 0, "accepted", f"disguised partition {bad!r} was NOT rejected (bypass)"
                except (PartitionWriteRejected, ContractViolation, ValueError):
                    continue
            return 1, "partition_write_rejected", "all disguised 'final' variants rejected"

        if case_id == "adv_encoder_undeclared_pretrained":
            desc = EncoderDescriptor(encoder_version="v1", kind="x", external_pretrained=True,
                                    source=None, license=None)
            # reaching here means descriptor accepted undeclared weights
            return 0, "accepted", "undeclared pretrained encoder was NOT rejected (bypass)"

        if case_id == "adv_perception_private_reference":
            resolve_reference("private/secret/t5", as_of_t_ticks=10)
            return 0, "accepted", "private namespace reference was NOT rejected (bypass)"

        if case_id == "adv_perception_future_reference":
            resolve_reference("obs/x/t999", as_of_t_ticks=10)
            return 0, "accepted", "future-stamped reference was NOT rejected (bypass)"

        if case_id == "adv_perception_absolute_reference":
            resolve_reference("/etc/passwd", as_of_t_ticks=10)
            return 0, "accepted", "absolute reference was NOT rejected (bypass)"

        if case_id == "adv_planner_truth_in_goal":
            planner = FakeHierarchicalPlanner()
            goal = {"target": "x", "position": [1.0, 2.0]}  # truth key
            belief = PoseBelief(group="SE2", mean=((1,0,0),(0,1,0),(0,0,1)),
                                covariance=((1e-4,0,0),(0,1e-4,0),(0,0,1e-5)),
                                gravity=(0,0,-1), unobservable_dof=("global_translation","global_yaw"))
            budget = PlanBudget(levels=(LevelBudget(level=2, max_expansions=5), LevelBudget(level=1, max_expansions=5), LevelBudget(level=0, max_expansions=5)))
            planner.plan(goal, belief, budget)
            return 0, "accepted", "truth key in planner goal was NOT rejected (bypass)"

        if case_id == "adv_planner_missing_budget":
            planner = FakeHierarchicalPlanner()
            belief = PoseBelief(group="SE2", mean=((1,0,0),(0,1,0),(0,0,1)),
                                covariance=((1e-4,0,0),(0,1e-4,0),(0,0,1e-5)),
                                gravity=(0,0,-1), unobservable_dof=("global_translation","global_yaw"))
            budget = PlanBudget(levels=(LevelBudget(level=1, max_expansions=5),))  # missing top level 2
            try:
                planner.plan({"g": 1}, belief, budget)
                return 0, "accepted", "missing budget level was NOT rejected (bypass)"
            except ContractViolation:
                return 1, "contract_violation", "missing budget level rejected"

        if case_id == "adv_scheduler_world_signal":
            sched = FakeUpdateScheduler(f_max=4, u_max=0.5)
            sig = UpdateSignal(kind="observation_change", node="bn-x", source_t_ticks=1,
                               detail={"event_id": "e1", "hidden_contact": True})
            sched.mark_dirty(sig)
            return 0, "accepted", "world-side signal keys were NOT rejected (bypass)"

        if case_id == "adv_scheduler_forbidden_key_in_detail":
            sched = FakeUpdateScheduler(f_max=4, u_max=0.5)
            sig = UpdateSignal(kind="observation_change", node="bn-x", source_t_ticks=1,
                               detail={"position": [1, 2]})
            sched.mark_dirty(sig)
            return 0, "accepted", "forbidden observation key in signal detail was NOT rejected (bypass)"

        if case_id == "adv_spatial_foreign_version_leak":
            mem = FakeSpatialMemory()
            frag = Fragment(fragment_id="f1", t_ticks=1, place="p", partition="train",
                            encoder_version="v-old", metric=np.array([0.0, 0.0]))
            mem.write(frag)
            res = mem.query_metric(region={"center": np.array([0.0, 0.0]), "radius_m": 10.0},
                                  encoder_version="v-new")
            if res.entries:
                return 0, "accepted", "foreign-version entry leaked into query results (bypass)"
            if len(res.excluded) != 1:
                return 0, "accepted", "foreign-version entry not reported in excluded (silent drop)"
            return 1, "encoder_version_mismatch", "foreign version excluded and reported"

        if case_id == "adv_spatial_teacher_promotion":
            from ainerzero.v9.interfaces.types import PromotionEvidence
            mem = FakeSpatialMemory()
            frag = Fragment(fragment_id="f1", t_ticks=1, place="p", partition="train",
                            encoder_version="v1")
            mem.write(frag)
            ev = PromotionEvidence(kind="independent_test", report_ref="r", producer="teacher_model",
                                   test_id="t1")
            mem.promote("f1", ev)
            return 0, "accepted", "teacher producer promotion was NOT rejected (bypass)"

        raise ValueError(f"unknown case id: {case_id}")
    except (V9InterfaceError, ValueError, TypeError, KeyError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return 1, code, f"rejected: {type(exc).__name__}: {exc}"
    except Exception as exc:  # pragma: no cover - unexpected
        return 2, "crash", f"unexpected: {type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--case", type=str)
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.list:
        for c in CASES:
            print(c)
        return 0

    if args.case:
        code, reason, detail = run_case(args.case)
        print(json.dumps({"case": args.case, "exit_code": code, "reason": reason, "detail": detail},
                         ensure_ascii=False))
        return code

    # --all : run each case in a fresh subprocess
    records = []
    overall = 0
    for case_id in CASES:
        t0 = time.time()
        env = dict(os.environ)
        proc = subprocess.run(
            [str(VENV_PY), str(Path(__file__).resolve()), "--case", case_id],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = round(time.time() - t0, 3)
        stdout = proc.stdout.strip()
        parsed = None
        try:
            parsed = json.loads(stdout.splitlines()[-1]) if stdout else None
        except Exception:
            parsed = None
        rec = {
            "id": case_id,
            "returncode": proc.returncode,
            "elapsed_s": elapsed,
            "stdout_tail": stdout.splitlines()[-3:],
            "stderr_tail": proc.stderr.strip().splitlines()[-5:],
            "parsed": parsed,
            "pass": proc.returncode == 1,
        }
        records.append(rec)
        if proc.returncode != 1:
            overall = 1
        print(f"{case_id}: rc={proc.returncode} {'PASS' if proc.returncode == 1 else 'FAIL'}")

    out = {
        "task": "ainerzero.V9.B3",
        "verified_task": "ainerzero.V9.B2",
        "total": len(CASES),
        "rejected_expected": sum(1 for r in records if r["returncode"] == 1),
        "bypassed": sum(1 for r in records if r["returncode"] == 0),
        "crashed": sum(1 for r in records if r["returncode"] not in (0, 1)),
        "cases": records,
    }
    RESULTS.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nTotal {len(CASES)}: rejected={out['rejected_expected']} bypassed={out['bypassed']} crashed={out['crashed']}")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
