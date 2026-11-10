"""S4 第一阶段新代码的隔离副本变异。作者自测，不替代非作者复核。

每个变异：从开始时取的快照复制 src/ainerzero、tests/conftest.py、S4 测试、pyproject.toml 到新的临时目录，
改一处文本（要求恰好出现一次、改完能过语法检查），PYTHONPATH 指向副本，在副本里跑 S4 测试（含 MLX 原生测试）。
结果写 results-<tag>.json。用法：mutate.py <tag> [--cpu] [变异名 ...]
--cpu：只跑纯 CPU 的测试文件，跳过 learned_mlx.py 的变异（MLX 训练在跑时用，不与它并行使用 MLX）。
"""
import ast, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
S4 = "src/ainerzero/v9/experiments/s4/"
FI, ME, MO, LM, AS = S4 + "filter.py", S4 + "metrics.py", S4 + "models.py", S4 + "learned_mlx.py", S4 + "assign.py"
AN = S4 + "analysis.py"
TESTS = ["tests/v9/experiments/test_s4_world.py", "tests/v9/experiments/test_s4_filter_metrics.py", "tests/v9/experiments/test_s4_analysis.py",
         "tests/v9/experiments/test_s4_learned_mlx.py"]
EXTRA_FILES: list[str] = ["tests/v9/experiments/data/s4_coincident_case.npz"]
CPU_ONLY = "--cpu" in sys.argv

