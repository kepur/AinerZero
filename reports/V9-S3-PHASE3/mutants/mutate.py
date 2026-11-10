"""S3 第三阶段新代码的隔离副本变异。作者自测，不替代非作者复核。

每个变异：复制 src/ainerzero、tests/conftest.py、第三阶段测试、pyproject.toml、运行器到新的临时目录，
改一处文本（要求恰好出现一次、改完能过语法检查），PYTHONPATH 指向副本，在副本里跑测试。
先跑快的三个测试文件，没抓到再跑运行器测试。结果写 results.json。
"""
import ast, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
S3 = "src/ainerzero/v9/experiments/s3/"
PSF, PRF, ANF, RUN = S3 + "persist.py", S3 + "promotion.py", S3 + "analysis_p3.py", "reports/V9-S3-PHASE3/run_phase3.py"
VF = "reports/V9-S3-PHASE3/verify_worlds.py"
VG = "reports/V9-S3-PHASE3/verify_generation.py"
MP = "reports/V9-S3-PHASE3/make_prereg.py"
FAST = ["tests/v9/experiments/test_s3p3_persist_promotion.py", "tests/v9/experiments/test_s3p3_analysis.py", "tests/v9/experiments/test_s3p3_verify_worlds.py", "tests/v9/experiments/test_s3p3_verify_generation.py"]
SLOW = ["tests/v9/experiments/test_s3p3_runner_guards.py"]

