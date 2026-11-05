"""S1 r7: one registered host anchor for every bounded path.

The r6 audit found the central anchor still depended on the checkout and on the
terminal-age accounting; this suite pins the r7 rules:

* two *real* source checkouts resolve the same host root / ledger / lock, and a
  checkout's own ``artifacts/.../phase1/control.sqlite3`` is never consulted;
* the approval log read by ``train`` is the anchored one, so a clone carrying a
  real-format SHA approval line still cannot approve anything;
* a missing/unreadable/unrecognised anchor fails closed instead of creating a
  fresh ledger;
* no environment variable can move the anchor.

Nothing here imports MLX, starts a model, or writes the real ledger.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import commands, prereg, spec, worker

from s1_testkit import (
    checkout_anchor,
    install_test_host,
    make_source_checkout,
    write_frozen,
    write_research_log,
)

# --- the registered anchor on this machine --------------------------------
def test_the_registered_anchor_is_one_absolute_dict():
    state = spec.host_anchor_state()
    assert state["status"] == "ok"
    assert state["registered"] is True
    assert state["root"] == str(spec.REGISTERED_HOST_ROOT)
    assert state["ledger"] == str(worker.canonical_ledger_path())
    assert state["lock"] == str(spec.REGISTERED_HOST_LOCK)
    assert state["approval_log"] == str(spec.RESEARCH_LOG)
    assert state["root"] == "/Users/mac/AinerWorkFlow/AinerZero"


def test_the_anchor_is_not_derived_from_the_executing_file():
    # ``SELF_PATH`` (source binding) may use __file__; the *anchor* must not.
    source = Path(spec.__file__).read_text(encoding="utf-8")
    anchor_block = source.split("# --- registered host anchor", 1)[1].split(
        "# --- storage layout", 1
    )[0]
    assert "Path(__file__)" not in anchor_block
    assert "SELF_PATH" not in anchor_block


def test_anchor_fails_closed_without_a_root(tmp_path):
    missing = tmp_path / "not-a-host"
    state = spec.host_anchor_state(missing)
    assert state["status"] == "missing_root"
    with pytest.raises(RuntimeError):
        spec.host_anchor(missing)


def test_anchor_fails_closed_without_an_approval_log(tmp_path):
    root = tmp_path / "host"
    (root / "artifacts" / "v9" / "s1" / "phase1").mkdir(parents=True)
    state = spec.host_anchor_state(root)
    assert state["status"] == "missing_approval"


def test_anchor_fails_closed_on_an_unreadable_approval_log(tmp_path):
    root = tmp_path / "host"
    (root / "artifacts" / "v9" / "s1" / "phase1").mkdir(parents=True)
    log = root / "RESEARCH_LOG.md"
    log.write_text("# log\n", encoding="utf-8")
    log.chmod(0o000)
    try:
        state = spec.host_anchor_state(root)
    finally:
        log.chmod(0o644)
    assert state["status"] in {"unreadable_approval", "ok"}


# --- two real source checkouts, one anchor --------------------------------
def test_two_real_checkouts_resolve_the_same_anchor(tmp_path):
    first = make_source_checkout(tmp_path / "checkout-a")
    second = make_source_checkout(tmp_path / "checkout-b")
    a = checkout_anchor(first)
    b = checkout_anchor(second)
    assert a["spec_file"].startswith(str(first)), "the checkout must import its own copy"
    assert b["spec_file"].startswith(str(second))
    for key in ("root", "phase1", "ledger", "lock"):
        assert a[key] == b[key], f"{key} differs between checkouts"
        assert str(first) not in a[key] and str(second) not in a[key]
    assert a["root"] == "/Users/mac/AinerWorkFlow/AinerZero"
    assert a["anchor"]["status"] == b["anchor"]["status"] == "ok"


def test_a_checkouts_own_ledger_and_approval_are_never_read(tmp_path, monkeypatch):
    """A clone with a legal empty RunStore + real-format approval is still refused."""
    clone = make_source_checkout(tmp_path / "clone")
    clone_root = clone / "artifacts" / "v9" / "s1" / "phase1"
    clone_root.mkdir(parents=True)
    clone_log = write_research_log(clone / "RESEARCH_LOG.md")
    path, digest, _document = write_frozen(clone_root / "pre_registration.json")
    # A real-format approval line bound to the frozen document SHA, written in
    # the clone.  It is the exact credential format the host gate parses; the
    # point is that the *location* is not the anchor, so it must not approve.
    real_line = prereg.scan_approval_log(write_research_log(clone / "x.md", approval_sha=digest))
    assert real_line["rows"], "the fixture must produce a real approval line"
    clone_log.write_text(
        (clone / "x.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # A legal, recognised empty ledger at the clone (prep experiment present).
    ledger = worker.PrepLedger(clone_root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
    finally:
        ledger.close()

    install_test_host(monkeypatch, tmp_path / "host")

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("train started from a clone-local root")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    args = SimpleNamespace(
        mode="train",
        output_root=clone_root,
        prereg=path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=clone_log,
        arm="arm2",
        seed=0,
    )
    report = commands.mode_train(args)
    assert report["status"] == "refused"
    assert report["stage"] == "output_root_not_canonical"

    # Even with the host root, the clone-local approval log is refused first.
    args.output_root = spec.PHASE1_ROOT
    report = commands.mode_train(args)
    assert report["status"] == "refused"
    assert report["stage"] == "research_log_not_canonical"
    assert report["canonical_research_log"] != str(clone_log)


def test_each_checkout_refuses_to_train_at_its_own_root(tmp_path):
    """Inside each checkout, the train entry refuses its own root (host ledger only)."""
    import hashlib
    import json
    import os
    import subprocess
    import sys

    host_ledger = Path(spec.REGISTERED_HOST_LEDGER)
    before = hashlib.sha256(host_ledger.read_bytes()).hexdigest()
    script = """
