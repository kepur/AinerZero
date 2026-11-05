"""V9.B4 CPU 参考核对：SkillProposal/v1 门禁（明确标 synthetic 的冻结上下文）。

依据：reports/V9-B1/COORDINATOR_DECISIONS.md 裁决 1–11 与「执行与证据」。

模式：
  gate  --proposal P --context C --expected-context-sha256 H [--schema S] [--reply-schema R] [--disable X]…
        读取待验提案与调用方固定的上下文身份，按裁决判定接受或拒绝。接受 exit 0，拒绝/环境错误 exit 1。
  reply --reply R [--reply-schema R]
        只核对门禁可见回执是否合 schema、原因码是否在白名单内。合 exit 0。
  --suite
        生成明确标 synthetic 的夹具（contracts/v9/examples/skill_proposal_v1/），
        子进程逐条验证正反例、单规则破坏对照、置信度扫描与 JCS 自测，结果写 check_result.json。

--disable / --schema / --reply-schema 只供报告目录的破坏测试，不是生产开关、不是授权、不改任何契约。
本脚本是参考核对，不是 AWZ 门禁实现；世界侧的完整决定只出现在本脚本的 world_side_log 里，永不进回执。
"""

import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PROPOSAL_SCHEMA = ROOT / 'contracts/v9/skill_proposal.v1.schema.json'
REPLY_SCHEMA = ROOT / 'contracts/v9/skill_gate_reply.v1.schema.json'
ENTRY_SCHEMA = ROOT / 'contracts/v9/ability_registry_entry.v0.schema.json'
FIXTURE = ROOT / 'contracts/v9/examples/skill_proposal_v1'
SABOTAGE = OUT / 'sabotage-schemas'


def configure_paths(root_dir=None):
    global ROOT, PROPOSAL_SCHEMA, REPLY_SCHEMA, ENTRY_SCHEMA, FIXTURE, SABOTAGE
    if root_dir:
        ROOT = Path(root_dir).resolve()
        PROPOSAL_SCHEMA = ROOT / 'contracts/v9/skill_proposal.v1.schema.json'
        REPLY_SCHEMA = ROOT / 'contracts/v9/skill_gate_reply.v1.schema.json'
        ENTRY_SCHEMA = ROOT / 'contracts/v9/ability_registry_entry.v0.schema.json'
        FIXTURE = ROOT / 'contracts/v9/examples/skill_proposal_v1'
        SABOTAGE = OUT / 'sabotage-schemas'


FORBIDDEN_STEMS = r'(world|entity|scene|event|instance|landmark|object|actor|agent|truth|hidden)'
FORBIDDEN_KEY_PATTERN = re.compile(rf'(^|.*){FORBIDDEN_STEMS}ids?$|^ids?$|.*hiddencontact.*')


def is_forbidden_world_id_key(k: str) -> bool:
    norm = re.sub(r'[^a-z0-9]', '', str(k).lower())
    return bool(FORBIDDEN_KEY_PATTERN.search(norm))


def has_forbidden_world_id_key(obj, path='') -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f"{path}.{k}" if path else str(k)
            if cur == 'actor.agent_id':
                continue
            if is_forbidden_world_id_key(k):
                return True
            if has_forbidden_world_id_key(v, cur):
                return True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if has_forbidden_world_id_key(item, f"{path}[{i}]"):
                return True
    return False


def check_schema_props_forbidden(s):
    if not isinstance(s, dict):
        return []
    forbidden = []
    if 'properties' in s and isinstance(s['properties'], dict):
        for prop_name, prop_schema in s['properties'].items():
            if is_forbidden_world_id_key(prop_name):
                forbidden.append(prop_name)
            forbidden.extend(check_schema_props_forbidden(prop_schema))
    if 'items' in s:
        forbidden.extend(check_schema_props_forbidden(s['items']))
    if '$defs' in s and isinstance(s['$defs'], dict):
        for d in s['$defs'].values():
            forbidden.extend(check_schema_props_forbidden(d))
    return forbidden


CHANNELS = ['symbol8', 'egocentric_grid', 'rgb', 'depth', 'relative_objects', 'ego_motion',
            'audio_events', 'semantic_mask']
# 裁决 8 的白名单：只允许这些原因码出现在门禁可见回执里。
VISIBLE_REASONS = ['accepted', 'schema_invalid', 'ability_unknown', 'params_invalid', 'budget_exceeded',
                   'proposal_expired', 'time_domain_mismatch', 'evidence_mismatch', 'handle_unknown',
                   'effect_class_not_registered', 'duplicate_proposal', 'rejected_other']
MAX_JCS_INT = 2 ** 53 - 1


# --------------------------------------------------------------------------- JCS (RFC 8785)

_ESC = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _jcs_string(s):
    out = ['"']
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _es6_number(x):
    """ECMAScript Number::toString（RFC 8785 §3.2.2.3）。"""
    if isinstance(x, bool):  # pragma: no cover - 调用方已分流
        raise TypeError('jcs_bool')
    if isinstance(x, int):
        if abs(x) > MAX_JCS_INT:
            raise ValueError('jcs_integer_out_of_range')
        return str(x)
    if not isinstance(x, float) or not math.isfinite(x):
        raise ValueError('jcs_non_finite')
    if x == 0:
        return '0'
    neg = x < 0
    _, digits, exp = Decimal(repr(abs(x))).as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    s = ''.join(str(d) for d in digits)
    k = len(s)
    n = k + exp
    if n <= -6 or n > 21:
        mant = s if k == 1 else s[0] + '.' + s[1:]
        e = n - 1
        body = mant + 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    elif k <= n <= 21:
        body = s + '0' * (n - k)
    elif 0 < n <= 21:
        body = s[:n] + '.' + s[n:]
    else:
        body = '0.' + '0' * (-n) + s
    return ('-' + body) if neg else body


def _jcs_into(o, out):
    if o is None:
        out.append('null')
    elif o is True:
        out.append('true')
    elif o is False:
        out.append('false')
    elif isinstance(o, str):
        out.append(_jcs_string(o))
    elif isinstance(o, (int, float)):
        out.append(_es6_number(o))
    elif isinstance(o, list):
        out.append('[')
        for i, v in enumerate(o):
            if i:
                out.append(',')
            _jcs_into(v, out)
        out.append(']')
    elif isinstance(o, dict):
        out.append('{')
        # RFC 8785 §3.2.3：键按 UTF-16 码元排序，不是按 Unicode 码点。
        for i, k in enumerate(sorted(o, key=lambda s: s.encode('utf-16-be'))):
            if i:
                out.append(',')
            out.append(_jcs_string(k))
            out.append(':')
            _jcs_into(o[k], out)
        out.append('}')
    else:
        raise TypeError('jcs_unsupported_type:' + type(o).__name__)


def jcs(o):
    out = []
    _jcs_into(o, out)
    return ''.join(out).encode('utf-8')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def jcs_sha(o):
    return sha(jcs(o))


def _dup_guard(items):
    seen = set()
    for k, _ in items:
        if k in seen:
            raise ValueError('duplicate_key:' + k)
        seen.add(k)
    return dict(items)


def _no_constants(c):
    raise ValueError('non_finite:' + c)


def load_json(path, *, strict=False):
    text = Path(path).read_text(encoding='utf-8')
    return json.loads(text, object_pairs_hook=_dup_guard if strict else None, parse_constant=_no_constants)


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def schema_load(path):
    s = load_json(path, strict=True)
    Draft202012Validator.check_schema(s)
    return s


def errors_of(validator, doc):
    return sorted({'%s@%s: %s' % (list(e.absolute_path), e.validator, e.message)
                   for e in validator.iter_errors(doc)})


# --------------------------------------------------------------------------- 冻结的 synthetic 上下文

EPISODE_ID = '0f2a7c1e-5b64-4d3a-9c88-1a2b3c4d5e6f'
EPOCH_ID = 'epoch-synthetic-0001'
TIME_DOMAIN = {'clock': 'episode_relative', 'episode_id': EPISODE_ID, 'epoch_id': EPOCH_ID, 'tick_hz': 120}
SESSION_ACTOR = {'kind': 'world_brain', 'run_id': 'run-synthetic-0007',
                 'agent_id': 'agent-7c1f0a92', 'policy_revision': 'v9-synthetic-brain-r1'}
PACKET_REF = {'uri': 'awz://observation/synthetic-episode-0001/000840',
              'sha256': sha(b'synthetic-observation-packet-v9b4')}
BELIEF_SHA = sha(b'synthetic-belief-summary-v9b4')
BRAIN = {'model_version': 'synthetic-brain-v0', 'encoder_version': 'synthetic-encoder-v0',
         'planner_version': 'synthetic-planner-v0'}
