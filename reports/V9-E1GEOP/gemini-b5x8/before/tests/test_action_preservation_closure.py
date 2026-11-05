"""E13b CPU closure tests (T1, T2, T5, T6, T7, T8); no MLX, no run, no model calls."""

import ast
import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.learning import tail_update

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m2md_pool_manifest.json"
LEARNING = ROOT / "src" / "ainerzero" / "learning"
RUN_ID = "00000000-0000-4000-8000-000000000000"


@pytest.fixture(scope="module")
def real():
    f = json.loads(FIXTURE.read_text())
    return f["samples"], f["schedule"]


def records(samples):
    out = {}
    for s in samples:
        rec = out.setdefault(s["episode_id"], {
            "partition": "train", "environment_instance_id": s["environment_instance_id"],
            "public_episode_sha256": s["public_episode_sha256"], "transitions": {}})
        rec["transitions"][s["transition_index"]] = {
            k: s[k] for k in ("target_observation_id", "current_observation_id", "action_request_id",
                              "public_transition_sha256", "target_tick")}
    return out


def test_no_mlx_imported():
    """The CPU layer must import without MLX (checked in a fresh process).

    A single-process full-suite run has MLX loaded by other tests, so the
    process-level assertion is checked where it is meaningful: in a fresh
    interpreter, following the existing repo idiom
    (``test_old_protocols_untouched_and_no_mlx``).
    """
    code = ("import sys, ainerzero.learning.action_preservation_closure; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code.format()], check=True)


# ---- T1 (B1)

def test_t1_registered_fixture_passes(real):
    out = apc.production_windows(*real, records(real[0]))
    assert out["keys"]["manifest_sha256"] == apc.REGISTERED_KEY_MANIFEST_SHA256
    assert out["keys"]["keys_sha256"] == apc.REGISTERED_KEYS_CONTENT_SHA256
    assert out["windows"]["windows_sha256"] == ap.REGISTERED_WINDOWS_SHA256


def test_t1_constants_not_duplicated():
    text = (LEARNING / "action_preservation_closure.py").read_text()
    assert ap.REGISTERED_WINDOWS_SHA256 not in text
    assert apc.M2MC_REPORT_SHA256 == ap.REGISTERED_INPUT["source_report_sha256"]


def test_t1_generic_windows_rejected(real):
    generic = ap.preservation_windows(*real)
    with pytest.raises(ValueError, match="registered_input"):
        apc.require_production_windows(generic)
    flagged = dict(generic, registered_manifest_verified=True, public_records_checked=True)
    with pytest.raises(ValueError, match="registered_input"):
        apc.require_production_windows(flagged)


def test_t1_swapped_episode_with_refreshed_digest_rejected(real):
    w = apc.production_windows(*real, records(real[0]))["windows"]
    bad = copy.deepcopy(w)
    a, b = bad["rows"][0], bad["rows"][16]
    for k in ("episode_id", "environment_instance_id", "public_episode_sha256"):
        a[k], b[k] = b[k], a[k]
    bad["windows_sha256"] = ap._digest([[r["row"], r["world_index"], r["q"], r["s"], r["episode_id"],
                                         r["environment_instance_id"], r["public_episode_sha256"],
                                         r["public_transition_sha256"]] for r in bad["rows"]])
    with pytest.raises(ValueError):
        apc.require_production_windows(bad)
    del bad["registered_input"]
    with pytest.raises(ValueError):
        apc.require_production_windows(bad)


def test_t1_key_binding_or_content_mismatch_rejected(real):
    keys = apc.production_windows(*real, records(real[0]))["keys"]
    apc.check_keys(keys)
    for field in ("manifest_sha256", "keys_sha256"):
        bad = dict(keys, **{field: "0" * 64})
        with pytest.raises(ValueError):
            apc.check_keys(bad)
    bad = copy.deepcopy(keys)
    bad["rows"][0]["keys"][0][3] ^= 1
    with pytest.raises(ValueError, match="listed keys"):
        apc.check_keys(bad)


def test_t1_missing_public_records_rejected(real):
    for value in (None, {}):
        with pytest.raises(ValueError, match="public_records"):
            apc.production_windows(*real, value)


def test_t1_wrong_record_identity_rejected(real):
    rec = records(real[0])
    eid = real[0][0]["episode_id"]
    rec[eid]["public_episode_sha256"] = "1" * 64
    with pytest.raises(ValueError):
        apc.production_windows(*real, rec)


# ---- T2 (B2)

def test_t2_int_keys_and_bad_key_types(real):
    rec = records(real[0])
    assert all(type(k) is int for r in rec.values() for k in r["transitions"])
    eid = real[0][0]["episode_id"]
    for convert in (np.int64, str):
        bad = copy.deepcopy(rec)
        bad[eid]["transitions"] = {convert(k): v for k, v in bad[eid]["transitions"].items()}
        with pytest.raises(ValueError, match="Python int"):
            apc.production_windows(*real, bad)
    bad = copy.deepcopy(rec)
    k = next(iter(bad[eid]["transitions"]))
    bad[eid]["transitions"][k]["target_tick"] = np.int64(bad[eid]["transitions"][k]["target_tick"])
    with pytest.raises(ValueError, match="target_tick"):
        apc.production_windows(*real, bad)


def test_t2_forged_flags_do_not_change_result(real):
    rec = records(real[0])
    forged = copy.deepcopy(rec)
    for r in forged.values():
        r["verified"] = True
    with pytest.raises(ValueError):
        apc.production_windows(*real, forged)
    eid = real[0][0]["episode_id"]
    bad = copy.deepcopy(rec)
    bad[eid]["public_episode_sha256"] = "1" * 64
    bad[eid]["public_records_checked"] = True
    with pytest.raises(ValueError):
        apc.production_windows(*real, bad)


def test_t2_records_from_episodes_use_int(monkeypatch):
    """Same identity algorithm as the diverse pool, on lightweight stand-ins."""
    from types import SimpleNamespace as N

    import ainerzero.core.experience as experience

    monkeypatch.setattr(experience, "admit_training", lambda item, policy: item)

    class Dumpable(N):
        def model_dump(self, mode):
            return {"id": self.tag}

    def transition(i):
        return Dumpable(tag=f"t{i}", observation=N(id=f"o{i}", step=np.int64(i)),
                        next_observation=N(id=f"o{i + 1}"), action_request=N(id=f"a{i}"))

    episode = Dumpable(tag="ep", initial=N(context=N(partition=N(value="train"), episode_id="e",
                                                     environment_instance_id="w")),
                       transitions=[transition(0), transition(1)])
    out = apc.public_records_from_episodes([episode])
    t = out["e"]["transitions"]
    assert list(t) == [0, 1] and all(type(k) is int for k in t)
    assert type(t[1]["target_tick"]) is int and t[1]["public_transition_sha256"] == apc._digest({"id": "t1"})
    assert out["e"]["public_episode_sha256"] == apc._digest({"id": "ep"})


# ---- T5

def test_t5_frozen_mask_complements_tail_rows():
    for name, shape in ap.GRU_LEAVES.items():
        tail = np.zeros(shape[0], dtype=bool)
        for start, stop in ((128, 256),) if name == "bhn" else tail_update.TAIL_ROW_RANGES:
            tail[start:stop] = True
        assert np.array_equal(ap.frozen_row_mask(name), ~tail)
    assert sum(int((~ap.frozen_row_mask(n)).sum()) * (s[1] if len(s) == 2 else 1)
               for n, s in ap.GRU_LEAVES.items()) == 111_104


# ---- T6

def _summary(count, correct, changed_count, changed_correct):
    return {"count": count, "accuracy": correct / count, "changed_count": changed_count,
            "changed_accuracy": changed_correct / changed_count}


def _inputs(dev=(3892, 115), pool=(1946, 126), act=(377, 359), inc=(0.05, 0.15), recon=544):
    def action(c1, c4, n1, n4):
        return {"horizons": {"1": {"model": {"count": 384, "accuracy": c1 / 384, "nll": n1}},
                             "4": {"model": {"count": 384, "accuracy": c4 / 384, "nll": n4}}}}
    # before NLL 0.0 keeps the increase bit-exact (0.05/0.15 themselves, no float drift).
    before = {"action": action(384, 384, 0.0, 0.0)}
    after = {"action": action(act[0], act[1], inc[0], inc[1]),
             "reconstruction": {"gate": {"status": "passed"},
                                "model": {"count": 544, "accuracy": recon / 544}}}
    paired = {"groups": {"development": {"methods": {"zero_context_tail": _summary(4096, dev[0], 127, dev[1])}}}}
    relabel = {"count": 2048, "correct": pool[0], "changed_count": 140, "changed_correct": pool[1]}
    return before, after, paired, relabel


def _status(**kw):
    return apc.preservation_screen(*_inputs(**kw))


def test_t6_boundaries_pass():
    out = _status()
    assert out["status"] == "passed" and out["promotion"] is False
    assert out["checks"]["action_1"]["nll_increase"] == 0.05
    assert out["checks"]["action_4"]["nll_increase"] == 0.15


@pytest.mark.parametrize("kw,gate", [
    ({"dev": (3891, 115)}, "development_zero_context"),
    ({"dev": (3892, 114)}, "development_zero_context"),
    ({"pool": (1945, 126)}, "relabel_pool"),
    ({"pool": (1946, 125)}, "relabel_pool"),
    ({"act": (376, 359)}, "action_1"),
    ({"act": (377, 358)}, "action_4"),
    ({"inc": (0.05 + 1e-9, 0.15)}, "action_1"),
    ({"inc": (0.05, 0.15 + 1e-9)}, "action_4"),
    ({"recon": 543}, "reconstruction"),
])
def test_t6_just_below_fails(kw, gate):
    out = _status(**kw)
    assert out["status"] == "failed" and out["checks"][gate]["passed"] is False
    assert all(v["passed"] for k, v in out["checks"].items() if k != gate)


def test_t6_wrong_denominator_rejected():
    before, after, paired, relabel = _inputs()
    relabel["changed_count"] = 139
    with pytest.raises(ValueError):
        apc.preservation_screen(before, after, paired, relabel)


# ---- T7

@pytest.fixture
def checkpoint(tmp_path):
    (tmp_path / "manifest.json").write_bytes(b'{"m2d": true}')
    return tmp_path


def _arrays():
    rng = np.random.default_rng(0)
    return {"incoming_h": rng.standard_normal((256, 256)).astype(np.float32),
            "teacher_logits": rng.standard_normal((256, 2, 8, 256)).astype(np.float32),
            "visible_mask": np.ones((256, 8), dtype=np.bool_)}


def test_t7_expected_binding_and_generic_rejected(real, checkpoint):
    out = apc.production_windows(*real, records(real[0]))
    binding = apc.expected_cache_binding(checkpoint_path=checkpoint, windows=out["windows"],
                                         keys=out["keys"], run_id=RUN_ID)
    assert ap.validate_cache_binding(binding) == binding and len(binding) == 14
    assert binding["teacher_checkpoint_manifest_sha256"] == apc._sha(checkpoint / "manifest.json")
    assert binding["teacher_source_sha256"] == apc._digest(
        {n: apc._sha(LEARNING / n) for n in apc.TEACHER_SOURCE_FILES})
    arrays = _arrays()
    manifest = ap.teacher_cache_manifest(binding, arrays)
    ap.verify_teacher_cache(manifest, arrays, binding, arrays["visible_mask"])
    # Generic (non-registered) windows: synthetic E13a-style pool, its own SHA/key manifest.
    qs = [1 + (i * 7) % 120 for i in range(256)]
    samples = [{"row": i, "world_index": i // 16, "query_tick": q, "target_tick": q - 1,
                "episode_id": f"e{i // 16}"} for i, q in enumerate(qs)]
    generic = ap.preservation_windows(samples, real[1])
    generic_keys = ap.key_manifest(generic)
    assert generic["windows_sha256"] != binding["windows_sha256"]
    assert generic_keys["manifest_sha256"] != binding["key_manifest_sha256"]
    for field, value in (("windows_sha256", generic["windows_sha256"]),
                         ("key_manifest_sha256", generic_keys["manifest_sha256"])):
        fake = dict(binding, **{field: value})
        bad = ap.teacher_cache_manifest(fake, arrays)
        with pytest.raises(ValueError, match="binding mismatch"):
            ap.verify_teacher_cache(bad, arrays, binding)
    with pytest.raises(ValueError):
        apc.expected_cache_binding(checkpoint_path=checkpoint, windows=generic, keys=generic_keys, run_id=RUN_ID)


# ---- T8

def _calls(path):
    tree = ast.parse(path.read_text())
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return imports, calls


def test_t8_static_key_rules():
    imports, _ = _calls(LEARNING / "action_preservation_closure.py")
    assert not any(m == "mlx" or m.startswith("mlx.") for m in imports)
    imports, calls = _calls(LEARNING / "action_preservation_mlx.py")
    text = (LEARNING / "action_preservation_mlx.py").read_text()
    assert [c for c in calls if c == "mx.random.key"] == ["mx.random.key"]
    assert "def _key(seed_u32) -> mx.array:\n    return mx.random.key(int(seed_u32))" in text
    for call in calls:
        tail = call.split(".")[-1]
        assert not call.endswith("random.seed") and not call.endswith("random.split")
        assert not tail.startswith("fold")
        assert not call.startswith("mx.random.") or call == "mx.random.key"
    keyed = [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.keyword) and n.arg == "key"]
    assert keyed and all(
        (isinstance(k.value, ast.Call) and ast.unparse(k.value.func) == "_key")
        # D condition: the in-batch distillation forwards the memory branch's own
        # registered keys to teacher and student instead of creating new ones
        or (isinstance(k.value, ast.Name) and k.value.id == "key")
        for k in keyed
    )
    creating = [k for k in keyed
                if isinstance(k.value, ast.Call) and ast.unparse(k.value.func) == "_key"]
    assert creating, "the keep path must still create its keys through _key"


