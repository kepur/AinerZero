"""V9.B6 独立复核：B4 r4 的 1131 条 B5 探针分层统计（自写判据，不复用作者 oracle）。

分层：
  L0 自写规范化判定（indep_lib.is_ident_key_indep，据裁决 2 / B4-r4 F1/F3 条文另写）
  L1 提案 schema 层（$defs/world_id_key 正则的 propertyNames，直接对键名做 ECMA 正则 search）
  L2 门禁规范化层（--disable schema 后仍必须拒绝；被测实现是作者 gate）
  L3 端到端全门禁（schema + 规范化 + 其余检查都在）
另测：关闭 schema 层后只靠 L2 的隔离性、裸复数正例、任意位置（3 层嵌套）、值级偷带样本。
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
TMP = OUT / 'tmp'
TMP.mkdir(parents=True, exist_ok=True)
RES.mkdir(parents=True, exist_ok=True)


def load_author():
    spec = importlib.util.spec_from_file_location('author_checker', L.CHECKER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_probe_context():
    """在合成的冻结上下文里加一条允许任意字符串键的 probe 能力（参数 schema 合法封闭）。"""
    ctx = deepcopy(L.load(L.FIXTURE / 'contexts' / '01_valid_minimal_handle_target.json'))
    probe_entry = {
        'schema_version': 'ability_registry_entry.v0',
        'ability_id': 'abil-probe-tags',
        'ability_version': '1.0',
        'effect_class': 'run',
        'target_kinds': ['handle'],
        'max_actions': 4,
        'max_duration_ticks': 120,
        'max_ttl_ticks': 240,
        'param_schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': [],
            'properties': {
                # 任意字符串键只允许出现在数组元素对象里（登记 schema 支持的静态形态）
                'tags': {'type': 'array',
                         'items': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
                'root': {'type': 'array', 'items': {
                    'type': 'object',
                    'additionalProperties': {'type': 'string'},
                    'properties': {'level2': {'type': 'array', 'items': {
                        'type': 'object', 'additionalProperties': {'type': 'string'}}}}}},
            },
        },
        'preconditions': [],
        'observable_names': ['detection.rel_position_m'],
    }
    ctx['ability_registry']['entries'].append(probe_entry)
    ctx['context_id'] = 'ctx-v9b6-probe-1131'
    return ctx


def build_proposal(ctx, params):
    base = L.load(L.FIXTURE / 'valid' / '01_valid_minimal_handle_target.json')
    p = deepcopy(base)
    p['ability_id'] = 'abil-probe-tags'
    p['params'] = params
    return p


def main():
    author = load_author()
    pschema = author.schema_load(author.PROPOSAL_SCHEMA)
    rschema = author.schema_load(author.REPLY_SCHEMA)
    probes = L.load(L.ROOT / 'reports/V-V9-B1/probe_variants.json')
    ctx = build_probe_context()
    pin = L.jcs_sha(ctx)
    # 基线：同一上下文/提案形态（无探针键）必须被接受，否则后面的拒绝无意义
    base_proposal = build_proposal(ctx, {'tags': [{'note': 'ok'}]})
    base_res = author.gate_and_check(base_proposal, ctx, pin, pschema, rschema)
    assert base_res.get('decision') == 'accepted', base_res
    # 作者 schema 的 world_id_key 正则（L1 判据直接取自 schema 文本）
    wkey = pschema['$defs']['world_id_key']
    pat = re.compile(wkey['pattern'])

    families = sorted({x['family'] for x in probes})
    stats = {f: {'total': 0, 'L0_indep_reject': 0, 'L1_schema_reject': 0,
                 'L2_gate_layer_reject': 0, 'L3_full_gate_reject': 0,
                 'L2_only': 0} for f in families}
    mismatches = {'L0_accept': [], 'author_impl_diff': [], 'L2_accept': [], 'L3_accept': [],
                  'L1_accept': []}
    for x in probes:
        fam, key = x['family'], x['key']
        st = stats[fam]
        st['total'] += 1
        # L0：自写判据
        my = L.is_ident_key_indep(key)
        if my:
            st['L0_indep_reject'] += 1
        elif len(mismatches['L0_accept']) < 20:
            mismatches['L0_accept'].append(key)
        # 作者实现 vs 自写判据（只记录差异）
        auth = author.is_forbidden_world_id_key(key)
        if auth != my:
            mismatches['author_impl_diff'].append({'key': key, 'author': auth, 'indep': my})
        # L1：schema propertyNames 正则
        l1_reject = bool(pat.search(key))
        if l1_reject:
            st['L1_schema_reject'] += 1
        elif len(mismatches['L1_accept']) < 20:
            mismatches['L1_accept'].append(key)
        # L2/L3：端到端
        for pos, params in (('tags0', {'tags': [{key: 'v'}]}),
                            ('root0', {'root': [{key: 'v'}]}),
                            ('nested', {'root': [{'level2': [{key: 'v'}]}]})):
            prop = build_proposal(ctx, params)
            r2 = author.gate_and_check(prop, ctx, pin, pschema, rschema, disabled=('schema',))
            r3 = author.gate_and_check(prop, ctx, pin, pschema, rschema)
            if pos == 'tags0':
                if r2.get('decision') == 'rejected' and r2.get('reason_code') == 'schema_invalid':
                    st['L2_gate_layer_reject'] += 1
                elif len(mismatches['L2_accept']) < 20:
                    mismatches['L2_accept'].append({'key': key, 'pos': pos, 'res': r2})
                if r3.get('decision') == 'rejected':
                    st['L3_full_gate_reject'] += 1
                    if not l1_reject:
                        st['L2_only'] += 1
                elif len(mismatches['L3_accept']) < 20:
                    mismatches['L3_accept'].append({'key': key, 'pos': pos, 'res': r3})
            else:
                # 其余位置只查关闭 schema 后的规范化层
                if not (r2.get('decision') == 'rejected' and r2.get('reason_code') == 'schema_invalid'):
                    if len(mismatches['L2_accept']) < 20:
                        mismatches['L2_accept'].append({'key': key, 'pos': pos, 'res': r2})
    # ---- 裸复数词干正例（文档 §2.4：两层都不拒）
    bare = ['entities', 'objects', 'actors', 'scenes', 'events', 'instances', 'landmarks',
            'agents', 'truths', 'worlds']
    bare_res = []
    for k in bare:
        prop = build_proposal(ctx, {'tags': [{k: 'v'}]})
        r2 = author.gate_and_check(prop, ctx, pin, pschema, rschema, disabled=('schema',))
        r3 = author.gate_and_check(prop, ctx, pin, pschema, rschema)
        bare_res.append({'key': k, 'L1_reject': bool(pat.search(k)),
                         'L2_decision': r2.get('decision'), 'L3_decision': r3.get('decision'),
                         'indep_reject': L.is_ident_key_indep(k)})
    # ---- 子进程端到端样本（真实进程、真实退出码）
    sub_cases = ['world_id', 'worlds_id', 'objects_id', 'worldIdsMap', 'entitiesId', 'gtWorldId',
                 'objectIdMap', 'entityIdRef', 'hidden_contact', 'contact_id', 'idx', 'identifiers']
    sub_rows = []
    for key in sub_cases:
        prop = build_proposal(ctx, {'tags': [{key: 'v'}]})
        pp = TMP / ('sub_' + re.sub(r'[^a-z0-9]', '_', key.lower()) + '.json')
        cp = TMP / 'probe_context.json'
        L.write_json(pp, prop)
        L.write_json(cp, ctx)
        full = L.run_cli(L.gate_args(pp, cp, pin))
        layer2 = L.run_cli(L.gate_args(pp, cp, pin, ['--disable', 'schema']))
        sub_rows.append({'key': key,
                         'full_rc': full['returncode'],
                         'full_reason': (full['payload'] or {}).get('reason_code'),
                         'full_world_log': (full['payload'] or {}).get('world_side_log'),
                         'full_stderr_empty': full['stderr'].strip() == '',
                         'layer2_rc': layer2['returncode'],
                         'layer2_reason': (layer2['payload'] or {}).get('reason_code'),
                         'layer2_world_log': (layer2['payload'] or {}).get('world_side_log')})
    # 基线子进程（应 accepted / rc0）
    base_pp = TMP / 'sub_baseline.json'
    L.write_json(base_pp, base_proposal)
    base_cli = L.run_cli(L.gate_args(base_pp, TMP / 'probe_context.json', pin))
    # ---- 值级偷带样本（合法键、值为冻结上下文里的真实实体 ID）：文档 §13 说不能拦
    smuggle = build_proposal(ctx, {'tags': [{'note': 'entity-7f3a41c9b2e05d18'}]})
    smuggle_res = author.gate_and_check(smuggle, ctx, pin, pschema, rschema)
    # ---- 关闭 schema 层后的 L2 隔离性：只有规范化层能拒的键
    only_layer2 = [x['key'] for x in probes if not pat.search(x['key'])]
    out = {
        'probe_total': len(probes),
        'probe_unique_keys': len({x['key'] for x in probes}),
        'families': stats,
        'L0_indep_rejected_total': sum(s['L0_indep_reject'] for s in stats.values()),
        'L1_schema_rejected_total': sum(s['L1_schema_reject'] for s in stats.values()),
        'L2_gate_layer_rejected_total': sum(s['L2_gate_layer_reject'] for s in stats.values()),
        'L3_full_gate_rejected_total': sum(s['L3_full_gate_reject'] for s in stats.values()),
        'L2_only_keys': only_layer2,
        'L2_only_count': len(only_layer2),
        'mismatches': mismatches,
        'bare_plural_positive_rows': bare_res,
        'subprocess_rows': sub_rows,
        'baseline_subprocess': {'rc': base_cli['returncode'],
                               'reason': (base_cli['payload'] or {}).get('reason_code'),
                               'stderr': base_cli['stderr'].strip()[:300]},
        'value_smuggle_decision': smuggle_res.get('decision'),
        'value_smuggle_reason': smuggle_res.get('reason_code'),
    }
    L.write_json(RES / 'probe_results.json', out)
    print(json.dumps({k: out[k] for k in ('probe_total', 'probe_unique_keys',
                                         'L0_indep_rejected_total', 'L1_schema_rejected_total',
                                         'L2_gate_layer_rejected_total',
                                         'L3_full_gate_rejected_total', 'L2_only_count',
                                         'value_smuggle_decision', 'baseline_subprocess')},
                     ensure_ascii=False, indent=1))
    print('mismatch sizes:', {k: len(v) for k, v in mismatches.items()})
    print('bare:', [(r['key'], r['L1_reject'], r['L2_decision'], r['L3_decision']) for r in bare_res])
    print('sub sample:', [(r['key'], r['full_rc'], r['full_reason'], r['layer2_rc'],
                           r['layer2_reason']) for r in sub_rows])
    ok = (out['L0_indep_rejected_total'] == 1131 and out['L2_gate_layer_rejected_total'] == 1131
          and out['L3_full_gate_rejected_total'] == 1131 and not mismatches['L2_accept']
          and not mismatches['L3_accept'])
    print('PROBE_VERDICT', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
