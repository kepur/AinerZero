"""P21 probe 02: the host anchor is unique, cwd/env independent, checkout independent.

Two *real* source checkouts (independent copies of ``src/ainerzero``) are
resolved in their own processes, with different working directories and hostile
environment variables.  All of them must resolve to the same registered host
anchor: the same phase-1 root, the same central ledger, the same shared
``m0-worker.lock`` and the same approval log.

Read-only: nothing under ``artifacts/`` is opened for writing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

HOSTILE_ENV = {
    "AINERZERO_S1_PHASE1_ROOT": "/tmp/hostile-phase1",
    "AINERZERO_S1_LEDGER": "/tmp/hostile-ledger.sqlite3",
    "AINERZERO_PHASE1_ROOT": "/tmp/hostile-phase1-2",
    "AINERZERO_REPO_ROOT": "/tmp/hostile-repo",
    "AINERZERO_RESEARCH_LOG": "/tmp/hostile-log.md",
    "REPO_ROOT": "/tmp/hostile-repo-2",
    "PWD": "/tmp/hostile-pwd",
}

ANCHOR_KEYS = ("phase1_root", "ledger", "lock", "approval_log", "registered_host_root")


def main() -> int:
    scratch = lib.scratch_dir("p21-anchor")
    checkout_a = lib.make_checkout(scratch / "checkout-a")
    checkout_b = lib.make_checkout(scratch / "checkout-b")

    runs = []
    # 1: checkout A, its own cwd, clean env
    runs.append(
        {
            "label": "checkout-a / own cwd / clean env",
            "result": lib.checkout_anchor(checkout_a),
        }
    )
    # 2: checkout B, a foreign cwd (the scratch dir), clean env
    runs.append(
        {
            "label": "checkout-b / foreign cwd / clean env",
            "result": lib.checkout_anchor(checkout_b, cwd=scratch),
        }
    )
    # 3: checkout A, hostile environment variables
    runs.append(
        {
            "label": "checkout-a / foreign cwd / hostile env",
            "result": lib.checkout_anchor(
                checkout_a, cwd=scratch, env_extra=HOSTILE_ENV
            ),
        }
    )
    # 4: checkout B, hostile environment variables + a fake HOME
    runs.append(
        {
            "label": "checkout-b / foreign cwd / hostile env + fake HOME",
            "result": lib.checkout_anchor(
                checkout_b, cwd=scratch, env_extra={**HOSTILE_ENV, "HOME": "/tmp/hostile-home"}
            ),
        }
    )

    resolved = []
    for row in runs:
        result = row["result"]
        if not result.get("ok"):
            resolved.append(None)
            continue
        resolved.append({key: result[key] for key in ANCHOR_KEYS})

    same = len({json.dumps(item, sort_keys=True) for item in resolved if item}) == 1
    anchor_states = [row["result"].get("anchor_state", {}) for row in runs if row["result"].get("ok")]
    anchor_ok = all(state.get("status") == "ok" for state in anchor_states)

    # The constants themselves must not be derived from __file__ / cwd / env.
    from ainerzero.v9.experiments.s1 import commands, spec, worker  # noqa: E402

    constants = {
        "REGISTERED_HOST_ROOT": str(spec.REGISTERED_HOST_ROOT),
        "REPO_ROOT": str(spec.REPO_ROOT),
        "PHASE1_ROOT": str(spec.PHASE1_ROOT),
        "RESEARCH_LOG": str(spec.RESEARCH_LOG),
        "canonical_ledger_path": str(worker.canonical_ledger_path()),
        "lock_path": str(commands._lock_path()),
        "spec_file": spec.__file__,
        "registered_is_absolute_literal": str(spec.REGISTERED_HOST_ROOT)
        == "/Users/mac/AinerWorkFlow/AinerZero",
        "repo_root_equals_registered_host": str(spec.REPO_ROOT) == str(spec.REGISTERED_HOST_ROOT),
        "phase1_under_registered_host": str(spec.PHASE1_ROOT).startswith(
            str(spec.REGISTERED_HOST_ROOT)
        ),
        "approval_log_under_registered_host": str(spec.RESEARCH_LOG).startswith(
            str(spec.REGISTERED_HOST_ROOT)
        ),
        "lock_under_registered_host": str(commands._lock_path()).startswith(
            str(spec.REGISTERED_HOST_ROOT)
        ),
        "ledger_under_registered_host": str(worker.canonical_ledger_path()).startswith(
            str(spec.REGISTERED_HOST_ROOT)
        ),
    }

    # The anchor is a plain read: it must not create anything.
    before = lib.host_ledger_identities()
    state = spec.host_anchor_state()
    after = lib.host_ledger_identities()
    side_effect_free = before == after

    payload = {
        "schema": "ainerzero.v9.p21.probe02_anchor_uniqueness.v1",
        "checkouts": [str(checkout_a), str(checkout_b)],
        "checkout_source_sha256": lib.sha256_file(
            lib.REPO / "src/ainerzero/v9/experiments/s1/spec.py"
        ),
        "runs": runs,
        "resolved_anchors": resolved,
        "all_checkouts_share_one_anchor": same,
        "anchor_state_ok": anchor_ok,
        "constants": constants,
        "host_ledger_before": before,
        "host_ledger_after": after,
        "anchor_resolution_side_effect_free": side_effect_free,
        "mlx_imported": lib.mlx_imported(),
        "verdict": {
            "unique_anchor": bool(same and anchor_ok),
            "cwd_env_cannot_move_anchor": bool(
                all(
                    item
                    and item["phase1_root"]
                    == constants["PHASE1_ROOT"]
                    and item["lock"] == constants["lock_path"]
                    and item["approval_log"] == constants["RESEARCH_LOG"]
                    for item in resolved
                )
            ),
            "ledger_lock_approval_same_anchor": bool(
                constants["ledger_under_registered_host"]
                and constants["lock_under_registered_host"]
                and constants["approval_log_under_registered_host"]
            ),
        },
    }
    out = lib.write_json("02-anchor-uniqueness.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps({k: constants[k] for k in ANCHOR_KEYS if k in constants}, indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
