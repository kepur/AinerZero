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

import pytest

NATIVE_OPTION = "--native-mlx"

# Modules importing real MLX at module level (collection would import MLX).
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