T_TICKS = 840
REPLAY_ID = 'prop-synthetic-replay-0001'
HANDLES = ['h-1', 'h-2', 'h-3', 'h-5']     # h-5 在包里但世界侧解析不到
RETIRED_HANDLES = ['h-4']                   # 遮挡重发后失效的旧句柄
HANDLE_ENTITY = {'h-1': 'entity-7f3a41c9b2e05d18', 'h-2': 'entity-2b9104e7ac63f852',
                 'h-3': 'entity-c40d9b1f5a72e630'}
HIDDEN_STATE = {'occluded_behind_wall': ['entity-5e1d77aa30bc9f42'],
                'nonexistent_after_tick': ['entity-88f20c6d41ae37b5']}


def base_basis():
    return {'packet_ref': dict(PACKET_REF), 't_ticks': T_TICKS, 'time_domain': dict(TIME_DOMAIN),
            'belief_sha256': BELIEF_SHA, 'brain': dict(BRAIN)}


REPLAY_EV = jcs_sha(base_basis())


def registry_entries():
    def entry(aid, eff, kinds, ma, md, mt, ps, pre):
        return {'schema_version': 'ability_registry_entry.v0', 'ability_id': aid, 'ability_version': '1.0',
                'effect_class': eff, 'target_kinds': kinds, 'max_actions': ma,
                'max_duration_ticks': md, 'max_ttl_ticks': mt, 'param_schema': ps, 'preconditions': pre}

    return [
        entry('abil-approach-object', 'run', ['handle'], 4, 120, 240,
              {'type': 'object', 'additionalProperties': False, 'required': ['speed_mps'],
               'properties': {'speed_mps': {'type': 'number', 'minimum': 0, 'maximum': 3}}},
              [{'kind': 'exists', 'observable': 'channel.relative_objects'}]),
        entry('abil-move-ego-relative', 'run', ['ego_relative_pose'], 8, 240, 480,
              {'type': 'object', 'additionalProperties': False, 'required': ['stride_m'],
               'properties': {'stride_m': {'type': 'number', 'minimum': 0, 'maximum': 2}}}, []),
        entry('abil-emit-audio-ping', 'run', [], 1, 12, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['loudness'],
               'properties': {'loudness': {'type': 'number', 'minimum': 0, 'maximum': 1}}},
              [{'kind': 'compare', 'observable': 'last_action_result.status', 'op': 'ne',
                'value': 'interrupted'}]),
        # 编辑类条目：v1 已登记的编辑类能力集合为空，被引用一律 effect_class_not_registered（裁决 1）。
        entry('abil-synthetic-edit-scene', 'edit', ['handle'], 1, 1, 60,
              {'type': 'object', 'additionalProperties': False, 'required': ['patch_op'],
               'properties': {'patch_op': {'type': 'string', 'enum': ['remove', 'replace']}}}, []),
        # 前置条件在本上下文不成立（payload 没有 pose_sensor）：核验前置条件真的被核验。
        entry('abil-require-pose-sensor', 'run', ['handle'], 2, 60, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['hold_ticks'],
               'properties': {'hold_ticks': {'type': 'integer', 'minimum': 1, 'maximum': 60}}},
              [{'kind': 'exists', 'observable': 'pose_sensor_if_allowed'}]),
        # 参数里带开放嵌套对象：用来核验世界 ID 键名在任意层级都被禁（裁决 2）。
        entry('abil-tag-objects', 'run', ['handle'], 2, 60, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['tags'],
               'properties': {'tags': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                                       'items': {'type': 'object', 'additionalProperties': {'type': 'string'}}}}},
              []),
    ]


def base_context(current_tick=850):
    return {
        'synthetic': True,
        'context_id': 'v9b4-synthetic-frozen-20261016',
        'note': '明确标 synthetic 的冻结上下文；不是真实 AWZ 回合，不构成运行授权，也不代表任何能力。',
        'round': {'round_id': 'round-synthetic-0007', 'episode_id': EPISODE_ID,
                  'time_domain': dict(TIME_DOMAIN), 'current_tick': current_tick,
                  'partition': 'development'},
        'session': {'actor': dict(SESSION_ACTOR)},
        'observation': {
            'packet_ref': dict(PACKET_REF), 't_ticks': T_TICKS, 'time_domain': dict(TIME_DOMAIN),
            'handles': list(HANDLES), 'retired_handles': list(RETIRED_HANDLES),
            'present_channels': ['relative_objects', 'ego_motion', 'symbol8'],
            'pose_sensor_if_allowed': False, 'episode_start': False,
            'last_action_result': {'status': 'executed', 'reason_code': 'none'},
        },
        'ability_registry': {
            'registry_id': 'awz-ability-registry-synthetic-0001', 'tick_hz': 120,
            'registered_edit_abilities': [], 'entries': registry_entries(),
        },
        'world_side': {'handle_entity_map': dict(HANDLE_ENTITY), 'unresolvable_handles': ['h-5'],
                       'hidden_state': copy.deepcopy(HIDDEN_STATE)},
        'decisions_seen': [],   # 由 suite 按重放夹具注入
    }


def context_problems(ctx):
    """上下文自身的结构断言；任一条不成立就 fail closed，不产生提案判定。"""
    if not isinstance(ctx, dict):
        return ['context_shape']
    p = []
    if ctx.get('synthetic') is not True:
        p.append('context_not_marked_synthetic')
    for k in ('context_id', 'round', 'session', 'observation', 'ability_registry', 'world_side',
              'decisions_seen'):
        if k not in ctx:
            p.append('context_missing:' + k)
    if p:
        return p
    rnd, obs, reg, ws = ctx['round'], ctx['observation'], ctx['ability_registry'], ctx['world_side']
    td = rnd.get('time_domain')
    if not isinstance(td, dict) or td.get('tick_hz') != 120 or td.get('clock') != 'episode_relative':
        p.append('context_time_domain')
    if obs.get('time_domain') != td:
        p.append('context_observation_time_domain')
    if not isinstance(rnd.get('current_tick'), int) or rnd['current_tick'] < 0:
        p.append('context_current_tick')
    if not isinstance(obs.get('t_ticks'), int) or obs['t_ticks'] < 0:
        p.append('context_t_ticks')
    if sorted(set(obs.get('handles', []))) != sorted(obs.get('handles', [])):
        p.append('context_duplicate_handles')
    if set(obs.get('retired_handles', [])) & set(obs.get('handles', [])):
        p.append('context_retired_overlaps_live')
    if not set(obs.get('present_channels', [])) <= set(CHANNELS):
        p.append('context_unknown_channel')
    if not isinstance(ctx['session'].get('actor'), dict):
        p.append('context_session_actor')
    if not isinstance(reg.get('registry_id'), str) or not reg['registry_id']:
        p.append('context_registry_id')
    if reg.get('registered_edit_abilities') != []:
        p.append('context_edit_set_not_empty')   # ADR-0005 例外集合为空的处理（裁决 1）
    if not isinstance(reg.get('entries'), list) or not reg['entries']:
        p.append('context_registry_entries')
    if not set(ws.get('handle_entity_map', {})) <= set(obs.get('handles', [])):
        p.append('context_entity_map_outside_packet')
    return p


def registry_problems(ctx, entry_schema=None):
    p = []
    v = Draft202012Validator(entry_schema or schema_load(ENTRY_SCHEMA))
    ids = []
    for e in ctx['ability_registry']['entries']:
        ids.append(e.get('ability_id'))
        if not v.is_valid(e):
            p.append('entry_schema:' + str(e.get('ability_id')))
            continue
        ps = e.get('param_schema')
        try:
            Draft202012Validator.check_schema(ps)
        except Exception:
            p.append('entry_param_schema_meta:' + str(e.get('ability_id')))
            continue
        # 裁决 2 / 裁决 5（r3）：param_schema 必须封闭（additionalProperties: false）
        if not isinstance(ps, dict) or ps.get('additionalProperties') is not False:
            p.append('entry_param_schema_not_closed:' + str(e.get('ability_id')))
        # 且属性名通过规范化判定
        bad_props = check_schema_props_forbidden(ps)
        for bp in bad_props:
            p.append('entry_param_schema_forbidden_property:' + str(e.get('ability_id')) + ':' + bp)
    if len(set(ids)) != len(ids):
        p.append('entry_duplicate_id')
    for d in ctx['decisions_seen']:
        for k in ('proposal_id', 'proposal_digest', 'evidence_version', 'decision', 'reason_code',
                  'decided_at_tick'):
            if k not in d:
                p.append('decision_missing:' + k)
        if d.get('reason_code') not in VISIBLE_REASONS:
            p.append('decision_reason_not_whitelisted')
    return p


