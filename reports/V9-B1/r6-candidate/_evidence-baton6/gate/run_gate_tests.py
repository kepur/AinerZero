#!/usr/bin/env python3
"""B7 第6棒：gate/reply 入口行为测试（重复键、非法属性名+F2干净拒绝、来源内容绑定/漂移）。
全部在 /tmp staging 副本上执行；真实候选/原 r4/AWZ 只读。"""
import json, hashlib, subprocess, sys, importlib.util, shutil
from pathlib import Path

PY = '/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python'
STAGE = Path('/tmp/b7r6-stage/repo')
CAND = STAGE / 'reports/V9-B1/r6-candidate'
CK = CAND / 'check_skill_proposal.py'
EV = Path('/tmp/b7r6-evidence/gate')
INPUTS = EV / 'inputs'
TB = 'Traceback (most recent call last)'

INPUTS.mkdir(parents=True, exist_ok=True)
base_ctx = CAND / 'fixtures/contexts/01_valid_minimal_handle_target.json'
base_prop = CAND / 'fixtures/valid/01_valid_minimal_handle_target.json'
base_reply = CAND / 'fixtures/replies/valid/01_accepted_reply.json'
for p in (base_ctx, base_prop, base_reply):
    shutil.copy2(p, INPUTS / p.name)

def sha(b): return hashlib.sha256(b).hexdigest()
def file_sha(p): return sha(Path(p).read_bytes())

# 载入被测核对器的 JCS（仅读 import；-B 不写 pycache）
spec = importlib.util.spec_from_file_location('ck_under_test', str(CK))
ck = importlib.util.module_from_spec(spec); spec.loader.exec_module(ck)
def jcs_pin(obj): return ck.jcs_sha(obj)

def mutate_dup(src_path, key, dst_path, extra_value='0.6'):
    """文本手术：在同一对象里插入重复键（不经过 json 解析，保证重复键字节存在）。"""
    raw = Path(src_path).read_text(encoding='utf-8')
    needle = '  "%s":' % key
    assert needle in raw, 'anchor %r missing' % needle
    idx = raw.index(needle)
    line_end = raw.index('\n', idx)
    insert = '\n  "%s": %s,' % (key, extra_value)
    out = raw[:line_end] + insert + raw[line_end:]
    Path(dst_path).write_text(out, encoding='utf-8')
    return out

def run(label, argv, env_extra=None):
    import os
    env = dict(os.environ)
    if env_extra: env.update(env_extra)
    r = subprocess.run(argv, cwd=str(STAGE), env=env, capture_output=True, text=True, timeout=120)
    (EV / ('%s.stdout' % label)).write_text(r.stdout, encoding='utf-8')
    (EV / ('%s.stderr' % label)).write_text(r.stderr, encoding='utf-8')
    (EV / ('%s.rc' % label)).write_text(str(r.returncode))
    row = {'label': label, 'argv': argv[3:] if argv[0] == str(PY) else argv,
           'rc': r.returncode, 'traceback': TB in r.stderr, 'stderr_bytes': len(r.stderr),
           'stdout_head': r.stdout[:300].replace('\n', ' '), 'stdout_sha256': sha(r.stdout.encode()),
           'stderr_sha256': sha(r.stderr.encode())}
    try: row['parsed'] = json.loads(r.stdout)
    except Exception: row['parsed'] = None
    return row

rows = []
def gate(prop, ctx, pin, disable=None, extra_argv=None, label='', env_extra=None):
    argv = [PY, '-B', str(CK), 'gate', '--proposal', str(prop), '--context', str(ctx),
            '--expected-context-sha256', pin]
    for d in (disable or []): argv += ['--disable', d]
    return run(label, argv + (extra_argv or []), env_extra=env_extra)
def reply(rep, label):
    return run(label, [PY, '-B', str(CK), 'reply', '--reply', str(rep)])

base_pin = json.loads((CAND / 'fixtures/EXPECTATIONS.json').read_text())['context_identity_pins']['valid_minimal_handle_target']
ctx_obj = json.loads(base_ctx.read_text())
prop_s = str(INPUTS / base_prop.name); ctx_s = str(base_ctx)

