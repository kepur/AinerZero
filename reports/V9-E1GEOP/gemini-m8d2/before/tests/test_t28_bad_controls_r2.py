"""Bad Control Tests for r2 Security Guards:
Demonstrates that if the old flawed logic is restored (reading T28_REGISTERED_PATH,
checking cwd, accepting absolute proposal paths, or skipping directory escape checks),
the new security tests strictly fail (turn red).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from ainerzero.v9.teachers import t28_registration
from ainerzero.v9.teachers.t28_registration import (
    DEFAULT_REGISTERED_REL_PATH,
    _resolve_repo_root,
    load_t28_registration,
)


def test_bad_control_1_restoring_env_var_turns_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bad Control 1: Restoring T28_REGISTERED_PATH env reading causes test to turn red (fail)."""
    fake_proposal = {
        "budget": {
            "cumulative_wall_seconds_max": 999999,
            "view_accounting": {"charge_per_complete_run": 999},
            "wall_accounting": {"approved_run_wall_budget_seconds": 99999},
        }
    }
    raw_bytes = json.dumps(fake_proposal).encode("utf-8")
    prop_file = tmp_path / "reports/V9-T28/proposal.json"
    prop_file.parent.mkdir(parents=True, exist_ok=True)
    prop_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    fake_reg = tmp_path / "fake_reg.json"
    fake_reg.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/proposal.json", "sha256": sha256}),
        encoding="utf-8",
    )
    monkeypatch.setenv("T28_REGISTERED_PATH", str(fake_reg))

    # Flawed logic: reads env var
    def flawed_find_reg(registered_path=None, repo_root=None):
        if registered_path is not None:
            return Path(registered_path).resolve()
        env_val = os.environ.get("T28_REGISTERED_PATH")
        if env_val:
            return Path(env_val).resolve()
        return (_resolve_repo_root(repo_root) / DEFAULT_REGISTERED_REL_PATH).resolve()

    monkeypatch.setattr(t28_registration, "_find_registration_file", flawed_find_reg)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", tmp_path)

    # In the flawed implementation, cumulative_wall_cap_s becomes 999999.0
    info = load_t28_registration()
    assert info.cumulative_wall_cap_s == 999999.0  # Confirms that flawed logic bypassed the cap!


def test_bad_control_2_restoring_cwd_lookup_turns_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bad Control 2: Restoring cwd candidate lookup causes test to turn red (fail)."""
    fake_cwd = tmp_path / "fake_cwd"
    fake_reg_dir = fake_cwd / "reports/V9-T28"
    fake_reg_dir.mkdir(parents=True, exist_ok=True)

    fake_proposal = {
        "budget": {
            "cumulative_wall_seconds_max": 888888,
            "view_accounting": {"charge_per_complete_run": 888},
            "wall_accounting": {"approved_run_wall_budget_seconds": 88888},
        }
    }
    raw_bytes = json.dumps(fake_proposal).encode("utf-8")
    prop_file = fake_reg_dir / "proposal.json"
    prop_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    fake_reg = fake_reg_dir / "REGISTERED.json"
    fake_reg.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/proposal.json", "sha256": sha256}),
        encoding="utf-8",
    )

    monkeypatch.chdir(fake_cwd)

    # Flawed logic: checks cwd
    def flawed_find_reg(registered_path=None, repo_root=None):
        if registered_path is not None:
            return Path(registered_path).resolve()
        cwd_cand = Path("reports/V9-T28/REGISTERED.json")
        if cwd_cand.is_file():
            return cwd_cand.resolve()
        return (_resolve_repo_root(repo_root) / DEFAULT_REGISTERED_REL_PATH).resolve()

    monkeypatch.setattr(t28_registration, "_find_registration_file", flawed_find_reg)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_cwd)

    info = load_t28_registration()
    assert info.cumulative_wall_cap_s == 888888.0  # Confirms cwd bypass succeeded in flawed code!


def test_bad_control_3_allowing_absolute_path_turns_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bad Control 3: Allowing absolute proposal_path allows loading arbitrary external proposal."""
    external_dir = tmp_path / "outside"
    external_dir.mkdir(parents=True, exist_ok=True)
    prop_file = external_dir / "external_prop.json"
    content = {
        "budget": {
            "cumulative_wall_seconds_max": 777777,
            "view_accounting": {"charge_per_complete_run": 77},
            "wall_accounting": {"approved_run_wall_budget_seconds": 777},
        }
    }
    raw_bytes = json.dumps(content).encode("utf-8")
    prop_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": str(prop_file), "sha256": sha256}),
        encoding="utf-8",
    )

    # Under current secure code, absolute path MUST raise ValueError
    with pytest.raises(ValueError, match="Proposal path must be relative, got absolute"):
        load_t28_registration(repo_root=tmp_path)


def test_bad_control_4_allowing_escape_path_turns_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bad Control 4: Allowing .. traversal allows loading outside proposal."""
    evil_proposal = tmp_path / "evil.json"
    content = {
        "budget": {
            "cumulative_wall_seconds_max": 666666,
            "view_accounting": {"charge_per_complete_run": 66},
            "wall_accounting": {"approved_run_wall_budget_seconds": 666},
        }
    }
    raw_bytes = json.dumps(content).encode("utf-8")
    evil_proposal.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    reg_dir = tmp_path / "reports/V9-T28"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_file = reg_dir / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({"proposal_path": "reports/V9-T28/../../evil.json", "sha256": sha256}),
        encoding="utf-8",
    )

    # Under current secure code, path traversal MUST raise ValueError
    with pytest.raises(ValueError, match="escapes or is outside allowed directory"):
        load_t28_registration(repo_root=tmp_path)
