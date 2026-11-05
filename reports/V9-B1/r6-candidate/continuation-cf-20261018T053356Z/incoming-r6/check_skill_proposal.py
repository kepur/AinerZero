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

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROPOSAL_SCHEMA = ROOT / 'contracts/v9/skill_proposal.v1.schema.json'
REPLY_SCHEMA = ROOT / 'contracts/v9/skill_gate_reply.v1.schema.json'
ENTRY_SCHEMA = ROOT / 'contracts/v9/ability_registry_entry.v0.schema.json'
FIXTURE = OUT / 'fixtures'
SABOTAGE = OUT / 'sabotage-schemas'


def configure_paths(root_dir=None):
    global ROOT, PROPOSAL_SCHEMA, REPLY_SCHEMA, ENTRY_SCHEMA, FIXTURE, SABOTAGE
    if root_dir:
        ROOT = Path(root_dir).resolve()
        PROPOSAL_SCHEMA = ROOT / 'contracts/v9/skill_proposal.v1.schema.json'
        REPLY_SCHEMA = ROOT / 'contracts/v9/skill_gate_reply.v1.schema.json'
        ENTRY_SCHEMA = ROOT / 'contracts/v9/ability_registry_entry.v0.schema.json'
        FIXTURE = OUT / 'fixtures'
        SABOTAGE = OUT / 'sabotage-schemas'


# --------------------------------------------------------------------------- 标识族与键名规范化（r4 F1/F3）
#
# 11 族标识词（裁决 2）：world/entity/scene/event/instance/landmark/object/actor/agent/truth/hidden。
# 规范化判定与 B5 的探针档位口径一致（mandated / plural_stem / padded / hidden_contact），
# 但按本规范独立实现，不读探针文件、不按例子 ID 硬编码：键名转小写、去掉所有非字母数字后，
#   1) 命中 <族>+<id 后缀>（后缀含 id/ids/idx/identifier/identifiers，族含单数、规则复数与不规则复数），或
#   2) 命中 <id 后缀>+<族>（id_entity 这类前缀别名），或
#   3) 命中 hidden_contact / contact_id 这类隐藏接触标识，或
#   4) 去掉分隔符后恰好是 id/ids/idx/identifier(s) 裸键，
# 即判为世界侧标识键名。族的单数形式允许出现在更长词里（如 gtObjectId），这是保守方向：
# 已知过度拒绝 identity（entity+id 结尾）与 objectIdMap 这类名字；见 docs/v9/SKILL_PROPOSAL.md 闭合矩阵。
FAMILY_STEMS = ('world', 'entity', 'scene', 'event', 'instance', 'landmark', 'object', 'actor',
                'agent', 'truth', 'hidden')
FAMILY_PLURALS = {'world': 'worlds', 'entity': 'entities', 'scene': 'scenes', 'event': 'events',
                  'instance': 'instances', 'landmark': 'landmarks', 'object': 'objects',
                  'actor': 'actors', 'agent': 'agents', 'truth': 'truths', 'hidden': 'hiddens'}
FAMILY_FORMS = tuple(sorted({f for stem in FAMILY_STEMS for f in
                             (stem, FAMILY_PLURALS[stem], stem + 's')}, key=len, reverse=True))
ID_SUFFIX = r'(?:ids|id|idx|identifiers|identifier)'
FAMILY_GROUP = r'(?:' + '|'.join(FAMILY_FORMS) + r')'
FAMILY_ID_PATTERN = re.compile(FAMILY_GROUP + ID_SUFFIX + r'|' + ID_SUFFIX + FAMILY_GROUP +
                               r'|hiddencontacts?|contacts?' + ID_SUFFIX)
BARE_ID_KEYS = {'id', 'ids', 'idx', 'ident', 'identifier', 'identifiers'}
NON_ALNUM = re.compile(r'[^a-z0-9]')


def normalize_key_name(k) -> str:
    return NON_ALNUM.sub('', str(k).lower())


def is_forbidden_world_id_key(k: str) -> bool:
    norm = normalize_key_name(k)
    if not norm:
        return False
    if norm in BARE_ID_KEYS:
        return True
    return bool(FAMILY_ID_PATTERN.search(norm))


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


# r4 F1/F3：登记条目的 param_schema 只能是被支持的那一小块静态封闭对象 schema。
UNSUPPORTED_PARAM_SCHEMA_KEYWORDS = (
    'patternProperties', '$ref', '$dynamicRef', '$recursiveRef', '$dynamicAnchor', '$recursiveAnchor',
    'propertyNames', 'unevaluatedProperties', 'if', 'then', 'else', 'dependentSchemas', 'dependentRequired',
    'oneOf', 'anyOf', 'allOf', 'not', 'contains', 'minContains', 'maxContains', 'prefixItems', 'items',
    'additionalItems', 'uniqueItems', 'minProperties', 'maxProperties', 'format', 'contentSchema',
)
SUPPORTED_PARAM_SCHEMA_KEYWORDS = ('type', 'properties', 'additionalProperties', 'required', 'description',
                                  'title', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
                                  'minLength', 'maxLength', 'enum', 'const', 'minItems', 'maxItems',
                                  'items', 'prefixItems', '$defs', 'default', 'examples')


def _schema_keyword_problems(s, path, position='object'):
    """递归检查 param_schema 子树里未支持/未知的关键字（r4 F1/F3）。

    位置语义：
      object —— 对象位置（条目根、嵌套属性、数组元素）：patternProperties、additionalProperties 为
                schema、$ref/$dynamicRef、if/then/else、dependentSchemas、oneOf/anyOf/allOf/not、
                $defs 的动态锚点、propertyNames、unevaluatedProperties 一律未支持；
      array  —— 数组位置：允许 items/prefixItems 这类数组关键字。
    数组元素里允许 `additionalProperties: {…}`（旧夹具用它表达“字符串值映射”）；对象位置上
    它是开放分支，未支持。
    """
    out = []
    if not isinstance(s, dict):
        return out
    tail = path.split('.', 1)[1] if '.' in path else ''

    def here(msg):
        return ((tail + ':') if tail else '') + msg

    for kw in UNSUPPORTED_PARAM_SCHEMA_KEYWORDS:
        if kw not in s:
            continue
        if kw == 'items':
            continue          # items 由数组位置递归处理（见函数说明）
        if position == 'array' and kw in ('prefixItems', 'minItems', 'maxItems'):
            continue
        out.append(here('unsupported_keyword:' + kw))
    if position == 'object' and isinstance(s.get('additionalProperties'), dict):
        out.append(here('open_additionalProperties'))
    for kw in sorted(s):
        if kw not in SUPPORTED_PARAM_SCHEMA_KEYWORDS:
            out.append(here('unknown_keyword:' + kw))
        elif kw == 'items':       # 允许，但要递归进数组元素继续查
            pass
    for name, sub in (s.get('properties') or {}).items():
        if is_forbidden_world_id_key(name):
            out.append(here('forbidden_property:' + str(name)))
        out.extend(_schema_keyword_problems(sub, path + ('.' if path else '') + str(name), 'object'))
    for kw in ('items', 'contains', 'not', 'if', 'then', 'else'):
        sub = s.get(kw)
        if isinstance(sub, dict):
            out.extend(_schema_keyword_problems(sub, path + ('.' if path else '') + kw, 'array'))
    if isinstance(s.get('additionalProperties'), dict):
        out.extend(_schema_keyword_problems(s['additionalProperties'],
                                            path + ('.' if path else '') + 'additionalProperties',
                                            'array'))
    for kw in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
        if isinstance(s.get(kw), list):
            for i, sub in enumerate(s[kw]):
                out.extend(_schema_keyword_problems(sub, path + ('.' if path else '') + kw + str(i), 'object'))
    for kw in ('$defs', 'definitions', 'dependentSchemas'):
        if isinstance(s.get(kw), dict):
            for name, sub in s[kw].items():
                out.extend(_schema_keyword_problems(
                    sub, path + ('.' if path else '') + kw + '.' + str(name), 'object'))
    return out


def param_schema_problems(s, path='param_schema'):
    """登记条目 param_schema 的结构检查（r4 F1/F3）。

    只对条目根位置要求「封闭对象 schema」；嵌套属性/数组元素按它们自己的 JSON Schema 形状检查：
    仍然禁止 patternProperties / additionalProperties 为 schema / $ref / if-then-else / oneOf 等
    动态分支与未支持关键字，但不要求嵌套对象必须封闭（嵌套开放对象在旧夹具里是合法的观察用法）。
    """
    p = []
    if not isinstance(s, dict):
        return [(path + ':' if path else '') + 'not_object']
    if s.get('type') != 'object':
        p.append(path + ':type_not_object')
    if s.get('additionalProperties') is not False:
        p.append(path + ':not_closed')
    props = s.get('properties', {})
    if not isinstance(props, dict):
        p.append(path + ':properties_not_object')
        props = {}
    if not props:
        p.append(path + ':no_properties')
    p.extend(_schema_keyword_problems(s, ''))
    return p


