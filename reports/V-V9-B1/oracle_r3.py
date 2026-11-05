"""独立 oracle：V9.B5 复核者 deepseek-flash-r8t4 自写（不复用 B4 作者核对函数）。

用途：对 ainerzero.V9.B4 r3 交付的 SkillProposal/v1 契约与参考核对做独立交叉判定。
只读源码与夹具，不写被验文件。

包含三部分：
  1. 自写 JCS（RFC 8785）序列化与 sha256；
  2. 自写“世界侧标识键名”规范化判定（分档：mandated / plural_stem / padded）；
  3. 自写门禁 oracle（按 reports/V9-B1/COORDINATOR_DECISIONS.md 裁决 1–10 的可观察语义）。
"""

import hashlib
import json
import math
import re

MAX_SAFE_INT = 2 ** 53 - 1

SINGULAR_STEMS = ('world', 'entity', 'scene', 'event', 'instance', 'landmark', 'object',
                  'actor', 'agent', 'truth', 'hidden')
PLURALS = {'world': 'worlds', 'entity': 'entities', 'scene': 'scenes', 'event': 'events',
           'instance': 'instances', 'landmark': 'landmarks', 'object': 'objects',
           'actor': 'actors', 'agent': 'agents', 'truth': 'truths', 'hidden': 'hiddens'}
ID_TOKENS = ('id', 'ids', 'Id', 'ID', 'Ids')

VISIBLE_REASONS = ('accepted', 'schema_invalid', 'ability_unknown', 'params_invalid',
                   'budget_exceeded', 'proposal_expired', 'time_domain_mismatch',
                   'evidence_mismatch', 'handle_unknown', 'effect_class_not_registered',
                   'duplicate_proposal', 'rejected_other')


# --------------------------------------------------------------------- 自写 JCS

