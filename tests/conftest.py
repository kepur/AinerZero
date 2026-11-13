"""Default pytest entry is pure CPU: no real MLX import, no model update.

A39 classification. Everything that imports real MLX at collection time or
performs real optimizer updates / needs real ``mlx.core`` is marked
``native_mlx`` and is NOT covered by the default entry. It is collected only
with the explicit ``--native-mlx`` opt-in. Opting in does not create a native
runner and grants no run authority: real model work must still go through the
project CLI, the shared lock ``artifacts/locks/m0-worker.lock``, the central
RunStore and the registered budget (see AGENTS.md). No registered native pytest
runner exists; do not run these bare.
"""

import fcntl
import glob
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure bytecode is never written into artifacts/
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import pytest

REAL_REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
LOCAL_REPO_ROOT = Path(__file__).resolve().parent.parent

HERMETIC_SENSITIVE_PATTERNS = [
    "artifacts/locks/**",
    "artifacts/locks",
    "artifacts/control.sqlite3*",
    "artifacts/v9/**/control.sqlite3*",
    "artifacts/v9/s1/**/*.sqlite3*",
    "artifacts/v9/e1/**",
]

# Whitelist for legitimate real-artifact access (real_path -> reason).
# The default pure-CPU suite must be hermetic, so this whitelist is empty by default.
HERMETIC_WHITELIST: dict[str, str] = {}

_hermetic_guards_active = True
_orig_flock = fcntl.flock
_orig_lockf = fcntl.lockf
_orig_sqlite_connect = sqlite3.connect


def guard_resolve_path(target) -> str | None:
    if target is None:
        return None
    if isinstance(target, int):
        try:
            buf = b" " * 1024
            res_buf = fcntl.fcntl(target, 50, buf)
            raw = res_buf.split(b"\x00", 1)[0].decode("utf-8", "replace")
            if raw:
                return os.path.realpath(raw)
        except OSError:
            pass
        try:
            proc_path = f"/proc/self/fd/{target}"
            if os.path.islink(proc_path):
                return os.path.realpath(proc_path)
        except Exception:
            pass
        return None
    if hasattr(target, "fileno"):
        try:
            return guard_resolve_path(target.fileno())
        except Exception:
            return None
    target_str = str(target)
    if not target_str or target_str == ":memory:":
        return None
    if target_str.startswith("file:"):
        target_str = urlparse(target_str).path
    try:
        return os.path.realpath(target_str)
    except Exception:
        return None


def check_hermetic_access(
    target,
    op_name: str,
    root: Path = REAL_REPO_ROOT,
    whitelist: dict | None = None,
) -> None:
    if not _hermetic_guards_active:
        return
    resolved = guard_resolve_path(target)
    if not resolved:
        return
    active_whitelist = HERMETIC_WHITELIST if whitelist is None else whitelist
    roots = [root]
    if root == REAL_REPO_ROOT and LOCAL_REPO_ROOT != REAL_REPO_ROOT and LOCAL_REPO_ROOT.is_dir():
        roots.append(LOCAL_REPO_ROOT)
    for r in roots:
        art_dir = os.path.realpath(r / "artifacts")
        if resolved == art_dir or resolved.startswith(art_dir + os.sep):
            if resolved not in active_whitelist:
                raise RuntimeError(
                    f"Hermetic test guard violation: {op_name} called on protected artifact: {resolved}. "
                    f"Tests must use tmp_path or staged copies and must never touch real artifacts."
                )


def make_guarded_flock(root: Path = REAL_REPO_ROOT, orig_flock=_orig_flock, whitelist=None):
    def _flock(fd, operation):
        check_hermetic_access(fd, "fcntl.flock", root=root, whitelist=whitelist)
        return orig_flock(fd, operation)
    return _flock


def make_guarded_lockf(root: Path = REAL_REPO_ROOT, orig_lockf=_orig_lockf, whitelist=None):
    def _lockf(fd, cmd, *args, **kwargs):
        check_hermetic_access(fd, "fcntl.lockf", root=root, whitelist=whitelist)
        return orig_lockf(fd, cmd, *args, **kwargs)
    return _lockf