# --------------------------------------------------------------------------- 门禁

def entry_for(ctx, ability_id):
    for e in ctx['ability_registry']['entries']:
        if e['ability_id'] == ability_id:
            return e
    return None


def observable_value(ctx, name):
    """把 observable 名字映到可核验的值；核验不了返回 (False, None)，由调用方 fail closed。"""
    obs = ctx['observation']
    if name.startswith('channel.'):
        return True, name[len('channel.'):] in obs['present_channels']
    if name == 'pose_sensor_if_allowed':
        return True, bool(obs['pose_sensor_if_allowed'])
    if name == 'episode_start':
        return True, bool(obs['episode_start'])
    if name == 'last_action_result.status':
        return True, obs['last_action_result']['status']
    if name == 'last_action_result.reason_code':
        return True, obs['last_action_result']['reason_code']
    if name == 'time.t_ticks':
        return True, obs['t_ticks']
    if name == 'time.dt_ticks':
        return True, ctx['round']['current_tick'] - obs['t_ticks']
    return False, None


OPS = {'lt': lambda a, b: a < b, 'le': lambda a, b: a <= b, 'gt': lambda a, b: a > b,
       'ge': lambda a, b: a >= b, 'eq': lambda a, b: a == b, 'ne': lambda a, b: a != b}


def preconditions_met(ctx, entry):
    """裁决 5：前置条件只能用观察可得的量表达；核验不了的量一律保守判为不成立。"""
    for c in entry['preconditions']:
        if c['kind'] == 'handle_present':
            if c['handle'] not in ctx['observation']['handles']:
                return False
            continue
        known, value = observable_value(ctx, c['observable'])
        if not known:
            return False
        if c['kind'] == 'exists':
            if not value:
                return False
        elif c['kind'] == 'compare' and not OPS[c['op']](value, c['value']):
            return False
    return True


def valid_until(proposal):
    try:
        return proposal['basis']['t_ticks'] + proposal['ttl_ticks']
    except Exception:
        return None


def build_reply(proposal, decision, reason_code, decided_at_tick):
    return {
        'schema_version': 'skill_gate_reply.v1',
        'proposal_id': proposal.get('proposal_id'),
        'evidence_version': proposal.get('evidence_version'),
        'decision': decision,
        'reason_code': reason_code,
        'decided_at_tick': decided_at_tick,
        'valid_until_tick': valid_until(proposal),
    }


def world_side_tokens(ctx):
    toks = set(ctx['world_side']['handle_entity_map'].values())
    for v in ctx['world_side']['hidden_state'].values():
        toks.update(v if isinstance(v, list) else [v])
    return sorted(t for t in toks if isinstance(t, str) and t)


def gate(proposal, ctx, pin, proposal_schema=None, disabled=()):
    """按裁决 1–10 判定。decision/reason_code 是回执可见量；world_side_log 只进世界侧日志。"""
    log = []
    schema = proposal_schema or schema_load(PROPOSAL_SCHEMA)

    def reject(code, world_reason):
        log.append(world_reason)
        return {'decision': 'rejected', 'reason_code': code, 'world_side_log': log}

    if not isinstance(proposal, dict):
        return {'decision': None, 'reason_code': None, 'errors': ['proposal_shape'],
                'world_side_log': ['proposal_shape']}
    if ctx is None:
        return {'decision': None, 'reason_code': None, 'errors': ['trusted_context_missing'],
                'world_side_log': ['trusted_context_missing']}
    if 'context_identity' not in disabled and (not pin or jcs_sha(ctx) != pin):
        return {'decision': None, 'reason_code': None, 'errors': ['trusted_context_identity'],
                'world_side_log': ['trusted_context_identity']}
    env = context_problems(ctx) or registry_problems(ctx)
    if env:
        return {'decision': None, 'reason_code': None, 'errors': env, 'world_side_log': env}

    decided_at = ctx['round']['current_tick']

    # 破坏对照专用接线：只在 --disable confidence_independence 下让置信度 1.0 短路所有门。
    if 'confidence_independence' in disabled and proposal.get('confidence') == 1.0:
        log.append('sabotage_confidence_override')
        return {'decision': 'accepted', 'reason_code': 'accepted', 'world_side_log': log}

    # 裁决 1/2/7/9：schema 层只做结构。世界 ID 字段、真值字段、非白名单形状在这里就被挡住。
    if 'schema' not in disabled and not Draft202012Validator(schema).is_valid(proposal):
        return reject('schema_invalid', 'schema_invalid')

    # 裁决 2（r3 规范化判定）：键名转小写、去掉非字母数字后，命中 forbidden pattern 即拒。
    # schema 正则作为第 1 层；本检查作为第 2 层，覆盖任意层级键名。
    if 'world_id_normalization' not in disabled and has_forbidden_world_id_key(proposal):
        return reject('schema_invalid', 'forbidden_world_id_key')

    # 裁决 5：能力登记是门禁的唯一依据。
    entry = entry_for(ctx, proposal.get('ability_id'))
    if entry is None and 'ability' not in disabled:
        return reject('ability_unknown', 'ability_unknown:' + str(proposal.get('ability_id')))
    if entry is None:
        # 破坏对照专用：关掉 ability 检查后，未登记能力按最宽松条目处理。
        entry = {'effect_class': 'run', 'target_kinds': ['handle', 'ego_relative_pose'],
                 'max_actions': 10 ** 9, 'max_duration_ticks': 10 ** 9, 'max_ttl_ticks': 10 ** 9,
                 'param_schema': {'type': 'object'}, 'preconditions': []}

    if 'precondition' not in disabled and not preconditions_met(ctx, entry):
        return reject('rejected_other', 'precondition_not_met:' + str(entry.get('ability_id')))

    # 裁决 1：v1 只开运行路线；编辑类效果一律拒。
    if 'effect_class' not in disabled and entry['effect_class'] != 'run':
        return reject('effect_class_not_registered', 'effect_class:' + str(entry['effect_class']))

    # 裁决 5：可作用的目标种类。
    if 'target_kind' not in disabled:
        for t in proposal.get('targets', []):
            if not isinstance(t, dict) or t.get('kind') not in entry['target_kinds']:
                return reject('rejected_other', 'target_kind_not_registered:'
                              + str(t.get('kind') if isinstance(t, dict) else t))

    # 裁决 5：参数按登记条目的 param_schema 校验。
    if 'params' not in disabled:
        if not Draft202012Validator(entry['param_schema']).is_valid(proposal.get('params')):
            return reject('params_invalid', 'params_invalid:' + str(entry.get('ability_id')))

    # 裁决 3：门禁重算 basis 的 JCS 摘要；basis 必须绑定到可信的当前包。
    basis = proposal.get('basis', {})
    if 'evidence' not in disabled:
        if not isinstance(basis, dict) or jcs_sha(basis) != proposal.get('evidence_version'):
            return reject('evidence_mismatch', 'evidence_digest_mismatch')
        if basis.get('packet_ref') != ctx['observation']['packet_ref']:
            return reject('evidence_mismatch', 'evidence_packet_ref_mismatch')
        if basis.get('t_ticks') != ctx['observation']['t_ticks']:
            return reject('evidence_mismatch', 'evidence_t_ticks_mismatch')

    # 裁决 4：时间域不一致直接拒，不做换算。
    if 'time_domain' not in disabled and basis.get('time_domain') != ctx['round']['time_domain']:
        return reject('time_domain_mismatch', 'time_domain_mismatch')

    # 裁决 4：TTL 用 tick 计，闭区间 [t_ticks, t_ticks + ttl_ticks]。
    if 'ttl' not in disabled:
        vu = valid_until(proposal)
        if vu is None or decided_at > vu:
            return reject('proposal_expired', 'proposal_expired:%s>%s' % (decided_at, vu))

    # 裁决 5：TTL 上限、动作数、持续时长。
    if 'budget' not in disabled:
        ab = proposal.get('action_budget', {})
        if proposal.get('ttl_ticks', 0) > entry['max_ttl_ticks']:
            return reject('budget_exceeded', 'ttl_over_cap')
        if not isinstance(ab, dict) or ab.get('max_actions', 0) > entry['max_actions']:
            return reject('budget_exceeded', 'actions_over_cap')
        if ab.get('max_duration_ticks', 0) > entry['max_duration_ticks']:
            return reject('budget_exceeded', 'duration_over_cap')

    # 裁决 2：句柄必须在所依据的包里、未因遮挡重发失效、且世界侧可解析。
    if 'handle' not in disabled:
        obs, ws = ctx['observation'], ctx['world_side']
        for t in proposal.get('targets', []):
            if not isinstance(t, dict) or t.get('kind') != 'handle':
                continue
            h = t.get('handle')
            if h in obs['retired_handles']:
                return reject('handle_unknown', 'handle_retired_after_occlusion:' + str(h))
            if h not in obs['handles']:
                return reject('handle_unknown', 'handle_not_in_packet:' + str(h))
            if h not in ws['handle_entity_map']:
                return reject('handle_unknown', 'handle_unresolvable_world_side:' + str(h))

    # 裁决 10：门禁从会话取 actor。
    if 'actor' not in disabled and proposal.get('actor') != ctx['session']['actor']:
        return reject('rejected_other', 'actor_mismatch')

    # 裁决 7：预期结果的时间窗是相对 basis.t_ticks 的闭区间，且落在 TTL 内。
    if 'outcome_window' not in disabled:
        ttl = proposal.get('ttl_ticks', 0)
        for o in proposal.get('expected_outcomes', []):
            w = o.get('window', {}) if isinstance(o, dict) else {}
            s, e = w.get('start_offset_ticks'), w.get('end_offset_ticks')
            if not isinstance(s, int) or not isinstance(e, int) or not (0 <= s <= e <= ttl):
                return reject('schema_invalid', 'outcome_window_out_of_range')

    # 裁决 10：同 ID 同摘要返回原决定；同 ID 不同摘要 duplicate_proposal。
    # 身份摘要取整份提案的 JCS 摘要（含 evidence_version）。这比只比 evidence_version 更严，
    # 口径说明见 docs/v9/SKILL_PROPOSAL.md §裁决 10。
    if 'duplicate' not in disabled:
        digest = jcs_sha(proposal)
        for d in ctx['decisions_seen']:
            if d['proposal_id'] != proposal.get('proposal_id'):
                continue
            if d['proposal_digest'] == digest and d['evidence_version'] == proposal.get('evidence_version'):
                log.append('duplicate_replay:' + d['reason_code'])
                return {'decision': d['decision'], 'reason_code': d['reason_code'],
                        'world_side_log': log, 'replayed': True}
            return reject('duplicate_proposal', 'duplicate_id_changed_payload')

    log.append('accepted')
    return {'decision': 'accepted', 'reason_code': 'accepted', 'world_side_log': log}


