"""V9.B6 汇总：把各分项复核结果聚合成 metrics.json + 本目录 SHA256SUMS.txt。"""
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'


def load(name):
    return json.loads((RES / name).read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    probe = load('probe_results.json')
    fixtures = load('fixture_results.json')
    gate = load('gate_results.json')
    jcs = load('jcs_results.json')
    suite = load('suite_results.json')
    awz = load('awz_quantity_results.json')
    b1 = load('b1_doc_results.json')
    base = load('baseline_manifest.json')
    git_head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                              cwd=str(L.ROOT)).stdout.strip()
    sel = {}
    for f in base['deliverables_and_inputs']:
        sel[f['path']] = f['sha256']
    metrics = {
        'task': 'ainerzero.V9.B6',
        'title': '【非作者复核】SkillProposal r4 最小加固与信息隔离',
        'verifier': 'deepseek-flash-emje',
        'verifier_tier': '二级执行层',
        'verified_tasks': ['ainerzero.V9.B1', 'ainerzero.V9.B4'],
        'verified_revisions': {'B1': 'docs/v9/SKILL_PROPOSAL_COORDINATION.md（9593eccf…）',
                               'B4': 'r4'},
        'verifier_is_author': False,
        'non_author_evidence': {
            'b1_authors': b1['identity']['b1_authors'],
            'b4_authors': b1['identity']['b4_authors'],
            'i_am_author': (not b1['identity']['i_am_not_b1_author'] or
                            not b1['identity']['i_am_not_b4_author']),
        },
        'reused_author_oracle': False,
        'independent_tools': {
            'own_jcs': 'tests/indep_lib.py（自写 RFC 8785；自测 16 向量 + 复现 112/112 上下文 pin）',
            'own_key_classifier': 'tests/indep_lib.py is_ident_key_indep（按裁决 2/F1-F3 条文另写）',
            'own_gate_harness': 'tests/verify_gate_checks.py（112 用例 + 101 对照子进程重跑）',
            'not_reused': ['reports/V9-B1/check_skill_proposal.py 的判定逻辑（仅作被测对象）',
                           'reports/V-V9-B1/oracle_r3.py'],
        },
        'environment': {
            'time_local': '2026-10-17T08:22–09:1x +03:00 Europe/Istanbul',
            'python': sys.version.split()[0],
            'platform': platform.platform(),
            'gpu': False, 'training': False, 'mlx_ort_torch': False, 'downloads': False,
            'paid_services': False, 'git_commit': git_head,
            'git_head_unchanged_by_me': True,
            'files_outside_scope_written': 0,
            'delivered_tree_unchanged_by_me': not [f for f in base['deliverables_and_inputs']
                                                   if sha(L.ROOT / f['path']) != f['sha256']],
        },
        'authority': {
            'reports/V9-B1/COORDINATOR_DECISIONS.md': sel['reports/V9-B1/COORDINATOR_DECISIONS.md'],
            'docs/v9/SKILL_PROPOSAL_COORDINATION.md': sel['docs/v9/SKILL_PROPOSAL_COORDINATION.md'],
            'B4-r4-DECISIONS.md': 'd2e5dee3c4331442e19db59254dc60a3b1a160fdda86b1962db07d120fd21cf2',
            'B5_probe_variants.json': sel['reports/V-V9-B1/probe_variants.json'],
            'AWZ_observation_packet.v1_1.schema.json': '01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb',
        },
        'verified_artifact_sha256': {
            'contracts/v9/skill_proposal.v1.schema.json': sel['contracts/v9/skill_proposal.v1.schema.json'],
            'contracts/v9/skill_gate_reply.v1.schema.json': sel['contracts/v9/skill_gate_reply.v1.schema.json'],
            'contracts/v9/ability_registry_entry.v0.schema.json': sel['contracts/v9/ability_registry_entry.v0.schema.json'],
            'docs/v9/SKILL_PROPOSAL.md': sel['docs/v9/SKILL_PROPOSAL.md'],
            'docs/v9/SKILL_PROPOSAL_COORDINATION.md': sel['docs/v9/SKILL_PROPOSAL_COORDINATION.md'],
            'reports/V9-B1/check_skill_proposal.py': sel['reports/V9-B1/check_skill_proposal.py'],
            'reports/V9-B1/check_result.json': sel['reports/V9-B1/check_result.json'],
            'reports/V9-B1/SHA256SUMS.txt': sel['reports/V9-B1/SHA256SUMS.txt'],
            'reports/V9-B1/metrics.json': sel['reports/V9-B1/metrics.json'],
            'reports/V9-B1/REPORT.md': sel['reports/V9-B1/REPORT.md'],
            'contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json': sel['contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json'],
        },
        'counts': {
            'probe_variants_total': probe['probe_total'],
            'probe_rejected_by_indep_classifier': probe['L0_indep_rejected_total'],
            'probe_rejected_by_schema_regex_layer': probe['L1_schema_rejected_total'],
            'probe_rejected_by_gate_normalization_layer': probe['L2_gate_layer_rejected_total'],
            'probe_rejected_by_full_gate': probe['L3_full_gate_rejected_total'],
            'probe_nested_positions_layer2_checked': probe['probe_total'] * 3,
            'probe_layer2_only_keys': len(probe['L2_only_keys']),
            'bare_plural_positive_accepted': sum(1 for r in probe['bare_plural_positive_rows']
                                                 if r['L3_decision'] == 'accepted'),
            'proposal_cases': gate['proposal_cases']['total'],
            'proposal_cases_ok': gate['proposal_cases']['ok'],
            'reply_cases': gate['reply_cases']['total'],
            'reply_cases_ok': gate['reply_cases']['ok'],
            'controls_total': gate['controls']['total'],
            'controls_isolated': gate['controls']['isolated'],
            'controls_nonisolated_explained_by_schema_layer':
                gate['controls']['nonisolated_explained_by_schema'],
            'rules_with_counterexample_and_isolated_control':
                len([r for r, d in gate['controls']['by_rule'].items() if d['isolated'] > 0]),
            'rules_total': len(gate['controls']['by_rule']),
            'confidence_sweep_rows': gate['section_EF']['confidence_sweep']['rows'],
            'no_rewrite_rows': 18,
            'leak_scan_rows': gate['section_EF']['reply_integrity']['replies_scanned'],
            'reply_leaks': len(gate['section_EF']['reply_integrity']['leaked']),
            'fixture_files': fixtures['file_count'],
            'fixture_casefold_collisions': len(fixtures['casefold_collisions']),
            'fixture_inode_collisions': len(fixtures['inode_collisions']),
            'fixture_unique_inodes': fixtures['unique_inodes'],
            'fixture_alias_spellings': fixtures['alias_case_count'],
            'sha256sums_data_rows_checked': fixtures['sums_rows_checked'],
            'sha256sums_errors': len(fixtures['sums_errors']),
            'sha256sums_claimed_rows_in_reports': 253,
            'sha256sums_actual_data_rows': fixtures['sums_rows_checked'],
            'archive_files_total': 124,
            'archive_payload_files': 123,
            'archive_payload_hashes_verified': 123,
            'jcs_mandated_rows': len(jcs['mandated_rows']),
            'jcs_rows_bad': len(jcs['bad']),
            'duplicate_key_input_accepted_observation': jcs['duplicate_key_observation']['rc'] == 0,
            'quantity_allowlist_items': awz['allowed_count'],
            'quantity_three_way_consistent': awz['consistency']['proposal_eq_entry'] and
                                             awz['consistency']['proposal_eq_checker'],
            'quantity_grounding_unmatched': len(awz['grounding_unmatched']),
            'quantity_negative_cases_rejected': len([x for x in gate['quantity']['cases']
                                                     if x['fixture_reason'] == 'schema_invalid']),
            'context_guards_ok': sum(1 for g in gate['quantity']['context_guards'] if g['hit_expected']),
            'suite_runs': len(suite['runs']),
            'suite_all_ok': all(r['all_ok'] for r in suite['runs']),
            'suite_elapsed_s': [r['elapsed_s'] for r in suite['runs']],
            'suite_fixture_tree_unchanged': all(r['fixture_tree_unchanged'] for r in suite['runs']),
            'suite_checkout_unchanged': all(r['checkout_unchanged'] for r in suite['runs']),
            'suite_deterministic': suite['deterministic_second_run'],
            'b1_original_rulings': b1['original_rulings']['count'],
            'b1_original_rulings_present': b1['original_rulings']['all_present'],
            'b1_claims_ok': sum(1 for c in b1['b1_claims']['rows'] if c['ok']),
            'b1_claims_total': len(b1['b1_claims']['rows']),
            'formalization_hold': b1['ruling_mapping']['formalization_hold'],
            'formalization_unimplemented_by_design':
                b1['ruling_mapping']['formalization_not_implemented_by_design'],
        },
        'layers': {
            'L0_independent_classifier': {'total': 1131, 'rejected': probe['L0_indep_rejected_total']},
            'L1_proposal_schema_regex': {'total': 1131, 'rejected': probe['L1_schema_rejected_total']},
            'L2_gate_normalization（--disable schema）': {'total': 1131,
                                                         'rejected': probe['L2_gate_layer_rejected_total']},
            'L3_full_gate': {'total': 1131, 'rejected': probe['L3_full_gate_rejected_total']},
            'families': probe['families'],
        },
        'findings': [
            {'id': 'B6-F1', 'severity': 'minor(evidence-integrity)', 'blocking': False,
             'title': 'metrics.json / relay B4 报告 data 的 check_skill_proposal.py 哈希陈旧',
             'detail': 'metrics.artifacts=9cf0d90b…，磁盘/SHA256SUMS=37d4308f…；两处均报旧值。'
                       'SUITE 在最终编辑后重跑（check_result/SHA256SUMS 02:56 自洽且与磁盘一致），'
                       '本复核以最终字节复跑两次 all_ok。建议统筹验收时以 SHA256SUMS.txt 为准或令作者补勘误。'},
            {'id': 'B6-F2', 'severity': 'minor(code-defect, fail-closed)', 'blocking': False,
             'title': 'check_schema_props_forbidden 对 forbidden 属性名抛 NameError（here 未定义）',
             'detail': '登记条目 param_schema 属性名为 WORLD_ID/entities_id/objectId/hidden_contact 时，'
                       'registry_problems→check_schema_props_forbidden 第 214 行 NameError；'
                       'CLI 兜底为 schema_invalid（无 traceback、真实非零，fail-closed 已验证），'
                       '但干净上下文拒绝路径被内部错误替代；作者矩阵用 lite_problems 未覆盖该路径。'
                       '非阻断，建议 r5 修一行。'},
            {'id': 'B6-F3', 'severity': 'minor(doc-consistency)', 'blocking': False,
             'title': '文档/摘要中两处旧数字',
             'detail': 'SKILL_PROPOSAL.md:139「本修订为 60 行全过」vs 实际 184 行；'
                       'r4/SUMMARY.md:12 称 SHA256SUMS「253 行」vs 实际数据行 254。'},
            {'id': 'B6-F4', 'severity': 'observation', 'blocking': False,
             'title': 'observable_registry.source_sha256 绑定的是路径字符串而非 AWZ 文件内容',
             'detail': '上下文该字段 = sha256("AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json")'
                       '（a2971c9a…），AWZ 文件内容哈希为 01be45e0…。允许表内容仍由整份上下文 JCS pin 固定；'
                       '但「取自 AWZ 契约」不能由核对器密码学验证。'},
            {'id': 'B6-F5', 'severity': 'observation', 'blocking': False,
             'title': 'quantity_forbidden_alias 分支按构造不可达（防御纵深死代码）',
             'detail': '允许表内 50 项无一命中标识规范化判定（作者与自写判定均为空），而上下文允许表'
                       '若含别名会被 context_observable_forbidden 拒；故任意别名先被 quantity_not_allowed 拦，'
                       '别名分支不会命中。不影响拒绝结果，但不应记为额外覆盖。'},
            {'id': 'B6-F6', 'severity': 'observation', 'blocking': False,
             'title': '输入 JSON 重复键不 fail-closed（最后值获胜）',
             'detail': 'gate 读提案/上下文用 load_json(strict=False)；重复键静默合并。已实测重复 '
                       'proposal_id 的提案 rc0 accepted。RFC 8259 允许重复键但 JCS 要求唯一；'
                       '建议所有输入 strict=True。不在 F4 点名范围（整数/代理项/编解码），列为残留风险。'},
            {'id': 'B6-F7', 'severity': 'observation', 'blocking': False,
             'title': '值级偷带可接受（任意隐写无通用证明）',
             'detail': '合法字符串参数承载真实实体 ID entity-7f3a41c9b2e05d18 → accepted；'
                       'B4 文档 §13 第 3/4 行已如实写明「不能/未实现」，本复核确认该自述诚实；'
                       '裁决 2 只要求字段级禁止，故不构成对 r4 的阻断。'},
            {'id': 'B6-F8', 'severity': 'observation', 'blocking': False,
             'title': 'r3 归档清单含自指占位行（e3b0c44…=空文件哈希），"124 文件"口径含清单自身',
             'detail': 'archive 目录共 124 文件：123 payload + ARCHIVE_SHA256SUMS.txt；'
                       '123 个 payload 哈希全部逐字核对通过；清单自指行用空哈希占位。建议措辞改「123 文件＋清单」。'},
            {'id': 'B6-F9', 'severity': 'observation', 'blocking': False,
             'title': 'B5 两个汇总文件与 B5 报告 data 记录哈希不一致（自指清单类）',
             'detail': 'reports/V-V9-B1/SHA256SUMS_b4-r3.txt、metrics_b4-r3.json 当前哈希与 B5 报告的 '
                       'verifier_artifact_hashes 不同（其中 sums 文件对自身行也记空哈希式占位）；'
                       'B5 的关键回归输入（probe_variants.json、oracle_r3.py、verify_b4r3.py、'
                       'REPORT_B4-r3.md、probe_results.json）与报告哈希一致，B5 负面发现可按原样使用。'},
        ],
        'verdicts': {
            'b4_r4_1131_probe_stratified': 'PASS（四层 1131/1131；3 层嵌套位置 L2 全拒）',
            'b4_r4_case_only_paths': 'PASS（236 文件 0 casefold/0 inode 碰撞；5 组大小写别名各自独立路径/inode/内容）',
            'b4_r4_quantity': 'PASS（50 项三方一致+可追溯 AWZ；7 反例+越权/未知/别名+上下文守卫全拒，控制真实漏检）',
            'b4_r4_jcs_fail_closed': 'PASS（点名两类 + NaN/Inf/无效 UTF-8 均真实非零白名单码、0 traceback；重复键见 B6-F6）',
            'b4_r4_manifest_sha': 'PASS with B6-F1（254/254 数据行核对通过；check_result/SHA256SUMS 自洽；metrics/relay 一处陈旧）',
            'b4_r4_suite_readonly': 'PASS（副本 2 次 all_ok；夹具 0 改动；交付副本哈希归一 inode 后与提交版一致；确定性）',
            'b4_r4_broken_controls': 'PASS（101 对照：48 真实隔离（41 提案+7 回执），53 由层 1 schema 正则先拒且逐条独立解释；17 规则均有隔离对照）',
            'b4_r4_stegh_proof': 'N/A（不存在任意隐写通用证明；B4 自述如实，见 B6-F7）',
            'b1_primary_rulings': 'PASS（Claude 原 11 条完整；B1 协调页 5 项重点主张全部与原裁决/AWZ 只读证据一致）',
            'b1_vs_b4_separation': 'PASS（一级裁决 11/11 保持、未改参数；二级形式化 10/11 有独立证据，裁决 11 按原裁决仅文档未实现）',
            'review_conclusion': '建议统筹验收 B1 + B4 r4（限本次证据范围）；B6-F1/F2/F3 建议随下一次修订补正，'
                                 '均非阻断；未验证项见报告。本复核不自行 accept。',
        },
        'unverified': [
            '真实 AWZ 门禁/运行内核/WorldBrainAdapter 均未实现（交付自述一致）；本复核只验 CPU 参考核对。',
            '参数值语义与任意隐写：无通用证明，未实现（B4 文档 §13 第 3/4 行）。',
            '裁决 11 final 分区训练门只在文档写明，未实现。',
            '句柄到实体映射、E3 编译与编辑路线授权未实现。',
            '未在大小写敏感文件系统（Linux CI）复跑；本机 APFS 大小写不敏感，casefold/inode 结论限本机。',
            '未运行真实模型/训练/下载/GPU；未修改任何源码或交付物。',
        ],
        'commands': [
            '/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V-V9-B1/r4-independent/tests/indep_lib.py selftest',
            '…/tests/verify_probe.py',
            '…/tests/verify_fixtures.py',
            '…/tests/verify_gate_checks.py',
            '…/tests/verify_jcs_cli.py',
            '…/tests/verify_suite_copy.py   # 在 /tmp/v9b6-suite-copy 副本跑 --suite 两次',
            '…/tests/verify_awz_quantity.py',
            '…/tests/verify_b1_doc.py',
            '…/tests/collect_metrics.py',
        ],
        'artifacts': {},
    }
    # 本目录产物哈希（写 metrics 前的文件）
    for p in sorted(OUT.rglob('*')):
        if not p.is_file() or 'tmp/' in str(p):
            continue
        rel = str(p.relative_to(L.ROOT))
        if rel.endswith('__pycache__') or '__pycache__' in rel:
            continue
        metrics['artifacts'][rel] = sha(p)
    # 写 metrics 后更新 metrics.json 自身不列入（自指）
    (OUT / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                      encoding='utf-8')
    # SHA256SUMS.txt：列出 tests/*.py、results/*.json、REPORT.md、metrics.json（最后写）
    lines = ['# ainerzero.V9.B6 独立复核产物 SHA256（raw）',
             '# 生成：collect_metrics.py；交付树与夹具在本轮复核前后逐字节不变（见 results/baseline_manifest.json）',
             '']
    for p in sorted(OUT.rglob('*')):
        if not p.is_file() or '__pycache__' in str(p) or 'tmp/' in str(p) or 'SHA256SUMS' in p.name:
            continue
        lines.append('%s  %s' % (sha(p), str(p.relative_to(OUT))))
    (OUT / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: metrics['counts'][k] for k in (
        'probe_variants_total', 'probe_rejected_by_gate_normalization_layer',
        'proposal_cases_ok', 'controls_isolated', 'controls_nonisolated_explained_by_schema_layer',
        'sha256sums_data_rows_checked', 'fixture_files', 'jcs_rows_bad',
        'quantity_allowlist_items', 'suite_runs', 'suite_all_ok',
        'b1_claims_ok', 'formalization_hold')}, ensure_ascii=False, indent=1))
    print('findings:', [(f['id'], f['severity']) for f in metrics['findings']])
    print('verdict:', metrics['verdicts']['review_conclusion'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
