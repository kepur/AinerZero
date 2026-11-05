"""Dynamic derivation of DA3 quota and limits from registered T28 proposal.

Zero model, zero ledger side-effects. Reads reports/V9-T28/REGISTERED.json when present,
verifies proposal SHA256 integrity, and derives:
- calibration_views: budget.view_accounting.charge_per_complete_run
- cumulative_wall_cap_s: budget.cumulative_wall_seconds_max
- run_wall_budget_s: budget.wall_accounting.approved_run_wall_budget_seconds

When REGISTERED.json is absent, preserves previous frozen defaults (18 / 1200.0 / None).
When REGISTERED.json is present, any missing/null required field or SHA mismatch
loudly fails (raises ValueError / RuntimeError).

Security and containment rules (r2):
1. Registration file only recognizes <repo_root>/reports/V9-T28/REGISTERED.json.
   No T28_REGISTERED_PATH environment variable reading, no cwd searching.
   Tests inject via explicit registered_path= / repo_root= parameters or monkeypatching.
2. proposal_path must be a relative path and must resolve strictly inside
   <repo_root>/reports/V9-T28/. Absolute paths and '..' path escapes are rejected.
   Resolved strictly against repo_root, never against reg_file.parent or cwd.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CALIBRATION_VIEWS = 18
DEFAULT_CUMULATIVE_WALL_CAP_S = 1200.0
DEFAULT_RUN_WALL_BUDGET_S: float | None = None

DEFAULT_REGISTERED_REL_PATH = Path("reports/V9-T28/REGISTERED.json")
ALLOWED_PROPOSAL_DIR_REL_PATH = Path("reports/V9-T28")
REPO_ROOT: Path | None = None


@dataclass(frozen=True)
class T28RegistrationInfo:
    """Parsed and verified T28 registration parameters."""

    calibration_views: int
    cumulative_wall_cap_s: float
    run_wall_budget_s: float | None
    proposal_path: str | None = None
    sha256: str | None = None
    is_registered: bool = False


def _resolve_repo_root(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    if REPO_ROOT is not None:
        return Path(REPO_ROOT).resolve()
    return Path(__file__).resolve().parents[4]


def _find_registration_file(
    registered_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> Path:
    if registered_path is not None:
        return Path(registered_path).resolve()
    root = _resolve_repo_root(repo_root)
    return (root / DEFAULT_REGISTERED_REL_PATH).resolve()


def load_t28_registration(
    registered_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> T28RegistrationInfo:
    """Read and verify registered T28 proposal.
    
    If registered file does not exist, returns defaults (18 / 1200.0 / None).
    If registered file exists, verifies SHA256 and required fields; loudly fails on any error.
    """
    reg_file = _find_registration_file(registered_path, repo_root)
    if not reg_file.is_file():
        return T28RegistrationInfo(
            calibration_views=DEFAULT_CALIBRATION_VIEWS,
            cumulative_wall_cap_s=DEFAULT_CUMULATIVE_WALL_CAP_S,
            run_wall_budget_s=DEFAULT_RUN_WALL_BUDGET_S,
            is_registered=False,
        )

    try:
        raw_reg = reg_file.read_bytes()
        reg_data = json.loads(raw_reg.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to read/parse registration file {reg_file}: {exc}") from exc

    if not isinstance(reg_data, dict):
        raise ValueError(f"Registration file {reg_file} must contain a JSON object, got {type(reg_data)}")

    proposal_rel = reg_data.get("proposal_path")
    expected_sha = reg_data.get("sha256")

    if not proposal_rel or not isinstance(proposal_rel, str):
        raise ValueError(f"Registration file {reg_file} missing or null 'proposal_path'")
    if not expected_sha or not isinstance(expected_sha, str):
        raise ValueError(f"Registration file {reg_file} missing or null 'sha256'")

    root = _resolve_repo_root(repo_root)
    allowed_dir = (root / ALLOWED_PROPOSAL_DIR_REL_PATH).resolve()

    p_path = Path(proposal_rel)
    if p_path.is_absolute():
        raise ValueError(f"Proposal path must be relative, got absolute: {proposal_rel}")

    resolved_proposal = (root / p_path).resolve()
    try:
        resolved_proposal.relative_to(allowed_dir)
    except ValueError:
        raise ValueError(
            f"Proposal path '{proposal_rel}' resolves to '{resolved_proposal}', "
            f"which escapes or is outside allowed directory '{allowed_dir}'"
        )

    if not resolved_proposal.is_file():
        raise FileNotFoundError(f"Registered proposal file not found: {resolved_proposal}")

    proposal_file = resolved_proposal

    try:
        proposal_bytes = proposal_file.read_bytes()
    except Exception as exc:
        raise RuntimeError(f"Failed to read proposal file {proposal_file}: {exc}") from exc

    actual_sha = hashlib.sha256(proposal_bytes).hexdigest()
    if actual_sha.lower() != expected_sha.strip().lower():
        raise ValueError(
            f"T28 proposal SHA256 mismatch for {proposal_file}: "
            f"registered {expected_sha.strip().lower()} != actual {actual_sha.lower()}"
        )

    try:
        proposal_json = json.loads(proposal_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse proposal JSON in {proposal_file}: {exc}") from exc

    if not isinstance(proposal_json, dict):
        raise ValueError(f"Proposal JSON in {proposal_file} must be an object")

    budget = proposal_json.get("budget")
    if budget is None or not isinstance(budget, dict):
        raise ValueError(f"Proposal {proposal_file} missing or null 'budget' object")

    # 1. calibration_views = budget.view_accounting.charge_per_complete_run
    view_accounting = budget.get("view_accounting")
    if view_accounting is None or not isinstance(view_accounting, dict):
        raise ValueError(f"Proposal {proposal_file} missing or null 'budget.view_accounting' object")

    calibration_views = view_accounting.get("charge_per_complete_run")
    if calibration_views is None or not isinstance(calibration_views, int) or calibration_views <= 0:
        raise ValueError(
            f"Proposal {proposal_file} missing, null, or invalid 'budget.view_accounting.charge_per_complete_run' "
            f"(got {calibration_views})"
        )

    # 2. cumulative_wall_cap_s = budget.cumulative_wall_seconds_max
    cumulative_wall_cap_s = budget.get("cumulative_wall_seconds_max")
    if cumulative_wall_cap_s is None or not isinstance(cumulative_wall_cap_s, (int, float)) or cumulative_wall_cap_s <= 0:
        raise ValueError(
            f"Proposal {proposal_file} missing, null, or invalid 'budget.cumulative_wall_seconds_max' "
            f"(got {cumulative_wall_cap_s})"
        )

    # 3. run_wall_budget_s = budget.wall_accounting.approved_run_wall_budget_seconds
    wall_accounting = budget.get("wall_accounting")
    if wall_accounting is None or not isinstance(wall_accounting, dict):
        raise ValueError(f"Proposal {proposal_file} missing or null 'budget.wall_accounting' object")

    run_wall_budget_s = wall_accounting.get("approved_run_wall_budget_seconds")
    if run_wall_budget_s is None or not isinstance(run_wall_budget_s, (int, float)) or run_wall_budget_s <= 0:
        raise ValueError(
            f"Proposal {proposal_file} missing, null, or invalid "
            f"'budget.wall_accounting.approved_run_wall_budget_seconds' (got {run_wall_budget_s})"
        )

    return T28RegistrationInfo(
        calibration_views=calibration_views,
        cumulative_wall_cap_s=float(cumulative_wall_cap_s),
        run_wall_budget_s=float(run_wall_budget_s),
        proposal_path=str(proposal_file),
        sha256=actual_sha,
        is_registered=True,
    )


def get_registered_calibration_views(
    registered_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> int:
    """Return calibration views derived from registered proposal, or default 18."""
    return load_t28_registration(registered_path, repo_root).calibration_views


def get_registered_cumulative_wall_cap_s(
    registered_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> float:
    """Return cumulative wall seconds cap derived from registered proposal, or default 1200.0."""
    return load_t28_registration(registered_path, repo_root).cumulative_wall_cap_s


def get_registered_run_wall_budget_s(
    registered_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> float | None:
    """Return approved single-run wall budget seconds from registered proposal, or None."""
    return load_t28_registration(registered_path, repo_root).run_wall_budget_s