def whitelist_of(reply_schema):
    """白名单以 schema 为唯一来源；schema 被变异时核对器必须跟着变，破坏对照才有意义。"""
    try:
        return set(reply_schema['$defs']['visible_reason_code']['enum'])
    except Exception:  # pragma: no cover
        return set(VISIBLE_REASONS)


def gate_and_check(proposal, ctx, pin, proposal_schema=None, reply_schema=None, disabled=()):
    schema = proposal_schema or schema_load(PROPOSAL_SCHEMA)
    rschema = reply_schema or schema_load(REPLY_SCHEMA)
    res = gate(proposal, ctx, pin, schema, disabled)
    if res.get('reason_code') is None:            # 环境错误：不产生回执
        res.update(ok=False, reply=None, reply_schema_errors=[], leaked_world_side_tokens=[],
                   reason_whitelisted=False)
        return res
    reply = build_reply(proposal, res['decision'], res['reason_code'], ctx['round']['current_tick'])
    errs = errors_of(Draft202012Validator(rschema), reply)
    toks = world_side_tokens(ctx)
    blob = jcs(reply).decode('utf-8')
    leaked = [t for t in toks if t in blob]
    # 安全阀：提案本身取不出合法回显字段时（proposal_id/evidence_version 不可用），
    # 回执只能如实留空；这只在 schema_invalid 下成立，且不放过任何白名单违规。
    echo_degraded = bool(errs) and res['reason_code'] == 'schema_invalid' and \
        not isinstance(proposal.get('evidence_version'), str)
    res.update(reply=reply, reply_schema_errors=errs, leaked_world_side_tokens=leaked,
               reason_whitelisted=reply['reason_code'] in whitelist_of(rschema),
               proposal_digest=jcs_sha(proposal), context_sha256=jcs_sha(ctx))
    res['ok'] = ((not errs) or echo_degraded) and (not leaked) and res['reason_whitelisted']
    return res


# --------------------------------------------------------------------------- worker

def worker_gate(a):
    proposal = load_json(a.proposal)
    ctx = load_json(a.context) if a.context else None
    res = gate_and_check(proposal, ctx, a.expected_context_sha256, schema_load(a.schema),
                         schema_load(a.reply_schema), a.disable)
    out = {k: res.get(k) for k in ('ok', 'decision', 'reason_code', 'errors', 'reply_schema_errors',
                                   'leaked_world_side_tokens', 'reason_whitelisted', 'world_side_log',
                                   'replayed', 'proposal_digest', 'context_sha256', 'reply')}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if (res.get('decision') == 'accepted' and res.get('ok')) else 1


def worker_reply(a):
    rdoc = load_json(a.reply)
    rschema = schema_load(a.reply_schema)
    errs = errors_of(Draft202012Validator(rschema), rdoc)
    whitelisted = rdoc.get('reason_code') in whitelist_of(rschema)
    print(json.dumps({'ok': not errs and whitelisted, 'errors': errs,
                      'reason_whitelisted': whitelisted}, ensure_ascii=False))
    return 0 if (not errs and whitelisted) else 1


# --------------------------------------------------------------------------- 夹具

def base_proposal(ctx):
    basis = {'packet_ref': dict(ctx['observation']['packet_ref']), 't_ticks': ctx['observation']['t_ticks'],
             'time_domain': dict(ctx['observation']['time_domain']), 'belief_sha256': BELIEF_SHA,
             'brain': dict(BRAIN)}
    return {
        'schema_version': 'skill_proposal.v1',
        'proposal_id': 'prop-synthetic-approach-0001',
        'actor': dict(ctx['session']['actor']),
        'basis': basis,
        'evidence_version': jcs_sha(basis),
        'ability_id': 'abil-approach-object',
        'params': {'speed_mps': 1.5},
        'targets': [{'kind': 'handle', 'handle': 'h-1'}],
        'action_budget': {'max_actions': 2, 'max_duration_ticks': 60},
        'ttl_ticks': 120,
        'expected_outcomes': [{'channel': 'relative_objects', 'quantity': 'detection.rel_position_m',
                               'predicted_value': 0.4, 'uncertainty': {'sigma': 0.05, 'units': 'm'},
                               'window': {'start_offset_ticks': 0, 'end_offset_ticks': 120}}],
        'confidence': 0.6,
        'calibration': 'uncalibrated',
    }


def replay_proposal():
    p = base_proposal(base_context())
    p.update(proposal_id=REPLAY_ID, params={'speed_mps': 1.0}, confidence=0.5)
    return p


def replay_record():
    """decisions_seen 里已存的那条决定：同 ID 同摘要重放时必须原样返回。"""
    p = replay_proposal()
    return {'proposal_id': REPLAY_ID, 'proposal_digest': jcs_sha(p), 'evidence_version': REPLAY_EV,
            'decision': 'accepted', 'reason_code': 'accepted', 'decided_at_tick': 850}


# --- 各反例的专用变形（每个只制造一处违规，好让破坏对照真的隔离）

def m_world_id(field):
    return lambda p, c: p.update({field: 'world-synthetic-0001'})


def m_edit_class(p, c):
    p.update(ability_id='abil-synthetic-edit-scene', params={'patch_op': 'replace'},
             targets=[{'kind': 'handle', 'handle': 'h-2'}],
             action_budget={'max_actions': 1, 'max_duration_ticks': 1}, ttl_ticks=60,
             expected_outcomes=[{'channel': 'relative_objects', 'quantity': 'detection.rel_position_m',
                                 'predicted_value': 0.4, 'uncertainty': {'sigma': 0.05, 'units': 'm'},
                                 'window': {'start_offset_ticks': 0, 'end_offset_ticks': 60}}])


def m_duplicate_changed_evidence(p, c):
    p.update(proposal_id=REPLAY_ID, params={'speed_mps': 2.0})
    p['basis']['belief_sha256'] = '2' * 64
    p['evidence_version'] = jcs_sha(p['basis'])


def m_duplicate_same_evidence(p, c):
    p.update(proposal_id=REPLAY_ID, params={'speed_mps': 2.0})


def m_packet_ref_mismatch(p, c):
    p['basis']['packet_ref'] = dict(PACKET_REF, sha256='1' * 64)
    p['evidence_version'] = jcs_sha(p['basis'])


def m_time_domain(p, c):
    p['basis']['time_domain']['epoch_id'] = 'epoch-synthetic-0002'
    p['evidence_version'] = jcs_sha(p['basis'])


