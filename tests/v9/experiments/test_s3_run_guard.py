"""Contracts for the S3 registered-run guards. Pure CPU, no MLX, temporary paths only."""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s3 import run_guard as G

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "worker.lock"


def _busy(path):
    fh = path.open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fh


def _tiny_tree(tmp_path):
    src = tmp_path / "src"
    pkg = src / "ainerzero" / "sub"
    pkg.mkdir(parents=True)
    (src / "ainerzero" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("from ainerzero.sub import b\nimport numpy\n", encoding="utf-8")
    (pkg / "b.py").write_text("from . import c\n", encoding="utf-8")
    (pkg / "c.py").write_text("def later():\n    from ainerzero.sub.d import x\n", encoding="utf-8")
    (pkg / "d.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "unused.py").write_text("x = 2\n", encoding="utf-8")
    return src, pkg


def test_closure_follows_absolute_relative_and_function_level_imports(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    names = {p.relative_to(src.resolve()).as_posix() for p in G.import_closure(src, [pkg / "a.py"])}
    assert names == {
        "ainerzero/__init__.py",
        "ainerzero/sub/__init__.py",
        "ainerzero/sub/a.py",
        "ainerzero/sub/b.py",
        "ainerzero/sub/c.py",
        "ainerzero/sub/d.py",
    }


def test_closure_of_the_real_s3_entries_reaches_the_s2_world() -> None:
    """The defect P208 found: s2/world.py and s2/spec.py were outside the frozen list."""
    s3 = SRC / "ainerzero/v9/experiments/s3"
    names = {p.relative_to(SRC.resolve()).as_posix() for p in G.import_closure(SRC, [s3 / "data.py", s3 / "world.py"])}
    assert "ainerzero/v9/experiments/s2/world.py" in names
    assert "ainerzero/v9/experiments/s2/spec.py" in names


def test_manifest_detects_change_in_a_transitive_dependency(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    manifest = G.build_manifest(tmp_path, [pkg / "a.py"], src_root=src)
    assert G.check_manifest(tmp_path, manifest) == []
    (pkg / "d.py").write_text("x = 3\n", encoding="utf-8")
    assert G.check_manifest(tmp_path, manifest) == ["changed: src/ainerzero/sub/d.py"]


def test_manifest_detects_a_missing_file_and_refuses_an_empty_one(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    manifest = G.build_manifest(tmp_path, [pkg / "a.py"], src_root=src)
    (pkg / "d.py").unlink()
    assert G.check_manifest(tmp_path, manifest) == ["missing: src/ainerzero/sub/d.py"]
    assert G.check_manifest(tmp_path, {}) != []


def test_loaded_module_outside_the_manifest_is_reported(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    manifest = G.build_manifest(tmp_path, [pkg / "d.py"], src_root=src)

    class Mod:
        __file__ = str(pkg / "unused.py")

    class Ok:
        __file__ = str(pkg / "d.py")

    class Other:
        __file__ = "/elsewhere/numpy.py"

    bad = G.check_loaded_modules(tmp_path, manifest, modules={"ainerzero.sub.unused": Mod, "ainerzero.sub.d": Ok, "numpy": Other, "ainerzero.ns": None})
    assert len(bad) == 1 and "ainerzero.sub.unused" in bad[0]


def test_busy_lock_is_refused_and_leaves_the_ledger_untouched(tmp_path, lock_path) -> None:
    ledger, marker = tmp_path / "uses.json", tmp_path / "FINAL.json"
    holder = _busy(lock_path)
    try:
        with pytest.raises(G.GuardError, match="busy"):
            with G.RunLock(lock_path) as lock:
                G.consume_dev_use(lock, ledger, "dev1", "first look")
                G.consume_final_read(lock, marker, "yes", "yes", prereg_sha256="s")
    finally:
        holder.close()
    assert not ledger.exists() and not marker.exists()


@pytest.mark.parametrize("call", ["dev", "final"])
def test_consuming_without_the_lock_is_refused(tmp_path, lock_path, call) -> None:
    ledger, marker = tmp_path / "uses.json", tmp_path / "FINAL.json"
    lock = G.RunLock(lock_path)
    with pytest.raises(G.GuardError, match="held"):
        if call == "dev":
            G.consume_dev_use(lock, ledger, "dev1", "first look")
        else:
            G.consume_final_read(lock, marker, "yes", "yes", prereg_sha256="s")
    assert not ledger.exists() and not marker.exists()


def test_dev_ledger_enforces_ids_purpose_and_the_limit(tmp_path, lock_path) -> None:
    ledger = tmp_path / "uses.json"
    with G.RunLock(lock_path) as lock:
        for use_id, purpose in ((None, "x"), ("dev1", None), ("dev1", "   ")):
            with pytest.raises(G.GuardError, match="purpose"):
                G.consume_dev_use(lock, ledger, use_id, purpose)
        assert not ledger.exists()
        G.consume_dev_use(lock, ledger, "dev1", "first")
        with pytest.raises(G.GuardError, match="already"):
            G.consume_dev_use(lock, ledger, "dev1", "again")
        G.consume_dev_use(lock, ledger, "dev2", "second")
        with pytest.raises(G.GuardError, match="exhausted"):
            G.consume_dev_use(lock, ledger, "dev3", "third")
    uses = json.loads(ledger.read_text(encoding="utf-8"))
    assert [u["id"] for u in uses] == ["dev1", "dev2"]
    assert [u["purpose"] for u in uses] == ["first", "second"]


def test_malformed_ledger_is_refused(tmp_path, lock_path) -> None:
    ledger = tmp_path / "uses.json"
    ledger.write_text('{"id": "dev1"}', encoding="utf-8")
    with G.RunLock(lock_path) as lock:
        with pytest.raises(G.GuardError, match="malformed"):
            G.consume_dev_use(lock, ledger, "dev2", "x")


def test_final_marker_needs_the_exact_line_and_is_single_use(tmp_path, lock_path) -> None:
    marker = tmp_path / "FINAL.json"
    with G.RunLock(lock_path) as lock:
        for wrong in (None, "", "NOPE"):
            with pytest.raises(G.GuardError, match="approval"):
                G.consume_final_read(lock, marker, wrong, "LINE", prereg_sha256="s")
        assert not marker.exists()
        with pytest.raises(G.GuardError, match="no final approval"):
            G.consume_final_read(lock, marker, "", "", prereg_sha256="s")
        G.consume_final_read(lock, marker, " LINE\n", "LINE", prereg_sha256="abc")
        assert json.loads(marker.read_text(encoding="utf-8"))["prereg_sha256"] == "abc"
        with pytest.raises(G.GuardError, match="already"):
            G.consume_final_read(lock, marker, "LINE", "LINE", prereg_sha256="abc")


@pytest.mark.parametrize(
    "stage,ns,ok",
    [
        ("smoke", "p", True),
        ("smoke", "d", False),
        ("smoke", "f", False),
        ("dev", "d", True),
        ("dev", "p", False),
        ("final", "f", True),
        ("final", "d", False),
    ],
)
def test_each_stage_reads_only_its_partition(stage, ns, ok) -> None:
    if ok:
        G.check_stage_namespace(stage, ns, probe="p", dev="d", final="f")
    else:
        with pytest.raises(G.GuardError, match="must read"):
            G.check_stage_namespace(stage, ns, probe="p", dev="d", final="f")


def test_unknown_stage_is_refused() -> None:
    with pytest.raises(G.GuardError, match="unknown"):
        G.check_stage_namespace("oops", "p", probe="p", dev="d", final="f")


def test_a_report_is_never_overwritten(tmp_path) -> None:
    p = tmp_path / "sub" / "report.json"
    G.claim_report(p)
    p.write_text("evidence", encoding="utf-8")
    with pytest.raises(G.GuardError, match="exists"):
        G.claim_report(p)
    assert p.read_text(encoding="utf-8") == "evidence"


def test_deadline_trips_only_after_the_limit() -> None:
    now = [0.0]
    d = G.Deadline(10.0, clock=lambda: now[0])
    d.check()
    now[0] = 9.9
    d.check()
    now[0] = 10.0
    with pytest.raises(G.GuardError, match="limit"):
        d.check()


def test_guard_module_imports_no_mlx_or_numpy() -> None:
    code = (
        "import sys; from ainerzero.v9.experiments.s3 import run_guard; "
        "bad=[m for m in ('mlx','mlx.core','numpy') if m in sys.modules]; "
        "print(bad); sys.exit(1 if 'mlx' in bad or 'mlx.core' in bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
