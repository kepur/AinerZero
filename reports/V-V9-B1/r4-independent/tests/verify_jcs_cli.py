"""V9.B6 独立复核：JCS 异常 fail-closed（r4 F4）与 CLI 健壮性。

被测：check_skill_proposal.py gate 子进程。判据（B4-r4 F4）：
  超范围整数、孤立代理项、解码/编码错误 → 真实非零 + 既有白名单原因码，无 traceback 替代拒绝。
另测独立构造的异常输入；全部要求 stdout 是合法 JSON 且 stderr 无 Traceback。
"""
import json
import math
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
TMP = OUT / 'tmp'
RES = OUT / 'results'
TMP.mkdir(parents=True, exist_ok=True)
RES.mkdir(parents=True, exist_ok=True)
FIX = L.FIXTURE
exp = L.load(FIX / 'EXPECTATIONS.json')
pins = exp['context_identity_pins']
cases = {c['name']: c for c in exp['cases']}


def run_gate(proposal_path, context_path, pin, extra=()):
    return L.run_cli(L.gate_args(proposal_path, context_path, pin, extra))


def check_payload(r, want_rc):
    p = r['payload'] or {}
    whitelist = {'accepted', 'schema_invalid', 'ability_unknown', 'params_invalid', 'budget_exceeded',
                 'proposal_expired', 'time_domain_mismatch', 'evidence_mismatch', 'handle_unknown',
                 'effect_class_not_registered', 'duplicate_proposal', 'rejected_other'}
    return {
        'rc': r['returncode'], 'want_rc': want_rc, 'rc_ok': r['returncode'] == want_rc,
        'json_parse_ok': not r['json_parse_exception'],
        'stderr_no_traceback': 'Traceback' not in r['stderr'],
        'reason_code': p.get('reason_code'),
        'reason_whitelisted': p.get('reason_code') in whitelist,
        'world_log': p.get('world_side_log'),
        'errors': p.get('errors'),
        'decision': p.get('decision'),
        'stderr_tail': r['stderr'].strip()[-200:] if r['stderr'].strip() else '',
    }


