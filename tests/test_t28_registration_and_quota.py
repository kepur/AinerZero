"""Tests for T28 proposal registration, dynamic DA3 quota derivation,
single-run wall clock cap enforcement, and date-based metadata views override.

Security and integrity verifications (r2):
1. No registration file returns previous frozen defaults (18 / 1200.0 / None).
2. Valid registration with matching proposal SHA and relative path inside
   reports/V9-T28/ derives 50 views / 1290s cumulative / 120s per-run.
3. Proposal SHA mismatch loudly raises ValueError and refuses execution.
4. Missing, null, or corrupted required fields loudly raise ValueError.
5. Single-run wall budget gate: 120s passes, 121s is refused with BenchmarkBudgetRefused.
6. RunStore metadata override:
   - Only 20261027 returns 82;
   - Adding 20261028 (131) selects latest date and returns 131;
   - Same date conflict (e.g. 131 vs 135) loudly refuses with BenchmarkRefusalError.
7. Real pipeline calibration views gate dynamically requires 50 views.
8. [r2 Security] Environment variable bypass immunity: setting T28_REGISTERED_PATH
   has zero effect on production registry resolution (A-scenario reproduction guard).
9. [r2 Security] CWD bypass immunity: placing fake REGISTERED.json in cwd
   has zero effect on production registry resolution (B-scenario reproduction guard).
10. [r2 Security] Absolute proposal_path is strictly rejected.
11. [r2 Security] Relative proposal_path with '..' directory escape is strictly rejected.
12. [r2 Security] Relative proposal_path outside reports/V9-T28/ is strictly rejected.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ainerzero.v9.teachers import benchmark_protocol, da3_controlled, da3_worker, t28_registration
from ainerzero.v9.teachers.benchmark_protocol import (
    EXIT_REFUSED_BUDGET,
    BenchmarkBudgetRefused,
    BenchmarkRefusalError,
    DA3RunSpec,
    T6_MAX_VIEWS,
)
from ainerzero.v9.teachers.da3_controlled import (
    execute_guarded_da3_benchmark,
    get_effective_t6_max_views,
)
from ainerzero.v9.teachers.t28_registration import (
    DEFAULT_CALIBRATION_VIEWS,
    DEFAULT_CUMULATIVE_WALL_CAP_S,
    DEFAULT_RUN_WALL_BUDGET_S,
    get_registered_calibration_views,
    get_registered_cumulative_wall_cap_s,
    get_registered_run_wall_budget_s,
    load_t28_registration,
)


class FakeDA3BenchmarkAdapter:
    """Mock adapter for CPU test substitute execution."""
    def run(self, *args, **kwargs):
        return {"status": "completed", "model_runs": 0}


def test_no_registration_returns_frozen_defaults(tmp_path: Path):
    """When REGISTERED.json does not exist, return exact frozen defaults (18 / 1200.0 / None)."""
    # Point repo_root to empty tmp_path
    info = load_t28_registration(repo_root=tmp_path)
    assert info.is_registered is False
    assert info.calibration_views == 18
    assert info.cumulative_wall_cap_s == 1200.0
    assert info.run_wall_budget_s is None

    assert get_registered_calibration_views(repo_root=tmp_path) == 18
    assert get_registered_cumulative_wall_cap_s(repo_root=tmp_path) == 1200.0
    assert get_registered_run_wall_budget_s(repo_root=tmp_path) is None

    assert DEFAULT_CALIBRATION_VIEWS == 18
    assert DEFAULT_CUMULATIVE_WALL_CAP_S == 1200.0


def test_valid_registration_and_sha_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When REGISTERED.json points to valid proposal with matching SHA, derive 50 / 1290 / 120."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    proposal_content = {
        "budget": {
            "cumulative_wall_seconds_max": 1290,
            "view_accounting": {
                "charge_per_complete_run": 50,
                "cumulative_view_cap": 131,
            },
            "wall_accounting": {
                "approved_run_wall_budget_seconds": 120,
                "cumulative_cap_s": 1290,
            },
        }
    }
    proposal_file = reg_dir / "proposal.json"
    raw_bytes = json.dumps(proposal_content).encode("utf-8")
    proposal_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_data = {
        "proposal_path": "reports/V9-T28/proposal.json",
        "sha256": sha256,
        "registered_by": "claude-az",
        "registered_at": "2026-10-28T18:00:00+03:00",
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    monkeypatch.setattr(t28_registration, "REPO_ROOT", tmp_path)

    info = load_t28_registration()
    assert info.is_registered is True
    assert info.calibration_views == 50
    assert info.cumulative_wall_cap_s == 1290.0
    assert info.run_wall_budget_s == 120.0

    assert get_registered_calibration_views() == 50
    assert get_registered_cumulative_wall_cap_s() == 1290.0
    assert get_registered_run_wall_budget_s() == 120.0

    assert da3_worker.REGISTERED_CALIBRATION_VIEWS == 50
    assert benchmark_protocol.T6_MAX_CUMULATIVE_WALL_SECONDS == 1290.0


def test_sha_mismatch_refused(tmp_path: Path):
    """When proposal SHA256 does not match registration, raise ValueError and refuse."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    proposal_content = {
        "budget": {
            "cumulative_wall_seconds_max": 1290,
            "view_accounting": {"charge_per_complete_run": 50},
            "wall_accounting": {"approved_run_wall_budget_seconds": 120},
        }
    }
    proposal_file = reg_dir / "proposal.json"
    proposal_file.write_text(json.dumps(proposal_content), encoding="utf-8")

    reg_file = reg_dir / "REGISTERED.json"
    reg_data = {
        "proposal_path": "reports/V9-T28/proposal.json",
        "sha256": "0" * 64,  # mismatched SHA
        "registered_by": "claude",
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        load_t28_registration(repo_root=tmp_path)


@pytest.mark.parametrize(
    "tampered_proposal",
    [
        {"budget": None},
        {"budget": {"view_accounting": None, "wall_accounting": {"approved_run_wall_budget_seconds": 120}, "cumulative_wall_seconds_max": 1290}},
        {"budget": {"view_accounting": {"charge_per_complete_run": None}, "wall_accounting": {"approved_run_wall_budget_seconds": 120}, "cumulative_wall_seconds_max": 1290}},
        {"budget": {"view_accounting": {"charge_per_complete_run": 50}, "wall_accounting": {"approved_run_wall_budget_seconds": None}, "cumulative_wall_seconds_max": 1290}},
        {"budget": {"view_accounting": {"charge_per_complete_run": 50}, "wall_accounting": {"approved_run_wall_budget_seconds": 120}, "cumulative_wall_seconds_max": None}},
    ],
)
def test_null_or_missing_fields_refused(tmp_path: Path, tampered_proposal: dict):
    """Any null or missing budget field must loudly fail with ValueError."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    proposal_file = reg_dir / "proposal.json"
    raw_bytes = json.dumps(tampered_proposal).encode("utf-8")
    proposal_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_data = {
        "proposal_path": "reports/V9-T28/proposal.json",
        "sha256": sha256,
        "registered_by": "claude",
    }
    reg_file.write_text(json.dumps(reg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="missing, null, or invalid|missing or null"):
        load_t28_registration(repo_root=tmp_path)


def test_wall_budget_gate_single_run_120_vs_121(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When run_wall_budget_s is 120s, 120s is accepted but 121s is refused."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    proposal_content = {
        "budget": {
            "cumulative_wall_seconds_max": 1290,
            "view_accounting": {"charge_per_complete_run": 50},
            "wall_accounting": {"approved_run_wall_budget_seconds": 120},
        }
    }
    proposal_file = reg_dir / "proposal.json"
    raw_bytes = json.dumps(proposal_content).encode("utf-8")
    proposal_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/proposal.json", "sha256": sha256}),
        encoding="utf-8",
    )
    monkeypatch.setattr(t28_registration, "REPO_ROOT", tmp_path)

    # Setup test env
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        """# Research Log
## R20261026-T6：批准 T6 有界 DA3 标定入口
- 批准对象：ainerzero.V9.T6。关键字：批准 T6。
- 统计协议：见 statistical_protocol.json
""",
        encoding="utf-8",
    )
    proto_file = tmp_path / "statistical_protocol.json"
    proto_file.write_text(
        json.dumps(
            {
                "protocol_id": "az.v9.da3.calibration.v1",
                "metrics": ["rotation_error_deg", "translation_rel_error"],
                "calibration_inputs": {"n_worlds": 4},
                "tolerance": {"max_rotation_deg": 1.0},
            }
        ),
        encoding="utf-8",
    )

    store_path = tmp_path / "runs.db"
    lock_path = tmp_path / "worker.lock"
    weights_root = Path("artifacts/teachers/da3")

    # 120.0 seconds: passes
    spec_120 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=120.0,
        views=4,
        research_log_path=log_file,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=proto_file,
    )
    res = execute_guarded_da3_benchmark(spec_120, adapter=FakeDA3BenchmarkAdapter())
    assert res["status"] == "completed"

    # 121.0 seconds: refused with BenchmarkBudgetRefused
    spec_121 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=121.0,
        views=4,
        research_log_path=log_file,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=proto_file,
    )
    with pytest.raises(BenchmarkBudgetRefused) as exc:
        execute_guarded_da3_benchmark(spec_121, adapter=FakeDA3BenchmarkAdapter())
    assert exc.value.exit_code == EXIT_REFUSED_BUDGET
    assert "exceeds registered single-run budget limit 120.0s" in str(exc.value)


def test_metadata_views_override_by_date(tmp_path: Path):
    """Metadata views override tests:
    - 20261027 alone -> 82
    - 20261027 (82) + 20261028 (131) -> 131
    - same date conflict (131 vs 135) -> BenchmarkRefusalError
    """
    db_path = tmp_path / "override_runs.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")

    # 1. Only 20261027 present -> 82
    cur.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        ("t6_views_override_20261027", json.dumps({"new_max_views": 82})),
    )
    conn.commit()
    assert get_effective_t6_max_views(db_path) == 82

    # 2. Add 20261028 with 131 -> latest is 20261028, returns 131
    cur.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        ("t6_views_override_20261028", json.dumps({"new_max_views": 131})),
    )
    conn.commit()
    assert get_effective_t6_max_views(db_path) == 131

    # Adding non-conflicting t35 key on 20261028 with 131 still yields 131
    cur.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        ("t35_views_override_20261028", json.dumps({"new_max_views": 131})),
    )
    conn.commit()
    assert get_effective_t6_max_views(db_path) == 131

    # 3. Conflict on same date (20261028): update t35_views_override_20261028 to 135 -> conflict
    cur.execute(
        "UPDATE metadata SET value = ? WHERE key = ?",
        (json.dumps({"new_max_views": 135}), "t35_views_override_20261028"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(BenchmarkRefusalError, match="Conflicting views override"):
        get_effective_t6_max_views(db_path)


def test_real_pipeline_calibration_views_gate_dynamic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When registered proposal dictates 50 views, real_pipeline execution requires views == 50."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    proposal_content = {
        "budget": {
            "cumulative_wall_seconds_max": 1290,
            "view_accounting": {"charge_per_complete_run": 50},
            "wall_accounting": {"approved_run_wall_budget_seconds": 120},
        }
    }
    proposal_file = reg_dir / "proposal.json"
    raw_bytes = json.dumps(proposal_content).encode("utf-8")
    proposal_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/proposal.json", "sha256": sha256}),
        encoding="utf-8",
    )
    monkeypatch.setattr(t28_registration, "REPO_ROOT", tmp_path)

    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        """# Research Log
## R20261026-T6：批准 T6 有界 DA3 标定入口
- 批准对象：ainerzero.V9.T6。关键字：批准 T6。
- 统计协议：见 statistical_protocol.json
""",
        encoding="utf-8",
    )
    proto_file = tmp_path / "statistical_protocol.json"
    proto_file.write_text(
        json.dumps(
            {
                "protocol_id": "az.v9.da3.calibration.v1",
                "metrics": ["rotation_error_deg"],
                "calibration_inputs": {"n_worlds": 4},
                "tolerance": {"max_rotation_deg": 1.0},
            }
        ),
        encoding="utf-8",
    )

    store_path = tmp_path / "runs.db"
    lock_path = tmp_path / "worker.lock"
    weights_root = Path("artifacts/teachers/da3")

    # views=18 was old default, but with registration active, 18 != 50 -> refused
    spec_old_views = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=120.0,
        views=18,
        research_log_path=log_file,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=proto_file,
    )
    with pytest.raises(BenchmarkRefusalError) as exc:
        execute_guarded_da3_benchmark(
            spec_old_views,
            worker_action="real_pipeline",
            allow_custom_paths=True,
            coordinator_release=True,
        )
    assert "Real DA3 pipeline execution requires views == 50" in str(exc.value)
    assert exc.value.details.get("required_views") == 50


# ==============================================================================
# r2 Security & Anti-Bypass Tests
# ==============================================================================

def test_security_scenario_a_env_var_bypass_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario A Reproduction & Guard:
    Setting T28_REGISTERED_PATH to a malicious registration pointing to 999999s cumulative cap
    must have ZERO effect. The system must ignore the env var and return safe frozen defaults.
    """
    fake_proposal = {
        "budget": {
            "cumulative_wall_seconds_max": 999999,
            "view_accounting": {"charge_per_complete_run": 999},
            "wall_accounting": {"approved_run_wall_budget_seconds": 99999},
        }
    }
    fake_proposal_bytes = json.dumps(fake_proposal).encode("utf-8")
    fake_proposal_file = tmp_path / "fake_proposal.json"
    fake_proposal_file.write_bytes(fake_proposal_bytes)
    fake_sha = hashlib.sha256(fake_proposal_bytes).hexdigest()

    fake_reg_file = tmp_path / "fake_reg.json"
    fake_reg_file.write_text(
        json.dumps({"proposal_path": str(fake_proposal_file), "sha256": fake_sha}),
        encoding="utf-8",
    )

    # Malicious attempt to inject registry via environment variable
    clean_repo = tmp_path / "clean_repo"
    clean_repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", clean_repo)
    monkeypatch.setenv("T28_REGISTERED_PATH", str(fake_reg_file))

    # Without registered file in real repo_root, defaults must be returned
    info = load_t28_registration()
    assert info.is_registered is False
    assert info.cumulative_wall_cap_s == DEFAULT_CUMULATIVE_WALL_CAP_S  # 1200.0, NOT 999999
    assert info.run_wall_budget_s is None  # NOT 99999
    assert info.calibration_views == DEFAULT_CALIBRATION_VIEWS  # 18, NOT 999

    assert get_registered_cumulative_wall_cap_s() == 1200.0
    assert get_registered_run_wall_budget_s() is None
    assert get_registered_calibration_views() == 18


def test_security_scenario_b_cwd_bypass_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Scenario B Reproduction & Guard:
    Placing reports/V9-T28/REGISTERED.json in an arbitrary directory and running from that cwd
    must have ZERO effect. The system must only look at <repo_root>/reports/V9-T28/REGISTERED.json.
    """
    clean_repo = tmp_path / "clean_repo_b"
    clean_repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", clean_repo)

    fake_cwd = tmp_path / "arbitrary_cwd"
    fake_reg_dir = fake_cwd / "reports/V9-T28"
    fake_reg_dir.mkdir(parents=True, exist_ok=True)

    fake_proposal = {
        "budget": {
            "cumulative_wall_seconds_max": 999999,
            "view_accounting": {"charge_per_complete_run": 999},
            "wall_accounting": {"approved_run_wall_budget_seconds": 99999},
        }
    }
    fake_proposal_bytes = json.dumps(fake_proposal).encode("utf-8")
    fake_prop_file = fake_reg_dir / "proposal.json"
    fake_prop_file.write_bytes(fake_proposal_bytes)
    fake_sha = hashlib.sha256(fake_proposal_bytes).hexdigest()

    fake_reg_file = fake_reg_dir / "REGISTERED.json"
    fake_reg_file.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/proposal.json", "sha256": fake_sha}),
        encoding="utf-8",
    )

    # Chdir to the fake directory
    monkeypatch.chdir(fake_cwd)

    # System must strictly evaluate against repo_root, ignoring cwd
    info = load_t28_registration()
    assert info.is_registered is False
    assert info.cumulative_wall_cap_s == 1200.0  # NOT 999999
    assert info.run_wall_budget_s is None  # NOT 99999
    assert info.calibration_views == 18  # NOT 999


def test_security_reject_absolute_proposal_path(tmp_path: Path):
    """Absolute proposal_path must be strictly rejected with ValueError."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    fake_proposal = {
        "budget": {
            "cumulative_wall_seconds_max": 1290,
            "view_accounting": {"charge_per_complete_run": 50},
            "wall_accounting": {"approved_run_wall_budget_seconds": 120},
        }
    }
    prop_file = reg_dir / "proposal.json"
    raw_bytes = json.dumps(fake_proposal).encode("utf-8")
    prop_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": str(prop_file.resolve()), "sha256": sha256}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Proposal path must be relative, got absolute"):
        load_t28_registration(repo_root=tmp_path)