def m_ego_relative(p, c):
    p.update(ability_id='abil-move-ego-relative', params={'stride_m': 0.5},
             targets=[{'kind': 'ego_relative_pose', 'rel_position_m': [0.5, 0.0, 0.0], 'rel_yaw_deg': 0,
                       'uncertainty': {'sigma': 0.1, 'units': 'm'}}],
             action_budget={'max_actions': 4, 'max_duration_ticks': 120}, ttl_ticks=240)


def m_audio_ping(p, c):
    p.update(ability_id='abil-emit-audio-ping', params={'loudness': 0.4}, targets=[],
             action_budget={'max_actions': 1, 'max_duration_ticks': 12}, ttl_ticks=120,
             expected_outcomes=[{'channel': 'audio_events', 'quantity': 'audio_events.loudness',
                                 'predicted_value': 0.4, 'uncertainty': {'sigma': 0.1},
                                 'window': {'start_offset_ticks': 0, 'end_offset_ticks': 60}}])


def m_target_kind(p, c):
    p.update(ability_id='abil-emit-audio-ping', params={'loudness': 0.4},
             action_budget={'max_actions': 1, 'max_duration_ticks': 12})


def cases():
    """每条规则一个独立反例；valid=True 是正例。control 是「关掉该检查后本反例漏检」的破坏对照。"""
    cs = []

    def add(name, valid, reason, rule, control, mutate, tick=850, mutation=None):
        cs.append({'name': name, 'valid': valid, 'reason': reason, 'rule': rule, 'control': control,
                   'mutate': mutate, 'tick': tick, 'mutation': mutation})

    # ---- 正例
    add('valid_minimal_handle_target', True, None, None, None, lambda p, c: None)
    add('valid_ttl_upper_boundary', True, None, 'ttl', None, lambda p, c: None, tick=T_TICKS + 120)
    add('valid_ttl_lower_boundary', True, None, 'ttl', None, lambda p, c: None, tick=T_TICKS)
    add('valid_budget_at_cap', True, None, 'budget', None,
        lambda p, c: p.update(action_budget={'max_actions': 4, 'max_duration_ticks': 120}))
    add('valid_confidence_at_zero', True, None, None, None, lambda p, c: p.update(confidence=0.0))
    add('valid_ego_relative_target', True, None, None, None, m_ego_relative)
    add('valid_no_target_audio_ping', True, None, None, None, m_audio_ping)
    add('replay_same_id_same_digest', True, None, 'duplicate', None, lambda p, c: None)

    # ---- 结构反例：世界 ID 字段（裁决 2）
    for field in ('world_id', 'entity_id', 'scene_id', 'event_id'):
        add('world_id_field_' + field, False, 'schema_invalid', 'schema',
            'mutation:proposal_no_additional_properties', m_world_id(field),
            mutation='proposal_no_additional_properties')
    add('world_id_in_target', False, 'schema_invalid', 'schema',
        'mutation:proposal_no_additional_properties',
        lambda p, c: p['targets'][0].update({'entity_id': 'entity-synthetic-0001'}),
        mutation='proposal_no_additional_properties')
    add('world_id_in_params', False, 'schema_invalid', 'schema',
        'mutation:proposal_no_world_id_key',
        lambda p, c: p.update(ability_id='abil-tag-objects',
                              params={'tags': [{'color': 'red',
                                                'entity_id': 'entity-synthetic-0001'}]}),
        mutation='proposal_no_world_id_key')
    add('world_id_camel_in_params', False, 'schema_invalid', 'schema',
        'mutation:proposal_no_world_id_key',
        lambda p, c: p.update(ability_id='abil-tag-objects',
                              params={'tags': [{'color': 'red', 'worldId': 'world-synthetic-0001',
                                                'entityID': 'entity-synthetic-0001'}]}),
        mutation='proposal_no_world_id_key')
    norm_spellings = [
        ('OBJECT_ID', 'OBJECT_ID'),
        ('Entity_Id', 'Entity_Id'),
        ('ENTITY_ID', 'ENTITY_ID'),
        ('entity-id', 'entity_hyphen_id'),
        ('world.id', 'world_dot_id'),
        ('objectId', 'objectId'),
        ('actorIds', 'actorIds'),
        ('instanceId', 'instanceId'),
        ('landmarkId', 'landmarkId'),
        ('agentId', 'agentId'),
        ('truthId', 'truthId'),
        ('gtObjectId', 'gtObjectId'),
    ]
    for key_spelling, case_suffix in norm_spellings:
        add('world_id_norm_' + case_suffix, False, 'schema_invalid', 'world_id_normalization',
            'disable:world_id_normalization',
            lambda p, c, k=key_spelling: p.update(
                ability_id='abil-tag-objects',
                params={'tags': [{'color': 'red', k: 'world-synthetic-0001'}]}
            ))
    for token in ('world_id', 'hidden_contact'):
        add('quantity_value_' + token, False, 'schema_invalid', 'schema',
            'mutation:proposal_quantity_value_open',
            lambda p, c, token=token: p['expected_outcomes'][0].update(quantity=token),
            mutation='proposal_quantity_value_open')
    add('expected_outcome_truth_field', False, 'schema_invalid', 'schema',
        'mutation:proposal_no_additional_properties',
        lambda p, c: p['expected_outcomes'][0].update({'truth_position_m': [1.0, 2.0, 3.0]}),
        mutation='proposal_no_additional_properties')
    add('confidence_without_calibration', False, 'schema_invalid', 'schema',
        'mutation:proposal_drop_dependent_required',
        lambda p, c: p.pop('calibration'), mutation='proposal_drop_dependent_required')
    add('outcome_window_reversed', False, 'schema_invalid', 'outcome_window', 'disable:outcome_window',
        lambda p, c: p['expected_outcomes'][0]['window'].update({'start_offset_ticks': 90,
                                                                 'end_offset_ticks': 10}))

    # ---- 句柄（裁决 2）
    add('handle_not_in_packet', False, 'handle_unknown', 'handle', 'disable:handle',
        lambda p, c: p['targets'][0].update({'handle': 'h-9'}))
    add('handle_retired_after_occlusion', False, 'handle_unknown', 'handle', 'disable:handle',
        lambda p, c: p['targets'][0].update({'handle': 'h-4'}))
    add('handle_unresolvable_world_side', False, 'handle_unknown', 'handle', 'disable:handle',
        lambda p, c: p['targets'][0].update({'handle': 'h-5'}))

    # ---- 证据与时间域（裁决 3、4）
    add('evidence_digest_mismatch', False, 'evidence_mismatch', 'evidence', 'disable:evidence',
        lambda p, c: p.update(evidence_version='0' * 64))
    add('evidence_packet_ref_mismatch', False, 'evidence_mismatch', 'evidence', 'disable:evidence',
        m_packet_ref_mismatch)
    add('time_domain_mismatch', False, 'time_domain_mismatch', 'time_domain', 'disable:time_domain',
        m_time_domain)

    # ---- TTL 与预算（裁决 4、5）
    add('ttl_expired', False, 'proposal_expired', 'ttl', 'disable:ttl', lambda p, c: None,
        tick=T_TICKS + 120 + 1)
    add('ttl_over_registry_cap', False, 'budget_exceeded', 'budget', 'disable:budget',
        lambda p, c: p.update(ttl_ticks=241))
    add('actions_over_cap', False, 'budget_exceeded', 'budget', 'disable:budget',
        lambda p, c: p.update(action_budget={'max_actions': 5, 'max_duration_ticks': 60}))
    add('duration_over_cap', False, 'budget_exceeded', 'budget', 'disable:budget',
        lambda p, c: p.update(action_budget={'max_actions': 2, 'max_duration_ticks': 121}))

    # ---- 能力（裁决 1、5）
    add('ability_unknown', False, 'ability_unknown', 'ability', 'disable:ability',
        lambda p, c: p.update(ability_id='abil-unregistered-9999'))
    add('params_out_of_range', False, 'params_invalid', 'params', 'disable:params',
        lambda p, c: p.update(params={'speed_mps': 9.0}))
    add('params_missing_required', False, 'params_invalid', 'params', 'disable:params',
        lambda p, c: p.update(params={}))
    add('edit_effect_class', False, 'effect_class_not_registered', 'effect_class', 'disable:effect_class',
        m_edit_class)
    add('precondition_not_met', False, 'rejected_other', 'precondition', 'disable:precondition',
        lambda p, c: p.update(ability_id='abil-require-pose-sensor', params={'hold_ticks': 10}))
    add('target_kind_not_registered', False, 'rejected_other', 'target_kind', 'disable:target_kind',
        m_target_kind)

    # ---- actor 与幂等（裁决 10）
    add('actor_mismatch', False, 'rejected_other', 'actor', 'disable:actor',
        lambda p, c: p['actor'].update({'agent_id': 'agent-0000dead'}))
    add('duplicate_id_changed_evidence', False, 'duplicate_proposal', 'duplicate', 'disable:duplicate',
        m_duplicate_changed_evidence)
    add('duplicate_id_same_evidence_changed_params', False, 'duplicate_proposal', 'duplicate',
        'disable:duplicate', m_duplicate_same_evidence)

    # ---- 置信度不是门禁依据（裁决 6）
    add('confidence_one_ability_unknown', False, 'ability_unknown', 'confidence_independence',
        'disable:confidence_independence',
        lambda p, c: p.update(ability_id='abil-unregistered-zzz', confidence=1.0,
                              calibration='uncalibrated'))
    return cs