M = [
    # filter.py
    ("fi_gate_no_dt", FI, "cfg.gate_base + cfg.gate_grow * W.DT * (t - last[c])", "cfg.gate_base + cfg.gate_grow * (t - last[c])"),
    ("fi_no_update", FI, "                _update(P, V, k, z[r], cfg, rng)\n", "                pass\n"),
    ("fi_q_swap", FI, "rng.normal(0.0, cfg.q_pos, P2.shape)", "rng.normal(0.0, cfg.q_vel, P2.shape)"),
    ("fi_var_ignored", FI, "if len(out) == 4:", "if False:"),
    ("fi_last_not_updated", FI, "                _update(P, V, k, z[r], cfg, rng)\n                last[k] = t\n", "                _update(P, V, k, z[r], cfg, rng)\n"),
    ("fi_obs_var", FI, "np.eye(2) * cfg.obs_sigma ** 2", "np.eye(2) * cfg.obs_sigma"),
    ("fi_prior_speed", FI, "spd = rng.uniform(*cfg.speed, M)", "spd = rng.uniform(0.0, 1.0, M)"),
    ("fi_assoc_first_member", FI, "    mu = P.mean(0)\n", "    mu = P[0]\n"),
    ("fi_gate_strict", FI, "if dist[r, c] <= cfg.gate_base", "if dist[r, c] < cfg.gate_base"),
    ("fi_members", FI, "members: int = 32", "members: int = 16"),
    ("fi_diag_no_truth", FI, "                P[:, k], V[:, k] = s.positions[truth], s.velocities[truth]\n", "                pass\n"),
    # metrics.py
    ("me_reid_same_step", ME, 'at[e["a"]][e["k"]] == at[e["b"]][e["k"]]', 'at[e["a"]][e["k"]] == at[e["a"]][e["k"]]'),
    ("me_graze_margin", ME, "GRAZE_MARGIN = 0.3", "GRAZE_MARGIN = 0.2"),
    ("me_graze_includes_coll", ME, "+ GRAZE_MARGIN} - coll)", "+ GRAZE_MARGIN})"),
    ("me_graze_start_positions", ME, "d = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1)", "d = np.linalg.norm(s.positions[:, None] - s.positions[None], axis=-1)"),
    ("me_tail", ME, "tail = (1 - LEVEL) / 2", "tail = 1 - LEVEL"),
    ("me_bonf_no_m", ME, "[tail / m, 1 - tail / m]", "[tail, 1 - tail]"),
    ("me_C_denominator", ME, "return (x - b) / (p - b)", "return (x - b) / (p - x)"),
    ("me_idf1_max_cost", ME, "hungarian(-cnt)", "hungarian(cnt)"),
    ("me_D_flip", ME, "return 1 - x_coll / b_coll", "return 1 - b_coll / x_coll"),
    ("me_HF_means", ME, "return (x_graze / n_graze) / (b_coll / n_coll)", "return x_graze / b_coll"),
    ("me_boot_seed", ME, "BOOT_SEED, LEVEL = 10_000, 20261110, 0.95", "BOOT_SEED, LEVEL = 10_000, 20261111, 0.95"),
    # models.py
    ("mo_bounce_disks", MO, "p, v, _ = W.physics(P, V, pillars, disks=False)", "p, v, _ = W.physics(P, V, pillars)"),
    ("mo_cv_no_move", MO, "return P + V * W.DT, V.copy()", "return P.copy(), V.copy()"),
    # assign.py
    ("as_pad_small", AS, "c = np.full((n, n), cost.max() + 1.0)", "c = np.full((n, n), 0.0)"),
    ("as_strict_better", AS, "better = free & (cur < minv[1:])", "better = free & (cur <= minv[1:])"),
    # learned_mlx.py
    ("lm_no_mask", LM, "scal = (m * mask).sum(2)", "scal = m.sum(2)"),
    ("lm_canon_raw_dv", LM, "x = mx.concatenate([dist, dist - 2 * RADIUS, dv_loc], -1)", "x = mx.concatenate([dist, dist - 2 * RADIUS, dv], -1)"),
    ("lm_vec_not_rotated", LM, "vec = ((w[..., 0:1] * e + w[..., 1:2] * eperp) * mask).sum(2)", "vec = (w * mask).sum(2)"),
    ("lm_ind_interacts", LM, 'self.interact = arm != "L-ind"', "self.interact = True"),
    ("lm_analytic_rule", LM, "        v_next = v + o[..., 2:4]\n", "        v_next = mx.where(mx.array(True), v + o[..., 2:4], v)\n"),
    ("lm_drop_ignored", LM, "keep = rng.random(len(pos)) >= P_DROP", "keep = rng.random(len(pos)) >= 0.0"),
    ("lm_hidden_share", LM, "hidden = rng.random(len(pos)) < P_HIDDEN", "hidden = rng.random(len(pos)) < 1 - P_HIDDEN"),
    ("lm_exact_never", LM, "exact=rng.random() < exact_frac)", "exact=False)"),
    ("lm_pool_wrong_pillars", LM, "pillars = tuple(map(tuple, episodes[e].pillars))", "pillars = tuple(map(tuple, episodes[0].pillars))"),
    ("lm_contact_one_sided", LM, "contact[b, i, j] = contact[b, j, i] = 1.0", "contact[b, i, j] = 1.0"),
    ("lm_label_extra_step", LM, "            if k > 1:\n                p, v, _ = physics(p, v, pillars)", "            if k > 0:\n                p, v, _ = physics(p, v, pillars)"),
    ("lm_sigma_target_now", LM, "s, nxt = ep.steps[t], ep.steps[t + 1]", "s, nxt = ep.steps[t], ep.steps[t]"),
    ("lm_sigma_hidden_noise", LM, "vel = s.velocities + rng.normal(0, VISIBLE_SIGMA[1], s.velocities.shape)", "vel = s.velocities + rng.normal(0, HIDDEN_SIGMA[1], s.velocities.shape)"),
    ("lm_sigma_unfrozen", LM, "        model.freeze()\n", ""),
    ("lm_sigma_no_stopgrad", LM, "self.var1(mx.stop_gradient(z))", "self.var1(z)"),
    ("lm_wrapper_var_swap", LM, "out = out + (var[..., 0:2], var[..., 2:4])", "out = out + (var[..., 2:4], var[..., 0:2])"),
    ("lm_contact_weight", LM, "CONTACT_WEIGHT = 0.1", "CONTACT_WEIGHT = 0.0"),
    ("lm_no_long_rollout", LM, "ROLLOUT = (1, 5, 10)", "ROLLOUT = (1,)"),
    ("lm_msg_radius", LM, "MSG_RADIUS = 1.5", "MSG_RADIUS = 2.0"),
    ("lm_pos_scale", LM, "p_next = p + v * DT + o[..., 0:2] * P_SCALE", "p_next = p + o[..., 0:2] * P_SCALE"),
    ("lm_ghost_vel", LM, "        vel = np.vstack([vel, vel[k]])\n", "        vel = np.vstack([vel, np.zeros(2)])\n"),
    ("lm_batch_uniform_bucket_INFO", LM, "j = int(rng.choice(len(ns), p=w))", "j = int(rng.choice(len(ns)))"),
    ("lm_no_oversample", LM, 'share, near = (COLL_SHARE, NEAR_SHARE) if arm != "L-int-s" else (0.0, 0.0)', "share, near = 0.0, 0.0"),
    ("lm_oversample_sigma", LM, 'share, near = (COLL_SHARE, NEAR_SHARE) if arm != "L-int-s" else (0.0, 0.0)', "share, near = COLL_SHARE, NEAR_SHARE"),
    ("lm_near_not_passed", LM, "coll_share=share, near_share=near), 1):", "coll_share=share), 1):"),
    ("lm_near_includes_contact", LM, "near = (d.min((1, 2)) < NEAR_GAP) & ~hit", "near = d.min((1, 2)) < NEAR_GAP"),
    ("lm_near_start_positions", LM, '    p1 = e["p1"]\n', '    p1 = e["p"]\n'),
    ("lm_near_gap", LM, "NEAR_GAP = 2 * RADIUS + 0.3", "NEAR_GAP = 2 * RADIUS + 0.6"),
    ("lm_near_from_all", LM, "            parts.append(nr[rng.integers(0, len(nr), q)])\n", "            parts.append(rng.integers(0, int(sizes[j]), q))\n"),
    ("lm_shares_unchecked", LM, "    if k + q > batch:\n", "    if False:\n"),
    ("lm_no_clip", LM, "        grads, norm = optim.clip_grad_norm(grads, max_norm=CLIP)\n", "        norm = mx.array(0.0)\n"),
    ("lm_eps_dir", LM, "EPS_DIR = 0.01", "EPS_DIR = 1e-6"),
    ("lm_nan_after_update", LM, "        mx.eval(loss, norm)\n        if not (np.isfinite(float(loss)) and np.isfinite(float(norm))):", "        mx.eval(loss, norm)\n        if False:"),
    # metrics.py: resamples with an undefined ratio must withhold the interval
    ("me_boot_drop_nonfinite", ME, "if not np.isfinite(point) or len(boot) < n_boot:", "if not np.isfinite(point) or len(boot) == 0:"),
    # analysis.py
    ("an_seed_first_only", AN, 'for s in SEEDS], axis=0) if r["events"] else np.zeros(0)', 'for s in SEEDS[:1]], axis=0) if r["events"] else np.zeros(0)'),
    ("an_coll_mask_off", AN, 'mask = np.array([e[3] == 1 if collision else True for e in r["events"]], dtype=bool)', 'mask = np.array([True for e in r["events"]], dtype=bool)'),
    ("an_HD_threshold", AN, '"HD": {"D": 0.8, "D_low": 0.7}', '"HD": {"D": 0.7, "D_low": 0.7}'),
    ("an_neg_control_ignored", AN, '    if not neg["passed"]:\n', "    if False:\n"),
    ("an_valid_ignored", AN, "    if not valid:\n", "    if False:\n"),
    ("an_floor_order", AN, 'acc["E-CV"] < acc["E-B"] < acc["E-P"]', 'acc["E-CV"] <= acc["E-P"]'),
    ("an_sample_band", AN, "SAMPLE_BAND = 0.25", "SAMPLE_BAND = 0.9"),
    ("an_filter_seed_shared", AN, 'return W.derive_seed(ns, "filter", w, seed, variant)', 'return W.derive_seed(ns, "filter", w, 0, variant)'),
    ("an_HD_no_lower", AN, 'd["ci_low"] is not None and d["ci_low"] > T["HD"]["D_low"]', 'd["ci_low"] is not None'),
    ("an_H1_no_lower", AN, 'c["ci_low"] is not None and c["ci_low"] > T["H1"]["C_low"]', 'c["ci_low"] is not None'),
    ("an_H3_no_lower", AN, 'cx["ci_low"] is not None and cx["ci_low"] > T["H3"]["C_low"]', 'cx["ci_low"] is not None'),
    ("an_HDx_no_lower", AN, 'dx["ci_low"] is not None and dx["ci_low"] > T["HD-x"]["D_low"]', 'dx["ci_low"] is not None'),
    ("an_H2_no_lower", AN, 'h2["ci_low"] is not None and h2["ci_low"] > T["H2"]["diff_low"]', 'h2["ci_low"] is not None'),
    ("an_HF_upper_ignored", AN, 'hf["ci_high"] is not None and hf["ci_high"] <= T["HF"]["ratio_high"]', 'hf["ci_high"] is not None'),
    ("an_HDx_uses_main", AN, 'dx, hfx = D_of(extrap, "L-int"), HF_of(extrap, "L-int")', 'dx, hfx = D_of(main, "L-int"), HF_of(main, "L-int")'),
    ("an_H3_uses_main", AN, 'c, cx = C_of(main, "L-int"), C_of(extrap, "L-int")', 'c, cx = C_of(main, "L-int"), C_of(main, "L-int")'),
    ("an_HDx_graze_ignored", AN, 'hfx["value"] is not None and hfx["value"] <= T["HD-x"]["ratio"]', 'hfx["value"] is not None'),
    ("an_dyn_seed_first", AN, 'return np.array([np.mean([r["dyn"][f"{arm}#{s}"][field] for s in seeds]) for r in records], dtype=np.float64)', 'return np.array([r["dyn"][f"{arm}#{seeds[0]}"][field] for r in records], dtype=np.float64)'),
    ("an_events_window", AN, '"events": [[e["k"], e["a"], e["b"], int(e["collision"])] for e in events]', '"events": [[e["k"], e["a"], e["b"], 1] for e in events]'),
    ("lm_oversample_from_all", LM, "            parts.append(h[rng.integers(0, len(h), k)])\n", "            parts.append(rng.integers(0, int(sizes[j]), k))\n"),
]


