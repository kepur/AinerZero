"""S4 phase 1 label verifier: an independent recomputation that passes on honest records and
catches each kind of tampering. CPU only; the verifier runs as python -I in a subprocess."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "reports/V9-S4-PHASE1/verify_labels.py"
NS = "test-s4-verify"


@pytest.fixture(scope="module")
def data():
    eps = [("main", W.generate_episode(NS, 0, 6)), ("main", W.generate_episode(NS, 1, 6)), ("extrap", W.generate_episode(NS, 1000, 10, steps=120))]
    cells = [A.Cell("E-B", s) for s in A.SEEDS]
    recs = [A.world_record(ep, kind, NS, cells, {"E-B": Mo.bounce, "E-P": Mo.true_physics}) for kind, ep in eps]
    return [A.label_log(kind, ep) for kind, ep in eps], recs


def _run(tmp_path, labels, recs):
    lp, rp = tmp_path / "labels.jsonl", tmp_path / "worlds.jsonl"
    lp.write_text("".join(json.dumps(x) + "\n" for x in labels))
    rp.write_text("".join(json.dumps(x) + "\n" for x in recs))
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(lp), str(rp)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_honest_records_pass(tmp_path, data) -> None:
    out = _run(tmp_path, *data)
    assert out["passed"], out
    assert out["events"] == sum(len(r["events"]) for r in data[1]) and out["collision_events"] > 0


def test_verifier_is_independent() -> None:
    src = SCRIPT.read_text()
    assert "ainerzero" not in src.split('"""', 2)[2] and "import numpy" not in src


@pytest.mark.parametrize("tamper", ["flip_collision", "drop_event", "shift_b", "n_coll", "short_reid", "swap_worlds", "contact_moved", "missing_world"])
def test_tampering_is_caught(tmp_path, data, tamper) -> None:
    labels, recs = copy.deepcopy(data)
    r = recs[0]
    if tamper == "flip_collision":
        r["events"][0][3] = 1 - r["events"][0][3]
    elif tamper == "drop_event":
        r["events"].pop()
    elif tamper == "shift_b":
        r["events"][0][2] += 1
    elif tamper == "n_coll":
        r["dyn"]["E-B"]["n_coll"] += 1
    elif tamper == "short_reid":
        key = next(iter(r["reid"]))
        r["reid"][key] = r["reid"][key][:-1]
    elif tamper == "swap_worlds":
        recs[0], recs[1] = recs[1], recs[0]
    elif tamper == "missing_world":
        recs.pop()                                  # zip would silently compare one world fewer
    elif tamper == "contact_moved":
        # a disk contact the record counted is moved to a step after every event window of that disk
        g = labels[0]
        s = next(t for t, c in enumerate(g["disk_contacts"][:-1]) if c)
        g["disk_contacts"][-1] = g["disk_contacts"][-1] + g["disk_contacts"][s]
        g["disk_contacts"][s] = []
    out = _run(tmp_path, labels, recs)
    assert not out["passed"], tamper