def test_security_reject_directory_escape_proposal_path(tmp_path: Path):
    """Proposal path with '..' that escapes reports/V9-T28/ must be rejected."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    # Malicious proposal outside reports/V9-T28
    evil_proposal = tmp_path / "evil_proposal.json"
    content = {
        "budget": {
            "cumulative_wall_seconds_max": 999999,
            "view_accounting": {"charge_per_complete_run": 999},
            "wall_accounting": {"approved_run_wall_budget_seconds": 99999},
        }
    }
    raw_bytes = json.dumps(content).encode("utf-8")
    evil_proposal.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Attempt path traversal
    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({
            "proposal_path": "reports/V9-T28/../../evil_proposal.json",
            "sha256": sha256,
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes or is outside allowed directory"):
        load_t28_registration(repo_root=tmp_path)


def test_security_reject_outside_directory_relative_path(tmp_path: Path):
    """Proposal path pointing to relative path outside reports/V9-T28 must be rejected."""
    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)

    other_dir = tmp_path / "docs"
    other_dir.mkdir(parents=True, exist_ok=True)
    prop_file = other_dir / "proposal.json"
    content = {
        "budget": {
            "cumulative_wall_seconds_max": 999999,
            "view_accounting": {"charge_per_complete_run": 999},
            "wall_accounting": {"approved_run_wall_budget_seconds": 99999},
        }
    }
    raw_bytes = json.dumps(content).encode("utf-8")
    prop_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": "docs/proposal.json", "sha256": sha256}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes or is outside allowed directory"):
        load_t28_registration(repo_root=tmp_path)
