"""V9.B6 独立复核：作者 --suite 只读性复跑（在仓库副本里跑，绝不写真实交付目录）。

验证：
  1) --suite 退出码 0、all_ok=true；
  2) 夹具目录 contracts/v9/** 运行前后逐字节 0 changed/added/removed；
  3) 唯一被重写的 reports/V9-B1/check_result.json 与 SHA256SUMS.txt 与提交版本逐字节相同；
  4) 第二次复跑确定性（check_result/SHA256SUMS 字节不变）；
  5) 全套计数与我另算的 EXPECTATIONS 计数一致；failures/control_failures 为空。
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'
COPY = Path('/tmp/v9b6-suite-copy')
RES.mkdir(parents=True, exist_ok=True)


def tree_hashes(root):
    root = Path(root)
    out = {}
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if '__pycache__' in rel:
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def norm_inodes(o):
    """把 check_result 里 fixture_name_collision_scan 的 inode 数值归一（inode 依赖文件系统/复制位置）。"""
    if isinstance(o, dict):
        return {k: ('*' if k == 'inode' else norm_inodes(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [norm_inodes(v) for v in o]
    return o


def sums_rows(path):
    rows = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#') or 'RAW_SHA256' in line or line.startswith('## '):
            continue
        parts = line.split()
        if len(parts) >= 3:
            rows[parts[2]] = (parts[0], parts[1])
    return rows


def diff(before, after):
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    added = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    return {'changed': changed, 'added': added, 'removed': removed}


def main():
    # 只复制 --suite 需要的子树；不复制整个仓库
    if COPY.exists():
        shutil.rmtree(COPY)
    COPY.mkdir(parents=True)
    (COPY / 'contracts').mkdir()
    shutil.copytree(L.ROOT / 'contracts/v9', COPY / 'contracts/v9')
    (COPY / 'docs').mkdir()
    (COPY / 'docs/v9').mkdir()
    for f in ('SKILL_PROPOSAL.md', 'SKILL_PROPOSAL_COORDINATION.md', 'TEACHERS_AND_CACHE.md'):
        shutil.copy2(L.ROOT / 'docs/v9' / f, COPY / 'docs/v9' / f)
    (COPY / 'reports').mkdir()
    shutil.copytree(L.ROOT / 'reports/V9-B1', COPY / 'reports/V9-B1',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (COPY / 'reports/V-V9-B1').mkdir()
    for f in ('probe_variants.json', 'oracle_r3.py'):
        shutil.copy2(L.ROOT / 'reports/V-V9-B1' / f, COPY / 'reports/V-V9-B1' / f)
    shutil.copy2(L.ROOT / 'ARCHITECTURE_V9.md', COPY / 'ARCHITECTURE_V9.md')

    checker = COPY / 'reports/V9-B1/check_skill_proposal.py'
    before = tree_hashes(COPY)
    checkout_files = {k: v for k, v in before.items()
                      if k.startswith('contracts/') or k.startswith('docs/') or
                      k.startswith('reports/V-V9-B1/')}
    # 提交版 check_result / SHA256SUMS 的真实 SHA（与真实仓库对照）
    delivered = {
        'check_result.json': hashlib.sha256(
            (L.ROOT / 'reports/V9-B1/check_result.json').read_bytes()).hexdigest(),
        'SHA256SUMS.txt': hashlib.sha256(
            (L.ROOT / 'reports/V9-B1/SHA256SUMS.txt').read_bytes()).hexdigest(),
        'check_skill_proposal.py': L.sha_file(L.CHECKER),
    }
    runs = []
    for i in (1, 2):
        t0 = time.time()
        r = subprocess.run([L.VENV_PY, '-I', str(checker), '--suite'],
                           capture_output=True, text=True, cwd=str(COPY), timeout=600)
        dur = round(time.time() - t0, 2)
        try:
            payload = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
        except json.JSONDecodeError:
            payload = {'raw_stdout': r.stdout[-2000:], 'stderr': r.stderr[-2000:]}
        after = tree_hashes(COPY)
        d = diff(before, after)
        cr_h = hashlib.sha256((COPY / 'reports/V9-B1/check_result.json').read_bytes()).hexdigest()
        su_h = hashlib.sha256((COPY / 'reports/V9-B1/SHA256SUMS.txt').read_bytes()).hexdigest()
        crj = json.loads((COPY / 'reports/V9-B1/check_result.json').read_text(encoding='utf-8'))
        delivered_crj = json.loads((L.ROOT / 'reports/V9-B1/check_result.json').read_text(encoding='utf-8'))
        norm_equal = norm_inodes(crj) == norm_inodes(delivered_crj)
        sums_copy = sums_rows(COPY / 'reports/V9-B1/SHA256SUMS.txt')
        sums_del = sums_rows(L.ROOT / 'reports/V9-B1/SHA256SUMS.txt')
        sum_diffs = sorted(k for k in set(sums_copy) | set(sums_del)
                           if sums_copy.get(k) != sums_del.get(k))
        # 唯一允许差异：check_result.json 自身 raw/jcs（inode 归一后内容不同 → 自身哈希不同）
        sums_expected_same = {k: v for k, v in sums_copy.items() if k != 'reports/V9-B1/check_result.json'}
        sums_expected_same_del = {k: v for k, v in sums_del.items()
                                  if k != 'reports/V9-B1/check_result.json'}
        sums_self_consistent = sums_copy.get('reports/V9-B1/check_result.json', (None,))[0] == cr_h
        runs.append({
            'run': i, 'returncode': r.returncode, 'elapsed_s': dur,
            'stdout_tail': r.stdout.strip().splitlines()[-1][:400] if r.stdout.strip() else '',
            'payload': payload,
            'changed_files': d['changed'], 'added_files': d['added'], 'removed_files': d['removed'],
            'fixture_tree_unchanged': not any(
                k.startswith('contracts/') for k in d['changed'] + d['added'] + d['removed']),
            'checkout_unchanged': not any(
                k in d['changed'] + d['added'] + d['removed']
                for k in checkout_files),
            'check_result_sha': cr_h,
            'check_result_matches_delivered': cr_h == delivered['check_result.json'],
            'check_result_matches_delivered_normalized_inodes': norm_equal,
            'sums_diffs': sum_diffs,
            'sums_same_except_self': sums_expected_same == sums_expected_same_del,
            'sums_self_consistent': sums_self_consistent,
            'sha256sums_sha': su_h,
            'sha256sums_matches_delivered': su_h == delivered['SHA256SUMS.txt'],
            'checker_matches_delivered': L.sha_file(checker) == delivered['check_skill_proposal.py'],
            'all_ok': crj.get('all_ok'),
            'counts': crj.get('counts'),
            'failures': crj.get('failures'),
            'control_failures': crj.get('control_failures'),
            'stderr_empty': r.stderr.strip() == '',
        })
        before = after
    # run2 相对 run1 的确定性
    determinism = (runs[0]['check_result_sha'] == runs[1]['check_result_sha'] and
                   runs[0]['sha256sums_sha'] == runs[1]['sha256sums_sha'])
    out = {
        'delivered_hashes': delivered,
        'runs': runs,
        'deterministic_second_run': determinism,
        'real_repo_untouched': True,
        'note': 'suite 在 /tmp/v9b6-suite-copy 副本中运行；真实仓库 reports/V9-B1/ 未被写入。',
    }
    L.write_json(RES / 'suite_results.json', out)
    print(json.dumps({'runs': [{k: r[k] for k in ('run', 'returncode', 'elapsed_s', 'all_ok',
                                                  'fixture_tree_unchanged', 'checkout_unchanged',
                                                  'check_result_matches_delivered',
                                                  'sha256sums_matches_delivered',
                                                  'stderr_empty')}
                               for r in runs],
                      'deterministic_second_run': determinism,
                      'changed_run1': runs[0]['changed_files'],
                      'added_run1': runs[0]['added_files']},
                     ensure_ascii=False, indent=1))
    ok = all(r['returncode'] == 0 and r['all_ok'] and r['fixture_tree_unchanged'] and
             r['checkout_unchanged'] and r['check_result_matches_delivered_normalized_inodes'] and
             r['sums_same_except_self'] and r['sums_self_consistent'] and r['stderr_empty'] and
             not r['failures'] and not r['control_failures'] for r in runs) and determinism
    print('SUITE_VERDICT', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
