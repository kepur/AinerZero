"""P14 reviewer: record mtime/size/sha256 of the real files P14 must not touch.

The list is fixed and identical for the before and after runs, so a plain
``diff`` of the two outputs is the evidence.  The before file was taken the
moment the task was claimed; this script produced the after file and is kept so
the snapshot is reproducible.

Usage:  python reports/V9-P14/harness/real_files_snapshot.py <out.txt>
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
FILES = (
    "RESEARCH_LOG.md",
    "artifacts/locks/m0-worker.lock",
    "artifacts/v9/s1/phase1/control.sqlite3",
    "artifacts/v9/s1/phase1/pre_registration.json",
    "src/ainerzero/v9/experiments/s1/commands.py",
    "src/ainerzero/v9/experiments/s1/worker.py",
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out = Path(sys.argv[1])
    lines: list[str] = []
    for rel in FILES:
        p = REAL / rel
        if not p.exists():
            lines.append(f"{rel} MISSING")
            continue
        st = p.stat()
        lines.append(f"{rel} {int(st.st_mtime)} {st.st_size}")
        lines.append(f"{digest(p)}  {rel}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