def reply_cases():
    good = {'schema_version': 'skill_gate_reply.v1', 'proposal_id': 'prop-synthetic-approach-0001',
            'evidence_version': jcs_sha({'synthetic': 'reply-evidence'}), 'decision': 'accepted',
            'reason_code': 'accepted', 'decided_at_tick': 850, 'valid_until_tick': 960}
    out = []

    def add(name, valid, mutate, mutation):
        r = copy.deepcopy(good)
        mutate(r)
        out.append({'name': name, 'valid': valid, 'reply': r, 'mutation': mutation})

    add('accepted_reply', True, lambda r: None, None)
    add('rejected_reply_whitelisted', True,
        lambda r: r.update(decision='rejected', reason_code='handle_unknown'), None)
    add('rejected_reply_rejected_other', True,
        lambda r: r.update(decision='rejected', reason_code='rejected_other'), None)
    add('reply_reason_not_whitelisted', False,
        lambda r: r.update(decision='rejected', reason_code='target_behind_wall'),
        'reply_enum_widened')
    add('reply_reason_hidden_state_leak', False,
        lambda r: r.update(decision='rejected', reason_code='object_no_longer_exists'),
        'reply_enum_widened')
    add('reply_carries_resolved_entity', False,
        lambda r: r.update(resolved_entity_id='entity-7f3a41c9b2e05d18'),
        'reply_no_additional_properties')
    add('reply_accepted_with_rejected_code', False,
        lambda r: r.update(decision='accepted', reason_code='handle_unknown'), 'reply_drop_consistency')
    add('reply_rejected_with_accepted_code', False,
        lambda r: r.update(decision='rejected', reason_code='accepted'), 'reply_drop_consistency')
    add('reply_uppercase_sha', False,
        lambda r: r.update(evidence_version=r['evidence_version'].upper()), 'reply_sha_pattern')
    add('reply_ttl_window_negative', False, lambda r: r.update(valid_until_tick=-1), 'reply_drop_minimum')
    return out


# --------------------------------------------------------------------------- 破坏用 schema 变异

def mutate_proposal(s):
    x = copy.deepcopy(s)
    x['additionalProperties'] = True
    x['$defs']['expected_outcome']['additionalProperties'] = True
    x['$defs']['basis']['additionalProperties'] = True
    for br in x['$defs']['target']['oneOf']:
        br['additionalProperties'] = True
    return x


def mutate_params_keys(s):
    x = copy.deepcopy(s)
    x['properties']['params'].pop('propertyNames')
    x['$defs']['param_value']['oneOf'][5].pop('propertyNames')
    return x


def mutate_quantity_value(s):
    x = copy.deepcopy(s)
    q = x['$defs']['expected_outcome']['properties']['quantity']
    q.clear()
    q['type'] = 'string'
    q['pattern'] = '^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$'
    q['description'] = '破坏对照：去掉 quantity 值上的世界标识与隐藏接触禁令。'
    return x


def mutate_dependent_required(s):
    x = copy.deepcopy(s)
    x.pop('dependentRequired')
    return x


def mutate_reply_enum(s):
    x = copy.deepcopy(s)
    x['$defs']['visible_reason_code']['enum'] += ['target_behind_wall', 'object_no_longer_exists']
    x['$defs']['rejected_reason_code']['enum'] += ['target_behind_wall', 'object_no_longer_exists']
    return x


def mutate_reply_additional(s):
    x = copy.deepcopy(s)
    x['additionalProperties'] = True
    return x


def mutate_reply_consistency(s):
    x = copy.deepcopy(s)
    x.pop('allOf')
    return x


def mutate_reply_sha(s):
    x = copy.deepcopy(s)
    x['$defs']['sha256']['pattern'] = '^[0-9a-fA-F]{64}$'
    return x


def mutate_reply_minimum(s):
    x = copy.deepcopy(s)
    for k in ('decided_at_tick', 'valid_until_tick'):
        x['properties'][k].pop('minimum')
    return x


PROPOSAL_MUTATIONS = {'proposal_no_additional_properties': mutate_proposal,
                      'proposal_no_world_id_key': mutate_params_keys,
                      'proposal_quantity_value_open': mutate_quantity_value,
                      'proposal_drop_dependent_required': mutate_dependent_required}
REPLY_MUTATIONS = {'reply_enum_widened': mutate_reply_enum,
                   'reply_no_additional_properties': mutate_reply_additional,
                   'reply_drop_consistency': mutate_reply_consistency,
                   'reply_sha_pattern': mutate_reply_sha,
                   'reply_drop_minimum': mutate_reply_minimum}


# --------------------------------------------------------------------------- JCS 自测

def jcs_self_tests():
    v = [
        ('rfc8785_3_2_2_numbers_literals',
         {'numbers': [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27], 'literals': [None, True, False]},
         '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'),
        ('key_sort_utf16', {'b': 1, 'a': 2}, '{"a":2,"b":1}'),
        ('es6_integer_form_at_1e20', {'n': 1e20}, '{"n":100000000000000000000}'),
        ('es6_exponential_at_1e21', {'n': 1e21}, '{"n":1e+21}'),
        ('es6_negative_zero', {'n': -0.0}, '{"n":0}'),
        ('es6_small_exponential', {'n': 1e-7}, '{"n":1e-7}'),
        ('es6_small_decimal', {'n': 1e-6}, '{"n":0.000001}'),
        ('string_escapes', {'s': 'a"b\\c\nd\te\x01f'}, '{"s":"a\\"b\\\\c\\nd\\te\\u0001f"}'),
        ('non_ascii_passthrough', {'s': '\u20ac\u00f6'}, '{"s":"\u20ac\u00f6"}'),
        ('key_sort_utf16_beyond_bmp',
         {k: i for i, k in enumerate(['\ufb33', '\u000d', '1', '\u20ac', '\U00010000'])},
         '{"\\r":1,"1":2,"\u20ac":3,"\U00010000":4,"\ufb33":0}'),
        ('negative_number', -1.5, '-1.5'),
        ('int_2_53_minus_1', MAX_JCS_INT, str(MAX_JCS_INT)),
    ]
    rows = []
    for name, obj, expected in v:
        if isinstance(obj, (int, float)) and not isinstance(obj, bool) and name in (
                'negative_number', 'int_2_53_minus_1'):
            try:
                got = jcs({'v': obj}).decode('utf-8')[5:-1]
            except Exception as e:  # pragma: no cover
                got = 'exception:%s' % e
        else:
            try:
                got = jcs(obj).decode('utf-8')
            except Exception as e:  # pragma: no cover
                got = 'exception:%s' % e
        rows.append({'name': name, 'ok': got == expected, 'expected': expected, 'got': got})
    for name, fn in (('reject_nan', lambda: jcs(float('nan'))),
                     ('reject_inf', lambda: jcs(float('inf'))),
                     ('reject_int_over_range', lambda: jcs(MAX_JCS_INT + 1))):
        try:
            fn()
            rows.append({'name': name, 'ok': False, 'expected': 'raise', 'got': 'no_raise'})
        except Exception as e:
            rows.append({'name': name, 'ok': True, 'expected': 'raise', 'got': type(e).__name__})
    for name, text in (('reject_duplicate_key', '{"a":1,"a":2}'),
                       ('reject_nan_literal', '{"a":NaN}'),
                       ('reject_inf_literal', '{"a":Infinity}')):
        try:
            json.loads(text, object_pairs_hook=_dup_guard, parse_constant=_no_constants)
            rows.append({'name': name, 'ok': False, 'expected': 'raise', 'got': 'no_raise'})
        except Exception as e:
            rows.append({'name': name, 'ok': True, 'expected': 'raise', 'got': type(e).__name__})
    return rows


# --------------------------------------------------------------------------- suite

def run_process(argv):
    r = subprocess.run(argv, capture_output=True, text=True)
    try:
        payload = json.loads(r.stdout)
        exception = False
    except json.JSONDecodeError:
        payload = {'stdout': r.stdout, 'stderr': r.stderr}
        exception = True
    return {'argv': argv, 'returncode': r.returncode, 'payload': payload, 'exception': exception}