# ---- paired recompute from saved cells (closure-owned counting rule)

def test_cell_metrics_match_symbol_metrics():
    from ainerzero.learning.baselines import symbol_metrics

    rng = np.random.default_rng(5)
    for _ in range(50):
        targets = rng.integers(0, 4, 8)
        current = np.where(rng.random(8) < 0.5, targets, rng.integers(0, 4, 8))
        tmask, cmask = rng.random(8) < 0.7, rng.random(8) < 0.7
        tmask[0] = True
        probs = np.full((8, 256), 1e-4)
        argmax = rng.integers(0, 256, 8)
        probs[np.arange(8), argmax] = 0.6
        probs[np.arange(8), targets] += 0.1
        probs /= probs.sum(-1, keepdims=True)
        expected = symbol_metrics(probs, targets, tmask, current, cmask)
        nll = np.where(tmask, -np.log(probs[np.arange(8), targets]), np.nan)
        got = apc._metrics(probs.argmax(-1), nll, targets, tmask, current, cmask, "t")
        stats = {"compared": 0, "max_float_diff": 0.0}
        apc._close(got, expected, "t", stats)
        assert stats["compared"] == 9


def test_cell_shape_and_nll_presence_rejected():
    with pytest.raises(ValueError):
        apc._cell_arrays({"argmax": [0] * 7, "nll": [0.1] * 7}, "c")
    with pytest.raises(ValueError):
        apc._cell_arrays({"argmax": [0] * 8, "nll": [float("inf")] + [0.1] * 7}, "c")
    a, n = apc._cell_arrays({"argmax": [0] * 8, "nll": [None] + [0.1] * 7}, "c")
    with pytest.raises(ValueError, match="visible"):
        apc._metrics(a, n, np.zeros(8, int), np.ones(8, bool), np.zeros(8, int), np.ones(8, bool), "c")
    with pytest.raises(ValueError, match="2560"):
        apc.recompute_paired([], {}, [], {"per_query": []})