M = [
    # persist.py
    ("ps_n_persistent", PSF, "N_PERSISTENT = 4", "N_PERSISTENT = 3"),
    ("ps_p_decoy", PSF, "P_DECOY = 0.3", "P_DECOY = 0.25"),
    ("ps_reloc_episode", PSF, "RELOCATION_EPISODE = 6", "RELOCATION_EPISODE = 5"),
    ("ps_p_relocate", PSF, "P_RELOCATE = 0.5", "P_RELOCATE = 0.4"),
    ("ps_regime_gt", PSF, "after if e >= RELOCATION_EPISODE else before", "after if e > RELOCATION_EPISODE else before"),
    ("ps_no_decoy_shown", PSF, "shown[c] = _other(tokens, regime[c], er) if decoy[c] else regime[c]", "shown[c] = regime[c]"),
    ("ps_persistent_swaps", PSF, "            swap[c] = NEVER\n", "            swap[c] = er.randint(*SWAP_WINDOW)\n"),
    ("ps_volatile_not_banned", PSF, "separated_cells(free, N_VOLATILE, er, banned=persistent)", "separated_cells(free, N_VOLATILE, er, banned=())"),
    ("ps_guard_off", PSF, "if namespace in REGISTERED and not allow_registered:", "if False:"),
    ("ps_first_arrival_last", PSF, "                out.append((c, int(s[\"t\"])))\n                break\n", "                out.append((c, int(s[\"t\"])))\n"),
    ("ps_spacing_strict", PSF, ">= min_dist for x in chosen + banned", "> min_dist for x in chosen + banned"),
    ("ps_other_any", PSF, "return rng.choice([k for k in tokens if k != than])", "return rng.choice(list(tokens))"),
    # promotion.py
    ("pr_dmax", PRF, "D_MAX = 5.0", "D_MAX = 4.0"),
    ("pr_simmin", PRF, "SIM_MIN = 1.0", "SIM_MIN = 0.8"),
    ("pr_minvotes", PRF, "MIN_VOTES = 2", "MIN_VOTES = 3"),
    ("pr_d_strict", PRF, "(d <= D_MAX) & (sim >= SIM_MIN)", "(d < D_MAX) & (sim >= SIM_MIN)"),
    ("pr_tie_last", PRF, "    j = int(np.argmax(s))\n", "    j = int(len(s) - 1 - np.argmax(s[::-1]))\n"),
    ("pr_tie_flag_off", PRF, "return j, bool((s == s[j]).sum() > 1)", "return j, False"),
    ("pr_dwell_no_reset", PRF, "        else:\n            prev = None\n    return out", "        else:\n            pass\n    return out"),
    ("pr_pick_oldest", PRF, "key=lambda k: (counts[k], last[k])", "key=lambda k: (counts[k], -last[k])"),
    ("pr_after_includes_last_EQUIV", PRF, "votes[last + 1 :]", "votes[last:]"),
    ("pr_norollback_ignored", PRF, "    if not rollback:\n        return slow\n", ""),
    ("pr_vote_last_token", PRF, "item.votes.append((episode, top[0][0]))", "item.votes.append((episode, list(per[j])[-1]))"),
    ("pr_vote_tie_flag_off", PRF, "int(len(top) > 1 and top[0][1] == top[1][1])", "0"),
    ("pr_version_always", PRF, "        if changed:\n            items = self.version_items()", "        if True:\n            items = self.version_items()"),
    ("pr_version_no_votes", PRF, "list(it.anchor_ter), [list(v) for v in it.votes]] for it in self.items if it.slow is not None]", "list(it.anchor_ter), []] for it in self.items if it.slow is not None]"),
    ("pr_version_no_anchor", PRF, "[[it.id, it.slow, list(it.anchor_xy), list(it.anchor_ter),", "[[it.id, it.slow, [0.0, 0.0], list(it.anchor_ter),"),
    ("pr_match_ignores_slow_only", PRF, "if (it.slow is not None or not slow_only)]", "if True]"),
    ("pr_snapshot_tie_last", PRF, "if best_score is None or score > best_score:", "if best_score is None or score >= best_score:"),
    ("pr_chain_no_hash", PRF, "        if v[\"hash\"] != version_hash(v[\"parent\"], v[\"episode\"], v[\"items\"]):\n            bad.append(f\"version {i}: hash does not recompute\")\n", ""),
    ("pr_restore_drops_votes", PRF, "[(int(e), int(k)) for e, k in votes]", "[]"),
    ("pr_hash_without_parent", PRF, "_canonical({\"parent\": parent, \"episode\": episode,", "_canonical({\"parent\": None, \"episode\": episode,"),
    ("pr_truth_first_token", PRF, "self.votes.setdefault(c, []).append(per[c].most_common(1)[0][0])", "self.votes.setdefault(c, []).append(next(iter(per[c])))"),
    ("pr_mode_oldest", PRF, "    return _pick(list(cnt), cnt, list(votes))", "    return max(cnt, key=lambda k: (cnt[k], -list(votes).index(k)))"),
    ("pr_members_off", PRF, "            self.items[j].members.append(tag)\n", ""),
    # analysis_p3.py
    ("an_tie_oldest", ANF, "+ TIE * R.gtime(idx)", "- TIE * R.gtime(idx)"),
    ("an_alpha_sign", ANF, "score = score - alpha * (R.ep[qi] - R.ep[idx])", "score = score + alpha * (R.ep[qi] - R.ep[idx])"),
    ("an_eligible_ignored", ANF, "    if eligible_only:\n        if not ok.any():", "    if False:\n        if not ok.any():"),
    ("an_fast_gap", ANF, "max(t - GAP + 1, 0)", "max(t - GAP + 2, 0)"),
    ("an_unified_is_fast", ANF, "np.concatenate([np.arange(0, R.start[e]), fast_pool(R, e, t)])", "fast_pool(R, e, t)"),
    ("an_latest_oldest", ANF, "m[int(np.argmax(R.gtime(m)))]", "m[int(np.argmin(R.gtime(m)))]"),
    ("an_offset_y_only", ANF, "xy[R.ep == e] += (dx, dy)", "xy[R.ep == e] += (dx, 0)"),
    ("an_perm_identity", ANF, "\"GP\": perm.get(g, g)", "\"GP\": g"),
    ("an_g_never_slow", ANF, "g = latest if g_slow is None else g_slow", "g = latest"),
    ("an_mode_slow_only", ANF, "j_any = G.match(R.xy[qi], R.terrain[qi], slow_only=False)", "j_any = G.match(R.xy[qi], R.terrain[qi], slow_only=True)"),
    ("an_sr_no_gate", ANF, "                f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)\n                at_cell", "                f = top1(R, fast_pool(R, e, t), qi)\n                at_cell"),
    ("an_first_ok_const", ANF, "first_ok=int(len(own) > 0 and int(R.t[own[0]]) == t)", "first_ok=1"),
    ("an_relocated_any_episode", ANF, "relocated=int(e >= PS.RELOCATION_EPISODE and c in seq.relocated)", "relocated=int(c in seq.relocated)"),
    ("an_tok_before_after", ANF, "tok_before=seq.before[c], tok_after=seq.after[c]", "tok_before=seq.before[c], tok_after=seq.before[c]"),
    ("an_queries_from_two", ANF, "        if e >= 1:\n", "        if e >= 2:\n"),
    ("an_fast_unswapped_too", ANF, "if ev[\"bucket\"] != spec.BUCKET_LONG or not ev[\"swapped\"]:", "if ev[\"bucket\"] != spec.BUCKET_LONG:"),
    ("an_fast_g_unified", ANF, "            g = top1(R, fast_pool(R, e, t), qi)\n", "            g = top1(R, unified_pool(R, e, t), qi)\n"),
    ("an_u0_past_le", ANF, "R.ep[u[\"U0\"]] < e)", "R.ep[u[\"U0\"]] <= e)"),
    ("an_lookahead_L", ANF, "        op = np.array(past, dtype=np.int64)\n", "        op = np.array(past + [s0 + i for i in PR.dwell_starts(R.xy[s0:s1], R.token[s0:s1])], dtype=np.int64)\n"),
    ("an_query_version_gnr", ANF, "\"version\": G.head", "\"version\": GNR.head"),
    ("an_snapshot_check_off", ANF, "q[\"terrain\"]) != q[\"slow\"]]", "q[\"terrain\"]) != q[\"slow\"] and False]"),
    ("an_replay_check_off", ANF, "for k in range(len(checkpoints) - 1):", "for k in range(0):"),
    ("an_stable_includes_relocated", ANF, "\"decoy_stable\": q & (ev[\"decoy\"] == 1) & (ev[\"relocated\"] == 0),", "\"decoy_stable\": q & (ev[\"decoy\"] == 1),"),
    ("an_fast_e1_all", ANF, "\"fast_e1\": fast & (ev[\"episode\"] >= 1),", "\"fast_e1\": fast,"),
    ("an_event_bootstrap", ANF, "    boot = d_w[draws].sum(1) / n_w[draws].sum(1)\n", "    boot = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(1)\n"),
    ("an_level_90", ANF, "BOOT_N, BOOT_SEED, LEVEL = 10_000, 20261110, 0.95", "BOOT_N, BOOT_SEED, LEVEL = 10_000, 20261110, 0.90"),
    ("an_bonf_no_m", ANF, "np.quantile(boot, [tail / m, 1 - tail / m])", "np.quantile(boot, [tail, 1 - tail])"),
    ("an_alpha_u1", ANF, "\"U1\": 1.0", "\"U1\": 1.5"),
    ("an_cmp_d3", ANF, "(\"D3_G_minus_L\", \"decoy_stable\", \"G\", \"L\")", "(\"D3_G_minus_L\", \"decoy_stable\", \"G\", \"GNR\")"),
    ("an_cmp_d4", ANF, "(\"D4_G_minus_GNR\", \"relocated\", \"G\", \"GNR\")", "(\"D4_G_minus_GNR\", \"relocated\", \"G\", \"L\")"),
    ("an_cmp_d1", ANF, "(\"D1_G_minus_Gperm_decoy\", \"decoy\", \"G\", \"GP\")", "(\"D1_G_minus_Gperm_decoy\", \"decoy\", \"G\", \"C\")"),
    ("an_k1_always", ANF, "\"passed\": bool(chain == 0 and", "\"passed\": bool(True and"),
    ("an_k2_ignores_external", ANF, "external is not None and external.get(\"passed\") is True", "True"),
    ("an_k3_no_checkpoint_req", ANF, " and all(lg[\"checks\"][\"n_checkpoints\"] > 1 for lg in logs)", ""),
    ("an_k4_no_decoy", ANF, "\"decoy_iff_shown_differs\": bool(((ev[\"shown\"][q] != ev[\"answer\"][q]) == (ev[\"decoy\"][q] == 1)).all()),", "\"decoy_iff_shown_differs\": True,"),
    ("an_k4_no_stable", ANF, "\"stable_answer_is_episode0_value\": bool((ev[\"answer\"][stable] == ev[\"tok_before\"][stable]).all()),", "\"stable_answer_is_episode0_value\": True,"),
    ("an_k4_reloc_no_differ", ANF, " and (ev[\"tok_after\"][reloc] != ev[\"tok_before\"][reloc]).all()),", "),"),
    ("an_k4_no_first", ANF, "\"query_is_first_arrival\": bool((ev[\"first_ok\"][q] == 1).all()),", "\"query_is_first_arrival\": True,"),
    ("an_k5_band", ANF, "\"relocated\": 0.21}", "\"relocated\": 0.30}"),
    ("an_k5_no_upper", ANF, "band[k][0] <= have[k] <= band[k][1]", "band[k][0] <= have[k]"),
    ("an_valid_always", ANF, "    out[\"valid\"] = all(v[\"passed\"] for v in out.values() if isinstance(v, dict))", "    out[\"valid\"] = True"),
    ("an_recovery_ge", ANF, "if first is None and row[\"G\"] > row[\"C\"]:", "if first is None and row[\"G\"] >= row[\"C\"]:"),
    # run_phase3.py
    ("run_registered_always", RUN, "registered=a.stage in (\"dev\", \"final\")", "registered=True"),
    ("run_no_stage_check", RUN, "        GD.check_stage_namespace(a.stage, ns, **A.NAMESPACES)\n", ""),
    ("run_no_late_check", RUN, "        if pre:\n            late =", "        if False:\n            late ="),
    ("run_no_min_samples", RUN, "stage=a.stage if a.stage != \"smoke\" else None", "stage=None"),
    ("run_not_isolated_ok", RUN, "    if not sys.flags.isolated:", "    if False:"),
    ("run_no_pycache_check", RUN, "    GD.require_fresh_pycache(STARTED)\n", ""),
    ("run_ledger_before_report", RUN, "        GD.claim_report(report)\n        out.mkdir(parents=True)\n        try:\n", "        out.mkdir(parents=True)\n        try:\n"),
    ("run_no_git_check", RUN, "    if dirty:\n        raise", "    if False:\n        raise"),
    ("run_skip_verifier", RUN, "        k2 = independent_check(VERIFY, worlds, deadline=deadline)\n", "        k2 = {\"passed\": True, \"worlds\": cfg[\"worlds\"]}\n"),
    ("run_verifier_not_isolated", RUN, "[sys.executable, \"-I\", str(script), *map(str, args)]", "[sys.executable, str(script), *map(str, args)]"),
    ("run_offsets_dropped", RUN, "external=k2, external_gen=k2b, offsets=off)", "external=k2, external_gen=k2b, offsets=None)"),
    ("run_n_worlds_wrong", RUN, "n_worlds=cfg[\"worlds\"]", "n_worlds=100"),
    # verify_worlds.py
    ("vf_no_hash", VF, "        if vhash(v[\"parent\"], v[\"episode\"], v[\"items\"]) != v[\"hash\"]:", "        if False:"),
    ("vf_no_parent", VF, "        if v[\"parent\"] != parent:", "        if False:"),
    ("vf_min_votes", VF, "D_MAX, SCALE, LAM, MIN_VOTES, T = 5.0, 49.0, 1.0, 2, 360", "D_MAX, SCALE, LAM, MIN_VOTES, T = 5.0, 49.0, 1.0, 1, 360"),
    ("vf_no_rebuild", VF, "    if [v[\"hash\"] for v in rebuilt] != [v[\"hash\"] for v in versions]:", "    if False:"),
    ("vf_no_reanswer", VF, "if L != q[\"pred_L\"] or G != q[\"pred_G\"]:", "if False:"),
    ("vf_no_in_force", VF, " or in_force[-1][\"hash\"] != q[\"version\"]", ""),
    ("vf_passed_always", VF, "\"passed\": bool(n_w > 0 and n_q > 0 and not problems)", "\"passed\": True"),
    ("vf_rule_no_rollback", VF, "    return pick(ok, after, votes) if ok else slow", "    return slow"),
    ("vf_place_strict", VF, "(d <= D_MAX and sim >= 1.0)", "(d < D_MAX and sim >= 1.0)"),
    ("vf_tie_last", VF, "if ok and (top is None or s > top):", "if ok and (top is None or s >= top):"),
    ("vf_vote_last", VF, "items[j][3].append([e, per[j].most_common(1)[0][0]])", "items[j][3].append([e, list(per[j])[-1]])"),
    ("vf_no_anchor_check", VF, "if old[2] != axy or old[3] != ater:", "if False:"),
    ("vf_no_disappear", VF, "            if iid not in cur:", "            if False:"),
    ("vf_no_replace_check", VF, "if toks[last + 1:].count(tok) < MIN_VOTES:", "if False:"),
    ("vf_no_vote_order", VF, "if eps != sorted(set(eps)) or (eps and eps[-1] > v[\"episode\"]):", "if False:"),
    # r1 review: the reviewer's survivors, against the current code
    ("rv_pred_G_decoupled", ANF, '"C": shown, "L": latest, "G": g, "GNR":', '"C": shown, "L": latest, "G": (shown if e >= 9 else g), "GNR":'),
    ("rv_gt_no_rollback", ANF, "truth_store = PR.TruthKeyedStore(rollback=True)", "truth_store = PR.TruthKeyedStore(rollback=False)"),
    ("rv_lt_fallback_latest", ANF, "if len(at_cell) else shown", "if len(at_cell) else latest"),
    ("rv_mixed_ge1", ANF, "for m in it.members}) > 1 for it in store.items)", "for m in it.members}) >= 1 for it in store.items)"),
    ("rv_several_slow_ge1", ANF, "sum(on.count(c) > 1 for c in persistent)", "sum(on.count(c) >= 1 for c in persistent)"),
    ("rv_k3_versions_only", ANF, "if json.loads(json.dumps(s.state())) != final_state:", 'if json.loads(json.dumps(s.state()))["versions"] != final_state["versions"]:'),
    ("rv_u0past_all_fast", ANF, '"D2_U0_won_by_past": rate(ev, s["fast_e1"], "u0_past"),', '"D2_U0_won_by_past": rate(ev, s["fast"], "u0_past"),'),
    ("rv_gnr_rollback", ANF, "GNR = PR.PromotionStore(rollback=False)", "GNR = PR.PromotionStore(rollback=True)"),
    ("rv_query_tie_all", ANF, 'rate(ev, s["query"] & (ev["g_slow"] == 1), "query_tie")', 'rate(ev, s["query"], "query_tie")'),
    ("rv_fast_sr_no_gate", ANF, "            f = top1(R, fast_pool(R, e, t), qi, eligible_only=True)\n            if f is not None:", "            f = top1(R, fast_pool(R, e, t), qi)\n            if f is not None:"),
    ("rv_vf_no_query_count", VF, '"passed": bool(n_w > 0 and n_q > 0 and not problems)', '"passed": bool(n_w > 0 and not problems)'),
    ("rv_run_offsets_k0", RUN, "ck, _ = A.analyse_world(seq, offset=k, full=False)", "ck, _ = A.analyse_world(seq, offset=0, full=False)"),
    # r2: counts, K2b, K6 and the runner
    ("an_k2_no_counts", ANF, "    counts_ok = external is not None and external.get(\"worlds\") == n_worlds and external.get(\"queries\") == n_q\n", "    counts_ok = True\n"),
    ("an_k2b_passed_only", ANF, "gen_ok = (external_gen is not None and external_gen.get(\"passed\") is True and external_gen.get(\"worlds\") == n_worlds", "gen_ok = (external_gen is not None and external_gen.get(\"passed\") is True or external_gen.get(\"worlds\") == n_worlds"),
    ("an_k2b_no_fast_count", ANF, " and external_gen.get(\"fast_events\") == int(s[\"fast\"].sum()))", ")"),
    ("an_k6_always", ANF, "return {\"passed\": bool(ok_q and ok_f and worlds == sorted(set(ev[\"world\"].tolist())) and len(event_q) > 0),", "return {\"passed\": True,"),
    ("an_k6_no_fast", ANF, "bool(ok_q and ok_f and worlds", "bool(ok_q and worlds"),
    ("an_k6_no_world_set", ANF, " and worlds == sorted(set(ev[\"world\"].tolist()))", ""),
    ("an_k6_no_pred_G", ANF, "x[\"relocated\"], x[\"pred_G\"], x[\"pred_L\"]) for lg in logs for x in lg[\"queries\"]]", "x[\"relocated\"], x[\"pred_L\"]) for lg in logs for x in lg[\"queries\"]]"),
    ("an_k6_not_in_valid", ANF, "    out[\"K6_events_match_log\"] = log_linkage(ev, logs)\n", "    out[\"K6_events_match_log\"] = dict(log_linkage(ev, logs), passed=True)\n"),
    ("an_k5_fast_wider", ANF, "SAMPLE_BAND = {\"fast\": 0.07,", "SAMPLE_BAND = {\"fast\": 0.10,"),
    ("an_log_no_fast", ANF, "            fast_events.append([e, t, int(ev[\"answer\"])])\n", ""),
    ("an_log_answer_shown", ANF, "\"shown\": shown, \"answer\": answer, \"decoy\": int(ep.decoy[c]),", "\"shown\": shown, \"answer\": shown, \"decoy\": int(ep.decoy[c]),"),
    ("vg_no_obs", VG, "    if lg[\"observations\"] != obs:", "    if False:"),
    ("vg_no_queries", VG, "    if logged != queries:", "    if False:"),
    ("vg_no_fast", VG, "    if lg[\"fast_events\"] != fast:", "    if False:"),
    ("vg_no_seed", VG, "    if lg.get(\"world_seed\") != seq.world_seed or lg.get(\"layout_sha256\") != seq.layout_sha256:", "    if False:"),
    ("vg_no_order", VG, "    if worlds != list(range(len(worlds))):", "    if False:"),
    ("vg_forbidden_off", VG, "    if loaded:\n        problems.append", "    if False:\n        problems.append"),
    ("vg_passed_always", VG, "\"passed\": bool(worlds and n_q > 0 and not problems)", "\"passed\": True"),
    ("vg_dwell_no_reset", VG, "            else:\n                prev = None\n        if e >= 1:", "            else:\n                pass\n        if e >= 1:"),
    ("vg_query_last_visit", VG, "                        })\n                        break\n", "                        })\n"),
    ("vg_fast_unswapped", VG, "if ev[\"bucket\"] == spec.BUCKET_LONG and ev[\"swapped\"]:", "if ev[\"bucket\"] == spec.BUCKET_LONG:"),
    ("vg_keys_no_answer", VG, "KEYS = (\"episode\", \"t\", \"xy\", \"terrain\", \"shown\", \"answer\", \"decoy\", \"relocated\")", "KEYS = (\"episode\", \"t\", \"xy\", \"terrain\", \"shown\", \"decoy\", \"relocated\")"),
    ("run_smoke_registered", RUN, "SMOKE_NAMESPACE = \"s3p3x-smoke\"", "SMOKE_NAMESPACE = \"s3p3x-explore\""),
    ("run_useid_optional", RUN, "    if a.stage in (\"smoke\", \"probe\") and not a.use_id:\n        raise GD.GuardError(f\"a {a.stage} run needs a use id\")\n", ""),
    ("run_no_code_dirty", RUN, "\"code_manifest_sha256\": manifest_sha(code), \"code_dirty\": code_dirty,", "\"code_manifest_sha256\": manifest_sha(code), \"code_dirty\": [],"),
    ("run_code_without_gen", RUN, "extra=[VERIFY, VERIFY_GEN])\n\n\ndef manifest_sha", "extra=[VERIFY])\n\n\ndef manifest_sha"),
    ("run_k2b_skipped", RUN, "        k2b = independent_check(VERIFY_GEN, worlds, ns, cfg[\"episodes\"], deadline=deadline)\n", "        k2b = {\"passed\": True, \"worlds\": cfg[\"worlds\"]}\n"),
    ("run_k2b_wrong_ns", RUN, "independent_check(VERIFY_GEN, worlds, ns, cfg[\"episodes\"], deadline=deadline)", "independent_check(VERIFY_GEN, worlds, \"x\", cfg[\"episodes\"], deadline=deadline)"),
    ("mp_no_code_check", MP, "    if pr.get(\"code_manifest_sha256\") != code_sha or pr.get(\"code_dirty\") != []:", "    if pr.get(\"code_dirty\") != []:"),
    ("mp_dirty_ok", MP, "    if pr.get(\"code_manifest_sha256\") != code_sha or pr.get(\"code_dirty\") != []:", "    if pr.get(\"code_manifest_sha256\") != code_sha:"),
    ("mp_dev_uses", MP, "\"dev_max_uses\": 0,", "\"dev_max_uses\": 2,"),
    ("vf_L_includes_current", VF, "            if e < q[\"episode\"]:", "            if e <= q[\"episode\"]:"),
]


