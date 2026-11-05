"""Compare every path of a commit with a verified isolated tree (blob hashes; symlink targets)."""
import subprocess, os, sys, collections, json
REPO = "/Users/mac/AinerWorkFlow/AinerZero"
T = sys.argv[1]; REV = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
out = subprocess.run(['git','-C',REPO,'-c','core.quotepath=off','ls-tree','-r','-z',REV],capture_output=True,text=True,check=True).stdout
entries = {}
for rec in out.split('\0'):
    if rec:
        meta, path = rec.split('\t', 1); mode, typ, sha = meta.split(); entries[path] = (mode, sha)
links = {p: v for p, v in entries.items() if v[0] == '120000'}
files = [p for p, v in entries.items() if v[0] != '120000']
mism, missing = [], []
for i in range(0, len(files), 2000):
    part = files[i:i+2000]
    chunk = [p for p in part if os.path.isfile(os.path.join(T, p)) and not os.path.islink(os.path.join(T, p))]
    missing += [p for p in part if p not in set(chunk)]
    r = subprocess.run(['git','-C',REPO,'hash-object','--no-filters','--stdin-paths'], input='\n'.join(os.path.join(T,p) for p in chunk)+'\n', capture_output=True, text=True, check=True).stdout.split()
    mism += [p for p, h in zip(chunk, r) if h != entries[p][1]]
cat = subprocess.run(['git','-C',REPO,'cat-file','--batch'], input=''.join(v[1]+'\n' for v in links.values()).encode(), capture_output=True, check=True).stdout
pos, lmism = 0, []
for p, (mode, sha) in links.items():
    nl = cat.index(b'\n', pos); size = int(cat[pos:nl].split()[2]); target = cat[nl+1:nl+1+size].decode(); pos = nl + 1 + size + 1
    tp = os.path.join(T, p)
    if not os.path.islink(tp) or os.readlink(tp) != target: lmism.append(p)
extra = []
for root, dirs, fs in os.walk(T):
    for f in fs + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
        rel = os.path.relpath(os.path.join(root, f), T)
        if rel not in entries: extra.append(rel)
res = {"rev": subprocess.run(['git','-C',REPO,'rev-parse',REV],capture_output=True,text=True).stdout.strip(), "tree": T,
       "files": len(files), "file_mismatches": mism, "missing_in_tree": missing, "symlinks": len(links), "symlink_mismatches": lmism,
       "extra_in_tree_count": len(extra), "extra_in_tree_by_dir": collections.Counter('/'.join(e.split('/')[:2]) for e in extra).most_common(15)}
print(json.dumps(res, ensure_ascii=False, indent=1))