# ---- E13b-R1: full paired recompute, swap counterexample, query manifest self-check

def _synthetic_paired(seed=11, queries=2560, worlds=20):
    """Expected stats built with the original M2k functions from one-hot-ish probabilities."""
    from types import SimpleNamespace as N

    from ainerzero.learning.baselines import symbol_metrics
    from ainerzero.learning.evaluation import _Summary
    from ainerzero.learning.paired_memory import _paired_counts, _paired_result

    rng = np.random.default_rng(seed)
    frames = {"previous_symbols": rng.integers(0, 3, (queries, 8)),
              "previous_visible": rng.random((queries, 8)) < 0.8,
              "current_symbols": rng.integers(0, 3, (queries, 8)),
              "current_visible": rng.random((queries, 8)) < 0.8}
    frames["previous_visible"][:, 0] = True
    names = ("fitted_train", "other_train", "development")
    qlist, cells, per_query = [], [], []
    groups = {g: {"m": {b: _Summary() for b in apc.PAIRED_BRANCHES}, "p": {}} for g in names}
    wsum = {w: {"m": {b: _Summary() for b in apc.PAIRED_BRANCHES}, "p": {}} for w in range(worlds)}
    for i in range(queries):
        world = i * worlds // queries
        group = names[world % 3]
        target = N(symbols=frames["previous_symbols"][i], visible_mask=frames["previous_visible"][i])
        current = N(symbols=frames["current_symbols"][i], visible_mask=frames["current_visible"][i])
        probs, row, methods = {}, {}, {}
        for b in apc.PAIRED_BRANCHES:
            p = np.full((8, 256), 1e-3)
            p[np.arange(8), rng.integers(0, 3, 8)] = 0.5
            p /= p.sum(-1, keepdims=True)
            probs[b] = p
            methods[b] = symbol_metrics(p, target.symbols, target.visible_mask, current.symbols,
                                        current.visible_mask)
            nll = -np.log(p[np.arange(8), target.symbols])
            row[b] = {"argmax": [int(v) for v in p.argmax(-1)],
                      "nll": [float(v) if m else None for v, m in zip(nll, target.visible_mask)]}
        counts = _paired_counts(probs["history_tail"], probs["zero_context_tail"], target, current)
        for bucket in (groups[group], wsum[world]):
            for b in apc.PAIRED_BRANCHES:
                bucket["m"][b].add(methods[b])
            for k, v in counts.items():
                bucket["p"][k] = bucket["p"].get(k, 0) + v
        qlist.append({"episode_id": f"e{world}", "query_tick": i, "group": group})
        cells.append(row)
        per_query.append({"episode_id": f"e{world}", "query_tick": i, "world_index": world,
                          "methods": methods, "paired": _paired_result(counts, methods)})

    def result(bucket):
        methods = {b: s.result() for b, s in bucket["m"].items()}
        return {"methods": methods, "paired": _paired_result(bucket["p"], methods)}

    expected = {"per_query": per_query, "groups": {g: result(v) for g, v in groups.items()},
                "per_world": [{"world_index": w, **result(v)} for w, v in wsum.items()]}
    return cells, frames, qlist, expected


