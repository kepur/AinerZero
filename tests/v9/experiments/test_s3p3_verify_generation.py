"""Contract gate K2b: the world log agrees with the seeded generator. CPU only.

K2 shows that the versions and answers follow from the observation log; K2b ties the log
back to the generator, so a consistent rewrite of the log (which K2 cannot see) is caught.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s3 import analysis_p3 as A
from ainerzero.v9.experiments.s3 import persist as PS

REPO = Path(__file__).resolve().parents[3]
VERIFY_GEN = REPO / "reports/V9-S3-PHASE3/verify_generation.py"
VERIFY = REPO / "reports/V9-S3-PHASE3/verify_worlds.py"
NS = "test-s3p3-gen"
EPISODES = 6


def _log(w):
    seq = PS.generate_sequence(NS, w, n_episodes=EPISODES)
    _, lg = A.analyse_world(seq)
    lg["world_seed"], lg["layout_sha256"] = seq.world_seed, seq.layout_sha256
    return json.loads(json.dumps(lg))


@pytest.fixture(scope="module")
def logs():
    return [_log(0), _log(1)]


def _run(script, path, *args):
    r = subprocess.run([sys.executable, "-I", str(script), str(path), *map(str, args)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _write(tmp_path, name, logs):
    p = tmp_path / name
    p.write_text("".join(json.dumps(lg) + "\n" for lg in logs), encoding="utf-8")
    return p


def test_true_logs_pass_and_counts_are_reported(logs, tmp_path) -> None:
    out = _run(VERIFY_GEN, _write(tmp_path, "ok.jsonl", logs), NS, EPISODES)
    assert out["passed"] is True and out["worlds"] == 2 and out["forbidden_loaded"] == []
    assert out["queries"] == sum(len(lg["queries"]) for lg in logs) and out["fast_events"] == sum(len(lg["fast_events"]) for lg in logs)


def test_the_generator_check_loads_no_memory_or_analysis_code(logs, tmp_path) -> None:
    imports = [ln for ln in VERIFY_GEN.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith(("import ", "from "))]
    assert imports and not any(name in ln for ln in imports for name in ("promotion", "analysis_p3", "cues"))
    assert set(_run(VERIFY_GEN, _write(tmp_path, "ok.jsonl", logs), NS, EPISODES)["forbidden_loaded"]) == set()


def test_a_consistent_rewrite_of_the_observation_log_passes_k2_but_fails_k2b(logs, tmp_path) -> None:
    """The reviewer's attack C: rewrite observations, rebuild versions with the same rule, re-answer."""
    spec_ = importlib.util.spec_from_file_location("s3p3_verify_for_gen_test", VERIFY)
    V = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(V)
    lg = copy.deepcopy(logs[0])
    for o in lg["observations"][:20]:
        o[5] = (o[5] % 8) + 1
    lg["versions"] = V.rebuild(lg["observations"])
    by_hash = {v["hash"]: v for v in lg["versions"]}
    for q in lg["queries"]:
        in_force = [v for v in lg["versions"] if v["episode"] < q["episode"]][-1]
        q["version"] = in_force["hash"]
        slow = V.best([(it[0], it[2], it[3], it[1]) for it in in_force["items"]], q["xy"], q["terrain"])
        latest, when = None, None
        for e, t, x, y, ter, tok in lg["observations"]:
            if e < q["episode"] and V.place([x, y], ter, q["xy"], q["terrain"])[0] and (when is None or e * 360 + t > when):
                latest, when = tok, e * 360 + t
        q["pred_L"] = q["shown"] if latest is None else latest
        q["pred_G"] = q["pred_L"] if slow is None else slow
    assert by_hash and V.check_world(lg)[0] == []  # K2 cannot see it
    out = _run(VERIFY_GEN, _write(tmp_path, "c.jsonl", [lg, logs[1]]), NS, EPISODES)
    assert out["passed"] is False and any("observation log differs" in p for p in out["problems"])


@pytest.mark.parametrize("field,value", [("xy", [99.0, 99.0]), ("shown", 0), ("answer", 0), ("decoy", 7), ("relocated", 7), ("t", 9999)])
def test_a_changed_query_fails(logs, tmp_path, field, value) -> None:
    lg = copy.deepcopy(logs[0])
    lg["queries"][1][field] = value
    out = _run(VERIFY_GEN, _write(tmp_path, "q.jsonl", [lg, logs[1]]), NS, EPISODES)
    assert out["passed"] is False and any("queries differ" in p for p in out["problems"])


def test_a_dropped_query_or_fast_event_fails(logs, tmp_path) -> None:
    for key in ("queries", "fast_events"):
        lg = copy.deepcopy(logs[0])
        lg[key] = lg[key][1:]
        out = _run(VERIFY_GEN, _write(tmp_path, f"{key}.jsonl", [lg, logs[1]]), NS, EPISODES)
        assert out["passed"] is False, key


def test_missing_or_reordered_worlds_fail(logs, tmp_path) -> None:
    assert _run(VERIFY_GEN, _write(tmp_path, "one.jsonl", [logs[1]]), NS, EPISODES)["passed"] is False
    assert _run(VERIFY_GEN, _write(tmp_path, "rev.jsonl", [logs[1], logs[0]]), NS, EPISODES)["passed"] is False


def test_wrong_seed_namespace_or_episode_count_fails(logs, tmp_path) -> None:
    lg = copy.deepcopy(logs[0])
    lg["world_seed"] += 1
    assert _run(VERIFY_GEN, _write(tmp_path, "s.jsonl", [lg, logs[1]]), NS, EPISODES)["passed"] is False
    p = _write(tmp_path, "ok.jsonl", logs)
    assert _run(VERIFY_GEN, p, NS + "-other", EPISODES)["passed"] is False
    assert _run(VERIFY_GEN, p, NS, EPISODES - 1)["passed"] is False


def test_an_empty_file_does_not_pass(tmp_path) -> None:
    assert _run(VERIFY_GEN, _write(tmp_path, "e.jsonl", []), NS, EPISODES)["passed"] is False
