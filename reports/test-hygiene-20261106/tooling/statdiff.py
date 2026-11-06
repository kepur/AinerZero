import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
added = sorted(set(b) - set(a)); removed = sorted(set(a) - set(b))
changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
print("added", len(added), "removed", len(removed), "changed", len(changed))
for k in added[:50]: print("  +", k, b[k])
for k in removed[:50]: print("  -", k, a[k])
for k in changed[:80]:
    fields = [n for n, x, y in zip(("type","size","mtime","ctime","ino"), a[k], b[k]) if x != y]
    print("  ~", k, fields, a[k][1], "->", b[k][1])
