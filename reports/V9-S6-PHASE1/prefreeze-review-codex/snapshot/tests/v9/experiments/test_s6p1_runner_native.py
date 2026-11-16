"""S6 phase 1 runner end to end on the smoke set, in a throwaway copy of the repo (its own lock, artifacts and
git), plus the refusals that protect the registered set. MLX."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mlx.core")
pytestmark = pytest.mark.native_mlx

REPO = Path(__file__).resolve().parents[3]
HERE = "reports/V9-S6-PHASE1"
FILES = (f"{HERE}/run_s6p1.py", f"{HERE}/verify_s6p1.py")


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


def _make_root(tmp: Path) -> Path:
    r = tmp / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (r / HERE).mkdir(parents=True)
    for f in FILES:
        shutil.copy2(REPO / f, r / f)
    (r / "artifacts/locks").mkdir(parents=True)
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "fake")
    return r


def _run(root, *args, check=True):
    r = subprocess.run([sys.executable, "-I", str(root / HERE / "run_s6p1.py"), *args], cwd=root,
                       capture_output=True, text=True, timeout=1800)
    if check and r.returncode != 0:
        raise AssertionError(r.stdout[-3000:] + r.stderr[-3000:])
    return r


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    root = _make_root(tmp_path_factory.mktemp("s6p1"))
    assert (root / "src/ainerzero/v9/experiments/s6/cells.py").is_file()
    first = _run(root, "train", "--set", "smoke")
    again = _run(root, "train", "--set", "smoke")
    report = root / "smoke-report.json"
    ev = _run(root, "eval", "--set", "smoke", "--report", str(report))
    return root, first, again, ev, json.loads(report.read_text())


def test_smoke_trains_every_cell_and_resumes(smoke):
    root, first, again, _, _ = smoke
    set_root = root / "artifacts/v9/s6/phase1/smoke"
    cells = sorted(p.name for p in (set_root / "cells").iterdir())
    assert cells == sorted([f"{a}-r{k}" for a in "REZTP" for k in (0, 1)] + ["G-r0"])
    assert all((set_root / "cells" / c / "cell.json").is_file() for c in cells)
    assert "training complete" in first.stdout and "cell " in first.stdout
    assert "cell " not in again.stdout and "training complete" in again.stdout    # nothing retrained
    rows = json.loads((set_root / "train-ledger.json").read_text())
    assert len(rows) == 2 and all(r["closed"] for r in rows) and len(rows[0]["cells"]) == 11 and rows[1]["cells"] == []
    assert set(json.loads((set_root / "pools.json").read_text())) == {"0", "1"}


def test_smoke_eval_verifies_then_scores(smoke):
    root, _, _, ev, R = smoke
    assert R["verify"]["passed"], R["verify"]
    assert set(R["verify"]["retrain"]) == {"E-r0-n0", "P-r0-n0"}
    assert all(v["passed"] for v in R["verify"]["replay"].values()) and len(R["verify"]["replay"]) == 11
    assert set(R["result"]["gates"]) == {"GS", "GT", "GZ-D", "GZ-W", "GK-A", "GK-F", "GP", "GX"}
    assert R["result"]["replicates"] == 2 and R["result"]["m"] == 8
    assert set(R["descriptive"]) == {"round0", "round1"}
    out = root / "artifacts/v9/s6/phase1/smoke/eval-s6t-smoke-test"
    assert {"errors.npz", "worlds.json", "verify.json"} <= {p.name for p in out.iterdir()}
    assert json.loads((out / "worlds.json").read_text()) == {"main6": [[0, 6], [1, 6], [2, 6]], "extrap10": [[1000, 10], [1001, 10]]}


def test_eval_refuses_a_second_run_and_an_approval(smoke):
    root = smoke[0]
    r = _run(root, "eval", "--set", "smoke", "--report", str(root / "again.json"), check=False)
    assert r.returncode != 0 and "already exists" in r.stderr
    r = _run(root, "eval", "--set", "smoke", "--report", str(root / "x.json"), "--approval", "yes", check=False)
    assert r.returncode != 0 and "only final" in r.stderr


def test_final_refuses_without_preregistration(smoke):
    root = smoke[0]
    for args in (("train", "--set", "final"), ("eval", "--set", "final", "--report", str(root / "f.json"))):
        r = _run(root, *args, check=False)
        assert r.returncode != 0
    assert not (root / "artifacts/v9/s6/phase1/final").exists()


def test_a_tampered_cell_stops_evaluation_before_any_test_world(tmp_path_factory, smoke):
    root = smoke[0]
    clone = tmp_path_factory.mktemp("tamper") / "fake"
    shutil.copytree(root, clone, ignore=shutil.ignore_patterns("eval-*"))
    rec_path = clone / "artifacts/v9/s6/phase1/smoke/cells/E-r1/cell.json"
    rec = json.loads(rec_path.read_text())
    rec["tracks"][0]["picks"][1] = rec["tracks"][0]["picks"][1][::-1]
    rec["tracks"][0]["reveal_log"][1]["ids"] = rec["tracks"][0]["picks"][1]
    rec["tracks"][0]["revealed"] = [i for p in rec["tracks"][0]["picks"] for i in p]
    rec_path.write_text(json.dumps(rec, sort_keys=True))
    report = clone / "t.json"
    r = _run(clone, "eval", "--set", "smoke", "--report", str(report), check=False)
    R = json.loads(report.read_text())
    assert not R["verify"]["passed"] and not R["verify"]["replay"]["E-r1"]["passed"]
    assert R["result"]["valid"] is False
    assert not (clone / "artifacts/v9/s6/phase1/smoke/eval-s6t-smoke-test/errors.npz").exists()