# 0) 基线正例
rows.append(gate(prop_s, ctx_s, base_pin, label='T0_base_valid'))
# 1) 重复键 proposal / context / reply
mutate_dup(base_prop, 'confidence', INPUTS / 'dup_proposal.json')
rows.append(gate(str(INPUTS / 'dup_proposal.json'), ctx_s, base_pin, label='T1_dup_proposal'))
mutate_dup(base_ctx, 'context_id', INPUTS / 'dup_context.json')
dup_ctx_obj = json.loads('{ "x":1 }', object_pairs_hook=None)  # placeholder keep simple
rows.append(gate(prop_s, str(INPUTS / 'dup_context.json'), jcs_pin(None) if False else base_pin, label='T2_dup_context'))
mutate_dup(base_reply, 'decision', INPUTS / 'dup_reply.json', '"accepted"')
rows.append(reply(str(INPUTS / 'dup_reply.json'), 'T3_dup_reply'))

# 2) 非法登记属性名（F2 干净拒绝；嵌套）
def ctx_with(mutator, name):
    obj = json.loads(base_ctx.read_text())
    mutator(obj)
    p = INPUTS / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return p, jcs_pin(obj)
p_ill, pin_ill = ctx_with(lambda o: o['ability_registry']['entries'][0]['param_schema']['properties'].__setitem__('world_id', {'type': 'string'}), 'ctx_illegal_property.json')
rows.append(gate(prop_s, str(p_ill), pin_ill, label='T4_illegal_property'))
def nested(o):
    o['ability_registry']['entries'][0]['param_schema']['properties']['tags'] = {
        'type': 'array', 'items': {'type': 'object', 'additionalProperties': {'type': 'string'},
        'properties': {'worldId': {'type': 'string'}}}}
p_ill_n, pin_ill_n = ctx_with(nested, 'ctx_illegal_property_nested.json')
rows.append(gate(prop_s, str(p_ill_n), pin_ill_n, label='T5_illegal_property_nested'))

# 3) 关守卫对照（真漏检）：分别关关键字遍历层 / check_schema_props_forbidden / 两层全关
src = CK.read_text(encoding='utf-8')
kw_old = ("    for name, sub in (s.get('properties') or {}).items():\n"
          "        if is_forbidden_world_id_key(name):\n"
          "            out.append(here('forbidden_property:' + str(name)))\n")
assert kw_old in src
kw_off = src.replace(kw_old, ("    for name, sub in (s.get('properties') or {}).items():\n"
                              "        pass  # B7-r6 对照：关关键字遍历里的登记属性名守卫\n"))
reg_old = ("def check_schema_props_forbidden(s, path='param_schema'):\n"
           '    """递归收集 param_schema 里既未支持也不合规的属性名（含 patternProperties 这类动态分支）。"""\n'
           '    out = []\n')
assert reg_old in src
reg_off = src.replace(reg_old, ("def check_schema_props_forbidden(s, path='param_schema'):\n"
                                '    """B7-r6 对照：关掉登记属性名递归守卫。"""\n'
                                '    return []\n'))
variants = {
    'nokw': (kw_off, 'check_skill_proposal_nokw.py'),
    'noreg': (reg_off, 'check_skill_proposal_noreg.py'),
    'noboth': (kw_off.replace(reg_old, reg_old), 'check_skill_proposal_noboth.py'),
}
# noboth：在 kw_off 基础上再关 check_schema_props_forbidden
variants['noboth'] = (kw_off.replace(reg_old, ("def check_schema_props_forbidden(s, path='param_schema'):\n"
                                                '    """B7-r6 对照：关掉登记属性名递归守卫。"""\n'
                                                '    return []\n')), 'check_skill_proposal_noboth.py')
variant_sha = {}
for name, (text, fname) in variants.items():
    p = CAND / fname
    p.write_text(text, encoding='utf-8')
    variant_sha[name] = {'path': str(p), 'sha256': sha(text.encode())}
for vname in ('nokw', 'noreg', 'noboth'):
    vck = CAND / variants[vname][1]
    argv = [PY, '-B', str(vck), 'gate', '--proposal', prop_s, '--context', str(p_ill),
            '--expected-context-sha256', pin_ill]
    rows.append(run('T6_illegal_property_guard_off_%s' % vname, argv))