def main():
    rows = []

    # ---- 1) 作者夹具 88/89 两条 JCS 反例 + 其破坏对照
    for name in ('jcs_int_out_of_range', 'jcs_lone_surrogate'):
        c = cases[name]
        pp = FIX / c['dir'] / c['proposal_file']
        cp = FIX / 'contexts' / c['context_file']
        r = run_gate(pp, cp, pins[name])
        row = check_payload(r, 1)
        row.update(name=name, kind='author_fixture',
                   jcs_log=any('jcs_canonicalization_failed' in str(x)
                               for x in (r['payload'] or {}).get('world_side_log') or []))
        extra = []
        for part in c['control'].split(','):
            rule = part.split(':', 1)[1] if part.startswith('disable:') else part
            extra += ['--disable', rule]
        ctl = run_gate(pp, cp, pins[name], extra)
        row['control'] = check_payload(ctl, 0)
        rows.append(row)

    # ---- 2) 独立构造异常提案（基于合法正例改一处）
    base = L.load(FIX / 'valid' / '01_valid_minimal_handle_target.json')
    ctxp = FIX / 'contexts' / '01_valid_minimal_handle_target.json'
    pin = L.jcs_sha(L.load(ctxp))

    def variant(name, mutate, raw_write=None):
        p = deepcopy(base)
        mutate(p)
        path = TMP / ('jcsprobe_' + name + '.json')
        if raw_write is not None:
            path.write_bytes(raw_write)
        else:
            L.write_json(path, p)
        return name, path

    def add_int(p):
        # basis.t_ticks 超 ±(2^53−1)：schema 只有 minimum 无上限，必须由 fail-closed 兜住
        p['basis']['t_ticks'] = 2 ** 53
        p['evidence_version'] = L.jcs_sha(p['basis']) if False else p['evidence_version']

    def add_big_param(p):
        p['params'] = {'speed_mps': 2 ** 53}

    def add_surrogate(p):
        p['proposal_id'] = 'prop-' + '\ud800' + '-x'

    def add_nan(p):
        p['params'] = {'speed_mps': float('nan')}

    def add_inf(p):
        p['params'] = {'speed_mps': float('inf')}

    variants = [
        variant('int_out_of_range_ticks', add_int),
        variant('int_out_of_range_param', add_big_param),
        variant('lone_surrogate_params', add_surrogate),
        variant('nan_param', add_nan),
        variant('inf_param', add_inf),
    ]
    # 无效 UTF-8 字节
    variants.append(('invalid_utf8', TMP / 'jcsprobe_invalid_utf8.json'))
    (TMP / 'jcsprobe_invalid_utf8.json').write_bytes(b'{"schema_version": "skill_proposal.v1",\n"proposal_id": "\xff\xfe"}')
    # 重复键（RFC 8259 允许；JCS 要求唯一键）：两个同名提案 ID
    dup_text = json.dumps(base, ensure_ascii=False)
    dup_text = dup_text.replace('"proposal_id": ' + json.dumps(base['proposal_id']),
                                '"proposal_id": "prop-dup-one", "proposal_id": ' +
                                json.dumps(base['proposal_id']))
    variants.append(('duplicate_keys', TMP / 'jcsprobe_duplicate_keys.json'))
    (TMP / 'jcsprobe_duplicate_keys.json').write_text(dup_text, encoding='utf-8')

    for name, path in variants:
        r = run_gate(path, ctxp, pin)
        row = check_payload(r, 1)
        row.update(name=name, kind='independent_probe')
        rows.append(row)
        # 对 JCS 类反例补破坏对照：关掉 jcs_fail_closed + 后续语义检查仍必须拒绝或明确 accepted
        r2 = run_gate(path, ctxp, pin, ['--disable', 'jcs_fail_closed'])
        row['control_disable_jcs'] = check_payload(r2, 1)

    # ---- 3) 断言汇总（mandated = F4 点名的超范围整数/孤立代理项/解码编码错误；
    #          重复键是 JCS 唯一性要求下的独立观察，单列，不作为 F4 判据）
    mandated = {'jcs_int_out_of_range', 'jcs_lone_surrogate', 'int_out_of_range_ticks',
                'int_out_of_range_param', 'lone_surrogate_params', 'nan_param', 'inf_param',
                'invalid_utf8'}
    bad = []
    for row in rows:
        if row['name'] not in mandated:
            continue
        if not (row['rc_ok'] and row['json_parse_ok'] and row['stderr_no_traceback'] and
                (row['want_rc'] == 0 or row['reason_whitelisted'])):
            bad.append(row)
        if 'jcs_log' in row and row['jcs_log'] is not True:
            bad.append({**row, 'what': 'missing jcs world log'})
    out = {
        'rows': rows,
        'all_expected_rc': all(r['rc_ok'] for r in rows),
        'all_json_parse': all(r['json_parse_ok'] for r in rows),
        'no_traceback': all(r['stderr_no_traceback'] for r in rows),
        'all_reasons_whitelisted': all(r['reason_whitelisted'] for r in rows if r['want_rc'] == 1),
        'bad': bad,
        'mandated_rows': sorted(mandated),
        'observation_rows': [r for r in rows if r['name'] not in mandated],
        'author_claims': {
            'cases': ['jcs_int_out_of_range', 'jcs_lone_surrogate'],
            'expected_reason': 'schema_invalid',
            'no_traceback': True,
            'isolated_controls': True,
        },
        'duplicate_key_observation': next(r for r in rows if r['name'] == 'duplicate_keys'),
    }
    L.write_json(RES / 'jcs_results.json', out)
    print(json.dumps({k: out[k] for k in ('all_expected_rc', 'all_json_parse', 'no_traceback',
                                         'all_reasons_whitelisted')}, ensure_ascii=False))
    print('rows:')
    for r in rows:
        ctl = r.get('control') or r.get('control_disable_jcs')
        print(' ', r['name'], '| rc', r['rc'], '| reason', r['reason_code'],
              '| log', r['world_log'], '| ctl rc', (ctl or {}).get('rc'))
    print('bad:', len(bad))
    print('JCS_VERDICT', 'PASS' if not bad else 'FAIL')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
