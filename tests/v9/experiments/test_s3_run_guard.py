"""Contracts for the S3 registered-run guards. Pure CPU, no MLX, temporary paths only."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s3 import run_guard as G

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "worker.lock"


def _hold(path, mode=fcntl.LOCK_EX):
    fh = path.open("a+")
    fcntl.flock(fh, mode | fcntl.LOCK_NB)
    return fh


def _dev(lock, ledger, use_id, purpose, *, max_uses=2):
    return G.consume_dev_use(lock, ledger, use_id, purpose, max_uses=max_uses, expected_lock=lock.path)


def _final(lock, marker, approval, expected):
    G.consume_final_read(lock, marker, approval, expected, prereg_sha256="s", expected_lock=lock.path)


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


def test_closure_includes_a_module_beside_the_entry_script(tmp_path) -> None:
    src, _ = _tiny_tree(tmp_path)
    scripts = tmp_path / "reports"
    scripts.mkdir()
    (scripts / "runner.py").write_text("import helper\nimport ainerzero.sub.d\n", encoding="utf-8")
    (scripts / "helper.py").write_text("x = 1\n", encoding="utf-8")
    names = {p.name for p in G.import_closure(src, [scripts / "runner.py"])}
    assert {"runner.py", "helper.py", "d.py"} <= names


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


def test_manifest_freezes_extra_files(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    design = tmp_path / "DESIGN.md"
    design.write_text("v1", encoding="utf-8")
    manifest = G.build_manifest(tmp_path, [pkg / "d.py"], src_root=src, extra=[design])
    assert "DESIGN.md" in manifest
    design.write_text("v2", encoding="utf-8")
    assert G.check_manifest(tmp_path, manifest) == ["changed: DESIGN.md"]


def _mod(path):
    return type("Mod", (), {"__file__": str(path)})


def test_any_loaded_repository_module_must_be_frozen(tmp_path) -> None:
    src, pkg = _tiny_tree(tmp_path)
    manifest = G.build_manifest(tmp_path, [pkg / "d.py"], src_root=src)
    shadow = tmp_path / "reports" / "numpy.py"
    bad = G.check_loaded_modules(
        tmp_path,
        manifest,
        modules={
            "ainerzero.sub.unused": _mod(pkg / "unused.py"),
            "ainerzero.sub.d": _mod(pkg / "d.py"),
            "numpy": _mod(shadow),
            "__main__": _mod(tmp_path / "reports" / "runner.py"),
            "os": _mod("/elsewhere/os.py"),
            "ainerzero.ns": None,
        },
        ignore_roots=[],
    )
    assert len(bad) == 3
    assert any("ainerzero.sub.unused" in b for b in bad)
    assert any(b.startswith("not frozen: numpy") for b in bad)
    assert any(b.startswith("not frozen: __main__") for b in bad)


def test_interpreter_prefix_inside_the_repository_is_ignored(tmp_path) -> None:
    venv = tmp_path / ".venv" / "lib" / "numpy.py"
    assert G.check_loaded_modules(tmp_path, {"x": "y"}, modules={"numpy": _mod(venv)}, ignore_roots=[tmp_path / ".venv"]) == []


def test_third_party_shadowed_from_the_repository_is_refused(tmp_path, monkeypatch) -> None:
    (tmp_path / "shadowlib.py").write_text("__version__ = 'shadow'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(G.GuardError, match="shadowed"):
        G.third_party_versions(tmp_path, ["shadowlib"])
    sys.modules.pop("shadowlib", None)


def test_third_party_versions_are_reported() -> None:
    assert G.third_party_versions(REPO, ["json"]) == {"json": str(json.__version__) if hasattr(json, "__version__") else "unknown"}


def test_pycache_prefix_is_required(monkeypatch) -> None:
    monkeypatch.setattr(sys, "pycache_prefix", None)
    with pytest.raises(G.GuardError, match="pycache_prefix"):
        G.require_fresh_pycache(time.time())


def test_fresh_pycache_passes_and_old_bytecode_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path))
    f = tmp_path / "a" / "m.cpython-312.pyc"
    f.parent.mkdir()
    f.write_bytes(b"0")
    now = time.time()
    G.require_fresh_pycache(now)
    os.utime(f, (now - 11, now - 11))
    with pytest.raises(G.GuardError, match="stale"):
        G.require_fresh_pycache(now)
    os.utime(f, (now - 9, now - 9))
    G.require_fresh_pycache(now)


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True)


def test_git_clean_reports_dirty_and_untracked_frozen_files(tmp_path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "c")
    head, dirty = G.check_git_clean(tmp_path, ["a.txt"])
    assert len(head) == 40 and dirty == []
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    (tmp_path / "b.txt").write_text("3", encoding="utf-8")
    _, dirty = G.check_git_clean(tmp_path, ["a.txt", "b.txt"])
    assert len(dirty) == 2


def test_git_clean_refuses_outside_a_checkout(tmp_path) -> None:
    with pytest.raises(G.GuardError, match="git"):
        G.check_git_clean(tmp_path, ["a.txt"])


@pytest.mark.parametrize("mode", [fcntl.LOCK_EX, fcntl.LOCK_SH])
def test_busy_lock_is_refused_and_leaves_the_ledger_untouched(tmp_path, lock_path, mode) -> None:
    ledger, marker = tmp_path / "uses.json", tmp_path / "FINAL.json"
    holder = _hold(lock_path, mode)
    try:
        with pytest.raises(G.GuardError, match="busy"):
            with G.RunLock(lock_path) as lock:
                _dev(lock, ledger, "dev1", "first look")
                _final(lock, marker, "yes", "yes")
    finally:
        holder.close()
    assert not ledger.exists() and not marker.exists()


def test_replaced_lock_file_is_refused(lock_path, monkeypatch) -> None:
    real = G.os.fstat

    class Stat:
        st_ino = -1

    monkeypatch.setattr(G.os, "fstat", lambda fd: Stat if fd > 2 else real(fd))
    with pytest.raises(G.GuardError, match="replaced"):
        with G.RunLock(lock_path):
            pass


@pytest.mark.parametrize("call", ["dev", "final"])
def test_consuming_without_the_lock_is_refused(tmp_path, lock_path, call) -> None:
    ledger, marker = tmp_path / "uses.json", tmp_path / "FINAL.json"
    lock = G.RunLock(lock_path)
    with pytest.raises(G.GuardError, match="held"):
        if call == "dev":
            _dev(lock, ledger, "dev1", "first look")
        else:
            _final(lock, marker, "yes", "yes")
    assert not ledger.exists() and not marker.exists()


@pytest.mark.parametrize("call", ["dev", "final"])
def test_holding_some_other_lock_is_refused(tmp_path, lock_path, call) -> None:
    """Review r0 G1: a different lock file gave no mutual exclusion and counts were lost."""
    ledger, marker = tmp_path / "uses.json", tmp_path / "FINAL.json"
    with G.RunLock(tmp_path / "other.lock") as lock:
        with pytest.raises(G.GuardError, match="registered lock"):
            if call == "dev":
                G.consume_dev_use(lock, ledger, "dev1", "x", max_uses=2, expected_lock=lock_path)
            else:
                G.consume_final_read(lock, marker, "y", "y", prereg_sha256="s", expected_lock=lock_path)
    assert not ledger.exists() and not marker.exists()


def test_concurrent_consumers_cannot_exceed_the_limit(tmp_path) -> None:
    """Six processes on six lock files sharing one ledger: the per-ledger mutex must hold."""
    ledger = tmp_path / "uses.json"
    code = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from ainerzero.v9.experiments.s3 import run_guard as G
        lock_path, ledger, use_id = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        with G.RunLock(lock_path) as lock:
            try:
                G.consume_dev_use(lock, ledger, use_id, "race", max_uses=2, expected_lock=lock_path)
            except G.GuardError:
                sys.exit(3)
        """
    )
    env = {"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}
    procs = [
        subprocess.Popen([sys.executable, "-c", code, str(tmp_path / f"{i}.lock"), str(ledger), f"dev{i}"], env=env)
        for i in range(6)
    ]
    codes = [p.wait(timeout=60) for p in procs]
    assert sorted(codes) == [0, 0, 3, 3, 3, 3]
    assert len(json.loads(ledger.read_text(encoding="utf-8"))) == 2


def test_a_writer_waits_for_the_ledger_mutex(tmp_path, lock_path) -> None:
    """Deterministic form of the race above: flock is per open file, so a thread blocks too."""
    ledger = tmp_path / "uses.json"
    holder = _hold(tmp_path / "uses.json.lock")
    errors = []

    def consume():
        try:
            with G.RunLock(lock_path) as lock:
                _dev(lock, ledger, "dev1", "waits")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        worker.join(timeout=1.0)
        assert worker.is_alive() and not ledger.exists()
    finally:
        holder.close()
    worker.join(timeout=20)
    assert not worker.is_alive() and not errors
    assert len(json.loads(ledger.read_text(encoding="utf-8"))) == 1


def test_dev_ledger_enforces_ids_purpose_and_the_limit(tmp_path, lock_path) -> None:
    ledger = tmp_path / "uses.json"
    with G.RunLock(lock_path) as lock:
        for use_id, purpose in ((None, "x"), ("", "x"), (" dev1", "x"), ("dev1 ", "x"), ("a/b", "x"), ("../up", "x"), ("dev.1", "x"), ("dev1", None), ("dev1", "   ")):
            with pytest.raises(G.GuardError, match="purpose"):
                _dev(lock, ledger, use_id, purpose)
        assert not ledger.exists()
        _dev(lock, ledger, "dev1", "first")
        with pytest.raises(G.GuardError, match="already"):
            _dev(lock, ledger, "dev1", "again")
        _dev(lock, ledger, "dev2", "second")
        with pytest.raises(G.GuardError, match="exhausted"):
            _dev(lock, ledger, "dev3", "third")
    uses = json.loads(ledger.read_text(encoding="utf-8"))
    assert [u["id"] for u in uses] == ["dev1", "dev2"]
    assert [u["purpose"] for u in uses] == ["first", "second"]


def test_max_uses_has_no_default() -> None:
    with pytest.raises(TypeError):
        G.consume_dev_use(None, Path("x"), "a", "b", expected_lock="l")


@pytest.mark.parametrize("text", ['{"id": "dev1"}', "not json"])
def test_malformed_ledger_is_refused(tmp_path, lock_path, text) -> None:
    ledger = tmp_path / "uses.json"
    ledger.write_text(text, encoding="utf-8")
    with G.RunLock(lock_path) as lock:
        with pytest.raises(G.GuardError, match="malformed"):
            _dev(lock, ledger, "dev2", "x")


def test_ledger_write_is_atomic(tmp_path, lock_path, monkeypatch) -> None:
    ledger = tmp_path / "uses.json"
    with G.RunLock(lock_path) as lock:
        _dev(lock, ledger, "dev1", "first")
        before = ledger.read_text(encoding="utf-8")

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(G.os, "replace", boom)
        with pytest.raises(OSError):
            _dev(lock, ledger, "dev2", "second")
    assert ledger.read_text(encoding="utf-8") == before


def test_final_marker_needs_the_exact_line_and_is_single_use(tmp_path, lock_path) -> None:
    marker = tmp_path / "FINAL.json"
    with G.RunLock(lock_path) as lock:
        for wrong in (None, "", "NOPE"):
            with pytest.raises(G.GuardError, match="approval"):
                _final(lock, marker, wrong, "LINE")
        assert not marker.exists()
        with pytest.raises(G.GuardError, match="no final approval"):
            _final(lock, marker, "", "")
        G.consume_final_read(lock, marker, " LINE\n", "LINE", prereg_sha256="abc", expected_lock=lock_path)
        assert json.loads(marker.read_text(encoding="utf-8"))["prereg_sha256"] == "abc"
        with pytest.raises(G.GuardError, match="already"):
            _final(lock, marker, "LINE", "LINE")


def test_final_marker_is_created_exclusively(tmp_path, lock_path, monkeypatch) -> None:
    """A racer that passed the exists() check must still lose: the open itself is exclusive."""
    marker = tmp_path / "FINAL.json"
    marker.write_text("first", encoding="utf-8")
    monkeypatch.setattr(G.Path, "exists", lambda self: False)
    with G.RunLock(lock_path) as lock:
        with pytest.raises(G.GuardError, match="already"):
            _final(lock, marker, "LINE", "LINE")
    assert marker.read_text(encoding="utf-8") == "first"


NS = {"train": "t", "probe": "p", "dev": "d", "final": "f"}


@pytest.mark.parametrize(
    "stage,ns,ok",
    [
        ("smoke", "p", True),
        ("probe", "p", True),
        ("smoke", "d", False),
        ("smoke", "f", False),
        ("probe", "d", False),
        ("dev", "d", True),
        ("dev", "p", False),
        ("final", "f", True),
        ("final", "d", False),
        ("final", "t", False),
    ],
)
def test_each_stage_reads_only_its_partition(stage, ns, ok) -> None:
    if ok:
        G.check_stage_namespace(stage, ns, **NS)
    else:
        with pytest.raises(G.GuardError, match="must read"):
            G.check_stage_namespace(stage, ns, **NS)


def test_unknown_stage_is_refused() -> None:
    with pytest.raises(G.GuardError, match="unknown"):
        G.check_stage_namespace("oops", "p", **NS)


@pytest.mark.parametrize("key", ["train", "dev", "final"])
def test_partitions_must_be_distinct(key) -> None:
    with pytest.raises(G.GuardError, match="distinct"):
        G.check_stage_namespace("smoke", "p", **{**NS, key: "p"})


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


def test_guard_module_imports_no_mlx() -> None:
    code = "import sys; from ainerzero.v9.experiments.s3 import run_guard; sys.exit(1 if 'mlx' in sys.modules or 'mlx.core' in sys.modules else 0)"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_deadline_defaults_to_the_wall_clock() -> None:
    assert G.Deadline.__init__.__kwdefaults__["clock"] is time.time
