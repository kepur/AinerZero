import hashlib, json, sys, os
ROOT = "/Users/mac/AinerWorkFlow/AinerZero"
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

inputs = json.load(open("/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-morning/P18-r3-review-inputs.json"))
rows, bad = [], 0
for e in inputs["files"]:
    p = e["path"]
    ok_exists = os.path.exists(p)
    cur = sha(p) if ok_exists else None
    exp = e.get("sha256")
    if exp is None:
        status = "NO_EXPECTED(inherited)"
        match = None
    elif not ok_exists:
        status = "MISSING"; match = False
    else:
        match = (cur == exp); status = "OK" if match else "MISMATCH"
    if match is False: bad += 1
    rows.append((os.path.relpath(p, ROOT), status, (cur or "")[:12], (exp or "")[:12]))
print(f"review-inputs entries: {len(rows)}  mismatches/missing: {bad}")
for r in rows:
    print(f"  {r[1]:<22} {r[2]:<14} exp={r[3]:<14} {r[0]}")

# frozen source files named in r3 REPORT section 2 (expected prefixes)
frozen = {
  "evaluation.py": "92d8de4a6551", "runtime.py": "a99346522f29", "metrics.py": "e1c36b657794",
  "worker.py": "4174187473cd", "commands.py": "48b3fb48cf4b", "spec.py": "beedc9482b8d",
  "prereg.py": "d441b84e1c52",
}
print("--- frozen r5 snapshot sources (r3 report section 2 table) ---")
found = {}
for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "artifacts/v9/s1")):
    for fn in filenames:
        if fn in frozen:
            found.setdefault(fn, []).append(os.path.join(dirpath, fn))
for fn, exp in frozen.items():
    paths = found.get(fn, [])
    if not paths:
        print(f"  NOT_FOUND {fn}"); continue
    for p in paths:
        cur = sha(p)[:12]
        print(f"  {'OK' if cur==exp else 'MISMATCH':<10} {cur} exp={exp}  {os.path.relpath(p, ROOT)}")

# other frozen artifacts named in r3 report section 2
others = {
  "artifacts/v9/s1/phase1/r5/pre_registration.json": "895bb3676cd3",
  "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/dataset_manifest.json": "5cbd65225c84",
  "artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/truth/development.jsonl": "76b986495229",
}
print("--- other frozen artifacts ---")
for p, exp in others.items():
    fp = os.path.join(ROOT, p)
    if not os.path.exists(fp):
        print(f"  NOT_FOUND {p}"); continue
    cur = sha(fp)[:12]
    print(f"  {'OK' if cur==exp else 'MISMATCH':<10} {cur} exp={exp}  {p}")

# r1/r2 report files named in r3 report section 2
r1r2 = {
  "reports/V9-P18/REPORT.md": "0b33e29fbd2e", "reports/V9-P18/metrics.json": "71bc8c38eb27",
  "reports/V9-P18/r2/REPORT.md": "86a13488b1f7", "reports/V9-P18/r2/metrics.json": "ad32d483508a",
}
print("--- r1/r2 named files ---")
for p, exp in r1r2.items():
    fp = os.path.join(ROOT, p)
    if not os.path.exists(fp):
        print(f"  NOT_FOUND {p}"); continue
    cur = sha(fp)[:12]
    print(f"  {'OK' if cur==exp else 'MISMATCH':<10} {cur} exp={exp}  {p}")