# 4) 来源内容绑定：旧路径 pin 拒绝 / 有效上下文内容 pin 通过 / 漂移+缺失拒绝 / 关来源守卫真漏检
AWZ = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')
awz_sha = file_sha(AWZ)
drift = Path('/tmp/b7r6-envsrc/obs_drift.json')
drift.write_bytes(AWZ.read_bytes() + b'\n')
def ctx_source(field_sha, drop_path, name):
    obj = json.loads(base_ctx.read_text())
    obr = obj['ability_registry']['observable_registry']
    obr['source_sha256'] = field_sha
    if drop_path: obr.pop('source_path_sha256', None)
    p = INPUTS / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return p, jcs_pin(obj)
old_hash = 'a2971c9a293701ae588053b88dffe817d450db45dc1d16527ccdf8b0ab1a26d6'
p_old, pin_old = ctx_source(old_hash, True, 'ctx_old_path_pin.json')
rows.append(gate(prop_s, str(p_old), pin_old, label='T7_old_path_pin_rejected'))
rows.append(gate(prop_s, ctx_s, base_pin, env_extra={'AWZ_OBSERVATION_PATH': str(drift)}, label='T8_source_content_drift'))
rows.append(gate(prop_s, ctx_s, base_pin, env_extra={'AWZ_OBSERVATION_PATH': '/tmp/b7r6-envsrc/does_not_exist.json'}, label='T9_source_unavailable'))
# 关来源守卫副本（真实漏检）
sg_old = ("        # 运行时漂移校验：AWZ 观察文件必须存在且可读；缺失/不可读/内容漂移一律 fail-closed。\n"
          "        import os as _os\n"
          "        awz_env = _os.environ.get('AWZ_OBSERVATION_PATH')\n"
          "        awz_obs_path = Path(awz_env) if awz_env else Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')\n"
          "        if not awz_obs_path.is_file():\n"
          "            p.append('context_observable_source_unavailable')\n"
          "        else:\n"
          "            try:\n"
          "                actual = sha(awz_obs_path.read_bytes())\n"
          "            except Exception:\n"
          "                actual = None\n"
          "                p.append('context_observable_source_unreadable')\n"
          "            if actual is not None and actual != OBSERVABLE_SOURCE_CONTENT_SHA256:\n"
          "                p.append('context_observable_source_content_drift')\n")
assert sg_old in src, 'source guard anchor missing'
sg_off = src.replace(sg_old, '        pass  # B7-r6 对照：关运行时来源内容守卫\n')
sg_p = CAND / 'check_skill_proposal_sourceguard_off.py'
sg_p.write_text(sg_off, encoding='utf-8')
variant_sha['sourceguard_off'] = {'path': str(sg_p), 'sha256': sha(sg_off.encode())}
rows.append(run('T10_source_guard_off_drift_accepted',
                [PY, '-B', str(sg_p), 'gate', '--proposal', prop_s, '--context', ctx_s,
                 '--expected-context-sha256', base_pin],
                env_extra={'AWZ_OBSERVATION_PATH': str(drift)}))

# 5) 动态事实：AWZ 内容哈希 == 常量；合法上下文内容 pin/迁移字段
summary = {
    'awz_file_sha256': awz_sha,
    'checker_content_constant': ck.OBSERVABLE_SOURCE_CONTENT_SHA256,
    'checker_path_constant': ck.OBSERVABLE_SOURCE_PATH_SHA256,
    'content_constant_matches_file': awz_sha == ck.OBSERVABLE_SOURCE_CONTENT_SHA256,
    'legacy_path_hash': old_hash,
    'context_has_migration_fields': sorted(set(['source_sha256', 'source_path_sha256', 'source_sha256_migration']) & set(ctx_obj['ability_registry']['observable_registry'])),
    'gate_variant_sha': variant_sha,
    'rows': rows,
}
(EV / 'gate_results.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(json.dumps({k: summary[k] for k in ('awz_file_sha256', 'checker_content_constant', 'content_constant_matches_file', 'context_has_migration_fields')}, ensure_ascii=False, indent=1))
print('rows:', len(rows))
for r in rows:
    p = r.get('parsed') or {}
    print('%-42s rc=%d tb=%s err=%-22s reason=%s' % (r['label'], r['rc'], r['traceback'],
          (p.get('errors') or [''])[0][:22] if p.get('errors') else '', p.get('reason_code')))
