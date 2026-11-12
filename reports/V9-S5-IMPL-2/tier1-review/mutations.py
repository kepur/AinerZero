import subprocess, sys, os
from pathlib import Path
M = Path(sys.argv[1]); S5 = M / "src/ainerzero/v9/experiments/s5"
T = ["tests/v9/experiments/test_s5_tokens.py", "tests/v9/experiments/test_s5_student_mlx.py"]
muts = {
 "N1_rlt_anchor_compare": ("tokens.py", "        retained, run_lengths, positions, restoration, rate = rlt_frame_dropping(\n            chunk, tau\n        )",
   "        retained, run_lengths, positions, restoration, rate = rlt_frame_dropping(\n            chunk, tau * 3.0\n        )"),
 "N2_patch_hw_swap": ("tokens.py", "    transposed = reshaped.transpose(0, 1, 3, 5, 2, 4, 6, 7)", "    transposed = reshaped.transpose(0, 1, 5, 3, 2, 4, 6, 7)"),
 "N3_no_attn_mask_sparse": ("student.py", "            curr_compact = block(curr_compact, mask=attn_mask)", "            curr_compact = block(curr_compact, mask=None)"),
 "N4_ssi_no_shift": ("losses.py", "        t_shift = t_mean - s * p_mean\n        p_aligned = s * p_flat + t_shift\n        l1_err", "        t_shift = 0.0 * (t_mean - s * p_mean)\n        p_aligned = s * p_flat + t_shift\n        l1_err"),
 "N5_align_no_stopgrad": ("losses.py", "    teacher_sg = mx.stop_gradient(teacher)", "    teacher_sg = teacher"),
 "N6_gridhead_ignore_mask": ("heads.py", "        pooled = self.pool(q, tokens, tokens, mask=attn_mask).squeeze(1)", "        pooled = self.pool(q, tokens, tokens, mask=None).squeeze(1)"),
 "N7_r1_frame_order": ("heads.py", "        pred_logd = logd_2f.transpose(0, 1, 4, 2, 3).reshape(B, 16, 14, 14)", "        pred_logd = logd_2f.transpose(0, 4, 1, 2, 3).reshape(B, 16, 14, 14)"),
 "N8_depthhead_transpose": ("heads.py", "        grid = out.transpose(0, 1, 2, 4, 3, 5).reshape(B, 8, 56, 56)", "        grid = out.transpose(0, 1, 2, 3, 4, 5).reshape(B, 8, 56, 56)"),
 "N9_no_runlen_embed": ("student.py", "                x = x + self.run_len_embed[rl]", "                x = x + 0.0 * self.run_len_embed[rl]"),
 "N10_restoration_prev_frame": ("tokens.py", "                    if k_arr[b, t, h, w]:\n                        anchor_vec = arr[b, t, h, w]", "                    anchor_vec = arr[b, t - 1, h, w] if t > 0 else arr[b, t, h, w]\n                    if k_arr[b, t, h, w]:\n                        pass"),
}
env = dict(os.environ, PYTHONPATH=str(M / "src"))
print("imports from:", subprocess.run([sys.executable, "-c", "import ainerzero;print(ainerzero.__file__)"], cwd=M, env=env, capture_output=True, text=True).stdout.strip())
def run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf", *T], cwd=M, env=env, capture_output=True, text=True)
    fails = [l.split("::")[-1][:55] for l in r.stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")]
    tail = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l or "error" in l][-1:]
    return r.returncode, fails, tail
rc, f, t = run(); print("BASELINE", rc, f, t)
for name, (fn, a, b) in muts.items():
    p = S5 / fn; orig = p.read_text()
    assert orig.count(a) == 1, (name, orig.count(a))
    p.write_text(orig.replace(a, b))
    rc, f, t = run()
    print(f"{name}: {'KILLED' if rc != 0 else 'SURVIVED'} {f} {t}", flush=True)
    p.write_text(orig)
