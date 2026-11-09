"""Start-up order of the real S3 phase 2 runner, exercised in a throwaway copy of the repository.

Every case must refuse before a dev use or the final read is spent. The runner derives its
root from its own path, so nothing here can touch the live artifacts or the live lock.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mlx.core")

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
RUNNER = "reports/V9-S3-PHASE2/run_phase2.py"
APPROVAL = "TEST-APPROVAL-LINE"


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "fake"
    (r / "src").mkdir(parents=True)
    shutil.copytree(REPO / "src/ainerzero", r / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (r / "reports/V9-S3-PHASE2").mkdir(parents=True)
    shutil.copy2(REPO / RUNNER, r / RUNNER)
    design = r / "reports/DESIGN.md"
    design.write_text("design", encoding="utf-8")
    (r / "artifacts/locks").mkdir(parents=True)
    manifest = GD.build_manifest(r, [r / RUNNER], src_root=r / "src", extra=[design])
    prereg = {
        "manifest": manifest,
        "third_party": GD.third_party_versions(REPO, ("numpy", "mlx.core")),
        "dev_max_uses": 2,
        "final_approval_line": APPROVAL,
        "h3_capacity": 64,
    }
    (r / "reports/V9-S3-PHASE2/PREREG-r1.json").write_text(json.dumps(prereg), encoding="utf-8")
    (r / ".gitignore").write_text("artifacts/\n__pycache__/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "frozen")
    return r


def _run(root, *args, pycache=True):
    cmd = [sys.executable, "-I"]
    if pycache:
        cmd += ["-X", f"pycache_prefix={root.parent / 'pyc'}"]
    cmd += [str(root / RUNNER), "--report", str(root / "reports/out.json"), *args]
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=120)


def _spent(root):
    a = root / "artifacts/v9/s3/phase2"
    return (a / "dev_uses.json").exists() or (a / "FINAL_READ_ONCE.json").exists()


DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x")
FINAL = ("--stage", "final", "--approval", APPROVAL)


def _refused(r, needle):
    assert r.returncode != 0, r.stdout + r.stderr
    assert needle in r.stderr, r.stderr[-1500:]


@pytest.mark.parametrize("args", [DEV, FINAL])
def test_busy_lock_spends_nothing(root, args) -> None:
    fh = (root / "artifacts/locks/m0-worker.lock").open("a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        _refused(_run(root, *args), "lock is busy")
    finally:
        fh.close()
    assert not _spent(root) and not (root / "reports/out.json").exists()


@pytest.mark.parametrize("args", [DEV, FINAL])
def test_changed_transitive_dependency_spends_nothing(root, args) -> None:
    """The S2 world was outside the phase 1 manifest."""
    f = root / "src/ainerzero/v9/experiments/s2/world.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "edit")
    _refused(_run(root, *args), "frozen manifest does not hold")
    assert not _spent(root) and not (root / "reports/out.json").exists()


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


def test_existing_report_is_kept_and_spends_nothing(root) -> None:
    (root / "reports/out.json").write_text("earlier evidence", encoding="utf-8")
    _refused(_run(root, *DEV), "report already exists")
    assert not _spent(root)
    assert (root / "reports/out.json").read_text(encoding="utf-8") == "earlier evidence"


def test_dev_without_a_purpose_records_nothing(root) -> None:
    _refused(_run(root, "--stage", "dev", "--use-id", "dev1"), "purpose")
    assert not _spent(root)


def test_wrong_approval_writes_no_marker(root) -> None:
    _refused(_run(root, "--stage", "final", "--approval", "NOPE"), "approval")
    assert not _spent(root)
