"""Contract gate K2: the standard-library verifier of S3 phase 3 world logs. CPU only.

Tampering with any part of the evidence must be reported, including by a forger who
recomputes every hash so that the chain itself stays consistent.
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
VERIFY = REPO / "reports/V9-S3-PHASE3/verify_worlds.py"
NS = "test-s3p3-verify"


@pytest.fixture(scope="module")
def V():
    spec_ = importlib.util.spec_from_file_location("s3p3_verify_under_test", VERIFY)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def log():
    _, lg = A.analyse_world(PS.generate_sequence(NS, 0))
    return json.loads(json.dumps(lg))


def _rehash(V, versions):
    """What a careful forger does: recompute every parent link and hash."""
    for i, v in enumerate(versions):
        v["parent"] = versions[i - 1]["hash"] if i else None
        v["hash"] = V.vhash(v["parent"], v["episode"], v["items"])
    return versions


def _repoint(lg, old_hashes):
    new = [v["hash"] for v in lg["versions"]]
    m = dict(zip(old_hashes, new))
    for q in lg["queries"]:
        q["version"] = m.get(q["version"], q["version"])
    return lg


def _forge(V, log, edit):
    lg = copy.deepcopy(log)
    old = [v["hash"] for v in lg["versions"]]
    edit(lg)
    _rehash(V, lg["versions"])
    return _repoint(lg, old)


def test_verifier_imports_no_project_code() -> None:
    src = VERIFY.read_text(encoding="utf-8")
    assert "ainerzero" not in src.split('"""', 2)[2] and "numpy" not in src


def test_a_true_log_passes(V, log) -> None:
    bad, n_q, n_v = V.check_world(log)
    assert bad == [] and n_q == len(log["queries"]) > 0 and n_v == len(log["versions"]) - 1 > 0


def test_rebuild_reproduces_the_versions(V, log) -> None:
    assert [v["hash"] for v in V.rebuild(log["observations"])] == [v["hash"] for v in log["versions"]]


def test_the_verifier_matches_the_promotion_hash(V, log) -> None:
    from ainerzero.v9.experiments.s3 import promotion as PR

    for v in log["versions"]:
        assert V.vhash(v["parent"], v["episode"], v["items"]) == PR.version_hash(v["parent"], v["episode"], v["items"]) == v["hash"]


def _promoted(log):
    return next(i for i, v in enumerate(log["versions"]) if v["items"])


def test_changed_hash_is_reported(V, log) -> None:
    lg = copy.deepcopy(log)
    lg["versions"][1]["hash"] = "0" * 64
    assert any("hash does not recompute" in b for b in V.check_world(lg)[0])


def test_broken_parent_link_is_reported(V, log) -> None:
    lg = copy.deepcopy(log)
    lg["versions"][-1]["parent"] = None
    assert any("parent link broken" in b for b in V.check_world(lg)[0])


def test_forged_token_is_reported(V, log) -> None:
    i = _promoted(log)

    def edit(lg):
        it = lg["versions"][i]["items"][0]
        it[1] = (it[1] % 8) + 1

    bad = V.check_world(_forge(V, log, edit))[0]
    assert any("fewer than" in b for b in bad) and any("do not follow" in b for b in bad)


def test_forged_missing_evidence_is_reported(V, log) -> None:
    i = _promoted(log)

    def edit(lg):
        it = lg["versions"][i]["items"][0]
        keep = [v for v in it[4] if v[1] != it[1]]
        it[4] = keep + [v for v in it[4] if v[1] == it[1]][:1]

    assert any("fewer than" in b for b in V.check_world(_forge(V, log, edit))[0])


def test_forged_anchor_change_is_reported(V, log) -> None:
    later = [i for i, v in enumerate(log["versions"]) if i and log["versions"][i - 1]["items"]]
    if not later:
        pytest.skip("no version with a promoted parent in this world")
    i = later[0]

    def edit(lg):
        lg["versions"][i]["items"][0][2] = [99.0, 99.0]

    assert any("anchor changed" in b for b in V.check_world(_forge(V, log, edit))[0])


