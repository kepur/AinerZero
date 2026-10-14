"""E13 CPU protocol tests for M2m-d; no MLX, no model calls."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ainerzero.learning import action_preservation as ap

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m2md_pool_manifest.json"
M2MC = ROOT / "artifacts" / "reports" / "m2mc-lr0003-relabel.json"


def synthetic_samples(qs=None):
    qs = qs or [1 + (i * 7) % 120 for i in range(256)]
    return [{"row": i, "world_index": i // 16, "query_tick": q, "target_tick": q - 1,
             "episode_id": f"e{i // 16}"} for i, q in enumerate(qs)]


def schedule():
    return np.asarray([[w * 16 + (u + w) % 16 for w in range(16)] for u in range(200)], dtype=np.int32)


@pytest.fixture(scope="module")
def real():
    # Portable integer fixture extracted from the M2m-c report (source SHA recorded inside).
    f = json.loads(FIXTURE.read_text())
    assert f["source"]["file_sha256"] == ap.REGISTERED_INPUT["source_report_sha256"]
    return f["samples"], f["schedule"]


def test_plan_frozen_values():
    p = ap.action_preservation_plan()
    assert p["protocol"] == "m2m_d_m2d_distilled_action_preservation_v1"
    assert p["memory_branch"]["learning_rate"] == 0.003 and p["memory_branch"]["updates"] == 200
    assert p["memory_branch"]["seeds"] == {"latent": 2203, "augmentation": 2307, "relabel_evaluation": 9103}
    assert p["keep_branch"]["lambda"] == 1.0 and p["keep_branch"]["seed"] == 3307
    assert p["units"]["total"] == 208_546 and p["seconds"]["prepaid"] == 1_610
    assert p["parameters"] == {"total": 393_232, "trainable_tail": 111_104, "frozen": 282_128}
    assert p["promotion"] is False and p["automatic_next_run"] is False


def test_real_manifest_budget_matches_c05(real):
    w = ap.preservation_windows(*real)
    assert w["teacher_qmax"] == [44, 54, 67, 60, 101, 81, 48, 123, 59, 72, 48, 111, 62, 70, 112, 102]
    assert w["units"] == {"teacher": 2254, "student": 27988, "student_feedback": 11988,
                          "padded_extra_not_executed": 812}
    assert ap.check_budget(w)["total"] == 208_546
    assert all(r["s"] == max(0, r["q"] - 4) and r["rollout_actions_ticks"][-1] <= 127 for r in w["rows"])


def test_budget_mismatch_stops():
    w = ap.preservation_windows(synthetic_samples(), schedule())
    with pytest.raises(ValueError):
        ap.check_budget(w)


@pytest.mark.parametrize("bad", ["order", "too_late", "target", "count"])
def test_windows_reject_bad_manifests(bad):
    s = synthetic_samples()
    if bad == "order":
        s[3]["row"] = 4
    elif bad == "too_late":
        s[0]["query_tick"], s[0]["target_tick"] = 125, 124
    elif bad == "target":
        s[0]["target_tick"] = 0 if s[0]["query_tick"] != 1 else 5
    else:
        s = s[:-1]
    with pytest.raises(ValueError):
        ap.preservation_windows(s, schedule())
    with pytest.raises(ValueError):
        ap.preservation_windows(synthetic_samples(), schedule()[:-1])


def test_student_window_never_reads_past_q():
    obs = list(range(129))
    acts = [10 + i for i in range(128)]
    w = ap.student_window(obs, acts, 6)
    assert w["observations"] == [2, 3, 4, 5, 6] and w["feedback_actions"] == [12, 13, 14, 15]
    assert w["rollout_actions"] == [16, 17, 18, 19] and max(w["observations"]) == 6
    w1 = ap.student_window(obs, acts, 1)
    assert w1["observations"] == [0, 1] and len(w1["feedback_actions"]) == 1  # no padding
    with pytest.raises(ValueError):
        ap.student_window(obs, acts, 125)


def test_keys_namespace_isolated_and_deterministic():
    k = ap.call_key(0, 3, 7)
    assert k == ap.call_key(0, 3, 7)
    assert len({ap.call_key(0, 3, 7), ap.call_key(1, 3, 7), ap.call_key(2, 3, 7, 1),
                ap.call_key(0, 4, 7), ap.call_key(0, 3, 8)}) == 5
    state = np.random.default_rng(2307).bit_generator.state
    ap.call_key(1, 0, 0)
    assert np.random.default_rng(2307).bit_generator.state == state
    with pytest.raises(ValueError):
        ap.call_key(2, 0, 5, 0)
    with pytest.raises(ValueError):
        ap.call_key(0, 0, 5, 1)


def test_row_keys_order_and_teacher_sharing():
    calls = ap.row_call_keys(2, 3, 6)
    assert [c[:3] for c in calls] == [("observe", 3, 0), ("feedback_imagine", 3, 0), ("feedback_observe", 4, 0),
                                       ("feedback_imagine", 4, 0), ("feedback_observe", 5, 0),
                                       ("feedback_imagine", 5, 0), ("feedback_observe", 6, 0),
                                       ("query_imagine", 6, 1), ("query_imagine", 6, 2),
                                       ("query_imagine", 6, 3), ("query_imagine", 6, 4)]
    teacher = ap.row_call_keys(2, 0, 10)
    shared = {(c[0].replace("feedback_observe", "observe"), c[1], c[2]): c[3] for c in teacher}
    for c in calls[:7]:
        assert shared[(c[0].replace("feedback_observe", "observe"), c[1], c[2])] == c[3]
    w = ap.preservation_windows(synthetic_samples(), schedule())
    assert ap.key_manifest(w)["manifest_sha256"] == ap.key_manifest(w)["manifest_sha256"]


def test_keep_loss_reference_properties():
    rng = np.random.default_rng(0)
    t = rng.normal(size=(3, 2, 8, 256))
    mask = np.ones((3, 8), bool)
    assert ap.keep_loss_reference(t, t, mask)["loss"] == pytest.approx(0, abs=1e-12)
    s = rng.normal(size=t.shape)
    full = ap.keep_loss_reference(t, s, mask)["loss"]
    assert full > 0
    mask2 = mask.copy()
    mask2[:, 4:] = False
    s2 = s.copy()
    s2[:, :, 4:] += 50  # hidden cells must not change the loss
    assert ap.keep_loss_reference(t, s2, mask2)["loss"] == pytest.approx(ap.keep_loss_reference(t, s, mask2)["loss"])
    big = ap.keep_loss_reference(t * 1e3, s * 1e3, mask)["loss"]
    assert np.isfinite(big)
    # manual KL check for one entry
    lp = t[0, 0, 0] - np.log(np.exp(t[0, 0, 0]).sum())
    lq = s[0, 0, 0] - np.log(np.exp(s[0, 0, 0]).sum())
    out = ap.keep_loss_reference(t[:1], s[:1], mask[:1])["per_row_horizon"]
    assert out[0, 0] == pytest.approx(np.mean([(np.exp(a := t[0, 0, c] - np.log(np.exp(t[0, 0, c]).sum()))
                                                * (a - (s[0, 0, c] - np.log(np.exp(s[0, 0, c]).sum())))).sum()
                                               for c in range(8)]))
    assert (np.exp(lp) * (lp - lq)).sum() >= 0


@pytest.mark.parametrize("bad", ["argmax", "nan", "no_visible", "mask_dtype"])
def test_keep_loss_rejects(bad):
    t = np.zeros((2, 2, 8, 256))
    s = np.zeros_like(t)
    m = np.ones((2, 8), bool)
    if bad == "argmax":
        t = np.zeros((2, 2, 8))
        s = t
    elif bad == "nan":
        s = s.copy()
        s[0, 0, 0, 0] = np.nan
    elif bad == "no_visible":
        m[1] = False
    else:
        m = m.astype(int)
    with pytest.raises(ValueError):
        ap.keep_loss_reference(t, s, m)


def test_combined_gradient_normalisation_and_scope():
    mem = {"a": np.full(3, 8.0), "b": np.ones(2)}
    keep = [{"a": np.full(3, float(i)), "b": np.zeros(2)} for i in range(16)]
    g = ap.combine_branch_gradients(mem, 4.0, keep)
    assert np.allclose(g["a"], 2.0 + 7.5) and np.allclose(g["b"], 0.25)
    with pytest.raises(ValueError):
        ap.combine_branch_gradients(mem, 0.0, keep)
    with pytest.raises(ValueError):
        ap.combine_branch_gradients(mem, 4.0, keep[:4])  # one micro chunk alone
    with pytest.raises(ValueError):
        ap.combine_branch_gradients(mem, 4.0, [{"a": np.ones(3)}] * 16)
    with pytest.raises(ValueError):
        ap.combine_branch_gradients({"a": np.array([np.inf]), "b": np.ones(2)}, 1.0,
                                    [{"a": np.zeros(1), "b": np.zeros(2)}] * 16)
    raw = gru_tree(front=1.0)
    out = ap.check_applied_front_gradient(raw, gru_tree())
    assert out["raw_front_gradient_l2"] > 0 and out["applied_front_gradient_l2"] == 0.0


def gru_tree(front=0.0, tail=0.0):
    tree = {}
    for name, shape in ap.GRU_LEAVES.items():
        arr = np.zeros(shape)
        mask = ap.frozen_row_mask(name)
        arr[mask] = front
        arr[~mask] = tail
        tree[name] = arr
    return tree


def binding():
    return {"protocol": ap.PROTOCOL, "teacher_checkpoint": ap.SOURCE_CHECKPOINT,
            "teacher_checkpoint_manifest_sha256": "a" * 64, "teacher_source_sha256": "b" * 64,
            "architecture": "pilot_shared_symbol_v1", "training_samples_sha256": "c" * 64,
            "schedule_sha256": "d" * 64, "windows_sha256": "e" * 64, "key_manifest_sha256": "f" * 64,
            "particles": 1, "temperature": 1.0, "mask_rule": "public_visible_at_q",
            "run_id": "00000000-0000-4000-8000-000000000001", "budget_units": 2254}


def arrays():
    return {"incoming_h": np.zeros((256, 256), np.float32),
            "teacher_logits": np.zeros((256, 2, 8, 256), np.float32),
            "visible_mask": np.ones((256, 8), bool)}


def test_teacher_cache_binding_roundtrip_and_mismatch():
    m = ap.teacher_cache_manifest(binding(), arrays())
    ap.verify_teacher_cache(m, arrays(), binding())
    for field in ("schedule_sha256", "key_manifest_sha256", "teacher_checkpoint_manifest_sha256"):
        b = binding()
        b[field] = "0" * 64
        with pytest.raises(ValueError):
            ap.verify_teacher_cache(m, arrays(), b)
    a = arrays()
    a["teacher_logits"][0, 0, 0, 0] = 1
    with pytest.raises(ValueError):
        ap.verify_teacher_cache(m, a, binding())
    forged = copy.deepcopy(m)
    forged["binding"]["run_id"] = "other"
    with pytest.raises(ValueError):
        ap.verify_teacher_cache(forged, arrays(), binding())


@pytest.mark.parametrize("bad", ["teacher", "particles", "missing", "dtype", "argmax_cache"])
def test_teacher_cache_rejects_unregistered(bad):
    b, a = binding(), arrays()
    if bad == "teacher":
        b["teacher_checkpoint"] = "m2m-c"
    elif bad == "particles":
        b["particles"] = 8
    elif bad == "missing":
        del b["run_id"]
    elif bad == "dtype":
        a["incoming_h"] = a["incoming_h"].astype(np.float64)
    else:
        a["teacher_logits"] = np.zeros((256, 2, 8), np.float32)
    with pytest.raises(ValueError):
        ap.teacher_cache_manifest(b, a)


def test_old_protocols_untouched_and_no_mlx():
    code = ("import sys, ainerzero.learning.action_preservation; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    subprocess.run([sys.executable, "-c", code], check=True)
    from ainerzero.runtime import memory_worker as mw
    assert mw.RELABEL_LEARNING_RATES == {0.001: "m2m_consistent_relabel_single_edge_tail_fit_v1",
                                         0.003: "m2m_c_consistent_relabel_lr0003_single_edge_tail_fit_v1"}


# ---------------- E13a-R1 counterexamples (F01-F05)

def test_f01_plan_copies_independent_and_frozen_check():
    p = ap.action_preservation_plan()
    p["gates"]["action_1"]["accuracy_min"] = 1
    assert ap.action_preservation_plan()["gates"]["action_1"]["accuracy_min"] == 377
    assert ap.PRESERVATION_GATES["action_1"]["accuracy_min"] == 377
    assert ap.verify_frozen_plan(ap.action_preservation_plan()) == ap.FROZEN_PLAN_SHA256
    for path, value in ((("gates", "action_1", "accuracy_min"), 1), (("units", "total"), 1),
                        (("keep_branch", "seed"), 3308), (("memory_branch", "seeds", "latent"), 1)):
        q = ap.action_preservation_plan()
        node = q
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        with pytest.raises(ValueError):
            ap.verify_frozen_plan(q)


def test_f02_registered_inputs_verify(real):
    w = ap.verify_registered_inputs(*real, partition="train")
    assert w["registered_manifest_verified"] is True and w["public_records_checked"] is False
    assert ap.check_budget(w) == {"retained": 178304, "teacher": 2254, "student": 27988, "total": 208546}
    assert "source_verified" not in w
    assert w["schedule_sha256"] == ap.REGISTERED_INPUT["schedule_sha256"]
    calculated = ap.preservation_windows(*real)
    assert calculated["registered_manifest_verified"] is False and calculated["public_records_checked"] is False
    assert "source_verified" not in calculated
    km = ap.key_manifest(w)
    assert km["keys_sha256"] == "5a6449008da160e7b32c3056d724c4fd954efba8008ce62478bd67411d6c4ad1"
    assert w["windows_sha256"] == "60e86293c6cc85aeee36e917fad544414cc1ce0d33b4ad2074c26f1924067b83"
    assert km["manifest_sha256"] == "71deb0f0b98be564f04227225ff5925108c479223910de3e1d3442b37542c1ca"


def _public_records(samples, partition="train"):
    recs = {}
    for x in samples:
        r = recs.setdefault(x["episode_id"], {"partition": partition,
                                              "environment_instance_id": x["environment_instance_id"],
                                              "public_episode_sha256": x["public_episode_sha256"],
                                              "transitions": {}})
        r["transitions"][x["transition_index"]] = {k: x[k] for k in (
            "target_observation_id", "current_observation_id", "action_request_id",
            "public_transition_sha256", "target_tick")}
    return recs


@pytest.mark.parametrize("bad", ["episode", "world_env", "partition", "observation", "action",
                                 "swap_in_batch", "swap_batches", "window_same_units"])
def test_f02_counterfeits_rejected(real, bad):
    samples, sched = copy.deepcopy(real[0]), np.asarray(real[1]).copy()
    partition = "train"
    records = _public_records(real[0])
    if bad == "episode":
        samples[0]["episode_id"] = "foreign"
    elif bad == "world_env":
        samples[0]["environment_instance_id"] = samples[16]["environment_instance_id"]
    elif bad == "partition":
        partition = "development"
    elif bad == "observation":
        samples[3]["target_observation_id"] = samples[4]["target_observation_id"]
    elif bad == "action":
        records[samples[5]["episode_id"]]["transitions"][samples[5]["transition_index"]][
            "action_request_id"] = "00000000-0000-4000-8000-000000000009"
        with pytest.raises(ValueError):
            ap.verify_registered_inputs(samples, sched, partition=partition, public_records=records)
        return
    elif bad == "swap_in_batch":
        sched[0] = sched[0][::-1]
    elif bad == "swap_batches":
        sched[[0, 1]] = sched[[1, 0]]
    else:
        w = ap.verify_registered_inputs(samples, sched, partition="train")
        w["rows"][7] = dict(w["rows"][7], q=w["rows"][7]["q"] + 1)
        with pytest.raises(ValueError):
            ap.check_budget(w)
        return
    with pytest.raises(ValueError):
        ap.verify_registered_inputs(samples, sched, partition=partition, public_records=records)
    if bad in ("swap_in_batch", "swap_batches"):  # same budget/keys still cannot stand in
        w0, w1 = ap.preservation_windows(*real), ap.preservation_windows(samples, sched)
        assert w0["units"] == w1["units"] and ap.key_manifest(w0)["keys_sha256"] == ap.key_manifest(w1)["keys_sha256"]
        assert ap.key_manifest(w0)["manifest_sha256"] != ap.key_manifest(w1)["manifest_sha256"]


def test_f02_public_records_accepted(real):
    w = ap.verify_registered_inputs(*real, partition="train", public_records=_public_records(real[0]))
    assert w["registered_manifest_verified"] is True and w["public_records_checked"] is True
    assert "source_verified" not in w and "source_verified" not in ap.check_budget(w)
    with pytest.raises(ValueError):
        ap.verify_registered_inputs(*real, partition="train",
                                    public_records=_public_records(real[0], partition="development"))


@pytest.mark.parametrize("field,value", [
    ("teacher_checkpoint_manifest_sha256", "not-a-digest"), ("architecture", "other_model"),
    ("budget_units", -1), ("budget_units", 2254.0), ("mask_rule", "future_labels"), ("run_id", "unregistered"),
    ("particles", True), ("temperature", True), ("windows_sha256", "A" * 64)])
def test_f03_binding_typed(field, value):
    b = binding()
    b[field] = value
    with pytest.raises(ValueError):
        ap.teacher_cache_manifest(b, arrays())
    m = ap.teacher_cache_manifest(binding(), arrays())
    with pytest.raises(ValueError):
        ap.verify_teacher_cache(m, arrays(), b)


@pytest.mark.parametrize("bad", ["width0", "width1", "all_hidden", "one_hidden_row"])
def test_f03_arrays_strict(bad):
    a = arrays()
    if bad == "width0":
        a["incoming_h"] = np.zeros((256, 0), np.float32)
    elif bad == "width1":
        a["incoming_h"] = np.zeros((256, 1), np.float32)
    elif bad == "all_hidden":
        a["visible_mask"] = np.zeros((256, 8), bool)
    else:
        a["visible_mask"][17] = False
    with pytest.raises(ValueError):
        ap.teacher_cache_manifest(binding(), a)


def test_f03_mask_must_match_public_q_mask():
    m = ap.teacher_cache_manifest(binding(), arrays())
    public = np.ones((256, 8), bool)
    ap.verify_teacher_cache(m, arrays(), binding(), expected_visible_mask=public)
    public[0, 0] = False
    with pytest.raises(ValueError):
        ap.verify_teacher_cache(m, arrays(), binding(), expected_visible_mask=public)
    assert "content_sha256" in m["arrays"]["incoming_h"]


def test_f04_gradient_strictness():
    keep16 = [{"w": np.zeros(1)} for _ in range(16)]
    with pytest.raises(ValueError):
        ap.combine_branch_gradients({"w": np.ones((1,))}, 1.0, [{"w": np.arange(3.0)}] * 16)
    for denom in (float("inf"), float("nan"), 0, 0.0, -1.0, True):
        with pytest.raises(ValueError):
            ap.combine_branch_gradients({"w": np.array([4.0])}, denom, keep16)
    with pytest.raises(ValueError):
        ap.combine_branch_gradients({}, 1.0, [{}] * 16)
    with pytest.raises(ValueError):
        ap.combine_branch_gradients({"w": np.array([np.nan])}, 1.0, keep16)
    bad_keep = [{"w": np.zeros(1)} for _ in range(15)] + [{"w": np.array([np.inf])}]
    with pytest.raises(ValueError):
        ap.combine_branch_gradients({"w": np.array([1.0])}, 1.0, bad_keep)
    g = ap.combine_branch_gradients({"w": np.array([4.0])}, 2, [{"w": np.array([float(i)])} for i in range(16)])
    assert g["w"][0] == pytest.approx(2.0 + 7.5)


def test_f05_applied_front_guard():
    with pytest.raises(ValueError):
        ap.check_applied_front_gradient(gru_tree(front=1.0), gru_tree(front=1.0))  # raw==masked, front nonzero
    out = ap.check_applied_front_gradient(gru_tree(front=2.0, tail=1.0), gru_tree(tail=1.0))
    assert out["applied_front_gradient_l2"] == 0.0 and out["raw_front_gradient_l2"] > 0
    tail_only = gru_tree(tail=3.0)
    assert ap.check_applied_front_gradient(tail_only, tail_only)["raw_front_gradient_l2"] == 0.0
    t = gru_tree()
    t["Wx"] = np.zeros((768, 31))
    with pytest.raises(ValueError):
        ap.check_applied_front_gradient(t, gru_tree())
    t = gru_tree()
    del t["bhn"]
    with pytest.raises(ValueError):
        ap.check_applied_front_gradient(gru_tree(), t)
    t = gru_tree()
    t["b"][200] = np.nan
    with pytest.raises(ValueError):
        ap.check_applied_front_gradient(gru_tree(), t)
    m = ap.frozen_row_mask("Wh")
    assert m.sum() == 384 and not m[128:256].any() and not m[384:512].any() and not m[640:768].any()
    assert ap.frozen_row_mask("bhn").sum() == 128 and not ap.frozen_row_mask("bhn")[128:256].any()
    tiny = gru_tree()
    tiny["Wx"][0, 0] = 1e-9
    ap.check_applied_front_gradient(tiny, tiny)


# ---------------- E13a-R2 fixed authority and consumer counterexamples

def test_r2_registered_authority_not_overridable(real):
    replacement = dict(ap.REGISTERED_INPUT)
    replacement["sample_manifest_sha256"] = "0" * 64
    with pytest.raises(TypeError):
        ap.verify_registered_inputs(*real, partition="train", registered=replacement)
    with pytest.raises(TypeError):
        ap.REGISTERED_INPUT["sample_manifest_sha256"] = "0" * 64
    returned = ap.verify_registered_inputs(*real, partition="train")
    returned["registered_input"]["sample_manifest_sha256"] = "0" * 64
    returned["registered_input"]["partition"] = "development"
    checked = ap.verify_registered_inputs(*real, partition="train")
    assert checked["registered_input"] == dict(ap.REGISTERED_INPUT)
    assert checked["registered_input"]["partition"] == "train"
    assert checked["registered_input"]["sample_manifest_sha256"] == (
        "3558c8b5e924def7703bf46d246888612dee406a2f86829ca111fca5c9ede618")
    with pytest.raises(ValueError):
        ap.key_manifest(returned)


@pytest.mark.parametrize("consumer", [ap.check_budget, ap.key_manifest])
@pytest.mark.parametrize("bad", [
    "episode", "environment", "episode_sha", "transition_sha", "row_order", "world", "world_bool",
    "q_bool", "q_range", "q_consistent", "s", "feedback", "feedback_bool", "rollout", "rollout_bool",
    "schedule", "qmax", "qmax_bool", "units", "units_bool", "schema", "window_sha", "schedule_sha",
])
def test_r2_modified_windows_rejected_by_consumers(real, consumer, bad):
    w = ap.verify_registered_inputs(*real, partition="train")
    row = w["rows"][0]
    if bad == "episode":
        row["episode_id"] = "00000000-0000-4000-8000-000000000999"
    elif bad == "environment":
        row["environment_instance_id"] = "00000000-0000-4000-8000-000000000999"
    elif bad in ("episode_sha", "transition_sha"):
        row["public_" + bad.replace("_sha", "_sha256")] = "0" * 64
    elif bad == "row_order":
        w["rows"][0], w["rows"][1] = w["rows"][1], w["rows"][0]
    elif bad == "world":
        row["world_index"] = 1
    elif bad == "world_bool":
        row["world_index"] = False
    elif bad == "q_bool":
        row["q"] = True
    elif bad == "q_range":
        row["q"] = 125
    elif bad == "q_consistent":
        row["q"] += 1
        row["s"] = max(0, row["q"] - 4)
        row["feedback"] = row["q"] - row["s"]
        row["rollout_actions_ticks"] = list(range(row["q"], row["q"] + 4))
    elif bad == "s":
        row["s"] += 1
    elif bad == "feedback":
        row["feedback"] = 0
    elif bad == "feedback_bool":
        row["feedback"] = True
    elif bad == "rollout":
        row["rollout_actions_ticks"] = [0, 0, 0, 0]
    elif bad == "rollout_bool":
        row["rollout_actions_ticks"][0] = True
    elif bad == "schedule":
        w["schedule"][0].reverse()
    elif bad == "qmax":
        w["teacher_qmax"][0] += 1
    elif bad == "qmax_bool":
        w["teacher_qmax"][0] = True
    elif bad == "units":
        w["units"]["student_feedback"] += 1
    elif bad == "units_bool":
        w["units"]["padded_extra_not_executed"] = True
    elif bad == "schema":
        w["windows_schema"] = "m2md_windows_v1"
    elif bad == "window_sha":
        w["windows_sha256"] = "0" * 64
    else:
        w["schedule_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        consumer(w)


@pytest.mark.parametrize("consumer", [ap.check_budget, ap.key_manifest])
@pytest.mark.parametrize("bad", ["false_claim", "public_without_registration", "legacy_source", "flag_type"])
def test_r2_window_state_is_not_a_source_certificate(real, consumer, bad):
    w = ap.preservation_windows(*real)
    if bad == "false_claim":
        w["registered_manifest_verified"] = True
    elif bad == "public_without_registration":
        w["public_records_checked"] = True
    elif bad == "legacy_source":
        w["source_verified"] = True
    else:
        w["registered_manifest_verified"] = 1
    with pytest.raises(ValueError):
        consumer(w)


@pytest.mark.parametrize("consumer", [ap.check_budget, ap.key_manifest])
def test_r2_foreign_pool_refresh_cannot_claim_fixed_registration(real, consumer):
    samples = copy.deepcopy(real[0])
    for row in samples[:16]:
        row["episode_id"] = "00000000-0000-4000-8000-000000000999"
    with pytest.raises(ValueError):
        ap.verify_registered_inputs(samples, real[1], partition="train")
    generic = ap.preservation_windows(samples, real[1])
    # Same numerical work and seeds are still valid computations, never provenance.
    assert ap.check_budget(generic)["total"] == 208546
    assert ap.key_manifest(generic)["keys_sha256"] == "5a6449008da160e7b32c3056d724c4fd954efba8008ce62478bd67411d6c4ad1"
    assert generic["windows_sha256"] != ap.REGISTERED_WINDOWS_SHA256
    generic["registered_manifest_verified"] = True
    generic["registered_input"] = dict(ap.REGISTERED_INPUT)
    with pytest.raises(ValueError):
        consumer(generic)
    generic["registered_input"]["sample_manifest_sha256"] = ap._digest(samples)
    with pytest.raises(ValueError):
        consumer(generic)


def test_r2_generic_calculator_rechecks_content_without_registering():
    samples = synthetic_samples()
    computed = ap.preservation_windows(samples, schedule())
    checked = ap.validate_windows(computed)
    assert checked["units"] == computed["units"]
    assert checked["windows_sha256"] == computed["windows_sha256"]
    assert "registered_manifest_verified" not in checked and "public_records_checked" not in checked
    assert len(ap.key_manifest(computed)["rows"]) == 256
    computed["rows"][0]["rollout_actions_ticks"] = [0, 0, 0, 0]
    with pytest.raises(ValueError):
        ap.key_manifest(computed)


def test_r2_applied_gradient_derived_norms_must_be_finite():
    raw = gru_tree()
    raw["Wx"][0, 0] = 1e308
    with pytest.raises(ValueError, match="norms must be finite"):
        ap.check_applied_front_gradient(raw, gru_tree())
