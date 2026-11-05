#!/usr/bin/env python3
"""V9.B5 独立复核 harness（复核者 deepseek-flash-r8t4 自写；不复用作者核对函数）。

阶段：
  oracle  自写 JCS 自测 + 52 份冻结上下文身份复现 + 夹具清单复核 + 我的 oracle 对作者 62 条夹具交叉
  probe   系统化键名变体探针（大小写/分隔符/复数/11 标识词 × id 词元），覆盖 params 任意层级与
          能力登记 param_schema 属性名；分层记录 schema 层与规范化层各自是否拦下
  adverse 自写不利反例：真实子进程非零退出 + 配对破坏对照真实零退出（并区分"崩溃"与"合法拒绝"）
  suite   复跑作者 --suite：退出码/耗时/交付目录是否被改写/check_result.json 是否 byte-identical

所有输出只写 reports/V-V9-B1/（phase suite 会先备份作者目录下的 check_result.json，
比对后若被改写则原样恢复并在报告里登记）。
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[2]
MY = Path(__file__).resolve().parent
FIX = REPO / 'contracts/v9/examples/skill_proposal_v1'
AUTHOR = REPO / 'reports/V9-B1/check_skill_proposal.py'
AUTHOR_OUT = REPO / 'reports/V9-B1'
SABOTAGE = AUTHOR_OUT / 'sabotage-schemas'
PROPOSAL_SCHEMA_PATH = REPO / 'contracts/v9/skill_proposal.v1.schema.json'
REPLY_SCHEMA_PATH = REPO / 'contracts/v9/skill_gate_reply.v1.schema.json'
ENTRY_SCHEMA_PATH = REPO / 'contracts/v9/ability_registry_entry.v0.schema.json'
VENV_PY = '/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python'

sys.path.insert(0, str(MY))
import oracle_r3 as O  # noqa: E402  自写 oracle

import jsonschema  # noqa: E402


def wjson(name, obj):
    p = MY / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + '\n', encoding='utf-8')
    return p


def load_author():
    spec = importlib.util.spec_from_file_location('author_check_r3', AUTHOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.configure_paths(str(REPO))
    return mod


def hash_tree(root):
    root = Path(root)
    out = {}
    for p in sorted(root.rglob('*')):
        if p.is_file():
            out[str(p.relative_to(REPO))] = (O.sha256_file(p), int(p.stat().st_mtime_ns))
    return out


def tree_diff(before, after):
    changed, added, removed = [], [], []
    for k, v in after.items():
        if k not in before:
            added.append(k)
        elif before[k] != v:
            changed.append(k)
    for k in before:
        if k not in after:
            removed.append(k)
    return {'changed': changed, 'added': added, 'removed': removed}


# ---------------------------------------------------------------- phase oracle

JCS_VECTORS = [
    ({}, '{}'),
    ({'b': 1, 'a': 2}, '{"a":2,"b":1}'),
    ({'\ufffd': 1, '\U00010000': 2}, '{"\U00010000":2,"\ufffd":1}'),
    ({'\u20ac': 'e', 'a': 'a'}, '{"a":"a","\u20ac":"e"}'),
    ({'n': None, 't': True, 'f': False}, '{"f":false,"n":null,"t":true}'),
    ([1, 'a', None, True], '[1,"a",null,true]'),
    ({'s': '"\\\b\f\n\r\t' + '\x01'}, '{"s":"\\"\\\\\\b\\f\\n\\r\\t\\u0001"}'),
    ({'e': '\u00e9\U0001f600'}, '{"e":"\u00e9\U0001f600"}'),
    (1e21, '1e+21'),
    (1e20, '100000000000000000000'),
    (1e-6, '0.000001'),
    (1e-7, '1e-7'),
    (-0.0, '0'),
    (0.1, '0.1'),
    (1.0, '1'),
    (100.0, '100'),
    (1.5, '1.5'),
    (-1.5, '-1.5'),
    (2 ** 53 - 1, '9007199254740991'),
    (1.2e-7, '1.2e-7'),
    (1.7976931348623157e308, '1.7976931348623157e+308'),
]


def phase_oracle():
    res = {'jcs_vectors': [], 'pins': {}, 'manifest': {}, 'evidence': {}, 'cross': {}, 'jcs_vs_author': {}}
    ok = 0
    for obj, expect in JCS_VECTORS:
        try:
            got = O.jcs(obj)
        except Exception as exc:  # noqa: BLE001
            got = 'EXC:' + repr(exc)
        good = got == expect
        ok += good
        res['jcs_vectors'].append({'input': repr(obj)[:60], 'expect': expect, 'got': got, 'ok': good})
    res['jcs_vectors_ok'] = sum(1 for v in res['jcs_vectors'] if v['ok'])
    res['jcs_vectors_total'] = len(JCS_VECTORS)

    exp = O.load_json(FIX / 'EXPECTATIONS.json')
    pins = exp['context_identity_pins']
    cases = exp['cases']
    author = load_author()

    # 1) 上下文身份 pins：我的 JCS 能否复现作者固定的 52 个 pin
    pin_ok = 0
    pin_bad = []
    jcs_agree = 0
    jcs_checked = 0
    for c in cases:
        ctx_path = FIX / 'contexts' / (c['name'] + '.json')
        if not ctx_path.exists():
            continue
        ctx = O.load_json(ctx_path)
        mine = O.sha256_jcs(ctx)
        if c['name'] in pins:
            if mine == pins[c['name']]:
                pin_ok += 1
            else:
                pin_bad.append({'case': c['name'], 'mine': mine, 'pin': pins[c['name']]})
        try:
            theirs = author.jcs(ctx).decode('utf-8')
        except Exception as exc:  # noqa: BLE001
            theirs = 'EXC:' + repr(exc)
        jcs_checked += 1
        if theirs == O.jcs(ctx):
            jcs_agree += 1
    res['pins'] = {'ok': pin_ok, 'total': len(pins), 'bad': pin_bad[:5]}
    res['jcs_vs_author'] = {'agree': jcs_agree, 'checked': jcs_checked}

    # 2) 夹具清单：重算每份文件的 sha256，与 EXPECTATIONS 登记值比对
    #    注意（复核发现）：EXPECTATIONS 对提案登记的是**文件原始字节 sha256**，
    #    对上下文登记的却是**JCS 规范摘要**（= context_identity_pins）。两者口径不同。
    man_ok, man_bad = 0, []
    hash_semantics = []
    for c in cases:
        if c.get('expected_decision') in ('accepted', 'rejected'):
            p = FIX / c['dir'] / (c['name'] + '.json')
            if p.exists() and c.get('proposal_sha256'):
                got = O.sha256_file(p)
                if got == c['proposal_sha256']:
                    man_ok += 1
                else:
                    man_bad.append({'name': c['name'], 'kind': 'proposal(raw file)', 'got': got,
                                    'want': c['proposal_sha256']})
            cx = FIX / 'contexts' / (c['name'] + '.json')
            if cx.exists():
                raw = O.sha256_file(cx)
                canon = O.sha256_jcs(O.load_json(cx))
                want = c.get('context_sha256')
                ok = (canon == want)
                man_ok += int(ok)
                if not ok:
                    man_bad.append({'name': c['name'], 'kind': 'context(JCS)', 'got': canon,
                                    'want': want})
                if c['name'] in pins and raw != want:
                    hash_semantics.append({'name': c['name'], 'raw': raw, 'jcs': canon, 'pin': want})
        else:
            rp = FIX / c['dir'] / (c['name'] + '.json')
            if rp.exists() and c.get('reply_sha256'):
                got = O.sha256_file(rp)
                if got == c['reply_sha256']:
                    man_ok += 1
                else:
                    man_bad.append({'name': c['name'], 'kind': 'reply(raw file)', 'got': got,
                                    'want': c['reply_sha256']})
    res['manifest'] = {'ok': man_ok, 'bad': man_bad[:8], 'bad_count': len(man_bad),
                       'proposal_hash_kind': 'raw file sha256',
                       'context_hash_kind': 'JCS canonical sha256',
                       'mixed_semantics_examples': hash_semantics[:3],
                       'mixed_semantics_count': len(hash_semantics)}

    # 3) evidence_version = JCS(basis) 复算
    ev_match, ev_total, ev_detail = 0, 0, []
    for c in cases:
        if c.get('expected_decision') not in ('accepted', 'rejected'):
            continue
        prop = O.load_json(FIX / c['dir'] / (c['name'] + '.json'))
        ev_total += 1
        mine = O.sha256_jcs(prop.get('basis'))
        same = mine == prop.get('evidence_version')
        ev_match += same
        ev_detail.append({'name': c['name'], 'match': same, 'expected_decision': c['expected_decision']})
    res['evidence'] = {'match': ev_match, 'total': ev_total,
                       'mismatch_names': [d['name'] for d in ev_detail if not d['match']]}

    # 4) 我的 oracle 对作者夹具交叉
    psch = O.load_json(PROPOSAL_SCHEMA_PATH)
    rsch = O.load_json(REPLY_SCHEMA_PATH)
    esch = O.load_json(ENTRY_SCHEMA_PATH)
    dec_ok, reason_ok = 0, 0
    mismatches = []
    n_prop = 0
    for c in cases:
        if c.get('expected_decision') not in ('accepted', 'rejected'):
            continue
        n_prop += 1
        prop = O.load_json(FIX / c['dir'] / (c['name'] + '.json'))
        ctx = O.load_json(FIX / 'contexts' / (c['name'] + '.json'))
        pin = pins.get(c['name'])
        got = O.oracle_gate(prop, ctx, psch, esch, pin)
        want_dec = c['expected_decision']
        want_reason = c.get('expected_reason_code') or ('accepted' if want_dec == 'accepted' else None)
        if got['decision'] == want_dec:
            dec_ok += 1
        else:
            mismatches.append({'name': c['name'], 'kind': 'decision', 'want': want_dec, 'got': got})
        if want_reason is None or got['reason_code'] == want_reason:
            reason_ok += 1
        else:
            mismatches.append({'name': c['name'], 'kind': 'reason', 'want': want_reason,
                               'got': got['reason_code']})
    rep_ok, rep_bad = 0, []
    n_rep = 0
    for c in cases:
        if c.get('expected_decision') not in ('valid', 'invalid'):
            continue
        n_rep += 1
        reply = O.load_json(FIX / c['dir'] / (c['name'] + '.json'))
        got = O.oracle_reply(reply, rsch)
        want = c['expected_decision'] == 'valid'
        if got['valid'] == want:
            rep_ok += 1
        else:
            rep_bad.append({'name': c['name'], 'want': want, 'got': got})
    res['cross'] = {'proposal_cases': n_prop, 'decision_match': dec_ok, 'reason_match': reason_ok,
                    'reply_cases': n_rep, 'reply_match': rep_ok,
                    'mismatches': mismatches[:10], 'mismatch_count': len(mismatches),
                    'reply_mismatches': rep_bad[:5]}
    wjson('oracle_results.json', res)
    print(json.dumps({'phase': 'oracle', 'jcs_vectors': f"{ok}/{len(JCS_VECTORS)}",
                      'pins': f"{pin_ok}/{len(pins)}", 'jcs_vs_author': f'{jcs_agree}/{jcs_checked}',
                      'manifest': f"{man_ok} ok / {len(man_bad)} bad",
                      'evidence_match': f'{ev_match}/{ev_total}',
                      'oracle_decision_match': f'{dec_ok}/{n_prop}', 'oracle_reason_match': f'{reason_ok}/{n_prop}',
                      'oracle_reply_match': f'{rep_ok}/{n_rep}',
                      'mismatches': len(mismatches)}, ensure_ascii=False))
    return res


# ----------------------------------------------------------------- phase probe

PROBE_ENTRIES = [
    {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-probe-tags',
     'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [],
     'max_actions': 10, 'max_duration_ticks': 240, 'max_ttl_ticks': 480,
     'param_schema': {'type': 'object', 'additionalProperties': False, 'required': ['tags'],
                      'properties': {'tags': {'type': 'array', 'minItems': 1, 'maxItems': 8,
                                              'items': {'type': 'object',
                                                        'additionalProperties': {'type': 'string'}}}}},
     'preconditions': []},
    {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-probe-nested',
     'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [],
     'max_actions': 10, 'max_duration_ticks': 240, 'max_ttl_ticks': 480,
     'param_schema': {'type': 'object', 'additionalProperties': False, 'required': ['root'],
                      'properties': {'root': {'type': 'object', 'additionalProperties': False,
                                              'required': ['payload'],
                                              'properties': {'payload': {'type': 'object',
                                                                         'additionalProperties': True}}}}},
     'preconditions': []},
]


def build_variants():
    """返回 [(key, family)]；family ∈ mandated / plural_stem / padded / hidden_contact。"""
    out = []
    seps = ['', '_', '-', '.']
    cases = ['lower', 'Capital', 'UPPER']
    for stem in O.SINGULAR_STEMS:
        for tok in O.ID_TOKENS:
            for sep in seps:
                for cs in cases:
                    s = stem if cs == 'lower' else (stem.capitalize() if cs == 'Capital' else stem.upper())
                    t = tok if cs == 'lower' else (tok.capitalize() if cs == 'Capital' else tok.upper())
                    out.append((s + sep + t, 'mandated'))
    for stem in O.SINGULAR_STEMS:
        pl = O.PLURALS[stem]
        for tok in O.ID_TOKENS:
            for sep in seps:
                for cs in cases:
                    s = pl if cs == 'lower' else (pl.capitalize() if cs == 'Capital' else pl.upper())
                    t = tok if cs == 'lower' else (tok.capitalize() if cs == 'Capital' else tok.upper())
                    out.append((s + sep + t, 'plural_stem'))
    for stem in O.SINGULAR_STEMS:
        for tok in ('Id', 'ID', 'Ids'):
            for suf in ('Map', 'List', 'Ref', 'Value', 'Set'):
                out.append((stem + tok + suf, 'padded'))
            for pre in ('gt', 'raw', 'my', 'src'):
                out.append((pre + stem.capitalize() + tok, 'padded'))
    for hc in ('hidden', 'Hidden', 'HIDDEN'):
        for ct in ('contact', 'Contact', 'CONTACT'):
            for sep in ('', '_', '-', '.'):
                out.append((hc + sep + ct, 'hidden_contact'))
    out.extend([('id', 'mandated'), ('ids', 'mandated'), ('ID', 'mandated'), ('IDs', 'mandated'),
                ('iD', 'mandated'), ('iDs', 'mandated')])
    seen, uniq = set(), []
    for k, fam in out:
        if k not in seen:
            seen.add(k)
            uniq.append((k, fam))
    return uniq


def probe_proposal(ability, params, ctx):
    basis = {'packet_ref': dict(ctx['observation']['packet_ref']),
             't_ticks': ctx['observation']['t_ticks'],
             'time_domain': dict(ctx['observation']['time_domain']),
             'belief_sha256': 'a' * 64,
             'brain': {'model_version': 'probe-brain', 'encoder_version': 'probe-enc',
                       'planner_version': 'probe-plan'}}
    return {
        'schema_version': 'skill_proposal.v1',
        'proposal_id': 'prop-probe-0001',
        'actor': dict(ctx['session']['actor']),
        'basis': basis,
        'evidence_version': O.sha256_jcs(basis),
        'ability_id': ability,
        'params': params,
        'targets': [],
        'action_budget': {'max_actions': 1, 'max_duration_ticks': 10},
        'ttl_ticks': 120,
        'expected_outcomes': [{'channel': 'relative_objects', 'quantity': 'detection.rel_position_m',
                               'predicted_value': 0.4, 'uncertainty': {'sigma': 0.05, 'units': 'm'},
                               'window': {'start_offset_ticks': 0, 'end_offset_ticks': 10}}],
        'confidence': 0.5,
        'calibration': 'uncalibrated',
    }


def phase_probe():
    base_ctx = O.load_json(FIX / 'contexts' / 'valid_minimal_handle_target.json')
    psch = O.load_json(PROPOSAL_SCHEMA_PATH)
    esch = O.load_json(ENTRY_SCHEMA_PATH)
    author = load_author()
    validator = jsonschema.Draft202012Validator(psch)

    variants = build_variants()
    families = {}
    for k, fam in variants:
        families.setdefault(fam, 0)
        families[fam] += 1

    pos_tags = {'name': 'params.tags[0]', 'ability': 'abil-probe-tags',
                'mk': lambda k: {'tags': [{k: 'x'}]}}
    pos_d2 = {'name': 'params.root.payload', 'ability': 'abil-probe-nested',
              'mk': lambda k: {'root': {'payload': {k: 'x'}}}}
    pos_d3 = {'name': 'params.root.payload.level2', 'ability': 'abil-probe-nested',
              'mk': lambda k: {'root': {'payload': {'level2': {k: 'x'}}}}}
    positions = [pos_tags, pos_d2, pos_d3]

    # 探针上下文：在冻结上下文上追加允许任意字符串/嵌套对象的登记条目（其余不变）
    probe_ctx = json.loads(json.dumps(base_ctx))
    probe_ctx['ability_registry']['entries'].extend(json.loads(json.dumps(PROBE_ENTRIES)))
    probe_ctx['context_id'] = 'v9b5-probe-context-20261016'
    wjson('probe_context.json', probe_ctx)
    pin = O.sha256_jcs(probe_ctx)

    rows = []
    agg = {}
    escapes = []
    for key, fam in variants:
        a = agg.setdefault(fam, {'total': 0, 'schema_reject': 0, 'norm_reject': 0,
                                 'gate_reject': 0, 'gate_accept': 0})
        a['total'] += 1
        oracle_fam = O.classify_key(key)
        for pos in positions:
            prop = probe_proposal(pos['ability'], pos['mk'](key), probe_ctx)
            l1 = not validator.is_valid(prop)
            l2 = author.has_forbidden_world_id_key(prop)
            g = author.gate(prop, probe_ctx, pin, psch)
            acc = g.get('decision') == 'accepted'
            if pos is pos_tags:
                a['schema_reject'] += int(l1)
                a['norm_reject'] += int(l2)
                a['gate_reject'] += int(not acc)
                a['gate_accept'] += int(acc)
            if acc:
                escapes.append({'key': key, 'family': fam, 'position': pos['name'],
                                'oracle_family': oracle_fam, 'schema_valid': not l1, 'norm_flag': l2})
        rows.append({'key': key, 'family': fam, 'oracle_classify': oracle_fam})
    rows = [r for r in rows]  # 全量明细另存

    # 关闭对象位置：全部变体只做 schema 层（关闭对象对任何多余键一视同仁）
    closed_positions = {}
    def put(obj, k, v):
        if isinstance(obj, dict):
            obj[k] = v
    for name, mk in {
        'root': lambda k: {k: 'x'},
        'targets[0]': lambda k: {'targets': [{'kind': 'handle', 'handle': 'h-1', k: 'x'}]},
        'basis': lambda k: {'basis': {k: 'x'}},
        'basis.packet_ref': lambda k: {'basis': {'packet_ref': {k: 'x'}}},
        'basis.brain': lambda k: {'basis': {'brain': {k: 'x'}}},
        'expected_outcomes[0]': lambda k: {'expected_outcomes': [{'channel': 'relative_objects',
                                                                  'quantity': 'detection.rel_position_m',
                                                                  'predicted_value': 0.1,
                                                                  'uncertainty': {'sigma': 0.1},
                                                                  'window': {'start_offset_ticks': 0,
                                                                             'end_offset_ticks': 1},
                                                                  k: 'x'}]},
        'action_budget': lambda k: {'action_budget': {k: 'x'}},
        'actor': lambda k: {'actor': {k: 'x'}},
        'time_domain': lambda k: {'basis': {'time_domain': {k: 'x'}}},
    }.items():
        rej = 0
        for key, _fam in variants:
            prop = probe_proposal('abil-probe-tags', {'tags': [{'c': 'x'}]}, probe_ctx)
            for kk, vv in mk(key).items():
                if kk == 'basis':
                    prop['basis'].update(vv)
                    prop['evidence_version'] = O.sha256_jcs(prop['basis'])
                elif kk == 'targets':
                    prop['targets'] = vv
                elif kk == 'expected_outcomes':
                    prop['expected_outcomes'] = vv
                elif kk == 'action_budget':
                    prop['action_budget'] = vv
                elif kk == 'actor':
                    prop['actor'] = {**prop['actor'], **vv}
                else:
                    prop[kk] = vv
            if not validator.is_valid(prop):
                rej += 1
        closed_positions[name] = {'variants': len(variants), 'schema_rejected': rej}

    # 能力登记条目 param_schema 属性名探针（要求 b）
    entry_schema = esch
    entry_rows = []
    for key, fam in variants:
        e = {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-probe-entry',
             'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [], 'max_actions': 1,
             'max_duration_ticks': 10, 'max_ttl_ticks': 10,
             'param_schema': {'type': 'object', 'additionalProperties': False,
                              'properties': {key: {'type': 'string'}}}, 'preconditions': []}
        ctx2 = json.loads(json.dumps(probe_ctx))
        ctx2['ability_registry']['entries'] = [
            x for x in ctx2['ability_registry']['entries'] if x['ability_id'] != 'abil-probe-tags']
        ctx2['ability_registry']['entries'].append(e)
        probs = author.registry_problems(ctx2)
        my_probs = O.entry_problems(ctx2, entry_schema)
        entry_rows.append({'key': key, 'family': fam, 'author_flags': bool(probs),
                           'mine_flags': bool(my_probs),
                           'author_flag_kind': probs[0].split(':')[0] if probs else None})

    # patternProperties 缺口探针（要求 b 的覆盖面）
    pattern_probe = {}
    for pat_key, pat_src in (('^instanceId$', 'instanceId'), ('^world_ids$', 'world_ids')):
        e = {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-probe-pattern',
             'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [], 'max_actions': 1,
             'max_duration_ticks': 10, 'max_ttl_ticks': 10,
             'param_schema': {'type': 'object', 'additionalProperties': False,
                              'properties': {'seed': {'type': 'string'}},
                              'patternProperties': {pat_key: {'type': 'string'}}}, 'preconditions': []}
        ctx3 = json.loads(json.dumps(probe_ctx))
        ctx3['ability_registry']['entries'] = [e]
        pattern_probe[pat_src] = {'author_flags': author.registry_problems(ctx3),
                                  'mine_flags': O.entry_problems(ctx3, entry_schema)}

    author_agg = {}
    for r in entry_rows:
        a = author_agg.setdefault(r['family'], {'total': 0, 'author_flagged': 0, 'mine_flagged': 0})
        a['total'] += 1
        a['author_flagged'] += int(r['author_flags'])
        a['mine_flagged'] += int(r['mine_flags'])

    res = {'variants_total': len(variants), 'families': families,
           'gate_agg_by_family': agg, 'entry_agg_by_family': author_agg,
           'closed_positions': closed_positions,
           'escapes': escapes[:80], 'escape_count': len(escapes),
           'escape_keys_by_family': {},
           'pattern_probe': pattern_probe,
           'probe_context_pin': pin}
    byfam = {}
    for e in escapes:
        byfam.setdefault(e['family'], [])
        if len(byfam[e['family']]) < 6:
            byfam[e['family']].append(e['key'] + '@' + e['position'])
    res['escape_keys_by_family'] = byfam
    wjson('probe_results.json', res)
    wjson('probe_variants.json', [{'key': k, 'family': f} for k, f in variants])
    print(json.dumps({'phase': 'probe', 'variants': len(variants), 'gate_agg': agg,
                      'entry_agg': author_agg, 'escapes': len(escapes),
                      'escape_sample': escape_keys_sample(escapes)}, ensure_ascii=False))
    return res


def escape_keys_sample(escapes, n=12):
    out, seen = [], set()
    for e in escapes:
        kk = (e['key'], e['position'])
        if kk in seen:
            continue
        seen.add(kk)
        out.append(f"{e['key']}@{e['position']}")
        if len(out) >= n:
            break
    return out


# --------------------------------------------------------------- phase adverse

BASELINE_CTX = 'valid_minimal_handle_target'


def baseline_ctx():
    return O.load_json(FIX / 'contexts' / (BASELINE_CTX + '.json'))


def baseline_proposal(ctx, **over):
    basis = {'packet_ref': dict(ctx['observation']['packet_ref']),
             't_ticks': ctx['observation']['t_ticks'],
             'time_domain': dict(ctx['observation']['time_domain']),
             'belief_sha256': 'b' * 64,
             'brain': {'model_version': 'adv-brain', 'encoder_version': 'adv-enc',
                       'planner_version': 'adv-plan'}}
    prop = {
        'schema_version': 'skill_proposal.v1',
        'proposal_id': 'prop-adverse-0001',
        'actor': dict(ctx['session']['actor']),
        'basis': basis,
        'evidence_version': O.sha256_jcs(basis),
        'ability_id': 'abil-approach-object',
        'params': {'speed_mps': 1.5},
        'targets': [{'kind': 'handle', 'handle': 'h-1'}],
        'action_budget': {'max_actions': 2, 'max_duration_ticks': 60},
        'ttl_ticks': 10,
        'expected_outcomes': [{'channel': 'relative_objects', 'quantity': 'detection.rel_position_m',
                               'predicted_value': 0.4, 'uncertainty': {'sigma': 0.05, 'units': 'm'},
                               'window': {'start_offset_ticks': 0, 'end_offset_ticks': 10}}],
        'confidence': 0.6,
        'calibration': 'uncalibrated',
    }
    prop.update(over)
    return prop


def tags_ctx(ability_entry):
    ctx = baseline_ctx()
    ctx['ability_registry']['entries'].append(ability_entry)
    ctx['context_id'] = 'v9b5-adverse-context'
    return ctx


def open_tags_entry(prop_key):
    return {'schema_version': 'ability_registry_entry.v0',
            'ability_id': 'abil-adv-tags', 'ability_version': '1.0', 'effect_class': 'run',
            'target_kinds': [], 'max_actions': 5, 'max_duration_ticks': 60, 'max_ttl_ticks': 480,
            'param_schema': {'type': 'object', 'additionalProperties': False, 'required': ['tags'],
                             'properties': {'tags': {'type': 'array', 'minItems': 1,
                                                     'items': {'type': 'object',
                                                               'additionalProperties': {'type': 'string'}}}}},
            'preconditions': []}


def build_adverse():
    """返回 (cases, files)；case 含 ce（反例）与 ctrl（破坏对照）两组运行参数。"""
    ctx0 = baseline_ctx()
    base = baseline_proposal(ctx0)
    cases = []

    def add(cid, desc, rule, prop, ctx, ctrl_disable=None, ctrl_schema=None, expect='reject',
            ctrl_expect='accept', differential=None, note=None):
        cases.append({'id': cid, 'desc': desc, 'rule': rule, 'proposal': prop, 'context': ctx,
                      'ctrl_disable': ctrl_disable or [], 'ctrl_schema': ctrl_schema,
                      'expect': expect, 'ctrl_expect': ctrl_expect, 'differential': differential,
                      'note': note})

    # --- 世界 ID 键名（mandated 家族，params 深层/数组项）
    for key, cid in (('world.id', 'dot'), ('entity-id', 'hyphen'), ('OBJECT_ID', 'upper'),
                     ('instanceId', 'camel'), ('actorIds', 'plural_token'),
                     ('Hidden_Contact', 'hidden_contact'), ('gtObjectId', 'padded_prefix_caught')):
        ctx = tags_ctx(open_tags_entry(key))
        prop = baseline_proposal(ctx, ability_id='abil-adv-tags', targets=[],
                                 params={'tags': [{key: 'x'}]})
        add('adv_norm_' + cid, f'params.tags[0]["{key}"] 世界 ID 键名', 'world_id_normalization',
            prop, ctx, ctrl_disable=['world_id_normalization'])

    # --- 复数词干 / 后缀填充：本复核重点对抗项
    for key, cid in (('objects_id', 'plural_stem'), ('worldIdsMap', 'padded_suffix'),
                     ('entitiesId', 'plural_stem_entities')):
        ctx = tags_ctx(open_tags_entry(key))
        prop = baseline_proposal(ctx, ability_id='abil-adv-tags', targets=[],
                                 params={'tags': [{key: 'x'}]})
        canon = {'objects_id': 'object_id', 'worldIdsMap': 'world_ids',
                 'entitiesId': 'entity_ids'}[key]
        ctx_canon = tags_ctx(open_tags_entry(canon))
        prop_canon = baseline_proposal(ctx_canon, ability_id='abil-adv-tags', targets=[],
                                       params={'tags': [{canon: 'x'}]})
        add('adv_leak_' + cid, f'params.tags[0]["{key}"]（规范化判定未覆盖）', 'world_id_normalization',
            prop, ctx, expect='reject', ctrl_disable=None,
            differential={'proposal': prop_canon, 'context': ctx_canon,
                          'note': f'同结构换成规范拼写 {canon} 必须被拒'})

    # --- 端到端：登记条目声明 escaping 属性名 + 值携带真实世界实体 ID
    entry_plural = {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-adv-tags',
                    'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [],
                    'max_actions': 5, 'max_duration_ticks': 60, 'max_ttl_ticks': 480,
                    'param_schema': {'type': 'object', 'additionalProperties': False,
                                     'required': ['tags'],
                                     'properties': {'tags': {'type': 'array', 'minItems': 1,
                                                             'items': {'type': 'object',
                                                                       'additionalProperties':
                                                                           {'type': 'string'}}}}},
                    'preconditions': []}
    ctx_p = tags_ctx(entry_plural)
    prop_p = baseline_proposal(ctx_p, ability_id='abil-adv-tags', targets=[],
                               params={'tags': [{'objects_id': 'entity-7f3a41c9b2e05d18'}]})
    ctx_c = tags_ctx(entry_plural)
    prop_c = baseline_proposal(ctx_c, ability_id='abil-adv-tags', targets=[],
                               params={'tags': [{'object_id': 'entity-7f3a41c9b2e05d18'}]})
    add('adv_e2e_plural_stem_value_smuggle',
        '登记条目声明 objects_id；提案值携带冻结上下文里的真实实体 ID', 'world_id_normalization',
        prop_p, ctx_p, expect='reject',
        differential={'proposal': prop_c, 'context': ctx_c, 'note': '同条目下规范拼写 object_id 必须被拒'})

    # --- 登记条目 patternProperties 缺口
    e_pat = {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-adv-pattern',
             'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': [], 'max_actions': 5,
             'max_duration_ticks': 60, 'max_ttl_ticks': 480,
             'param_schema': {'type': 'object', 'additionalProperties': False,
                              'properties': {'seed': {'type': 'string'}},
                              'patternProperties': {'^instanceId$': {'type': 'string'}}},
             'preconditions': []}
    ctx_pp = tags_ctx(e_pat)
    prop_pp = baseline_proposal(ctx_pp, ability_id='abil-adv-pattern', targets=[],
                               params={'seed': 's', 'instanceId': 'x'})
    add('adv_entry_patternproperties_gap',
        '登记条目用 patternProperties 声明 instanceId：条目层检查未覆盖，靠提案层规范化兜底',
        'registry_param_schema', prop_pp, ctx_pp, expect='reject',
        ctrl_disable=['world_id_normalization'],
        note='对照：关掉提案层规范化后应被接受 → 证明条目层确实没拦')

    # --- quantity 值泄露
    for q in ('world_id', 'hidden_contact'):
        ctx = baseline_ctx()
        prop = baseline_proposal(ctx)
        prop['expected_outcomes'][0]['quantity'] = q
        add('adv_quantity_' + q, f'expected_outcomes[0].quantity="{q}"', 'schema', prop, ctx,
            ctrl_schema=str(SABOTAGE / 'proposal_quantity_value_open.json'))

    # --- 句柄：旧句柄 / 跨包句柄 / 原始实体 ID 当句柄
    for h, cid in (('h-4', 'retired'), ('h-9', 'cross_package')):
        ctx = baseline_ctx()
        prop = baseline_proposal(ctx, targets=[{'kind': 'handle', 'handle': h}])
        add('adv_handle_' + cid, f'targets[0].handle="{h}"', 'handle', prop, ctx,
            ctrl_disable=['handle'])
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx, targets=[{'kind': 'handle', 'handle': 'entity-7f3a41c9b2e05d18'}])
    add('adv_handle_raw_entity_id', 'targets[0].handle 直接写世界实体 ID', 'schema', prop, ctx,
        ctrl_disable=['handle'], ctrl_schema=str(MY / 'mine_handle_pattern_open.json'),
        note='链条：schema 正则先拦；放开正则后仍被 handle 解析检查拦；再关 handle 才漏')

    # --- 伪造 basis 后自算 evidence_version
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx)
    prop['basis']['packet_ref'] = {'uri': 'awz://observation/synthetic-episode-0001/000999',
                                   'sha256': 'f' * 64}
    prop['evidence_version'] = O.sha256_jcs(prop['basis'])
    add('adv_forged_basis_packetref', '伪造 packet_ref 并按伪造 basis 自算 evidence_version',
        'evidence', prop, ctx, ctrl_disable=['evidence'])
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx)
    prop['basis']['t_ticks'] = 999
    prop['evidence_version'] = O.sha256_jcs(prop['basis'])
    add('adv_forged_basis_tticks', '伪造 basis.t_ticks 并自算 evidence_version', 'evidence', prop, ctx,
        ctrl_disable=['evidence'])

    # --- TTL 边界 ±1 tick（窗口同时收敛到 ttl 内，避免被 outcome_window 抢先拒）
    ctx = baseline_ctx()  # current_tick=850, t_ticks=840
    win_ok = [{'channel': 'relative_objects', 'quantity': 'detection.rel_position_m',
               'predicted_value': 0.4, 'uncertainty': {'sigma': 0.05, 'units': 'm'},
               'window': {'start_offset_ticks': 0, 'end_offset_ticks': 10}}]
    win_bad = [dict(win_ok[0], window={'start_offset_ticks': 0, 'end_offset_ticks': 9})]
    prop_ok = baseline_proposal(ctx, ttl_ticks=10, expected_outcomes=win_ok)
    prop_bad = baseline_proposal(ctx, ttl_ticks=9, expected_outcomes=win_bad)
    add('adv_ttl_boundary_in', 'ttl=10 → valid_until == current_tick（闭区间边界内）', 'ttl',
        prop_ok, ctx, expect='accept', ctrl_expect='accept', ctrl_disable=['ttl'])
    add('adv_ttl_boundary_out', 'ttl=9 → 右端 +1 过期（窗口在 ttl 内，排除其他规则干扰）', 'ttl',
        prop_bad, ctx, ctrl_disable=['ttl'])

    # --- 跨 episode 时间域
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx)
    prop['basis']['time_domain'] = dict(prop['basis']['time_domain'])
    prop['basis']['time_domain']['episode_id'] = 'ffffffff-0000-0000-0000-000000000000'
    prop['evidence_version'] = O.sha256_jcs(prop['basis'])
    add('adv_cross_episode', 'basis.time_domain 换成另一个 episode 并自算摘要', 'time_domain',
        prop, ctx, ctrl_disable=['time_domain'])

    # --- 置信度 1.0 越门
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx, ability_id='abil-not-registered', confidence=1.0)
    add('adv_confidence_one', 'confidence=1.0 + 未登记能力', 'confidence_independence', prop, ctx,
        ctrl_disable=['confidence_independence'])

    # --- 编辑类效果伪装成运行类
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx, ability_id='abil-synthetic-edit-scene',
                             params={'patch_op': 'remove'})
    add('adv_edit_disguised_run', '引用登记为 edit 的能力，其余字段伪装成运行类', 'effect_class',
        prop, ctx, ctrl_disable=['effect_class'])

    # --- 预期结果夹带真值 / 事件类型
    for extra, cid in (('event_type', 'event_type'), ('gt_pose', 'truth_field'),
                       ('truth_id', 'truth_id')):
        ctx = baseline_ctx()
        prop = baseline_proposal(ctx)
        prop['expected_outcomes'][0][extra] = 'spawn' if extra == 'event_type' else 'x'
        add('adv_outcome_' + cid, f'expected_outcomes[0].{extra} 夹带真值/事件类型', 'schema', prop, ctx,
            ctrl_schema=str(SABOTAGE / 'proposal_no_additional_properties.json'))

    # --- 同 ID 换载荷
    ctx = baseline_ctx()
    prior = baseline_proposal(ctx)
    prior_digest = O.sha256_jcs(prior)
    ctx2 = baseline_ctx()
    ctx2['decisions_seen'] = [{'proposal_id': 'prop-adverse-0001', 'proposal_digest': prior_digest,
                               'evidence_version': prior['evidence_version'],
                               'decision': 'rejected', 'reason_code': 'handle_unknown',
                               'decided_at_tick': 850}]
    prop = baseline_proposal(ctx2, params={'speed_mps': 2.5})
    add('adv_duplicate_id_changed_payload', '同 proposal_id、换 params 载荷', 'duplicate', prop, ctx2,
        ctrl_disable=['duplicate'])

    # --- 回执泄露隐藏状态：非白名单原因 / 解析出的实体（由下方 replies 子探针用 reply 模式运行）

    # --- 值级偷带：键名合法，但字符串值就是冻结上下文里的真实实体 ID
    ctx = tags_ctx(open_tags_entry('color'))
    prop = baseline_proposal(ctx, ability_id='abil-adv-tags', targets=[],
                             params={'tags': [{'color': 'entity-7f3a41c9b2e05d18'}]})
    add('adv_value_smuggle_legit_key',
        '键名合法（color），值携带 world_side.handle_entity_map 里的真实实体 ID', 'value_level',
        prop, ctx, expect='accept',
        note='超范围残留风险登记：裁决 2 只要求字段级禁止；值级世界 ID 偷带当前无法被 schema/核对器发现，'
             '建议 AWZ 侧门禁补值级白名单或模式检查。不作为对裁决 2 的打回依据。')

    # --- 健壮性：超出安全整数范围 / 孤立代理项（异常退出不算有效拒绝）
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx)
    prop['basis']['t_ticks'] = 2 ** 53
    prop['evidence_version'] = 'e' * 64
    ctx_safe = baseline_ctx()
    prop_safe = baseline_proposal(ctx_safe)
    prop_safe['basis']['t_ticks'] = 999
    prop_safe['evidence_version'] = 'e' * 64
    add('adv_robust_tticks_2p53', 'basis.t_ticks=2^53（schema 无上限，JCS 超范围）', 'robustness',
        prop, ctx, expect='reject', ctrl_disable=['evidence', 'duplicate'],
        differential={'proposal': prop_safe, 'context': ctx_safe,
                      'note': '换成安全整数 t_ticks=999 应得到合法的 evidence_mismatch 拒绝而非崩溃'},
        note='期望：合法拒绝（白名单原因码）；若 traceback 崩溃则违反 fail-closed')
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx)
    prop['params'] = {'tags': [{'color': 'ok'}]}
    ctx_lone = baseline_ctx()
    ctx_lone['ability_registry']['entries'].append(open_tags_entry('color'))
    prop = baseline_proposal(ctx_lone, ability_id='abil-adv-tags', targets=[],
                             params={'tags': [{'color': 'ok'}]})
    del prop['targets']
    prop['targets'] = []
    prop['params'] = {'tags': [{'color': '\ud800'}]}
    add('adv_robust_lone_surrogate', 'params 字符串含孤立代理项（JCS 无法编码）', 'robustness',
        prop, ctx_lone, expect='no_crash', note='期望：合法拒绝或合法接受，不得 traceback')

    return cases


def run_cli(proposal_path, ctx_path, pin, disable=(), schema=None, reply_schema=None, mode='gate',
            reply_path=None):
    argv = [VENV_PY, str(Path(__file__).resolve()), '--noop']  # placeholder, replaced below
    argv = [VENV_PY, str(AUTHOR), mode]
    if mode == 'gate':
        argv += ['--proposal', str(proposal_path), '--context', str(ctx_path),
                 '--expected-context-sha256', pin]
    else:
        argv += ['--reply', str(reply_path)]
    for d in disable:
        argv += ['--disable', d]
    if schema:
        argv += ['--schema', str(schema)]
    if reply_schema:
        argv += ['--reply-schema', str(reply_schema)]
    argv += ['--root', str(REPO)]
    t0 = time.time()
    p = subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO),
                       env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONDONTWRITEBYTECODE': '1',
                            'HOME': str(Path.home())})
    dt = time.time() - t0
    out = {'argv': ' '.join(argv), 'returncode': p.returncode, 'elapsed_s': round(dt, 3),
           'decision': None, 'reason_code': None, 'ok': None, 'crash': False,
           'stdout_bytes': len(p.stdout), 'stderr_tail': p.stderr.strip().splitlines()[-1:] }
    try:
        j = json.loads(p.stdout.strip().splitlines()[-1])
        out.update({'decision': j.get('decision'), 'reason_code': j.get('reason_code'),
                    'ok': j.get('ok'), 'replay': j.get('replayed'),
                    'world_side_log': j.get('world_side_log'),
                    'leaked_world_side_tokens': j.get('leaked_world_side_tokens')})
    except Exception:  # noqa: BLE001
        out['crash'] = True
    return out


def build_my_mutations():
    """我自己写的变异 schema（只落在 reports/V-V9-B1/）。"""
    psch = O.load_json(PROPOSAL_SCHEMA_PATH)
    open_handle = json.loads(json.dumps(psch))
    for br in open_handle['$defs']['target']['oneOf']:
        if br.get('properties', {}).get('kind', {}).get('const') == 'handle':
            br['properties']['handle'] = {'type': 'string', 'minLength': 1}
    wjson('mine_handle_pattern_open.json', open_handle)
    rsch = O.load_json(REPLY_SCHEMA_PATH)
    wide = json.loads(json.dumps(rsch))
    for key in ('visible_reason_code', 'rejected_reason_code'):
        if key in wide['$defs']:
            wide['$defs'][key]['enum'] = list(wide['$defs'][key]['enum']) + [
                'resolved_entity_5e1d77aa30bc9f42', 'hidden_contact_detected']
    wjson('mine_reply_enum_widened.json', wide)


def phase_adverse():
    cases = build_adverse()
    build_my_mutations()
    advdir = MY / 'adverse'
    advdir.mkdir(exist_ok=True)
    results = []
    n_ce_pass = n_ce_fail = n_crash = 0
    n_ctrl_pass = 0
    for c in cases:
        pin = O.sha256_jcs(c['context'])
        pp = advdir / (c['id'] + '.proposal.json')
        cc = advdir / (c['id'] + '.context.json')
        pp.write_text(json.dumps(c['proposal'], ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        cc.write_text(json.dumps(c['context'], ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        ce = run_cli(pp, cc, pin, schema=c.get('ctrl_schema') if False else None)
        ctrl = None
        if c.get('ctrl_disable') or c.get('ctrl_schema'):
            ctrl = run_cli(pp, cc, pin, disable=c.get('ctrl_disable') or [],
                           schema=c.get('ctrl_schema'))
        diff = None
        if c.get('differential'):
            d = c['differential']
            dpin = O.sha256_jcs(d['context'])
            dpp = advdir / (c['id'] + '.diff.proposal.json')
            dcc = advdir / (c['id'] + '.diff.context.json')
            dpp.write_text(json.dumps(d['proposal'], ensure_ascii=True, indent=2) + '\n',
                           encoding='utf-8')
            dcc.write_text(json.dumps(d['context'], ensure_ascii=True, indent=2) + '\n',
                           encoding='utf-8')
            diff = run_cli(dpp, dcc, dpin)
            diff['note'] = d.get('note')

        if c['expect'] == 'accept':
            ce_pass = (ce['returncode'] == 0 and ce['decision'] == 'accepted' and not ce['crash'])
        elif c['expect'] == 'no_crash':
            ce_pass = (not ce['crash'])
        else:
            ce_pass = (ce['returncode'] != 0 and ce['decision'] == 'rejected' and not ce['crash'])
        crash = bool(ce['crash'])
        if crash:
            n_crash += 1
        n_ce_pass += int(ce_pass)
        n_ce_fail += int(not ce_pass)
        ctrl_pass = None
        if ctrl is not None:
            ctrl_pass = (ctrl['returncode'] == 0 and ctrl['decision'] == 'accepted'
                         and not ctrl['crash'])
            n_ctrl_pass += int(bool(ctrl_pass))
        results.append({'id': c['id'], 'desc': c['desc'], 'rule': c['rule'], 'expect': c['expect'],
                        'ce': ce, 'ce_pass': ce_pass, 'crash': crash,
                        'ctrl': ctrl, 'ctrl_pass': ctrl_pass,
                        'differential': diff,
                        'differential_pass': (None if diff is None
                                              else (diff['returncode'] != 0
                                                    and diff['decision'] == 'rejected')),
                        'note': c.get('note')})

    # 回执探针：非白名单原因 / 解析到的实体 / 自定义非白名单原因
    replies = []
    rdir = advdir / 'replies'
    rdir.mkdir(exist_ok=True)
    base_reply = {'schema_version': 'skill_gate_reply.v1', 'proposal_id': 'prop-adverse-0001',
                  'evidence_version': 'a' * 64, 'decision': 'rejected',
                  'reason_code': 'handle_unknown', 'decided_at_tick': 850,
                  'valid_until_tick': 850}
    variants = [
        ('reply_ok_whitelisted', base_reply, None, True),
        ('reply_nonwhitelisted_target_behind_wall',
         {**base_reply, 'reason_code': 'target_behind_wall'}, str(SABOTAGE / 'reply_enum_widened.json'),
         False),
        ('reply_resolved_entity_field',
         {**base_reply, 'resolved_entity_id': 'entity-5e1d77aa30bc9f42'},
         str(SABOTAGE / 'reply_no_additional_properties.json'), False),
        ('reply_custom_nonwhitelisted',
         {**base_reply, 'reason_code': 'hidden_contact_detected'},
         str(MY / 'mine_reply_enum_widened.json'), False),
    ]
    for name, obj, ctrl_schema, expect_valid in variants:
        rp = rdir / (name + '.json')
        rp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        r = run_cli(None, None, None, mode='reply', reply_path=rp)
        c = None
        if ctrl_schema:
            c = run_cli(None, None, None, mode='reply', reply_path=rp, reply_schema=ctrl_schema)
        got_valid = (r['returncode'] == 0 and not r['crash'])
        replies.append({'name': name, 'expect_valid': expect_valid, 'got_valid': got_valid,
                        'pass': got_valid == expect_valid, 'run': r, 'ctrl': c,
                        'ctrl_valid': None if c is None else (c['returncode'] == 0 and not c['crash'])})

    # 未知 --disable 静默无效探针
    ctx = baseline_ctx()
    prop = baseline_proposal(ctx, params={'speed_mps': 9.9})
    pp = advdir / 'disable_typo.proposal.json'
    cc = advdir / 'disable_typo.context.json'
    pp.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cc.write_text(json.dumps(ctx, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    typo = run_cli(pp, cc, O.sha256_jcs(ctx), disable=['paramss'])
    good = run_cli(pp, cc, O.sha256_jcs(ctx), disable=['params'])

    res = {'cases': results, 'ce_pass': n_ce_pass, 'ce_fail': n_ce_fail, 'crash': n_crash,
           'ctrl_pass': n_ctrl_pass, 'replies': replies,
           'disable_typo': {'typo': typo, 'correct': good,
                            'silent_noop_confirmed': typo['decision'] == 'rejected'}}
    wjson('adverse_results.json', res)
    print(json.dumps({'phase': 'adverse', 'cases': len(results), 'ce_pass': n_ce_pass,
                      'ce_fail': n_ce_fail, 'crash': n_crash, 'ctrl_pass': n_ctrl_pass,
                      'reply_pass': sum(1 for r in replies if r['pass']), 'replies': len(replies),
                      'failing': [r['id'] for r in results if not r['ce_pass']]},
                     ensure_ascii=False))
    return res


# ----------------------------------------------------------------- phase suite

def phase_suite():
    before_tree = hash_tree(REPO / 'contracts/v9')
    before_tree.update(hash_tree(SABOTAGE))
    cr = AUTHOR_OUT / 'check_result.json'
    backup = MY / 'check_result.before.json'
    shutil.copyfile(cr, backup)
    before_cr_sha = O.sha256_file(cr)
    t0 = time.time()
    p = subprocess.run([VENV_PY, str(AUTHOR), '--suite', '--root', str(REPO)],
                       capture_output=True, text=True, cwd=str(REPO),
                       env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONDONTWRITEBYTECODE': '1',
                            'HOME': str(Path.home())})
    elapsed = time.time() - t0
    after_tree = hash_tree(REPO / 'contracts/v9')
    after_tree.update(hash_tree(SABOTAGE))
    d = tree_diff(before_tree, after_tree)
    after_cr_sha = O.sha256_file(cr)
    restored = False
    if after_cr_sha != before_cr_sha:
        shutil.copyfile(backup, cr)
        restored = True
    result = None
    try:
        result = O.load_json(backup)
    except Exception:  # noqa: BLE001
        pass
    controls = result.get('controls', []) if result else []
    reply_controls = result.get('reply_controls', []) if result else []
    ctrl_isolated = [c for c in controls if c.get('control_returncode') == 0
                     and c.get('control_reason') == 'accepted' and not c.get('exception')]
    ctrl_unclean = [c for c in controls if c.get('exception')]
    case_fail = [c for c in (result.get('cases', []) if result else [])
                 if c.get('valid') and c.get('got_reason') != 'accepted']
    case_fail += [c for c in (result.get('cases', []) if result else [])
                  if (not c.get('valid')) and (c.get('got_reason') == 'accepted' or not c.get('got_reason'))]
    reply_ctrl_ok = [c for c in reply_controls if c.get('control_returncode') == 0
                     and not c.get('exception')]
    res = {
        'suite_returncode': p.returncode, 'elapsed_s': round(elapsed, 3),
        'stdout_tail': p.stdout.strip().splitlines()[-3:],
        'stderr_tail': p.stderr.strip().splitlines()[-3:],
        'tree_diff': d, 'delivery_dir_untouched': (not d['changed'] and not d['added']
                                                   and not d['removed']),
        'check_result_before_sha': before_cr_sha, 'check_result_after_sha': after_cr_sha,
        'check_result_byte_identical': before_cr_sha == after_cr_sha, 'restored_after_run': restored,
        'all_ok': (result or {}).get('all_ok'),
        'cases_total': len((result or {}).get('cases', [])),
        'controls_total': len(controls), 'controls_isolated_verified_by_reviewer': len(ctrl_isolated),
        'controls_unclean_exception': ctrl_unclean,
        'case_fail_count': len(case_fail),
        'reply_controls_total': len(reply_controls),
        'reply_controls_verified': len(reply_ctrl_ok),
        'counts': (result or {}).get('counts'),
        'leak_scan_rows': len((result or {}).get('leak_scan', [])),
        'leak_scan_violations': [x for x in (result or {}).get('leak_scan', [])
                                 if x.get('leaked_tokens')],
        'jcs_self_tests': len((result or {}).get('jcs_self_tests', [])),
        'jcs_self_tests_failed': [x for x in (result or {}).get('jcs_self_tests', [])
                                  if not x.get('ok', True)],
        'no_rewrite_rows': len((result or {}).get('no_rewrite', [])),
        'registry_entries': len((result or {}).get('registry_entries_in_frozen_context', [])),
    }
    wjson('suite_results.json', res)
    print(json.dumps({'phase': 'suite', 'returncode': p.returncode, 'elapsed_s': res['elapsed_s'],
                      'delivery_dir_untouched': res['delivery_dir_untouched'],
                      'check_result_byte_identical': res['check_result_byte_identical'],
                      'restored': restored, 'all_ok': res['all_ok'],
                      'controls_isolated': f"{len(ctrl_isolated)}/{len(controls)}",
                      'reply_controls': f"{len(reply_ctrl_ok)}/{len(reply_controls)}",
                      'case_fail': len(case_fail)}, ensure_ascii=False))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', required=True,
                    choices=['oracle', 'probe', 'adverse', 'suite', 'all'])
    a = ap.parse_args()
    if a.phase in ('oracle', 'all'):
        phase_oracle()
    if a.phase in ('probe', 'all'):
        phase_probe()
    if a.phase in ('adverse', 'all'):
        phase_adverse()
    if a.phase in ('suite', 'all'):
        phase_suite()
    return 0


if __name__ == '__main__':
    sys.exit(main())
