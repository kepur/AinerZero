import subprocess, sys, shutil, os
from pathlib import Path
M = Path(sys.argv[1]); S5 = M / "src/ainerzero/v9/experiments/s5"
muts = {
 "M1_no_registered_guard": ("world.py", "    if namespace in REGISTERED and not allow_registered:", "    if False and namespace in REGISTERED and not allow_registered:"),
 "M2_da2_frames_no_f": ("world.py", "            f=DA2_F,\n", ""),
 "M3_r2_counts": ("labels.py", "        grid[az_bin, d_bin] = 1", "        grid[az_bin, d_bin] += 1"),
 "M4_r2_wrong_frame": ("labels.py", "    t = clip_idx * 16 + 15\n    return _occupancy_grid", "    t = clip_idx * 16 + 14\n    return _occupancy_grid"),
 "M5_ray_distance_depth": ("render.py", "        z = t * cos_off                                     # [W]", "        z = t * 1.0                                         # [W]"),
 "M6_student_clip_offset": ("world.py", "    for t in range(start_t, start_t + FRAMES_PER_CLIP):", "    for t in range(start_t + 1, start_t + 1 + FRAMES_PER_CLIP):"),
 "M7_r1_sky_zero": ("labels.py", "    logd_arr = np.full((16, GRID_H, GRID_W), np.nan, dtype=np.float32)", "    logd_arr = np.zeros((16, GRID_H, GRID_W), dtype=np.float32)"),
 "M8_r3_no_offset": ("labels.py", "    t = clip_idx * 16 + 15 + 8", "    t = clip_idx * 16 + 15"),
 "M9_min_visible_1": ("labels.py", "MIN_VISIBLE_PIXELS: int = 4", "MIN_VISIBLE_PIXELS: int = 1"),
 "M10_azimuth_flip": ("labels.py", "        rel_ang = (ang - heading + math.pi) % (2.0 * math.pi) - math.pi\n        az_bin = _compute_azimuth_bin(rel_ang)\n\n        grid", "        rel_ang = -((ang - heading + math.pi) % (2.0 * math.pi) - math.pi)\n        az_bin = _compute_azimuth_bin(rel_ang)\n\n        grid"),
 "M11_texture_off_default": ("render.py", "    texture: bool = True,", "    texture: bool = False,"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
chk = subprocess.run([sys.executable, "-c", "import ainerzero,sys;print(ainerzero.__file__)"], cwd=M, env=env, capture_output=True, text=True)
print("imports from:", chk.stdout.strip())
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text()
    assert orig.count(a) == 1, (name, orig.count(a))
    p.write_text(orig.replace(a, b))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/v9/experiments/", "-rf"], cwd=M, env=env, capture_output=True, text=True)
    last = [l.split("::")[-1][:60] for l in r.stdout.splitlines() if l.startswith("FAILED")] + [l for l in r.stdout.splitlines() if " passed" in l][-1:]
    print(f"{name}: {'KILLED' if r.returncode != 0 else 'SURVIVED'}  {last}")
    p.write_text(orig)
