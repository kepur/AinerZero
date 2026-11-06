"""stat snapshot of live trees: path -> (type, size, mtime_ns, ctime_ns, ino). Read-only."""
import json, os, sys
root, out = sys.argv[1], sys.argv[2]
trees = sys.argv[3:]
snap = {}
for t in trees:
    base = os.path.join(root, t)
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        for name in [dirpath] + [os.path.join(dirpath, n) for n in dirnames + filenames]:
            try:
                st = os.lstat(name)
            except FileNotFoundError:
                continue
            kind = "d" if os.path.isdir(name) and not os.path.islink(name) else ("l" if os.path.islink(name) else "f")
            snap[os.path.relpath(name, root)] = [kind, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]
json.dump(snap, open(out, "w"))
print(len(snap), "entries")
