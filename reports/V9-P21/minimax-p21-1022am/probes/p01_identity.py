"""P21 probe 01: frozen identity + host ledger identity snapshot (before).

Read-only.  Records the SHA256 of every file the coordinator froze for this
review, the git state, and the byte identity of the real central ledger and its
WAL side files so that any later side effect can be detected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402


def main() -> int:
    snapshot = lib.frozen_identity_snapshot("before")
    payload = {
        "schema": "ainerzero.v9.p21.probe01_identity_before.v1",
        "frozen": {
            "count": snapshot["count"],
            "mismatch_count": snapshot["mismatch_count"],
            "all_match": snapshot["all_match"],
            "mismatches": snapshot["mismatches"],
            "rows": snapshot["rows"],
        },
        "git": lib.git_state(),
        "host_ledger": lib.host_ledger_identities(),
        "mlx_imported": lib.mlx_imported(),
    }
    out = lib.write_json("01-frozen-identity-before.json", payload)
    print(json.dumps({
        "frozen_count": payload["frozen"]["count"],
        "mismatch_count": payload["frozen"]["mismatch_count"],
        "git_clean": payload["git"]["clean"],
        "host_ledger": payload["host_ledger"],
        "mlx_imported": payload["mlx_imported"],
        "wrote": str(out),
    }, indent=1))
    return 0 if payload["frozen"]["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
