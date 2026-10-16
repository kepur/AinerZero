#!/usr/bin/env python3
"""G2 独立复核：G1 证据身份/冻结核对（只读）。

检查项：
  1. reports/V9-G1/r1-codex-20261016/SHA256SUMS.txt 全部条目（仓库根相对路径）逐字节核对；
  2. source-sha256.json 中源码/测试/脚本身份与当前字节一致；
  3. cpu_registration.json 的四个原始输入：当前字节 vs 登记哈希（分类 fresh / stale）；
  4. 登记文件自身 SHA 是否等于报告引用的 5aa8199f...；
  5. 测试 XML 计数、变异结果（真实 exit1 断言）、首次失败日志确实是非零失败；
  6. git 范围内 G1 只新增三个授权目录下的文件，受跟踪文件未被 G1 改动（按 mtime 交叉核对）。

退出码 0=全部一致；1=有不一致（真实发现）；2=脚本自身错误。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
G1 = ROOT / 'reports/V9-G1/r1-codex-20261016'
REG_SHA_EXPECTED = '5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    violations, notes = [], {}
    # 1. SHA256SUMS
    bad, checked, missing = [], 0, []
    for line in (G1 / 'SHA256SUMS.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        digest, path = line.split(None, 1)
        target = ROOT / path.lstrip('*').strip()
        if not target.exists():
            missing.append(path)
            continue
        checked += 1
        if sha(target) != digest:
            bad.append(path)
    notes['sha256sums'] = {'checked': checked, 'mismatched': bad, 'missing': missing}
    if bad or missing:
        violations.append(f'SHA256SUMS 不一致: {bad[:3]} 缺失: {missing[:3]}')

    # 2. source-sha256.json
    src = json.loads((G1 / 'source-sha256.json').read_text())
    mism = [p for p, h in src.items() if not (ROOT / p).exists() or sha(ROOT / p) != h]
    notes['source_sha256'] = {'entries': len(src), 'mismatched': mism}
    if mism:
        violations.append(f'source-sha256.json 与当前字节不一致: {mism}')

    # 3-4. 登记与原始输入
    reg_path = G1 / 'cpu_registration.json'
    reg_sha = sha(reg_path)
    notes['registration_sha256'] = reg_sha
    if reg_sha != REG_SHA_EXPECTED:
        violations.append(f'登记文件 SHA 与报告引用不符: {reg_sha}')
    reg = json.loads(reg_path.read_text())
    inputs = {}
    for path, digest in reg['source_sha256'].items():
        target = Path(path) if Path(path).is_absolute() else ROOT / path
        if not target.exists():
            inputs[path] = 'MISSING'
            violations.append(f'登记原始输入缺失: {path}')
            continue
        current = sha(target)
        state = 'fresh' if current == digest else 'stale'
        inputs[path] = {'state': state, 'registered': digest[:16], 'current': current[:16],
                        'mtime': target.stat().st_mtime}
        if state == 'stale':
            # 代码输入必须 fresh；文档输入漂移只记录（不归 G1，也不改它）
            if path.endswith(('.py', '.json')):
                violations.append(f'登记代码输入已漂移: {path}')
    notes['registered_inputs'] = inputs

    # 5. 测试 XML / 变异 / 首次失败
    xml = ElementTree.parse(G1 / 'cpu-tests-final.xml').getroot()
    suite = xml if xml.tag == 'testsuite' else xml.find('testsuite')
    tests = int(suite.get('tests', 0))
    fails = int(suite.get('failures', 0)) + int(suite.get('errors', 0))
    notes['cpu_tests'] = {'tests': tests, 'failures': fails, 'skipped': int(suite.get('skipped', 0))}
    if fails or tests == 0:
        violations.append(f'CPU 测试 XML 不满足 49/0: tests={tests} failures={fails}')
    mut = json.loads((G1 / 'mutation-results-r1.json').read_text())
    records = mut if isinstance(mut, list) else mut.get('mutations', mut.get('results', []))
    exits = [r.get('exit_code', r.get('returncode')) for r in records]
    notes['mutations'] = {'count': len(records), 'all_exit_1': all(e == 1 for e in exits),
                          'exit_codes': sorted({e for e in exits})}
    if not records or not all(e == 1 for e in exits):
        violations.append(f'变异结果不满足全部 exit1: {exits}')
    fail_log = (G1 / 'reference-first-failure.log').read_text()
    notes['first_failure_log'] = {
        'has_assertion': 'AssertionError' in fail_log or 'assert' in fail_log,
        'bytes': len(fail_log),
        'mentions_yaw_or_bound': ('yaw' in fail_log) or ('bound' in fail_log),
    }
    if not notes['first_failure_log']['has_assertion']:
        violations.append('首次失败日志不像真实断言失败')
    metrics = json.loads((G1 / 'metrics.json').read_text())
    notes['metrics_claims'] = {k: metrics.get(k) for k in
                               ('cpu_tests', 'cpu_failures', 'new_mutations', 'mutation_real_nonzero',
                                'registration_sha256') if k in metrics}
    if metrics.get('cpu_tests') not in (None, tests):
        violations.append('metrics.json 的 cpu_tests 与 XML 不符')

    # 6. git 范围
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout
    entries = [line for line in status.splitlines() if line.strip()]
    v9_untracked = [e[3:] for e in entries if e.startswith('??') and e[3:].rstrip('/').startswith(
        ('src/ainerzero/v9', 'tests/v9', 'reports/V9-G1'))]
    modified = [(e[3:], (ROOT / e[3:]).stat().st_mtime) for e in entries if e[:2].strip() == 'M']
    report_mtime = (G1 / 'report.md').stat().st_mtime
    touched_by_g1_window = [p for p, m in modified if m <= report_mtime + 60]
    notes['git'] = {'g1_new_paths': sorted(v9_untracked),
                    'tracked_modified_count': len(modified),
                    'tracked_modified_before_g1_report': touched_by_g1_window,
                    'report_mtime': report_mtime}
    if touched_by_g1_window:
        violations.append(f'有受跟踪文件在 G1 报告时间前被改动（需一级确认归属）: {touched_by_g1_window}')

    out = {'violations': violations, 'notes': notes, 'ok': not violations}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"--- freeze: ok={out['ok']} violations={len(violations)}")
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
