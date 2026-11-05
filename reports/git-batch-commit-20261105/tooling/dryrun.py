import os, collections, subprocess, sys
from batches import *
seq, rep = all_batches()
seen = collections.Counter()
for n, d, fs in seq:
    sz = sum(os.path.getsize(os.path.join(REPO, f)) for f in fs if not os.path.islink(os.path.join(REPO,f)))
    links = [f for f in fs if os.path.islink(os.path.join(REPO, f))]
    big = [f for f in fs if not os.path.islink(os.path.join(REPO,f)) and os.path.getsize(os.path.join(REPO, f)) > 1_000_000]
    print(f"{n:14s} files={len(fs):6d} size={sz/1e6:7.2f}MB symlinks={len(links)} >1MB={len(big)} {big[:3]}")
    for f in fs: seen[f] += 1
dup = [f for f, c in seen.items() if c > 1]
print("duplicates:", len(dup), dup[:5])
ex = collections.Counter(); exs = collections.Counter()
for n, (k, e) in rep.items():
    for f, r in e:
        ex[r] += 1; exs[r] += 0 if r == 'symlink' else os.path.getsize(os.path.join(REPO, f))
print("excluded report files:", {r: (ex[r], round(exs[r]/1e6,1)) for r in ex})
allf = set(files_for(["."]))
rest = sorted(allf - set(seen) - set(f for n,(k,e) in rep.items() for f,r in e) - {"src/ainerzero/cli.py"})
c = collections.Counter(f.split('/')[0] if f.split('/')[0] in ('.tmp','envs','.workbuddy-ai') else f for f in rest)
print("not in any batch:", sum(c.values())); print(c.most_common(40))
