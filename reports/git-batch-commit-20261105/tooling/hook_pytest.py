"""Run pytest with an audit hook that records every LIVE-repo path opened, with its mode.

Write-mode opens (open() mode with w/a/x/+, os.open flags with WRONLY/RDWR/CREAT/TRUNC) and
sqlite3.connect calls on live paths are recorded separately so the caller can prove the
isolated run did not write to the live working tree.
"""
import atexit, json, os, signal, sys

LIVE = "/Users/mac/AinerWorkFlow/AinerZero/"
LOG = os.environ["LIVE_OPEN_LOG"]
INHERITED_SIGINT = signal.getsignal(signal.SIGINT)
if __name__ == "__main__":
    # Restore normal SIGINT handling (a background launcher may have set SIG_IGN, which makes the
    # project's SIGINT tests fail spuriously; children inherit SIG_DFL once a handler is installed).
    signal.signal(signal.SIGINT, signal.default_int_handler)

seen, writes, sqlite = set(), set(), set()
WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _live(p):
    try:
        p = os.fsdecode(p)
    except Exception:
        return None
    if p.startswith("file:"):
        p = p[5:].split("?", 1)[0]
    p = os.path.realpath(p)  # resolve symlinks so overlay reads/writes into the live tree are caught
    if p.startswith(LIVE) and "/.venv" not in p and "__pycache__" not in p:
        return p[len(LIVE):]
    return None


def hook(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        rel = _live(args[0])
        if rel is None:
            return
        seen.add(rel)
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & WFLAGS):
            writes.add(f"{rel}\tmode={mode}\tflags={flags}")
    elif event == "sqlite3.connect" and args:
        rel = _live(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else None
        if rel is not None:
            sqlite.add(os.fsdecode(args[0]).replace(LIVE, "<LIVE>/"))


def _dump():
    with open(LOG, "w", encoding="utf-8") as fh:
        json.dump({"inherited_sigint": str(INHERITED_SIGINT), "opened": sorted(seen),
                   "write_mode_opens": sorted(writes), "sqlite_connects": sorted(sqlite)},
                  fh, ensure_ascii=False, indent=0)


if __name__ == "__main__":
    # Guarded: tests that use multiprocessing "spawn" re-import this file as __mp_main__ in the
    # child; without the guard the child would re-run pytest and the parent would wait forever.
    sys.addaudithook(hook)
    atexit.register(_dump)
    import pytest  # noqa: E402
    import ainerzero  # noqa: E402

    assert ainerzero.__file__.startswith(os.environ["TREE"]), ainerzero.__file__
    sys.exit(pytest.main(sys.argv[1:]))
