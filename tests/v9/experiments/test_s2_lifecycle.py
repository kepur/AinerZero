"""Pure CPU lifecycle tests for S2 Phase 1 commands, worker, and RunStore wiring.

Tests:
- (a) No approval line: train refused with stage="approval" (exit 3); verify succeeds with zero writes.
- (b) Qualified approval line + fake runner: admits train cell; second attempt returns duplicate_execution (exit 1).
- (c) Total phase budget ceiling (registered total): cell pushing total over it refused with
      stage="phase_budget_exceeded" (exit 2); boundary condition exactly equal to 10 h admitted.
      Cross-lineage accumulation verified.
- (d) Calendar window (72 h) vs actual compute separation: 30 h idle gap admitted; > 72 h calendar window refused.
- (e) Approval line in blockquote, fenced code, or indented block refused as unqualified.
- (f) Isolated subprocess `.venv/bin/python -I -m ainerzero s2-phase1 --mode verify` against tmp_path.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any, Callable

import pytest

from ainerzero.v9.experiments.s2 import commands, spec, worker

QUALIFIED_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


REPO_ROOT = Path(__file__).resolve().parents[3]


def _freeze_and_approve(tmp_env: dict[str, Any]) -> str:
    """Freeze a real S2 prereg into tmp output_root and write the matching approval line.

    Run modes require a frozen prereg whose source digests match the repository and an
    approval line naming its document SHA (commands Preflight 0, 11-07).
    """
    from ainerzero.v9.experiments.s2 import freeze as s2_freeze
    from ainerzero.v9.experiments.s2 import prereg as s2_prereg

    assert str(tmp_env["output_root"].resolve()).startswith(str(tmp_env["tmp_path"].resolve()))
    sha = s2_freeze.freeze(s2_prereg.build_draft(repo_root=REPO_ROOT), out_dir=tmp_env["output_root"], repo_root=REPO_ROOT)
    tmp_env["research_log"].write_text(
        f"## R20261106-S2-approval\n\n{s2_freeze.approval_line(sha)}\n", encoding="utf-8"
    )
    return sha


class FakeClock:
    """Deterministic controllable clock for lifecycle testing."""

    def __init__(self, start_ts: float = 1700000000.0) -> None:
        self.current = float(start_ts)

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += float(seconds)


def make_fake_runner(active_seconds: float = 100.0) -> Callable[..., dict[str, Any]]:
    """Create a controllable fake runner that marks runs as completed in the ledger."""

    def _runner(
        ledger: worker.S2Ledger,
        run_id: str,
        mode: str,
        arm: str | None,
        seed: int | None,
        cell_wall_budget: float,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        clock_fn = clock or time.time
        if hasattr(clock, "advance"):
            clock.advance(active_seconds)
        ledger.complete_run(
            run_id,
            active_seconds=active_seconds,
            metrics={"loss": 0.05, "status": "completed"},
        )
        return {
            "status": "completed",
            "run_id": run_id,
            "mode": mode,
            "arm": arm,
            "seed": seed,
            "active_seconds": active_seconds,
        }

    return _runner


@pytest.fixture
def tmp_env(tmp_path: Path):
    """Fixture ensuring all paths are strictly inside tmp_path."""
    output_root = tmp_path / "artifacts/v9/s2/phase1"
    output_root.mkdir(parents=True, exist_ok=True)
    ledger = output_root / "control.sqlite3"
    lock = tmp_path / "artifacts/locks/m0-worker.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    research_log = tmp_path / "RESEARCH_LOG.md"
    prereg = output_root / "prereg.json"

    # Assert paths are strictly beneath tmp_path
    for p in (output_root, ledger, lock, research_log, prereg):
        assert str(p.resolve()).startswith(str(tmp_path.resolve())), f"Path escape: {p}"

    return {
        "tmp_path": tmp_path,
        "output_root": output_root,
        "ledger": ledger,
        "lock": lock,
        "research_log": research_log,
        "prereg": prereg,
    }


def _make_args(tmp_env: dict[str, Any], mode: str, **kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        arm=kwargs.get("arm", "arm_a"),
        seed=kwargs.get("seed", 42),
        output_root=tmp_env["output_root"],
        ledger=tmp_env["ledger"],
        lock_file=tmp_env["lock"],
        research_log=tmp_env["research_log"],
        prereg=tmp_env["prereg"],
        budget=kwargs.get("budget"),
        runner=kwargs.get("runner"),
        fake_clock=kwargs.get("fake_clock"),
        experiment_id=kwargs.get("experiment_id", worker.EXPERIMENT_ID),
    )


# --- Test (a): No approval line -> train refused, verify passes with zero writes ---
def test_a_no_approval_refuses_train_verify_zero_writes(tmp_env):
    """(a) 没有批准行：train 被拒（exit 3）；verify 通过且零写入。"""
    # Frozen prereg exists, but the research log carries no approval line.
    _freeze_and_approve(tmp_env)
    tmp_env["research_log"].write_text("# Project Log\n\nNo approvals here.\n", encoding="utf-8")

    # verify mode: passes with zero writes
    verify_args = _make_args(tmp_env, "verify")
    report_v, code_v = commands.s2_phase1_command(verify_args)
    assert code_v == commands.EXIT_COMPLETED
    assert report_v["status"] == "verified"
    assert report_v["approved"] is False
    assert not tmp_env["ledger"].exists(), "verify must not create or write to ledger"
    assert not tmp_env["lock"].exists(), "verify must not touch lock file"

    # train mode: refused because approval line is missing
    train_args = _make_args(tmp_env, "train", runner=make_fake_runner())
    report_t, code_t = commands.s2_phase1_command(train_args)
    assert code_t == commands.EXIT_REFUSED_APPROVAL
    assert report_t["status"] == "refused"
    assert report_t["stage"] == "approval"
    assert not tmp_env["ledger"].exists(), "refused train must not touch ledger"


# --- Test (b): Qualified approval line -> admits train cell; second attempt returns duplicate_execution ---
def test_b_qualified_approval_admits_train_and_detects_duplicate(tmp_env):
    """(b) 有合格批准行加假 runner：能准入一格 train；同一格第二次准入返回 duplicate_execution。"""
    _freeze_and_approve(tmp_env)

    fake_runner = make_fake_runner(active_seconds=200.0)
    args_first = _make_args(tmp_env, "train", arm="arm_a", seed=42, runner=fake_runner)

    # First execution: successfully admitted and completed
    report_1, code_1 = commands.s2_phase1_command(args_first)
    assert code_1 == commands.EXIT_COMPLETED
    assert report_1["status"] == "completed"
    assert report_1["result"]["active_seconds"] == 200.0

    # Second execution of the exact same cell (train, arm_a, seed 42): refused as duplicate
    report_2, code_2 = commands.s2_phase1_command(args_first)
    assert code_2 == commands.EXIT_FAILED
    assert report_2["status"] == "refused"
    assert report_2["stage"] == "duplicate_execution"

    # Different seed (seed 43) is NOT a duplicate: can be admitted
    args_diff_seed = _make_args(tmp_env, "train", arm="arm_a", seed=43, runner=fake_runner)
    report_3, code_3 = commands.s2_phase1_command(args_diff_seed)
    assert code_3 == commands.EXIT_COMPLETED
    assert report_3["status"] == "completed"


# --- Test (c): Total phase wall-clock ceiling (registered total, appendix F) & Boundary Condition ---
def test_c_phase_budget_ceiling_boundary_and_lineage_accumulation(tmp_env):
    """(c) 总上限：累计到超过 10 h 的那一格被拒；恰好等于 10 h 的边界单独测一条；跨谱系累计验证。"""
    _freeze_and_approve(tmp_env)

    total_ceiling = float(spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS)  # registered total (appendix F: 54,000 s)

    # Simulate past lineage run from an earlier revision "s2-phase1-20261106-r0" consuming 34,800 s
    past_consumed = total_ceiling - 1200.0  # one 1,200 s cell left before the ceiling
    clock = FakeClock()
    ledger = worker.S2Ledger(tmp_env["ledger"], clock=clock.time)
    past_run_id = ledger.open_run(
        mode="train",
        arm="arm_a",
        seed=10,
        cell_wall_budget=past_consumed,
        experiment_id="s2-phase1-20261106-r0",
    )
    ledger.begin_run(past_run_id)
    ledger.complete_run(past_run_id, active_seconds=past_consumed)
    ledger.close()

    # Case 1: Exact boundary condition -> new cell budget = 1,200 s; total reaches the ceiling exactly.
    # Must be admitted!
    args_boundary = _make_args(
        tmp_env,
        "train",
        arm="arm_b",
        seed=42,
        budget=1200.0,
        fake_clock=clock,
        experiment_id="s2-phase1-20261106-r1",
        runner=make_fake_runner(active_seconds=1200.0),
    )
    report_b, code_b = commands.s2_phase1_command(args_boundary)
    assert code_b == commands.EXIT_COMPLETED, f"Boundary cell failed: {report_b}"
    assert report_b["status"] == "completed"

    # Case 2: Ceiling reached. Any additional compute cell (> 0 s) must be refused!
    args_overflow = _make_args(
        tmp_env,
        "train",
        arm="arm_c",
        seed=42,
        budget=1200.0,
        fake_clock=clock,
        experiment_id="s2-phase1-20261106-r1",
        runner=make_fake_runner(),
    )
    report_over, code_over = commands.s2_phase1_command(args_overflow)
    assert code_over == commands.EXIT_REFUSED_RESOURCE
    assert report_over["status"] == "refused"
    assert report_over["stage"] == "phase_budget_exceeded"
    assert report_over["consumed_seconds"] == total_ceiling
    assert report_over["ceiling_seconds"] == total_ceiling


# --- Test (d): Calendar window (72 h) vs actual compute wall-time separation ---
def test_d_calendar_window_separation_and_expiration(tmp_env):
    """(d) 日历窗口与实际用时分离：两格之间空 30 h（实际用时远小于 10 h），仍能准入；超过 72 h 后被拒。"""
    _freeze_and_approve(tmp_env)

    fake_clock = FakeClock(start_ts=1700000000.0)
    fake_runner = make_fake_runner(active_seconds=100.0)

    # 1. First cell at t = 0
    args_1 = _make_args(tmp_env, "train", arm="arm_a", seed=42, fake_clock=fake_clock, runner=fake_runner)
    report_1, code_1 = commands.s2_phase1_command(args_1)
    assert code_1 == commands.EXIT_COMPLETED

    # 2. Advance clock by 30 hours (30 * 3600 = 108,000 s). Actual compute consumed = 100 s (<< 10 h).
    # Since 30 h < 72 h calendar window, the second cell MUST BE ADMITTED!
    fake_clock.advance(30.0 * 3600.0)
    args_2 = _make_args(tmp_env, "train", arm="arm_a", seed=43, fake_clock=fake_clock, runner=fake_runner)
    report_2, code_2 = commands.s2_phase1_command(args_2)
    assert code_2 == commands.EXIT_COMPLETED, f"Second cell refused after 30h: {report_2}"
    assert report_2["status"] == "completed"

    # 3. Advance clock past 72 hours from start (advance by an additional 43 hours -> total elapsed = 73 hours > 72 h).
    # Calendar window has expired! Cell 3 must be refused with experiment_budget_exceeded.
    fake_clock.advance(43.0 * 3600.0)
    args_3 = _make_args(tmp_env, "train", arm="arm_a", seed=44, fake_clock=fake_clock, runner=fake_runner)
    report_3, code_3 = commands.s2_phase1_command(args_3)
    assert code_3 == commands.EXIT_REFUSED_RESOURCE
    assert report_3["status"] == "refused"
    assert report_3["stage"] == "experiment_budget_exceeded"


# --- Test (e): Non-qualifying approval lines (blockquote, fenced code, indented block) ---
def test_e_approval_line_in_quote_or_code_refused(tmp_env):
    """(e) 批准行出现在引用块、代码块或缩进行里，都不算合格。"""
    # 1. Blockquote
    text_quote = (
        f"## R20261106-S2-approval\n\n"
        f"> APPROVED s2-phase1 prereg document_sha256={QUALIFIED_HASH}\n"
    )
    tmp_env["research_log"].write_text(text_quote, encoding="utf-8")
    scan_q = commands.scan_approval_log(tmp_env["research_log"])
    assert not scan_q["found"]
    assert scan_q["skipped"]["blockquote"]

    # 2. Fenced code
    text_fence = (
        f"## R20261106-S2-approval\n\n"
        f"```\n"
        f"APPROVED s2-phase1 prereg document_sha256={QUALIFIED_HASH}\n"
        f"```\n"
    )
    tmp_env["research_log"].write_text(text_fence, encoding="utf-8")
    scan_f = commands.scan_approval_log(tmp_env["research_log"])
    assert not scan_f["found"]
    assert scan_f["skipped"]["fenced_code"]

    # 3. Indented block (4 spaces)
    text_indent = (
        f"## R20261106-S2-approval\n\n"
        f"    APPROVED s2-phase1 prereg document_sha256={QUALIFIED_HASH}\n"
    )
    tmp_env["research_log"].write_text(text_indent, encoding="utf-8")
    scan_i = commands.scan_approval_log(tmp_env["research_log"])
    assert not scan_i["found"]
    assert scan_i["skipped"]["indented_code"]


# --- Test (f): Subprocess test with .venv/bin/python -I without conftest ---
def test_f_isolated_subprocess_verify_matches_expected(tmp_env):
    """(f) 子进程用 `.venv/bin/python -I -m ainerzero s2-phase1 --mode verify` 指向临时路径。"""
    repo_root = Path(__file__).resolve().parents[3]
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        real_venv = Path("/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python")
        if real_venv.exists():
            venv_python = real_venv
    py_exec = str(venv_python)

    # Write a qualified approval log
    frozen_sha = _freeze_and_approve(tmp_env)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root}:{repo_root / 'src'}"

    cmd = [
        py_exec,
        "-I",
        "-m",
        "ainerzero",
        "s2-phase1",
        "--mode",
        "verify",
        "--research-log",
        str(tmp_env["research_log"]),
        "--output-root",
        str(tmp_env["output_root"]),
    ]

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    data = json.loads(proc.stdout)
    assert data["status"] == "verified"
    assert data["approved"] is True
    assert data["approval_info"]["document_sha256"] == frozen_sha


# --- Test (g): ledger_read_snapshot leaves real ledger, WAL, and SHM completely untouched ---
def test_g_ledger_read_snapshot_leaves_real_ledger_completely_untouched(tmp_path):
    """(g) 预检读取前后，对主库、-wal、-shm 分别做 stat（mtime_ns、size、inode）加 SHA，结果完全一致；账本目录零新增文件。"""
    ledger_dir = tmp_path / "protected_ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "control.sqlite3"
    wal_path = ledger_dir / "control.sqlite3-wal"
    shm_path = ledger_dir / "control.sqlite3-shm"

    # Hold a connection open to simulate an active running worker / process
    hold_conn = sqlite3.connect(ledger_path)
    hold_conn.execute("PRAGMA journal_mode=WAL")

    # Create a real ledger with WAL & SHM active
    ledger = worker.S2Ledger(ledger_path)
    run_id = ledger.open_run(mode="train", arm="arm_a", seed=42, cell_wall_budget=100.0)
    ledger.begin_run(run_id, state="training")
    # Keep in WAL without checkpoint
    ledger.store._conn.execute("PRAGMA wal_autocheckpoint=0")
    ledger.complete_run(run_id, active_seconds=10.0)

    assert ledger_path.is_file()
    assert wal_path.is_file() and wal_path.stat().st_size > 0
    assert shm_path.is_file()

    # Snapshot pre-state of ledger_dir
    pre_dir_files = sorted(f.name for f in ledger_dir.iterdir())

    def get_file_stat_and_sha(p: Path):
        st = p.stat()
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        return (st.st_mtime_ns, st.st_size, st.st_ino, sha)

    pre_ledger = get_file_stat_and_sha(ledger_path)
    pre_wal = get_file_stat_and_sha(wal_path)
    pre_shm = get_file_stat_and_sha(shm_path)

    # Perform snapshot read
    with worker.ledger_read_snapshot(ledger_path) as store:
        assert store is not None
        runs = store.list_runs()
        assert len(runs) >= 1

    # Check preflight check_cell_already_completed
    assert worker.check_cell_already_completed(ledger_path, mode="train", arm="arm_a", seed=42) is True

    # Assert ledger_dir has zero new files (e.g. no .tmp_read_* left behind)
    post_dir_files = sorted(f.name for f in ledger_dir.iterdir())
    assert post_dir_files == pre_dir_files

    # Assert stat and SHA256 of all 3 files are 100% identical
    post_ledger = get_file_stat_and_sha(ledger_path)
    post_wal = get_file_stat_and_sha(wal_path)
    post_shm = get_file_stat_and_sha(shm_path)

    assert post_ledger == pre_ledger, f"Main ledger was modified: {pre_ledger} -> {post_ledger}"
    assert post_wal == pre_wal, f"WAL was modified: {pre_wal} -> {post_wal}"
    assert post_shm == pre_shm, f"SHM was modified: {pre_shm} -> {post_shm}"

    ledger.close()
    hold_conn.close()


# --- Test (h): ledger_read_snapshot reads completed runs residing only in WAL ---
def test_h_ledger_read_snapshot_reads_completed_run_residing_only_in_wal(tmp_path):
    """(h) 账本里有一条 completed 记录、只存在于 WAL 中时，预检也能读到，验证 WAL 确实被一并拷贝。"""
    ledger_dir = tmp_path / "wal_only_ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "control.sqlite3"
    wal_path = ledger_dir / "control.sqlite3-wal"

    hold_conn = sqlite3.connect(ledger_path)
    hold_conn.execute("PRAGMA journal_mode=WAL")

    ledger = worker.S2Ledger(ledger_path)
    run_id = ledger.open_run(mode="train", arm="arm_b", seed=43, cell_wall_budget=200.0)
    ledger.begin_run(run_id, state="training")
    ledger.store._conn.execute("PRAGMA wal_autocheckpoint=0")
    ledger.complete_run(run_id, active_seconds=20.0)

    assert wal_path.is_file() and wal_path.stat().st_size > 0

    # Confirm that reading with ledger_read_snapshot sees the completed cell
    with worker.ledger_read_snapshot(ledger_path) as store:
        assert store is not None
        completed_runs = [
            r for r in store.list_runs()
            if r.state == "completed" and r.config_snapshot.get("seed") == 43
        ]
        assert len(completed_runs) == 1

    # And check_cell_already_completed returns True
    assert worker.check_cell_already_completed(ledger_path, mode="train", arm="arm_b", seed=43) is True

    ledger.close()
    hold_conn.close()


# --- Preflight 0 (11-07): run modes require frozen prereg, matching identity, approval bound to its SHA ---
def test_g_run_mode_refused_when_unfrozen(tmp_env):
    """没有冻结的 prereg.json：train 被拒（stage=unfrozen），不碰账本。"""
    tmp_env["research_log"].write_text(
        f"## R20261106-S2-approval\n\nAPPROVED s2-phase1 prereg document_sha256={QUALIFIED_HASH}\n",
        encoding="utf-8",
    )
    report, code = commands.s2_phase1_command(_make_args(tmp_env, "train", runner=make_fake_runner()))
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert report["stage"] == "unfrozen"
    assert not tmp_env["ledger"].exists()


def test_h_run_mode_refused_when_approval_names_other_document(tmp_env):
    """已冻结，但批准行写的是别的哈希：train 被拒（stage=approval）。"""
    _freeze_and_approve(tmp_env)
    tmp_env["research_log"].write_text(
        f"## R20261106-S2-approval\n\nAPPROVED s2-phase1 prereg document_sha256={QUALIFIED_HASH}\n",
        encoding="utf-8",
    )
    report, code = commands.s2_phase1_command(_make_args(tmp_env, "train", runner=make_fake_runner()))
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert report["stage"] == "approval"
    assert not tmp_env["ledger"].exists()


def test_i_run_mode_refused_on_source_identity_mismatch(tmp_env, monkeypatch):
    """冻结后源码摘要变化（模拟改了一个 s2 文件）：train 被拒（stage=identity_mismatch）。"""
    _freeze_and_approve(tmp_env)
    from ainerzero.v9.experiments.s2 import freeze as s2_freeze
    from ainerzero.v9.experiments.s2 import identity as s2_identity

    real = s2_freeze.collect_source_digests

    def tampered(repo_root=None):
        d = dict(real(repo_root))
        key = sorted(d)[0]
        d[key] = "f" * 64
        return d

    monkeypatch.setattr(s2_freeze, "collect_source_digests", tampered)
    if hasattr(s2_identity, "collect_source_digests"):
        monkeypatch.setattr(s2_identity, "collect_source_digests", tampered)
    report, code = commands.s2_phase1_command(_make_args(tmp_env, "train", runner=make_fake_runner()))
    assert code == commands.EXIT_FAILED
    assert report["stage"] == "identity_mismatch"
    assert not tmp_env["ledger"].exists()


def test_j_run_mode_admitted_with_frozen_prereg_and_matching_approval(tmp_env):
    """冻结且批准行哈希一致：train 被准入。"""
    sha = _freeze_and_approve(tmp_env)
    report, code = commands.s2_phase1_command(
        _make_args(tmp_env, "train", runner=make_fake_runner(active_seconds=10.0))
    )
    assert code == commands.EXIT_COMPLETED, report
    assert report["status"] == "completed"
    assert len(sha) == 64
