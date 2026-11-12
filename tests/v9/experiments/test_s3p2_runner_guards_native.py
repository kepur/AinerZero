"""The real S3 phase 2 runner: start-up order, the path after the ledger, and its wiring.

Runner runs happen in a throwaway copy of the repository with tiny data, so nothing here can
touch the live artifacts or the live lock. The runner derives its root from its own path.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

from ainerzero.v9.experiments.s3 import analysis_p2 as AP  # noqa: E402
from ainerzero.v9.experiments.s3 import arms_mlx as A  # noqa: E402
from ainerzero.v9.experiments.s3 import batching as B  # noqa: E402
from ainerzero.v9.experiments.s3 import replay as RP  # noqa: E402
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s3 import spec  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
RUNNER = "reports/V9-S3-PHASE2/run_phase2.py"
APPROVAL = "TEST-APPROVAL-LINE"
CAPACITY = 16
REAL_NAMESPACES = AP.NAMESPACES
BUILD_HOOK = (
    "def build(ns, tag, n_w, n_e, family, base, want_rows=False):\n    out, rows = [], []\n",
    "def build(ns, tag, n_w, n_e, family, base, want_rows=False):\n"
    '    with (REPO / "build_calls.jsonl").open("a") as fh:\n'
    "        fh.write(json.dumps([ns, tag, family, base]) + chr(10))\n"
    "    out, rows = [], []\n",
)


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def _tiny(text, extra=()):
    subs = [
        ('"dev": {"ns": "dev", "train": (400, 4), "eval": (50, 2), "steps": (F1_STEPS, F2_STEPS), "limit": 5400}', '"dev": {"ns": "dev", "train": (6, 2), "eval": (6, 2), "steps": (4, 2), "limit": 600}'),
        ('"final": {"ns": "final", "train": (400, 4), "eval": (100, 2), "steps": (F1_STEPS, F2_STEPS), "limit": 5400}', '"final": {"ns": "final", "train": (6, 2), "eval": (6, 2), "steps": (4, 2), "limit": 600}'),
        ('clamp=a.stage == "smoke"', "clamp=True"),
        *extra,
    ]
    for old, new in subs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


STAND_IN = {"train": "standin-train", "dev": "standin-dev", "final": "standin-final", "probe": "standin-probe"}


def _stand_in_partitions(root):
    """A runner test must never generate a registered partition, final above all."""
    p = root / "src/ainerzero/v9/experiments/s3/analysis_p2.py"
    text = p.read_text(encoding="utf-8")
    line = "NAMESPACES = " + json.dumps(REAL_NAMESPACES)
    assert text.count(line) == 1, line
    p.write_text(text.replace(line, "NAMESPACES = " + json.dumps(STAND_IN)), encoding="utf-8")


def _make_root(tmp_path, extra=(), mutate_prereg=None):
    r = tmp_path / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    _stand_in_partitions(r)
    (r / "reports/V9-S3-PHASE2").mkdir(parents=True)
    (r / RUNNER).write_text(_tiny((REPO / RUNNER).read_text(encoding="utf-8"), extra), encoding="utf-8")
    design = r / "reports/DESIGN.md"
    design.write_text("design", encoding="utf-8")
    (r / "artifacts/locks").mkdir(parents=True)
    prereg = {
        "manifest": GD.build_manifest(r, [r / RUNNER], src_root=r / "src", extra=[design]),
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx.core")),
        "dev_max_uses": 2,
        "final_approval_line": APPROVAL,
        "h3_capacity": CAPACITY,
    }
    if mutate_prereg:
        mutate_prereg(prereg)
    (r / "reports/V9-S3-PHASE2/PREREG-r1.json").write_text(json.dumps(prereg), encoding="utf-8")
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
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
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=200)


def _spent(root):
    a = root / "artifacts/v9/s3/phase2"
    return (a / "dev_uses.json").exists() or (a / "FINAL_READ_ONCE.json").exists()


DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x")
FINAL = ("--stage", "final", "--approval", APPROVAL)


def _refused(r, needle):
    assert r.returncode != 0, r.stdout[-800:] + r.stderr[-800:]
    assert needle in r.stderr, r.stderr[-1500:]


def _out(root):
    return root / "reports/out.json"


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
    """The S2 world was outside the phase 1 manifest."""
    f = root / "src/ainerzero/v9/experiments/s2/world.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *args), "frozen manifest does not hold")
    assert not _spent(root) and not _out(root).exists()


def test_changed_design_spends_nothing(root) -> None:
    (root / "reports/DESIGN.md").write_text("other", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *DEV), "frozen manifest does not hold")
    assert not _spent(root)


def test_uncommitted_preregistration_spends_nothing(root) -> None:
    p = root / "reports/V9-S3-PHASE2/PREREG-r1.json"
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
    """Review r1 must-fix 1: this used to fail after the use was already spent."""
    (root / "artifacts/v9/s3/phase2" / run_dir).mkdir(parents=True)
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
    assert not (root / "artifacts/escaped").exists() and not (root / "artifacts/v9/s3/phase2/a").exists()


def test_library_version_mismatch_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path, mutate_prereg=lambda p: p["third_party"].update({"numpy": "0.0.0"}))
    _refused(_run(root, *DEV), "library versions")
    assert not _spent(root)


def test_a_loaded_module_outside_the_manifest_spends_nothing(tmp_path) -> None:
    gone = "src/ainerzero/v9/experiments/s3/replay.py"
    root = _make_root(tmp_path, mutate_prereg=lambda p: p["manifest"].pop(gone))
    _refused(_run(root, *DEV), "not frozen")
    assert not _spent(root)


def test_a_stage_reading_the_wrong_partition_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('"dev": {"ns": "dev",', '"dev": {"ns": "probe",')])
    _refused(_run(root, *DEV), "must read")
    assert not _spent(root)


def _exhausted(root):
    a = root / "artifacts/v9/s3/phase2"
    a.mkdir(parents=True)
    ledger = a / "dev_uses.json"
    ledger.write_text(json.dumps([{"id": "a"}, {"id": "b"}]), encoding="utf-8")
    return ledger


def test_refused_ledger_leaves_no_shell_behind(root) -> None:
    ledger = _exhausted(root)
    before = ledger.read_text(encoding="utf-8")
    _refused(_run(root, *DEV), "exhausted")
    assert ledger.read_text(encoding="utf-8") == before
    assert not _out(root).exists() and not (root / "artifacts/v9/s3/phase2/dev-dev1").exists()


def test_dev_limit_comes_from_the_preregistration(tmp_path) -> None:
    root = _make_root(tmp_path, mutate_prereg=lambda p: p.update(dev_max_uses=3))
    _exhausted(root)
    r = _run(root, *DEV)
    assert r.returncode == 0, r.stderr[-1500:]


def test_wall_clock_limit_stops_the_run(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('"limit": 900}', '"limit": 0}')])
    _refused(_run(root, "--stage", "smoke", "--use-id", "t"), "wall-clock limit")


def test_runner_test_copies_never_use_registered_partitions(root) -> None:
    text = (root / "src/ainerzero/v9/experiments/s3/analysis_p2.py").read_text(encoding="utf-8")
    for name in REAL_NAMESPACES.values():
        assert f'"{name}"' not in text
    assert all(f'"{name}"' in text for name in STAND_IN.values())


def test_wrong_approval_claims_and_spends_nothing(root) -> None:
    _refused(_run(root, "--stage", "final", "--approval", "NOPE"), "approval")
    assert not _spent(root) and not _out(root).exists()


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_dev_runs_through_the_path_after_the_ledger(root) -> None:
    r = _run(root, *DEV)
    assert r.returncode == 0, r.stderr[-2000:]
    a = root / "artifacts/v9/s3/phase2"
    assert [(u["id"], u["purpose"]) for u in json.loads((a / "dev_uses.json").read_text(encoding="utf-8"))] == [("dev1", "x")]
    R = json.loads(_out(root).read_text(encoding="utf-8"))
    calls = [json.loads(line) for line in (root / "build_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls == [
        ["standin-train", "", "F1", 0],
        ["standin-train", "f2-", "F2", 10_000_000],
        ["standin-dev", "", "F1", 20_000_000],
        ["standin-dev", "f2-", "F2", 30_000_000],
    ]
    assert {"min_sample_F1", "min_sample_F2"} <= set(R["result"]["legality"])
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert R["git_head"] == head and R["prereg_sha256"] == _sha(root / "reports/V9-S3-PHASE2/PREREG-r1.json")
    assert R["h3_capacity"] == CAPACITY and R["result"]["h3_prime"]["capacity"] == CAPACITY
    assert R["late_violations"] == []
    assert "h1" in R["result"] and "h1" in R["result"]["claims"]
    assert R["result"]["valid"] is False and not any(R["result"]["claims"].values())  # too few events
    assert R["cells"]["A2-R64/1"]["buffer_episodes"] == 12  # clamped by the tiny copy
    run = a / "dev-dev1"
    cell = R["cells"]["A2-C0/1"]
    for phase in ("F1", "F1_after", "F2"):
        assert cell["events_sha256"][phase] == _sha(run / f"A2-C0-s1-{phase}.npz")
    assert cell["weights_F1_sha256"] == _sha(run / "A2-C0-s1-F1.weights.npz")
    assert cell["weights_end_sha256"] == _sha(run / "A2-C0-s1-end.weights.npz")
    f1, f2 = np.load(run / "A2-C0-s1-F1.npz"), np.load(run / "A2-C0-s1-F2.npz")
    assert set(f1["pred_8"].tolist()) <= set(spec.F1_TOKENS)
    assert set(f2["pred_8"].tolist()) <= set(spec.F2_TOKENS)
    assert np.array_equal(f1["correct"], f1["pred"] == f1["answer"])


def test_final_runs_once(root) -> None:
    r = _run(root, *FINAL)
    assert r.returncode == 0, r.stderr[-2000:]
    a = root / "artifacts/v9/s3/phase2"
    assert (a / "FINAL_READ_ONCE.json").exists() and (a / "final-final").is_dir()
    assert json.loads(_out(root).read_text(encoding="utf-8"))["late_violations"] == []
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
    assert R["result"]["valid"] is False and "invalid_reason" in R["result"]
    assert not any(R["result"]["claims"].values())


@pytest.fixture(scope="module")
def run_module():
    spec_ = importlib.util.spec_from_file_location("s3p2_runner_under_test", REPO / RUNNER)
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    try:
        yield mod
    finally:
        mx.set_default_device(prev)


def test_registered_constants_of_the_runner(run_module) -> None:
    m = run_module
    assert (m.SEEDS, m.F1_STEPS, m.F2_STEPS, m.BATCH, m.MIX, m.LR, m.LAM) == ((1, 2, 3), 2000, 1000, 16, 8, 1e-3, 1.0)
    assert (m.BUFFER_SEED, m.CN_SEED, m.N_SEED) == (7_000_000, 7_100_000, 7_200_000)
    full = (m.F1_STEPS, m.F2_STEPS)
    assert m.STAGES["dev"] == {"ns": "dev", "train": (400, 4), "eval": (50, 2), "steps": full, "limit": 5400}
    assert m.STAGES["final"] == {"ns": "final", "train": (400, 4), "eval": (100, 2), "steps": full, "limit": 5400}
    assert m.STAGES["probe"]["ns"] == m.STAGES["smoke"]["ns"] == "probe"


def test_evaluation_uses_the_hard_top_candidate(run_module, monkeypatch) -> None:
    eps, _ = run_module.build("test-s3p2-runner", "", 3, 1, "F1", 0)
    mx.random.seed(1)
    m = A.ReadoutArm("A3")
    mx.eval(m.parameters())
    seen = []
    real = run_module.A.forward

    def spy(model, b, *, hard):
        seen.append(hard)
        return real(model, b, hard=hard)

    monkeypatch.setattr(run_module.A, "forward", spy)
    run_module.per_event(m, eps, spec.F1_TOKENS)
    assert seen and all(seen)


def test_conditions_wiring(run_module) -> None:
    c = run_module.conditions(True)
    assert c["A3S"] == ("A3", "plain", "f1")
    assert c["A3H-C0"] == ("A3", "sampled", "none")
    assert c["A2-C0"] == ("A2", "plain", "none")
    assert c["A2-CN"] == ("A2", "plain", "CN")
    assert c["A1"] == ("A1", "plain", "f1")
    for mem, loss in (("A2", "plain"), ("A3H", "sampled")):
        for cap in (16, 64, 256):
            assert c[f"{mem}-R{cap}"][1:] == (loss, f"R{cap}")
        assert c[f"{mem}-J"][2] == "joint"
    assert "A1" not in run_module.conditions(False)


def _tagged(n, tag):
    """Episodes whose identity can be read back from the answer field."""
    return [
        B.PreparedEpisode(
            obs=np.zeros((10, spec.OBS_DIM), dtype=np.float32),
            query_t=np.array([6, 7], dtype=np.int32),
            top1=np.array([1, 2], dtype=np.int32),
            oracle=np.array([1, 2], dtype=np.int32),
            shuffled=np.array([0, 1], dtype=np.int32),
            candidates=np.zeros((2, 12), dtype=np.int32),
            cand_feats=np.zeros((2, 12, 3), dtype=np.float32),
            cand_mask=np.ones((2, 12), dtype=bool),
            answer=np.array([tag * 1000 + i, tag * 1000 + i + 500], dtype=np.int32),
            swapped=np.ones(2, dtype=bool),
            bucket=np.full(2, 3, dtype=np.int32),
        )
        for i in range(n)
    ]


def _sources(batch):
    return [int(e.answer[0]) // 1000 for e in batch]


def test_no_replay_samples_only_the_new_family(run_module) -> None:
    tr1, tr2 = _tagged(300, 1), _tagged(300, 2)
    sampler, n = run_module.f2_sampler("none", tr1, tr2, 1, clamp=False)
    batch = sampler(np.random.default_rng(0))
    assert n == 0 and len(batch) == run_module.BATCH and set(_sources(batch)) == {2}


@pytest.mark.parametrize("how,cap", [("R16", 16), ("R64", 64), ("R256", 256)])
def test_replay_mixes_eight_new_with_eight_from_the_old_buffer(run_module, how, cap) -> None:
    tr1, tr2 = _tagged(300, 1), _tagged(300, 2)
    sampler, n = run_module.f2_sampler(how, tr1, tr2, 2, clamp=False)
    assert n == cap
    allowed = {int(tr1[j].answer[0]) for j in RP.buffer_indices(len(tr1), cap, run_module.BUFFER_SEED + 2)}
    for s in range(30):
        batch = sampler(np.random.default_rng(s))
        assert _sources(batch) == [2] * 8 + [1] * 8
        assert {int(e.answer[0]) for e in batch[8:]} <= allowed


def test_content_control_replays_the_r64_episodes_with_permuted_answers(run_module) -> None:
    tr1, tr2 = _tagged(300, 1), _tagged(300, 2)
    sampler, n = run_module.f2_sampler("CN", tr1, tr2, 3, clamp=False)
    idx = RP.buffer_indices(len(tr1), 64, run_module.BUFFER_SEED + 3)
    original = {int(a) for j in idx for a in tr1[j].answer}
    seen, moved = set(), 0
    index_of_obs = {id(tr1[j].obs): j for j in idx}
    for s in range(60):
        for e in sampler(np.random.default_rng(s))[8:]:
            assert id(e.obs) in index_of_obs
            seen |= {int(a) for a in e.answer}
            moved += not np.array_equal(e.answer, tr1[index_of_obs[id(e.obs)]].answer)
    assert n == 64 and seen <= original and moved > 0


def test_clamp_only_when_asked(run_module) -> None:
    tr1, tr2 = _tagged(20, 1), _tagged(20, 2)
    assert run_module.f2_sampler("R64", tr1, tr2, 1, clamp=True)[1] == 20
    with pytest.raises(ValueError):
        run_module.f2_sampler("R64", tr1, tr2, 1, clamp=False)


def test_build_gives_arm_n_only_past_records(run_module) -> None:
    eps, _ = run_module.build("test-s3p2-runner", "", 4, 1, "F1", 0)
    assert eps
    for p in eps:
        assert (p.shuffled <= p.query_t - RP.MIN_GAP).all()


@pytest.mark.parametrize("family,tokens", [("F1", spec.F1_TOKENS), ("F2", spec.F2_TOKENS)])
def test_restricted_readout_stays_in_the_family(run_module, family, tokens) -> None:
    eps, _ = run_module.build("test-s3p2-runner", "", 3, 1, family, 0)
    mx.random.seed(1)
    m = A.ReadoutArm("A2")
    mx.eval(m.parameters())
    r = run_module.per_event(m, eps, tokens)
    assert set(r["pred_8"].tolist()) <= set(tokens)
    assert np.array_equal(r["correct_8"], r["pred_8"] == r["answer"])
    assert np.array_equal(r["correct"], r["pred"] == r["answer"])


@pytest.mark.parametrize("kind,attr", [("sampled", "a3_sampled_loss"), ("plain", "loss_fn")])
def test_training_dispatches_the_registered_loss(run_module, monkeypatch, kind, attr) -> None:
    eps, _ = run_module.build("test-s3p2-runner", "", 3, 1, "F1", 0)
    mx.random.seed(1)
    m = A.ReadoutArm("A3")
    mx.eval(m.parameters())
    calls = []
    owner = run_module.P if attr == "a3_sampled_loss" else run_module.A
    real = getattr(owner, attr)

    def spy(*args):
        calls.append(len(args))
        return real(*args)

    monkeypatch.setattr(owner, attr, spy)
    run_module.train(m, run_module.optim.Adam(learning_rate=1e-3), run_module.pick(eps, 3), 2, 5, kind, GD.Deadline(60))
    assert len(calls) == 2 and calls[0] == (3 if kind == "sampled" else 2)
