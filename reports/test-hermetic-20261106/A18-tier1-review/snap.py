import os, sys, json
root = "/Users/mac/AinerWorkFlow/AinerZero/artifacts"
out = {}
for dp, dns, fns in os.walk(root, followlinks=False):
    for n in [dp] + [os.path.join(dp, f) for f in fns] + [os.path.join(dp, d) for d in dns if os.path.islink(os.path.join(dp, d))]:
        try:
            st = os.lstat(n); out[n] = [st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino]
        except OSError: pass
json.dump(out, open(sys.argv[1], "w"))
print(len(out))