def generate_fixtures_to_dir(fixture_dir: Path, sabotage_dir: Path, pschema, rschema):
    mut_paths = {}
    sabotage_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in list(PROPOSAL_MUTATIONS.items()) + list(REPLY_MUTATIONS.items()):
        p = sabotage_dir / (name + '.json')
        write(p, fn(pschema if name in PROPOSAL_MUTATIONS else rschema))
        mut_paths[name] = p

    (fixture_dir / 'contexts').mkdir(parents=True, exist_ok=True)
    (fixture_dir / 'valid').mkdir(parents=True, exist_ok=True)
    (fixture_dir / 'invalid').mkdir(parents=True, exist_ok=True)
    (fixture_dir / 'replies/valid').mkdir(parents=True, exist_ok=True)
    (fixture_dir / 'replies/invalid').mkdir(parents=True, exist_ok=True)

    write(fixture_dir / 'contexts/baseline.json', base_context())

    pins = {}
    expectations = []
    case_list = cases()
    for case in case_list:
        ctx = base_context(case['tick'])
        proposal = base_proposal(ctx)
        case['mutate'](proposal, ctx)
        if case['rule'] == 'duplicate':
            ctx['decisions_seen'] = [replay_record()]
        if case['name'] == 'replay_same_id_same_digest':
            proposal = replay_proposal()
        directory = 'valid' if case['valid'] else 'invalid'
        ppath = fixture_dir / directory / (case['name'] + '.json')
        cpath = fixture_dir / 'contexts' / (case['name'] + '.json')
        write(ppath, proposal)
        write(cpath, ctx)
        ctx_disk = load_json(cpath)
        pin = jcs_sha(ctx_disk)
        pins[case['name']] = pin
        sha_p = sha(ppath.read_bytes())
        expectations.append({'name': case['name'], 'dir': directory, 'rule': case['rule'],
                             'expected_decision': 'accepted' if case['valid'] else 'rejected',
                             'expected_reason_code': case['reason'], 'control': case['control'],
                             'proposal_sha256': sha_p, 'context_sha256': pin})

    for rc in reply_cases():
        directory = 'valid' if rc['valid'] else 'invalid'
        rpath = fixture_dir / 'replies' / directory / (rc['name'] + '.json')
        write(rpath, rc['reply'])
        expectations.append({'name': rc['name'], 'dir': 'replies/' + directory,
                             'expected_decision': 'valid' if rc['valid'] else 'invalid',
                             'control': ('mutation:' + rc['mutation']) if rc['mutation'] else None,
                             'reply_sha256': sha(rpath.read_bytes())})

    write(fixture_dir / 'EXPECTATIONS.json', {
        'synthetic_only': True,
        'note': '全部夹具都是 synthetic 冻结上下文；不是真实 AWZ 回合，不构成运行授权或能力。'
                'context_identity_pins 是调用方固定的上下文身份，核对时须逐字传入。',
        'context_identity_pins': pins,
        'cases': expectations,
    })
    return mut_paths, pins, expectations


