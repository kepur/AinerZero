"""The real S4 phase 1 runner: start-up order, refusals that spend nothing, the final path, the
independent checks and the files it leaves. Native (the runner imports MLX).

Every run happens in a throwaway copy of the repository with stand-in partitions, 60-step
episodes, a few worlds and a handful of training steps on the MLX CPU device, so nothing here can
touch the live artifacts, the live lock, the GPU or a registered partition. The runner derives its
root from its own path.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mlx.core")

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
HERE = "reports/V9-S4-PHASE1"
RUNNER, PREREG, MAKE = f"{HERE}/run_s4p1.py", f"{HERE}/PREREG-r1.json", f"{HERE}/make_prereg.py"
VERIFY = [f"{HERE}/verify_labels.py", f"{HERE}/verify_replay.py"]
ARTS = "artifacts/v9/s4/phase1"
STAND_IN = {"train": "standin-s4-train", "probe": "standin-s4-probe", "final": "standin-s4-final"}
TINY = [
    ('"smoke": {"n_train": 10, "sizes": (4, 2), "limit": 3600, "pool": 4000, "sigma": 2000}',
     '"smoke": {"n_train": 6, "sizes": (2, 1), "limit": 900, "pool": 300, "sigma": 200}'),
    ('"probe": {"n_train": A.N_TRAIN, "sizes": A.SIZES["probe"], "limit": 4 * 3600, "pool": 240_000, "sigma": 120_000}',
     '"probe": {"n_train": 8, "sizes": (2, 1), "limit": 900, "pool": 300, "sigma": 200}'),
    ('"final": {"n_train": A.N_TRAIN, "sizes": A.SIZES["final"], "limit": 4 * 3600, "pool": 240_000, "sigma": 120_000}',
     '"final": {"n_train": 8, "sizes": (2, 1), "limit": 900, "pool": 300, "sigma": 200}'),
    ("WORKERS = 6", "WORKERS = 2"),
    ("CALIB_FIT_WORLDS, CALIB_FIT_EVERY = 100, 3", "CALIB_FIT_WORLDS, CALIB_FIT_EVERY = 2, 3"),
    ('REPLAY_WORLDS = {"main": 3, "extrap": 2}', 'REPLAY_WORLDS = {"main": 1, "extrap": 1}'),
    ("STUDENT_WORLDS, STUDENT_CUT = 2, 150", "STUDENT_WORLDS, STUDENT_CUT = 1, 30"),
    ("    mx.set_default_device(mx.gpu)\n", "    mx.set_default_device(mx.cpu)\n"),
]
APPROVAL = "S4-P1-FINAL-READ-APPROVED-TIER1-20261110"
SMOKE = ("--stage", "smoke", "--use-id", "s1", "--steps", "3", "--batch", "4")
PROBE = ("--stage", "probe", "--use-id", "p1", "--steps", "3", "--batch", "4")
FINAL = ("--stage", "final", "--approval", APPROVAL)


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def _sub(path: Path, pairs):
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, (path, old)
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def _make_root(tmp_path, extra=()):
    r = tmp_path / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    s4 = r / "src/ainerzero/v9/experiments/s4"
    _sub(s4 / "analysis.py", [('NAMESPACES = {"train": "s4p1-train", "probe": "s4p1-probe", "final": "s4p1-final"}', "NAMESPACES = " + json.dumps(STAND_IN))])
    _sub(s4 / "world.py", [('REGISTERED = frozenset({"s4p1-final"})', f'REGISTERED = frozenset({{"{STAND_IN["final"]}"}})'), ("STEPS = 300\n", "STEPS = 60\n")])
    (r / HERE).mkdir(parents=True)
    for f in (RUNNER, MAKE, *VERIFY):
        shutil.copy2(REPO / f, r / f)
    _sub(r / RUNNER, TINY + list(extra))
    (r / "reports/DESIGN.md").write_text("design", encoding="utf-8")
    (r / "artifacts/locks").mkdir(parents=True)
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "code")
    return r


def _run(root, *args, report="reports/out.json", pycache=True, timeout=600, isolated=True):
    cmd = [sys.executable] + (["-I"] if isolated else [])
    if pycache:
        fresh = root.parent / f"pyc-{time.monotonic_ns()}"
        fresh.mkdir()
        cmd += ["-X", f"pycache_prefix={fresh}"]
    cmd += [str(root / RUNNER), "--report", str(root / report), *args]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)


def _refused(r, needle):
    assert r.returncode != 0, r.stdout[-800:] + r.stderr[-800:]
    assert needle in r.stderr, r.stderr[-1500:]


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


TRAIN_SPY = """

