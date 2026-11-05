"""B8 阶段 B：入口重复键 / 非法登记属性名 / 来源漂移，各自独立破坏对照。

原则：
- 不复用作者 verification_logs 的输入；从候选夹具取合法输入，用本脚本自己的文本手术伪造
  重复键字节，用自己的 JCS 实现重算 pin（与作者 EXPECTATIONS 交叉核对，见 crosscheck）。
- 每个守卫做三态对照：候选原脚本（守卫在）→ 期望拒绝；同一候选的"关守卫"副本 → 期望真实漏检
  （accepted，不是异常退出）；原 r4（若该守卫在 r4 不存在/有缺陷）→ 记录其真实行为。
- 所有子进程记录 argv / rc / stdout / stderr / 时长；stderr 是否含 traceback 单独判定。
- 不改候选目录、不改原 r4、不改真实 AWZ；补丁副本只写在 /tmp。
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
CASES = HERE / 'tests' / 'cases'
TMP = Path('/tmp/b8-probe')
PATCH_ROOT = TMP / 'patched'                # /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal.py
PATCHED_CAND = PATCH_ROOT / 'reports/V9-B1/r5-candidate/check_skill_proposal.py'
SRC_DIR = TMP / 'sources'
LOG = L.RunLog('B-entries-source')
R4_FIX = L.ROOT / 'contracts/v9/examples/skill_proposal_v1'

TB = 'Traceback (most recent call last)'


# ---------------------------------------------------------------- prepare

def prep_dirs():
    if TMP.exists():
        shutil.rmtree(TMP)
    for d in (CASES, TMP, SRC_DIR, PATCH_ROOT / 'contracts'):
        d.mkdir(parents=True, exist_ok=True)
    # 补丁副本：镜像根结构，使 ROOT=parents[3] 指向 PATCH_ROOT；schemas 复制（只读）
    shutil.copytree(L.ROOT / 'contracts/v9', PATCH_ROOT / 'contracts/v9')
    for d in (PATCH_ROOT / 'reports/V9-B1/r5-candidate/fixtures',
              PATCH_ROOT / 'reports/V9-B1/r5-candidate/sabotage-schemas'):
        shutil.copytree(L.CAND_DIR / d.relative_to(PATCH_ROOT / 'reports/V9-B1/r5-candidate'), d)
    shutil.copy2(L.CAND, PATCHED_CAND)


def patch_variants():
    """从候选复制生成关守卫副本（每个只改一处守卫），记录替换与结果 SHA。"""
    src = L.CAND.read_text(encoding='utf-8')
    subs = {
        'strict': [
            ('load_json(a.proposal, strict=True)', 'load_json(a.proposal)'),
            ('load_json(a.context, strict=True) if a.context else None', 'load_json(a.context) if a.context else None'),
            ('load_json(a.reply, strict=True)', 'load_json(a.reply)'),
        ],
        'propguard': [
            ("def check_schema_props_forbidden(s, path='param_schema'):\n"
             '    """递归收集 param_schema 里既未支持也不合规的属性名（含 patternProperties 这类动态分支）。"""\n'
             '    out = []',
             "def check_schema_props_forbidden(s, path='param_schema'):\n"
             '    """递归收集 param_schema 里既未支持也不合规的属性名（含 patternProperties 这类动态分支）。"""\n'
             '    return []  # B8 破坏对照：关掉登记属性名守卫\n'
             '    out = []'),
        ],
        'sourceguard': [
            ('        # 运行时漂移校验：AWZ 观察文件必须存在且可读；缺失/不可读/内容漂移一律 fail-closed。\n'
             '        import os as _os\n'
             "        awz_env = _os.environ.get('AWZ_OBSERVATION_PATH')\n"
             "        awz_obs_path = Path(awz_env) if awz_env else Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')\n"
             '        if not awz_obs_path.is_file():\n'
             "            p.append('context_observable_source_unavailable')\n"
             '        else:\n'
             '            try:\n'
             '                actual = sha(awz_obs_path.read_bytes())\n'
             '            except Exception:\n'
             '                actual = None\n'
             "                p.append('context_observable_source_unreadable')\n"
             "            if actual is not None and actual != OBSERVABLE_SOURCE_CONTENT_SHA256:\n"
             "                p.append('context_observable_source_content_drift')",
             '        # B8 破坏对照：关掉运行时来源文件校验\n'
             '        pass'),
        ],
    }
    out = {'base_sha256': L.sha(L.CAND), 'variants': {}}
    for name, pairs in subs.items():
        text = src
        for old, new in pairs:
            if old not in text:
                raise SystemExit('patch anchor missing for %s: %r' % (name, old[:80]))
            text = text.replace(old, new)
        target = PATCH_ROOT / 'reports/V9-B1/r5-candidate' / ('check_skill_proposal_%s.py' % name)
        target.write_text(text, encoding='utf-8')
        out['variants'][name] = {'path': str(target), 'sha256': L.sha(target)}
    # 程序化补丁：在 check_schema_props_forbidden 的 docstring 之后插入 return []
    # （noregpropguard 再把 _schema_keyword_problems 里的登记属性名检查也关掉）。
    def patch_propguard(text, also_keyword):
        rows = text.splitlines(True)
        idx = next(i for i, l in enumerate(rows) if l.startswith('def check_schema_props_forbidden('))
        rows.insert(idx + 2, '    return []  # B8 破坏对照：关掉登记属性名守卫\n')
        if also_keyword:
            j = next(i for i, l in enumerate(rows)
                     if l.rstrip('\n') == '        if is_forbidden_world_id_key(name):'
                     and i + 1 < len(rows) and "here('forbidden_property:" in rows[i + 1])
            rows[j:j + 2] = ['        # B8 破坏对照：关掉关键字遍历里的登记属性名守卫\n']
        return ''.join(rows)

    for name, also in (('propguard', False), ('noregpropguard', True)):
        target = PATCH_ROOT / 'reports/V9-B1/r5-candidate' / ('check_skill_proposal_%s.py' % name)
        target.write_text(patch_propguard(src, also), encoding='utf-8')
        out['variants'][name] = {'path': str(target), 'sha256': L.sha(target)}

    # 独立解释器校验：补丁副本可被正常解析
    for v in out['variants'].values():
        r = L.run([L.PY, '-c', 'import ast,sys; ast.parse(open(sys.argv[1]).read())', v['path']])
        out.setdefault('syntax', {})[Path(v['path']).name] = r['rc'] == 0
    LOG.add('patch-variants', **out)
    return out


def run_script(script, *args, env_extra=None, label=''):
    argv = [L.PY, '-I', str(script), *map(str, args)]
    rec = L.run(argv, env_extra=env_extra)
    rec['label'] = label
    rec['script'] = str(script)
    rec['has_traceback'] = (TB in rec['stderr'])
    parsed = None
    try:
        parsed = json.loads(rec['stdout'])
    except Exception:
        pass
    rec['parsed'] = parsed
    LOG.add('run', **rec)
    return rec


def jwrite(path, obj):
    L.write_json(path, obj)
    return path


def pin_of(path):
    return L.jcs_sha(L.load_json(path))


def prep_base():
    """取候选合法夹具做基线输入（synthetic 冻结上下文）。"""
    ctx = L.load_json(L.CAND_DIR / 'fixtures/contexts/01_valid_minimal_handle_target.json')
    prop = L.load_json(L.CAND_DIR / 'fixtures/valid/01_valid_minimal_handle_target.json')
    reply = L.load_json(L.CAND_DIR / 'fixtures/replies/valid/01_accepted_reply.json')
    f = {}
    f['ctx'] = jwrite(CASES / 'base_context.json', ctx)
    f['prop'] = jwrite(CASES / 'base_proposal.json', prop)
    f['reply'] = jwrite(CASES / 'base_reply.json', reply)
    return ctx, prop, reply, f


def crosscheck_jcs():
    """自写 JCS 与作者 EXPECTATIONS 的 112 个 context pin 交叉核对（验证我的 pin 实现）。"""
    exp = L.load_json(L.CAND_DIR / 'fixtures/EXPECTATIONS.json')
    pins = exp['context_identity_pins']
    ok, bad = 0, []
    for name, want in pins.items():
        p = L.CAND_DIR / 'fixtures/contexts' / (name + '.json')
        if not p.is_file():
            # 由 cases 名单反查 context_file
            continue
        got = L.jcs_sha(L.load_json(p))
        if got == want:
            ok += 1
        else:
            bad.append({'name': name, 'want': want, 'got': got})
    # 用 cases 的 context_file 映射补全
    for row in exp['cases']:
        cf = row.get('context_file')
        if not cf:
            continue
        p = L.CAND_DIR / 'fixtures/contexts' / cf
        want = pins.get(row['name'])
        if p.is_file() and want:
            got = L.jcs_sha(L.load_json(p))
            if got == want:
                ok += 1
            else:
                bad.append({'name': row['name'], 'want': want, 'got': got})
    res = {'pins_compared': ok + len(bad), 'ok': ok, 'mismatch': bad,
           'all_match': not bad and ok >= len(pins)}
    LOG.add('jcs-crosscheck', **res)
    return res


# ---------------------------------------------------------------- text surgery

def canonical_text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + '\n'


def mk_dup_proposal(path, ctx, *, smuggle=False):
    """在合法提案文本里制造重复键。
    - smuggle=False：重复 confidence（同值），标准解析器最后值获胜，语义不变。
    - smuggle=True：重复 params，第一个含禁止的世界 ID 键（world_id），第二个合法；
      标准 json 解析最后值获胜 → 文本里明明有被禁键却会被放过（真实漏检面）。"""
    prop = L.load_json(CASES / 'base_proposal.json')
    text = canonical_text(prop)
    if smuggle:
        anchor = '  "params": {\n    "speed_mps": 1.5\n  },'
        assert anchor in text, 'params anchor not found'
        repl = ('  "params": {\n'
                '    "speed_mps": 1.5,\n'
                '    "world_id": "entity-smuggle-7f3a41c9b2e05d18"\n'
                '  },\n'
                '  "params": {\n'
                '    "speed_mps": 1.5\n'
                '  },')
        text = text.replace(anchor, repl)
    else:
        anchor = '  "confidence": 0.6,'
        assert anchor in text
        text = text.replace(anchor, anchor + '\n' + anchor)
    p = CASES / ('dup_proposal%s.json' % ('_smuggle' if smuggle else ''))
    L.write_text(p, text)
    return p


def mk_dup_context(path):
    ctx = L.load_json(CASES / 'base_context.json')
    text = canonical_text(ctx)
    anchor = '    "current_tick": 850,'
    assert anchor in text, 'current_tick anchor not found'
    text = text.replace(anchor, anchor + '\n' + anchor)
    L.write_text(path, text)
    return path


def mk_dup_reply(path):
    reply = L.load_json(CASES / 'base_reply.json')
    text = canonical_text(reply)
    anchor = '  "reason_code": "accepted",'
    assert anchor in text, 'reason_code anchor not found'
    text = text.replace(anchor, anchor + '\n' + anchor)
    L.write_text(path, text)
    return path


def mk_registry_illegal_context(path, nested=False):
    ctx = L.load_json(CASES / 'base_context.json')
    entry = ctx['ability_registry']['entries'][0]
    if nested:
        entry['param_schema'] = {
            'type': 'object', 'additionalProperties': False, 'required': ['speed_mps'],
            'properties': {
                'speed_mps': {'type': 'number', 'minimum': 0, 'maximum': 3},
                'tags': {'type': 'array', 'items': {
                    'type': 'object', 'additionalProperties': {'type': 'string'},
                    'properties': {'worldId': {'type': 'string'}}}},
            },
        }
    else:
        entry['param_schema']['properties']['world_id'] = {'type': 'string'}
    L.write_json(path, ctx)
    return path


def mk_source_variants():
    """从真实 AWZ 文件只读复制出缺失/不可读/漂移三种来源，不改真实文件。"""
    real = L.AWZ_OBSERVATION
    drift = SRC_DIR / 'observation_packet.drift.json'
    shutil.copy2(real, drift)
    raw = bytearray(drift.read_bytes())
    raw[-2] = raw[-2] ^ 0x01 if raw[-2] != 0x0A else raw[-2]  # 改最后一个非换行字节附近
    # 更稳：直接在结尾追加一个空格，内容 SHA 必变但仍是合法 JSON 文件
    drift.write_bytes(drift.read_bytes() + b' ')
    unread = SRC_DIR / 'observation_packet.unreadable.json'
    shutil.copy2(real, unread)
    unread.chmod(0o000)
    missing = SRC_DIR / 'does-not-exist.json'
    return {'real': real, 'drift': drift, 'unreadable': unread, 'missing': missing}


def gate_argv(script, proposal, context, pin, extra=()):
    return [L.PY, '-I', str(script), 'gate', '--proposal', str(proposal),
            '--context', str(context), '--expected-context-sha256', str(pin), *extra]


def describe(rec):
    p = rec.get('parsed') or {}
    return {'label': rec['label'], 'script': Path(rec['script']).name, 'rc': rec['rc'],
            'decision': p.get('decision'), 'reason_code': p.get('reason_code'),
            'errors': p.get('errors'), 'ok': p.get('ok'),
            'has_traceback': rec['has_traceback'],
            'stderr_tail': rec['stderr'][-200:] if rec['stderr'] else '',
            'stdout_tail': rec['stdout'][-300:] if rec['stdout'] else '',
            'duration_s': rec['duration_s'], 'env_extra': rec['env_extra']}


def expect(rows, label, conds):
    """runs 里存的是 describe() 的摘要行（decision/reason_code/errors/ok 在顶层）。"""
    rec = next(r for r in rows if r['label'] == label)
    fails = []
    for k, want in conds.items():
        if k == 'has_traceback':
            got = rec['has_traceback']
        elif k == 'errors_contain_any':
            got = any(any(w in (e or '') for w in want) for e in (rec.get('errors') or []))
            want = True
        elif k == 'errors_contain_all':
            got = all(any(w in (e or '') for e in (rec.get('errors') or [])) for w in want)
            want = True
        else:
            got = rec.get(k)
        if got != want:
            fails.append((k, want, got))
    return {'label': label, 'ok': not fails, 'fails': fails}


def main():
    prep_dirs()
    patches = patch_variants()
    variants = patches['variants']
    P = {k: v['path'] for k, v in variants.items()}
    ctx0, prop0, reply0, files = prep_base()
    pin0 = pin_of(files['ctx'])
    cross = crosscheck_jcs()
    il = mk_registry_illegal_context(CASES / 'ctx_illegal_property.json', nested=False)
    il_nested = mk_registry_illegal_context(CASES / 'ctx_illegal_property_nested.json', nested=True)
    pin_il = pin_of(il)
    pin_il_nested = pin_of(il_nested)
    # r4 形态：基座换成 r4 的 context fixture（旧 source pin），否则 r4 会先在 context_problems 拒绝
    r4ctx_txt = canonical_text(L.load_json(r4ctx_obj_path := (R4_FIX / 'contexts/01_valid_minimal_handle_target.json')))
    il_r4 = CASES / 'ctx_illegal_property_r4.json'
    il_r4_nested = CASES / 'ctx_illegal_property_r4_nested.json'
    import copy as _copy
    for tag, tgt, nested in (('plain', il_r4, False), ('nested', il_r4_nested, True)):
        c = L.load_json(r4ctx_obj_path)
        e = c['ability_registry']['entries'][0]
        if nested:
            e['param_schema'] = _copy.deepcopy(L.load_json(il_nested)['ability_registry']['entries'][0]['param_schema'])
        else:
            e['param_schema']['properties']['world_id'] = {'type': 'string'}
        L.write_json(tgt, c)
    src = mk_source_variants()
    runs = []

    def R(label, script, proposal, context, pin, extra=(), env_extra=None):
        rec = run_script(script, 'gate', '--proposal', proposal, '--context', context,
                         '--expected-context-sha256', pin, *extra, env_extra=env_extra, label=label)
        runs.append(describe(rec))
        return rec

    # ---------- 基线正例（候选 / r4 各自自己的合法夹具） ----------
    r4ctx = R4_FIX / 'contexts/01_valid_minimal_handle_target.json'
    r4prop = R4_FIX / 'valid/01_valid_minimal_handle_target.json'
    r4pin = pin_of(r4ctx)
    base_cand = R('base-cand', L.CAND, files['prop'], files['ctx'], pin0)
    base_r4 = R('base-r4', L.R4, r4prop, r4ctx, r4pin)
    # 同值重复键三态
    dup_prop = mk_dup_proposal(CASES / 'dup_proposal.json', ctx0, smuggle=False)
    dup_prop_smug = mk_dup_proposal(CASES / 'dup_proposal_smuggle.json', ctx0, smuggle=True)
    for label, script, prop, extra in (
            ('dup-proposal-cand', L.CAND, dup_prop, ()),
            ('dup-proposal-smuggle-cand', L.CAND, dup_prop_smug, ()),
            ('dup-proposal-cand-nostrict', P['strict'], dup_prop, ()),
            ('dup-proposal-smuggle-cand-nostrict', P['strict'], dup_prop_smug, ()),
            ('dup-proposal-r4', L.R4, dup_prop, ()),
            ('dup-proposal-smuggle-r4', L.R4, dup_prop_smug, ())):
        # r4 需要 r4 自己的 context/pin；候选用候选的
        if script == L.R4:
            R(label, script, prop, r4ctx, r4pin)
        else:
            R(label, script, prop, files['ctx'], pin0)
    dup_ctx = mk_dup_context(CASES / 'dup_context.json')
    # r4 形态的上下文（旧 pin）重复键：基座取 r4 自己的 context fixture
    r4ctx_obj = L.load_json(r4ctx)
    r4_text = canonical_text(r4ctx_obj)
    anchor4 = '    "current_tick": 850,'
    assert anchor4 in r4_text
    dup_ctx_r4_p = CASES / 'dup_context_r4.json'
    L.write_text(dup_ctx_r4_p, r4_text.replace(anchor4, anchor4 + '\n' + anchor4))
    for label, script in (('dup-context-cand', L.CAND), ('dup-context-cand-nostrict', P['strict'])):
        R(label, script, files['prop'], dup_ctx, pin_of(dup_ctx))
    R('dup-context-r4', L.R4, r4prop, dup_ctx_r4_p, pin_of(dup_ctx_r4_p))
    dup_reply = mk_dup_reply(CASES / 'dup_reply.json')
    for label, script in (('dup-reply-cand', L.CAND), ('dup-reply-cand-nostrict', P['strict']),
                          ('dup-reply-r4', L.R4)):
        rec = run_script(script, 'reply', '--reply', dup_reply, label=label)
        runs.append(describe(rec))
    # ---------- 非法登记属性名 ----------
    R('registry-illegal-cand', L.CAND, files['prop'], il, pin_il)
    R('registry-illegal-disable-norm-cand', L.CAND, files['prop'], il, pin_il,
      extra=('--disable', 'world_id_normalization'))
    R('registry-illegal-cand-nopropguard', P['propguard'], files['prop'], il, pin_il)
    R('registry-illegal-r4', L.R4, r4prop, il_r4, pin_of(il_r4))
    R('registry-illegal-nested-cand', L.CAND, files['prop'], il_nested, pin_il_nested)
    R('registry-illegal-nested-cand-nopropguard', P['propguard'], files['prop'], il_nested, pin_il_nested)
    R('registry-illegal-cand-noregpropguard', P['noregpropguard'], files['prop'], il, pin_il)
    R('registry-illegal-nested-cand-noregpropguard', P['noregpropguard'], files['prop'], il_nested, pin_il_nested)
    R('registry-illegal-nested-r4', L.R4, r4prop, il_r4_nested, pin_of(il_r4_nested))
    R('registry-legal-cand', L.CAND, files['prop'], files['ctx'], pin0)
    R('registry-legal-r4', L.R4, r4prop, r4ctx, r4pin)
    # ---------- 来源文件：缺失 / 不可读 / 内容漂移（路径字符串不变） ----------
    env_cases = [('source-missing-cand', L.CAND, src['missing']),
                 ('source-unreadable-cand', L.CAND, src['unreadable']),
                 ('source-drift-cand', L.CAND, src['drift']),
                 ('source-missing-cand-nosourceguard', P['sourceguard'], src['missing']),
                 ('source-unreadable-cand-nosourceguard', P['sourceguard'], src['unreadable']),
                 ('source-drift-cand-nosourceguard', P['sourceguard'], src['drift'])]
    for label, script, path in env_cases:
        R(label, script, files['prop'], files['ctx'], pin0,
          env_extra={'AWZ_OBSERVATION_PATH': str(path)})
    # 路径不变、内容漂移：context 里的 source 字符串保持固定契约路径，只让磁盘文件内容变
    R('source-drift-path-unchanged-cand', L.CAND, files['prop'], files['ctx'], pin0,
      env_extra={'AWZ_OBSERVATION_PATH': str(src['drift'])})
    # 旧 r4 形态上下文（source_sha256=路径字符串哈希）在候选/r4 下的行为：不静默迁移 / 旧 fail-open
    oldctx = L.load_json(CASES / 'base_context.json')
    oldctx['ability_registry']['observable_registry'].pop('source_path_sha256', None)
    oldctx['ability_registry']['observable_registry']['source_sha256'] = \
        L.sha_bytes(b'AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')
    old_ctx_p = jwrite(CASES / 'ctx_old_pin.json', oldctx)
    R('source-old-pin-cand', L.CAND, files['prop'], old_ctx_p, pin_of(old_ctx_p))
    R('source-old-pin-r4-env-missing', L.R4, r4prop, r4ctx, r4pin,
      env_extra={'AWZ_OBSERVATION_PATH': str(src['missing'])})
    # source_path_sha256 漂移
    bad_path_ctx = L.load_json(CASES / 'base_context.json')
    bad_path_ctx['ability_registry']['observable_registry']['source_path_sha256'] = '0' * 64
    bad_path_p = jwrite(CASES / 'ctx_bad_path_sha.json', bad_path_ctx)
    R('source-path-sha-drift-cand', L.CAND, files['prop'], bad_path_p, pin_of(bad_path_p))
    # 试图把 context 的 source_sha256 改成漂移文件的内容哈希（不能绕过固定 pin）
    drift_sha = L.sha(src['drift'])
    adv_ctx = L.load_json(CASES / 'base_context.json')
    adv_ctx['ability_registry']['observable_registry']['source_sha256'] = drift_sha
    adv_p = jwrite(CASES / 'ctx_adv_source_sha.json', adv_ctx)
    R('source-adv-ctx-sha-cand', L.CAND, files['prop'], adv_p, pin_of(adv_p),
      env_extra={'AWZ_OBSERVATION_PATH': str(src['drift'])})
    # 环境变量缺失时默认真实 AWZ 路径仍被读（基线正例已覆盖）；额外：env 指向真实文件也应接受
    R('source-env-real-cand', L.CAND, files['prop'], files['ctx'], pin0,
      env_extra={'AWZ_OBSERVATION_PATH': str(src['real'])})
    # 全 disable 组合仍不能绕过来源/登记守卫
    R('source-missing-all-disable-cand', L.CAND, files['prop'], files['ctx'], pin0,
      extra=tuple(sum([['--disable', r] for r in sorted(['schema', 'jcs_fail_closed', 'ability',
                                                          'params', 'evidence', 'ttl', 'budget', 'handle',
                                                          'actor', 'outcome_window'])], [])),
      env_extra={'AWZ_OBSERVATION_PATH': str(src['missing'])})

    # ---------- 断言 ----------
    checks = [
        expect(runs, 'base-cand', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'base-r4', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-proposal-cand', {'rc': 1, 'decision': 'rejected', 'reason_code': 'schema_invalid',
                                           'errors_contain_any': ['proposal_unreadable:ValueError'],
                                           'has_traceback': False}),
        expect(runs, 'dup-proposal-smuggle-cand', {'rc': 1, 'has_traceback': False,
                                                   'errors_contain_any': ['proposal_unreadable:ValueError']}),
        expect(runs, 'dup-proposal-cand-nostrict', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-proposal-smuggle-cand-nostrict', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-proposal-r4', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-proposal-smuggle-r4', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-context-cand', {'rc': 1, 'errors_contain_any': ['context_unreadable:ValueError'],
                                          'has_traceback': False}),
        expect(runs, 'dup-context-cand-nostrict', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-context-r4', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'dup-reply-cand', {'rc': 1, 'errors_contain_any': ['reply_unreadable:ValueError'],
                                        'has_traceback': False}),
        expect(runs, 'dup-reply-cand-nostrict', {'rc': 0, 'has_traceback': False}),
        expect(runs, 'dup-reply-r4', {'rc': 0, 'has_traceback': False}),
        expect(runs, 'registry-illegal-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                               'errors_contain_all': ['entry:abil-approach-object:forbidden_property:world_id']}),
        expect(runs, 'registry-illegal-disable-norm-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                                            'errors_contain_all': ['forbidden_property:world_id']}),
        expect(runs, 'registry-illegal-cand-nopropguard', {'rc': 1, 'decision': None, 'has_traceback': False,
                                                           'errors_contain_all': ['forbidden_property:world_id']}),
        expect(runs, 'registry-illegal-cand-noregpropguard', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'registry-illegal-r4', {'rc': 1, 'has_traceback': False,
                                             'errors_contain_any': ['gate_internal_error:NameError']}),
        expect(runs, 'registry-illegal-nested-cand', {'rc': 1, 'has_traceback': False,
                                                      'errors_contain_all': ['forbidden_property:worldId']}),
        expect(runs, 'registry-illegal-nested-cand-nopropguard', {'rc': 1, 'has_traceback': False,
                                                                  'errors_contain_all': ['forbidden_property:worldId']}),
        expect(runs, 'registry-illegal-nested-cand-noregpropguard', {'rc': 0, 'decision': 'accepted',
                                                                    'has_traceback': False}),
        expect(runs, 'registry-illegal-nested-r4', {'rc': 1, 'has_traceback': False,
                                                    'errors_contain_any': ['gate_internal_error:NameError']}),
        expect(runs, 'registry-legal-cand', {'rc': 0, 'decision': 'accepted'}),
        expect(runs, 'source-missing-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                             'errors_contain_all': ['context_observable_source_unavailable']}),
        expect(runs, 'source-unreadable-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                                'errors_contain_all': ['context_observable_source_unreadable']}),
        expect(runs, 'source-drift-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                           'errors_contain_all': ['context_observable_source_content_drift']}),
        expect(runs, 'source-missing-cand-nosourceguard', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'source-unreadable-cand-nosourceguard', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'source-drift-cand-nosourceguard', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'source-drift-path-unchanged-cand', {'rc': 1, 'has_traceback': False,
                                                          'errors_contain_all': ['context_observable_source_content_drift']}),
        expect(runs, 'source-old-pin-cand', {'rc': 1, 'decision': None, 'has_traceback': False,
                                             'errors_contain_all': ['context_observable_source_sha256']}),
        expect(runs, 'source-old-pin-r4-env-missing', {'rc': 0, 'decision': 'accepted', 'has_traceback': False}),
        expect(runs, 'source-path-sha-drift-cand', {'rc': 1, 'has_traceback': False,
                                                    'errors_contain_all': ['context_observable_source_path_sha256_drift']}),
        expect(runs, 'source-adv-ctx-sha-cand', {'rc': 1, 'has_traceback': False,
                                                 'errors_contain_all': ['context_observable_source_sha256']}),
        expect(runs, 'source-env-real-cand', {'rc': 0, 'decision': 'accepted'}),
        expect(runs, 'source-missing-all-disable-cand', {'rc': 1, 'decision': None,
                                                         'errors_contain_all': ['context_observable_source_unavailable']}),
    ]
    # 清理不可读文件，避免影响后续
    try:
        src['unreadable'].chmod(0o644)
    except OSError:
        pass

    summary = {
        'identity': L.py_identity(),
        'patch_variants': patches,
        'jcs_crosscheck': cross,
        'source_variants': {k: str(v) for k, v in src.items()},
        'drift_source_sha256': L.sha(src['drift']),
        'real_source_sha256': L.sha(src['real']),
        'runs': runs,
        'checks': checks,
        'checks_failed': [c for c in checks if not c['ok']],
        'all_checks_ok': all(c['ok'] for c in checks),
        'note': '共 %d 次 CLI 运行；每个守卫含"候选原脚本 / 关守卫副本 / 原 r4(如适用)"三态。' % len(runs),
    }
    LOG.save_summary(summary)
    print(json.dumps({'runs': len(runs), 'checks': len(checks),
                      'failed': summary['checks_failed'],
                      'jcs_crosscheck': {k: cross[k] for k in ('pins_compared', 'ok', 'all_match')},
                      'patch_variants': {k: v['sha256'] for k, v in patches['variants'].items()},
                      'source_variants': summary['source_variants']}, ensure_ascii=False, indent=1))
    return 0 if summary['all_checks_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
