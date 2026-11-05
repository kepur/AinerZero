"""B8 独立复核公共库（非 B7 作者自写，不复用作者 oracle）。

提供：
- sha() / sha_bytes()：原始字节 sha256
- jcs() / jcs_sha()：独立实现 RFC 8785 规范化 JSON（JS Number::toString + UTF-16 码元键排序）
- load_json()：可选的重复键检测（independent 实现，与候选的 _dup_guard 无关）
- tree_manifest()：目录树逐文件 raw sha256 / size / mtime_ns
- run()：子进程执行并记录 argv/env/rc/stdout/stderr/时长
- append_log()：JSONL 事件日志
- py_identity()：解释器/依赖/环境身份

只读被验对象；本文件只被复核脚本导入。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
AWZ = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero')
HERE = Path(__file__).resolve().parents[1]          # reports/V-V9-B1/r5-independent
RESULTS = HERE / 'results'
LOGS = RESULTS / 'logs'
AWZ_OBSERVATION = AWZ / 'contracts/v9/observation_packet.v1_1.schema.json'
PY = '/usr/local/bin/python3'                        # 本机唯一带 jsonschema 的解释器（见 report 身份节）
# 被验候选目录可用环境变量切换（B8 复核 r5-candidate；B7 v1 的 r6 复核可复用同一 harness）
CAND_DIR = Path(os.environ.get('B8_CAND_DIR', str(ROOT / 'reports/V9-B1/r5-candidate')))
CAND = CAND_DIR / 'check_skill_proposal.py'
R4_DIR = ROOT / 'reports/V9-B1'
R4 = R4_DIR / 'check_skill_proposal.py'

MAX_SAFE_INT = 2 ** 53 - 1


# ---------------------------------------------------------------- identity

def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def py_identity():
    ident = {
        'harness_python': sys.executable,
        'harness_version': sys.version.split()[0],
        'platform': platform.platform(),
        'agent': 'deepseek-h7m2',
        'task': 'ainerzero.V9.B8',
        'cwd': os.getcwd(),
    }
    try:
        import importlib.metadata as md
        ident['jsonschema'] = md.version('jsonschema')
    except Exception as exc:  # pragma: no cover
        ident['jsonschema'] = 'unavailable:' + type(exc).__name__
    ident['checked_python'] = PY
    ident['checked_python_real'] = str(Path(PY).resolve())
    return ident


# ---------------------------------------------------------------- JCS (RFC 8785)

_ESC = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _jcs_str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch in _ESC:
            out.append(_ESC[ch])
        elif o < 0x20:
            out.append('\\u%04x' % o)
        elif 0xD800 <= o <= 0xDFFF:
            raise ValueError('jcs_lone_surrogate')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _es6_number(x) -> str:
    if isinstance(x, bool):
        raise TypeError('jcs_bool')
    if isinstance(x, int):
        if abs(x) > MAX_SAFE_INT:
            raise ValueError('jcs_integer_out_of_range')
        return str(x)
    if not isinstance(x, float):
        raise TypeError('jcs_number_type:' + type(x).__name__)
    import math
    if not math.isfinite(x):
        raise ValueError('jcs_non_finite')
    if x == 0:
        return '0'
    neg = x < 0
    _, digits, exp = Decimal(repr(abs(x))).as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    s = ''.join(map(str, digits))
    k, n = len(s), len(s) + exp
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
        out.append(_jcs_str(o))
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
        for i, k in enumerate(sorted(o, key=lambda s: s.encode('utf-16-be'))):
            if i:
                out.append(',')
            out.append(_jcs_str(k))
            out.append(':')
            _jcs_into(o[k], out)
        out.append('}')
    else:
        raise TypeError('jcs_unsupported:' + type(o).__name__)


def jcs(obj) -> bytes:
    out = []
    _jcs_into(obj, out)
    return ''.join(out).encode('utf-8')


def jcs_sha(obj) -> str:
    return sha_bytes(jcs(obj))


# ---------------------------------------------------------------- JSON IO

def _dup_hook(items):
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
    return json.loads(text, object_pairs_hook=_dup_hook if strict else None,
                      parse_constant=_no_constants)


def write_json(path, obj, *, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + '\n', encoding='utf-8')


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


# ---------------------------------------------------------------- tree manifest

def tree_manifest(base, *, rel_to=ROOT):
    base = Path(base)
    out = {}
    files = [base] if base.is_file() else sorted(p for p in base.rglob('*') if p.is_file())
    for p in files:
        st = p.stat()
        try:
            rel = str(p.relative_to(rel_to))
        except ValueError:
            rel = str(p)
        out[rel] = {'sha256': sha(p), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    return out


# ---------------------------------------------------------------- subprocess

def run(argv, *, cwd=None, env_extra=None, timeout=1800):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        r = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                           cwd=str(cwd) if cwd else None, env=env, timeout=timeout)
        rec = {'argv': [str(a) for a in argv], 'cwd': str(cwd) if cwd else None,
               'env_extra': env_extra or {}, 'rc': r.returncode,
               'stdout': r.stdout, 'stderr': r.stderr,
               'duration_s': round(time.time() - t0, 3), 'timeout': False}
    except subprocess.TimeoutExpired as exc:
        rec = {'argv': [str(a) for a in argv], 'cwd': str(cwd) if cwd else None,
               'env_extra': env_extra or {}, 'rc': None,
               'stdout': (exc.stdout or b'').decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''),
               'stderr': (exc.stderr or b'').decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else (exc.stderr or ''),
               'duration_s': round(time.time() - t0, 3), 'timeout': True}
    return rec


def json_of(rec):
    """从 rc 记录里取 stdout 的 JSON；解析失败返回 None。"""
    try:
        return json.loads(rec['stdout'])
    except Exception:
        return None


# ---------------------------------------------------------------- logging

class RunLog:
    """一个复核阶段的事件日志：JSONL + 汇总。"""

    def __init__(self, name):
        self.name = name
        stamp = time.strftime('%Y%m%dT%H%M%S')
        self.path = LOGS / ('%s-%s.jsonl' % (name, stamp))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def add(self, kind, **payload):
        row = {'t': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'kind': kind, **payload}
        self.rows.append(row)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return row

    def run_case(self, label, argv, *, want=None, cwd=None, env_extra=None, timeout=1800):
        rec = run(argv, cwd=cwd, env_extra=env_extra, timeout=timeout)
        rec['label'] = label
        self.add('run', label=label, **rec)
        return rec

    def save_summary(self, summary):
        path = RESULTS / (self.name + '-summary.json')
        write_json(path, summary)
        return path


def arg_parser(desc):
    import argparse
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument('--out', default=None)
    return ap
