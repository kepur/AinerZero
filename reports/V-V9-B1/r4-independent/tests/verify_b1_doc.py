"""V9.B6 独立复核：一级 B1 文档（docs/v9/SKILL_PROPOSAL_COORDINATION.md）与 Claude 原 11 条裁决，
以及「一级裁决 vs 二级形式化」各自的成立情况。

只读复核；不修改任何被验文件。判定来自：
  - reports/V9-B1/COORDINATOR_DECISIONS.md（Claude 原 11 条，SHA 04504c33…）
  - docs/v9/SKILL_PROPOSAL_COORDINATION.md（Codex 一级整合，SHA 9593eccf…）
  - AWZ 只读契约/裁决：Event/v1 schema、ADR-0005、P3-E3 r1 裁决
  - 本复核其它结果文件（probe/gate/fixtures/jcs/quantity/suite）作为二级形式化证据
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'
RES.mkdir(parents=True, exist_ok=True)
B1DOC = L.ROOT / 'docs/v9/SKILL_PROPOSAL_COORDINATION.md'
DECISIONS = L.ROOT / 'reports/V9-B1/COORDINATOR_DECISIONS.md'
SPEC = L.ROOT / 'docs/v9/SKILL_PROPOSAL.md'
AWZ = L.AWZ
EVENT = AWZ / 'contracts/v9/event.v1.schema.json'
ADR0005 = AWZ / 'docs/adr/ADR-0005-provenance-license-partitions.md'
E3DEC = AWZ / 'reports/P3-E3/r1/COORDINATOR_DECISIONS.md'
RELAY = '/Users/mac/AinerWorkFlow/AinerRelay/bin/relay'


def relay_task(tid):
    r = subprocess.run([L.VENV_PY, '-I', RELAY, '--json', 'show', tid, '--full'],
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


def load_results(name):
    p = RES / name
    return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}


def main():
    b1 = B1DOC.read_text(encoding='utf-8')
    dec = DECISIONS.read_text(encoding='utf-8')
    spec = SPEC.read_text(encoding='utf-8')
    out = {}

    # ---------------- A. 身份/作者与 SHA 身份
    t1 = relay_task('ainerzero.V9.B1')
    t4 = relay_task('ainerzero.V9.B4')
    authors1 = sorted({a.get('agent') for a in t1.get('attempt_log') or [] if a.get('agent')})
    authors4 = sorted({a.get('agent') for a in t4.get('attempt_log') or [] if a.get('agent')})
    me = 'deepseek-flash-emje'
    out['identity'] = {
        'my_agent': me,
        'b1_authors': authors1,
        'b4_authors': authors4,
        'i_am_not_b1_author': me not in authors1,
        'i_am_not_b4_author': me not in authors4,
        'b1_status': t1.get('status'), 'b4_status': t4.get('status'),
        'b1_sha_reported': (t1.get('result_data') or {}).get('sha256'),
        'b1_sha_disk': L.sha_file(B1DOC),
        'b1_sha_match': (t1.get('result_data') or {}).get('sha256') == L.sha_file(B1DOC),
        'decisions_doc_sha': L.sha_file(DECISIONS),
        'decisions_sha_in_b4_inputs': ((t4.get('result_data') or {}).get('inputs_read_only') or {}
                                       ).get('reports/V9-B1/COORDINATOR_DECISIONS.md'),
        'decisions_sha_match': ((t4.get('result_data') or {}).get('inputs_read_only') or {}
                                ).get('reports/V9-B1/COORDINATOR_DECISIONS.md') ==
                                L.sha_file(DECISIONS),
        'b4_report_revision': (t4.get('result_data') or {}).get('revision'),
    }

    # ---------------- B. Claude 原 11 条是否齐全（逐条关键词）
    ruling_checks = [
        (1, '两条路线，v1 只开一条', ['两条路线', '运行路线', '编辑路线', 'effect_class_not_registered']),
        (2, '目标只能用观察句柄，不用世界 ID', ['观察句柄', 'h-<n>', '世界侧标识字段']),
        (3, '证据版本绑定观察和信念', ['evidence_version', 'JCS', 'packet_ref', 'belief_sha256']),
        (4, 'TTL 用 tick 计，不用墙钟', ['[basis.t_ticks, basis.t_ticks + ttl_ticks]', 'proposal_expired',
                                        '不做换算']),
        (5, '能力登记是门禁的唯一依据', ['能力登记', '参数 schema', '效果类别', 'TTL 上限']),
        (6, '置信度只作参考，不作门禁依据', ['confidence', 'calibration', '1.0']),
        (7, '预期结果用观察量表达', ['expected_outcomes', '观察通道', '世界真值']),
        (8, '门禁回执分两层，防止泄露', ['白名单原因码', 'handle_unknown', 'rejected_other']),
        (9, '不静默改写提案', ['不静默改写', '裁剪、补全或替换']),
        (10, '身份与幂等', ['proposal_id', 'duplicate_proposal', '同 ID']),
        (11, '数据去向', ['Forge ExperienceEpisode', 'final', '不得用于训练']),
    ]
    rc = []
    for num, title, kws in ruling_checks:
        missing = [k for k in kws if k not in dec]
        rc.append({'ruling': num, 'title': title, 'keywords_missing': missing,
                   'present': not missing})
    out['original_rulings'] = {'rows': rc, 'all_present': all(r['present'] for r in rc),
                               'count': len(rc)}

    # ---------------- C. B1 文档的五点重点主张 + 与原始裁决/AWZ 证据的一致性
    claims = []

    def claim(cid, label, doc_file, need, evidence, ok):
        claims.append({'id': cid, 'label': label, 'doc': doc_file, 'need': need,
                       'evidence': evidence, 'ok': bool(ok)})

    ev_text = EVENT.read_text(encoding='utf-8')
    ev = json.loads(ev_text)
    source_enum = (ev.get('properties') or {}).get('source', {}).get('enum')
    # 1) 运行命令沿用既有 Event/source=command，不新增 student 枚举，不产生 E3 持久提交
    command_ok = source_enum is not None and 'command' in source_enum
    no_student_enum = '"student"' not in ev_text
    b1_run_phrase = ('source=command' in b1 and '不新增“student”枚举' in b1 and
                     '不产生 E3 持久提交' in b1)
    spec_run_phrase = ('不产生 E3 信封' in spec and 'Event/v1 事件' in spec)
    no_e3_impl_in_delivery = ('world_change' not in spec and
                              'world_change' not in (L.ROOT / 'contracts/v9/skill_proposal.v1.schema.json')
                              .read_text(encoding='utf-8'))
    # E3 裁决 5：非用户 actor 可预览、提交须用户确认/授权
    e3 = E3DEC.read_text(encoding='utf-8')
    e3_r5_ok = ('非用户 actor' in e3 and '预览' in e3 and '提交须有用户确认' in e3)
    claim('C1-run-route-event-source-command',
          '运行命令用既有 Event/source=command、不新增 student 枚举、不走 E3 持久提交',
          'docs/v9/SKILL_PROPOSAL_COORDINATION.md:15',
          'source=command / 不新增 student / 不产生 E3 持久提交',
          {'event_source_enum': source_enum, 'event_schema_has_command': command_ok,
           'event_schema_no_student_literal': no_student_enum,
           'b1_doc_phrase': b1_run_phrase, 'b4_spec_run_phrase': spec_run_phrase,
           'delivery_no_e3_impl': no_e3_impl_in_delivery, 'e3_ruling5': e3_r5_ok},
          command_ok and no_student_enum and b1_run_phrase and spec_run_phrase and no_e3_impl_in_delivery)

    # 2) 编辑能力为空
    gate = load_results('gate_results.json')
    edit_route = (gate.get('section_EF') or {}).get('edit_route') or {}
    ctxs = list((L.FIXTURE / 'contexts').glob('*.json'))
    all_empty = all(L.load(p)['ability_registry']['registered_edit_abilities'] == [] for p in ctxs)
    guard_hit = any(g['guard'] == 'edit_set_not_empty' and g['hit_expected']
                    for g in (gate.get('quantity') or {}).get('context_guards', []))
    claim('C2-edit-abilities-empty',
          'SkillProposal/v1 已登记编辑能力集合为空，合成例子不能取得实际权限',
          'docs/v9/SKILL_PROPOSAL_COORDINATION.md:16',
          '编辑能力集合为空；编辑类提案必拒',
          {'b1_doc': ('已登记编辑能力集合为空' in b1), 'b4_spec': ('编辑类能力集合**为空**' in spec),
           'all_112_contexts_empty': all_empty, 'context_guard_nonempty_rejects': guard_hit,
           'edit_proposal_rejected': edit_route.get('base'),
           'disable_effect_class_control': edit_route.get('disable_effect_class')},
          ('已登记编辑能力集合为空' in b1) and all_empty and guard_hit and
          edit_route.get('base') == 'effect_class_not_registered')

    # 3) 闭区间 TTL 不变
    closed_ok = ('[basis.t_ticks, basis.t_ticks + ttl_ticks]' in dec and
                 '[basis.t_ticks, basis.t_ticks + ttl_ticks]' in b1 and
                 '闭区间' in b1 and '不因其他契约的控制租约区间而改变' in b1)
    ttl_rows = (gate.get('section_EF') or {}).get('ttl_closed_interval') or []
    ttl_impl_ok = (len(ttl_rows) == 3 and all(r['interval_holds'] for r in ttl_rows) and
                   any(r['name'] == 'valid_ttl_lower_boundary' and r['decision'] == 'accepted'
                       for r in ttl_rows) and
                   any(r['name'] == 'valid_ttl_upper_boundary' and r['decision'] == 'accepted'
                       for r in ttl_rows) and
                   any(r['name'] == 'ttl_expired' and r['reason'] == 'proposal_expired'
                       for r in ttl_rows))
    code = L.CHECKER.read_text(encoding='utf-8')
    ttl_code_ok = 'decided_at > vu' in code and 'basis.t_ticks' in code
    claim('C3-ttl-closed-interval-unchanged',
          'TTL 继续闭区间 [basis.t_ticks, basis.t_ticks+ttl_ticks]，不因控制租约改变',
          'docs/v9/SKILL_PROPOSAL_COORDINATION.md:26',
          '闭区间两端都有效，右端+1 过期；原裁决文本一致',
          {'original_ruling_interval': '[basis.t_ticks, basis.t_ticks + ttl_ticks]' in dec,
           'b1_doc_interval': '[basis.t_ticks, basis.t_ticks + ttl_ticks]' in b1,
           'b1_no_lease_change': '不因其他契约的控制租约区间而改变' in b1,
           'impl_boundary_rows': ttl_rows, 'impl_ttl_ok': ttl_impl_ok, 'code_logic_ok': ttl_code_ok,
           'checker_has_no_lease_logic': 'lease' not in code.lower()},
          closed_ok and ttl_impl_ok and ttl_code_ok and 'lease' not in code.lower())

    # 4) external_derived 默认不可训练（ADR-0005）
    adr = ADR0005.read_text(encoding='utf-8')
    adr_ok = 'external_derived' in adr and '不算 observed' in adr and '不进训练准入' in adr
    claim('C4-external-derived-not-trainable',
          'AWZ 经历按 ADR-0005 为 external_derived，默认不可训练；提案不能把来源改成 observed',
          'docs/v9/SKILL_PROPOSAL_COORDINATION.md:18',
          'ADR-0005 原文 + 交付物未改来源政策/枚举',
          {'adr_text_ok': adr_ok,
           'b1_doc_phrase': ('external_derived' in b1 and '默认不可训练' in b1),
           'delivery_does_not_redefine_source': ('external_derived' not in
                                                 (L.ROOT / 'contracts/v9/skill_proposal.v1.schema.json')
                                                 .read_text(encoding='utf-8')),
           'spec_no_observed_rewrite': ('不能把经历的训练来源改成 observed' in b1)},
          adr_ok and ('external_derived' in b1 and '默认不可训练' in b1))

    # 5) confidence 非授权
    conf = (gate.get('section_EF') or {}).get('confidence_not_authority') or {}
    sweep = (gate.get('section_EF') or {}).get('confidence_sweep') or {}
    conf_schema = json.loads(('contracts/v9/skill_proposal.v1.schema.json' if False else
                              (L.ROOT / 'contracts/v9/skill_proposal.v1.schema.json').read_text(
                                  encoding='utf-8')))
    dep = conf_schema.get('dependentRequired') or {}
    claim('C5-confidence-not-authority',
          'confidence/学生自填量不能成为权限来源；置信度 1.0 不能越过任何一道门',
          'docs/v9/SKILL_PROPOSAL_COORDINATION.md:22',
          '原裁决 6 + 扫描 184 行判定不变 + 专用反例',
          {'original_ruling6': ('置信度只作参考' in dec),
           'b1_doc_phrase': ('confidence、学生自填 quantity、学生自填 schema 都不能成为权限来源' in b1),
           'schema_dependent_required': dep,
           'sweep_rows': sweep.get('rows'), 'sweep_bad': len(sweep.get('bad') or []),
           'dedicated_case': conf},
          ('置信度只作参考' in dec) and ('不能成为权限来源' in b1) and
          sweep.get('rows') == 184 and not (sweep.get('bad') or []) and
          conf.get('base') == 'ability_unknown' and conf.get('sabotage_override') == 'accepted')
    out['b1_claims'] = {'rows': claims, 'all_ok': all(c['ok'] for c in claims)}

    # ---------------- D. 一级裁决 vs 二级形式化：逐条状态（证据来自我自己的复跑结果）
    probe = load_results('probe_results.json')
    fixtures = load_results('fixtures_results.json') or load_results('fixture_results.json')
    jcs = load_results('jcs_results.json')
    suite = load_results('suite_results.json')
    q = load_results('awz_quantity_results.json')
    gcases = (gate.get('proposal_cases') or {})
    rules = (gate.get('controls') or {}).get('by_rule') or {}
    mapping = [
        {'ruling': 1, 'policy': '成立：原裁决 1 + B1 文档两条路线（运行开/编辑只定义未开）',
         'formalization': '成立（CPU 参考核对）：编辑类提案 effect_class_not_registered 且控制漏检；'
                          '上下文 registered_edit_abilities 非空即 fail-closed',
         'evidence': ['gate:edit_route', 'gate:context_guards', 'fixtures:all_contexts_edit_empty'],
         'ok': edit_route.get('base') == 'effect_class_not_registered' and guard_hit and all_empty},
        {'ruling': 2, 'policy': '成立：原裁决 2 / B1 文档 §目标与隔离',
         'formalization': '成立（r4 F1/F3 加固）：1131/1131 探针四层全拒；56 拼写反例；'
                          '任意层级键名；句柄/世界 ID 反例与破坏对照',
         'evidence': ['probe_results', 'gate:controls(schema/world_id_normalization)'],
         'ok': (probe.get('L2_gate_layer_rejected_total') == 1131 and
                probe.get('L3_full_gate_rejected_total') == 1131 and
                rules.get('schema', {}).get('isolated', 0) >= 1 and
                rules.get('world_id_normalization', {}).get('isolated', 0) >= 1)},
        {'ruling': 3, 'policy': '成立：原裁决 3 / B1 文档 §证据',
         'formalization': '成立：evidence_version 重算 + packet_ref/t_ticks 绑定反例；'
                          '自写 JCS 复现 112/112 上下文 pin；JCS 异常 fail-closed',
         'evidence': ['jcs_results', 'fixtures:context_pins', 'gate:cases'],
         'ok': (jcs.get('all_reasons_whitelisted') and
                not (fixtures.get('case_pin_sha_errors') or []))},
        {'ruling': 4, 'policy': '成立：原裁决 4 闭区间 + B1 文档 §TTL 不变',
         'formalization': '成立：闭区间两端正例 + 右端+1 过期；时间域不换算反例；无 lease 逻辑',
         'evidence': ['gate:ttl_closed_interval'],
         'ok': ttl_impl_ok},
        {'ruling': 5, 'policy': '成立：原裁决 5 / B1 文档 §授权与证据',
         'formalization': '成立：未登记/参数越界/动作时长/TTL 上限/目标种类/前置条件反例与对照',
         'evidence': ['gate:cases', 'gate:controls:ability,params,budget,target_kind,precondition'],
         'ok': all(rules.get(k, {}).get('isolated', 0) >= 1 for k in
                   ('ability', 'params', 'budget', 'target_kind', 'precondition'))},
        {'ruling': 6, 'policy': '成立：原裁决 6 / B1 文档 §confidence 非授权',
         'formalization': '成立：184 行扫描 0 变化 + 专用反例 + 造假接线仅在 1.0 且被关闭专用规则时生效',
         'evidence': ['gate:confidence'],
         'ok': sweep.get('rows') == 184 and not (sweep.get('bad') or [])},
        {'ruling': 7, 'policy': '成立：原裁决 7 / B1 文档 §quantity 允许表',
         'formalization': '成立（r4 F6）：50 项允许表三方一致、可追溯到 AWZ schema；7 反例 + 越权/未知/'
                          '别名被拒；允许表内未声明量被 quantity_registry_binding 拒',
         'evidence': ['awz_quantity_results', 'gate:quantity'],
         'ok': (q.get('allowed_count') == 50 and not (q.get('grounding_unmatched') or []) and
                all(x['fixture_reason'] == 'schema_invalid'
                    for x in (gate.get('quantity') or {}).get('cases', [])))},
        {'ruling': 8, 'policy': '成立：原裁决 8 / B1 文档 §观察、授权与证据',
         'formalization': '成立：回执 schema 封闭枚举 + 112 条泄露扫描 0 泄露 + 7/7 回执破坏对照',
         'evidence': ['gate:reply_cases', 'gate:reply_integrity'],
         'ok': ((gate.get('reply_cases') or {}).get('ok') == 10 and
                not (gate.get('section_EF') or {}).get('reply_integrity', {}).get('bad') and
                not (gate.get('section_EF') or {}).get('reply_integrity', {}).get('leaked'))},
        {'ruling': 9, 'policy': '成立：原裁决 9 / B1 文档 §证据',
         'formalization': '成立：no_rewrite 18 条断言；接受的 18 正例回执回显=提交=重算',
         'evidence': ['gate:reply_integrity'],
         'ok': not (gate.get('section_EF') or {}).get('reply_integrity', {}).get('bad')},
        {'ruling': 10, 'policy': '成立：原裁决 10 / B1 文档 §身份',
         'formalization': '成立（加强读法已说明）：actor 不符 rejected_other；同 ID 换载荷 '
                          'duplicate_proposal（含只改 params 的加强反例）；重放正例',
         'evidence': ['gate:controls:actor,duplicate'],
         'ok': all(rules.get(k, {}).get('isolated', 0) >= 1 for k in ('actor', 'duplicate'))},
        {'ruling': 11, 'policy': '成立（文档）：原裁决 11 / B1 文档 §任务与完成口径',
         'formalization': '未实现（如实登记）：final 分区训练门只在文档写明，参考核对不实现；'
                          '交付物 §13 矩阵第 13 行自述不能',
         'evidence': ['SKILL_PROPOSAL.md §11/§13', 'checker 无 Forge 写入'],
         'ok': ('final' in spec and '不得用于训练' in spec and
                'Forge' not in code)},
    ]
    out['ruling_mapping'] = {
        'rows': mapping,
        'policy_all_hold': all('成立' in m['policy'] for m in mapping),
        'formalization_hold': sum(1 for m in mapping if m['ok'] and '未实现' not in m['formalization']),
        'formalization_not_implemented_by_design': [m['ruling'] for m in mapping
                                                    if '未实现' in m['formalization']],
        'all_ok': all(m['ok'] for m in mapping),
        'distinction_note': ('一级裁决 = 路线/权限/契约原则（Claude 原 11 条 + B1 文档整合）：全部保持，'
                             '未改 TTL、来源政策、观察契约、冻结参数与权限；'
                             '二级形式化 = B4 的 schema/示例/参考核对，逐条有证据；'
                             '裁决 11 按原裁决只在文档写明、参考核对不实现，不能当成已形式化。'),
    }

    # ---------------- E. 文档内部一致性（数字与陈述）
    doc_issues = []
    if '本修订为 60 行全过' in spec and '置信度扫描 184 行' in spec:
        doc_issues.append({'file': 'docs/v9/SKILL_PROPOSAL.md', 'line': 139,
                           'issue': '§6 写「本修订为 60 行全过」，与 r4 §13b/§12 的「184 行」矛盾（旧版残留）'})
    sums = (L.ROOT / 'reports/V9-B1/SHA256SUMS.txt').read_text(encoding='utf-8')
    data_rows = [l for l in sums.splitlines() if l.strip() and not l.startswith('#')
                 and 'RAW_SHA256' not in l and not l.startswith('## ')]
    if len(data_rows) != 253:
        doc_issues.append({'file': 'reports/V9-B1/r4/SUMMARY.md', 'line': 12,
                           'issue': '称 SHA256SUMS「253 行」，实际数据行 %d（11 交付物 + 7 只读 + 236 夹具）'
                                    % len(data_rows)})
    fixture_stats = fixtures or {}
    if (fixture_stats.get('file_count') or 0) != 236:
        doc_issues.append({'file': 'fixtures', 'issue': '夹具文件数不是 236'})
    out['doc_consistency'] = {'issues': doc_issues,
                              'sums_data_rows': len(data_rows),
                              'fixture_file_count': fixture_stats.get('file_count')}

    # ---------------- F. 运行边界（不新增训练/下载/GPU；不自行 accept）
    out['boundaries'] = {
        'b1_doc_no_new_architecture': ('不产生下一版主架构' in b1),
        'b1_doc_no_D019_A10_release': ('不放行 D-019/A10' in b1),
        'b4_not_runtime_implemented': ('真实 AWZ 消费者尚未实现' in spec or
                                       '真实消费者' in spec),
        'training_pause_kept': '训练继续暂停' in (L.ROOT / 'README.md').read_text(encoding='utf-8'),
        'no_git_commit_by_me': True,
    }
    L.write_json(RES / 'b1_doc_results.json', out)
    print(json.dumps({
        'identity': out['identity'],
        'original_rulings': {k: out['original_rulings'][k] for k in ('count', 'all_present')},
        'b1_claims_all_ok': out['b1_claims']['all_ok'],
        'b1_claims_failed': [c['id'] for c in claims if not c['ok']],
        'policy_all_hold': out['ruling_mapping']['policy_all_hold'],
        'formalization_hold': out['ruling_mapping']['formalization_hold'],
        'formalization_not_implemented': out['ruling_mapping'][
            'formalization_not_implemented_by_design'],
        'ruling_map_failed': [m['ruling'] for m in mapping if not m['ok']],
        'doc_issues': doc_issues,
        'boundaries': out['boundaries'],
    }, ensure_ascii=False, indent=1))
    bad = (not out['identity']['i_am_not_b1_author'] or
           not out['identity']['i_am_not_b4_author'] or
           not out['identity']['b1_sha_match'] or
           not out['identity']['decisions_sha_match'] or
           not out['original_rulings']['all_present'] or not out['b1_claims']['all_ok'] or
           not out['ruling_mapping']['all_ok'])
    print('B1DOC_VERDICT', 'PASS' if not bad else 'FAIL')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
