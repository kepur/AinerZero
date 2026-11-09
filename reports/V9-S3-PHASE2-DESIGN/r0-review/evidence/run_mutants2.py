"""P208 的 12 个变异 + 5 个新变异，核对移植后的项目测试是否与原校验器同等强度。"""
import hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path
W = Path(sys.argv[1]); R = Path("/Users/mac/AinerWorkFlow/AinerZero"); PY = str(R / ".venv/bin/python")
S3 = "src/ainerzero/v9/experiments/s3/"
M = [
 ("m01_a0_reads_oracle", S3+"arms_mlx.py", '        m = model.project(mx.zeros_like(z_q))\n    elif arm == "A1":', '        m = model.project(model.encode(b["obs"][ep, b["oracle"]]))\n    elif arm == "A1":'),
 ("m02_a3_eval_uses_answer_target", S3+"arms_mlx.py", 'top = mx.argmax(mx.where(mask, s, mx.array(-1e9)), axis=-1)', 'top = mx.argmax(mx.where(mask, target, mx.array(-1e9)), axis=-1)'),
 ("m03_a1_sees_future", S3+"arms_mlx.py", 'h = model.gru(model.encode(b["obs"]))', 'h = model.gru(model.encode(b["obs"])[:, ::-1, :])[:, ::-1, :]'),
 ("m04_a2_top1_is_oracle", S3+"batching.py", 'top = ranked[0][0].t', 'top = int(e["prev_visit_t"])'),
 ("m05_n_control_equals_a2", S3+"batching.py", 'shuffled.append(perm[top])', 'shuffled.append(top)'),
 ("m06_cand_feat_leaks_swapped", S3+"batching.py", '(t - r.t) / float(spec.T),', 'float(bool(e["swapped"])),'),
 ("m07_cand_pool_reads_future", S3+"batching.py", 'pool = build_multi_cue_candidate_pool(store, t, lam=lam)', 'pool = build_multi_cue_candidate_pool(store, t, lam=lam, gap=-5)'),
 ("m08_bootstrap_event_unit", S3+"analysis.py", 'uniq, inv = np.unique(episode_ids, return_inverse=True)', 'uniq, inv = np.unique(np.arange(len(episode_ids)), return_inverse=True)'),
 ("m09_ci_sign_flip", S3+"analysis.py", 'delta = (sum_a[idx].sum(1) - sum_b[idx].sum(1)) / tot', 'delta = (sum_b[idx].sum(1) - sum_a[idx].sum(1)) / tot'),
 ("m10_h2_threshold_drift", S3+"analysis.py", 'H2_MIN_DELTA = 0.05', 'H2_MIN_DELTA = -0.10'),
 ("m11_floor_gate_always_true", S3+"analysis.py", '"floor_A0": primary["A0"] <= FLOOR,', '"floor_A0": True,'),
 ("m12_gate_or_not_and", S3+"analysis.py", 'return bool(boot["delta"] >= min_delta and boot["ci_low"] > 0.0)', 'return bool(boot["delta"] >= min_delta or boot["ci_low"] > 0.0)'),
 ("m13_pose_absolute_coord", S3+"cues.py", 'return abs(q.est_pose[0] - r.est_pose[0]) + abs(q.est_pose[1] - r.est_pose[1])', 'return abs(q.est_pose[0] - r.est_pose[0]) + abs(q.est_pose[1] - r.est_pose[1]) + abs(r.est_pose[0]) * 1e-3'),
 ("m14_store_reads_truth", S3+"store.py", '    t = int(step_data["t"])\n', '    t = int(step_data["t"]); _ = step_data["truth"]\n'),
 ("m15_a3_soft_weights_use_answer", S3+"arms_mlx.py", 'w = mx.exp(_masked_log_softmax(mx.stop_gradient(s), mask))', 'w = target'),
 ("m16_upper_gate_drift", S3+"analysis.py", 'UPPER_MIN = 0.90', 'UPPER_MIN = 0.50'),
 ("m17_h3_threshold_drift", S3+"analysis.py", 'H3_MAX_DROP = 0.05', 'H3_MAX_DROP = 0.50'),
]
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
base = W / "base"; out = W / "out"; mdir = W / "mutants"; mdir.mkdir(exist_ok=True)
files = sorted(set(m[1] for m in M)); before = {f: sha(base / f) for f in files}
def run(cmd, cwd, env):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=500)
    return p.returncode, p.stdout + p.stderr
summary = []
for name, rel, old, new in [("m00_unmutated_control", None, None, None)] + M:
    t0 = time.time(); d = mdir / name
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(base, d)
    if rel:
        p = d / rel; s = p.read_text(encoding="utf-8"); assert s.count(old) == 1, (name, s.count(old))
        p.write_text(s.replace(old, new), encoding="utf-8"); assert sha(p) != before[rel]
    env = {**os.environ, "PYTHONPATH": str(d / "src"), "PYTHONDONTWRITEBYTECODE": "1", "REVIEW_ROOT": str(d), "PREREG_PATH": str(d / "reports/V9-S3-DESIGN/PREREG-r1.json")}
    rc, txt = run([PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider", "--tb=line"], d, env)
    fails = sorted(l.split()[1] for l in txt.splitlines() if l.startswith("FAILED"))
    contract = [f.split("::")[-1] for f in fails if "test_s3_isolation_contract" in f]
    older = [f.split("::")[-1] for f in fails if "test_s3_isolation_contract" not in f]
    rc2, txt2 = run([PY, str(W / "review_harness.py"), str(out / f"{name}.harness.json")], W, env)
    hf = sorted(k for k, v in json.loads((out / f"{name}.harness.json").read_text()).items() if not v["pass"])
    info = {"mutant": name, "file": rel, "contract_failed": contract, "other_project_failed": older, "project_exit": rc, "harness_failed": hf, "harness_exit": rc2, "seconds": round(time.time() - t0, 1)}
    (out / f"{name}.txt").write_text(f"### {name} file={rel}\n--- OLD\n{old}\n--- NEW\n{new}\n\n### project exit={rc}\n{txt}\n\n### harness exit={rc2}\n{txt2}\n", encoding="utf-8")
    summary.append(info); print(json.dumps({k: info[k] for k in ("mutant", "contract_failed", "other_project_failed", "harness_failed")}, ensure_ascii=False)[:420], flush=True)
    shutil.rmtree(d)
assert before == {f: sha(base / f) for f in files}
(out / "contract_mutations.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("BASE_UNCHANGED True", flush=True)