def make_guarded_connect(root: Path = REAL_REPO_ROOT, orig_connect=_orig_sqlite_connect, whitelist=None):
    def _connect(database, *args, **kwargs):
        check_hermetic_access(database, "sqlite3.connect", root=root, whitelist=whitelist)
        return orig_connect(database, *args, **kwargs)
    return _connect


guarded_flock = make_guarded_flock(REAL_REPO_ROOT)
guarded_lockf = make_guarded_lockf(REAL_REPO_ROOT)
guarded_connect = make_guarded_connect(REAL_REPO_ROOT)


def _install_hermetic_function_guards() -> None:
    fcntl.flock = guarded_flock
    fcntl.lockf = guarded_lockf
    sqlite3.connect = guarded_connect
    if "sqlite3" in sys.modules:
        sys.modules["sqlite3"].connect = guarded_connect


def guard_snapshot(root: Path = REAL_REPO_ROOT) -> dict[str, tuple[int, int, int]]:
    """Record {path_str: (st_mtime_ns, st_size, st_ino)} for sensitive paths.

    Only performs stat; does NOT read file contents (especially sealed_final).
    """
    snapshot = {}
    roots = [root]
    if root == REAL_REPO_ROOT and LOCAL_REPO_ROOT != REAL_REPO_ROOT and LOCAL_REPO_ROOT.is_dir():
        roots.append(LOCAL_REPO_ROOT)
    for r in roots:
        for pattern in HERMETIC_SENSITIVE_PATTERNS:
            full_pattern = str(r / pattern)
            for p in glob.glob(full_pattern, recursive=True):
                try:
                    st = os.stat(p)
                    snapshot[os.path.realpath(p)] = (st.st_mtime_ns, st.st_size, st.st_ino)
                except OSError:
                    pass
    return snapshot


def guard_compare(before: dict, after: dict) -> dict[str, str]:
    diffs = {}
    all_keys = set(before.keys()) | set(after.keys())
    for k in sorted(all_keys):
        if k not in before:
            diffs[k] = "ADDED"
        elif k not in after:
            diffs[k] = "DELETED"
        elif before[k] != after[k]:
            b_mtime, b_size, b_ino = before[k]
            a_mtime, a_size, a_ino = after[k]
            changes = []
            if b_mtime != a_mtime:
                changes.append(f"mtime_ns: {b_mtime} -> {a_mtime}")
            if b_size != a_size:
                changes.append(f"size: {b_size} -> {a_size}")
            if b_ino != a_ino:
                changes.append(f"inode: {b_ino} -> {a_ino}")
            diffs[k] = "MODIFIED (" + ", ".join(changes) + ")"
    return diffs


# Install function-level patches immediately on module load
_install_hermetic_function_guards()

NATIVE_OPTION = "--native-mlx"

