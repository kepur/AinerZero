"""The real S4 phase 2 runner: start-up order, refusals that spend nothing, the weight check, the
final path, the independent checks and the files it leaves. Native (the runner imports MLX).

Every run happens in a throwaway copy of the repository with stand-in partitions, 60-step episodes
and a few worlds on the MLX CPU device, with copies of the phase-1 weights, so nothing here can
touch the live artifacts, the live lock or a registered partition. The runner derives its root
from its own path.
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

from ainerzero.v9.experiments.s4 import analysis_p2 as P2  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
HERE = "reports/V9-S4-PHASE2"
RUNNER, PREREG, MAKE = f"{HERE}/run_s4p2.py", f"{HERE}/PREREG-r1.json", f"{HERE}/make_prereg.py"
VERIFY = [f"{HERE}/verify_labels_p2.py", f"{HERE}/verify_replay_p2.py"]
ARTS = "artifacts/v9/s4/phase2"
WEIGHTS = "artifacts/v9/s4/phase1/final-final/weights"
STAND_IN = {"probe": "standin-s4p2-probe", "final": "standin-s4p2-final"}
TINY = [
    ('"smoke": {"sizes": (4, 2), "limit": 1800}', '"smoke": {"sizes": (2, 1), "limit": 900}'),
    ('"probe": {"sizes": P2.SIZES["probe"], "limit": 2 * 3600}', '"probe": {"sizes": (2, 1), "limit": 900}'),
    ('"final": {"sizes": P2.SIZES["final"], "limit": 2 * 3600}', '"final": {"sizes": (2, 1), "limit": 900}'),
    ("WORKERS = 6", "WORKERS = 2"),
    ('REPLAY_WORLDS = {"main": 3, "extrap": 2}', 'REPLAY_WORLDS = {"main": 1, "extrap": 1}'),
    ("STUDENT_WORLDS, STUDENT_CUT = 2, 150", "STUDENT_WORLDS, STUDENT_CUT = 1, 30"),
    # 60-step world 0 of the real smoke namespace has too few detections after step 30 for the
    # future-frame mutation to change any shared id; this stand-in's world 0 has enough
    ('SMOKE_NS = "s4p2x-smoke-eval"', 'SMOKE_NS = "s4p2x-test-eval"'),
]
APPROVAL = "S4-P2-FINAL-READ-APPROVED-TIER1-20261111"
SMOKE = ("--stage", "smoke", "--use-id", "s1")
PROBE = ("--stage", "probe", "--use-id", "p1")
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
    _sub(s4 / "analysis_p2.py", [('NAMESPACES = {"probe": "s4p2-probe", "final": "s4p2-final"}', "NAMESPACES = " + json.dumps(STAND_IN))])
    _sub(s4 / "world.py", [('REGISTERED = frozenset({"s4p1-final", "s4p2-final"})', f'REGISTERED = frozenset({{"{STAND_IN["final"]}"}})'),
                           ("STEPS = 300\n", "STEPS = 60\n")])
    (r / HERE).mkdir(parents=True)
    for f in (RUNNER, MAKE, *VERIFY):
        shutil.copy2(REPO / f, r / f)
    _sub(r / RUNNER, TINY + list(extra))
    (r / "reports/DESIGN.md").write_text("design", encoding="utf-8")
    (r / "artifacts/locks").mkdir(parents=True)
    shutil.copytree(REPO / WEIGHTS, r / WEIGHTS)
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "code")
    return r


def _run(root, *args, report="reports/out.json", pycache=True, timeout=900, isolated=True):
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


def _nothing_spent(root, report="reports/out.json"):
    assert not (root / report).exists() and not (root / ARTS).exists()


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    root = _make_root(tmp_path_factory.mktemp("smoke"))
    r = _run(root, *SMOKE)
    assert r.returncode == 0, r.stderr[-3000:]
    return root, json.loads((root / "reports/out.json").read_text())


def test_copy_never_uses_the_real_partitions(smoke) -> None:
    root, R = smoke
    text = (root / "src/ainerzero/v9/experiments/s4/analysis_p2.py").read_text()
    assert all(f'"{v}"' not in text for v in P2.NAMESPACES.values())
    assert R["namespace"] == "s4p2x-test-eval"


def test_smoke_runs_end_to_end_and_records_its_files(smoke) -> None:
    root, R = smoke
    out = root / ARTS / "smoke-s1"
    for name, digest in R["files_sha256"].items():
        assert _sha(out / name) == digest, name
    recs = [json.loads(x) for x in (out / "worlds.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in recs] == ["main", "main", "extrap"]
    want = {P2.cell_key(a, s) for a in P2.HAND + P2.LEARNED for s in P2.SEEDS}
    assert all(set(r["cells"]) == want for r in recs)
    assert all(set(r["dyn"]) == {"E-B"} | {f"{a}#{s}" for a in ("L-int", *P2.GATES) for s in P2.SEEDS} for r in recs)
    assert all("kstep" in r for r in recs if r["kind"] == "main") and all("kstep" not in r for r in recs if r["kind"] == "extrap")
    assert all(r["cells"][f"{a}#1"]["gate"][1] > 0 for r in recs for a in P2.GATES)
    assert all("gate" not in r["cells"][f"{a}#1"] for r in recs for a in ("E-B", "L-int"))
    rep = json.loads((out / "replay.json").read_text())
    assert set(rep["weights"]) == {f"{a}#{s}" for a in ("L-int", "L-ind") for s in P2.SEEDS}
    assert R["checks"]["labels"]["passed"] and R["checks"]["replay"]["passed"] and R["checks"]["student_view"]["passed"]
    assert R["checks"]["weights"]["passed"]
    assert R["checks"]["replay"]["checked"] == 2 * 33 == 2 * 3 * (len(P2.HAND) + len(P2.LEARNED))
    assert R["weights_sha256"] == {n: _sha(root / WEIGHTS / f"{n}.safetensors") for n in R["weights_sha256"]}
    assert R["pre_eval_seconds"] >= 0 and R["post_marker_seconds"] > 0
    assert set(R["result"]["gates"]) == {"GN", "GA", "GC", "GK1", "GK2", "GD", "GX", "GR"}
    assert 0 < R["descriptive"]["main"]["L-int-rand"]["gate_share"] < 0.06
    assert not R["result"]["legality"]["samples"]["passed"]       # two worlds are far below the registered sample counts
    assert R["prereg_sha256"] is None and R["code_dirty"] == []
    assert set(R["descriptive"]["main"]) == set(P2.HAND + P2.LEARNED)
    assert "L-int-g" in R["descriptive"]["kstep_position_error"]
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()


def test_busy_lock_spends_nothing(tmp_path) -> None:
    root = _make_root(tmp_path)
    fh = (root / "artifacts/locks/m0-worker.lock").open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _refused(_run(root, *SMOKE), "lock is busy")
    finally:
        fh.close()
    _nothing_spent(root)


@pytest.mark.parametrize("args,needle", [
    (("--stage", "smoke"), "needs a use id"),
    (("--stage", "smoke", "--use-id", "../x"), "invalid use id"),
    (("--stage", "probe", "--use-id", "p1", "--approval", APPROVAL), "only final"),
])
def test_bad_requests_claim_nothing(tmp_path, args, needle) -> None:
    root = _make_root(tmp_path)
    _refused(_run(root, *args), needle)
    _nothing_spent(root)


def test_smoke_must_not_read_a_registered_partition(tmp_path) -> None:
    root = _make_root(tmp_path, extra=[('SMOKE_NS = "s4p2x-test-eval"', f'SMOKE_NS = "{STAND_IN["final"]}"')])
    _refused(_run(root, *SMOKE), "must not read a registered partition")
    _nothing_spent(root)


@pytest.mark.parametrize("how", ["changed", "missing"])
def test_changed_or_missing_weights_are_refused_before_anything(tmp_path, how) -> None:
    root = _make_root(tmp_path)
    w = root / WEIGHTS / "L-ind#2.safetensors"
    if how == "changed":
        b = bytearray(w.read_bytes())
        b[-1] ^= 1
        w.write_bytes(bytes(b))
    else:
        w.unlink()
    _refused(_run(root, *SMOKE), "weights missing or changed")
    _nothing_spent(root)


def test_existing_report_and_run_directory_are_refused(tmp_path) -> None:
    root = _make_root(tmp_path)
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
    root = _make_root(tmp_path, extra=[('"smoke": {"sizes": (2, 1), "limit": 900}', '"smoke": {"sizes": (2, 1), "limit": 1}')])
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


def _frozen(root):
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
    return probe, json.loads((root / PREREG).read_text())


def test_final_path_after_a_frozen_probe(tmp_path) -> None:
    """probe -> make_prereg -> commit -> final: the final writes the one-time marker after the start-up
    checks, and a second final is refused; bad finals before it spend nothing."""
    root = _make_root(tmp_path)
    probe, pre = _frozen(root)
    assert pre["final_approval_line"] == APPROVAL and pre["gates"] == json.loads(json.dumps(P2.THRESHOLDS))
    assert RUNNER in pre["manifest"] and all(v in pre["manifest"] for v in VERIFY) and "reports/DESIGN.md" in pre["manifest"]
    assert "src/ainerzero/v9/experiments/s4/gated.py" in pre["manifest"] and "src/ainerzero/v9/experiments/s4/worker_p2.py" in pre["manifest"]
    assert pre["weights_sha256"] == probe["weights_sha256"]
    assert pre["budget"]["eval_reserve_s"] == math.ceil(1.5 * 4 * probe["post_marker_seconds"])
    _refused(_run(root, *FINAL, report="reports/f0.json"), "not committed")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze")
    _refused(_run(root, *FINAL, "--use-id", "x", report="reports/f1.json"), "takes no use id")
    _refused(_run(root, "--stage", "final", "--approval", "wrong", report="reports/f2.json"), "approval line")
    _refused(_run(root, *FINAL, report="reports/f3.json", pycache=False), "pycache_prefix")
    _refused(_run(root, *FINAL, report="reports/f4.json", isolated=False), "python -I")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
    r = _run(root, *FINAL, report="reports/final.json")
    assert r.returncode == 0, r.stderr[-3000:]
    R = json.loads((root / "reports/final.json").read_text())
    assert R["prereg_sha256"] == _sha(root / PREREG) and R["late_violations"] == [] and R["namespace"] == STAND_IN["final"]
    marker = json.loads((root / ARTS / "FINAL_READ_ONCE.json").read_text())
    assert marker["prereg_sha256"] == R["prereg_sha256"] and R["final_read_marker_sha256"] == _sha(root / ARTS / "FINAL_READ_ONCE.json")
    _refused(_run(root, *FINAL, report="reports/final2.json"), "run directory already exists")
    shutil.rmtree(root / ARTS / "final-final")
    _refused(_run(root, *FINAL, report="reports/final3.json"), "already been read")
    assert not (root / ARTS / "final-final").exists() and not (root / "reports/final3.json").exists()


def test_final_refuses_weights_that_differ_from_the_preregistration(tmp_path) -> None:
    root = _make_root(tmp_path)
    _frozen(root)
    pre = json.loads((root / PREREG).read_text())
    pre["weights_sha256"]["L-int#1"] = "0" * 64
    (root / PREREG).write_text(json.dumps(pre))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze with other weights")
    _refused(_run(root, *FINAL, report="reports/final.json"), "weights registered in the preregistration differ")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists() and not (root / "reports/final.json").exists()


def test_make_prereg_refuses_a_probe_with_other_weights(tmp_path) -> None:
    root = _make_root(tmp_path)
    r = _run(root, *PROBE, report=f"{HERE}/probe.json")
    assert r.returncode == 0, r.stderr[-3000:]
    probe = json.loads((root / HERE / "probe.json").read_text())
    probe["result"]["valid"] = True
    probe["weights_sha256"]["L-ind#3"] = "f" * 64
    (root / HERE / "probe.json").write_text(json.dumps(probe))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "probe")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    m = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"), "--probe", str(root / HERE / "probe.json"),
                        "--out", str(root / PREREG)], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert m.returncode != 0 and "权重" in m.stderr + m.stdout and not (root / PREREG).exists()


def test_final_refuses_a_changed_weight_file_before_the_marker(tmp_path) -> None:
    root = _make_root(tmp_path)
    _frozen(root)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze")
    w = root / WEIGHTS / "L-int#2.safetensors"           # artifacts/ is not tracked by git, editing it keeps git clean
    b = bytearray(w.read_bytes())
    b[-1] ^= 1
    w.write_bytes(bytes(b))
    _refused(_run(root, *FINAL, report="reports/final.json"), "weights missing or changed")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
    assert not (root / "reports/final.json").exists()


@pytest.mark.parametrize("reserve", [10 ** 6, 1000])
def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path, reserve) -> None:
    root = _make_root(tmp_path)
    _frozen(root)
    pre = json.loads((root / PREREG).read_text())
    pre["budget"]["eval_reserve_s"] = reserve
    (root / PREREG).write_text(json.dumps(pre))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "freeze with a reserve above the limit")
    _refused(_run(root, *FINAL, report="reports/final.json"), "the final read is not spent")
    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
