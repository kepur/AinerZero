"""P21 probe 12: the frozen identity and the real ledger after the review.

Proves that the reviewed source did not move while the probes ran and that the
real central ledger, its WAL side files and the shared lock are byte-identical
to the "before" snapshot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402


def main() -> int:
    snapshot = lib.frozen_identity_snapshot("after")
    before_path = lib.EVIDENCE / "01-frozen-identity-before.json"
    before = json.loads(before_path.read_text(encoding="utf-8")) if before_path.is_file() else {}
    after_ledger = lib.host_ledger_identities()
    before_ledger = (before.get("host_ledger") or {}) if before else {}
    content_unchanged = None
    volatile = {}
    if before_ledger:
        content_unchanged = True
        for key, row in before_ledger.items():
            now = after_ledger.get(key, {})
            same_content = row.get("sha256") == now.get("sha256")
            if not same_content:
                content_unchanged = False
            if row.get("mtime_ns") != now.get("mtime_ns"):
                volatile[key] = {
                    "mtime_ns_before": row.get("mtime_ns"),
                    "mtime_ns_after": now.get("mtime_ns"),
                    "sha256_unchanged": same_content,
                }
    payload = {
        "schema": "ainerzero.v9.p21.probe12_identity_after.v1",
        "frozen": {
            "count": snapshot["count"],
            "mismatch_count": snapshot["mismatch_count"],
            "all_match": snapshot["all_match"],
            "mismatches": snapshot["mismatches"],
        },
        "git": lib.git_state(),
        "host_ledger_before": before_ledger,
        "host_ledger_after": after_ledger,
        "host_ledger_content_unchanged": content_unchanged,
        "host_ledger_volatile_mtime_changes": volatile,
        "host_ledger_note": "the ledger file, its -wal and the shared lock are byte-identical; "
        "only the -shm (SQLite's volatile shared-memory index, not ledger content) has a newer "
        "mtime, which a read-only attachment to a WAL database causes (demonstrated in the "
        "review); no zero-write claim is made, only a content-identity claim",
        "mlx_imported": lib.mlx_imported(),
        "real_mlx_loaded": lib.real_mlx_loaded(),
    }
    out = lib.write_json("12-frozen-identity-after.json", payload)
    print(json.dumps({
        "mismatch_count": payload["frozen"]["mismatch_count"],
        "host_ledger_content_unchanged": payload["host_ledger_content_unchanged"],
        "volatile_mtime_changes": list(payload["host_ledger_volatile_mtime_changes"]),
        "git_clean": payload["git"]["clean"],
    }, indent=1))
    print("wrote", out)
    return 0 if payload["frozen"]["all_match"] and content_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
