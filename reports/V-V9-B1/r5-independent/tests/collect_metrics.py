"""B8：把各阶段 summary 聚合成 metrics.json（数字全部来自原始运行记录，不手写）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
RES = HERE / 'results'

A = json.load(open(RES / 'A-identity-summary.json'))
B = json.load(open(RES / 'B-entries-source-summary.json'))
C = json.load(open(RES / 'C-suite-summary.json'))
D = json.load(open(RES / 'D-fixture-suite-summary.json'))
F = json.load(open(RES / 'F-final-identity-summary.json'))
check = json.load(open(L.CAND_DIR / 'check_result.json'))
author_metrics = json.load(open(L.CAND_DIR / 'metrics.json'))


def by_label(runs, label):
    return next(r for r in runs if r['label'] == label)


findings = [
    {"id": "F1", "severity": "high", "status": "confirmed",
     "claim": "suite 显式 --output-dir 只写显式目录、输入输出分离",
     "observation": "--output-dir 指向原 r4 交付目录副本 / 候选交付目录自身 / fixtures 输入夹具目录时均未被拒绝，"
                    "rc=0/all_ok=true，并覆盖该目录下既有的 check_result.json 与 SHA256SUMS.txt（各 2 个文件）。",
     "evidence": "results/C-suite-summary.json c3_output_dir_safety",
     "note": "直接回答 codex #167 的问题：会覆盖，且没有拒绝；违反“输出仅显式新目录、输入与输出分离”。B9 已独立实证同类，本复核独立复现。"},
    {"id": "F2", "severity": "medium", "status": "confirmed",
     "claim": "候选自己的 SHA256SUMS.txt 与最终字节一致（证据清单自洽）",
     "observation": "候选清单 254 数据行中 251 raw 对；REPORT.md 行陈旧（清单 e128141f…，磁盘 dcd6fa8e…）；"
                    "另 2 行为 MISSING（COORDINATOR_DECISIONS.md、r4/SUMMARY.md，继承标签未随 OUT 更新）；JCS 列全对。",
     "evidence": "results/A-identity-summary.json a3_candidate_vs_r4.candidate_manifest",
     "note": "与 B6-F1 同类问题复发；我的独立重跑生成的清单与作者清单只差 REPORT.md 这一行。"},
    {"id": "F3", "severity": "medium", "status": "confirmed",
     "claim": "候选清单的交付物路径可直接按物理路径核验",
     "observation": "候选清单把自身交付物标成 reports/V9-B1/check_skill_proposal.py 等原 r4 物理路径，"
                    "哈希却对应候选副本（5b28818b… vs 磁盘原 r4 37d4308f…）。按物理路径直接核对会误判 r4 被改。",
     "evidence": "results/A-identity-summary.json a3_candidate_vs_r4.logical_path_collisions",
     "note": "需要显式重映射说明；建议交付时改标 r5-candidate/ 前缀或写明映射。"},
    {"id": "F4", "severity": "low", "status": "confirmed",
     "claim": "所有 JSON 入口 strict=True → 重复键 fail-closed、无 traceback",
     "observation": "proposal/context/reply 三入口成立（rc=1、*_unreadable:ValueError、无 traceback）；"
                    "已提交夹具被篡改时由更早的逐字节比对干净拦下（FIXTURE MISMATCH，rc=1，无 traceback）；"
                    "但 suite 的回归输入 reports/V-V9-B1/probe_variants.json 含重复键时抛未捕获 ValueError（rc=1 + traceback）。"
                    "关掉该入口 strict 的副本可完整跑完 all_ok=true → strict 载入确实承重，但失败形态不是干净 fail-closed。",
     "evidence": "results/D-fixture-suite-summary.json"},
    {"id": "F5", "severity": "low", "status": "confirmed",
     "claim": "非法登记属性名由 check_schema_props_forbidden 单独守住（B6-F2 修复的承重性）",
     "observation": "候选干净拒绝（rc=1、decision=null、entry:…:forbidden_property:world_id、无 traceback），"
                    "关闭 world_id_normalization 不绕过；但只关 check_schema_props_forbidden 仍被 param_schema_problems 正常拒绝（冗余层）；"
                    "把两处登记属性名检查都关掉后同一反例 decision=accepted（真实漏检，不是异常退出）。"
                    "r4 同输入为 gate_internal_error:NameError，r5 修复的是干净路径而不是唯一检测层。",
     "evidence": "results/B-entries-source-summary.json"},
    {"id": "F6", "severity": "low", "status": "confirmed",
     "claim": "首版（被打回版）已归档、证据可追溯",
     "observation": "候选目录没有任何首版归档（无 archive/ 目录）；REPORT.md 未披露首版不可恢复；relay 历史只有报告文本，无源码字节。"
                    "B9 亦记录“无法确认完整归档或恢复首版，不重建冒充”。",
     "evidence": "reports/V9-B1/r5-candidate/ 目录清单；relay B7/B9 事件"},
    {"id": "F7", "severity": "low", "status": "confirmed",
     "claim": "四入口/来源三反例/suite 实跑的实际日志已随候选提交",
     "observation": "候选 verification_logs/ 只有 duplicate_key.log 与 illegal_property.log 两条（已复制存档并核对与我复现一致）；"
                    "没有四入口/来源三反例/suite 实跑日志；REPORT 未列出 verification_logs。本复核的 170 条原始运行记录见 results/logs/*.jsonl 与 COMMANDS.md。",
     "evidence": "results/original-author-logs/；results/logs/"},
    {"id": "F8", "severity": "info", "status": "confirmed",
     "claim": "重复键反例输出无重复/无噪声",
     "observation": "非法登记属性名反例中同一 forbidden_property:world_id 在 errors 里出现两次（两个检查层各报一次）。不影响判定，但与作者日志一致，属可去重的噪声。"},
]

metrics = {
    "task": "ainerzero.V9.B8",
    "agent": "deepseek-h7m2",
    "role": "非作者二级执行（verify）",
    "subject": "ainerzero.V9.B7 候选 r5-candidate（SHA 5b28818b…）及原 r4 不变性",
    "timeline_note": "2026-10-17 09:03 领取；A/B/C 完成、D 中断；2026-10-17 20:59 租约到期被回收（非失败）；"
                     "2026-10-18 08:45 恢复后补归档 exec 组空、补齐 D/F 并落盘本证据；B8 仍因前置 B7 进行中而不可领取。",
    "subject_identity": {
        "candidate_checker_sha256": L.sha(L.CAND),
        "candidate_dir": "reports/V9-B1/r5-candidate",
        "base_note": "B7 v1 参数 base_candidate_sha256 与本值一致；B7 新修订将另建 r6-candidate",
        "original_r4_checker_sha256": L.sha(L.R4),
        "awz_observation_source_sha256": L.sha(L.AWZ_OBSERVATION),
        "awz_pinned_content_sha256": "01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb",
        "legacy_path_sha256": "a2971c9a293701ae588053b88dffe817d450db45dc1d16527ccdf8b0ab1a26d6",
        "schemas": A['a3_candidate_vs_r4']['script'] and {p.name: L.sha(p) for p in sorted((L.ROOT / 'contracts/v9').glob('*.json'))},
    },
    "r4_invariance": {
        "r4_manifest_rows": A['a1_r4_manifest']['rows'],
        "r4_manifest_raw_ok": A['a1_r4_manifest']['raw_ok'],
        "r4_manifest_jcs_ok": A['a1_r4_manifest']['jcs_ok'],
        "r4_manifest_jcs_error_rows": [x['path'] for x in A['a1_r4_manifest']['jcs_error_rows']],
        "b6_baseline_ok": A['a2_b6_baseline']['ok'],
        "b6_baseline_deliverables": A['a2_b6_baseline']['deliverables_checked'],
        "b6_baseline_fixtures": A['a2_b6_baseline']['fixtures_checked'],
        "b6_baseline_sabotage": A['a2_b6_baseline']['sabotage_checked'],
        "files_touched_after_b6_capture": A['a5_r4_tree_extra']['files_touched_after_b6_capture'],
        "all_bytes_unchanged_after_all_runs": F['all_bytes_unchanged'],
        "r4_delivery_tree_files_checked": F['filesystem_unchanged']['r4_delivery_tree']['n_before'],
        "candidate_tree_files_checked": F['filesystem_unchanged']['candidate_tree']['n_before'],
        "contracts_docs_awz_inputs_unchanged": {
            k: v['bytes_unchanged'] for k, v in F['filesystem_unchanged'].items()},
    },
    "candidate_vs_r4": {
        "checker_diff_added_lines": A['a3_candidate_vs_r4']['script']['added_lines'],
        "checker_diff_removed_lines": A['a3_candidate_vs_r4']['script']['removed_lines'],
        "fixtures_total": A['a3_candidate_vs_r4']['fixtures']['r4_files'],
        "fixtures_byte_diff": len(A['a3_candidate_vs_r4']['fixtures']['byte_diff']),
        "fixtures_byte_diff_note": "113 个 contexts/EXPECTATIONS（source SHA 迁移）+ 1 个 EXPECTATIONS = 114；valid/invalid/replies 未变",
        "sabotage_byte_diff": len(A['a3_candidate_vs_r4']['sabotage']['byte_diff']),
        "candidate_manifest_raw_mismatch": A['a3_candidate_vs_r4']['candidate_manifest']['raw_mismatch'],
        "candidate_manifest_missing_rows": A['a3_candidate_vs_r4']['candidate_manifest']['missing_rows'],
        "logical_path_collisions": A['a3_candidate_vs_r4']['logical_path_collisions'],
    },
    "entries_and_guards": {
        "cli_runs": len(B['runs']),
        "checks": len(B['checks']),
        "checks_failed": len(B['checks_failed']),
        "jcs_pin_crosscheck": {k: B['jcs_crosscheck'][k] for k in ('pins_compared', 'ok', 'all_match')},
        "proposal_dup_key": {
            "candidate": {"rc": by_label(B['runs'], 'dup-proposal-cand')['rc'],
                          "errors": by_label(B['runs'], 'dup-proposal-cand')['errors'],
                          "traceback": by_label(B['runs'], 'dup-proposal-cand')['has_traceback']},
            "candidate_strict_off": {"rc": by_label(B['runs'], 'dup-proposal-cand-nostrict')['rc'],
                                     "decision": by_label(B['runs'], 'dup-proposal-cand-nostrict')['decision']},
            "r4": {"rc": by_label(B['runs'], 'dup-proposal-r4')['rc'],
                   "decision": by_label(B['runs'], 'dup-proposal-r4')['decision']},
            "smuggle_variant": {"candidate": by_label(B['runs'], 'dup-proposal-smuggle-cand')['rc'],
                                "candidate_strict_off": by_label(B['runs'], 'dup-proposal-smuggle-cand-nostrict')['decision'],
                                "r4": by_label(B['runs'], 'dup-proposal-smuggle-r4')['decision']},
        },
        "context_dup_key": {"candidate_rc": by_label(B['runs'], 'dup-context-cand')['rc'],
                            "candidate_errors": by_label(B['runs'], 'dup-context-cand')['errors'],
                            "strict_off_decision": by_label(B['runs'], 'dup-context-cand-nostrict')['decision'],
                            "r4_decision": by_label(B['runs'], 'dup-context-r4')['decision']},
        "reply_dup_key": {"candidate_rc": by_label(B['runs'], 'dup-reply-cand')['rc'],
                          "candidate_errors": by_label(B['runs'], 'dup-reply-cand')['errors'],
                          "strict_off_rc": by_label(B['runs'], 'dup-reply-cand-nostrict')['rc'],
                          "r4_rc": by_label(B['runs'], 'dup-reply-r4')['rc']},
        "registry_illegal_property": {
            "candidate": {"rc": by_label(B['runs'], 'registry-illegal-cand')['rc'],
                          "decision": by_label(B['runs'], 'registry-illegal-cand')['decision'],
                          "errors": by_label(B['runs'], 'registry-illegal-cand')['errors'],
                          "traceback": by_label(B['runs'], 'registry-illegal-cand')['has_traceback']},
            "disable_norm": {"rc": by_label(B['runs'], 'registry-illegal-disable-norm-cand')['rc'],
                             "errors": by_label(B['runs'], 'registry-illegal-disable-norm-cand')['errors']},
            "propguard_only_off": {"rc": by_label(B['runs'], 'registry-illegal-cand-nopropguard')['rc'],
                                   "errors": by_label(B['runs'], 'registry-illegal-cand-nopropguard')['errors']},
            "both_guards_off": {"rc": by_label(B['runs'], 'registry-illegal-cand-noregpropguard')['rc'],
                                "decision": by_label(B['runs'], 'registry-illegal-cand-noregpropguard')['decision']},
            "r4": {"rc": by_label(B['runs'], 'registry-illegal-r4')['rc'],
                   "decision": by_label(B['runs'], 'registry-illegal-r4')['decision'],
                   "errors": by_label(B['runs'], 'registry-illegal-r4')['errors']},
            "nested": {"candidate_errors": by_label(B['runs'], 'registry-illegal-nested-cand')['errors'],
                       "r4_errors": by_label(B['runs'], 'registry-illegal-nested-r4')['errors'],
                       "both_guards_off": by_label(B['runs'], 'registry-illegal-nested-cand-noregpropguard')['decision']},
        },
        "source_binding": {
            "missing": {"candidate_rc": by_label(B['runs'], 'source-missing-cand')['rc'],
                        "candidate_errors": by_label(B['runs'], 'source-missing-cand')['errors'],
                        "sourceguard_off_decision": by_label(B['runs'], 'source-missing-cand-nosourceguard')['decision']},
            "unreadable": {"candidate_rc": by_label(B['runs'], 'source-unreadable-cand')['rc'],
                           "candidate_errors": by_label(B['runs'], 'source-unreadable-cand')['errors'],
                           "sourceguard_off_decision": by_label(B['runs'], 'source-unreadable-cand-nosourceguard')['decision']},
            "content_drift_path_unchanged": {"candidate_rc": by_label(B['runs'], 'source-drift-path-unchanged-cand')['rc'],
                                             "candidate_errors": by_label(B['runs'], 'source-drift-path-unchanged-cand')['errors'],
                                             "sourceguard_off_decision": by_label(B['runs'], 'source-drift-cand-nosourceguard')['decision']},
            "old_pin_path_hash": {"candidate_rc": by_label(B['runs'], 'source-old-pin-cand')['rc'],
                                  "candidate_errors": by_label(B['runs'], 'source-old-pin-cand')['errors'],
                                  "r4_with_missing_env_decision": by_label(B['runs'], 'source-old-pin-r4-env-missing')['decision']},
            "source_path_sha_drift": by_label(B['runs'], 'source-path-sha-drift-cand')['errors'],
            "adversarial_ctx_sha": by_label(B['runs'], 'source-adv-ctx-sha-cand')['errors'],
            "all_disable_cannot_bypass": by_label(B['runs'], 'source-missing-all-disable-cand')['errors'],
        },
        "patch_variants_sha256": {k: v['sha256'] for k, v in B['patch_variants']['variants'].items()},
    },
    "suite": {
        "default": {
            "rc": C['c1_default_readonly']['run']['rc'],
            "all_ok": (C['c1_default_readonly']['stdout_parsed'] or {}).get('all_ok'),
            "duration_s": C['c1_default_readonly']['run']['duration_s'],
            "tree_diffs": {k: {'added': len(v['added']), 'removed': len(v['removed']), 'changed': len(v['changed'])}
                           for k, v in C['c1_default_readonly']['tree_diff'].items()},
            "all_clean": C['c1_default_readonly']['all_clean'],
            "no_traceback": C['c1_default_readonly']['no_traceback'],
        },
        "explicit_output": {
            "rc": [C['c2_output_dir']['run1']['rc'], C['c2_output_dir']['run2']['rc']],
            "duration_s": [C['c2_output_dir']['run1']['duration_s'], C['c2_output_dir']['run2']['duration_s']],
            "deterministic_run1_vs_run2": C['c2_output_dir']['deterministic'],
            "check_result_identical_to_author": C['c2_output_dir']['vs_author']['check_result.json']['identical'],
            "sha256sums_identical_to_author": C['c2_output_dir']['vs_author']['SHA256SUMS.txt']['identical'],
            "sha256sums_line_diff": C['c2_output_dir']['vs_author']['SHA256SUMS.txt'].get('first_diffs'),
            "counts_equal_author": C['c2_output_dir']['counts_equal_author'],
            "counts": check['counts'],
        },
        "output_dir_safety": {
            "cases": [{'case': x['case'], 'files_changed': x['files_changed']} for x in C['c3_output_dir_safety']['cases']],
            "any_rejection": C['c3_output_dir_safety']['any_rejection'],
            "copy_default_readonly_clean": C['c3_output_dir_safety']['copy_default_readonly']['clean'],
        },
    },
    "fixture_suite_entries": {
        "committed_fixture_dup_tamper": {k: D['results']['d1_fixture_dup'][k] for k in ('rc', 'has_traceback', 'stdout_contains_FIXTURE_MISMATCH')},
        "extra_fixture_file_dup": {k: D['results']['d3_extra_fixture_dup'][k] for k in ('rc', 'has_traceback', 'stdout_contains_FIXTURE_MISMATCH')},
        "probe_input_dup_strict": {k: D['results']['d2_probe_dup'][k] for k in ('rc', 'has_traceback')},
        "probe_input_dup_strict_off": {k: D['results']['d2b_probe_dup_nostrict'][k] for k in ('rc', 'has_traceback', 'all_ok')},
        "all_checks_ok": D['all_checks_ok'],
    },
    "final_identity": {
        "all_bytes_unchanged": F['all_bytes_unchanged'],
        "r4_vs_b6_baseline": F['r4_vs_b6_baseline'],
        "r4_manifest_selfcheck": F['r4_manifest_selfcheck'],
        "runs_recorded": F['runs_recorded'],
        "files_unchanged": {k: v['bytes_unchanged'] for k, v in F['filesystem_unchanged'].items()},
    },
    "findings": findings,
    "limits": [
        "只读核对与 CPU 工程测试；无训练/MLX/ORT/GPU/下载/付费/提交/推送。",
        "值级隐写通用证明仍未提供，维持字段级档位，未在此复核范围外扩。",
        "未验证真实 AWZ 门禁/内核/WorldBrainAdapter/句柄解析/E3；候选是参考核对器，不是生产实现。",
        "suite 的 probe_variants 重复键 traceback 只证明该入口失败形态不干净，不构成 gate 判定绕过。",
        "输出目录重叠实验只在 /tmp 隔离副本做，未触碰真实旧交付；真实旧交付字节由 F 阶段核对不变。",
        "B8 因租约到期被回收后重领受阻于前置 B7（进行中）；本证据针对 r5 候选 SHA 5b28818b，B7 新修订 r6-candidate 需另核。",
    ],
}

out = HERE / 'metrics.json'
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('wrote', out, len(json.dumps(metrics)), 'bytes')