@pytest.fixture(scope="module")
def synthetic():
    return _synthetic_paired()


def test_r1_full_paired_recompute_passes(synthetic):
    stats = apc.recompute_paired(*synthetic)
    assert stats["max_float_diff"] <= apc.FLOAT_TOLERANCE
    paired_fields = len(apc.PAIRED_COUNT_FIELDS) + 4
    assert stats["compared"] >= 2560 * (2 * 9 + paired_fields)


def _find_swap(cells, frames):
    """Two cells, same label: one only-history correct, the other only-zero correct."""
    for i, row in enumerate(cells):
        tg, vis = frames["previous_symbols"][i], frames["previous_visible"][i]
        h, z = np.array(row["history_tail"]["argmax"]), np.array(row["zero_context_tail"]["argmax"])
        only_h = [c for c in range(8) if vis[c] and h[c] == tg[c] and z[c] != tg[c]]
        only_z = [c for c in range(8) if vis[c] and z[c] == tg[c] and h[c] != tg[c]]
        for a in only_h:
            for b in only_z:
                if tg[a] == tg[b]:
                    return i, a, b
    raise AssertionError("no swap candidate")


def test_r1_swap_counterexample_rejected(synthetic):
    cells, frames, queries, expected = synthetic
    i, a, b = _find_swap(cells, frames)
    bad = copy.deepcopy(cells)
    hist = bad[i]["history_tail"]
    for field in ("argmax", "nll"):
        hist[field][a], hist[field][b] = hist[field][b], hist[field][a]
    # The marginal (methods) statistics are unchanged by the swap...
    cur = (frames["current_symbols"][i], frames["current_visible"][i])
    tg = (frames["previous_symbols"][i], frames["previous_visible"][i])
    for rows in (cells, bad):
        arr = apc._cell_arrays(rows[i]["history_tail"], "h")
        stats = {"compared": 0, "max_float_diff": 0.0}
        apc._close(apc._metrics(*arr, *tg, *cur, "h"), expected["per_query"][i]["methods"]["history_tail"],
                   "h", stats)
    # ...but the paired comparison now rejects it.
    with pytest.raises(ValueError, match="paired"):
        apc.recompute_paired(bad, frames, queries, expected)


