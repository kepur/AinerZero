import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mut_lib import run_group
W = Path(sys.argv[1]); RUN = "reports/V9-S3-PHASE2/run_phase2.py"; T = ["tests/v9/experiments/test_s3p2_runner_guards_native.py"]
M = [
 ("p01_consume_before_claim_report", RUN, [('        GD.claim_report(report)\n        ROOT.mkdir(parents=True, exist_ok=True)\n', '        ROOT.mkdir(parents=True, exist_ok=True)\n'), ("""        run_id = f"{a.stage}-{a.use_id or 'final'}"\n""", """        GD.claim_report(report)\n        run_id = f"{a.stage}-{a.use_id or 'final'}"\n""")], T),
 ("p02_manifest_check_off", RUN, [('bad = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])', 'bad = GD.check_loaded_modules(REPO, pre["manifest"])')], T),
 ("p03_loaded_check_off", RUN, [('bad = GD.check_manifest(REPO, pre["manifest"]) + GD.check_loaded_modules(REPO, pre["manifest"])', 'bad = GD.check_manifest(REPO, pre["manifest"])')], T),
 ("p04_version_check_off", RUN, [('    if versions != pre["third_party"]:\n', '    if False:\n')], T),
 ("p05_git_check_off", RUN, [('    if dirty:\n', '    if False:\n')], T),
 ("p06_pycache_check_off", RUN, [('    GD.require_pycache_prefix()\n', '')], T),
 ("p07_namespace_check_off", RUN, [('        GD.check_stage_namespace(a.stage, ns_eval, **G.NAMESPACES)\n', '')], T),
 ("p08_smoke_reads_dev", RUN, [('"smoke": {"ns": "probe",', '"smoke": {"ns": "dev",')], T),
 ("p09_max_uses_overridden", RUN, [('max_uses=pre["dev_max_uses"]', 'max_uses=99')], T),
 ("p10_capacity_ignored", RUN, [('capacity = pre["h3_capacity"] if pre else 64', 'capacity = 64')], T),
 ("p11_a1_dropped", RUN, [('with_a1 = a.stage != "probe"', 'with_a1 = False')], T),
 ("p12_n_not_past_only", RUN, [('out.append(RP.past_only_shuffle(p, N_SEED + seed))', 'out.append(p)')], T),
 ("p13_cn_not_permuted", RUN, [('buf = RP.permute_answers(buf, CN_SEED + seed)', 'pass')], T),
 ("p14_buffer_from_f2", RUN, [('buf = [tr1[j] for j in RP.buffer_indices(len(tr1), cap, BUFFER_SEED + seed)]', 'buf = [tr2[j] for j in RP.buffer_indices(len(tr2), cap, BUFFER_SEED + seed)]')], T),
 ("p15_c0_retrains_f1", RUN, [('sampler = pick(tr2, BATCH)', 'sampler = pick(tr1, BATCH)')], T),
 ("p16_8class_not_restricted", RUN, [('pred, pred_8 = L.argmax(-1), np.where(keep, L, -np.inf).argmax(-1)', 'pred, pred_8 = L.argmax(-1), L.argmax(-1)')], T),
 ("p17_late_check_off", RUN, [('            if late:\n', '            if False:\n')], T),
 ("p18_a3h_trained_soft", RUN, [('    sampled = loss_kind == "sampled"\n', '    sampled = False\n')], T),
 ("p19_eval_soft", RUN, [('logits, _ = A.forward(m, to_mx(b), hard=True)', 'logits, _ = A.forward(m, to_mx(b), hard=False)')], T),
 ("p20_f1_after_on_f2_events", RUN, [('record(cond, seed, "F1_after", per_event(m, ev1, spec.F1_TOKENS), cell)', 'record(cond, seed, "F1_after", per_event(m, ev2, spec.F2_TOKENS), cell)')], T),
 ("p21_two_seeds", RUN, [('SEEDS = (1, 2, 3)', 'SEEDS = (1, 2)')], T),
 ("p22_f1_steps_changed", RUN, [('F1_STEPS, F2_STEPS = 2000, 1000', 'F1_STEPS, F2_STEPS = 3000, 1000')], T),
 ("p23_deadline_never_checked", RUN, [('            deadline.check()\n', '            pass\n')], T),
 ("p24_joint_only_f1", RUN, [('mixed(tr1, tr2, MIX, MIX), f1s + f2s', 'mixed(tr1, tr1, MIX, MIX), f1s + f2s')], T),
 ("p25_min_sample_off", RUN, [('check_samples=a.stage != "smoke"', 'check_samples=False')], T),
 ("p26_dev_not_recorded", RUN, [('GD.consume_dev_use(lock, ROOT / "dev_uses.json", a.use_id, a.purpose, max_uses=pre["dev_max_uses"], expected_lock=LOCK)', 'pass')], T),
 ("p27_final_not_marked", RUN, [("""GD.consume_final_read(lock, ROOT / "FINAL_READ_ONCE.json", a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)""", 'pass')], T),
 ("p28_lock_after_checks", RUN, [('    with GD.RunLock(LOCK) as lock:\n        pre, pre_sha, head, versions = startup_checks(a.stage)\n', '    pre, pre_sha, head, versions = startup_checks(a.stage)\n    with GD.RunLock(LOCK) as lock:\n')], T),
 ("p29_expected_lock_tautology", RUN, [('max_uses=pre["dev_max_uses"], expected_lock=LOCK)', 'max_uses=pre["dev_max_uses"], expected_lock=lock.path)')], T),
 ("p30_eval_on_train_namespace", RUN, [('        ev1, rows1 = build(ns_eval, "", ew, ee, "F1", 20_000_000, want_rows=True)', '        ev1, rows1 = build(G.NAMESPACES["train"], "", ew, ee, "F1", 20_000_000, want_rows=True)')], T),
 ("p31_buffer_seed_shared", RUN, [('RP.buffer_indices(len(tr1), cap, BUFFER_SEED + seed)', 'RP.buffer_indices(len(tr1), cap, BUFFER_SEED)')], T),
 ("p32_opt_reset_for_f2", RUN, [('                    cell["train_seconds_f2"] = train(m, opt, sampler, f2s, seed + 1000, loss, deadline)', '                    opt = optim.Adam(learning_rate=LR)\n                    cell["train_seconds_f2"] = train(m, opt, sampler, f2s, seed + 1000, loss, deadline)')], T),
]
M.insert(0, ("p00_unmutated_control_with_stop_stub", RUN, [], T))
run_group(W, "runner", M, None, "mutations_runner.json")