def copy_tree(dst, src=REPO):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "tests/v9/experiments").mkdir(parents=True)
    shutil.copy2(src / "tests/conftest.py", dst / "tests/conftest.py")
    for t in TESTS + EXTRA_FILES:
        (dst / t).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / t, dst / t)
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")


def pytest(dst, files):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    native = [] if CPU_ONLY else ["--native-mlx"]
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *native, *files], cwd=dst, env=env, capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout[-600:]


def main():
    tag = sys.argv[1]
    only = set(a for a in sys.argv[2:] if a != "--cpu")
    tests = [t for t in TESTS if not (CPU_ONLY and t.endswith("test_s4_learned_mlx.py"))]
    results = []
    with tempfile.TemporaryDirectory(prefix="s4p1-mut-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base)
        # the copy must import itself, not the live tree
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PYTHONPATH"] = str(base / "src")
        where = subprocess.run([sys.executable, "-c", "import ainerzero.v9.experiments.s4.filter as f; print(f.__file__)"], cwd=base, env=env, capture_output=True, text=True).stdout.strip()
        assert where.startswith(str(base)), where
        rc, tail = pytest(base, tests)
        print("unmutated", rc, flush=True)
        if rc != 0:
            raise SystemExit("unmutated copy fails:\n" + tail)
        for name, path, old, new in M:
            if (only and name not in only) or (CPU_ONLY and path == LM):
                continue
            d = Path(tmp) / name
            copy_tree(d, base)
            f = d / path
            text = f.read_text(encoding="utf-8")
            if text.count(old) != 1:
                results.append({"name": name, "status": "stale", "count": text.count(old)})
                print(name, "STALE", flush=True)
                continue
            text = text.replace(old, new)
            ast.parse(text)
            f.write_text(text, encoding="utf-8")
            t0 = time.monotonic()
            rc, tail = pytest(d, tests)
            status = "killed" if rc != 0 else "SURVIVED"
            results.append({"name": name, "file": path, "status": status, "seconds": round(time.monotonic() - t0, 1), "tail": tail[-300:]})
            print(name, status, round(time.monotonic() - t0, 1), flush=True)
            shutil.rmtree(d)
    (OUT / f"results-{tag}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("killed", sum(r["status"] == "killed" for r in results), "of", len(results))


if __name__ == "__main__":
    main()
