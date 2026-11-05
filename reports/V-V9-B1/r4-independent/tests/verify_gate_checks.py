"""V9.B6 独立复核：门禁判定重跑 + quantity/编辑/TTL/置信度/回执泄露/登记条目矩阵。

在进程内调用被测 gate_and_check（被测对象），但判据/期望全部来自：
  - reports/V9-B1/COORDINATOR_DECISIONS.md 裁决 1–11
  - B4-r4-DECISIONS.md F1–F7
  - EXPECTATIONS.json 的冻结期望（逐条比对，不信任 check_result.json 自述）
"""
import importlib.util
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'
RES.mkdir(parents=True, exist_ok=True)
FIX = L.FIXTURE
SAB = L.ROOT / 'reports/V9-B1/sabotage-schemas'


def load_author():
    spec = importlib.util.spec_from_file_location('author_checker', L.CHECKER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    A = load_author()
    ps = A.schema_load(A.PROPOSAL_SCHEMA)
    rs = A.schema_load(A.REPLY_SCHEMA)
    es = A.schema_load(A.ENTRY_SCHEMA)
    exp = L.load(FIX / 'EXPECTATIONS.json')
    pins = exp['context_identity_pins']
    cases = exp['cases']
    out = {}

    def ctx_of(c):
        return L.load(FIX / 'contexts' / c['context_file'])

    def prop_of(c):
        return L.load(FIX / c['dir'] / c['proposal_file'])

    def run(prop, ctx, pin=None, schema=None, rsch=None, disabled=()):
        pin = pin if pin is not None else L.jcs_sha(ctx)
        return A.gate_and_check(prop, ctx, pin, schema or ps, rsch or rs, disabled)

    # ---------------- A. 112 条提案用例逐条重跑（对照冻结期望）
    case_rows, case_bad = [], []
    for c in cases:
        if c['dir'] not in ('valid', 'invalid'):
            continue
        prop, ctx = prop_of(c), ctx_of(c)
        r = run(prop, ctx, pins[c['name']])
        want = 'accepted' if c['dir'] == 'valid' else 'rejected'
        got = r.get('decision')
        reason_ok = (c['expected_reason_code'] is None or r.get('reason_code') == c['expected_reason_code'])
        ok = got == want and reason_ok and r.get('ok') is True
        row = {'name': c['name'], 'rule': c['rule'], 'want': want,
               'want_reason': c['expected_reason_code'], 'got': got,
               'got_reason': r.get('reason_code'), 'ok_flag': r.get('ok'),
               'reply_monotone': r.get('reply') is not None, 'ok': ok}
        case_rows.append(row)
        if not ok:
            case_bad.append(row)
    out['proposal_cases'] = {'total': len(case_rows), 'ok': sum(1 for r in case_rows if r['ok']),
                             'bad': case_bad}

    # ---------------- B. 回执 10 条 + 7 条回执破坏对照（真实子进程 reply 模式）
    reply_rows, reply_bad = [], []
    rcases = [c for c in cases if c['dir'] not in ('valid', 'invalid')]
    for c in rcases:
        sub = 'valid' if c['expected_decision'] == 'valid' else 'invalid'
        p = FIX / 'replies' / sub / c['reply_file']
        r = L.run_cli(['reply', '--reply', str(p), '--reply-schema', str(A.REPLY_SCHEMA)])
        want_rc = 0 if c['expected_decision'] == 'valid' else 1
        ok = r['returncode'] == want_rc and not r['json_parse_exception']
        reply_rows.append({'name': c['name'], 'valid': c['expected_decision'] == 'valid',
                           'rc': r['returncode'], 'want_rc': want_rc, 'ok': ok,
                           'errors': (r['payload'] or {}).get('errors')})
        if not ok:
            reply_bad.append(reply_rows[-1])
    out['reply_cases'] = {'total': len(reply_rows), 'ok': sum(1 for r in reply_rows if r['ok']),
                          'bad': reply_bad}

    # ---------------- C. 94 条破坏对照：关闭规则/变异 schema 后必须漏检（子进程）
    ctrl_rows, ctrl_bad = [], []
    for c in cases:
        if not c.get('control'):
            continue
        if c['dir'] not in ('valid', 'invalid'):
            # 回执破坏对照：基础回执必须 schema 拒；变异 reply-schema 后必须接受（真实漏检）
            sub = 'valid' if c['expected_decision'] == 'valid' else 'invalid'
            rpath = FIX / 'replies' / sub / c['reply_file']
            base_args = ['reply', '--reply', str(rpath), '--reply-schema', str(A.REPLY_SCHEMA)]
            base = L.run_cli(base_args)
            cargs = ['reply', '--reply', str(rpath)]
            mut = c['control'].split(',')[0].split(':', 1)[1]
            cargs += ['--reply-schema', str(SAB / (mut + '.json'))]
            ctl = L.run_cli(cargs)
            base_rejected = base['returncode'] == 1
            isolated = base_rejected and ctl['returncode'] == 0 and ctl['stderr'].strip() == ''
            row = {'name': c['name'], 'rule': c.get('rule') or 'reply_validation', 'kind': 'reply',
                   'control': c['control'], 'base_rc': base['returncode'],
                   'control_rc': ctl['returncode'], 'isolated': isolated,
                   'base_rejected': base_rejected, 'schema_layer_catches': True,
                   'stderr_empty': ctl['stderr'].strip() == ''}
            ctrl_rows.append(row)
            if not (base_rejected and isolated):
                ctrl_bad.append(row)
            continue
        prop_p = FIX / c['dir'] / c['proposal_file']
        ctx_p = FIX / 'contexts' / c['context_file']
        base_args = ['gate', '--proposal', str(prop_p), '--context', str(ctx_p),
                     '--expected-context-sha256', pins[c['name']],
                     '--schema', str(A.PROPOSAL_SCHEMA), '--reply-schema', str(A.REPLY_SCHEMA)]
        base = L.run_cli(base_args)
        cargs = list(base_args)
        for part in c['control'].split(','):
            if part.startswith('mutation:'):
                name = part.split(':', 1)[1]
                cargs[cargs.index('--schema') + 1] = str(SAB / (name + '.json'))
                if name in ('proposal_no_additional_properties', 'proposal_no_world_id_key'):
                    cargs += ['--disable', 'world_id_normalization']
            else:
                rule = part.split(':', 1)[1] if part.startswith('disable:') else part
                if rule:
                    cargs += ['--disable', rule]
        ctl = L.run_cli(cargs)
        isolated = (base['returncode'] == 1 and ctl['returncode'] == 0 and
                    (ctl['payload'] or {}).get('decision') == 'accepted' and
                    ctl['stderr'].strip() == '')
        base_rejected = base['returncode'] == 1 and ((base['payload'] or {}).get('decision') == 'rejected')
        # 非隔离对照必须由「层 1 schema 正则已经先拒」解释（文档 §2.4 的口径）：
        # 独立判据 = 该反例的拼写别名键名本身被 schema 的 world_id_key 正则命中。
        wkey_pat = re.compile(ps['$defs']['world_id_key']['pattern'])
        alias_key = c.get('alias_key')
        schema_layer_catches = bool(alias_key) and bool(wkey_pat.search(alias_key))
        if not schema_layer_catches:
            # 兜底：若 schema 校验该提案确实 invalid，再记一层证据
            try:
                schema_errors = A.errors_of(A.Draft202012Validator(ps), L.load(prop_p))
                schema_layer_catches = bool(schema_errors)
            except Exception:
                schema_layer_catches = False
        row = {'name': c['name'], 'rule': c['rule'], 'control': c['control'],
               'base_rc': base['returncode'], 'base_reason': (base['payload'] or {}).get('reason_code'),
               'control_rc': ctl['returncode'],
               'control_decision': (ctl['payload'] or {}).get('decision'),
               'isolated': isolated, 'base_rejected': base_rejected,
               'schema_layer_catches': schema_layer_catches,
               'stderr_empty': ctl['stderr'].strip() == ''}
        ctrl_rows.append(row)
        # 判定：base 必须被拒；isolated 或（非 isolated 且 schema 层已先拒）都可接受；
        # 其余（base 未拒 / 关闭后既没漏检也无法用 schema 层解释 / stderr 不干净）算异常。
        if not base_rejected or not row['stderr_empty'] or                 (not isolated and not schema_layer_catches):
            ctrl_bad.append(row)
    out['controls'] = {
        'total': len(ctrl_rows),
        'isolated': sum(1 for r in ctrl_rows if r['isolated']),
        'nonisolated_explained_by_schema': sum(1 for r in ctrl_rows
                                              if not r['isolated'] and r['schema_layer_catches']),
        'bad': ctrl_bad,
        'by_rule': {},
    }
    by_rule = {}
    for r in ctrl_rows:
        d = by_rule.setdefault(r['rule'], {'total': 0, 'isolated': 0})
        d['total'] += 1
        d['isolated'] += 1 if r['isolated'] else 0
    out['controls']['by_rule'] = by_rule
    out['controls']['rules_without_isolated_control'] = [
        r for r, d in by_rule.items() if d['isolated'] == 0]

    # ---------------- D. quantity：7 条反例 + 越权/未知/别名 + 上下文守卫
    # D1 反例重跑（上面 A 已覆盖判定；这里抽取检查原因码+分层）
    q_rows = []
    for c in cases:
        if c['dir'] not in ('valid', 'invalid'):
            continue
        if c.get('rule') not in ('quantity_allowlist', 'quantity_registry_binding') and \
                not c['name'].startswith('quantity_'):
            continue
        if c['dir'] not in ('valid', 'invalid'):
            continue
        prop, ctx = prop_of(c), ctx_of(c)
        r = run(prop, ctx, pins[c['name']])
        r_noschema = run(prop, ctx, pins[c['name']], disabled=('schema',))
        r_noq = run(prop, ctx, pins[c['name']], disabled=('schema', 'quantity_allowlist',
                                                         'quantity_registry_binding'))
        q_rows.append({'name': c['name'], 'fixture_reason': r.get('reason_code'),
                       'world_log': r.get('world_side_log'),
                       'without_schema_layer': r_noschema.get('reason_code'),
                       'without_schema_layer_log': r_noschema.get('world_side_log'),
                       'without_quantity_checks': r_noq.get('decision')})
    # D2 独立构造：允许表内但条目未声明的量
    ctx0 = ctx_of([c for c in cases if c['name'] == 'valid_minimal_handle_target'][0])
    base_prop = prop_of([c for c in cases if c['name'] == 'valid_minimal_handle_target'][0])
    pin0 = L.jcs_sha(ctx0)
    over = deepcopy(base_prop)
    over['expected_outcomes'][0]['quantity'] = 'audio_events.type'   # 在 50 项允许表内
    r_full = run(over, ctx0, pin0)
    r_unbind = run(over, ctx0, pin0, disabled=('quantity_registry_binding',))
    unknown = deepcopy(base_prop)
    unknown['expected_outcomes'][0]['quantity'] = 'detection.geo_truth_m'
    chain = []
    for dis in ((), ('schema',), ('schema', 'quantity_allowlist'),
                ('schema', 'quantity_allowlist', 'quantity_registry_binding')):
        r = run(unknown, ctx0, pin0, disabled=dis)
        chain.append({'disabled': list(dis), 'decision': r.get('decision'),
                      'reason': r.get('reason_code'), 'log': r.get('world_side_log')})
    alias_rows = []
    for q in ['world.id', 'world_id', 'hidden_contact', 'contact_id', 'entityId', 'entities_id',
              'worlds_id', 'ids']:
        prop = deepcopy(base_prop)
        prop['expected_outcomes'][0]['quantity'] = q
        r1 = run(prop, ctx0, pin0)
        r2 = run(prop, ctx0, pin0, disabled=('schema',))
        alias_rows.append({'quantity': q, 'full_reason': r1.get('reason_code'),
                           'schema_disabled_reason': r2.get('reason_code'),
                           'schema_disabled_log': r2.get('world_side_log'),
                           'alias_branch_hit': 'quantity_forbidden_alias' in str(r2.get('world_side_log'))})
    nonstr = deepcopy(base_prop)
    nonstr['expected_outcomes'][0]['quantity'] = 42
    r_nonstr = run(nonstr, ctx0, pin0)
    # 上下文 observable_registry 守卫
    def ctx_variant(mut):
        c = deepcopy(ctx0)
        mut(c)
        return c, L.jcs_sha(c)
    guard_rows = []

    def g(name, mut, want_prefix):
        c, pin = ctx_variant(mut)
        r = run(base_prop, c, pin)
        errs = r.get('errors') or []
        hit = any(str(e).startswith(want_prefix) for e in errs)
        guard_rows.append({'guard': name, 'decision': r.get('decision'), 'errors': errs[:4],
                           'hit_expected': hit})

    g('edit_set_not_empty', lambda c: c['ability_registry'].__setitem__(
        'registered_edit_abilities', ['abil-approach-object']), 'context_edit_set_not_empty')
    g('observable_unknown', lambda c: c['ability_registry']['observable_registry'][
        'quantities'].append('detection.geo_truth_m'), 'context_observable_not_derived')
    g('observable_forbidden_alias', lambda c: c['ability_registry']['observable_registry'][
        'quantities'].append('entities_id'), 'context_observable_forbidden')
    g('observable_source_sha', lambda c: c['ability_registry']['observable_registry'].__setitem__(
        'source_sha256', '0' * 64), 'context_observable_source_sha256')
    # 编辑类条目本身可以登记（裁决 1 只要求「已登记编辑能力集合为空」；引用它的提案必拒）
    c_edit = deepcopy(ctx0)
    c_edit['ability_registry']['entries'].append(dict(
        c_edit['ability_registry']['entries'][0], ability_id='abil-edit-x', effect_class='edit'))
    pe = L.jcs_sha(c_edit)
    prop_edit = deepcopy(base_prop)
    prop_edit['ability_id'] = 'abil-edit-x'
    r_edit_entry = run(prop_edit, c_edit, pe)
    guard_rows.append({'guard': 'edit_entry_registered_but_proposal_rejected',
                       'decision': r_edit_entry.get('decision'),
                       'reason': r_edit_entry.get('reason_code'),
                       'errors': (r_edit_entry.get('errors') or [])[:2],
                       'hit_expected': r_edit_entry.get('reason_code') == 'effect_class_not_registered'})
    # 允许表内且已声明的量在 context 可信表里被移除 → 必拒
    c2 = deepcopy(ctx0)
    qs = c2['ability_registry']['observable_registry']['quantities']
    c2['ability_registry']['observable_registry']['quantities'] = [q for q in qs
                                                                  if q != 'detection.rel_position_m']
    pin2 = L.jcs_sha(c2)
    r_removed = run(base_prop, c2, pin2)
    out['quantity'] = {'cases': q_rows, 'overreach': {
        'full': {'decision': r_full.get('decision'), 'reason': r_full.get('reason_code'),
                 'log': r_full.get('world_side_log')},
        'without_binding': {'decision': r_unbind.get('decision'),
                            'reason': r_unbind.get('reason_code')}},
        'unknown_chain': chain, 'alias_rows': alias_rows, 'nonstr': {
            'decision': r_nonstr.get('decision'), 'reason': r_nonstr.get('reason_code')},
        'context_guards': guard_rows,
        'trusted_table_removed_quantity': {'decision': r_removed.get('decision'),
                                           'reason': r_removed.get('reason_code'),
                                           'world_log': r_removed.get('world_side_log'),
                                           'errors': (r_removed.get('errors') or [])[:3]},
        'allowlist_internal_aliases': [q for q in A.OBSERVABLE_QUANTITIES
                                       if A.is_forbidden_world_id_key(q)],
        'my_indep_allowlist_aliases': [q for q in A.OBSERVABLE_QUANTITIES
                                       if L.is_ident_key_indep(q)]}

    # ---------------- E. 编辑路线 / TTL / 置信度 / no_rewrite / 回执泄露
    sec = {}
    # 编辑类：反例 + 控制
    edit_c = [c for c in cases if c.get('rule') == 'effect_class'][0]
    ep, ec = prop_of(edit_c), ctx_of(edit_c)
    er = run(ep, ec, pins[edit_c['name']])
    er_off = run(ep, ec, pins[edit_c['name']], disabled=('effect_class',))
    sec['edit_route'] = {'base': er.get('reason_code'), 'disable_effect_class': er_off.get('decision'),
                         'source_edit_abilities_empty': ec['ability_registry'][
                             'registered_edit_abilities'] == []}
    # TTL 闭区间：三份夹具的 tick 关系 + 判定
    ttl = []
    for name in ('valid_ttl_lower_boundary', 'valid_ttl_upper_boundary', 'ttl_expired'):
        c = [x for x in cases if x['name'] == name][0]
        p, cx = prop_of(c), ctx_of(c)
        r = run(p, cx, pins[name])
        ttl.append({'name': name, 'basis_t_ticks': p['basis']['t_ticks'],
                    'ttl_ticks': p['ttl_ticks'], 'current_tick': cx['round']['current_tick'],
                    'right_endpoint': p['basis']['t_ticks'] + p['ttl_ticks'],
                    'decision': r.get('decision'), 'reason': r.get('reason_code'),
                    'interval_holds': (r.get('decision') == 'accepted') ==
                                      (cx['round']['current_tick'] <= p['basis']['t_ticks'] +
                                       p['ttl_ticks'])})
    sec['ttl_closed_interval'] = ttl
    # 置信度扫描：所有负例改 confidence=1.0/0.0 判定与原因码不变，evidence_version 不变
    conf_bad, conf_rows = [], 0
    for c in cases:
        if c['dir'] != 'invalid' or c.get('rule') == 'duplicate':
            continue
        p, cx = prop_of(c), ctx_of(c)
        base = run(p, cx, pins[c['name']])
        for val in (1.0, 0.0):
            p2 = deepcopy(p)
            p2['confidence'] = val
            r = run(p2, cx, pins[c['name']])
            conf_rows += 1
            if (r.get('reason_code') != base.get('reason_code') or
                    p2.get('evidence_version') != p.get('evidence_version')):
                conf_bad.append({'name': c['name'], 'confidence': val,
                                 'base': base.get('reason_code'),
                                 'got': r.get('reason_code')})
    sec['confidence_sweep'] = {'rows': conf_rows, 'bad': conf_bad}
    # confidence = 1.0 + 未登记能力（专用反例）+ 造假覆盖对照
    conf_c = [c for c in cases if c.get('rule') == 'confidence_independence'][0]
    cp, cc = prop_of(conf_c), ctx_of(conf_c)
    cr = run(cp, cc, pins[conf_c['name']])
    cr_off = run(cp, cc, pins[conf_c['name']], disabled=('confidence_independence',))
    # 关掉检查但 confidence != 1.0 时不得被 confidence 分支短路（证明该分支只是造假接线）
    cp_half = deepcopy(cp)
    cp_half['confidence'] = 0.5
    cr_half = run(cp_half, cc, pins[conf_c['name']], disabled=('confidence_independence',))
    sec['confidence_not_authority'] = {
        'base': cr.get('reason_code'), 'sabotage_override': cr_off.get('decision'),
        'sabotage_only_at_1': cr_half.get('decision'),
        'base_world_log': cr.get('world_side_log')}
    # no_rewrite + 回执白名单 + 泄露扫描（自写）
    nw_bad, leak_bad, replies = [], [], 0
    for c in cases:
        if c['dir'] not in ('valid', 'invalid'):
            continue
        p, cx = prop_of(c), ctx_of(c)
        r = run(p, cx, pins[c['name']])
        reply = r.get('reply')
        replies += 1
        # 回执结构：只允许 skill_gate_reply.v1 字段
        if reply is not None:
            errs = A.errors_of(A.Draft202012Validator(rs), reply)
            if errs:
                nw_bad.append({'name': c['name'], 'what': 'reply_schema', 'errors': errs[:3]})
            # 泄露扫描：自写世界侧 token 汇总
            toks = set(cx['world_side'].get('handle_entity_map', {}).values())
            for v in cx['world_side'].get('hidden_state', {}).values():
                toks.update(v if isinstance(v, list) else [v])
            blob = json.dumps(reply, ensure_ascii=False)
            leaked = sorted(t for t in toks if t and t in blob)
            if leaked:
                leak_bad.append({'name': c['name'], 'leaked': leaked[:3]})
            # 原因码白名单（以 reply schema enum 为唯一来源）
            wl = set(rs['$defs']['visible_reason_code']['enum'])
            if reply.get('reason_code') not in wl:
                nw_bad.append({'name': c['name'], 'what': 'reason_not_whitelisted'})
            if c['dir'] == 'valid':
                if not (reply.get('evidence_version') == p.get('evidence_version') ==
                        L.jcs_sha(p['basis'])):
                    nw_bad.append({'name': c['name'], 'what': 'evidence_rewritten'})
    sec['reply_integrity'] = {'replies_scanned': replies, 'bad': nw_bad, 'leaked': leak_bad}

    # ---------------- F. 能力登记条目矩阵（schema 层 + registry_problems 层，自建用例）
    base_entry = {
        'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-matrix',
        'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': ['handle'],
        'max_actions': 1, 'max_duration_ticks': 12, 'max_ttl_ticks': 60,
        'param_schema': {'type': 'object', 'additionalProperties': False, 'required': [],
                         'properties': {'speed_mps': {'type': 'number'}}},
        'preconditions': [], 'observable_names': ['detection.rel_position_m']}
    ev = A.Draft202012Validator(es)
    matrix, matrix_bad = [], []

    def entry_row(name, mut, want_schema_invalid, want_clean_checker):
        e = deepcopy(base_entry)
        mut(e)
        schema_invalid = not ev.is_valid(e)
        try:
            ctx = deepcopy(ctx0)
            ctx['ability_registry']['entries'].append(e)
            probs = A.registry_problems(ctx)
            clean = [p for p in probs if 'entry:' in p or 'entry_' in p]
            exc = None
        except Exception as ex:
            probs, clean, exc = [], [], type(ex).__name__ + ': ' + str(ex)
        row = {'name': name, 'schema_invalid': schema_invalid,
               'want_schema_invalid': want_schema_invalid,
               'checker_problems': probs[:4], 'exception': exc,
               'want_clean_checker': want_clean_checker, 'ok': True}
        row['ok'] = ((schema_invalid == want_schema_invalid) and
                     (bool(clean) if (want_clean_checker and exc is None) else True) and
                     (exc is None or exc.startswith('NameError')))
        matrix.append(row)
        if not row['ok']:
            matrix_bad.append(row)

    def m(name, ps):
        def f(e):
            e['param_schema'] = ps
        return f

    entry_row('valid_closed', lambda e: None, False, False)
    entry_row('patternProperties', m('patternProperties', {
        'type': 'object', 'additionalProperties': False,
        'patternProperties': {'^h-': {'type': 'string'}},
        'properties': {'speed_mps': {'type': 'number'}}}), False, True)
    entry_row('nested_patternProperties', m('nested_patternProperties', {
        'type': 'object', 'additionalProperties': False,
        'properties': {'tags': {'type': 'object',
                                'patternProperties': {'^x': {'type': 'string'}}}}}), False, True)
    entry_row('dynamic_ref', m('dynamic_ref', {
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'$ref': '#/$defs/num'}},
        '$defs': {'num': {'type': 'number'}}}), False, True)
    entry_row('if_then', m('if_then', {
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'type': 'number'}},
        'if': {'required': ['speed_mps']}, 'then': {'required': ['stride_m']}}), False, True)
    entry_row('one_of', m('one_of', {
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'oneOf': [{'type': 'number'}, {'type': 'string'}]}}}),
        False, True)
    entry_row('additional_open_true', m('additional_open_true', {
        'type': 'object', 'additionalProperties': True,
        'properties': {'speed_mps': {'type': 'number'}}}), True, False)
    for propname in ('WORLD_ID', 'entities_id', 'objectId', 'hidden_contact', 'entity_id'):
        entry_row('prop_' + propname, m(propname, {
            'type': 'object', 'additionalProperties': False,
            'properties': {propname: {'type': 'string'}}}), False, True)
    for obs in ('detection.geo_truth_m', 'world_id', 'entities_id'):
        entry_row('obs_' + obs, lambda e, o=obs: e.__setitem__('observable_names', [o]),
                  True, False)
    name_errors = [r for r in matrix if r['exception']]
    # 端到端验证 NameError 行仍 fail-closed：把该条目塞进冻结上下文，CLI 必须拒绝（非 traceback 给用户）
    e2e = []
    for name in ('prop_WORLD_ID', 'prop_entities_id'):
        row = next(r for r in matrix if r['name'] == name)
        e = deepcopy(base_entry)
        entry_row_mut = {'prop_WORLD_ID': lambda x: x['param_schema'].__setitem__(
            'properties', {'WORLD_ID': {'type': 'string'}}),
            'prop_entities_id': lambda x: x['param_schema'].__setitem__(
                'properties', {'entities_id': {'type': 'string'}})}[name]
        entry_row_mut(e)
        c = deepcopy(ctx0)
        c['ability_registry']['entries'].append(e)
        pin = L.jcs_sha(c)
        pth = OUT / 'tmp' / (name + '_ctx.json')
        L.write_json(pth, c)
        r = L.run_cli(L.gate_args(FIX / 'valid' / '01_valid_minimal_handle_target.json', pth, pin))
        payload = r['payload'] or {}
        e2e.append({'name': name, 'rc': r['returncode'], 'reason': payload.get('reason_code'),
                    'errors': payload.get('errors'), 'world_log': payload.get('world_side_log'),
                    'stderr_has_traceback': 'Traceback' in r['stderr'],
                    'fail_closed_clean_json': (r['returncode'] == 1 and not r['json_parse_exception']
                                               and payload.get('reason_code') == 'schema_invalid')})
    out['registry_entry_matrix'] = {'rows': matrix, 'bad': matrix_bad,
                                    'name_error_rows': [r['name'] for r in name_errors],
                                    'end_to_end_name_error': e2e,
                                    'note': ('check_schema_props_forbidden 对 forbidden 属性名调用未定义 here()，'
                                             '抛 NameError；CLI 兜底为 schema_invalid（fail-closed），'
                                             '但不是干净上下文拒绝，属实现缺陷（非阻断）。')}
    out['registry_entries_in_context_zero'] = len(ctx0['ability_registry']['entries'])

    # ---------------- G. --disable 卫生 / context_identity 不可关闭
    hy = []
    for args, want_rc, name in (
            (['gate', '--proposal', str(FIX / 'valid' / '01_valid_minimal_handle_target.json'),
              '--context', str(FIX / 'contexts' / '01_valid_minimal_handle_target.json'),
              '--expected-context-sha256', pins['valid_minimal_handle_target'],
              '--disable', 'no_such_rule_zzz'], 2, 'unknown_rule'),
            (['gate', '--proposal', str(FIX / 'invalid' / '93_handle_not_in_packet.json'),
              '--context', str(FIX / 'contexts' / '93_handle_not_in_packet.json'),
              '--expected-context-sha256', pins['handle_not_in_packet'],
              '--disable', 'handle'], 0, 'known_rule_disable'),
            (['gate', '--proposal', str(FIX / 'valid' / '01_valid_minimal_handle_target.json'),
              '--context', str(FIX / 'contexts' / '01_valid_minimal_handle_target.json'),
              '--expected-context-sha256', pins['valid_minimal_handle_target'],
              '--disable', 'context_identity'], 2, 'context_identity_not_disableable')):
        r = L.run_cli(args)
        hy.append({'name': name, 'rc': r['returncode'], 'want_rc': want_rc,
                   'ok': r['returncode'] == want_rc, 'payload': r['payload']})
    out['disable_hygiene'] = hy

    # ---------------- H. 隐写：合法键的值偷带（文档 §13 第 3/4 行如实登记）
    import verify_probe as VP
    probe_ctx = VP.build_probe_context()
    probe_pin = L.jcs_sha(probe_ctx)
    smuggle = VP.build_proposal(probe_ctx, {'tags': [{'note': 'entity-7f3a41c9b2e05d18'}]})
    r_sm = run(smuggle, probe_ctx, probe_pin)
    out['steganography'] = {
        'value_smuggle_via_legal_field_accepted': r_sm.get('decision') == 'accepted',
        'value_smuggle_field': 'params.tags[0].note（合法字符串参数值）',
        'real_entity_id': 'entity-7f3a41c9b2e05d18',
        'gate_reason': r_sm.get('reason_code'),
        'doc_concedes': {'params_value_level': 'docs §13 row 3 不能',
                         'arbitrary_steganography': 'docs §13 row 4 不能/未实现',
                         'no_general_proof': True},
        'arg_note': ('字段名判定无法证明数值/字符串内容不承载外部真值；合法键与合法枚举值域之外，'
                     '提案可携带任意字符串，门禁本卡不做值语义检查（`param_value` 无值约束）。'
                     '故不存在任意隐写的通用否定证明；B4 只在 §13 第 3/4 行如实登记未实现。')}

    out['section_EF'] = sec
    L.write_json(RES / 'gate_results.json', out)
    print(json.dumps({
        'proposal_cases': {k: out['proposal_cases'][k] for k in ('total', 'ok')},
        'reply_cases': {k: out['reply_cases'][k] for k in ('total', 'ok')},
        'controls': {k: out['controls'][k] for k in ('total', 'isolated',
                                                      'nonisolated_explained_by_schema')},
        'rules_without_isolated_control': out['controls']['rules_without_isolated_control'],
        'control_bad': len(out['controls']['bad']),
        'quantity_cases': [(r['name'], r['fixture_reason']) for r in out['quantity']['cases']],
        'overreach': out['quantity']['overreach'],
        'unknown_chain': [(c['disabled'], c['decision'], c['reason'])
                          for c in out['quantity']['unknown_chain']],
        'alias_rows': [(r['quantity'], r['full_reason'], r['schema_disabled_reason'],
                        r['alias_branch_hit']) for r in out['quantity']['alias_rows']],
        'context_guards': out['quantity']['context_guards'],
        'edit_route': sec['edit_route'],
        'ttl': [(r['name'], r['decision'], r['reason'], r['interval_holds'])
                for r in sec['ttl_closed_interval']],
        'confidence': sec['confidence_not_authority'],
        'confidence_sweep': {k: sec['confidence_sweep'][k] for k in ('rows',)},
        'confidence_sweep_bad': len(sec['confidence_sweep']['bad']),
        'reply_integrity_bad': len(sec['reply_integrity']['bad']),
        'reply_leaked': len(sec['reply_integrity']['leaked']),
        'registry_matrix_bad': [(r['name'], r['schema_invalid'], r['checker_problems'],
                                 r['exception']) for r in matrix_bad],
        'matrix_exceptions': [(r['name'], r['exception']) for r in matrix if r['exception']],
        'registry_matrix_rows': len(matrix),
        'disable_hygiene': [(r['name'], r['rc'], r['ok']) for r in hy],
        'steganography': out['steganography']['value_smuggle_via_legal_field_accepted'],
    }, ensure_ascii=False, indent=1))
    bad = (case_bad or reply_bad or ctrl_bad or sec['confidence_sweep']['bad'] or
           sec['reply_integrity']['bad'] or sec['reply_integrity']['leaked'] or matrix_bad or
           not all(r['fail_closed_clean_json'] for r in e2e) or
           not all(r['ok'] for r in hy) or not all(g['hit_expected'] for g in guard_rows))
    print('GATE_VERDICT', 'PASS' if not bad else 'FAIL')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
