"""Build intermediate cli.py variants by removing per-line blocks from the working-tree version."""
import subprocess, sys
REPO = "/Users/mac/AinerWorkFlow/AinerZero"
final = open(f"{REPO}/src/ainerzero/cli.py", encoding="utf-8").read()
head = subprocess.run(["git", "-C", REPO, "show", "HEAD:src/ainerzero/cli.py"], capture_output=True, text=True, check=True).stdout

def cut(text, start, end, include_end=False):
    i = text.index(start)
    assert text.count(start) == 1, start
    j = text.index(end, i + len(start))
    if include_end:
        j += len(end)
    return text[:i] + text[j:], text[i:j]

BLOCKS = {}
def remove(text, line):
    t = text
    if line == "lockbusy":
        cls = 'class WorkerLockBusy(RuntimeError):\n    """Another worker already holds the project-wide shared lock."""\n\n\n'
        assert t.count(cls) == 1
        t = t.replace(cls, "")
        new = 'raise WorkerLockBusy("A worker is already running in this project") from exc'
        assert t.count(new) == 1
        t = t.replace(new, 'raise RuntimeError("A worker is already running in this project") from exc')
        return t
    if line == "s1":
        t, _ = cut(t, '    s1 = commands.add_parser(\n', '    e1 = commands.add_parser(\n') if '    e1 = commands.add_parser(\n' in t else cut(t, '    s1 = commands.add_parser(\n', '    teacher = commands.add_parser(\n') if '    teacher = commands.add_parser(\n' in t else cut(t, '    s1 = commands.add_parser(\n', '    args = parser.parse_args(argv)\n')
        t, _ = cut(t, '        if args.command == "s1-phase1":\n', '            return exit_code\n', include_end=True)
        return t
    if line == "e1":
        nxt = '    teacher = commands.add_parser(\n' if '    teacher = commands.add_parser(\n' in t else '    args = parser.parse_args(argv)\n'
        t, _ = cut(t, '    e1 = commands.add_parser(\n', nxt)
        t, _ = cut(t, '        if args.command == "e1-phase2":\n', '            return exit_code\n', include_end=True)
        return t
    if line == "teacher":
        t, _ = cut(t, '    teacher = commands.add_parser(\n', '    args = parser.parse_args(argv)\n')
        t, _ = cut(t, '        if args.command in ("teacher-benchmark", "teacher-da3"):\n', '            return exit_code\n', include_end=True)
        return t
    raise KeyError(line)

ALL = ["lockbusy", "e1", "s1", "teacher"]
def variant(included):
    t = final
    for line in ALL:
        if line not in included:
            t = remove(t, line)
    return t

if __name__ == "__main__":
    # consistency: removing everything must give HEAD exactly; including everything gives final
    assert variant(set()) == head, "removing all blocks does not reproduce HEAD"
    assert variant(set(ALL)) == final
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, inc in [("e1", {"lockbusy", "e1"}), ("e1s1", {"lockbusy", "e1", "s1"}), ("all", set(ALL))]:
        open(f"{out}/cli_{name}.py", "w", encoding="utf-8").write(variant(inc))
    print("ok: HEAD reproduced; variants written")