def test_forged_disappearance_is_reported(V, log) -> None:
    later = [i for i, v in enumerate(log["versions"]) if i and log["versions"][i - 1]["items"]]
    if not later:
        pytest.skip("no version with a promoted parent in this world")
    i = later[0]

    def edit(lg):
        lg["versions"][i]["items"] = lg["versions"][i]["items"][1:]

    assert any("disappeared" in b for b in V.check_world(_forge(V, log, edit))[0])


def test_forged_replacement_without_later_votes_is_reported(V) -> None:
    base = {"world": 0, "observations": [], "queries": []}
    items1 = [[0, 1, [0.0, 0.0], [0] * 9, [[0, 1], [1, 1]]]]
    items2 = [[0, 2, [0.0, 0.0], [0] * 9, [[0, 1], [1, 1], [2, 2]]]]  # one later vote only
    vs = [{"episode": -1, "items": []}, {"episode": 1, "items": items1}, {"episode": 2, "items": items2}]
    lg = dict(base, versions=_rehash(V, vs))
    assert any("replaced without" in b for b in V.check_world(lg)[0])


@pytest.mark.parametrize(
    "votes,episode",
    [([[1, 1], [1, 1]], 1),   # two votes from one episode
     ([[0, 1], [3, 1]], 2),   # a vote from after the version
     ([[2, 1], [0, 1]], 2)],  # votes out of order
)
def test_forged_vote_record_is_reported(V, votes, episode) -> None:
    vs = [{"episode": -1, "items": []}, {"episode": episode, "items": [[0, 1, [0.0, 0.0], [0] * 9, votes]]}]
    lg = {"world": 0, "observations": [], "queries": [], "versions": _rehash(V, vs)}
    assert any("votes not one per earlier episode" in b for b in V.check_world(lg)[0])


def test_changed_observation_log_is_reported(V, log) -> None:
    lg = copy.deepcopy(log)
    for o in lg["observations"]:
        if o[0] == 0:
            o[5] = (o[5] % 8) + 1
    assert any("do not follow" in b for b in V.check_world(lg)[0])


def test_changed_answer_is_reported(V, log) -> None:
    for field in ("pred_G", "pred_L"):
        lg = copy.deepcopy(log)
        lg["queries"][0][field] = (lg["queries"][0][field] % 8) + 1
        assert any("re-answer differs" in b for b in V.check_world(lg)[0]), field


def test_query_on_a_stale_version_is_reported(V, log) -> None:
    lg = copy.deepcopy(log)
    q = next(q for q in lg["queries"] if q["version"] != lg["versions"][0]["hash"])
    q["version"] = lg["versions"][0]["hash"]
    assert any("version in force" in b for b in V.check_world(lg)[0])


def test_command_line_in_a_separate_process(V, log, tmp_path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(json.dumps(log) + "\n", encoding="utf-8")
    lg = copy.deepcopy(log)
    lg["queries"][0]["pred_G"] = (lg["queries"][0]["pred_G"] % 8) + 1
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(log) + "\n" + json.dumps(lg) + "\n", encoding="utf-8")
    run = lambda p: json.loads(subprocess.run([sys.executable, "-I", str(VERIFY), str(p)], capture_output=True, text=True, check=True).stdout)
    g, b = run(good), run(bad)
    assert g["passed"] is True and g["n_problems"] == 0 and g["worlds"] == 1
    assert b["passed"] is False and b["n_problems"] >= 1 and b["worlds"] == 2


def test_an_empty_file_does_not_pass(V, tmp_path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    out = json.loads(subprocess.run([sys.executable, "-I", str(VERIFY), str(p)], capture_output=True, text=True, check=True).stdout)
    assert out["passed"] is False


def test_worlds_without_queries_do_not_pass(V, log, tmp_path) -> None:
    lg = copy.deepcopy(log)
    lg["queries"] = []
    p = tmp_path / "noq.jsonl"
    p.write_text(json.dumps(lg) + "\n", encoding="utf-8")
    out = json.loads(subprocess.run([sys.executable, "-I", str(VERIFY), str(p)], capture_output=True, text=True, check=True).stdout)
    assert out["n_problems"] == 0 and out["queries"] == 0 and out["passed"] is False
