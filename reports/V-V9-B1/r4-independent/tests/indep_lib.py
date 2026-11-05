"""V9.B6 独立复核用公共库：自写 JCS + 自写键名判定 + 加载/子进程工具。

独立性声明：本文件不 import reports/V9-B1/check_skill_proposal.py，也不 import
reports/V-V9-B1/oracle_r3.py；JCS 与键名判定均按 RFC 8785 / 裁决 2 / B4-r4-DECISIONS F1/F3
的公开条文另写。被验实现只作为被测对象，不作为判据。
"""
import hashlib
import json
import math
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
FIXTURE = ROOT / 'contracts/v9/examples/skill_proposal_v1'
AWZ = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero')
VENV_PY = '/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python'
CHECKER = ROOT / 'reports/V9-B1/check_skill_proposal.py'
DEVNULL = subprocess.DEVNULL


# ---------------------------------------------------------------- JCS (RFC 8785) 自写
class JcsError(ValueError):
    pass


_ESC = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _jcs_str(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    # 编码校验：孤立代理项在这里失败（JCS 要求 UTF-8 可表示）
    ''.join(out).encode('utf-8')
    return ''.join(out)


def _num_tokens(x, neg, tok):
    """把最短十进制串 tok 按 ECMAScript Number::toString 格式化。"""
    t = tok.lower()
    if 'e' in t:
        mant, exp = t.split('e')
        exp = int(exp)
    else:
        mant, exp = t, 0
    if '.' in mant:
        ip, fp = mant.split('.')
    else:
        ip, fp = mant, ''
    digits = (ip + fp).lstrip('0')
    if digits == '':
        return '0'
    # 小数点在 digits 内的位置
    n = len(ip.lstrip('0')) if ip.lstrip('0') else -(len(fp) - len(fp.lstrip('0')))
    # 上面 n 不可靠；直接由数值定位：value = digits * 10^scale
    scale = exp - len(fp)
    digits = digits.rstrip('0')
    scale += 0
    k = len(digits)
    n = k + scale
    if k <= n <= 21:
        body = digits + '0' * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + '.' + digits[n:]
    elif -6 < n <= 0:
        body = '0.' + '0' * (-n) + digits
    else:
        e = n - 1
        body = digits[0] + ('.' + digits[1:] if k > 1 else '')
        body += 'e' + ('+' if e >= 0 else '-') + str(abs(e))
    return ('-' + body) if neg else body


def _es6_number(x):
    if isinstance(x, bool):
        raise JcsError('bool_as_number')
    if isinstance(x, int):
        if abs(x) > 2 ** 53 - 1:
            raise JcsError('int_out_of_range')
        return str(x)
    if not isinstance(x, float) or not math.isfinite(x):
        raise JcsError('non_finite')
    if x == 0:
        return '0'
    neg = x < 0
    tok = repr(abs(x))
    if tok.endswith('.0'):
        tok = tok[:-2]
    return _num_tokens(x, neg, tok)


def jcs(o):
    """RFC 8785 规范 JSON 字符串（UTF-8 bytes）。"""
    out = []
    _jcs_into(o, out)
    return ''.join(out).encode('utf-8')


def _jcs_into(o, out):
    if o is None:
        out.append('null')
    elif o is True:
        out.append('true')
    elif o is False:
        out.append('false')
    elif isinstance(o, str):
        out.append(_jcs_str(o))
    elif isinstance(o, int):
        out.append(_es6_number(o))
    elif isinstance(o, float):
        out.append(_es6_number(o))
    elif isinstance(o, list):
        out.append('[')
        for i, v in enumerate(o):
            if i:
                out.append(',')
            _jcs_into(v, out)
        out.append(']')
    elif isinstance(o, dict):
        # RFC 8785：按 UTF-16 码元排序
        items = sorted(o.items(), key=lambda kv: str(kv[0]).encode('utf-16-be'))
        out.append('{')
        for i, (k, v) in enumerate(items):
            if not isinstance(k, str):
                raise JcsError('non_string_key')
            if i:
                out.append(',')
            out.append(_jcs_str(k))
            out.append(':')
            _jcs_into(v, out)
        out.append('}')
    else:
        raise JcsError('unsupported_type:' + type(o).__name__)


def jcs_sha(o):
    return hashlib.sha256(jcs(o)).hexdigest()


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def load_json_strict(path):
    """读 JSON，拒绝重复键；NaN/Inf 由 parse_constant 拒绝。"""
    def pairs(items):
        seen = set()
        for k, _ in items:
            if k in seen:
                raise JcsError('duplicate_key:' + str(k))
            seen.add(k)
        return dict(items)

    def bad_const(x):
        raise JcsError('non_finite_literal:' + x)

    return json.loads(Path(path).read_text(encoding='utf-8'),
                      object_pairs_hook=pairs, parse_constant=bad_const)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- 键名规范化判定（自写）
FAMILY_STEMS = ['world', 'entity', 'scene', 'event', 'instance', 'landmark', 'object', 'actor',
                'agent', 'truth', 'hidden']
FAMILY_PLURALS = {'world': ['worlds', 'world'], 'entity': ['entities', 'entity'],
                  'scene': ['scenes', 'scene'], 'event': ['events', 'event'],
                  'instance': ['instances', 'instance'], 'landmark': ['landmarks', 'landmark'],
                  'object': ['objects', 'object'], 'actor': ['actors', 'actor'],
                  'agent': ['agents', 'agent'], 'truth': ['truths', 'truth'],
                  'hidden': ['hiddens', 'hidden']}
FAMILY_FORMS = sorted({f for stem in FAMILY_STEMS for f in FAMILY_PLURALS[stem]}, key=len,
                      reverse=True)
ID_TOKENS = ['identifiers', 'identifier', 'ids', 'idx', 'id']            # 长在前
PREFIX_TOKENS = ['gt', 'raw', 'my', 'src']
AFFIX_TOKENS = ['values', 'value', 'maps', 'map', 'lists', 'list', 'sets', 'set', 'refs', 'ref',
                'tables', 'table', 'dicts', 'dict', 'arrays', 'array', 'vectors', 'vector']
BARE_ID = {'id', 'ids', 'idx', 'identifier', 'identifiers'}


def norm_key(k):
    return ''.join(ch for ch in str(k).lower() if ch.isalnum())


def _strip_prefixes(s):
    changed = True
    while changed:
        changed = False
        for p in PREFIX_TOKENS:
            if s.startswith(p) and len(s) > len(p):
                s = s[len(p):]
                changed = True
                break
    return s


def _strip_affixes(s):
    changed = True
    while changed:
        changed = False
        for a in AFFIX_TOKENS:
            if s.endswith(a) and len(s) > len(a):
                s = s[:len(s) - len(a)]
                changed = True
                break
    return s


def _family_id_split(s):
    """s 是否恰为 族形式+id词元 或 id词元+族形式。"""
    for fam in FAMILY_FORMS:
        for ids in ID_TOKENS:
            if s == fam + ids or s == ids + fam:
                return True
    return False


def _contact_form(s):
    if s in ('hiddencontact', 'hiddencontacts', 'hiddencontacts'):
        return True
    for ids in ID_TOKENS:
        if s == 'contact' + ids or s == 'contacts' + ids or s == 'hidden' + ids:
            return True
    return False


def is_ident_key_indep(k):
    """独立版裁决 2 键名判定：返回 True 表示世界侧标识键名（应拒）。"""
    s = norm_key(k)
    if not s:
        return False
    if s in BARE_ID:
        return True
    if _contact_form(s):
        return True
    cand = _strip_affixes(_strip_prefixes(s))
    if _family_id_split(cand):
        return True
    # id 词元前缀形式（id_world / ids_object）
    for ids in ID_TOKENS:
        if s.startswith(ids) and _family_id_split(s[len(ids):]):
            return True
    # 前后缀同时存在（gtWorldIdMap）
    if cand != s and _family_id_split(cand):
        return True
    # 族形式后跟 id 词元再跟任意尾部（保守：已在规范里声明的尾缀已剥离，其余不扩）
    return False


# ---------------------------------------------------------------- 子进程运行门禁
def run_cli(args, timeout=120):
    r = subprocess.run([VENV_PY, '-I', str(CHECKER)] + args,
                       capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    try:
        payload = json.loads(r.stdout)
        exc = False
    except json.JSONDecodeError:
        payload = None
        exc = True
    return {'argv': [str(a) for a in args], 'returncode': r.returncode, 'stdout': r.stdout,
            'stderr': r.stderr, 'payload': payload, 'json_parse_exception': exc}


def gate_args(proposal, context, pin, extra=()):
    return ['gate', '--proposal', str(proposal), '--context', str(context),
            '--expected-context-sha256', pin] + list(extra)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, indent=1)
    try:
        raw.encode('utf-8')
    except UnicodeEncodeError:      # 孤立代理项反例：按 \udXXX 转义写盘，读回仍是同一代理项
        raw = json.dumps(obj, ensure_ascii=True, indent=1)
    path.write_text(raw, encoding='utf-8')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        vectors = [
            ({}, '{}'),
            ([], '[]'),
            (None, 'null'),
            (True, 'true'),
            ({'b': 1, 'a': 2}, '{"a":2,"b":1}'),
            ({'a': '\u0007\u000b\u001f'}, '{"a":"\\u0007\\u000b\\u001f"}'),
            ({'a': '\b\f\n\r\t'}, '{"a":"\\b\\f\\n\\r\\t"}'),
            ({'a': 'é中😀'}, '{"a":"é中😀"}'),
            (1.5, '1.5'), (-0.0, '0'), (1e21, '1e+21'), (1e20, '100000000000000000000'),
            (1e-6, '0.000001'), (1e-7, '1e-7'), (333333333.33333329, '333333333.3333333'),
            (2 ** 53 - 1, '9007199254740991'),
        ]
        bad = []
        for obj, want in vectors:
            try:
                got = jcs(obj).decode('utf-8')
            except Exception as e:  # pragma: no cover
                got = 'EXC:' + type(e).__name__
            if got != want:
                bad.append({'obj': repr(obj), 'want': want, 'got': got})
        for obj in (2 ** 53, float('nan'), float('inf'), {1: 'x'}, 123456789012345678901):
            try:
                jcs(obj)
                bad.append({'obj': repr(obj), 'want': 'raise', 'got': 'no_raise'})
            except JcsError:
                pass
        # UTF-16 码元排序：U+FFFF > U+1F600（UTF-16 中 surrogate 0xD83D < 0xFFFF）
        a = {'\uffff': 1, '\U0001f600': 2}
        order = jcs(a).decode('utf-8')
        bad.append({'note': 'utf16_order', 'got': order}) if False else None
        print(json.dumps({'vectors': len(vectors), 'bad': bad,
                          'utf16_parent_keys': order}, ensure_ascii=False))
        return 0 if not bad else 1
    print('usage: indep_lib.py selftest')
    return 2


if __name__ == '__main__':
    sys.exit(main())
