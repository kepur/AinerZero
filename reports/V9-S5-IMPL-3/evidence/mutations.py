import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); F = M / "src/ainerzero/v9/experiments/s5/extract_teachers.py"
muts = {
 "B1_no_div255": ("x = (clip.transpose(3, 0, 1, 2).astype(np.float32) / 255.0 - mean) / std", "x = (clip.transpose(3, 0, 1, 2).astype(np.float32) - mean) / std"),
 "B2_mean_std_bgr": ("    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32)[:, None, None, None]", "    mean = np.asarray(IMAGENET_MEAN[::-1], dtype=np.float32)[:, None, None, None]"),
 "B3_left_crop": ("    crop = np.ascontiguousarray(depth[:, DA2_CROP[0]:DA2_CROP[1]].astype(np.float32))", "    crop = np.ascontiguousarray(depth[:, 0:392].astype(np.float32))"),
 "B4_no_resume_skip": ("        if rel in ledger:\n            n_skip += 1\n            continue\n", ""),
 "B5_no_tamper_check": ("        if not p.exists() or sha256_file(p) != sha:", "        if not p.exists():"),
 "B6_no_registered_refusal": ("    if meta.get(\"partition\") in REGISTERED_PARTITIONS:", "    if False and meta.get(\"partition\") in REGISTERED_PARTITIONS:"),
 "B7_lock_after_build": ("    lock = acquire_lock(Path(lock_path))                     # lock first; nothing is written before this\n    if lock is None:\n        print(\"lock busy\", flush=True)\n        return EXIT_LOCK_BUSY\n    try:\n        fn, extra = (factories or FACTORIES)[a.teacher]()",
                         "    fn, extra = (factories or FACTORIES)[a.teacher]()\n    lock = acquire_lock(Path(lock_path))\n    if lock is None:\n        print(\"lock busy\", flush=True)\n        return EXIT_LOCK_BUSY\n    try:\n        pass"),
 "B8_bilinear_resize": ("Image.BOX)", "Image.BILINEAR)"),
 "B9_no_dtype_check": ("        if y.shape != want_shape or y.dtype != np.float16:", "        if y.shape != want_shape:"),
 "B10_skip_stray_check": ("        if dst.exists():\n            raise RuntimeError(f\"output exists but is not in the ledger: {rel}\")\n", ""),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
print("imports from:", subprocess.run([sys.executable, "-c", "import ainerzero;print(ainerzero.__file__)"], cwd=M, env=env, capture_output=True, text=True).stdout.strip())
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/test_s5_extract.py"], cwd=M, env=env, capture_output=True, text=True)
    return r.returncode, [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")], [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l][-1:]
print("BASELINE", *run())
orig = F.read_text()
for name, (a, b) in muts.items():
    assert orig.count(a) == 1, (name, orig.count(a))
    F.write_text(orig.replace(a, b))
    rc, f, t = run()
    print(f"{name}: {'KILLED' if rc else 'SURVIVED'} {f} {t}", flush=True)
    F.write_text(orig)