# test spy: every call of train is logged with its arm and time limit
_spied_train = train


def train(arm, *args, **kwargs):
    import json as _json, os as _os
    with open(_os.environ["S4_TRAIN_LOG"], "a") as _fh:
        _fh.write(_json.dumps({"arm": arm, "time_limit": kwargs.get("time_limit"), "steps": kwargs.get("steps")}) + chr(10))
    return _spied_train(arm, *args, **kwargs)
"""


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    root = _make_root(tmp_path_factory.mktemp("smoke"))
    lm = root / "src/ainerzero/v9/experiments/s4/learned_mlx.py"
    lm.write_text(lm.read_text() + TRAIN_SPY)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "spy")
    os.environ["S4_TRAIN_LOG"] = str(root / "train_calls.jsonl")
    r = _run(root, *SMOKE)
    assert r.returncode == 0, r.stderr[-3000:]
    return root, json.loads((root / "reports/out.json").read_text())


def test_copy_never_uses_the_real_partitions(smoke) -> None:
    root, R = smoke
    text = (root / "src/ainerzero/v9/experiments/s4/analysis.py").read_text()
    assert all(v not in text for v in A.NAMESPACES.values())
    assert R["namespaces"] == {"train": "s4p1x-smoke-train", "eval": "s4p1x-smoke-eval"}


def test_smoke_runs_end_to_end_and_records_its_files(smoke) -> None:
    root, R = smoke
    out = root / ARTS / "smoke-s1"
    assert set(R["training"]["cells"]) == {f"{a}#{s}" for a in ("L-ind", "L-int", "L-int-c", "L-int-e8", "L-int-c-e8", "L-int-s") for s in (1, 2, 3)}
    for name, digest in R["files_sha256"].items():
        assert _sha(out / name) == digest, name
    recs = [json.loads(x) for x in (out / "worlds.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in recs] == ["main", "main", "extrap"]
    main_keys = set(recs[0]["reid"])
    # L-int-s is trained (above) and described (calibration, below) but neither tracked nor replayed
    assert R["tracked_arms"] == ["L-ind", "L-int", "L-int-c", "L-int-e8", "L-int-c-e8"]
    assert not any(k.startswith("L-int-s") for r in recs for k in r["reid"])
    assert {c.key for c in A.plan_cells(R["tracked_arms"])} == main_keys
    assert {k for k in recs[2]["reid"]} == {c.key for c in A.plan_cells(R["tracked_arms"]) if c.variant == "base"}
    assert all(set(r["descriptive"]["calibration"]) == {"L-int-s#1", "L-int-s#2", "L-int-s#3"} for r in recs)
    rep = json.loads((out / "replay.json").read_text())
    assert set(rep["weights"]) == {f"{a}#{s}" for a in R["tracked_arms"] for s in (1, 2, 3)}
    assert R["checks"]["labels"]["passed"] and R["checks"]["replay"]["passed"] and R["checks"]["student_view"]["passed"]
    assert R["checks"]["replay"]["checked"] == 2 * (15 + 6)                  # tracked learned cells plus E-B and E-P
    assert "worlds.partial.jsonl" in R["files_sha256"] and R["result"]["legality"]["complete"]["passed"]
    assert R["pre_eval_seconds"] > 0 and R["post_marker_seconds"] > 0
    assert set(R["result"]["gates"]) == {"HD", "HF", "HD-x", "H1", "H2", "H3"}
    assert not R["result"]["legality"]["samples"]["passed"]       # two worlds are far below the registered sample counts
    assert R["prereg_sha256"] is None and R["code_dirty"] == []
    assert "calibration" in R["descriptive"] and "contact_f1" in R["descriptive"]
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()


def test_training_cells_are_sequential_and_seeded(smoke) -> None:
    root, R = smoke
    cells = R["training"]["cells"]
    assert all(c["loss"] and c["params"] > 0 for c in cells.values())
    assert cells["L-int-s#1"]["params"] > cells["L-int#1"]["params"]
    assert R["training"]["pools"]["eighth"]["size"] == 300 // 8


def test_busy_lock_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path)
    fh = (root / "artifacts/locks/m0-worker.lock").open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _refused(_run(root, *SMOKE), "lock is busy")
    finally:
        fh.close()
    assert not (root / "reports/out.json").exists() and not (root / ARTS).exists()


@pytest.mark.parametrize("args,needle", [
    (("--stage", "probe", "--use-id", "p1", "--batch", "4"), "positive --steps"),
    (("--stage", "smoke", "--steps", "3", "--batch", "4"), "needs a use id"),
    (("--stage", "smoke", "--use-id", "../x", "--steps", "3", "--batch", "4"), "invalid use id"),
    (("--stage", "probe", "--use-id", "p1", "--steps", "3", "--batch", "4", "--approval", APPROVAL), "only final"),
])
def test_bad_requests_claim_nothing(tmp_path, args, needle) -> None:
    root = _make_root(tmp_path)
    _refused(_run(root, *args), needle)
    assert not (root / "reports/out.json").exists() and not (root / ARTS).exists()


def test_smoke_must_not_read_a_registered_partition(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('SMOKE = {"train": "s4p1x-smoke-train", "eval": "s4p1x-smoke-eval"}',
                                        f'SMOKE = {{"train": "s4p1x-smoke-train", "eval": "{STAND_IN["final"]}"}}')])
    _refused(_run(root, *SMOKE), "must not read a registered partition")


def test_existing_report_and_run_directory_are_refused(tmp_path) -> None:
    root = _make_root(tmp_path)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports/out.json").write_text("keep")
    _refused(_run(root, *SMOKE), "report already exists")
    assert (root / "reports/out.json").read_text() == "keep"
    (root / ARTS / "smoke-s1").mkdir(parents=True)
    _refused(_run(root, *SMOKE, report="reports/other.json"), "run directory already exists")
    assert not (root / "reports/other.json").exists()


def test_final_needs_the_preregistration(tmp_path) -> None:
    root = _make_root(tmp_path)
    r = _run(root, *FINAL)
    assert r.returncode != 0 and not (root / ARTS / "FINAL_READ_ONCE.json").exists()


def test_wall_clock_limit_stops_the_run(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('"smoke": {"n_train": 6, "sizes": (2, 1), "limit": 900,', '"smoke": {"n_train": 6, "sizes": (2, 1), "limit": 1,')])
    _refused(_run(root, *SMOKE), "wall-clock limit")


@pytest.mark.parametrize("which,gate", [(0, "labels"), (1, "determinism")])
def test_failing_independent_check_invalidates(tmp_path, which, gate) -> None:
    root = _make_root(tmp_path)
    (root / VERIFY[which]).write_text('import json\nprint(json.dumps({"passed": False, "mismatches": ["planted"]}))\n')
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "planted verifier")
    r = _run(root, *SMOKE)
    assert r.returncode == 0, r.stderr[-2000:]
    R = json.loads((root / "reports/out.json").read_text())
    assert not R["result"]["valid"] and not R["result"]["legality"][gate]["passed"]
    others = {"labels", "determinism"} - {gate}
    assert all(R["result"]["legality"][k]["passed"] for k in others)
    assert not any(g["passed"] for g in R["result"]["gates"].values())


def test_final_path_after_a_frozen_probe(tmp_path) -> None:
    """probe -> make_prereg -> commit -> final: the final reads the preregistered steps, writes the
    one-time marker, and a second final is refused; a final with --steps is refused first."""
    root = _make_root(tmp_path)
    r = _run(root, *PROBE, report=f"{HERE}/probe.json")
    assert r.returncode == 0, r.stderr[-3000:]
    probe = json.loads((root / HERE / "probe.json").read_text())
    probe["result"]["valid"] = True            # two worlds cannot meet the sample gate; the freeze tool only reads this flag
    (root / HERE / "probe.json").write_text(json.dumps(probe))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "probe")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    m = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"), "--probe", str(root / HERE / "probe.json"),
                        "--out", str(root / PREREG)], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert m.returncode == 0, m.stderr[-2000:]
    pre = json.loads((root / PREREG).read_text())
    assert pre["training"]["steps"] == 3 and pre["training"]["batch"] == 4 and pre["final_approval_line"] == APPROVAL
    assert RUNNER in pre["manifest"] and all(v in pre["manifest"] for v in VERIFY) and "reports/DESIGN.md" in pre["manifest"]
    assert "src/ainerzero/v9/experiments/s4/worker_mlx.py" in pre["manifest"]
    scale = sum(A.SIZES["final"]) / sum(A.SIZES["probe"])
    assert scale == 4
    assert pre["budget"]["eval_reserve_s"] == math.ceil(1.5 * scale * probe["post_marker_seconds"])
    _refused(_run(root, *FINAL, report="reports/f0.json"), "not committed")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze")
    _refused(_run(root, *FINAL, "--steps", "5", report="reports/f1.json"), "from the preregistration only")
    _refused(_run(root, "--stage", "final", "--approval", "wrong", report="reports/f2.json"), "approval line")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
    _refused(_run(root, *FINAL, report="reports/f3.json", pycache=False), "pycache_prefix")
    r = _run(root, *FINAL, report="reports/final.json")
    assert r.returncode == 0, r.stderr[-3000:]
    R = json.loads((root / "reports/final.json").read_text())
    assert R["steps"] == 3 and R["prereg_sha256"] == _sha(root / PREREG) and R["late_violations"] == []
    assert R["namespaces"]["eval"] == STAND_IN["final"]
    assert (root / ARTS / "FINAL_READ_ONCE.json").exists()
    _refused(_run(root, *FINAL, report="reports/final2.json"), "run directory already exists")
    shutil.rmtree(root / ARTS / "final-final")
    _refused(_run(root, *FINAL, report="reports/final3.json"), "already been read")
    # refused up front: no run directory, no claimed report, nothing trained
    assert not (root / ARTS / "final-final").exists() and not (root / "reports/final3.json").exists()


@pytest.fixture(scope="module")
def small_probe(tmp_path_factory):
    root = _make_root(tmp_path_factory.mktemp("probe"))
    r = _run(root, *PROBE, report=f"{HERE}/probe.json")
    assert r.returncode == 0, r.stderr[-3000:]
    probe = json.loads((root / HERE / "probe.json").read_text())
    probe["result"]["valid"] = True
    (root / HERE / "probe.json").write_text(json.dumps(probe))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "probe")
    return root


def test_make_prereg_reserve_is_post_marker_time(small_probe) -> None:
    """The evaluation reserve is ceil(1.5 * scale * post_marker_seconds), not eval_seconds;
    and scale is sum(SIZES['final']) / sum(SIZES['probe']) == 4 (kills mp_reserve_eval_only)."""
    root = small_probe
    pr = json.loads((root / HERE / "probe.json").read_text())
    pr["post_marker_seconds"] = 100.0
    pr["eval_seconds"] = 37.0
    pr["pre_eval_seconds"] = 1000.0
    p1 = root / HERE / "probe_time.json"
    p1.write_text(json.dumps(pr))
    out1 = root / HERE / "prereg_time.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    m = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"),
                        "--probe", str(p1), "--out", str(out1)],
                       cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert m.returncode == 0, m.stderr[-2000:]
    pre = json.loads(out1.read_text())
    scale = sum(A.SIZES["final"]) / sum(A.SIZES["probe"])
    assert scale == 4
    assert pre["budget"]["eval_reserve_s"] == math.ceil(1.5 * scale * 100.0)
    assert pre["budget"]["eval_reserve_s"] != math.ceil(1.5 * scale * 37.0)
    assert pre["budget"]["probe_train_seconds"] == 1000.0


def test_make_prereg_refuses_when_training_plus_reserve_exceeds_four_hours(small_probe) -> None:
    """The budget guard checks 1.2 * pre_eval_seconds + eval_reserve_s > 4 * 3600 (14400 s);
    ignoring the reserve lets an over-budget run freeze (kills mp_budget_ignores_reserve)."""
    root = small_probe
    pr = json.loads((root / HERE / "probe.json").read_text())
    # 1. Over budget: 1.2 * 10000 = 12000 <= 14400, reserve = ceil(1.5 * 4 * 500) = 3000 -> total 15000 > 14400
    pr["pre_eval_seconds"] = 10000.0
    pr["post_marker_seconds"] = 500.0
    p_bad = root / HERE / "probe_over.json"
    p_bad.write_text(json.dumps(pr))
    out_bad = root / HERE / "prereg_over.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    m_bad = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"),
                            "--probe", str(p_bad), "--out", str(out_bad)],
                           cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert m_bad.returncode != 0
    assert "预计超出硬上限" in m_bad.stderr
    assert not out_bad.exists()

    # 2. Boundary: 1.2 * 10000 = 12000, reserve = ceil(1.5 * 4 * 400) = 2400 -> total exactly 14400 passes
    pr["pre_eval_seconds"] = 10000.0
    pr["post_marker_seconds"] = 400.0
    p_edge = root / HERE / "probe_edge.json"
    p_edge.write_text(json.dumps(pr))
    out_edge = root / HERE / "prereg_edge.json"
    m_edge = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"),
                             "--probe", str(p_edge), "--out", str(out_edge)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert m_edge.returncode == 0, m_edge.stderr[-2000:]
    assert out_edge.exists()


def test_post_marker_timing_starts_before_eval_generation(tmp_path) -> None:
    """The post-marker timer starts before evaluation worlds are generated so that world generation
    is covered by the evaluation reserve (kills ru_post_marker_after_generation)."""
    root = _make_root(tmp_path)
    w = root / "src/ainerzero/v9/experiments/s4/world.py"
    w.write_text(w.read_text() + f"""