def check_schema_props_forbidden(s, path='param_schema'):
    """递归收集 param_schema 里既未支持也不合规的属性名（含 patternProperties 这类动态分支）。"""
    out = []
    if not isinstance(s, dict):
        return out
    if 'patternProperties' in s and isinstance(s['patternProperties'], dict):
        for pattern in s['patternProperties']:
            out.append(path + ':patternProperties:' + str(pattern))
    for name, sub in (s.get('properties') or {}).items():
        if is_forbidden_world_id_key(name):
            _tail = path.split('.', 1)[1] if '.' in path else ''
            out.append(((_tail + ':') if _tail else '') + 'forbidden_property:' + str(name))
        out.extend(check_schema_props_forbidden(sub, path + '.' + str(name)))
    for kw in ('items', 'contains', 'not', 'if', 'then', 'else'):
        if kw in s:
            subs = s[kw] if isinstance(s[kw], list) else [s[kw]]
            for i, sub in enumerate(subs):
                out.extend(check_schema_props_forbidden(sub, path + '.' + kw + str(i)))
    for kw in ('oneOf', 'anyOf', 'allOf', 'prefixItems'):
        if isinstance(s.get(kw), list):
            for i, sub in enumerate(s[kw]):
                out.extend(check_schema_props_forbidden(sub, path + '.' + kw + str(i)))
    for kw in ('$defs', 'definitions', 'dependentSchemas'):
        if isinstance(s.get(kw), dict):
            for name, sub in s[kw].items():
                out.extend(check_schema_props_forbidden(sub, path + '.' + kw + '.' + str(name)))
    return out


CHANNELS = ['symbol8', 'egocentric_grid', 'rgb', 'depth', 'relative_objects', 'ego_motion',
            'audio_events', 'semantic_mask']
# 裁决 8 的白名单：只允许这些原因码出现在门禁可见回执里。
VISIBLE_REASONS = ['accepted', 'schema_invalid', 'ability_unknown', 'params_invalid', 'budget_exceeded',
                   'proposal_expired', 'time_domain_mismatch', 'evidence_mismatch', 'handle_unknown',
                   'effect_class_not_registered', 'duplicate_proposal', 'rejected_other']
MAX_JCS_INT = 2 ** 53 - 1

# --------------------------------------------------------------------------- 可观察量有限允许表（r4 F6）
#
# 逐项取自 /Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json
# 的 $defs/ch_*。properties 与 $defs/payload.properties（只读引用，不改 AWZ 契约）。
# 学生自填的新名字不是授权：expected_outcomes[].quantity 必须落在本表内，且落在被引用能力登记条目的
# observable_names 里；世界 ID、隐藏接触、接触标识及其规范化别名一律不在表内（另有规范化判定兜底）。
OBSERVABLE_QUANTITIES = [
    'channel.symbol8', 'channel.egocentric_grid', 'channel.rgb', 'channel.depth',
    'channel.relative_objects', 'channel.ego_motion', 'channel.audio_events', 'channel.semantic_mask',
    'time.sim_hz', 'time.t_ticks', 'time.dt_ticks', 'time.dt_s', 'episode_start',
    'pose_sensor_if_allowed', 'pose_sensor.frame', 'pose_sensor.position_m', 'pose_sensor.yaw_deg',
    'visibility.fov_deg', 'visibility.range_m',
    'detection.handle', 'detection.appearance_class', 'detection.rel_position_m',
    'detection.rel_yaw_deg', 'detection.confidence',
    'audio_events.type', 'audio_events.bearing_deg', 'audio_events.loudness',
    'ego_motion.delta.dx_m', 'ego_motion.delta.dy_m', 'ego_motion.delta.dz_m',
    'ego_motion.delta.dyaw_deg',
    'semantic_mask.class_vocab_sha256', 'symbol8.slots', 'symbol8.spec_sha256',
    'rgb.width', 'rgb.height', 'rgb.intrinsics.fx', 'rgb.intrinsics.fy', 'rgb.intrinsics.cx',
    'rgb.intrinsics.cy', 'depth.width', 'depth.height', 'depth.unit',
    'egocentric_grid.shape', 'egocentric_grid.cell_m',
    'last_action_result.status', 'last_action_result.reason_code',
    'task_instruction.goal', 'task_instruction.text', 'sensor_noise.model',
]
OBSERVABLE_QUANTITY_SET = frozenset(OBSERVABLE_QUANTITIES)
OBSERVABLE_SOURCE = 'AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json'

# 破坏对照可关闭的规则名（r4 F7）。未列名的 --disable 一律失败，不做静默 no-op。
# context_identity 不在名单内：调用方固定的上下文身份不可被破坏对照关闭。
KNOWN_DISABLE_RULES = frozenset([
    'schema', 'jcs_fail_closed', 'world_id_normalization', 'ability', 'precondition', 'effect_class',
    'target_kind', 'params', 'evidence', 'time_domain', 'ttl', 'budget', 'handle', 'actor',
    'outcome_window', 'duplicate', 'confidence_independence', 'quantity_allowlist',
    'quantity_registry_binding',
])


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