# Modules importing real MLX at collection time (collection would import MLX), either
# directly at module level or transitively through the code under test.  Keys are
# basenames anywhere under tests/ (pytest's rootdir/basename import mode keeps them unique).
#
# E1 and S1 (2026-11-06): the sources cannot be made lazy without breaking frozen
# identities.  ``ainerzero.v9.experiments.e1.__init__`` imports ``arms_net`` (module-level
# mlx.core/mlx.nn/mlx.optimizers), and every e1 source is bound by the frozen
# ``artifacts/v9/e1/phase2/prereg.json`` source_digests (E1 closed).  ``s1/arms.py`` imports
# mlx.core/mlx.nn at module level and is bound by ``artifacts/v9/s1/phase1/final/
# pre_registration.json``.  So every test module importing either package is native.
NATIVE_MODULES = {
    "test_dynamics.py": "module-level import mlx.core/mlx.nn/mlx.utils",
    "test_history_evaluation.py": "module-level import mlx.core",
    "test_micro_memory.py": "module-level import mlx.core",
    "test_one_step_memory.py": "module-level import mlx.core/mlx.nn/mlx.utils",
    "test_pilot_evaluation.py": "module-level import mlx.core",
    "test_pilot_model.py": "module-level importorskip mlx.core/mlx.nn/mlx.optimizers + mlx.utils",
    "test_recall_probe.py": "module-level import mlx.core",
    "test_reconstruction.py": "module-level import mlx.core",
    "test_relabel_memory_mlx.py": "module-level import mlx.core/mlx.nn",
    # E1: module-level mlx in the test itself, plus the e1 package init.
    "test_e1_arms_net.py": "module-level import mlx.core; e1 package init imports arms_net (mlx)",
    "test_e1_p87_geometry.py": "module-level import mlx.core; e1 package init imports arms_net (mlx)",
    "test_e1_p93_revision.py": "module-level import mlx.core/mlx.utils; e1 package init imports arms_net (mlx)",
    "test_e1_train_runner.py": "module-level import mlx.core; e1 package init imports arms_net (mlx)",
    # E1: transitive only, through the e1 package init (arms_net).
    "test_e1_analysis.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_arms_nonnet.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_calendar_window.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_contact_geometry.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_data_runner.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_entry.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_eval_runner.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_export.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_final_entry.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_identity.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_metrics.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_prereg.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_prior.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_prior_box.py": "e1 package init imports arms_net (module-level mlx)",
    "test_e1_wiring.py": "e1 package init imports arms_net (module-level mlx)",
    # S1 (tests/v9/experiments): transitive through s1.arms (module-level mlx).
    "test_s1_no_update.py": "imports s1.smoke -> s1.arms (module-level mlx)",
    "test_s1_pacer_duty.py": "imports s1.arms (module-level mlx)",
    "test_s1_r7_d_candidate.py": "imports s1.arms (module-level mlx)",
    # S2 (tests/v9/experiments): S2 arms MLX implementation.
    "test_s2_arms_mlx_native.py": "module-level import mlx.core/mlx.nn (S2 arms)",
    "test_s2_adapters_mlx_native.py": "module-level import mlx.core/mlx.nn (S2 MLX arm adapters)",
    "test_s2_arm_a_batched_native.py": "real MLX Arm A batched loss parity and speed (S2 W9)",
    "test_s2_learned_planning_native.py": "runs real MLX arms through learned planning (S2 W2)",
    "test_s2_production_e2e_native.py": "minimal MLX pipeline end-to-end (S2 W3)",
    "test_s2_train_native.py": "MLX arm training and smoke self-check native test (S2 W8)",
    "test_s2_plan_device_native.py": "planning inference device (CPU stream) vs training device, real MLX (S2 W10)",
    # S3 (tests/v9/experiments): MLX arms, gradients and truth-isolation contracts.
    "test_s3_arms_mlx.py": "module-level importorskip mlx.core/mlx.nn (S3 arms)",
    "test_s3_isolation_contract.py": "module-level importorskip mlx.core (S3 arms, P208 second-review checks)",
    "test_s3p2_arms_mlx.py": "module-level importorskip mlx.core/mlx.nn (S3 phase 2 training path)",
    "test_s3p2_runner_guards_native.py": "imports real MLX; runs the phase 2 runner start-up in a throwaway copy",
    # S4 phase 1: learned dynamics in MLX.
    "test_s4_learned_mlx.py": "module-level importorskip mlx.core (S4 learned dynamics, pools, training)",
    "test_s4p1_runner_native.py": "runs the real S4 phase 1 runner (MLX) in throwaway copies",
    # S4 phase 2: contact-gated models (MLX) and the runner.
    "test_s4_gated.py": "module-level importorskip mlx.core (S4 phase 2 contact-gated models)",
    "test_s4p2_runner_native.py": "runs the real S4 phase 2 runner (MLX) in throwaway copies",
    "test_s4p2_worker_native.py": "spawns fresh processes that compile MLX CPU kernels (S4 phase 2 workers)",
    # S5: Student ViT, losses, heads in MLX.
    "test_s5_student_mlx.py": "module-level importorskip mlx.core/mlx.nn (S5 student ViT, losses, heads)",
    "test_s5_train_mlx.py": "module-level importorskip mlx.core/mlx.nn (S5 data reading and training loops in MLX)",
    "test_s5_runner_native.py": "runs the S5 pre-freeze runner smoke path (MLX) in a throwaway copy",
    "test_s5_final_native.py": "runs the S5 registered runner end to end on stand-in partitions (MLX) in a throwaway copy",
}