def _esc(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\b':
            out.append('\\b')
        elif ch == '\f':
            out.append('\\f')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif o < 0x20:
            out.append('\\u%04x' % o)
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _num(x):
    """ECMAScript Number::toString（RFC 8785 §3.2.2.3 的十进制形式）。"""
    if isinstance(x, bool):
        raise TypeError('bool is not a JCS number')
    if isinstance(x, int):
        if abs(x) > MAX_SAFE_INT:
            raise ValueError('integer out of safe range')
        return str(x)
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise ValueError('NaN/Inf forbidden')
        if x == 0.0:
            return '0'
        neg = x < 0
        s = repr(abs(x))
        if 'e' in s:
            mant, _, ex = s.partition('e')
            ex = int(ex)
        else:
            mant, ex = s, 0
        ip, _, fp = mant.partition('.')
        joined = ip + fp
        lead = len(joined) - len(joined.lstrip('0'))
        digits = joined.lstrip('0').rstrip('0') or '0'
        n = len(ip) + ex - lead
        k = len(digits)
        if k <= n <= 21:
            body = digits + '0' * (n - k)
        elif 0 < n <= 21:
            body = digits[:n] + '.' + digits[n:]
        elif -6 < n <= 0:
            body = '0.' + '0' * (-n) + digits
        else:
            e = n - 1
            body = digits[0] + (('.' + digits[1:]) if k > 1 else '') \
                + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
        return ('-' if neg else '') + body
    raise TypeError('not a JSON number: %r' % (x,))


def jcs(obj):
    if obj is None:
        return 'null'
    if obj is True:
        return 'true'
    if obj is False:
        return 'false'
    if isinstance(obj, str):
        return _esc(obj)
    if isinstance(obj, (int, float)):
        return _num(obj)
    if isinstance(obj, (list, tuple)):
        return '[' + ','.join(jcs(v) for v in obj) + ']'
    if isinstance(obj, dict):
        ks = sorted(obj.keys(), key=lambda k: k.encode('utf-16-be'))
        return '{' + ','.join(_esc(k) + ':' + jcs(obj[k]) for k in ks) + '}'
    raise TypeError('unsupported type %r' % (type(obj),))


def jcs_bytes(obj):
    return jcs(obj).encode('utf-8')


def sha256_jcs(obj):
    return hashlib.sha256(jcs_bytes(obj)).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


class DupKey(ValueError):
    pass


def _no_dup_pairs(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise DupKey('duplicate key: %s' % k)
        seen.add(k)
    return dict(pairs)


def load_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh, object_pairs_hook=_no_dup_pairs)


# --------------------------------------------------- 自写世界侧标识键名判定

def norm_key(k):
    """小写 + 去掉所有非字母数字（与任何实现细节无关的规范化）。"""
    return re.sub(r'[^a-z0-9]', '', str(k).lower())


def classify_key(k):
    """返回 None（允许）或分档字符串（必须拒绝）。

    mandated   ：11 个单数标识词 × id/ids，含大小写与分隔符变体，以及 id/ids 裸键与 hiddencontact。
    plural_stem：标识词复数 + id(s)（coordinator 要求里的“复数”读作词干复数时属此档）。
    padded     ：标识词(+s)+id(s) 后面还带后缀（或前面带前缀），如 worldIdsMap / gtObjectId。
    """
    n = norm_key(k)
    if n in ('id', 'ids'):
        return 'mandated'
    if 'hiddencontact' in n:
        return 'mandated'
    for s in SINGULAR_STEMS:
        if re.search(rf'{s}ids?$', n):
            return 'mandated'
    for s in SINGULAR_STEMS:
        if re.search(rf'{PLURALS[s]}ids?$', n):
            return 'plural_stem'
    for s in SINGULAR_STEMS:
        forms = (s, PLURALS[s])
        for f in forms:
            if re.search(rf'{f}ids?', n):
                return 'padded'
    return None


def scan_forbidden_keys(obj, path='', skip=('actor.agent_id',)):
    """提案任意层级的键名扫描；返回命中的 (path, key, family) 列表。"""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f'{path}.{k}' if path else str(k)
            if cur in skip:
                continue
            fam = classify_key(k)
            if fam:
                hits.append((cur, k, fam))
            hits.extend(scan_forbidden_keys(v, cur, skip))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(scan_forbidden_keys(item, f'{path}[{i}]', skip))
    return hits


# ------------------------------------------------------------------- 门禁 oracle

def _jcs_sha(obj):
    return sha256_jcs(obj)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def preconditions_met(ctx, entry):
    obs = ctx['observation']
    for c in entry.get('preconditions', []):
        if not isinstance(c, dict):
            return False
        kind = c.get('kind')
        name = c.get('observable')
        if kind == 'exists':
            if name.startswith('channel.'):
                if name.split('.', 1)[1] not in obs.get('present_channels', []):
                    return False
            else:
                cur = obs
                for part in name.split('.'):
                    if isinstance(cur, dict) and part in cur:
                        cur = cur[part]
                    else:
                        return False
                if cur is False or cur is None:
                    return False
        elif kind == 'compare':
            cur = obs
            for part in str(name).split('.'):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return False
            op, val = c.get('op'), c.get('value')
            if op == 'ne' and cur == val:
                return False
            elif op == 'eq' and cur != val:
                return False
            elif op not in ('ne', 'eq'):
                return False
        else:
            return False
    return True


def entry_problems(ctx, entry_schema=None):
    """对能力登记条目做独立检查（严格版：properties 与 patternProperties 都查）。"""
    import jsonschema
    p = []
    if entry_schema is not None:
        v = jsonschema.Draft202012Validator(entry_schema)
    ids = []
    for e in ctx['ability_registry']['entries']:
        ids.append(e.get('ability_id'))
        if entry_schema is not None and not v.is_valid(e):
            p.append('entry_schema:' + str(e.get('ability_id')))
            continue
        ps = e.get('param_schema')
        try:
            jsonschema.Draft202012Validator.check_schema(ps)
        except Exception:
            p.append('entry_param_schema_meta:' + str(e.get('ability_id')))
            continue
        if not isinstance(ps, dict) or ps.get('additionalProperties') is not False:
            p.append('entry_param_schema_not_closed:' + str(e.get('ability_id')))
        for group in ('properties', 'patternProperties'):
            for name in (ps.get(group) or {}):
                if classify_key(name):
                    p.append('entry_param_schema_forbidden_property:' + str(e.get('ability_id')) + ':' + name)
    if len(set(ids)) != len(ids):
        p.append('entry_duplicate_id')
    for d in ctx.get('decisions_seen', []):
        for k in ('proposal_id', 'proposal_digest', 'evidence_version', 'decision', 'reason_code',
                  'decided_at_tick'):
            if k not in d:
                p.append('decision_missing:' + k)
        if d.get('reason_code') not in VISIBLE_REASONS:
            p.append('decision_reason_not_whitelisted')
    return p


def oracle_gate(proposal, ctx, proposal_schema=None, entry_schema=None, pin=None):
    """独立门禁判定；返回 {'decision','reason_code','errors'}。"""
    import jsonschema
    if not isinstance(proposal, dict):
        return {'decision': None, 'reason_code': None, 'errors': ['proposal_shape']}
    if not isinstance(ctx, dict):
        return {'decision': None, 'reason_code': None, 'errors': ['trusted_context_missing']}
    if pin is not None and _jcs_sha(ctx) != pin:
        return {'decision': None, 'reason_code': None, 'errors': ['trusted_context_identity']}
    env = []
    if ctx.get('synthetic') is not True:
        env.append('context_not_marked_synthetic')
    for k in ('round', 'session', 'observation', 'ability_registry', 'world_side', 'decisions_seen'):
        if k not in ctx:
            env.append('context_missing:' + k)
    if env:
        return {'decision': None, 'reason_code': None, 'errors': env}
    env = entry_problems(ctx, entry_schema)
    if env:
        return {'decision': None, 'reason_code': None, 'errors': env}

    def rej(code):
        return {'decision': 'rejected', 'reason_code': code, 'errors': []}

    schema = proposal_schema
    if schema is not None and not jsonschema.Draft202012Validator(schema).is_valid(proposal):
        return rej('schema_invalid')
    if scan_forbidden_keys(proposal):
        return rej('schema_invalid')
    ability = proposal.get('ability_id')
    entry = None
    for e in ctx['ability_registry']['entries']:
        if e.get('ability_id') == ability:
            entry = e
            break
    if entry is None:
        return rej('ability_unknown')
    if entry.get('effect_class') != 'run':
        return rej('effect_class_not_registered')
    if not preconditions_met(ctx, entry):
        return rej('rejected_other')
    for t in proposal.get('targets', []):
        if not isinstance(t, dict) or t.get('kind') not in entry.get('target_kinds', []):
            return rej('rejected_other')
    if not jsonschema.Draft202012Validator(entry['param_schema']).is_valid(proposal.get('params')):
        return rej('params_invalid')
    basis = proposal.get('basis', {})
    if not isinstance(basis, dict) or _jcs_sha(basis) != proposal.get('evidence_version'):
        return rej('evidence_mismatch')
    if basis.get('packet_ref') != ctx['observation']['packet_ref']:
        return rej('evidence_mismatch')
    if basis.get('t_ticks') != ctx['observation']['t_ticks']:
        return rej('evidence_mismatch')
    if basis.get('time_domain') != ctx['round']['time_domain']:
        return rej('time_domain_mismatch')
    ttl = proposal.get('ttl_ticks')
    if not _is_int(ttl) or ttl < 1:
        return rej('schema_invalid')
    if ctx['round']['current_tick'] > basis['t_ticks'] + ttl:
        return rej('proposal_expired')
    if ttl > entry['max_ttl_ticks']:
        return rej('budget_exceeded')
    ab = proposal.get('action_budget', {})
    if ab.get('max_actions', 0) > entry['max_actions']:
        return rej('budget_exceeded')
    if ab.get('max_duration_ticks', 0) > entry['max_duration_ticks']:
        return rej('budget_exceeded')
    obs, ws = ctx['observation'], ctx['world_side']
    for t in proposal.get('targets', []):
        if not isinstance(t, dict) or t.get('kind') != 'handle':
            continue
        h = t.get('handle')
        if h in obs.get('retired_handles', []) or h not in obs.get('handles', []) \
                or h not in ws.get('handle_entity_map', {}):
            return rej('handle_unknown')
    if proposal.get('actor') != ctx['session']['actor']:
        return rej('rejected_other')
    for o in proposal.get('expected_outcomes', []):
        w = o.get('window', {}) if isinstance(o, dict) else {}
        s, e = w.get('start_offset_ticks'), w.get('end_offset_ticks')
        if not _is_int(s) or not _is_int(e) or not (0 <= s <= e <= ttl):
            return rej('schema_invalid')
    digest = _jcs_sha(proposal)
    for d in ctx['decisions_seen']:
        if d.get('proposal_id') != proposal.get('proposal_id'):
            continue
        if d.get('proposal_digest') == digest and d.get('evidence_version') == proposal.get('evidence_version'):
            return {'decision': d.get('decision'), 'reason_code': d.get('reason_code'),
                    'errors': [], 'replayed': True}
        return rej('duplicate_proposal')
    return {'decision': 'accepted', 'reason_code': 'accepted', 'errors': []}


def oracle_reply(reply, reply_schema):
    """独立回执判定：schema + 白名单原因码。"""
    import jsonschema
    errs = sorted(e.message for e in jsonschema.Draft202012Validator(reply_schema).iter_errors(reply))
    whitelist = set(reply_schema['$defs']['visible_reason_code']['enum'])
    return {'valid': (not errs) and reply.get('reason_code') in whitelist, 'errors': errs,
            'reason_whitelisted': reply.get('reason_code') in whitelist}