def suite(regenerate=False, root_arg=None):
    pschema, rschema, eschema = schema_load(PROPOSAL_SCHEMA), schema_load(REPLY_SCHEMA), schema_load(ENTRY_SCHEMA)
    temp_dir_ctx = None

    if regenerate:
        if FIXTURE.exists():
            shutil.rmtree(FIXTURE)
        if SABOTAGE.exists():
            shutil.rmtree(SABOTAGE)
        FIXTURE.mkdir(parents=True, exist_ok=True)
        SABOTAGE.mkdir(parents=True, exist_ok=True)
        mut_paths, pins, expectations = generate_fixtures_to_dir(FIXTURE, SABOTAGE, pschema, rschema)
        target_fixture = FIXTURE
        target_sabotage = SABOTAGE
    else:
        temp_dir_ctx = tempfile.TemporaryDirectory()
        tmp_path = Path(temp_dir_ctx.name)
        tmp_fixture = tmp_path / 'fixture'
        tmp_sabotage = tmp_path / 'sabotage'
        mut_paths, pins, expectations = generate_fixtures_to_dir(tmp_fixture, tmp_sabotage, pschema, rschema)

        # 逐字节比对交付夹具目录（contracts/v9/examples/skill_proposal_v1/）与 sabotage-schemas
        for gen_p in tmp_fixture.rglob('*'):
            if gen_p.is_file():
                rel = gen_p.relative_to(tmp_fixture)
                com_p = FIXTURE / rel
                if not com_p.is_file():
                    print(f"FIXTURE MISMATCH: committed file missing {com_p}")
                    return 1
                if gen_p.read_bytes() != com_p.read_bytes():
                    print(f"FIXTURE MISMATCH: byte mismatch at {com_p}")
                    return 1
        for com_p in FIXTURE.rglob('*'):
            if com_p.is_file():
                rel = com_p.relative_to(FIXTURE)
                if not (tmp_fixture / rel).is_file():
                    print(f"FIXTURE MISMATCH: extra file in committed {com_p}")
                    return 1
        for gen_p in tmp_sabotage.glob('*.json'):
            com_p = SABOTAGE / gen_p.name
            if not com_p.is_file():
                print(f"SABOTAGE MISMATCH: committed file missing {com_p}")
                return 1
            if gen_p.read_bytes() != com_p.read_bytes():
                print(f"SABOTAGE MISMATCH: byte mismatch at {com_p}")
                return 1

        target_fixture = FIXTURE
        target_sabotage = tmp_sabotage

    rows, controls = [], []
    for case in cases():
        directory = 'valid' if case['valid'] else 'invalid'
        ppath = target_fixture / directory / (case['name'] + '.json')
        cpath = target_fixture / 'contexts' / (case['name'] + '.json')
        pin = pins[case['name']]
        argv = [sys.executable, '-I', str(Path(__file__)), 'gate', '--proposal', str(ppath),
                '--context', str(cpath), '--expected-context-sha256', pin,
                '--schema', str(PROPOSAL_SCHEMA), '--reply-schema', str(REPLY_SCHEMA)]
        if root_arg:
            argv += ['--root', str(root_arg)]
        result = run_process(argv)
        want_rc = 0 if case['valid'] else 1
        got_decision, got_reason = result['payload'].get('decision'), result['payload'].get('reason_code')
        ok = (not result['exception'] and result['returncode'] == want_rc and
              got_decision == ('accepted' if case['valid'] else 'rejected') and
              (case['reason'] is None or got_reason == case['reason']) and
              result['payload'].get('ok') is True)
        sha_p = sha(ppath.read_bytes())
        rows.append({'name': case['name'], 'valid': case['valid'], 'rule': case['rule'],
                     'expected_reason': case['reason'], 'got_reason': got_reason,
                     'returncode': result['returncode'], 'control': case['control'],
                     'proposal_sha256': sha_p, 'context_sha256': pin,
                     'reply': result['payload'].get('reply'),
                     'reply_schema_errors': result['payload'].get('reply_schema_errors'),
                     'leaked_world_side_tokens': result['payload'].get('leaked_world_side_tokens'),
                     'world_side_log': result['payload'].get('world_side_log'),
                     'replayed': result['payload'].get('replayed', False),
                     'ok': ok, 'exception': result['exception']})
        if case['control']:
            cargv = argv[:]
            if case['control'].startswith('disable:'):
                cargv += ['--disable', case['control'].split(':', 1)[1]]
            else:
                schema_name = case['control'].split(':', 1)[1]
                cargv[cargv.index('--schema') + 1] = str(SABOTAGE / (schema_name + '.json'))
                if schema_name in ('proposal_no_additional_properties', 'proposal_no_world_id_key'):
                    cargv += ['--disable', 'world_id_normalization']
            cr = run_process(cargv)
            isolated = (result['returncode'] == 1 and cr['returncode'] == 0 and not cr['exception'] and
                        cr['payload'].get('decision') == 'accepted')
            controls.append({'name': case['name'], 'rule': case['rule'], 'control': case['control'],
                             'base_returncode': result['returncode'],
                             'control_returncode': cr['returncode'],
                             'control_reason': cr['payload'].get('reason_code'),
                             'isolated_miss': isolated, 'exception': cr['exception']})

    # 裁决 6：置信度调到 1.0（和 0.0）都不能改变任何一次判定
    sweep = []
    for case in cases():
        if case['valid'] or case['rule'] == 'duplicate':
            continue
        ctx = base_context(case['tick'])
        proposal = base_proposal(ctx)
        case['mutate'](proposal, ctx)
        cpath = target_fixture / 'contexts' / (case['name'] + '.json')
        for conf in (1.0, 0.0):
            variant = copy.deepcopy(proposal)
            variant['confidence'] = conf
            vpath = (SABOTAGE if regenerate else target_sabotage) / ('sweep_%s_%s.json' % (case['name'], conf))
            write(vpath, variant)
            sargv = [sys.executable, '-I', str(Path(__file__)), 'gate', '--proposal', str(vpath),
                     '--context', str(cpath), '--expected-context-sha256', pins[case['name']],
                     '--schema', str(PROPOSAL_SCHEMA), '--reply-schema', str(REPLY_SCHEMA)]
            if root_arg:
                sargv += ['--root', str(root_arg)]
            r = run_process(sargv)
            sweep.append({'name': case['name'], 'confidence': conf,
                          'reason_code': r['payload'].get('reason_code'),
                          'evidence_version_unchanged':
                              variant['evidence_version'] == proposal['evidence_version'],
                          'ok': (not r['exception'] and
                                 r['payload'].get('reason_code') == case['reason'] and
                                 variant['evidence_version'] == proposal['evidence_version'])})

    rrows, rcontrols = [], []
    for rc in reply_cases():
        directory = 'valid' if rc['valid'] else 'invalid'
        rpath = target_fixture / 'replies' / directory / (rc['name'] + '.json')
        argv = [sys.executable, '-I', str(Path(__file__)), 'reply', '--reply', str(rpath),
                '--reply-schema', str(REPLY_SCHEMA)]
        if root_arg:
            argv += ['--root', str(root_arg)]
        r = run_process(argv)
        rrows.append({'name': rc['name'], 'valid': rc['valid'], 'mutation': rc['mutation'],
                      'reply_sha256': sha(rpath.read_bytes()), 'returncode': r['returncode'],
                      'errors': r['payload'].get('errors'),
                      'ok': not r['exception'] and r['returncode'] == (0 if rc['valid'] else 1)})
        if rc['mutation']:
            cargv = argv[:]
            cargv[cargv.index('--reply-schema') + 1] = str(SABOTAGE / (rc['mutation'] + '.json'))
            cr = run_process(cargv)
            isolated = r['returncode'] == 1 and cr['returncode'] == 0 and not cr['exception']
            rcontrols.append({'name': rc['name'], 'mutation': rc['mutation'],
                              'base_returncode': r['returncode'],
                              'control_returncode': cr['returncode'],
                              'isolated_miss': isolated, 'exception': cr['exception']})

    # 裁决 9：被接受的正例，提交摘要必须原样保留，不被门禁改写
    no_rewrite = []
    for row in rows:
        if not row['valid'] or row['exception']:
            continue
        p = load_json(target_fixture / 'valid' / (row['name'] + '.json'))
        reply = row['reply'] or {}
        no_rewrite.append({'name': row['name'],
                           'evidence_version_echoed':
                               reply.get('evidence_version') == p.get('evidence_version'),
                           'evidence_version_is_basis_digest':
                               p.get('evidence_version') == jcs_sha(p.get('basis', {})),
                           'ok': reply.get('evidence_version') == p.get('evidence_version') and
                                 p.get('evidence_version') == jcs_sha(p.get('basis', {}))})

    # 门禁可见回执泄露扫描：每一条回执都不得含世界侧标识
    toks = world_side_tokens(base_context())
    leak = []
    for row in rows:
        reply = row['reply'] or {}
        blob = jcs(reply).decode('utf-8') if reply else ''
        leaked = [t for t in toks if t in blob]
        leak.append({'name': row['name'], 'leaked': leaked,
                     'ok': not leaked and (not reply or reply.get('reason_code') in VISIBLE_REASONS)})

    meta = []
    for label, path in (('skill_proposal.v1', PROPOSAL_SCHEMA), ('skill_gate_reply.v1', REPLY_SCHEMA),
                        ('ability_registry_entry.v0', ENTRY_SCHEMA)):
        row = {'schema': label, 'path': str(path.relative_to(ROOT)), 'sha256': sha(path.read_bytes())}
        try:
            schema_load(path)
            row['meta_ok'] = True
        except Exception as e:  # pragma: no cover
            row.update(meta_ok=False, error=str(e))
        meta.append(row)

    ev = Draft202012Validator(eschema)
    entry_checks = [{'ability_id': e['ability_id'], 'effect_class': e['effect_class'],
                     'entry_schema_ok': ev.is_valid(e)} for e in registry_entries()]

    jcs_rows = jcs_self_tests()
    diffs = []
    for p in sorted(FIXTURE.rglob('*.json')):
        obj = load_json(p)
        legacy = json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        if legacy != jcs(obj).decode('utf-8'):
            diffs.append({'path': str(p.relative_to(ROOT)), 'legacy': legacy[:100]})

    if temp_dir_ctx:
        temp_dir_ctx.cleanup()

    failures = ([r['name'] for r in rows if not r['ok']] + [r['name'] for r in rrows if not r['ok']] +
                [x['name'] for x in sweep if not x['ok']] +
                [x['name'] for x in no_rewrite if not x['ok']] +
                [x['name'] for x in leak if not x['ok']] +
                [x['schema'] for x in meta if not x['meta_ok']] +
                [x['name'] for x in jcs_rows if not x['ok']] +
                [x['ability_id'] for x in entry_checks if not x['entry_schema_ok']])
    bad_controls = ([c['name'] for c in controls if not c['isolated_miss']] +
                    [c['name'] for c in rcontrols if not c['isolated_miss']])
    all_ok = not failures and not bad_controls
    result = {
        'synthetic_only': True,
        'all_ok': all_ok,
        'counts': {
            'cases_total': len(rows), 'positive_cases': sum(r['valid'] for r in rows),
            'negative_cases': sum(not r['valid'] for r in rows),
            'distinct_rules_with_counterexample': len({r['rule'] for r in rows if r['rule']}),
            'controls': len(controls), 'controls_isolated_miss': sum(c['isolated_miss'] for c in controls),
            'reply_cases': len(rrows), 'reply_negative_cases': sum(not r['valid'] for r in rrows),
            'reply_controls': len(rcontrols),
            'reply_controls_isolated_miss': sum(c['isolated_miss'] for c in rcontrols),
            'confidence_sweep_rows': len(sweep), 'no_rewrite_rows': len(no_rewrite),
            'leak_scan_rows': len(leak), 'jcs_self_tests': len(jcs_rows),
            'jcs_self_tests_ok': sum(x['ok'] for x in jcs_rows),
            'schema_meta_checks': len(meta), 'registry_entries': len(entry_checks),
            'existing_canon_vs_jcs_differences': len(diffs),
        },
        'cases': rows, 'controls': controls, 'confidence_sweep': sweep,
        'reply_cases': rrows, 'reply_controls': rcontrols,
        'no_rewrite': no_rewrite, 'leak_scan': leak, 'schema_meta': meta,
        'registry_entries_in_frozen_context': entry_checks, 'jcs_self_tests': jcs_rows,
        'canon_vs_jcs_report_only': {
            'differences': len(diffs), 'sample': diffs[:5],
            'note': '只报告；不改 Event/v1 r2、teacher_cache v2 或任何既有契约（RFC 8785 迁移由一级另行决定）。'},
        'failures': failures, 'control_failures': bad_controls,
    }
    write(OUT / 'check_result.json', result)
    print(json.dumps({k: result[k] for k in ('all_ok', 'counts', 'failures', 'control_failures')},
                     ensure_ascii=False))
    return int(not all_ok)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--suite', action='store_true')
    p.add_argument('--regenerate', action='store_true', help='显式原地重写交付夹具目录（复核流程不得使用）')
    p.add_argument('--root', default=None, help='仓库根目录（避免写死路径）')
    p.add_argument('mode', nargs='?', choices=['gate', 'reply'])
    p.add_argument('--proposal')
    p.add_argument('--reply')
    p.add_argument('--context')
    p.add_argument('--expected-context-sha256')
    p.add_argument('--schema')
    p.add_argument('--reply-schema')
    p.add_argument('--disable', action='append', default=[])
    a = p.parse_args()
    if a.root:
        configure_paths(a.root)
    schema_path = a.schema or str(PROPOSAL_SCHEMA)
    reply_schema_path = a.reply_schema or str(REPLY_SCHEMA)
    if a.suite:
        return suite(regenerate=a.regenerate, root_arg=a.root)
    if a.mode == 'gate':
        if not a.proposal:
            p.error('gate needs --proposal')
        a.schema = schema_path
        a.reply_schema = reply_schema_path
        return worker_gate(a)
    if a.mode == 'reply':
        if not a.reply:
            p.error('reply needs --reply')
        a.reply_schema = reply_schema_path
        return worker_reply(a)
    p.error('need --suite or a mode')



if __name__ == '__main__':
    sys.exit(main())