def copy_tree(dst, src=REPO):
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "tests/v9/experiments").mkdir(parents=True)
    shutil.copy2(src / "tests/conftest.py", dst / "tests/conftest.py")
    for t in FAST + SLOW:
        shutil.copy2(src / t, dst / t)
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    (dst / "reports/V9-S3-PHASE3").mkdir(parents=True)
    shutil.copy2(src / RUN, dst / RUN)
    for f in (VF, VG, MP):
        shutil.copy2(src / f, dst / f)


def pytest(dst, files):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *files], cwd=dst, env=env, capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout[-600:]


def main():
    only = set(sys.argv[1:])
    results = []
    with tempfile.TemporaryDirectory(prefix="s3p3-mut-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base)
        rc, tail = pytest(base, FAST + SLOW)
        print("unmutated", rc, flush=True)
        if rc != 0:
            raise SystemExit("unmutated copy fails:\n" + tail)
        for name, path, old, new in M:
            if only and name not in only:
                continue
            d = Path(tmp) / name
            copy_tree(d, base)  # from the snapshot taken at start, not the live tree
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
            rc, tail = pytest(d, FAST)
            stage = "fast"
            if rc == 0:
                rc, tail = pytest(d, SLOW)
                stage = "runner"
            status = "killed" if rc != 0 else "SURVIVED"
            results.append({"name": name, "file": path, "status": status, "by": stage if rc else None, "seconds": round(time.monotonic() - t0, 1), "tail": tail[-300:]})
            print(name, status, stage, round(time.monotonic() - t0, 1), flush=True)
            shutil.rmtree(d)
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("killed", sum(r["status"] == "killed" for r in results), "of", len(results))


if __name__ == "__main__":
    main()