def test_r1_paired_field_tamper_rejected(synthetic):
    cells, frames, queries, expected = synthetic
    for path in (("groups", "development", "paired", "prediction_disagreements"),
                 ("per_world", 3, "paired", "changed_both_correct")):
        bad = copy.deepcopy(expected)
        node = bad
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] += 1
        with pytest.raises(ValueError, match="paired"):
            apc.recompute_paired(cells, frames, queries, bad)
    bad = copy.deepcopy(expected)
    del bad["per_query"][0]["paired"]["history_minus_zero_nll"]
    with pytest.raises(ValueError, match="field set"):
        apc.recompute_paired(cells, frames, queries, bad)


def test_r1_query_manifest_self_check(monkeypatch, tmp_path):
    import ainerzero.learning.coverage_diagnostic as cov

    report = tmp_path / "m2mc.json"
    report.write_bytes(b"{}")
    monkeypatch.setattr(apc, "M2MC_REPORT_SHA256", apc._sha(report))
    relabel = {"report": {"m2l": {"x": 1}},
               "m2l_report": {"paired": {"query_manifest_sha256": "a" * 64}}}
    report.write_text(json.dumps({"status": "completed", "run_id": apc.M2MC_RUN_ID,
                                  "relabel": {"m2l": {"x": 1}},
                                  "m2l_paired_reproduction": {"exact_match": True}, "cells": {"m2l": []}}))
    monkeypatch.setattr(apc, "M2MC_REPORT_SHA256", apc._sha(report))
    monkeypatch.setattr(cov, "query_frames", lambda episodes: ({}, {"query_manifest_sha256": "b" * 64}))
    with pytest.raises(ValueError, match="query manifest"):
        apc.m2l_reuse_closure(report, relabel, store=None, episodes=object())
