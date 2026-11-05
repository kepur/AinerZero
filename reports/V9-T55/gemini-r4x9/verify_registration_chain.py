#!/usr/bin/env python3
"""Verification of registration chain:
1. reports/V9-T28/REGISTERED.json sha256 matches proposal.json actual SHA256.
2. t28_registration.load_t28_registration() returns 50 / 1440 / 120.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "registration_chain.log"

sys.path.insert(0, str(REPO / "src"))

PROPOSAL_PATH = REPO / "reports" / "V9-T28" / "r2" / "proposal.json"
REGISTERED_PATH = REPO / "reports" / "V9-T28" / "REGISTERED.json"


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    log = []
    log.append("=== Verification of T28 Registration Chain ===")

    # 1. Proposal SHA vs REGISTERED.json
    prop_bytes = PROPOSAL_PATH.read_bytes()
    actual_prop_sha = sha256_of_bytes(prop_bytes)
    log.append(f"Actual proposal.json SHA256: {actual_prop_sha}")

    reg_data = json.loads(REGISTERED_PATH.read_text(encoding="utf-8"))
    declared_prop_sha = reg_data["sha256"]
    log.append(f"Declared SHA256 in REGISTERED.json: {declared_prop_sha}")

    assert actual_prop_sha == declared_prop_sha, (
        f"Proposal SHA mismatch! Actual: {actual_prop_sha}, Declared: {declared_prop_sha}"
    )
    log.append("Check passed: REGISTERED.json sha256 matches actual proposal.json SHA256.")

    log.append("\nREGISTERED.json contents:")
    log.append(json.dumps(reg_data, indent=2, ensure_ascii=False))

    # 2. Call t28_registration.load_t28_registration()
    from ainerzero.v9.teachers import t28_registration
    reg_info = t28_registration.load_t28_registration()
    log.append(f"\nLoaded T28RegistrationInfo:\n  {reg_info}")

    views = reg_info.calibration_views
    cum_wall_cap = reg_info.cumulative_wall_cap_s
    run_budget = reg_info.run_wall_budget_s

    log.append(f"  calibration_views: {views} (Expected: 50)")
    log.append(f"  cumulative_wall_cap_s: {cum_wall_cap} (Expected: 1440.0)")
    log.append(f"  run_wall_budget_s: {run_budget} (Expected: 120.0)")

    assert views == 50, f"calibration_views != 50 ({views})"
    assert cum_wall_cap == 1440.0 or cum_wall_cap == 1440, f"cumulative_wall_cap_s != 1440 ({cum_wall_cap})"
    assert run_budget == 120.0 or run_budget == 120, f"run_wall_budget_s != 120 ({run_budget})"
    assert reg_info.is_registered is True, "is_registered is not True"
    assert reg_info.sha256 == actual_prop_sha, "Registration sha256 mismatch with actual proposal"

    log.append("\nREGISTRATION CHAIN VERIFICATION STATUS: PASS")
    out_str = "\n".join(log)
    print(out_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(out_str + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