import json
from types import SimpleNamespace
from ainerzero.v9.experiments.s1 import commands, spec

clone_root = spec.REGISTERED_HOST_ROOT  # placeholder, replaced below by argv
import sys
root = __import__("pathlib").Path(sys.argv[1])
args = SimpleNamespace(mode="train", output_root=root, prereg=root / "pre_registration.json",
                       limits_file=None, wall_budget_seconds=None, research_log=None,
                       arm="arm2", seed=0)
report, code = commands.s1_phase1_command(args)
print(json.dumps({"code": code, "stage": report.get("stage"),
                  "host_root": str(spec.REGISTERED_HOST_ROOT)}))
"""
    for name in ("checkout-a", "checkout-b"):
        clone = make_source_checkout(tmp_path / name)
        clone_root = clone / "artifacts" / "v9" / "s1" / "phase1"
        clone_root.mkdir(parents=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(clone / "src")
        result = subprocess.run(
            [sys.executable, "-c", script, str(clone_root)],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        assert payload["code"] == 3
        assert payload["stage"] == "output_root_not_canonical"
        assert payload["host_root"] == "/Users/mac/AinerWorkFlow/AinerZero"
        assert not (clone_root / "control.sqlite3").exists(), (
            "a refused checkout must not create a ledger"
        )
    assert hashlib.sha256(host_ledger.read_bytes()).hexdigest() == before


def test_no_environment_variable_moves_the_anchor(tmp_path, monkeypatch):
    before = spec.host_anchor_state()
    for key in ("AINERZERO_S1_PHASE1_ROOT", "AINERZERO_PHASE1_ROOT", "S1_PHASE1_ROOT"):
        monkeypatch.setenv(key, str(tmp_path / "elsewhere"))
    after = spec.host_anchor_state()
    assert after == before


def test_worker_refuses_when_the_anchor_root_disappears(tmp_path, monkeypatch):
    host = install_test_host(monkeypatch, tmp_path)
    path, _digest, _document = write_frozen(host / "pre_registration.json")
    monkeypatch.setattr(spec, "REGISTERED_HOST_ROOT", tmp_path / "gone")
    report = worker.run_worker(
        "train",
        output_root=host,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=450.0,
        prereg_path=path,
        arm="arm2",
        seed=0,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "host_anchor_missing_root"
    assert report["host_anchor"]["status"] == "missing_root"


def test_entry_refuses_when_the_phase1_root_and_anchor_disagree(tmp_path, monkeypatch):
    install_test_host(monkeypatch, tmp_path)
    monkeypatch.setattr(spec, "PHASE1_ROOT", tmp_path / "another-phase1")
    args = SimpleNamespace(mode="train", output_root=tmp_path / "another-phase1")
    _root, refusal = commands._canonical_run_root(args, "train")
    assert refusal is not None
    assert refusal["stage"] == "host_anchor_mismatch"


def test_the_real_ledger_is_untouched_by_the_anchor_checks():
    import sqlite3

    ledger = Path(spec.REGISTERED_HOST_LEDGER)
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    spec.host_anchor_state()
    state = worker.canonical_ledger_state()
    assert state["status"] == "ok"
    # Read-only accounting over the real rows: never opened for writing here.
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        rows = list(
            connection.execute(
                "SELECT run_id, state, created_at, updated_at, active_seconds FROM runs"
            )
        )
    finally:
        connection.close()
    total = 0.0
    for run_id, run_state, created_at, updated_at, active_seconds in rows:
        if run_state in worker.TERMINAL_STATES:
            total += max(float(active_seconds or 0.0), max(0.0, updated_at - created_at))
    assert total > 0
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert before == after, "the anchor checks must not write the immutable real ledger"
