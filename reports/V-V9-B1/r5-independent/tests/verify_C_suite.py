"""B8 阶段 C：候选 suite 实跑（默认只读 / 显式新输出目录 / 可复现）与 --output-dir 覆盖风险。

C1. 候选 --suite 默认运行（原地、不给 --output-dir）：期望 rc=0/all_ok=true；
    运行前后候选树、原 r4 交付树、contracts/v9、docs/v9 逐字节不变（默认只读）。
C2. 候选 --suite --output-dir <新目录>：写入 check_result.json + SHA256SUMS.txt；
    与作者候选目录里的 check_result.json 逐字节对比；两次输出目录之间对比（确定性）。
C3. 显式 --output-dir 指向"输入/旧交付目录"时是否拒绝：在 /tmp 隔离副本里测
    （a）候选交付目录自身（含 fixtures 输入）；（b）原 r4 交付目录 reports/V9-B1；
    （c）输入夹具目录 fixtures/。逐字节核对被覆盖前后的文件 —— 回答 codex message #167 的问题。
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
SUITE_OUT = HERE / 'results' / 'suite'
TMP = Path('/tmp/b8-outdir')
LOG = L.RunLog('C-suite')


def run_suite(script, *extra, label, cwd=None, env_extra=None):
    argv = [L.PY, '-I', str(script), '--suite', *map(str, extra)]
    rec = L.run(argv, cwd=cwd, env_extra=env_extra, timeout=2400)
    rec['label'] = label
    rec['script'] = str(script)
    parsed = None
    try:
        parsed = json.loads(rec['stdout'])
    except Exception:
        pass
    rec['parsed'] = parsed
    LOG.add('suite-run', **{k: v for k, v in rec.items() if k != 'parsed'})
    return rec


def tree_state(paths):
    st = {}
    for label, base in paths:
        base = Path(base)
        if base.is_file():
            st[label] = {str(base): L.sha(base)}
        elif base.is_dir():
            st[label] = L.tree_manifest(base)
        else:
            st[label] = {}
    return st


def diff_tree(before, after, label):
    b, a = before.get(label, {}), after.get(label, {})
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k]['sha256'] != b[k]['sha256'])
    return {'added': added, 'removed': removed, 'changed': changed,
            'n_before': len(b), 'n_after': len(a),
            'clean': not added and not removed and not changed}


def main():
    SUITE_OUT.mkdir(parents=True, exist_ok=True)
    watched = [('candidate', L.CAND_DIR), ('r4', L.R4_DIR),
               ('contracts_v9', L.ROOT / 'contracts/v9'), ('docs_v9', L.ROOT / 'docs/v9')]
    # r4 树里排除候选目录，避免候选自己变化干扰（候选单独看）
    r4_delivery = {k: v for k, v in tree_state([('r4', L.R4_DIR)])['r4'].items()
                   if not k.startswith('reports/V9-B1/r5-candidate/')}
    before = {
        'candidate': tree_state(watched)['candidate'],
        'r4': r4_delivery,
        'contracts_v9': tree_state(watched)['contracts_v9'],
        'docs_v9': tree_state(watched)['docs_v9'],
    }
    t0 = time.time()

    # ---------- C1 默认只读 ----------
    r1 = run_suite(L.CAND, label='c1-default-run')
    after1 = {
        'candidate': tree_state(watched)['candidate'],
        'r4': {k: v for k, v in tree_state([('r4', L.R4_DIR)])['r4'].items()
               if not k.startswith('reports/V9-B1/r5-candidate/')},
        'contracts_v9': tree_state(watched)['contracts_v9'],
        'docs_v9': tree_state(watched)['docs_v9'],
    }
    ro = {k: diff_tree(before, after1, k) for k in before}

    # ---------- C2 显式新输出目录（两次，确定性 + 与作者结果对比） ----------
    out1 = SUITE_OUT / 'run1'
    out2 = SUITE_OUT / 'run2'
    r2 = run_suite(L.CAND, '--output-dir', out1, label='c2-output-run1')
    r3 = run_suite(L.CAND, '--output-dir', out2, label='c2-output-run2')
    after2 = tree_state([('candidate', L.CAND_DIR)])['candidate']
    writes = diff_tree(before, {'candidate': after2}, 'candidate')

    cmp = {}
    for name, p in (('run1', out1), ('run2', out2)):
        cmp[name] = {f.name: {'sha256': L.sha(f), 'size': f.stat().st_size}
                     for f in sorted(p.rglob('*')) if f.is_file()}
    author = {f.name: {'sha256': L.sha(f), 'size': f.stat().st_size}
              for f in sorted(L.CAND_DIR.glob('check_result.json'))}
    author.update({f.name: {'sha256': L.sha(f), 'size': f.stat().st_size}
                   for f in sorted(L.CAND_DIR.glob('SHA256SUMS.txt'))})
    det = {'run1_vs_run2_identical': cmp['run1'] == cmp['run2'],
           'run1': cmp['run1'], 'run2': cmp['run2']}
    vs_author = {}
    for fname in ('check_result.json', 'SHA256SUMS.txt'):
        mine = out1 / fname
        auth = L.CAND_DIR / fname
        vs_author[fname] = {'mine_sha256': L.sha(mine) if mine.is_file() else None,
                            'author_sha256': L.sha(auth) if auth.is_file() else None,
                            'identical': mine.is_file() and auth.is_file() and L.sha(mine) == L.sha(auth)}
        if not vs_author[fname]['identical'] and fname == 'SHA256SUMS.txt' and mine.is_file() and auth.is_file():
            a = mine.read_text(encoding='utf-8').splitlines()
            b = auth.read_text(encoding='utf-8').splitlines()
            vs_author[fname]['line_diff_count'] = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
            vs_author[fname]['first_diffs'] = [
                {'mine': x, 'author': y} for x, y in zip(a, b) if x != y][:4]

    # ---------- C3 --output-dir 指向输入/旧交付目录：/tmp 隔离副本 ----------
    if TMP.exists():
        shutil.rmtree(TMP)
    repo = TMP / 'repo'
    # 镜像最小可运行根：候选目录 + contracts/v9 + probe 回归输入 + docs 身份输入
    shutil.copytree(L.CAND_DIR, repo / 'reports/V9-B1/r5-candidate')
    shutil.copytree(L.ROOT / 'contracts/v9', repo / 'contracts/v9')
    (repo / 'reports/V-V9-B1').mkdir(parents=True)
    shutil.copy2(L.ROOT / 'reports/V-V9-B1/probe_variants.json', repo / 'reports/V-V9-B1/probe_variants.json')
    (repo / 'docs/v9').mkdir(parents=True)
    for rel in ('docs/v9/SKILL_PROPOSAL.md', 'docs/v9/SKILL_PROPOSAL_COORDINATION.md',
                'docs/v9/TEACHERS_AND_CACHE.md', 'ARCHITECTURE_V9.md'):
        src = L.ROOT / rel
        if src.is_file():
            shutil.copy2(src, repo / rel)
    # 旧 r4 交付目录副本：含 check_result.json / SHA256SUMS.txt（用于覆盖试验）
    r4copy = repo / 'reports/V9-B1'
    for f in ('check_result.json', 'SHA256SUMS.txt', 'check_skill_proposal.py',
              'metrics.json', 'REPORT.md'):
        if (L.R4_DIR / f).is_file():
            shutil.copy2(L.R4_DIR / f, r4copy / f)
    tcand = repo / 'reports/V9-B1/r5-candidate/check_skill_proposal.py'
    fixtures_dir = repo / 'reports/V9-B1/r5-candidate/fixtures'

    def snap(names):
        out = {}
        for n, p in names.items():
            out[n] = {str(f.relative_to(p)): L.sha(f) for f in p.rglob('*') if f.is_file()}
        return out
    pre = snap({'r4dir': r4copy, 'canddir': repo / 'reports/V9-B1/r5-candidate',
                'fixtures': fixtures_dir})

    cases = []
    # (a) 指向旧 r4 交付目录（会覆盖 check_result.json / SHA256SUMS.txt）
    ra = run_suite(tcand, '--output-dir', r4copy, label='c3-outdir-r4-dir')
    post_r4 = {str(f.relative_to(r4copy)): L.sha(f) for f in r4copy.rglob('*') if f.is_file()}
    changed_r4 = {k: {'before': pre['r4dir'].get(k), 'after': post_r4.get(k)}
                  for k in sorted(set(pre['r4dir']) | set(post_r4))
                  if pre['r4dir'].get(k) != post_r4.get(k)}
    cases.append({'case': 'output-dir = 原 r4 交付目录副本', 'rejected': False,
                  'rc': ra['rc'], 'has_traceback': 'Traceback (most recent call last)' in ra['stderr'],
                  'files_changed': sorted(changed_r4), 'detail': changed_r4})
    # (b) 指向候选交付目录自身（含 fixtures 输入）
    rb = run_suite(tcand, '--output-dir', repo / 'reports/V9-B1/r5-candidate', label='c3-outdir-cand-dir')
    post_c = {str(f.relative_to(repo / 'reports/V9-B1/r5-candidate')): L.sha(f)
              for f in (repo / 'reports/V9-B1/r5-candidate').rglob('*') if f.is_file()}
    changed_c = {k: {'before': pre['canddir'].get(k), 'after': post_c.get(k)}
                 for k in sorted(set(pre['canddir']) | set(post_c))
                 if pre['canddir'].get(k) != post_c.get(k)}
    cases.append({'case': 'output-dir = 候选交付目录自身', 'rejected': False,
                  'rc': rb['rc'], 'has_traceback': 'Traceback (most recent call last)' in rb['stderr'],
                  'files_changed': sorted(k for k in changed_c if 'fixtures/' not in k)[:6],
                  'detail': {k: v for k, v in list(changed_c.items()) if 'fixtures/' not in k}})
    # (c) 指向输入夹具目录
    rc = run_suite(tcand, '--output-dir', fixtures_dir, label='c3-outdir-fixtures')
    post_f = {str(f.relative_to(fixtures_dir)): L.sha(f) for f in fixtures_dir.rglob('*') if f.is_file()}
    changed_f = {k: {'before': pre['fixtures'].get(k), 'after': post_f.get(k)}
                 for k in sorted(set(pre['fixtures']) | set(post_f))
                 if pre['fixtures'].get(k) != post_f.get(k)}
    cases.append({'case': 'output-dir = 输入夹具目录 fixtures/', 'rejected': False,
                  'rc': rc['rc'], 'has_traceback': 'Traceback (most recent call last)' in rc['stderr'],
                  'files_changed': sorted(changed_f), 'detail': changed_f})
    # 有无任何显式拒绝（rc 非 0 且 stderr 明说拒绝 output-dir）？
    rejects = [c for c in cases if 'output-dir' in (c.get('stdout', '') + c.get('stderr', '')).lower()
               or c.get('rejected')]
    # 默认只读在副本里也核一次（快速：只核有无新增文件）
    tree_before = {str(f.relative_to(repo)): L.sha(f) for f in repo.rglob('*') if f.is_file()}
    rd = run_suite(tcand, label='c3-default-readonly-in-copy')
    tree_after = {str(f.relative_to(repo)): L.sha(f) for f in repo.rglob('*') if f.is_file()}
    copy_ro = {'added': sorted(set(tree_after) - set(tree_before)),
               'removed': sorted(set(tree_before) - set(tree_after)),
               'changed': sorted(k for k in set(tree_before) & set(tree_after)
                                 if tree_before[k] != tree_after[k])}
    copy_ro['clean'] = not (copy_ro['added'] or copy_ro['removed'] or copy_ro['changed'])

    # 汇总计数：作者 metrics / 我的 check_result / 两次运行一致
    def counts_of(check_path):
        try:
            return L.load_json(check_path).get('counts') or {}
        except Exception:
            return {}
    authored = L.load_json(L.CAND_DIR / 'metrics.json')
    my_counts = counts_of(out1 / 'check_result.json')
    c1 = r1.get('parsed') or {}
    c2 = r2.get('parsed') or {}
    summary = {
        'identity': L.py_identity(),
        'c1_default_readonly': {
            'run': {k: r1[k] for k in ('argv', 'rc', 'duration_s', 'timeout')},
            'stdout_parsed': c1,
            'tree_diff': ro,
            'all_clean': all(v['clean'] for v in ro.values()),
            'no_traceback': 'Traceback (most recent call last)' not in r1['stderr'],
        },
        'c2_output_dir': {
            'run1': {k: r2[k] for k in ('argv', 'rc', 'duration_s', 'timeout')},
            'run2': {k: r3[k] for k in ('argv', 'rc', 'duration_s', 'timeout')},
            'stdout_equal': (r2['stdout'] == r3['stdout']),
            'deterministic': det['run1_vs_run2_identical'],
            'vs_author': vs_author,
            'author_metrics_all_ok': authored.get('all_ok'),
            'counts_equal_author': my_counts == (authored.get('counts') or {}),
            'count_diff': {k: {'mine': my_counts.get(k), 'author': (authored.get('counts') or {}).get(k)}
                           for k in sorted(set(my_counts) | set(authored.get('counts') or {}))
                           if my_counts.get(k) != (authored.get('counts') or {}).get(k)},
            'c2_tree_writes_during_output_runs': writes,
            'c2_tree_writes_clean': writes['clean'],
        },
        'c3_output_dir_safety': {
            'n_cases': len(cases), 'cases': cases,
            'any_rejection': bool(rejects),
            'copy_default_readonly': copy_ro,
            'note': '每个 case 都在 /tmp 隔离副本里跑真实候选 suite；看写入前后逐字节差。'
                    '“rejected”列按是否明确拒绝 output-dir（现在代码里没有这种拒绝）。',
        },
    }
    LOG.save_summary(summary)
    # 控制台精简输出
    print(json.dumps({
        'elapsed_s': round(time.time() - t0, 1),
        'c1': {'rc': r1['rc'], 'all_ok': c1.get('all_ok'), 'clean': summary['c1_default_readonly']['all_clean'],
               'no_traceback': summary['c1_default_readonly']['no_traceback']},
        'c2': {'rc1': r2['rc'], 'rc2': r3['rc'], 'deterministic': det['run1_vs_run2_identical'],
               'vs_author': vs_author, 'counts_equal_author': summary['c2_output_dir']['counts_equal_author'],
               'count_diff': summary['c2_output_dir']['count_diff'],
               'tree_writes_clean': writes['clean']},
        'c3': {'cases': [{'case': x['case'], 'files_changed': x['files_changed']} for x in cases],
               'any_rejection': bool(rejects),
               'copy_default_readonly_clean': copy_ro['clean']},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
