"""The real S3 phase 3 runner: start-up order, the path after the ledger, and its wiring. CPU only.

Runner runs happen in a throwaway copy of the repository with stand-in partitions and tiny
data, so nothing here can touch the live artifacts, the live lock or a registered partition.
The runner derives its root from its own path.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import analysis_p3 as AP  # noqa: E402
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
RUNNER = "reports/V9-S3-PHASE3/run_phase3.py"
PREREG = "reports/V9-S3-PHASE3/PREREG-r1.json"
VERIFY = "reports/V9-S3-PHASE3/verify_worlds.py"
VERIFY_GEN = "reports/V9-S3-PHASE3/verify_generation.py"
MAKE_PREREG = "reports/V9-S3-PHASE3/make_prereg.py"
ARTS = "artifacts/v9/s3/phase3"
APPROVAL = "TEST-APPROVAL-LINE"
REAL_NAMESPACES = AP.NAMESPACES
STAND_IN = {"train": "standin-train", "dev": "standin-dev", "final": "standin-final", "probe": "standin-probe"}
BUILD_HOOK = (
    "    cols = {k: [] for k in A.FIELDS}\n    off = {k: {f: [] for f in A.FIELDS} for k in A.OFFSETS}\n",
    '    with (REPO / "build_calls.jsonl").open("a") as fh:\n'
    "        fh.write(json.dumps([ns, n_worlds, n_episodes, registered]) + chr(10))\n"
    "    cols = {k: [] for k in A.FIELDS}\n    off = {k: {f: [] for f in A.FIELDS} for k in A.OFFSETS}\n",
)


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def _tiny(text, extra=()):
    subs = [
        ('"dev": {"ns": "dev", "worlds": 100, "episodes": PS.N_EPISODES, "limit": 1800}', '"dev": {"ns": "dev", "worlds": 3, "episodes": 8, "limit": 600}'),
        ('"final": {"ns": "final", "worlds": 200, "episodes": PS.N_EPISODES, "limit": 1800}', '"final": {"ns": "final", "worlds": 3, "episodes": 8, "limit": 600}'),
        *extra,
    ]
    for old, new in subs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def _stand_in_partitions(root):
    """A runner test must never generate a registered partition, final above all."""
    p = root / "src/ainerzero/v9/experiments/s3/analysis_p3.py"
    text = p.read_text(encoding="utf-8")
    line = "NAMESPACES = " + json.dumps(REAL_NAMESPACES)
    assert text.count(line) == 1, line
    p.write_text(text.replace(line, "NAMESPACES = " + json.dumps(STAND_IN)), encoding="utf-8")


def _make_root(tmp_path, extra=(), mutate_prereg=None, verifier=None):
    r = tmp_path / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    _stand_in_partitions(r)
    (r / "reports/V9-S3-PHASE3").mkdir(parents=True)
    (r / RUNNER).write_text(_tiny((REPO / RUNNER).read_text(encoding="utf-8"), extra), encoding="utf-8")
    design = r / "reports/DESIGN.md"
    design.write_text("design", encoding="utf-8")
    (r / VERIFY).write_text(verifier if verifier is not None else (REPO / VERIFY).read_text(encoding="utf-8"), encoding="utf-8")
    for f in (VERIFY_GEN, MAKE_PREREG):
        (r / f).write_text((REPO / f).read_text(encoding="utf-8"), encoding="utf-8")
    (r / "artifacts/locks").mkdir(parents=True)
    prereg = {
        "manifest": GD.build_manifest(r, [r / RUNNER], src_root=r / "src", extra=[design, r / VERIFY, r / VERIFY_GEN]),
        "third_party": GD.third_party_versions(REPO, ("numpy",)),
        "dev_max_uses": 2,
        "final_approval_line": APPROVAL,
    }
    if mutate_prereg:
        mutate_prereg(prereg)
    (r / PREREG).write_text(json.dumps(prereg), encoding="utf-8")
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\nbuild_calls.jsonl\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "frozen")
    return r


@pytest.fixture
def root(tmp_path):
    return _make_root(tmp_path, extra=[BUILD_HOOK])


def _run(root, *args, pycache=True, isolated=True, report="reports/out.json"):
    cmd = [sys.executable]
    if isolated:
        cmd += ["-I"]
    if pycache:
        fresh = root.parent / f"pyc-{time.monotonic_ns()}"
        fresh.mkdir()
        cmd += ["-X", f"pycache_prefix={fresh}"]
    cmd += [str(root / RUNNER), "--report", str(root / report), *args]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=300)


def _spent(root):
    a = root / ARTS
    return (a / "dev_uses.json").exists() or (a / "FINAL_READ_ONCE.json").exists()


DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x")
FINAL = ("--stage", "final", "--approval", APPROVAL)


def _refused(r, needle):
    assert r.returncode != 0, r.stdout[-800:] + r.stderr[-800:]
    assert needle in r.stderr, r.stderr[-1500:]


def _out(root):
    return root / "reports/out.json"


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize("args", [DEV, FINAL])
def test_busy_lock_spends_nothing(root, args) -> None:
    fh = (root / "artifacts/locks/m0-worker.lock").open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _refused(_run(root, *args), "lock is busy")
    finally:
        fh.close()
    assert not _spent(root) and not _out(root).exists()


@pytest.mark.parametrize("args", [DEV, FINAL])
def test_changed_transitive_dependency_spends_nothing(root, args) -> None:
    f = root / "src/ainerzero/v9/experiments/s2/world.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *args), "frozen manifest does not hold")
    assert not _spent(root) and not _out(root).exists()


def test_manifest_covers_the_new_and_the_frozen_modules(root) -> None:
    m = json.loads((root / PREREG).read_text(encoding="utf-8"))["manifest"]
    s3 = "src/ainerzero/v9/experiments/s3/"
    for name in ("persist", "promotion", "analysis_p3", "run_guard", "tour", "world", "store", "cues", "content", "data", "spec"):
        assert f"{s3}{name}.py" in m, name
    assert "src/ainerzero/v9/experiments/s2/world.py" in m and RUNNER in m and "reports/DESIGN.md" in m and VERIFY in m and VERIFY_GEN in m


def test_changed_design_spends_nothing(root) -> None:
    (root / "reports/DESIGN.md").write_text("other", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *DEV), "frozen manifest does not hold")
    assert not _spent(root)


def test_uncommitted_preregistration_spends_nothing(root) -> None:
    p = root / PREREG
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _refused(_run(root, *DEV), "not committed")
    assert not _spent(root)


def test_shared_bytecode_cache_is_refused(root) -> None:
    _refused(_run(root, *DEV, pycache=False), "pycache_prefix")
    assert not _spent(root)


def test_stale_bytecode_is_refused(root) -> None:
    prefix = root.parent / "stale"
    (prefix / "x").mkdir(parents=True)
    old = prefix / "x" / "old.cpython-312.pyc"
    old.write_bytes(b"0")
    os.utime(old, (1_000_000, 1_000_000))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    cmd = [sys.executable, "-I", "-X", f"pycache_prefix={prefix}", str(root / RUNNER), "--report", str(_out(root)), *DEV]
    _refused(subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=120), "stale bytecode")
    assert not _spent(root)


def test_non_isolated_interpreter_is_refused(root) -> None:
    _refused(_run(root, *DEV, isolated=False), "python -I")
    assert not _spent(root)


@pytest.mark.parametrize("args,run_dir", [(DEV, "dev-dev1"), (FINAL, "final-final")])
def test_existing_run_directory_spends_nothing(root, args, run_dir) -> None:
    (root / ARTS / run_dir).mkdir(parents=True)
    _refused(_run(root, *args), "run directory already exists")
    assert not _spent(root) and not _out(root).exists()


def test_existing_report_is_kept_and_spends_nothing(root) -> None:
    _out(root).write_text("earlier evidence", encoding="utf-8")
    _refused(_run(root, *DEV), "report already exists")
    assert not _spent(root)
    assert _out(root).read_text(encoding="utf-8") == "earlier evidence"


@pytest.mark.parametrize("args", [("--stage", "dev", "--use-id", "dev1"), ("--stage", "dev", "--purpose", "x")])
def test_bad_dev_request_claims_and_spends_nothing(root, args) -> None:
    _refused(_run(root, *args), "purpose")
    assert not _spent(root) and not _out(root).exists()


@pytest.mark.parametrize("use_id", [" dev1", "a/b", "../../../escaped", "dev.1"])
def test_use_id_cannot_leave_the_run_directory(root, use_id) -> None:
    _refused(_run(root, "--stage", "dev", "--use-id", use_id, "--purpose", "x"), "invalid use id")
    assert not _spent(root) and not _out(root).exists()
    assert not (root / "artifacts/escaped").exists() and not (root / ARTS / "a").exists()


def test_library_version_mismatch_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path, mutate_prereg=lambda p: p["third_party"].update({"numpy": "0.0.0"}))
    _refused(_run(root, *DEV), "library versions")
    assert not _spent(root)


def test_a_loaded_module_outside_the_manifest_spends_nothing(tmp_path) -> None:
    gone = "src/ainerzero/v9/experiments/s3/promotion.py"
    root = _make_root(tmp_path, mutate_prereg=lambda p: p["manifest"].pop(gone))
    _refused(_run(root, *DEV), "not frozen")
    assert not _spent(root)


def test_a_stage_reading_the_wrong_partition_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('"dev": {"ns": "dev",', '"dev": {"ns": "probe",')])
    _refused(_run(root, *DEV), "must read")
    assert not _spent(root)


def _exhausted(root):
    a = root / ARTS
    a.mkdir(parents=True)
    ledger = a / "dev_uses.json"
    ledger.write_text(json.dumps([{"id": "a"}, {"id": "b"}]), encoding="utf-8")
    return ledger


def test_refused_ledger_leaves_no_shell_behind(root) -> None:
    ledger = _exhausted(root)
    before = ledger.read_text(encoding="utf-8")
    _refused(_run(root, *DEV), "exhausted")
    assert ledger.read_text(encoding="utf-8") == before
    assert not _out(root).exists() and not (root / ARTS / "dev-dev1").exists()


def test_dev_limit_comes_from_the_preregistration(tmp_path) -> None:
    root = _make_root(tmp_path, mutate_prereg=lambda p: p.update(dev_max_uses=3))
    _exhausted(root)
    r = _run(root, *DEV)
    assert r.returncode == 0, r.stderr[-1500:]


def test_wall_clock_limit_stops_the_run(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('"episodes": 8, "limit": 600},\n    "probe"', '"episodes": 8, "limit": 0},\n    "probe"')])
    _refused(_run(root, "--stage", "smoke", "--use-id", "t"), "wall-clock limit")


def test_runner_test_copies_never_use_registered_partitions(root) -> None:
    text = (root / "src/ainerzero/v9/experiments/s3/analysis_p3.py").read_text(encoding="utf-8")
    for name in REAL_NAMESPACES.values():
        assert f'"{name}"' not in text
    assert all(f'"{name}"' in text for name in STAND_IN.values())


def test_wrong_approval_claims_and_spends_nothing(root) -> None:
    _refused(_run(root, "--stage", "final", "--approval", "NOPE"), "approval")
    assert not _spent(root) and not _out(root).exists()


def test_smoke_reads_probe_without_spending(root) -> None:
    r = _run(root, "--stage", "smoke", "--use-id", "t")
    assert r.returncode == 0, r.stderr[-1500:]
    assert not _spent(root)
    calls = [json.loads(x) for x in (root / "build_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls == [["s3p3x-smoke", 4, 8, False]]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    assert R["namespace"] == "s3p3x-smoke" and R["code_dirty"] == [] and R["code_manifest_sha256"] == _code_sha(root)
    assert R["result"]["legality"]["K2b_generator"]["passed"] and R["result"]["legality"]["K6_events_match_log"]["passed"]


def _code_sha(root):
    m = GD.build_manifest(root, [root / RUNNER], src_root=root / "src", extra=[root / VERIFY, root / VERIFY_GEN])
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("stage", ["smoke", "probe"])
def test_smoke_and_probe_need_a_use_id(root, stage) -> None:
    _refused(_run(root, "--stage", stage), "needs a use id")
    assert not _out(root).exists() and not (root / ARTS / f"{stage}-final").exists()


def test_an_uncommitted_code_change_is_recorded(root) -> None:
    f = root / "src/ainerzero/v9/experiments/s3/promotion.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    r = _run(root, "--stage", "smoke", "--use-id", "t")
    assert r.returncode == 0, r.stderr[-1500:]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    assert R["code_dirty"] == [" M src/ainerzero/v9/experiments/s3/promotion.py"]  # git porcelain and R["code_manifest_sha256"] == _code_sha(root)


def _prereg(root, probe_doc, name="p.json"):
    probe = root / "reports" / name
    probe.write_text(json.dumps(probe_doc), encoding="utf-8")
    out = root / "reports" / ("pre-" + name)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    r = subprocess.run([sys.executable, "-I", str(root / MAKE_PREREG), "--design", str(root / "reports/DESIGN.md"), "--probe", str(probe), "--out", str(out)],
                       cwd=root, env=env, capture_output=True, text=True, timeout=120)
    return r, out


def test_make_prereg_accepts_only_a_valid_clean_probe_of_the_frozen_code(root) -> None:
    good = {"stage": "probe", "namespace": "standin-probe", "result": {"valid": True}, "code_manifest_sha256": _code_sha(root), "code_dirty": []}
    for bad in (dict(good, stage="smoke"), dict(good, namespace="standin-dev"), dict(good, result={"valid": False}),
                dict(good, code_manifest_sha256="0" * 64), dict(good, code_dirty=["x.py"]), {k: v for k, v in good.items() if k != "code_dirty"}):
        r, out = _prereg(root, bad)
        assert r.returncode != 0 and not out.exists(), bad
    r, out = _prereg(root, good, name="good.json")
    assert r.returncode == 0, r.stderr[-1500:]
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["dev_max_uses"] == 0 and VERIFY in doc["manifest"] and VERIFY_GEN in doc["manifest"] and "reports/DESIGN.md" in doc["manifest"]
    assert doc["contract"]["code_manifest_sha256"] == _code_sha(root) and doc["contract"]["sample_band"] == AP.SAMPLE_BAND
    r2, _ = _prereg(root, good, name="good.json")
    assert r2.returncode != 0  # never overwrites


def test_dev_runs_through_the_path_after_the_ledger(root) -> None:
    r = _run(root, *DEV)
    assert r.returncode == 0, r.stderr[-2000:]
    a = root / ARTS
    assert [(u["id"], u["purpose"]) for u in json.loads((a / "dev_uses.json").read_text(encoding="utf-8"))] == [("dev1", "x")]
    calls = [json.loads(x) for x in (root / "build_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls == [["standin-dev", 3, 8, True]]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert R["git_head"] == head and R["prereg_sha256"] == _sha(root / PREREG)
    assert R["namespace"] == "standin-dev" and R["late_violations"] == []
    run = a / "dev-dev1"
    names = ["events.npz"] + [f"events_k{k}.npz" for k in AP.OFFSETS] + ["worlds.jsonl"]
    assert R["files_sha256"] == {n: _sha(run / n) for n in names}
    ev = dict(np.load(run / "events.npz"))
    off = {k: dict(np.load(run / f"events_k{k}.npz")) for k in AP.OFFSETS}
    assert set(ev) == set(AP.FIELDS) and sorted(set(ev["world"].tolist())) == [0, 1, 2]
    logs = [json.loads(x) for x in (run / "worlds.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [lg["world"] for lg in logs] == [0, 1, 2]
    lg = R["result"]["legality"]
    assert lg["K2_independent"]["passed"] is True and lg["K2_independent"]["report"]["worlds"] == 3
    assert lg["K2b_generator"]["passed"] is True and lg["K2b_generator"]["report"]["namespace"] == "standin-dev"
    assert lg["K6_events_match_log"]["passed"] is True
    again = AP.evaluate(ev, logs, stage="dev", n_worlds=3, external=lg["K2_independent"]["report"], external_gen=lg["K2b_generator"]["report"], offsets=off)
    assert json.dumps(again, sort_keys=True) == json.dumps(R["result"], sort_keys=True)
    assert set(R["result"]["descriptive"]) == {c[0] for c in AP.COMPARISONS} and set(R["result"]["offsets"]) == {str(k) for k in AP.OFFSETS}
    assert {"K1_versions", "K2_independent", "K2b_generator", "K3_restore_replay", "K4_labels", "K5_samples", "K6_events_match_log", "K7_offsets_same_events"} <= set(lg)
    assert lg["K7_offsets_same_events"]["passed"] is True
    # the offset files are the offset analyses of the same worlds, and they differ from each other
    sys.path.insert(0, str(root / "src"))
    try:
        import importlib

        PSf = importlib.import_module("ainerzero.v9.experiments.s3.persist")
        for k in AP.OFFSETS:
            want = {f: [] for f in AP.FIELDS}
            for w in range(3):
                cols, _ = AP.analyse_world(PSf.generate_sequence("standin-dev", w, n_episodes=8), offset=k, full=False)
                for f in want:
                    want[f] += cols[f]
            for f in AP.FIELDS:
                assert off[k][f].tolist() == want[f], (k, f)
    finally:
        sys.path.remove(str(root / "src"))
    preds = [tuple(off[k]["pred_L"].tolist()) for k in AP.OFFSETS]
    assert len(set(preds)) == len(preds)
    assert R["result"]["valid"] is False and lg["K5_samples"]["passed"] is False  # 3 worlds are outside the band


def test_failing_independent_check_invalidates(tmp_path) -> None:
    fake = 'import json\nprint(json.dumps({"passed": False, "n_problems": 1}))\n'
    root = _make_root(tmp_path, verifier=fake)
    r = _run(root, "--stage", "smoke", "--use-id", "t")
    assert r.returncode == 0, r.stderr[-1500:]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    assert R["result"]["legality"]["K2_independent"] == {"passed": False, "report": {"passed": False, "n_problems": 1}}
    assert R["result"]["valid"] is False


def test_crashing_independent_check_invalidates(tmp_path) -> None:
    root = _make_root(tmp_path, verifier="raise SystemExit(3)\n")
    r = _run(root, "--stage", "smoke", "--use-id", "t")
    assert r.returncode == 0, r.stderr[-1500:]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    assert R["result"]["legality"]["K2_independent"]["passed"] is False and R["result"]["valid"] is False


def test_independent_check_runs_isolated_on_the_written_log(tmp_path) -> None:
    spy = (
        "import json, sys\n"
        "open(sys.argv[1] + '.seen', 'w').write(json.dumps({'argv': sys.argv[1:], 'isolated': sys.flags.isolated, 'mods': sorted(m for m in sys.modules if m.startswith('ainerzero'))}))\n"
        "print(json.dumps({'passed': True}))\n"
    )
    root = _make_root(tmp_path, verifier=spy)
    r = _run(root, "--stage", "smoke", "--use-id", "t")
    assert r.returncode == 0, r.stderr[-1500:]
    seen = json.loads((root / ARTS / "smoke-t" / "worlds.jsonl.seen").read_text(encoding="utf-8"))
    assert seen["argv"] == [str(root / ARTS / "smoke-t" / "worlds.jsonl")] and seen["isolated"] == 1 and seen["mods"] == []


def test_final_runs_once(root) -> None:
    r = _run(root, *FINAL)
    assert r.returncode == 0, r.stderr[-2000:]
    a = root / ARTS
    assert (a / "FINAL_READ_ONCE.json").exists() and (a / "final-final").is_dir()
    assert json.loads(_out(root).read_text(encoding="utf-8"))["late_violations"] == []
    calls = [json.loads(x) for x in (root / "build_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls == [["standin-final", 3, 8, True]]
    shutil.rmtree(a / "final-final")
    _refused(_run(root, *FINAL, report="reports/out2.json"), "final has already been read")


def test_a_frozen_file_changed_during_the_run_invalidates_it(tmp_path) -> None:
    hook = (
        '            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])',
        '            (REPO / "reports/DESIGN.md").write_text("tampered", encoding="utf-8")\n'
        '            late = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])',
    )
    root = _make_root(tmp_path, extra=[hook])
    r = _run(root, *DEV)
    assert r.returncode == 0, r.stderr[-2000:]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    assert R["late_violations"] == ["changed: reports/DESIGN.md"]
    assert R["result"]["valid"] is False and R["result"]["invalid_reason"] == "frozen files or modules changed during the run"


def test_registered_stage_sizes_of_the_runner() -> None:
    import importlib.util

    spec_ = importlib.util.spec_from_file_location("s3p3_runner_under_test", REPO / RUNNER)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    assert {k: (v["ns"], v["worlds"], v["episodes"]) for k, v in mod.STAGES.items()} == {
        "smoke": (None, 4, 8), "probe": ("probe", 100, 12), "dev": ("dev", 100, 12), "final": ("final", 200, 12)}
    assert all(v["limit"] <= 1800 for v in mod.STAGES.values())
    assert mod.SMOKE_NAMESPACE == "s3p3x-smoke" and mod.SMOKE_NAMESPACE not in AP.NAMESPACES.values()
    assert mod.THIRD_PARTY == ("numpy",) and "mlx" not in (REPO / RUNNER).read_text(encoding="utf-8").split('"""')[2]


def _runner_module():
    import importlib.util

    spec_ = importlib.util.spec_from_file_location("s3p3_runner_timeout_test", REPO / RUNNER)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def test_verifier_timeout_is_the_time_left_in_the_run(monkeypatch) -> None:
    mod = _runner_module()
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, json.dumps({"passed": True}), ""

    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return Done()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.independent_check(mod.VERIFY, "w.jsonl", deadline=GD.Deadline(37)) == {"passed": True}
    assert 30 < seen["timeout"] <= 37 and seen["cmd"][1] == "-I"
    with pytest.raises(GD.GuardError, match="wall-clock"):
        mod.independent_check(mod.VERIFY, "w.jsonl", deadline=GD.Deadline(-1))

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(mod.subprocess, "run", slow)
    with pytest.raises(GD.GuardError, match="wall-clock"):
        mod.independent_check(mod.VERIFY, "w.jsonl", deadline=GD.Deadline(5))