import time
_orig_generate = generate_episode
def generate_episode(ns, *args, **kwargs):
    if ns == "{STAND_IN['probe']}":
        time.sleep(4.0)
    return _orig_generate(ns, *args, **kwargs)
""")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "wrap_world")
    r = _run(root, *PROBE)
    assert r.returncode == 0, r.stderr[-3000:]
    R = json.loads((root / "reports/out.json").read_text())
    # The probe evaluates 2 main + 1 extrapolation worlds, sleeping 4 s each: 12 s that only the
    # generation of evaluation worlds accounts for. A timer started after the generation leaves
    # only the other post-marker work (files, gates, description, the late check) in the difference.
    diff = R["post_marker_seconds"] - R["eval_seconds"] - R["check_seconds"]
    assert diff >= 11.5, f"post_marker_seconds must include eval world generation: {diff=}"


def _frozen_root(tmp_path, extra=(), reserve=0, plant=None, before_freeze=None, third_party=None):
    """A committed copy with a hand-made preregistration, ready for a final; ``plant`` replaces
    files (relative path -> text) and ``before_freeze(root)`` edits the copy before the freeze."""
    root = _make_root(tmp_path, extra=extra)
    for rel, text in (plant or {}).items():
        (root / rel).write_text(text)
    if before_freeze is not None:
        before_freeze(root)
    m = GD.build_manifest(root, [root / RUNNER], src_root=root / "src", extra=[root / "reports/DESIGN.md", *(root / v for v in VERIFY)])
    tp = GD.third_party_versions(REPO, ("numpy", "mlx")) if third_party is None else third_party
    (root / PREREG).write_text(json.dumps({"manifest": m, "third_party": tp,
                                           "final_approval_line": APPROVAL, "training": {"steps": 3, "batch": 4},
                                           "budget": {"eval_reserve_s": reserve}}))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze")
    return root


def test_final_that_fails_in_training_does_not_spend_the_read(tmp_path) -> None:
    """The marker is written after training and before the first registered world: a final stopped
    during training (here by the wall-clock limit) leaves no marker and has generated nothing of
    the registered partition; its run directory blocks a silent rerun."""
    root = _frozen_root(tmp_path, extra=[('"final": {"n_train": 8, "sizes": (2, 1), "limit": 900,', '"final": {"n_train": 8, "sizes": (2, 1), "limit": 1,')])
    _refused(_run(root, *FINAL), "wall-clock limit")
    out = root / ARTS / "final-final"
    assert out.is_dir() and not (root / ARTS / "FINAL_READ_ONCE.json").exists()
    assert not (out / "worlds.jsonl").exists() and not (out / "labels.jsonl").exists() and not (out / "replay.json").exists()
    R = json.loads((root / "reports/out.json").read_text())
    assert "result" not in R and "final_read_marker_sha256" not in R
    _refused(_run(root, *FINAL, report="reports/again.json"), "run directory already exists")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()


def test_registered_worlds_are_generated_only_after_the_marker(tmp_path) -> None:
    """In the runner source the marker is consumed before the only call that may generate the
    registered partition, and that call is the only one with allow_registered."""
    text = (REPO / RUNNER).read_text(encoding="utf-8")
    assert text.count("allow_registered") == 1 and text.count("GD.consume_final_read(") == 1
    assert text.index("GD.consume_final_read(") < text.index("allow_registered")
    assert text.index("train_all(train_eps") < text.index("GD.consume_final_read(")
    root = _frozen_root(tmp_path)
    r = _run(root, *FINAL)
    assert r.returncode == 0, r.stderr[-3000:]
    R = json.loads((root / "reports/out.json").read_text())
    assert R["final_read_marker_sha256"] == _sha(root / ARTS / "FINAL_READ_ONCE.json") and R["result"]["gates"]


def test_changed_frozen_module_is_refused_before_the_marker(tmp_path) -> None:
    root = _make_root(tmp_path)
    m = GD.build_manifest(root, [root / RUNNER], src_root=root / "src", extra=[root / "reports/DESIGN.md", *(root / v for v in VERIFY)])
    (root / PREREG).write_text(json.dumps({"manifest": m, "third_party": GD.third_party_versions(REPO, ("numpy", "mlx")),
                                           "final_approval_line": APPROVAL, "training": {"steps": 3, "batch": 4}}))
    f = root / "src/ainerzero/v9/experiments/s4/filter.py"
    f.write_text(f.read_text() + "\n# changed\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *FINAL), "frozen manifest does not hold")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()


@pytest.mark.parametrize("reserve", [10 ** 9, 1000])
def test_final_with_too_little_time_left_does_not_spend_the_read(tmp_path, reserve) -> None:
    """The evaluation reserve registered from the probe must remain when training ends. The final's
    limit here is 900 s and training takes seconds, so 1000 s is just over what is left: a check
    loosened to a fraction of the reserve would let it through."""
    root = _frozen_root(tmp_path, reserve=reserve)
    _refused(_run(root, *FINAL), "the final read is not spent")
    out = root / ARTS / "final-final"
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists() and not (out / "worlds.partial.jsonl").exists()


def test_a_training_cell_over_its_limit_stops_the_run(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[("CELL_LIMIT_S = 600", "CELL_LIMIT_S = 0")])
    _refused(_run(root, *SMOKE), "training cell over its limit")
    assert not (root / ARTS / "smoke-s1" / "worlds.partial.jsonl").exists()


def test_student_check_needs_the_mutation_to_change_something(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[("STUDENT_WORLDS, STUDENT_CUT = 1, 30", "STUDENT_WORLDS, STUDENT_CUT = 1, 100000")])
    r = _run(root, *SMOKE)
    assert r.returncode == 0, r.stderr[-2000:]
    R = json.loads((root / "reports/out.json").read_text())
    st = R["checks"]["student_view"]
    assert all(row["prefix_equal"] and not row["suffix_changed"] for row in st["rows"]) and not st["passed"]
    assert not R["result"]["valid"] and not R["result"]["legality"]["student_view"]["passed"]


def test_records_are_on_disk_world_by_world(smoke) -> None:
    root, R = smoke
    out = root / ARTS / "smoke-s1"
    part = [json.loads(x) for x in (out / "worlds.partial.jsonl").read_text().splitlines()]
    full = [json.loads(x) for x in (out / "worlds.jsonl").read_text().splitlines()]
    assert sorted(p["index"] for p in part) == list(range(len(full)))
    assert all(full[p["index"]] == p["record"] for p in part)
    assert R["eval_seconds"] > 0 and R["check_seconds"] > 0


def test_every_training_cell_gets_the_cell_limit(smoke) -> None:
    root, R = smoke
    calls = [json.loads(x) for x in (root / "train_calls.jsonl").read_text().splitlines()]
    assert len(calls) == 18 and {c["arm"] for c in calls} == {"L-ind", "L-int", "L-int-c", "L-int-s"}
    assert all(c["time_limit"] == 600 and c["steps"] == 3 for c in calls)


def test_a_frozen_file_changed_during_the_final_invalidates_it(tmp_path) -> None:
    """The second manifest check after the run: a planted verifier edits the frozen design text."""
    planted = ("import json, pathlib\n"
               "p = pathlib.Path(__file__).resolve().parents[2] / 'reports/DESIGN.md'\n"
               "p.write_text(p.read_text() + ' changed during the run')\n"
               "print(json.dumps({'passed': True}))\n")
    root = _frozen_root(tmp_path, plant={VERIFY[0]: planted})
    r = _run(root, *FINAL)
    assert r.returncode == 0, r.stderr[-2000:]
    R = json.loads((root / "reports/out.json").read_text())
    assert any("DESIGN.md" in v for v in R["late_violations"])
    # two worlds fail the sample gate anyway, so the run is invalid either way: check that the late
    # check is what voided every gate
    assert not R["result"]["valid"]
    assert all(g["void"] == "frozen files or modules changed during the run" and not g["passed"] for g in R["result"]["gates"].values())


def test_replay_verifier_catches_a_changed_assignment(smoke, tmp_path) -> None:
    root, R = smoke
    out = root / ARTS / "smoke-s1"
    rep = json.loads((out / "replay.json").read_text())
    recs = [json.loads(x) for x in (out / "worlds.jsonl").read_text().splitlines()]
    w = rep["worlds"][0]
    target = next(r for r in recs if (r["kind"], r["world"]) == (w["kind"], w["world"]))
    key = A.Cell("L-int-c", 2).key
    target["ids_sha256"][key] = "0" * 64
    bad = tmp_path / "worlds-bad.jsonl"
    bad.write_text("".join(json.dumps(r) + "\n" for r in recs))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}

    def verify(worlds):
        r = subprocess.run([sys.executable, "-I", str(root / VERIFY[1]), str(out / "replay.json"), str(worlds), str(out)],
                           cwd=root, env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(r.stdout)

    honest, tampered = verify(out / "worlds.jsonl"), verify(bad)
    assert honest["passed"] and honest["checked"] == 2 * (15 + 6)
    assert not tampered["passed"] and tampered["mismatches"] == [f"{w['kind']} {w['world']} {key}"]
    # a hand-made cell (the denominator of C) and a flipped correctness flag are caught too
    recs2 = [json.loads(x) for x in (out / "worlds.jsonl").read_text().splitlines()]
    replayed = {(x["kind"], x["world"]) for x in rep["worlds"]}
    t2 = next(r for r in recs2 if (r["kind"], r["world"]) in replayed and r["events"])
    where = f"{t2['kind']} {t2['world']}"
    t2["ids_sha256"][A.Cell("E-B", 1).key] = "0" * 64
    flip_key = A.Cell("L-int", 3).key
    t2["reid"][flip_key][0] = 1 - t2["reid"][flip_key][0]
    bad2 = tmp_path / "worlds-bad2.jsonl"
    bad2.write_text("".join(json.dumps(r) + "\n" for r in recs2))
    out2 = verify(bad2)
    assert not out2["passed"]
    assert f"{where} {A.Cell('E-B', 1).key}" in out2["mismatches"] and f"{where} {flip_key} reid" in out2["mismatches"]
    # nothing to check is not a pass
    empty = tmp_path / "replay-empty.json"
    empty.write_text(json.dumps(dict(rep, worlds=[])))
    r = subprocess.run([sys.executable, "-I", str(root / VERIFY[1]), str(empty), str(out / "worlds.jsonl"), str(out)],
                       cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and not json.loads(r.stdout)["passed"]


def test_a_module_loaded_outside_the_manifest_during_the_final_invalidates_it(tmp_path) -> None:
    """The second check also covers loaded modules: analysis loads, after the start-up checks and
    through a dynamic import the manifest builder cannot see, a module that is not frozen."""
    def plant(root):
        s4 = root / "src/ainerzero/v9/experiments/s4"
        (s4 / "unfrozen_extra.py").write_text("VALUE = 1\n")
        _sub(s4 / "analysis.py", [("def summarize_descriptive(main: Sequence[dict], extrap: Sequence[dict], learned_arms: Sequence[str]) -> dict[str, Any]:\n",
                                   "def summarize_descriptive(main: Sequence[dict], extrap: Sequence[dict], learned_arms: Sequence[str]) -> dict[str, Any]:\n"
                                   "    import importlib\n    importlib.import_module('ainerzero.v9.experiments.s4.' + 'unfrozen_extra')\n")])
    root = _frozen_root(tmp_path, before_freeze=plant)
    pre = json.loads((root / PREREG).read_text())
    assert "src/ainerzero/v9/experiments/s4/unfrozen_extra.py" not in pre["manifest"]
    r = _run(root, *FINAL)
    assert r.returncode == 0, r.stderr[-2000:]
    R = json.loads((root / "reports/out.json").read_text())
    assert any("unfrozen_extra" in v for v in R["late_violations"])
    # two worlds fail the sample gate anyway, so the run is invalid either way: check that the late
    # check is what voided every gate
    assert not R["result"]["valid"]
    assert all(g["void"] == "frozen files or modules changed during the run" and not g["passed"] for g in R["result"]["gates"].values())


def test_final_needs_an_isolated_interpreter(tmp_path) -> None:
    root = _frozen_root(tmp_path)
    _refused(_run(root, *FINAL, isolated=False), "python -I")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists() and not (root / "reports/out.json").exists()


def test_final_with_other_library_versions_is_refused(tmp_path) -> None:
    real = GD.third_party_versions(REPO, ("numpy", "mlx"))
    root = _frozen_root(tmp_path, third_party=dict(real, mlx="0.0.1"))
    _refused(_run(root, *FINAL), "library versions differ")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists() and not (root / "reports/out.json").exists()