# Individual tests in otherwise pure-CPU modules (prefix match on node id).
NATIVE_TESTS = {
    "tests/test_smoke.py::test_real_cpu_forward_backward_and_restored_continuation":
        "real run_smoke training + restored continuation (real optimizer updates)",
    "tests/test_smoke.py::test_low_budget_never_reports_unperformed_updates":
        "real run_smoke, 2 real optimizer updates",
    "tests/test_gridlab_s07_r2.py::test_isolation_check_detects_mlx_and_ignores_parent_state":
        "positive control imports real mlx.core in a child process",
    "tests/test_gridlab_s07_r2.py::test_f3_negative_control_separates_importerror_from_assertion":
        "F3 control requires real mlx.core import to reach the detector",
    "tests/v9/experiments/test_s1_timing_sequence.py::test_worker_train_resets_deadline_across_sequential_runs":
        "imports the test_s1_pacer_duty fakes at run time, which import s1.arms (real MLX)",
}


def pytest_addoption(parser):
    parser.addoption(
        NATIVE_OPTION, action="store_true", default=False,
        help="Opt in to native/MLX tests (not pure CPU). Still requires the project "
             "CLI lock, RunStore and registered budget; no bare native runner exists.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "native_mlx: imports real MLX or performs real model updates; "
        "excluded from the default pure-CPU entry (opt-in via --native-mlx)")
    if _native_enabled(config):
        global _hermetic_guards_active
        _hermetic_guards_active = False


def pytest_sessionstart(session):
    if not _native_enabled(session.config):
        session._hermetic_stat_before = guard_snapshot(REAL_REPO_ROOT)


@pytest.fixture(scope="session", autouse=True)
def hermetic_artifacts_guard(request):
    yield
    if _native_enabled(request.config):
        return
    before = getattr(request.session, "_hermetic_stat_before", {})
    after = guard_snapshot(REAL_REPO_ROOT)
    diff = guard_compare(before, after)
    assert not diff, (
        f"Hermetic session guard violation: real artifacts modified during test session:\n"
        + "\n".join(f"  {k}: {v}" for k, v in diff.items())
    )


@pytest.fixture(autouse=True)
def _restore_default_mlx_device_after_test(request):
    if _native_enabled(request.config) and "mlx.core" in sys.modules:
        import mlx.core as mx
        if mx.default_device() != mx.gpu:
            mx.set_default_device(mx.gpu)
    yield
    if _native_enabled(request.config) and "mlx.core" in sys.modules:
        import mlx.core as mx
        if mx.default_device() != mx.gpu:
            mx.set_default_device(mx.gpu)


def pytest_sessionfinish(session, exitstatus):
    if not _native_enabled(session.config):
        before = getattr(session, "_hermetic_stat_before", {})
        after = guard_snapshot(REAL_REPO_ROOT)
        diff = guard_compare(before, after)
        if diff:
            session.exitstatus = 1
            print(
                "\n[HERMETIC GUARD ERROR] Real artifacts modified during test session:\n"
                + "\n".join(f"  {k}: {v}" for k, v in diff.items()),
                file=sys.stderr,
            )


def _native_enabled(config):
    return bool(config.getoption(NATIVE_OPTION))


def pytest_ignore_collect(collection_path, config):
    if collection_path.name in NATIVE_MODULES and not _native_enabled(config):
        return True
    return None


def _native_reason(item):
    if item.path.name in NATIVE_MODULES:
        return NATIVE_MODULES[item.path.name]
    for prefix, reason in NATIVE_TESTS.items():
        if item.nodeid == prefix or item.nodeid.startswith(prefix + "["):
            return reason
    return None


def pytest_collection_modifyitems(config, items):
    selected, deselected = [], []
    for item in items:
        reason = _native_reason(item)
        if reason is not None:
            item.add_marker(pytest.mark.native_mlx(reason=reason))
        if item.get_closest_marker("native_mlx") is not None and not _native_enabled(config):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_report_header(config):
    if _native_enabled(config):
        return ("native-mlx OPT-IN: real MLX/model tests collected; must run under the "
                "project CLI lock/RunStore/budget, not bare pytest")
    return "default pure-CPU entry: native_mlx tests not collected/covered (see tests/conftest.py)"
