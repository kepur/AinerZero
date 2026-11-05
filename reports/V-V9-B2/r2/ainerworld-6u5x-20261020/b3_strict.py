"""ainerzero.V9.B3 r2 strict adversarial verifier (ainerworld-6u5x).
Each case runs in its own subprocess. A case PASSES only if the child reports the exact
expected exception class AND code (or, for legit samples, no exception), and the child rc agrees.
Any other exception / Traceback / import error = FAIL.  --disable <guard> monkeypatches one guard
off IN-PROCESS ONLY (source never edited); those controls must turn red.  Exit 1 if any check fails.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, traceback
from pathlib import Path
ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero'); HERE = Path(__file__).resolve().parent
PY = ROOT/'.venv-ainerzero/bin/python'

def _payload(t=10, dt=4, **extra):
    p = {"time": {"sim_hz": 120, "t_ticks": t, "dt_ticks": dt, "dt_s": dt/120.0}, "episode_start": False,
         "observation": {"channels": [{"kind": "rgb"}]}, "pose_sensor_if_allowed": None,
         "visibility": {"agent_visible": True}, "sensor_noise": {"pose": 0.1},
         "last_action_result": {"status": "ok"}, "task_instruction": "go"}
    p.update(extra); return p

def _belief():
    from ainerzero.v9.interfaces.types import PoseBelief
    return PoseBelief(group="SE2", mean=((1,0,0),(0,1,0),(0,0,1)), covariance=((1e-4,0,0),(0,1e-4,0),(0,0,1e-5)),
                      gravity=(0,0,-1), unobservable_dof=("global_translation","global_yaw"))

def _budget(levels=(2,1,0)):
    from ainerzero.v9.interfaces.types import LevelBudget, PlanBudget
    return PlanBudget(levels=tuple(LevelBudget(level=l, max_expansions=5) for l in levels))

def _enc_payload(uri, t=10):
    return _payload(t=t, observation={"channels": [{"kind": "rgb", "uri": uri}]})

# ---------- cases: name -> (fn, expected) ; expected = ("raise", Class, code) | ("accept",) ----------
def c_truth_nested():  # truth key buried in visibility
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    FakeWorldBrain().step(_payload(visibility={"agent_visible": True, "detail": [{"world_pose": [1, 2, 0]}]}))
def c_truth_reset_meta():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    FakeWorldBrain().reset({"note": "x", "episode_seed": 7})
def c_truth_planner_goal():
    from ainerzero.v9.fakes.planner import FakeHierarchicalPlanner
    FakeHierarchicalPlanner().plan({"target": {"gt_xy": [1, 2]}}, _belief(), _budget())
def c_envelope():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    FakeWorldBrain().step({"schema_version": "awz.observation_packet.v1.1", "payload": _payload()})
def c_snapshot():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    FakeWorldBrain().step(_payload(schema_version="awz.world_snapshot.v1"))
def c_time_extra_key():  # frame index smuggled into time whitelist
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    p = _payload(); p["time"]["frame_index"] = 3; FakeWorldBrain().step(p)
def c_time_dt_mismatch():  # dt_s derived from a frame rate (30fps) not 120Hz ticks
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    p = _payload(); p["time"]["dt_s"] = 4/30; FakeWorldBrain().step(p)  # 4 frames at 30fps, not 4 ticks
def c_time_bool_tick():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    p = _payload(); p["time"]["t_ticks"] = True; FakeWorldBrain().step(p)
def c_time_backwards():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    b = FakeWorldBrain(); b.step(_payload(t=40)); b.step(_payload(t=39))
def c_final_setattr():  # frozen dataclass bypass -> write() guard must still refuse
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment
    f = Fragment(fragment_id="f", t_ticks=1, place="p", partition="train", encoder_version="v1")
    object.__setattr__(f, "partition", "final"); FakeSpatialMemory().write(f)
def c_quarantine_setattr():
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment
    f = Fragment(fragment_id="f", t_ticks=1, place="p", partition="train", encoder_version="v1")
    object.__setattr__(f, "partition", "quarantine"); FakeSpatialMemory().write(f)
def c_final_ctor():  # plain final fragment through write()
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment
    FakeSpatialMemory().write(Fragment(fragment_id="f", t_ticks=1, place="p", partition="final", encoder_version="v1"))
def c_pretrained_undeclared():
    from ainerzero.v9.interfaces.types import EncoderDescriptor
    EncoderDescriptor(encoder_version="v1", kind="vit", external_pretrained=True, source="hf/x", license=None)
def c_ref_private():
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("private/answers/t5"))
def c_ref_future():
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("obs/cam/t11", t=10))
def c_ref_remote():
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("https://x/obs/t1"))
def c_sched_world_key():
    from ainerzero.v9.fakes.scheduler import FakeUpdateScheduler, WORLD_SIGNAL_KEYS
    from ainerzero.v9.interfaces.types import UpdateSignal
    FakeUpdateScheduler(f_max=4, u_max=0.5).mark_dirty(UpdateSignal(kind="observation_change", node="bn-a", source_t_ticks=1, detail={WORLD_SIGNAL_KEYS[0]: 1}))
def c_promote_untyped():
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment
    m = FakeSpatialMemory(); m.write(Fragment(fragment_id="f", t_ticks=1, place="p", partition="train", encoder_version="v1"))
    m.promote("f", {"kind": "independent_test", "producer": "teacher", "report_ref": "r", "test_id": "t"})
def c_singular_noise():
    import numpy as np
    from ainerzero.v9.fakes.geometry import FakeGeometryCore
    FakeGeometryCore().update(_belief(), np.zeros(3), {"H": np.eye(3), "R": np.zeros((3, 3))})
# ---- bypass probes (should be rejected per contract; failure = finding) ----
def p_ref_traversal():
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("obs/../private/answers"))
def p_ref_future_ext():  # future tick hidden by a file extension
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("obs/cam/t999.png", t=10))
def p_ref_frame_index():  # frame index masquerading as time inside a URI
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    FakePerceptionEncoder().encode(_enc_payload("obs/cam/frame_000999", t=10))
def p_time_stalled():  # t_ticks does not advance while dt_ticks claims 4 ticks passed
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    b = FakeWorldBrain(); b.step(_payload(t=10, dt=4)); b.step(_payload(t=10, dt=4))
def p_time_jump():  # t jumps 400 ticks while dt claims 4
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    b = FakeWorldBrain(); b.step(_payload(t=10, dt=4)); b.step(_payload(t=410, dt=4))
def p_truth_case():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    FakeWorldBrain().step(_payload(visibility={"Position": [1, 2]}))
def p_teacher_alias():
    from ainerzero.v9.interfaces.types import PromotionEvidence
    PromotionEvidence(kind="independent_test", report_ref="r", producer="distilled-teacher-v2", test_id="t")
def p_llm_alias():
    from ainerzero.v9.interfaces.types import PromotionEvidence
    PromotionEvidence(kind="independent_test", report_ref="r", producer="LLM-gpt", test_id="t")
# ---- legit samples (must be accepted) ----
def l_step_seq():
    from ainerzero.v9.fakes.world_brain import FakeWorldBrain
    b = FakeWorldBrain(); b.step(_payload(t=0, dt=0)); s = b.step(_payload(t=4, dt=4)); assert s.t_ticks == 4 and abs(s.dt_s - 4/120) < 1e-12
def l_write_train_dev():
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment
    m = FakeSpatialMemory()
    for i, part in enumerate(("train", "development")):
        m.write(Fragment(fragment_id=f"f{i}", t_ticks=1, place="p", partition=part, encoder_version="v1"))
def l_pretrained_declared():
    from ainerzero.v9.interfaces.types import EncoderDescriptor
    d = EncoderDescriptor(encoder_version="v1", kind="vit", external_pretrained=True, source="hf/x", license="apache-2.0"); assert "external_pretrained" in d.capability_note
def l_ref_ok():
    from ainerzero.v9.fakes.perception import FakePerceptionEncoder
    e = FakePerceptionEncoder().encode(_enc_payload("obs/cam/t10", t=10)); assert e.resolved_references == ("obs/cam/t10",)
def l_plan_ok():
    from ainerzero.v9.fakes.planner import FakeHierarchicalPlanner
    FakeHierarchicalPlanner().plan({"target": "door"}, _belief(), _budget())
def l_sched_ok():
    from ainerzero.v9.fakes.scheduler import FakeUpdateScheduler
    from ainerzero.v9.interfaces.types import UpdateSignal
    FakeUpdateScheduler(f_max=4, u_max=0.5).mark_dirty(UpdateSignal(kind="observation_change", node="bn-a", source_t_ticks=1, detail={}))
def l_promote_ok():
    from ainerzero.v9.fakes.spatial_memory import FakeSpatialMemory
    from ainerzero.v9.interfaces.types import Fragment, PromotionEvidence
    m = FakeSpatialMemory(); m.write(Fragment(fragment_id="f", t_ticks=1, place="p", partition="train", encoder_version="v1"))
    m.promote("f", PromotionEvidence(kind="independent_test", report_ref="r", producer="independent_verifier", test_id="t"))

E = lambda cls, code=None: ("raise", cls, code)
CASES = {
 "truth_nested": (c_truth_nested, E("TruthFieldRejected", "truth_field_rejected")),
 "truth_reset_meta": (c_truth_reset_meta, E("TruthFieldRejected", "truth_field_rejected")),
 "truth_planner_goal": (c_truth_planner_goal, E("TruthFieldRejected", "truth_field_rejected")),
 "envelope": (c_envelope, E("EnvelopeRejected", "envelope_rejected")),
 "snapshot": (c_snapshot, E("SnapshotRejected", "snapshot_rejected")),
 "time_extra_frame_index": (c_time_extra_key, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "time_dt_30fps": (c_time_dt_mismatch, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "time_bool_tick": (c_time_bool_tick, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "time_backwards": (c_time_backwards, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "final_setattr_write": (c_final_setattr, E("PartitionWriteRejected", "partition_write_rejected")),
 "quarantine_setattr_write": (c_quarantine_setattr, E("PartitionWriteRejected", "partition_write_rejected")),
 "final_write": (c_final_ctor, E("PartitionWriteRejected", "partition_write_rejected")),
 "pretrained_undeclared": (c_pretrained_undeclared, E("ValueError")),
 "ref_private": (c_ref_private, E("ReferenceRejected", "reference_rejected")),
 "ref_future": (c_ref_future, E("ReferenceRejected", "reference_rejected")),
 "ref_remote": (c_ref_remote, E("ReferenceRejected", "reference_rejected")),
 "sched_world_key": (c_sched_world_key, E("SignalRejected", "signal_rejected")),
 "promote_untyped": (c_promote_untyped, E("EvidenceRequired", "evidence_required")),
 "singular_noise": (c_singular_noise, E("SingularMeasurementNoise", "singular_measurement_noise")),
}
PROBES = {
 "probe_ref_traversal": (p_ref_traversal, E("ReferenceRejected", "reference_rejected")),
 "probe_ref_future_ext": (p_ref_future_ext, E("ReferenceRejected", "reference_rejected")),
 "probe_ref_frame_index": (p_ref_frame_index, E("ReferenceRejected", "reference_rejected")),
 "probe_time_stalled": (p_time_stalled, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "probe_time_jump": (p_time_jump, E("TimeWhitelistRejected", "time_whitelist_rejected")),
 "probe_truth_case_variant": (p_truth_case, E("TruthFieldRejected", "truth_field_rejected")),
 "probe_teacher_alias": (p_teacher_alias, E("ValueError")),
 "probe_llm_alias": (p_llm_alias, E("ValueError")),
}
LEGIT = {k: (f, ("accept",)) for k, f in {"legit_step_seq": l_step_seq, "legit_write_train_dev": l_write_train_dev,
         "legit_pretrained_declared": l_pretrained_declared, "legit_ref_ok": l_ref_ok, "legit_plan_ok": l_plan_ok,
         "legit_sched_ok": l_sched_ok, "legit_promote_ok": l_promote_ok}.items()}
# guard-off controls: (guard, case) — guard disabled in-process must make the case NOT meet expectation
def _disable(g):
    import ainerzero.v9.interfaces.validation as V
    if g == "forbidden_keys":
        V.assert_no_forbidden_keys = lambda *a, **k: None
        import ainerzero.v9.fakes.world_brain as W, ainerzero.v9.fakes.planner as P
        W.assert_no_forbidden_keys = V.assert_no_forbidden_keys; P.assert_no_forbidden_keys = V.assert_no_forbidden_keys
    elif g == "envelope_level":
        V._reject_envelope_level = lambda p: None
    elif g == "time_whitelist":
        V.validate_time_whitelist = lambda t, **k: {"sim_hz": 120, "t_ticks": int(t["t_ticks"]), "dt_ticks": int(t["dt_ticks"]), "dt_s": float(t["dt_s"])}
    elif g == "partition_writable":
        from ainerzero.v9.interfaces.spatial_memory import SpatialMemory
        SpatialMemory.require_writable = staticmethod(lambda p: None)
    elif g == "pretrained_declaration":
        from ainerzero.v9.interfaces.types import EncoderDescriptor
        EncoderDescriptor.__post_init__ = lambda self: object.__setattr__(self, "capability_note", "patched")
    elif g == "reference_resolver":
        import ainerzero.v9.fakes.perception as PE
        PE.resolve_reference = lambda uri, **k: uri
    elif g == "world_signal_keys":
        import ainerzero.v9.fakes.scheduler as S
        S.WORLD_SIGNAL_KEYS = (); S.scan_forbidden_keys = lambda *a, **k: iter(())
    elif g == "singular_noise":
        import ainerzero.v9.fakes.geometry as G
        orig = G._covariance; G._covariance = lambda v, n, strictly: orig(v, n, strictly=False)
    elif g == "evidence_typecheck":
        from ainerzero.v9.interfaces.spatial_memory import SpatialMemory
        from types import SimpleNamespace
        SpatialMemory.require_evidence = staticmethod(lambda e: SimpleNamespace(**e) if isinstance(e, dict) else e)
    else:
        raise SystemExit(f"unknown guard {g}")
CONTROLS = [("forbidden_keys", "truth_nested"), ("envelope_level", "snapshot"), ("time_whitelist", "time_dt_30fps"),
            ("partition_writable", "final_setattr_write"), ("pretrained_declaration", "pretrained_undeclared"),
            ("reference_resolver", "ref_private"), ("world_signal_keys", "sched_world_key"),
            ("singular_noise", "singular_noise"), ("evidence_typecheck", "promote_untyped")]
ALL = {**CASES, **PROBES, **LEGIT}

def child(name, guard):
    sys.path.insert(0, str(ROOT/'src'))
    fn, exp = ALL[name]
    rec = {"case": name, "guard_disabled": guard, "expected": [exp[0]] + list(exp[1:])}
    try:
        if guard: _disable(guard)
        fn(); rec.update(outcome="accepted", exc_class=None, code=None)
    except BaseException as ex:
        rec.update(outcome="raised", exc_class=type(ex).__name__, code=getattr(ex, "code", None), msg=str(ex)[:300], tb=traceback.format_exc()[-1500:])
    met = (rec["outcome"] == "accepted") if exp[0] == "accept" else (rec["outcome"] == "raised" and rec["exc_class"] == exp[1] and (exp[2] is None or rec["code"] == exp[2]))
    banned = [m for m in sys.modules if m.split('.')[0] in ("mlx", "onnxruntime", "torch")]
    rec["expectation_met"] = met; rec["banned_modules"] = banned
    print("RESULT " + json.dumps(rec, ensure_ascii=False))
    return 0 if met and not banned else 3

def run(name, guard=None):
    cmd = [str(PY), "-B", str(Path(__file__).resolve()), "--child", name] + (["--guard", guard] if guard else [])
    pr = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    tag = f"{name}{'__off_' + guard if guard else ''}"
    (HERE/'logs'/f'{tag}.log').write_text(f"$ {' '.join(cmd)}\nrc={pr.returncode}\n--stdout--\n{pr.stdout}\n--stderr--\n{pr.stderr}")
    lines = [l for l in pr.stdout.splitlines() if l.startswith("RESULT ")]
    rec = json.loads(lines[-1][7:]) if len(lines) == 1 else None
    consistent = rec is not None and ((rec["expectation_met"] and not rec["banned_modules"]) == (pr.returncode == 0)) and pr.returncode in (0, 3)
    return {"tag": tag, "rc": pr.returncode, "consistent": consistent, "rec": rec, "stderr_tail": pr.stderr[-300:]}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--child"); ap.add_argument("--guard"); a = ap.parse_args()
    if a.child: return child(a.child, a.guard)
    out = {"cases": [], "probes": [], "legit": [], "controls": []}
    for n in CASES: r = run(n); r["pass"] = r["consistent"] and r["rc"] == 0; out["cases"].append(r)
    for n in LEGIT: r = run(n); r["pass"] = r["consistent"] and r["rc"] == 0; out["legit"].append(r)
    for n in PROBES: r = run(n); r["held"] = r["consistent"] and r["rc"] == 0; r["bypass"] = r["consistent"] and r["rc"] == 3 and r["rec"]["outcome"] == "accepted"; out["probes"].append(r)
    for g, n in CONTROLS:
        base = next(x for x in out["cases"] if x["tag"] == n)
        r = run(n, g); r["turned_red"] = r["consistent"] and r["rc"] == 3 and base["pass"]; out["controls"].append(r)
    s = {"cases_pass": sum(x["pass"] for x in out["cases"]), "cases_total": len(out["cases"]),
         "legit_pass": sum(x["pass"] for x in out["legit"]), "legit_total": len(out["legit"]),
         "controls_red": sum(x["turned_red"] for x in out["controls"]), "controls_total": len(out["controls"]),
         "probes_held": sum(x["held"] for x in out["probes"]), "probes_bypassed": [x["tag"] for x in out["probes"] if x["bypass"]],
         "probes_other": [x["tag"] for x in out["probes"] if not x["held"] and not x["bypass"]]}
    out["summary"] = s
    res = HERE/'b3_strict_results.json'
    if res.exists(): raise SystemExit("refusing to overwrite results")
    res.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(s, ensure_ascii=False))
    ok = s["cases_pass"] == s["cases_total"] and s["legit_pass"] == s["legit_total"] and s["controls_red"] == s["controls_total"]
    return 0 if ok and not s["probes_bypassed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
