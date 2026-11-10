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


# --- r2 recheck: registered partitions only inside their registered run --------------------
def _load_vgen():
    spec_ = importlib.util.spec_from_file_location("s3p3_vgen_under_test", VERIFY_GEN)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


FIN, DEV = frozenset({"standin-reg-final"}), frozenset({"standin-reg-dev"})


def test_authorize_registered_partitions(tmp_path) -> None:
    G = _load_vgen()
    root = tmp_path / "phase3"
    (root / "final-final").mkdir(parents=True)
    (root / "dev-dev1").mkdir()
    reg = FIN | DEV
    auth = lambda p, ns: G.authorize(p, ns, root=root, final_names=FIN, dev_names=DEV, registered=reg)[0]
    assert auth(tmp_path / "anything.jsonl", NS)  # not registered
    final_log = root / "final-final" / "worlds.jsonl"
    assert not auth(final_log, "standin-reg-final")  # no read-once marker yet
    (root / "FINAL_READ_ONCE.json").write_text("{}", encoding="utf-8")
    assert auth(final_log, "standin-reg-final")
    assert not auth(root / "final-final" / "other.jsonl", "standin-reg-final")
    assert not auth(tmp_path / "worlds.jsonl", "standin-reg-final")
    assert not auth(root / "dev-dev1" / "worlds.jsonl", "standin-reg-final")
    (root / "dev_uses.json").write_text(json.dumps([{"id": "dev1"}]), encoding="utf-8")
    assert not auth(root / "dev-dev1" / "worlds.jsonl", "standin-reg-dev")  # dev is never used in this phase
    assert not auth(root / "final-final" / "worlds.jsonl", "standin-reg-dev")
    assert not G.authorize(final_log, "standin-other", root=root, final_names=FIN, dev_names=DEV, registered=reg | {"standin-other"})[0]


def test_refusal_happens_before_anything_is_generated(tmp_path, monkeypatch, capsys) -> None:
    G = _load_vgen()

    def boom(*a, **k):
        raise AssertionError("generated a registered partition")

    monkeypatch.setattr(G.PS, "generate_sequence", boom)
    monkeypatch.setattr(G.PS, "REGISTERED", FIN | DEV)
    monkeypatch.setattr(G, "FINAL_NAMES", FIN)
    monkeypatch.setattr(G, "DEV_NAMES", DEV)
    monkeypatch.setattr(G, "ROOT", tmp_path / "phase3")
    p = tmp_path / "worlds.jsonl"
    p.write_text(json.dumps({"world": 0}) + "\n", encoding="utf-8")
    G.main(str(p), "standin-reg-final", 4)
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is False and out["worlds"] == 0 and "only inside the final run" in out["problems"][0]


def test_registered_names_match_the_generator() -> None:
    G = _load_vgen()
    assert G.FINAL_NAMES | G.DEV_NAMES == PS.REGISTERED
    assert G.ROOT == REPO / "artifacts/v9/s3/phase3"


def test_a_generator_that_loads_forbidden_code_fails(logs, tmp_path) -> None:
    """Make the generator import the retrieval cues; the check must notice it."""
    import shutil

    fake = tmp_path / "fake"
    shutil.copytree(REPO / "src/ainerzero", fake / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    p = fake / "src/ainerzero/v9/experiments/s3/persist.py"
    p.write_text(p.read_text(encoding="utf-8") + "\nfrom ainerzero.v9.experiments.s3 import cues as _unused  # noqa\n", encoding="utf-8")
    (fake / "reports/V9-S3-PHASE3").mkdir(parents=True)
    shutil.copy2(VERIFY_GEN, fake / "reports/V9-S3-PHASE3/verify_generation.py")
    out = _run(fake / "reports/V9-S3-PHASE3/verify_generation.py", _write(tmp_path, "ok.jsonl", logs), NS, EPISODES)
    assert out["passed"] is False and out["forbidden_loaded"] == ["ainerzero.v9.experiments.s3.cues"]


def test_a_run_file_that_links_outside_is_refused(tmp_path) -> None:
    G = _load_vgen()
    root = tmp_path / "phase3"
    (root / "final-final").mkdir(parents=True)
    (root / "FINAL_READ_ONCE.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "worlds.jsonl"
    outside.parent.mkdir()
    outside.write_text("", encoding="utf-8")
    (root / "final-final" / "worlds.jsonl").symlink_to(outside)
    ok, why = G.authorize(root / "final-final" / "worlds.jsonl", "standin-reg-final", root=root, final_names=FIN, dev_names=DEV, registered=FIN | DEV)
    assert not ok and "only inside the final run" in why