def safe_jcs_sha(o):
    """JCS 摘要；规范化失败（超范围整数、孤立代理项、编解码错误）时返回不可能匹配的哨兵值。
    调用方按 r4 F4 把这个哨兵值当作 fail-closed 的拒绝，而不是让它变成 traceback。"""
    try:
        return jcs_sha(o)
    except Exception:
        return 'jcs_unavailable_' + sha(repr(type(o)).encode('utf-8'))[:32]


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
    """写 JSON 夹具。含孤立代理项的字符串用 ASCII 转义写（\\ud800），保证是合法 UTF-8 文件；
    读回来仍是同一个孤立代理项，用来核验 r4 F4 的 fail-closed 路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, indent=2)
    has_surrogate = False
    try:
        raw.encode('utf-8')
    except UnicodeEncodeError:
        has_surrogate = True
    if has_surrogate:
        raw = json.dumps(obj, ensure_ascii=True, indent=2)
    path.write_text(raw + '\n', encoding='utf-8')


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


# ---- 调用方固定（pin）的可信可观察量表（r4 F6 / r5 B6-F4）：与提案分离，随上下文一起被摘要固定。
# r5：source_sha256 改为 AWZ 固定 Observation 文件内容 SHA（01be45e0...），不再是路径字符串哈希。
# 旧路径字符串哈希 a2971c9a... 作为 source_path_sha256 保留为迁移证据，不静默重 pin。
OBSERVABLE_SOURCE_CONTENT_SHA256 = '01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb'
OBSERVABLE_SOURCE_PATH_SHA256 = sha(OBSERVABLE_SOURCE.encode('utf-8'))   # 旧值 a2971c9a...（迁移前）


def trusted_observables():
    return {
        'registry_id': 'awz-observable-allowlist-synthetic-0001',
        'source': OBSERVABLE_SOURCE,
        'source_sha256': OBSERVABLE_SOURCE_CONTENT_SHA256,
        'source_path_sha256': OBSERVABLE_SOURCE_PATH_SHA256,
        'source_sha256_migration': 'v4 path-string hash -> v5 AWZ observation file content hash; '
                                    'old value preserved in source_path_sha256; drift rejects',
        'derivation': 'ObservationPacket/v1.1 的 $defs/ch_* 通道字段名与 payload 字段名；逐项列出，不含世界 ID、'
                      '隐藏接触与接触标识',
        'quantities': sorted(OBSERVABLE_QUANTITY_SET),
    }


def registry_entries():
    def entry(aid, eff, kinds, ma, md, mt, ps, pre, obs):
        return {'schema_version': 'ability_registry_entry.v0', 'ability_id': aid, 'ability_version': '1.0',
                'effect_class': eff, 'target_kinds': kinds, 'max_actions': ma,
                'max_duration_ticks': md, 'max_ttl_ticks': mt, 'param_schema': ps, 'preconditions': pre,
                'observable_names': obs}

    return [
        entry('abil-approach-object', 'run', ['handle'], 4, 120, 240,
              {'type': 'object', 'additionalProperties': False, 'required': ['speed_mps'],
               'properties': {'speed_mps': {'type': 'number', 'minimum': 0, 'maximum': 3}}},
              [{'kind': 'exists', 'observable': 'channel.relative_objects'}],
              ['detection.rel_position_m', 'detection.rel_yaw_deg', 'detection.confidence',
               'channel.relative_objects']),
        entry('abil-move-ego-relative', 'run', ['ego_relative_pose'], 8, 240, 480,
              {'type': 'object', 'additionalProperties': False, 'required': ['stride_m'],
               'properties': {'stride_m': {'type': 'number', 'minimum': 0, 'maximum': 2}}}, [],
              ['ego_motion.delta.dx_m', 'ego_motion.delta.dy_m', 'ego_motion.delta.dz_m',
               'ego_motion.delta.dyaw_deg', 'detection.rel_position_m']),
        entry('abil-emit-audio-ping', 'run', [], 1, 12, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['loudness'],
               'properties': {'loudness': {'type': 'number', 'minimum': 0, 'maximum': 1}}},
              [{'kind': 'compare', 'observable': 'last_action_result.status', 'op': 'ne',
                'value': 'interrupted'}],
              ['audio_events.type', 'audio_events.bearing_deg', 'audio_events.loudness',
               'detection.rel_position_m']),
        # 编辑类条目：v1 已登记的编辑类能力集合为空，被引用一律 effect_class_not_registered（裁决 1）。
        entry('abil-synthetic-edit-scene', 'edit', ['handle'], 1, 1, 60,
              {'type': 'object', 'additionalProperties': False, 'required': ['patch_op'],
               'properties': {'patch_op': {'type': 'string', 'enum': ['remove', 'replace']}}}, [],
              ['detection.rel_position_m']),
        # 前置条件在本上下文不成立（payload 没有 pose_sensor）：核验前置条件真的被核验。
        entry('abil-require-pose-sensor', 'run', ['handle'], 2, 60, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['hold_ticks'],
               'properties': {'hold_ticks': {'type': 'integer', 'minimum': 1, 'maximum': 60}}},
              [{'kind': 'exists', 'observable': 'pose_sensor_if_allowed'}],
              ['pose_sensor.position_m', 'detection.rel_position_m']),
        # 参数里带开放嵌套对象：用来核验世界 ID 键名在任意层级都被禁（裁决 2）。
        entry('abil-tag-objects', 'run', ['handle'], 2, 60, 120,
              {'type': 'object', 'additionalProperties': False, 'required': ['tags'],
               'properties': {'tags': {'type': 'array', 'minItems': 1, 'maxItems': 4,
                                       'items': {'type': 'object', 'additionalProperties': {'type': 'string'}}}}},
              [], ['channel.semantic_mask', 'detection.rel_position_m', 'detection.rel_yaw_deg',
                   'detection.confidence']),
        # r4 F6：允许表里有、但本条目没声明——用来核验“量与能力的绑定”真的生效。
        entry('abil-never-declares-detection', 'run', ['handle'], 1, 12, 60,
              {'type': 'object', 'additionalProperties': False, 'required': ['speed_mps'],
               'properties': {'speed_mps': {'type': 'number', 'minimum': 0, 'maximum': 1}}},
              [], []),
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
            'observable_registry': trusted_observables(),
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
    obr = reg.get('observable_registry')
    if not isinstance(obr, dict):
        p.append('context_observable_registry')
    else:
        qs = obr.get('quantities')
        if not isinstance(qs, list) or not qs or not all(isinstance(x, str) for x in qs):
            p.append('context_observable_quantities')
        else:
            if sorted(set(qs)) != sorted(qs):
                p.append('context_observable_duplicates')
            unknown = sorted(set(qs) - OBSERVABLE_QUANTITY_SET)
            if unknown:
                p.append('context_observable_not_derived:' + ','.join(unknown[:3]))
            forbidden = sorted(q for q in qs if is_forbidden_world_id_key(q))
            if forbidden:
                p.append('context_observable_forbidden:' + ','.join(forbidden[:3]))
        if obr.get('source') != OBSERVABLE_SOURCE:
            p.append('context_observable_source')
        if obr.get('source_sha256') != OBSERVABLE_SOURCE_CONTENT_SHA256:
            p.append('context_observable_source_sha256')
        # 迁移证据：旧路径哈希可出现，但不能替代内容哈希；漂移时拒绝。
        if 'source_path_sha256' in obr and obr.get('source_path_sha256') != OBSERVABLE_SOURCE_PATH_SHA256:
            p.append('context_observable_source_path_sha256_drift')
        # 运行时漂移校验：AWZ 观察文件必须存在且可读；缺失/不可读/内容漂移一律 fail-closed。
        import os as _os
        awz_env = _os.environ.get('AWZ_OBSERVATION_PATH')
        awz_obs_path = Path(awz_env) if awz_env else Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')
        if not awz_obs_path.is_file():
            p.append('context_observable_source_unavailable')
        else:
            try:
                actual = sha(awz_obs_path.read_bytes())
            except Exception:
                actual = None
                p.append('context_observable_source_unreadable')
            if actual is not None and actual != OBSERVABLE_SOURCE_CONTENT_SHA256:
                p.append('context_observable_source_content_drift')
        for k in ('registry_id', 'derivation'):
            if not isinstance(obr.get(k), str) or not obr[k]:
                p.append('context_observable_missing:' + k)
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
        # 裁决 2 / 裁决 5（r3）/ r4 F1、F3：封闭、无未支持动态分支、属性名通过规范化判定。
        for problem in param_schema_problems(ps):
            p.append('entry:' + str(e.get('ability_id')) + ':' + problem)
        for bp in check_schema_props_forbidden(ps):
            p.append('entry:' + str(e.get('ability_id')) + ':' + bp)
        obs = e.get('observable_names')
        if not isinstance(obs, list):
            p.append('entry_observable_names:' + str(e.get('ability_id')))
        else:
            for name in obs:
                if name not in OBSERVABLE_QUANTITY_SET:
                    p.append('entry_observable_not_allowed:' + str(e.get('ability_id')) + ':' + str(name))
                if is_forbidden_world_id_key(name):
                    p.append('entry_observable_forbidden:' + str(e.get('ability_id')) + ':' + str(name))
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


def trusted_quantity_set(ctx):
    """返回 (允许量集合, 问题列表)。表由调用方固定在上下文里，与待验提案分离（r4 F6）。"""
    obr = ctx['ability_registry'].get('observable_registry') or {}
    qs = obr.get('quantities')
    if not isinstance(qs, list):
        return set(), ['trusted_observables_missing']
    return set(qs), []


def entry_observables(entry):
    obs = entry.get('observable_names')
    return set(obs) if isinstance(obs, list) else set()


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
    disabled = set(disabled or ())
    unknown = sorted(disabled - KNOWN_DISABLE_RULES)
    if unknown:   # r4 F7：未知规则名必须显式失败，不能静默变成 no-op 让破坏对照假变红。
        return {'decision': None, 'reason_code': None, 'errors': ['unknown_disable_rule:' + ','.join(unknown)],
                'world_side_log': ['unknown_disable_rule']}

    def reject(code, world_reason):
        log.append(world_reason)
        return {'decision': 'rejected', 'reason_code': code, 'world_side_log': log}

    if not isinstance(proposal, dict):
        return {'decision': None, 'reason_code': None, 'errors': ['proposal_shape'],
                'world_side_log': ['proposal_shape']}
    if ctx is None:
        return {'decision': None, 'reason_code': None, 'errors': ['trusted_context_missing'],
                'world_side_log': ['trusted_context_missing']}
    if 'context_identity' not in disabled and (not pin or safe_jcs_sha(ctx) != pin):
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

    # r4 F4：JCS 超范围整数、孤立代理项、编解码/重复键异常一律 fail-closed，返回白名单原因码，
    # 不许用 traceback 代替拒绝；异常类型只进世界侧日志。
    if 'jcs_fail_closed' not in disabled:
        try:
            jcs(proposal)
        except Exception as exc:
            return reject('schema_invalid', 'jcs_canonicalization_failed:' + type(exc).__name__)

    # 裁决 2（r3 规范化判定）：键名转小写、去掉非字母数字后，命中族标识 pattern 即拒。
    # schema 正则作为第 1 层；本检查作为第 2 层，覆盖任意层级键名与前后缀别名（r4 F1/F3）。
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
                 'param_schema': {'type': 'object'}, 'preconditions': [],
                 'observable_names': sorted(OBSERVABLE_QUANTITY_SET)}

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

    # r4 F6：预期结果的可观察量必须落在调用方固定的有限允许表里（与提案分离），
    # 且必须被被引用的能力登记条目声明。学生自填的名字不是授权。
    if 'quantity_allowlist' not in disabled:
        allowed, qprob = trusted_quantity_set(ctx)
        if qprob:
            return reject('schema_invalid', ';'.join(qprob))
        for o in proposal.get('expected_outcomes', []):
            q = o.get('quantity') if isinstance(o, dict) else None
            if not isinstance(q, str) or q not in allowed:
                return reject('schema_invalid', 'quantity_not_allowed:' + str(q))
            if is_forbidden_world_id_key(q):
                return reject('schema_invalid', 'quantity_forbidden_alias:' + str(q))
    if 'quantity_registry_binding' not in disabled and entry is not None:
        declared = entry_observables(entry)
        for o in proposal.get('expected_outcomes', []):
            q = o.get('quantity') if isinstance(o, dict) else None
            if isinstance(q, str) and q not in declared:
                return reject('schema_invalid', 'quantity_not_declared_by_ability:' + str(q))

    # 裁决 5：参数按登记条目的 param_schema 校验。
    if 'params' not in disabled:
        if not Draft202012Validator(entry['param_schema']).is_valid(proposal.get('params')):
            return reject('params_invalid', 'params_invalid:' + str(entry.get('ability_id')))

    # 裁决 3：门禁重算 basis 的 JCS 摘要；basis 必须绑定到可信的当前包。
    basis = proposal.get('basis', {})
    if 'evidence' not in disabled:
        digest = safe_jcs_sha(basis) if isinstance(basis, dict) else None
        if digest is None or digest.startswith('jcs_unavailable_'):
            return reject('schema_invalid', 'jcs_canonicalization_failed:basis')
        if digest != proposal.get('evidence_version'):
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
        digest = safe_jcs_sha(proposal)
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
    try:
        blob = jcs(reply).decode('utf-8')
    except Exception:
        blob = ''          # 回执本身不可规范化（孤立代理项）：泄露扫描退化为不可判定，另行标记
    leaked = [t for t in toks if t in blob]
    # 安全阀：提案本身取不出合法回显字段时（proposal_id/evidence_version 不可用），
    # 回执只能如实留空；这只在 schema_invalid 下成立，且不放过任何白名单违规。
    echo_degraded = bool(errs) and res['reason_code'] == 'schema_invalid' and \
        not isinstance(proposal.get('evidence_version'), str)
    res.update(reply=reply, reply_schema_errors=errs, leaked_world_side_tokens=leaked,
               reason_whitelisted=reply['reason_code'] in whitelist_of(rschema),
               proposal_digest=safe_jcs_sha(proposal), context_sha256=safe_jcs_sha(ctx))
    res['ok'] = ((not errs) or echo_degraded) and (not leaked) and res['reason_whitelisted']
    return res


# --------------------------------------------------------------------------- worker

def _print_json(obj) -> None:
    """打印 JSON 结果行。stdout 编码失败时退化为 ASCII 转义，绝不因打印异常而丢判定。"""
    line = json.dumps(obj, ensure_ascii=False)
    try:
        print(line)
    except UnicodeEncodeError:  # pragma: no cover - 只在孤立代理项进入回显字段时触发
        print(json.dumps(obj, ensure_ascii=True))


def worker_gate(a):
    # r4 F4：解析失败、编码异常、JCS 异常都 fail-closed 成白名单原因码，不向外抛 traceback。
    try:
        proposal = load_json(a.proposal, strict=True)
    except Exception as exc:
        out = {'ok': False, 'decision': 'rejected', 'reason_code': 'schema_invalid',
               'errors': ['proposal_unreadable:' + type(exc).__name__],
               'reply_schema_errors': [], 'leaked_world_side_tokens': [], 'reason_whitelisted': True,
               'world_side_log': ['proposal_unreadable:' + type(exc).__name__], 'reply': None}
        _print_json(out)
        return 1
    try:
        ctx = load_json(a.context, strict=True) if a.context else None
    except Exception as exc:
        out = {'ok': False, 'decision': 'rejected', 'reason_code': 'schema_invalid',
               'errors': ['context_unreadable:' + type(exc).__name__],
               'reply_schema_errors': [], 'leaked_world_side_tokens': [], 'reason_whitelisted': True,
               'world_side_log': ['context_unreadable:' + type(exc).__name__], 'reply': None}
        _print_json(out)
        return 1
    try:
        res = gate_and_check(proposal, ctx, a.expected_context_sha256, schema_load(a.schema),
                             schema_load(a.reply_schema), a.disable)
    except Exception as exc:
        out = {'ok': False, 'decision': 'rejected', 'reason_code': 'schema_invalid',
               'errors': ['gate_internal_error:' + type(exc).__name__],
               'reply_schema_errors': [], 'leaked_world_side_tokens': [], 'reason_whitelisted': True,
               'world_side_log': ['gate_internal_error:' + type(exc).__name__], 'reply': None}
        _print_json(out)
        return 1
    out = {k: res.get(k) for k in ('ok', 'decision', 'reason_code', 'errors', 'reply_schema_errors',
                                   'leaked_world_side_tokens', 'reason_whitelisted', 'world_side_log',
                                   'replayed', 'proposal_digest', 'context_sha256', 'reply')}
    _print_json(out)
    return 0 if (res.get('decision') == 'accepted' and res.get('ok')) else 1


def worker_reply(a):
    try:
        rdoc = load_json(a.reply, strict=True)
        rschema = schema_load(a.reply_schema)
    except Exception as exc:
        _print_json({'ok': False, 'errors': ['reply_unreadable:' + type(exc).__name__],
                         'reason_whitelisted': False})
        return 1
    errs = errors_of(Draft202012Validator(rschema), rdoc)
    whitelisted = rdoc.get('reason_code') in whitelist_of(rschema)
    _print_json({'ok': not errs and whitelisted, 'errors': errs,
                     'reason_whitelisted': whitelisted})
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

# r4 F2：Entity_Id 与 ENTITY_ID 在本机大小写不敏感文件系统上会同名碰撞，
# 所以每条反例用“序号前缀 + 小写文件名”保存真正不同的路径；拼写别名只出现在内容里。
NORM_SPELLINGS = [
    ('world_id', '01_world_snake'), ('World_Id', '02_world_title'), ('WORLD_ID', '03_world_upper'),
    ('world-id', '04_world_hyphen'), ('world.id', '05_world_dot'), ('worldId', '06_world_camel'),
    ('worldID', '07_world_upper_camel'),
    ('worldIds', '08_world_plural_camel'), ('worldids', '09_world_plural_flat'),
    ('world_ids', '10_world_plural_snake'), ('worlds_id', '11_worlds_stem_snake'),
    ('entities_id', '13_entities_id'),
    ('entitiesID', '14_entities_upper_camel'), ('entitiesIds', '15_entities_ids'),
    ('entity_idx', '16_entity_idx'),
    ('objects_id', '17_objects_id'), ('actors_id', '18_actors_id'), ('scenes_id', '19_scenes_id'),
    ('events_id', '20_events_id'), ('instances_id', '21_instances_id'),
    ('landmarks_id', '22_landmarks_id'), ('agents_id', '23_agents_id'), ('truths_id', '24_truths_id'),
    ('gtWorldId', '25_gt_world_id'), ('gtObjectId', '26_gt_object_id'),
    ('rawEntityId', '27_raw_entity_id'), ('myActorId', '28_my_actor_id'), ('srcAgentId', '29_src_agent_id'),
    ('objectIdMap', '30_object_id_map'), ('sceneIDList', '31_scene_id_list'),
    ('eventIdsSet', '32_event_ids_set'), ('instanceIdValue', '33_instance_id_value'),
    ('entityIDRef', '34_entity_id_ref'),
    ('id_world', '35_id_prefix_world'), ('id_entity', '36_id_prefix_entity'),
    ('ids_object', '37_ids_prefix_object'),
    ('hidden_contact', '38_hidden_contact'), ('hiddenContacts', '39_hidden_contacts'),
    ('contact_id', '40_contact_id'),

    ('hidden_id', '41_hidden_id'), ('hiddens_id', '42_hiddens_id'), ('HIDDENID', '43_hidden_upper'),
    ('hiddenIdMap', '44_hidden_id_map'),
    ('OBJECTID', '45_object_upper_flat'), ('OBJECT_IDS', '46_object_upper_snake'),
    ('ENTITIESID', '47_entities_upper_flat'), ('ENTITIES_ID', '48_entities_upper_snake'),
    ('ENTITYID', '49_entity_upper_flat'), ('SCENEID', '50_scene_upper_flat'),
    ('AGENTIDS', '51_agent_upper_flat'), ('TRUTHID', '52_truth_upper_flat'),
    ('ids', '53_bare_ids'), ('ID', '54_bare_id_upper'), ('idx', '55_bare_idx'),
    ('identifiers', '56_bare_identifiers'),
]


# 层 1（schema 正则）已经覆盖绝大多数拼写；下面两条的层 1 不覆盖，只有规范化判定能拒，
# 因此它们的破坏对照是真正隔离的（control 会把提案放行）。
ISOLATED_BARE_FORMS = {'55_bare_idx', '56_bare_identifiers'}

# r4 F1：界线之外的裸复数词干（entities/objects/actors/…）两层都不拒——记录为“按设计接受”，
# 免得把「复数词干 + id 后缀」的要求说成「任何含复数的键都拒」。B5 的 oracle 同样不拒这些键。
ACCEPTED_BARE_STEMS = [('entities', '12_entities_plural'), ('objects', '57_objects_plural'),
                       ('actors', '58_actors_plural'), ('scenes', '59_scenes_plural'),
                       ('events', '60_events_plural'), ('instances', '61_instances_plural'),
                       ('landmarks', '62_landmarks_plural'), ('agents', '63_agents_plural'),
                       ('truths', '64_truths_plural'), ('worlds', '65_worlds_plural')]


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

    def add(name, valid, reason, rule, control, mutate, tick=850, mutation=None,
            alias_key=None, alias_display=None, string_case=None, expect_control_isolated=True):
        cs.append({'name': name, 'valid': valid, 'reason': reason, 'rule': rule, 'control': control,
                   'mutate': mutate, 'tick': tick, 'mutation': mutation,
                   'alias_key': alias_key, 'alias_display': alias_display,
                   'string_case': string_case,
                   'expect_control_isolated': expect_control_isolated})

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
    for key_spelling, case_suffix in NORM_SPELLINGS:
        add('world_id_norm_' + case_suffix, False, 'schema_invalid', 'world_id_normalization',
            'disable:world_id_normalization',
            lambda p, c, k=key_spelling: p.update(
                ability_id='abil-tag-objects',
                params={'tags': [{'color': 'red', k: 'world-synthetic-0001'}]}),
            alias_key=key_spelling,
            expect_control_isolated=((case_suffix in ISOLATED_BARE_FORMS) or
                                     (case_suffix == '12_entities_plural')))
    for bare_key, case_suffix in ACCEPTED_BARE_STEMS:
        add('world_id_norm_accepted_' + case_suffix, True, None, 'world_id_normalization', None,
            lambda p, c, k=bare_key: p.update(
                ability_id='abil-tag-objects',
                params={'tags': [{'color': 'red', k: 'note'}]}),
            alias_key=bare_key)
    for token in ('world_id', 'hidden_contact', 'contact_id', 'world.id', 'entityid'):
        add('quantity_value_' + token.replace('.', '_dot_'), False, 'schema_invalid', 'schema',
            'mutation:proposal_quantity_value_open,disable:world_id_normalization,quantity_allowlist,quantity_registry_binding',
            lambda p, c, token=token: p['expected_outcomes'][0].update(quantity=token),
            mutation='proposal_quantity_value_open')
    # r4 F6：允许表之外的名字（合法形态但不是可观察量）、以及允许表内但未被条目声明的量。
    add('quantity_not_in_allowlist', False, 'schema_invalid', 'schema',
        'mutation:proposal_quantity_value_open,disable:world_id_normalization,quantity_allowlist,quantity_registry_binding',
        lambda p, c: p['expected_outcomes'][0].update(quantity='detection.geo_truth_m'))
    add('quantity_not_declared_by_ability', False, 'schema_invalid', 'schema',
        'disable:quantity_registry_binding,world_id_normalization',
        lambda p, c: p['expected_outcomes'][0].update(quantity='audio_events.loudness'))
    # r4 F4：JCS 异常必须 fail-closed 成白名单原因码，不许 traceback。
    def m_jcs_int(p, c):
        # basis 里放 JCS 超范围整数：任何 JCS 计算都会抛错，所以这里不能重算摘要（写占位值）。
        p['basis']['t_ticks'] = 2 ** 53 - 1 + 1
        p['evidence_version'] = '0' * 64

    def m_jcs_surrogate(p, c):
        # 孤立代理项放进 actor.policy_revision：schema 只查长度不查字符集，回执也不回显该字段，
        # 但提案整体无法 JCS 规范化（编码失败）。
        p['actor']['policy_revision'] = '\ud800' * 6

    add('jcs_int_out_of_range', False, 'schema_invalid', 'jcs_fail_closed',
        'disable:jcs_fail_closed,schema,evidence,time_domain', m_jcs_int)
    add('jcs_lone_surrogate', False, 'schema_invalid', 'jcs_fail_closed',
        'disable:jcs_fail_closed,schema,actor,evidence,time_domain', m_jcs_surrogate)

    # ---- 预期结果的真值字段与窗口（裁决 7）
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


def registry_entry_checks(entry_schema):
    """r4 F1/F3 的独立正反例：登记条目 param_schema 的封闭性、动态分支拒收与属性名规范化判定。
    每条反例都直接过 schema 与核验器；控制项是“关掉对应检查后确实漏检”。"""
    ev = Draft202012Validator(entry_schema)
    base = {'schema_version': 'ability_registry_entry.v0', 'ability_id': 'abil-probe-entry',
            'ability_version': '1.0', 'effect_class': 'run', 'target_kinds': ['handle'],
            'max_actions': 1, 'max_duration_ticks': 12, 'max_ttl_ticks': 60,
            'param_schema': {'type': 'object', 'additionalProperties': False,
                             'required': ['speed_mps'],
                             'properties': {'speed_mps': {'type': 'number', 'minimum': 0, 'maximum': 3}}},
            'preconditions': [], 'observable_names': ['detection.rel_position_m']}

    def variant(**kw):
        e = copy.deepcopy(base)
        e.update(kw)
        return e

    def lite_problems(e):
        """关掉‘属性名规范化判定’之后剩下的问题（其余关键字检查保持原样）。
        这是‘关闭该检查后专用反例确实被接受’的破坏对照；属性名干净时它必然为空。"""
        return [x for x in _schema_keyword_problems(e.get('param_schema', {}), '')
                if 'forbidden_property:' not in x]

    rows = []

    def check(name, entry, want_schema_invalid, want_problem_prefix, control_off, isolate,
              require_problems=True):
        """schema 层问题与核对器问题分列；控制项用简化版（只查属性名）模拟“关掉该检查”。"""
        schema_invalid = not ev.is_valid(entry)
        schema_problems = errors_of(ev, entry)
        checker_problems = param_schema_problems(entry.get('param_schema'))
        all_problems = schema_problems + checker_problems
        prefix_ok = any(p.startswith(want_problem_prefix) for p in all_problems) if want_problem_prefix else True
        after = bool(lite_problems(entry)) if control_off else bool(checker_problems)
        isolated = (not after) if (isolate and control_off) else True
        rows.append({'name': name, 'schema_invalid': schema_invalid,
                     'schema_problems': schema_problems[:2],
                     'checker_problems': checker_problems[:4],
                     'problems_count': len(all_problems),
                     'problem_prefix_ok': prefix_ok,
                     'control_after_disable': after,
                     'expects': {'schema_invalid': want_schema_invalid, 'problems': require_problems,
                                 'isolated': isolate},
                     'ok': (schema_invalid == want_schema_invalid) and
                           (bool(checker_problems) if require_problems else True) and prefix_ok and isolated})

    check('entry_valid_closed_schema', copy.deepcopy(base), False, None, False, False,
          require_problems=False)
    check('entry_pattern_properties', variant(param_schema={
        'type': 'object', 'additionalProperties': False, 'patternProperties': {'^h-': {'type': 'string'}},
        'properties': {'speed_mps': {'type': 'number'}}}), False, 'unsupported_keyword:patternProperties',
        False, False)
    check('entry_nested_pattern_properties', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'tags': {'type': 'object', 'patternProperties': {'^x': {'type': 'string'}}}}}
    ), False, 'unsupported_keyword:patternProperties', False, False)
    check('entry_dynamic_ref', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'$ref': '#/$defs/num'}},
        '$defs': {'num': {'type': 'number'}}}), False, 'unsupported_keyword:$ref', False, False)
    check('entry_if_then', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'type': 'number'}}, 'if': {'required': ['speed_mps']},
        'then': {'required': ['stride_m']}}), False, 'unsupported_keyword:if', False, False)
    check('entry_one_of_param', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'speed_mps': {'oneOf': [{'type': 'number'}, {'type': 'string'}]}}}
    ), False, 'unsupported_keyword:oneOf', False, False)
    check('entry_additional_properties_open', variant(param_schema={
        'type': 'object', 'additionalProperties': True,
        'properties': {'speed_mps': {'type': 'number'}}}), True, None, False, False)
    check('entry_property_world_id', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'WORLD_ID': {'type': 'number'}}}), False, 'forbidden_property:WORLD_ID', True, True)
    check('entry_property_entities_id', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'entities_id': {'type': 'string'}}}), False, 'forbidden_property:entities_id',
        True, True)
    check('entry_property_object_id_alias', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'objectId': {'type': 'string'}}}), False, 'forbidden_property:objectId', True, True)
    check('entry_property_hidden_contact', variant(param_schema={
        'type': 'object', 'additionalProperties': False,
        'properties': {'hidden_contact': {'type': 'string'}}}), False,
        'forbidden_property:hidden_contact', True, True)
    # observable_names 的允许表由核对器守着（entry schema 的 $defs/observable_ref enum 也会拒绝，
    # 但这里的预期以核对器为准；schema 侧结果单列在 schema_invalid 里）。
    check('entry_observable_not_in_allowlist', variant(observable_names=['detection.geo_truth_m']),
          True, None, False, False, require_problems=False)
    check('entry_observable_world_id', variant(observable_names=['world_id']), True, None, False, False,
          require_problems=False)
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
    """把全部夹具写进给定目录。

    文件名 = 序号前缀 + 纯小写名字（r4 F2）：Entity_Id 与 ENTITY_ID 这类只在大小写上不同的拼写
    不能同时作为文件名，否则在大小写不敏感的文件系统上会同名碰撞。拼写别名只出现在内容里，
    并作为 alias_key 记进 EXPECTATIONS.json。
    """
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
    ordinal = 0
    for case in case_list:
        ctx = base_context(case['tick'])
        proposal = base_proposal(ctx)
        case['mutate'](proposal, ctx)
        if case['rule'] == 'duplicate':
            ctx['decisions_seen'] = [replay_record()]
        if case['name'] == 'replay_same_id_same_digest':
            proposal = replay_proposal()
        ordinal += 1
        directory = 'valid' if case['valid'] else 'invalid'
        fname = '%02d_%s.json' % (ordinal, case['name'])
        case['file_name'] = fname
        case['context_file'] = fname
        ppath = fixture_dir / directory / fname
        cpath = fixture_dir / 'contexts' / fname
        write(ppath, proposal)
        write(cpath, ctx)
        ctx_disk = load_json(cpath, strict=True)
        pin = jcs_sha(ctx_disk)
        # 该夹具故意把 basis 写成 JCS 超范围整数：摘要无法重算（重算本身就会抛错），
        # 保留 mutation 写入的占位摘要，由 __init__ 之外的控制路径负责接受。
        if case['name'] == 'jcs_int_out_of_range':
            raw = load_json(ppath, strict=True)
            raw['evidence_version'] = '0' * 64
            write(ppath, raw)
        pins[case['name']] = pin
        expectations.append({'name': case['name'], 'dir': directory, 'rule': case['rule'],
                             'expected_decision': 'accepted' if case['valid'] else 'rejected',
                             'expected_reason_code': case['reason'], 'control': case['control'],
                             'proposal_file': ppath.name, 'context_file': cpath.name,
                             'proposal_sha256': sha(ppath.read_bytes()), 'context_sha256': pin,
                             'context_sha256_jcs': pin,
                             'alias_key': case['alias_key'], 'alias_display': case['alias_display']})

    reply_list = reply_cases()
    for idx, rc in enumerate(reply_list, start=1):
        directory = 'valid' if rc['valid'] else 'invalid'
        rc['file_name'] = '%02d_%s.json' % (idx, rc['name'])
        rpath = fixture_dir / 'replies' / directory / rc['file_name']
        write(rpath, rc['reply'])
        expectations.append({'name': rc['name'], 'dir': 'replies/' + directory,
                             'expected_decision': 'valid' if rc['valid'] else 'invalid',
                             'control': ('mutation:' + rc['mutation']) if rc['mutation'] else None,
                             'reply_file': rc['file_name'],
                             'reply_sha256': sha(rpath.read_bytes())})

    write(fixture_dir / 'EXPECTATIONS.json', {
        'synthetic_only': True,
        'note': '全部夹具都是 synthetic 冻结上下文；不是真实 AWZ 回合，不构成运行授权或能力。'
                'context_identity_pins 是调用方固定的上下文身份，核对时须逐字传入。'
                '文件名带序号前缀，避免大小写不敏感文件系统上同名碰撞（r4 F2）；'
                '拼写别名在 contents 与 alias_key 里。',
        'hash_semantics': {'proposal_sha256': 'raw file bytes sha256（原始字节）',
                           'context_sha256': 'JCS 上下文身份的 sha256（规范 JSON，RFC 8785）',
                           'context_sha256_jcs': '与 context_sha256 相同的 JCS 摘要，分列以免口径混用',
                           'reply_sha256': 'raw file bytes sha256（原始字节）'},
        'context_identity_pins': pins,
        'cases': expectations,
    })
    return mut_paths, pins, expectations, case_list, reply_list


def suite(regenerate=False, root_arg=None, output_dir=None):
    # r6 B9 必修：先校验输出路径，再做任何工作与任何写入。
    # 输出与实际输入同路径/祖先/后代/符号链接别名 重叠，或输出目录已含输出证据，一律清楚拒绝（exit 2）。
    # 默认只读（output_dir=None）不进入本分支，行为与 r5 一致。
    _reject_reason, _reject_rc = reject_output_dir(
        Path(output_dir).resolve() if output_dir else None)
    if _reject_reason is not None:
        _print_json({'ok': False, 'all_ok': False,
                     'output_dir_rejected': True,
                     'output_dir': str(output_dir),
                     'errors': [_reject_reason.splitlines()[0]],
                     'reason': _reject_reason,
                     'note': '在 mkdir 与写 check_result.json / SHA256SUMS.txt 之前拒绝；'
                             '合法的全新隔离输出目录不受影响。'})
        return _reject_rc
    pschema, rschema, eschema = schema_load(PROPOSAL_SCHEMA), schema_load(REPLY_SCHEMA), schema_load(ENTRY_SCHEMA)
    temp_dir_ctx = None

    if regenerate:
        if FIXTURE.exists():
            shutil.rmtree(FIXTURE)
        if SABOTAGE.exists():
            shutil.rmtree(SABOTAGE)
        FIXTURE.mkdir(parents=True, exist_ok=True)
        SABOTAGE.mkdir(parents=True, exist_ok=True)
        mut_paths, pins, expectations, case_list, reply_list = generate_fixtures_to_dir(
            FIXTURE, SABOTAGE, pschema, rschema)
        target_fixture = FIXTURE
        target_sabotage = SABOTAGE
    else:
        temp_dir_ctx = tempfile.TemporaryDirectory()
        tmp_path = Path(temp_dir_ctx.name)
        tmp_fixture = tmp_path / 'fixture'
        tmp_sabotage = tmp_path / 'sabotage'
        mut_paths, pins, expectations, case_list, reply_list = generate_fixtures_to_dir(
            tmp_fixture, tmp_sabotage, pschema, rschema)

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
    for case in case_list:
        directory = 'valid' if case['valid'] else 'invalid'
        ppath = target_fixture / directory / case['file_name']
        cpath = target_fixture / 'contexts' / case['context_file']
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
                     'proposal_file': case['file_name'], 'context_file': case['file_name'],
                     'alias_key': case['alias_key'],
                     'proposal_sha256': sha_p, 'context_sha256': pin,
                     'reply': result['payload'].get('reply'),
                     'reply_schema_errors': result['payload'].get('reply_schema_errors'),
                     'leaked_world_side_tokens': result['payload'].get('leaked_world_side_tokens'),
                     'world_side_log': result['payload'].get('world_side_log'),
                     'replayed': result['payload'].get('replayed', False),
                     'ok': ok, 'exception': result['exception']})
        if case['control']:
            cargv = argv[:]
            for part in case['control'].split(','):
                if part.startswith('mutation:'):
                    schema_name = part.split(':', 1)[1]
                    cargv[cargv.index('--schema') + 1] = str(SABOTAGE / (schema_name + '.json'))
                    if schema_name in ('proposal_no_additional_properties',
                                       'proposal_no_world_id_key'):
                        cargv += ['--disable', 'world_id_normalization']
                else:
                    # 'disable:a,b' 与 'disable:a,disable:b' 都接受：裸词按规则名处理。
                    rule = part.split(':', 1)[1] if part.startswith('disable:') else part
                    if not rule:
                        continue
                    cargv += ['--disable', rule]
            expected_rules = {x.split(':', 1)[1] for x in case['control'].split(',')
                              if x.startswith('disable:')}
            expected_rules |= {x for x in case['control'].split(',')
                               if x and not x.startswith(('disable:', 'mutation:'))}
            if case['control'].startswith('mutation:') and \
                    case['control'].split(',')[0].split(':', 1)[1] in (
                        'proposal_no_additional_properties', 'proposal_no_world_id_key'):
                expected_rules.add('world_id_normalization')
            cr = run_process(cargv)
            isolated = (result['returncode'] == 1 and cr['returncode'] == 0 and not cr['exception'] and
                        cr['payload'].get('decision') == 'accepted')
            controls.append({'name': case['name'], 'rule': case['rule'], 'control': case['control'],
                             'base_returncode': result['returncode'],
                             'control_returncode': cr['returncode'],
                             'control_reason': cr['payload'].get('reason_code'),
                             'isolated_miss': isolated,
                             'expect_isolated': case['expect_control_isolated'],
                             'exception': cr['exception']})

    # 裁决 6：置信度调到 1.0（和 0.0）都不能改变任何一次判定
    sweep = []
    for case in case_list:
        if case['valid'] or case['rule'] == 'duplicate':
            continue
        ctx = base_context(case['tick'])
        proposal = base_proposal(ctx)
        case['mutate'](proposal, ctx)
        cpath = target_fixture / 'contexts' / case['context_file']
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
    for rc in reply_list:
        directory = 'valid' if rc['valid'] else 'invalid'
        rpath = target_fixture / 'replies' / directory / rc['file_name']
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
        p = load_json(target_fixture / 'valid' / row['proposal_file'], strict=True)
        reply = row['reply'] or {}
        no_rewrite.append({'name': row['name'],
                           'evidence_version_echoed':
                               reply.get('evidence_version') == p.get('evidence_version'),
                           'evidence_version_is_basis_digest':
                               p.get('evidence_version') == safe_jcs_sha(p.get('basis', {})),
                           'ok': reply.get('evidence_version') == p.get('evidence_version') and
                                 p.get('evidence_version') == safe_jcs_sha(p.get('basis', {}))})

    # 门禁可见回执泄露扫描：每一条回执都不得含世界侧标识
    toks = world_side_tokens(base_context())
    leak = []
    for row in rows:
        reply = row['reply'] or {}
        try:
            blob = jcs(reply).decode('utf-8') if reply else ''
            canon_ok = True
        except Exception as exc:      # 回执含不可规范化字段（JCS 超范围整数/孤立代理项）
            blob, canon_ok = '', False
            note = type(exc).__name__
        leaked = [t for t in toks if t in blob]
        leak.append({'name': row['name'], 'leaked': leaked, 'reply_canonical': canon_ok,
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
    entry_schema_rows = [{'ability_id': e['ability_id'], 'effect_class': e['effect_class'],
                          'entry_schema_ok': ev.is_valid(e)} for e in registry_entries()]
    entry_matrix = registry_entry_checks(eschema)
    entry_observable_union = sorted({n for e in registry_entries() for n in e['observable_names']})

    # r4 F2：交付夹具目录里不得有两个文件名在大小写不敏感文件系统上指向同一个 inode。
    collision_rows = []
    committed_files = sorted(p for p in FIXTURE.rglob('*') if p.is_file())
    inodes = {}
    for p in committed_files:
        try:
            st = p.stat()
        except OSError:
            continue
        key = str(p.relative_to(FIXTURE)).casefold()
        collision_rows.append({'path': str(p.relative_to(ROOT)), 'inode': st.st_ino,
                               'size': st.st_size, 'casefold_name': key})
    dup_case = {}
    for row in collision_rows:
        dup_case.setdefault(row['casefold_name'], []).append(row['path'])
    case_collisions = sorted(k for k, v in dup_case.items() if len(v) > 1)
    by_inode = {}
    for row in collision_rows:
        by_inode.setdefault(row['inode'], []).append(row['path'])
    inode_collisions = sorted([v for v in by_inode.values() if len(v) > 1])

    # 回归输入：B5 的 1131 条探针（只读复用，不硬编码例子 ID）。文件缺失时只报告不失败。
    probe_rows, probe_invariants = [], []
    probe_path = ROOT / 'reports/V-V9-B1/probe_variants.json'
    if probe_path.is_file():
        probes = load_json(probe_path, strict=True)
        family_counts, family_reject = {}, {}
        for x in probes:
            fam = x.get('family')
            family_counts[fam] = family_counts.get(fam, 0) + 1
            if is_forbidden_world_id_key(x.get('key')):
                family_reject[fam] = family_reject.get(fam, 0) + 1
        probe_rows = [{'family': f, 'total': family_counts[f],
                       'rejected_by_normalization': family_reject.get(f, 0)} for f in sorted(family_counts)]
        probe_ok = all(r['rejected_by_normalization'] == r['total'] for r in probe_rows)
        probe_invariants.append({'name': 'b5_probe_variants_rejected_by_normalization',
                                 'total': len(probes), 'rejected': sum(family_reject.values()),
                                 'by_family': probe_rows, 'ok': probe_ok})
        rx = re.compile(schema_load(PROPOSAL_SCHEMA)['$defs']['world_id_key']['pattern'])
        l1 = sum(1 for x in probes if rx.search(x['key']))
        probe_invariants.append({'name': 'b5_probe_variants_rejected_by_schema_pattern',
                                 'total': len(probes), 'rejected': l1,
                                 'note': 'schema 只做结构快拒；完整覆盖由规范化判定负责（r4 F5 闭合矩阵）。',
                                 'ok': l1 > 0})
    else:  # pragma: no cover - 探针文件在复核目录里
        probe_invariants.append({'name': 'b5_probe_variants_present', 'ok': False,
                                 'note': '未找到 reports/V-V9-B1/probe_variants.json'})

    # 允许表一致性：schema enum 与核对器的 OBSERVABLE_QUANTITIES 必须逐项一致。
    schema_q = schema_load(PROPOSAL_SCHEMA)['$defs']['observable_quantity']['enum']
    entry_q = schema_load(ENTRY_SCHEMA)['$defs']['observable_ref']['enum']
    consistency = [
        {'name': 'schema_enum_matches_checker_allowlist', 'ok': sorted(schema_q) == sorted(OBSERVABLE_QUANTITIES),
         'schema_count': len(schema_q), 'checker_count': len(OBSERVABLE_QUANTITIES)},
        {'name': 'entry_enum_matches_checker_allowlist', 'ok': sorted(entry_q) == sorted(OBSERVABLE_QUANTITIES),
         'entry_count': len(entry_q), 'checker_count': len(OBSERVABLE_QUANTITIES)},
    ]

    # 破坏对照规则卫生：未知名必须显式失败（退出码 2），已知名必须被接受（退出码不为 2）。
    hygiene = []
    for label, rules, want_rc2 in (('unknown_rule_rejected', ['no_such_rule_zzz'], True),
                                   ('known_rule_accepted', ['params'], False)):
        hargv = [sys.executable, '-I', str(Path(__file__)), 'gate',
                 '--proposal', str(target_fixture / 'valid' / case_list[0]['file_name']),
                 '--context', str(target_fixture / 'contexts' / case_list[0]['context_file']),
                 '--expected-context-sha256', pins[case_list[0]['name']],
                 '--schema', str(PROPOSAL_SCHEMA), '--reply-schema', str(REPLY_SCHEMA)]
        for r in rules:
            hargv += ['--disable', r]
        hr = run_process(hargv)
        hygiene.append({'name': label, 'rules': rules, 'returncode': hr['returncode'],
                        'ok': (hr['returncode'] == 2) if want_rc2 else (hr['returncode'] != 2),
                        'payload_errors': (hr['payload'] or {}).get('errors')})

    jcs_rows = jcs_self_tests()
    diffs = []
    for p in sorted(FIXTURE.rglob('*.json')):
        obj = load_json(p, strict=True)
        legacy = json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        try:                                   # 含 JCS 超范围整数的夹具按异常记录，只报告
            canon = jcs(obj).decode('utf-8')
        except Exception as exc:
            diffs.append({'path': str(p.relative_to(ROOT)), 'legacy': legacy[:100],
                          'jcs': 'error:' + type(exc).__name__})
            continue
        if legacy != canon:
            diffs.append({'path': str(p.relative_to(ROOT)), 'legacy': legacy[:100]})

    if temp_dir_ctx:
        temp_dir_ctx.cleanup()

    bad_controls = ([c['name'] for c in controls
                     if c['expect_isolated'] and not c['isolated_miss']] +
                    [c['name'] for c in rcontrols if not c['isolated_miss']])
    non_isolated_by_design = [c['name'] for c in controls
                              if not c['expect_isolated'] and not c['isolated_miss']]
    unexpected_isolated = [c['name'] for c in controls
                           if not c['expect_isolated'] and c['isolated_miss']]
    failures = (
                [r['name'] for r in rows if not r['ok']] + [r['name'] for r in rrows if not r['ok']] +
                [x['name'] for x in sweep if not x['ok']] +
                [x['name'] for x in no_rewrite if not x['ok']] +
                [x['name'] for x in leak if not x['ok']] +
                [x['schema'] for x in meta if not x['meta_ok']] +
                [x['name'] for x in jcs_rows if not x['ok']] +
                [x['ability_id'] for x in entry_schema_rows if not x['entry_schema_ok']] +
                ['entry_matrix:' + x['name'] for x in entry_matrix if not x['ok']] +
                ['probe:' + x['name'] for x in probe_invariants if not x['ok']] +
                ['consistency:' + x['name'] for x in consistency if not x['ok']] +
                ['hygiene:' + x['name'] for x in hygiene if not x['ok']] +
                ['unexpectedly_isolated:' + n for n in unexpected_isolated])
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
            'schema_meta_checks': len(meta), 'registry_entries': len(entry_schema_rows),
            'registry_entry_matrix_rows': len(entry_matrix),
            'registry_entry_matrix_ok': sum(x['ok'] for x in entry_matrix),
            'probe_invariant_rows': len(probe_invariants),
            'consistency_rows': len(consistency), 'hygiene_rows': len(hygiene),
            'fixture_files_checked': len(collision_rows),
            'case_insensitive_name_collisions': len(case_collisions),
            'same_inode_collisions': len(inode_collisions),
            'existing_canon_vs_jcs_differences': len(diffs),
        },
        'controls_non_isolated_by_design': non_isolated_by_design,
        'controls_unexpectedly_isolated': unexpected_isolated,
        'cases': rows, 'controls': controls, 'confidence_sweep': sweep,
        'reply_cases': rrows, 'reply_controls': rcontrols,
        'no_rewrite': no_rewrite, 'leak_scan': leak, 'schema_meta': meta,
        'registry_entries_in_frozen_context': entry_schema_rows,
        'registry_entry_matrix': entry_matrix,
        'registry_entry_observable_union': entry_observable_union,
        'fixture_name_collision_scan': {'files': len(collision_rows),
                                        'case_insensitive_collisions': case_collisions,
                                        'same_inode_collisions': inode_collisions,
                                        'sample': collision_rows[:3]},
        'b5_probe_invariants': probe_invariants,
        'allowlist_consistency': consistency,
        'disable_rule_hygiene': hygiene,
        'jcs_self_tests': jcs_rows,
        'canon_vs_jcs_report_only': {
            'differences': len(diffs), 'sample': diffs[:5],
            'note': '只报告；不改 Event/v1 r2、teacher_cache v2 或任何既有契约（RFC 8785 迁移由一级另行决定）。'},
        'failures': failures, 'control_failures': bad_controls,
    }
    out_dir = Path(output_dir).resolve() if output_dir else None
    if out_dir is not None:
        # 写入前第二道校验：即便顶部之后路径被改动/新建了证据文件，也绝不在重叠或覆盖时落盘。
        _late_reason, _late_rc = reject_output_dir(out_dir)
        if _late_reason is not None:
            _print_json({'ok': False, 'all_ok': False,
                         'output_dir_rejected': True,
                         'output_dir': str(out_dir),
                         'errors': [_late_reason.splitlines()[0]],
                         'reason': _late_reason,
                         'note': '写入前复查拒绝；本轮未创建目录、未写任何文件。'})
            return _late_rc
        out_dir.mkdir(parents=True, exist_ok=True)
        write(out_dir / 'check_result.json', result)
        write_sha_manifest(result, out_dir)
    _print_json({k: result[k] for k in ('all_ok', 'counts', 'failures', 'control_failures')})
    return int(not all_ok)


def gen_jcs_sha(path):
    """文件内容按 RFC 8785 规范化后的 sha256（只对 JSON 有意义）。"""
    return jcs_sha(load_json(path, strict=True))


# --------------------------------------------------------------------------- r6 输出路径重叠校验（B9 必修）
#
# B9 实证：--output-dir 指向隔离候选输入目录时仍 rc=0/all_ok=true，并把 check_result.json
# 与 SHA256SUMS.txt 两份原字节覆盖。r6 只修这一项：任何输出与实际输入发生同路径、祖先、
# 后代或符号链接别名 重叠，或输出目录里已存在输出证据文件，均在写任何文件之前清楚拒绝。
# 合法的全新隔离输出目录与「默认只读（不传 --output-dir 就不写）」保持不变。

OUTPUT_EVIDENCE_FILES = ('check_result.json', 'SHA256SUMS.txt')


def _resolved(p):
    """规范绝对路径：跟随路径上所有仍存在的符号链接段（含尚未创建的尾段前缀）。
    别名重叠（symlink 指向输入目录）在 resolve 之后与输入同路径，因而被同路径分支命中。"""
    return Path(p).resolve()


def _manifest_inputs():
    """write_sha_manifest 实际读取/哈希的 (交付物, 只读输入) 两份清单。
    与输出重叠校验共用同一份，避免两处清单漂移；在调用时求值，以跟随 --root 改写。"""
    deliverables = [
        ('contracts/v9/skill_proposal.v1.schema.json', PROPOSAL_SCHEMA),
        ('contracts/v9/skill_gate_reply.v1.schema.json', REPLY_SCHEMA),
        ('contracts/v9/ability_registry_entry.v0.schema.json', ENTRY_SCHEMA),
        ('docs/v9/SKILL_PROPOSAL.md', ROOT / 'docs/v9/SKILL_PROPOSAL.md'),
        ('reports/V9-B1/COORDINATOR_DECISIONS.md', OUT / 'COORDINATOR_DECISIONS.md'),
        ('reports/V9-B1/check_skill_proposal.py', Path(__file__).resolve()),
        ('reports/V9-B1/check_result.json', OUT / 'check_result.json'),
        ('reports/V9-B1/metrics.json', OUT / 'metrics.json'),
        ('reports/V9-B1/REPORT.md', OUT / 'REPORT.md'),
        ('contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json', FIXTURE / 'EXPECTATIONS.json'),
        ('reports/V9-B1/r4/SUMMARY.md', OUT / 'r4/SUMMARY.md'),
    ]
    read_only = [
        ('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json',
         Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')),
        ('ARCHITECTURE_V9.md', ROOT / 'ARCHITECTURE_V9.md'),
        ('docs/v9/SKILL_PROPOSAL_COORDINATION.md', ROOT / 'docs/v9/SKILL_PROPOSAL_COORDINATION.md'),
        ('docs/v9/TEACHERS_AND_CACHE.md', ROOT / 'docs/v9/TEACHERS_AND_CACHE.md'),
        ('/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261017-cycle1/'
         'B4-r4-DECISIONS.md',
         Path('/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261017-cycle1/'
              'B4-r4-DECISIONS.md')),
        ('reports/V-V9-B1/probe_variants.json', ROOT / 'reports/V-V9-B1/probe_variants.json'),
        ('reports/V-V9-B1/oracle_r3.py', ROOT / 'reports/V-V9-B1/oracle_r3.py'),
    ]
    return deliverables, read_only


def manifest_input_paths():
    """suite 实际读取的全部输入：脚本同目录（含 fixtures / sabotage-schemas）、夹具目录、
    对照 schema 目录，以及 write_sha_manifest 会哈希的每一份文件。单一清单来源。"""
    deliverables, read_only = _manifest_inputs()
    return [OUT, FIXTURE, SABOTAGE] + [p for _label, p in deliverables] + [p for _label, p in read_only]


def output_overlap_reason(output_dir):
    """输出目录与任一输入发生重叠、或已含输出证据时，返回可读拒绝原因；否则返回 None。
    重叠三种：同路径、输出是输入的祖先、输出在输入之内（后代）；符号链接别名经 resolve
    后归入同路径。必须在 mkdir 与任何写文件之前调用。"""
    if output_dir is None:
        return None
    out = _resolved(output_dir)
    for raw in manifest_input_paths():
        if not raw:
            continue
        cand = _resolved(raw)
        if out == cand:
            return ('output_path_is_input: 输出目录与实际输入是同一路径（同路径重叠）：\n  输出 = %s\n  输入 = %s'
                    % (out, cand))
        if cand in out.parents:
            return ('output_inside_input: 输出目录位于实际输入之内（后代重叠）：\n  输出 = %s\n  被包含于 = %s'
                    % (out, cand))
        if out in cand.parents:
            return ('output_ancestor_of_input: 输出目录是实际输入的祖先（祖先重叠）：\n  输出 = %s\n  含输入 = %s'
                    % (out, cand))
    for name in OUTPUT_EVIDENCE_FILES:
        target = out / name
        if target.is_symlink() or target.exists():
            return ('output_evidence_exists: 输出目录已存在输出证据文件，拒绝覆盖既有文件：\n  文件 = %s'
                    % target)
    return None


def reject_output_dir(output_dir):
    """返回 (拒绝原因, 退出码)。可用时返回 (None, 0)。"""
    reason = output_overlap_reason(output_dir)
    if reason is None:
        return None, 0
    return reason, 2


def write_sha_manifest(result, out_dir=None):
    """r4 F7：重算全部交付物与输入的 SHA，并把「原始字节」与「JCS 摘要」分栏写清楚。"""
    deliverables, read_only = _manifest_inputs()
    lines = [
        '# V9.B4 交付物与输入身份（SHA256）',
        '# 生成：suite 每次运行重算；本目录内 COORDINATOR_DECISIONS.md 未改（只读输入）。',
        '# 口径：raw = 文件原始字节 sha256；jcs = RFC 8785 规范 JSON 的 sha256（只在 JSON 上下文上有意义）。',
        '# 注：check_result.json 含故意的 JCS 超范围整数夹具（jcs_int_out_of_range），'
        '其 jcs 列按 jcs_error:<Type> 记；本清单不列自身的 raw（自指）。',
        '',
        '## 交付物（raw / jcs）',
        'RAW_SHA256  JCS_SHA256  PATH',
    ]
    for label, path in deliverables:
        if not path.is_file():
            lines.append('%-64s  %-64s  %s' % ('MISSING', 'MISSING', label))
            continue
        raw = sha(path.read_bytes())
        jcs_col = '-'
        if path.suffix == '.json':
            try:
                jcs_col = gen_jcs_sha(path)
            except Exception as exc:  # pragma: no cover
                jcs_col = 'jcs_error:' + type(exc).__name__
        lines.append('%-64s  %-64s  %s' % (raw, jcs_col, label))
    lines += ['', '## 只读输入（raw / jcs）', 'RAW_SHA256  JCS_SHA256  PATH']
    for label, path in read_only:
        if not path.is_file():
            lines.append('%-64s  %-64s  %s' % ('MISSING', 'MISSING', label))
            continue
        raw = sha(path.read_bytes())
        jcs_col = '-'
        if path.suffix == '.json':
            try:
                jcs_col = gen_jcs_sha(path)
            except Exception as exc:  # pragma: no cover
                jcs_col = 'jcs_error:' + type(exc).__name__
        lines.append('%-64s  %-64s  %s' % (raw, jcs_col, label))
    lines += ['', '# 注：本清单不列自身的 RAW（自指，写入后即变）；check_result.json 的 RAW 同一轮有效。',
              '', '## 夹具（raw / JCS 上下文身份）', 'RAW_SHA256  JCS_SHA256  PATH']
    for path in sorted(FIXTURE.rglob('*')):
        if not path.is_file():
            continue
        raw = sha(path.read_bytes())
        jcs_col = '-'
        if path.suffix == '.json':
            try:
                jcs_col = gen_jcs_sha(path)
            except Exception as exc:
                jcs_col = 'jcs_error:' + type(exc).__name__
        lines.append('%-64s  %-64s  %s' % (raw, jcs_col, str(path.relative_to(ROOT))))
    lines += ['', '## 计数（来自 check_result.json）']
    for k in sorted(result['counts']):
        lines.append('# %s = %s' % (k, result['counts'][k]))
    _target = (Path(out_dir) if out_dir else OUT)
    (_target / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--suite', action='store_true')
    p.add_argument('--regenerate', action='store_true', help='显式原地重写交付夹具目录（复核流程不得使用）')
    p.add_argument('--root', default=None, help='仓库根目录（避免写死路径）')
    p.add_argument('--output-dir', default=None, help='显式输出目录；默认只读不写 check_result/SHA256SUMS')
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
    # r4 F7：未知的破坏对照规则名必须显式失败（退出码 2），不能静默 no-op。
    unknown = sorted(set(a.disable) - KNOWN_DISABLE_RULES)
    if unknown:
        _print_json({'ok': False, 'errors': ['unknown_disable_rule:' + ','.join(unknown)],
                         'known_rules': sorted(KNOWN_DISABLE_RULES)})
        return 2
    schema_path = a.schema or str(PROPOSAL_SCHEMA)
    reply_schema_path = a.reply_schema or str(REPLY_SCHEMA)
    if a.suite:
        return suite(regenerate=a.regenerate, root_arg=a.root, output_dir=a.output_dir)
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
