"""B8 阶段 F：全部复核动作之后，重算"原 r4 全字节不变 / 候选与输入树不变 / AWZ 只读源不变"，
并保存命令、身份、rc 证据（原日志副本 + COMMANDS 表 + identity.json）。

- 与阶段 A 的 before_tree.json 逐文件比对（sha256 + size + mtime_ns），确认本复核没有改动
  候选目录、原 r4 交付树、contracts/v9、docs/v9、AWZ 只读来源。
- 再对一次 B6 已验收 baseline（独立于 B7 作者的记录）。
- 存 after_tree.json / identity.json / COMMANDS.md / 作者原 verification_logs 副本。
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
RESULTS = HERE / 'results'
TB = 'Traceback (most recent call last)'
log = L.RunLog('F-final-identity')


def load_before():
    return json.load(open(RESULTS / 'baseline' / 'before_tree.json'))


def snap_like_before(before):
    out = {}
    for k in before:
        # 只重算 before 里列出的文件（不扫描整树）
        out[k] = {}
        for rel in before[k]:
            if rel.startswith('EXTERNAL/'):
                p = Path('/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9') / rel.split('/', 1)[1]
            else:
                p = Path(rel) if rel.startswith('/') else L.ROOT / rel
            if not p.is_file():
                out[k][rel] = {'missing': True}
                continue
            st = p.stat()
            out[k][rel] = {'sha256': L.sha(p), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                           'inode': st.st_ino}
    return out


def diff(before, after, label):
    b, a = before[label], after[label]
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = sorted(k for k in set(b) & set(a) if b[k] != a[k])
    return {'label': label, 'n_before': len(b), 'n_after': len(a),
            'added': added, 'removed': removed, 'changed': changed,
            'bytes_unchanged': not (added or removed or changed)}


def main():
    before = load_before()
    after = snap_like_before(before)
    results = {k: diff(before, after, k) for k in before}
    # AWZ 只读来源单独标记
    awz = next(iter(after['awz_source'].items()), (None, None))
    # 再对 B6 已验收 baseline（独立于 B7 作者记录）
    base = json.load(open(L.ROOT / 'reports/V-V9-B1/r4-independent/results/baseline_manifest.json'))
    bad = []
    for x in base['deliverables_and_inputs']:
        p = Path(x['path']) if x['path'].startswith('/') else L.ROOT / x['path']
        if not p.is_file() or L.sha(p) != x['sha256']:
            bad.append(x['path'])
    fixdir = L.ROOT / 'contracts/v9/examples/skill_proposal_v1'
    for x in base['fixture_tree']:
        p = fixdir / x['rel']
        if not p.is_file() or L.sha(p) != x['sha256']:
            bad.append('fixture:' + x['rel'])
    for rel in (base.get('sabotage_schemas') or []):
        p = L.R4_DIR / 'sabotage-schemas' / (rel if isinstance(rel, str) else rel.get('rel'))
        if not p.is_file():
            bad.append('sabotage:' + str(rel))
    b6 = {'checked': len(base['deliverables_and_inputs']) + len(base['fixture_tree']) + len(base.get('sabotage_schemas') or []),
          'mismatch': bad, 'ok': not bad}
    # 原 r4 自清单
    r4_manifest = L.R4_DIR / 'SHA256SUMS.txt'
    rows = []
    for line in r4_manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#') or line.startswith('RAW_SHA256'):
            continue
        segs = [s for s in line.split('  ') if s.strip()]
        if len(segs) >= 3:
            rows.append({'raw': segs[0].strip(), 'path': segs[2].strip()})
    r4bad = []
    for r in rows:
        p = Path(r['path']) if r['path'].startswith('/') else L.ROOT / r['path']
        if not p.is_file() or L.sha(p) != r['raw']:
            r4bad.append(r['path'])
    r4m = {'rows': len(rows), 'mismatch': r4bad, 'ok': not r4bad}

    # 作者原 verification_logs 副本 + 哈希（只读保存，不改原文件）
    origdir = RESULTS / 'original-author-logs'
    origdir.mkdir(parents=True, exist_ok=True)
    orig = {}
    for f in sorted((L.CAND_DIR / 'verification_logs').glob('*')):
        if f.is_file():
            (origdir / f.name).write_bytes(f.read_bytes())
            orig[f.name] = L.sha(f)
    (origdir / 'AUTHOR_LOGS_SHA256.json').write_text(json.dumps(orig, indent=1) + '\n', encoding='utf-8')

    # 所有运行记录 → COMMANDS.md（原命令/rc/traceback/耗时）
    lines = ['# B8 复核运行记录（原命令 / rc / traceback / 耗时）', '',
             '由 results/logs/*.jsonl 自动汇总；完整 stdout/stderr 在 JSONL 里。', '']
    n_runs = 0
    for jf in sorted(glob.glob(str(RESULTS / 'logs' / '*.jsonl'))):
        name = Path(jf).name
        lines += ['## ' + name, '', '```']
        for line in open(jf, encoding='utf-8'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if 'argv' not in d:
                continue
            n_runs += 1
            tb = TB in (d.get('stderr') or '')
            lines.append('# %-46s rc=%-3s traceback=%-5s %.2fs' % (
                d.get('label', ''), d.get('rc'), tb, d.get('duration_s') or 0))
            lines.append('$ ' + ' '.join(d['argv']))
            if d.get('env_extra'):
                lines.append('# env_extra: ' + json.dumps(d['env_extra'], ensure_ascii=False))
            if d.get('cwd'):
                lines.append('# cwd: ' + d['cwd'])
        lines += ['```', '']
    L.write_text(HERE / 'COMMANDS.md', '\n'.join(lines))

    # identity.json
    ident = {
        'agent': 'deepseek-h7m2', 'task': 'ainerzero.V9.B8', 'role': '非作者二级执行（verify）',
        'harness': L.py_identity(),
        'checked_python': {'path': L.PY, 'realpath': str(Path(L.PY).resolve())},
        'files': {
            'candidate_checker': {'path': 'reports/V9-B1/r5-candidate/check_skill_proposal.py', 'sha256': L.sha(L.CAND)},
            'original_r4_checker': {'path': 'reports/V9-B1/check_skill_proposal.py', 'sha256': L.sha(L.R4)},
            'candidate_report': {'sha256': L.sha(L.CAND_DIR / 'REPORT.md')},
            'candidate_metrics': {'sha256': L.sha(L.CAND_DIR / 'metrics.json')},
            'candidate_check_result': {'sha256': L.sha(L.CAND_DIR / 'check_result.json')},
            'candidate_sha256sums': {'sha256': L.sha(L.CAND_DIR / 'SHA256SUMS.txt')},
            'r4_report': {'sha256': L.sha(L.R4_DIR / 'REPORT.md')},
            'r4_metrics': {'sha256': L.sha(L.R4_DIR / 'metrics.json')},
            'r4_check_result': {'sha256': L.sha(L.R4_DIR / 'check_result.json')},
            'r4_sha256sums': {'sha256': L.sha(L.R4_DIR / 'SHA256SUMS.txt')},
            'awz_observation_source': {'path': str(L.AWZ_OBSERVATION), 'sha256': L.sha(L.AWZ_OBSERVATION),
                                       'size': L.AWZ_OBSERVATION.stat().st_size},
            'schemas': {p.name: L.sha(p) for p in sorted((L.ROOT / 'contracts/v9').glob('*.json'))},
        },
        'author_verification_logs_sha256': orig,
        'runs_recorded': n_runs,
        'filesystem_scope': '只写 reports/V-V9-B1/r5-independent/ 与 /tmp；候选/原 r4/契约/AWZ 只读',
        'r4_unchanged_since_b6_baseline': b6['ok'],
        'r4_manifest_selfcheck': r4m,
        'note': '没有训练/MLX/ORT/下载/付费/git 提交/提交推送；只读核对与 CPU 工程测试。',
    }
    (HERE / 'identity.json').write_text(json.dumps(ident, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (RESULTS / 'baseline' / 'after_tree.json').write_text(json.dumps(after, indent=1, sort_keys=True))

    summary = {'identity': L.py_identity(), 'filesystem_unchanged': results,
               'all_bytes_unchanged': all(v['bytes_unchanged'] for v in results.values()),
               'r4_vs_b6_baseline': b6, 'r4_manifest_selfcheck': r4m,
               'author_logs': orig, 'runs_recorded': n_runs,
               'after_snapshot': str(RESULTS / 'baseline' / 'after_tree.json')}
    log.save_summary(summary)
    print(json.dumps({k: summary[k] for k in ('all_bytes_unchanged', 'r4_vs_b6_baseline',
                                             'r4_manifest_selfcheck', 'runs_recorded')},
                     ensure_ascii=False, indent=1))
    return 0 if summary['all_bytes_unchanged'] and b6['ok'] and r4m['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
