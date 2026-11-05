"""B8 r6 复核补充阶段：新候选显式输出 suite 与 output-dir 拒绝语义（只读被验对象）。

被验对象：reports/V9-B1/r6-candidate/check_skill_proposal.py（sha d902876a…，B7 第 5 棒最终 r6）。
本脚本只读候选/原 r4/契约/真实 AWZ；全部写操作落在 /tmp 的一次性目录，输出证据落本复核目录。

E1 合法全新隔离输出：--suite --output-dir </tmp 新目录> → rc=0/all_ok、恰好写 2 个证据文件；
   与候选目录里既有的 check_result.json / SHA256SUMS.txt 逐字节对比（r6 交付物自洽性）。
E2 同目录二次运行 → 必须拒绝（output_evidence_exists）、两份证据字节前后不变。
E3 /tmp 最小可运行副本内的 output-dir 重叠拒绝：r4 交付目录（祖先）、候选目录（同路径）、
   fixtures（后代）、symlink 别名（同路径）、输出路径是普通文件（output_not_directory）；
   每个 case 记录 rc/错误码/traceback/被保护目录逐字节变化（应全为 0）。
E4 原 r4 与候选目录在 E1/E2 期间逐字节不变（mtime 也记）。

运行（复核人 deepseek-flash-4up8；沿用第 1 棒 harness，身份已更正）：
  B8_CAND_DIR=<.../r6-candidate> /usr/local/bin/python3 <本脚本>
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
RESULTS = HERE / 'results'
SUITE_OUT = RESULTS / 'suite-r6'
TMP = Path('/tmp/b8-r6-outputs')
LOG = L.RunLog('r6-output-suite')
TB = 'Traceback (most recent call last)'

EXPECT_CAND_SHA = 'd902876a8e5aa1af58d1e3a974c099d847cadae2b79f1956037b2186eafa8c0b'
EXPECT_R4_SHA = '37d4308f34a64bad515a8ef44b0c9a12b8bf6f35c24a628730280c3ad50328da'
EXPECT_DELIVERED_CHECK_RESULT = 'ef9a4bd11018c6cd37d8c78dde8a86fbc6643df7b04a2954c651f68753c2aa62'


def tree(paths):
    out = {}
    for label, base in paths:
        base = Path(base)
        if base.is_dir():
            out[label] = L.tree_manifest(base)
        else:
            st = base.stat()
            out[label] = {str(base): {'sha256': L.sha(base), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}}
    return out


def diff(before, after):
    rows = {}
    for label in before:
        b, a = before[label], after.get(label, {})
        added = sorted(set(a) - set(b))
        removed = sorted(set(b) - set(a))
        changed = sorted(k for k in set(b) & set(a) if b[k]['sha256'] != a[k]['sha256'])
        rows[label] = {'added': added, 'removed': removed, 'changed': changed,
                       'n_before': len(b), 'n_after': len(a),
                       'clean': not (added or removed or changed)}
    return rows


def run_suite(script, *extra, label, cwd=None, env_extra=None):
    argv = [L.PY, '-I', str(script), '--suite', *map(str, extra)]
    rec = L.run(argv, cwd=cwd, env_extra=env_extra, timeout=1800)
    rec['label'] = label
    rec['script'] = str(script)
    try:
        rec['parsed'] = json.loads(rec['stdout'])
    except Exception:
        rec['parsed'] = None
    LOG.add('suite-run', **{k: v for k, v in rec.items() if k != 'parsed'})
    return rec


def main() -> int:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    checks = []

    def check(cid, ok, detail):
        checks.append({'id': cid, 'ok': bool(ok), 'detail': detail})
        print('[%s] %s: %s' % ('PASS' if ok else 'FAIL', cid, json.dumps(detail, ensure_ascii=False)[:220]))

    cand_sha = L.sha(L.CAND)
    r4_sha = L.sha(L.R4)
    delivered_cr = L.CAND_DIR / 'check_result.json'
    delivered_sums = L.CAND_DIR / 'SHA256SUMS.txt'
    check('identity-candidate', cand_sha == EXPECT_CAND_SHA, {'sha256': cand_sha})
    check('identity-r4', r4_sha == EXPECT_R4_SHA, {'sha256': r4_sha})
    check('identity-delivered-check-result',
          delivered_cr.is_file() and L.sha(delivered_cr) == EXPECT_DELIVERED_CHECK_RESULT,
          {'sha256': L.sha(delivered_cr) if delivered_cr.is_file() else None})

    # ---- E1: 合法全新隔离输出（/tmp）
    fresh = TMP / ('fresh-' + time.strftime('%Y%m%dT%H%M%S'))
    snap_before = tree([('candidate', L.CAND_DIR), ('r4', L.R4_DIR),
                        ('contracts_v9', L.ROOT / 'contracts/v9'), ('docs_v9', L.ROOT / 'docs/v9')])
    e1 = run_suite(L.CAND, '--output-dir', fresh, label='e1-fresh-output')
    snap_after = tree([('candidate', L.CAND_DIR), ('r4', L.R4_DIR),
                       ('contracts_v9', L.ROOT / 'contracts/v9'), ('docs_v9', L.ROOT / 'docs/v9')])
    e1_diff = diff(snap_before, snap_after)
    made = sorted(str(p.relative_to(fresh)) for p in fresh.rglob('*') if p.is_file()) if fresh.is_dir() else []
    parsed = e1['parsed'] or {}
    cr = fresh / 'check_result.json'
    sums = fresh / 'SHA256SUMS.txt'
    e1_ok = (e1['rc'] == 0 and parsed.get('all_ok') is True
             and parsed.get('counts', {}).get('cases_total') == 112
             and made == ['SHA256SUMS.txt', 'check_result.json']
             and cr.is_file() and sums.is_file()
             and all(row['clean'] for row in e1_diff.values()))
    check('E1-fresh-output', e1_ok,
          {'rc': e1['rc'], 'duration_s': e1['duration_s'], 'files': made,
           'cases_total': parsed.get('counts', {}).get('cases_total'),
           'check_result_sha': L.sha(cr) if cr.is_file() else None,
           'sha_sums_sha': L.sha(sums) if sums.is_file() else None,
           'tree_diff_clean': all(row['clean'] for row in e1_diff.values()),
           'tree_diff': {k: {kk: vv for kk, vv in v.items() if kk in ('added', 'removed', 'changed')}
                         for k, v in e1_diff.items()}})

    # ---- E1b: 两次全新输出应逐字节可复现
    fresh2 = TMP / ('fresh2-' + time.strftime('%Y%m%dT%H%M%S'))
    e1b = run_suite(L.CAND, '--output-dir', fresh2, label='e1b-fresh-output-2')
    cr2, sums2 = fresh2 / 'check_result.json', fresh2 / 'SHA256SUMS.txt'
    e1b_ok = (e1b['rc'] == 0 and (e1b['parsed'] or {}).get('all_ok') is True
              and cr2.is_file() and sums2.is_file()
              and L.sha(cr2) == L.sha(cr)
              and (sums.is_file() and L.sha(sums2) == L.sha(sums)))
    check('E1b-output-deterministic', e1b_ok,
          {'rc': e1b['rc'], 'run1_sha': L.sha(cr) if cr.is_file() else None,
           'run2_sha': L.sha(cr2) if cr2.is_file() else None,
           'deterministic': cr2.is_file() and L.sha(cr2) == L.sha(cr)})

    # ---- E1c: 候选目录里既有 check_result/SHA256SUMS 是否随 r6 重生成（审计）
    delivered_cr_text = delivered_cr.read_text(encoding='utf-8')
    delivered_sums_text = delivered_sums.read_text(encoding='utf-8') if delivered_sums.is_file() else ''
    fresh_cr_text = cr.read_text(encoding='utf-8') if cr.is_file() else ''
    stale_markers = {
        'delivered_check_result_mentions_r5_candidate': 'reports/V9-B1/r5-candidate' in delivered_cr_text,
        'fresh_check_result_mentions_r6_candidate': 'reports/V9-B1/r6-candidate' in fresh_cr_text,
        'delivered_sums_mentions_r5_candidate': 'reports/V9-B1/r5-candidate' in delivered_sums_text,
        'delivered_check_result_sha': L.sha(delivered_cr),
        'fresh_check_result_sha': L.sha(cr) if cr.is_file() else None,
        'delivered_sums_sha': L.sha(delivered_sums) if delivered_sums.is_file() else None,
        'fresh_sums_sha': L.sha(sums) if sums.is_file() else None,
    }
    stale_markers['delivered_evidence_stale'] = bool(
        stale_markers['delivered_check_result_mentions_r5_candidate']
        and stale_markers['fresh_check_result_mentions_r6_candidate'])
    check('E1c-delivered-evidence-audit', True, stale_markers)

    # ---- E2: 同目录二次运行必须拒绝且不改字节
    cr_before, sums_before = L.sha(cr), L.sha(sums) if sums.is_file() else None
    e2 = run_suite(L.CAND, '--output-dir', fresh, label='e2-rerun-evidence-exists')
    e2_parsed = e2['parsed'] or {}
    e2_ok = (e2['rc'] == 2 and e2_parsed.get('output_dir_rejected') is True
             and any('output_evidence_exists' in x for x in e2_parsed.get('errors') or [])
             and L.sha(cr) == cr_before and (sums.is_file() and L.sha(sums) == sums_before)
             and TB not in e2['stderr'])
    check('E2-rerun-refused', e2_ok,
          {'rc': e2['rc'], 'errors': e2_parsed.get('errors'), 'no_traceback': TB not in e2['stderr'],
           'evidence_sha_unchanged': L.sha(cr) == cr_before})

    # ---- E3: /tmp 最小可运行副本里的 output-dir 重叠拒绝
    repo = TMP / 'repo'
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
    r4copy = repo / 'reports/V9-B1'
    for f in ('check_result.json', 'SHA256SUMS.txt', 'check_skill_proposal.py',
              'metrics.json', 'REPORT.md'):
        if (L.R4_DIR / f).is_file():
            shutil.copy2(L.R4_DIR / f, r4copy / f)
    tcand = repo / 'reports/V9-B1/r5-candidate/check_skill_proposal.py'
    alias = TMP / 'cand-alias'
    alias.symlink_to(repo / 'reports/V9-B1/r5-candidate', target_is_directory=True)
    not_dir = TMP / 'not-a-dir'
    not_dir.write_text('B8 r6 reject test: output path is a regular file\n', encoding='utf-8')

    protected = {'r4dir': r4copy,
                 'canddir': repo / 'reports/V9-B1/r5-candidate',
                 'fixtures': repo / 'reports/V9-B1/r5-candidate/fixtures'}
    pre = {name: {str(p.relative_to(base)): L.sha(p) for p in base.rglob('*') if p.is_file()}
           for name, base in protected.items()}
    cases = []

    def overlap_case(cid, output, expect_code):
        rec = run_suite(tcand, '--output-dir', output, label='e3-' + cid)
        parsed = rec['parsed'] or {}
        errors = parsed.get('errors') or []
        post = {name: {str(p.relative_to(base)): L.sha(p) for p in base.rglob('*') if p.is_file()}
                for name, base in protected.items()}
        changed = {name: sorted(k for k in set(pre[name]) | set(post[name])
                                if pre[name].get(k) != post[name].get(k)) for name in protected}
        ok = (rec['rc'] == 2 and parsed.get('output_dir_rejected') is True
              and any(expect_code in x for x in errors) and TB not in rec['stderr']
              and all(not v for v in changed.values()))
        cases.append({'case': cid, 'rc': rec['rc'], 'errors': errors[:2],
                      'no_traceback': TB not in rec['stderr'],
                      'protected_changed': changed, 'ok': ok})
        LOG.add('overlap-case', case=cid, output=str(output), rc=rec['rc'],
                errors=errors[:2], protected_changed=changed)
        print('[%s] E3-%s: rc=%s errors=%s changed=%s'
              % ('PASS' if ok else 'FAIL', cid, rec['rc'], errors[:1], changed))
        return ok

    e3_results = [
        overlap_case('r4-dir-ancestor', r4copy, 'output_ancestor_of_input'),
        overlap_case('candidate-dir-same-path', repo / 'reports/V9-B1/r5-candidate', 'output_path_is_input'),
        overlap_case('fixtures-descendant', repo / 'reports/V9-B1/r5-candidate/fixtures', 'output_inside_input'),
        overlap_case('symlink-alias', alias, 'output_path_is_input'),
        overlap_case('output-path-is-file', not_dir, 'output_not_directory'),
    ]
    check('E3-overlap-rejections', all(e3_results), {'cases': cases})

    # ---- E4: 原 r4 / 候选树在 E1/E2 期间逐字节不变（上面已快照，再确认一次）
    final_diff = diff(snap_before, tree([('candidate', L.CAND_DIR), ('r4', L.R4_DIR),
                                         ('contracts_v9', L.ROOT / 'contracts/v9'),
                                         ('docs_v9', L.ROOT / 'docs/v9')]))
    # E4: 候选/原 r4 只读快照（相对 E1 前）；E1 之后未再触碰真实候选
    e4_ok = all(row['clean'] for row in final_diff.values())
    check('E4-r4-candidate-bytes-unchanged', e4_ok,
          {k: {kk: vv for kk, vv in v.items() if kk in ('added', 'removed', 'changed')}
           for k, v in final_diff.items()})

    summary = {
        'task': 'ainerzero.V9.B8',
        'stage': 'r6-output-suite',
        'candidate': {'path': str(L.CAND), 'sha256': cand_sha},
        'r4': {'path': str(L.R4), 'sha256': r4_sha},
        'delivered': {'check_result_sha256': L.sha(delivered_cr),
                      'sha256sums_sha256': L.sha(delivered_sums) if delivered_sums.is_file() else None},
        'checks': checks,
        'checks_failed': [c for c in checks if not c['ok']],
        'all_checks_ok': all(c['ok'] for c in checks),
        'findings': ([{'id': 'r6-delivered-evidence-stale',
                       'detail': '候选目录 r6-candidate 的 check_result.json/SHA256SUMS.txt 仍含 '
                                 'reports/V9-B1/r5-candidate 逻辑路径（B7 第4棒改目录名后未重生成），'
                                 '与本次全新输出不一致；R6_SHA256SUMS.txt 是另一份当前身份清单'}]
                     if stale_markers['delivered_evidence_stale'] else []),
        'identity': L.py_identity(),
    }
    LOG.save_summary(summary)
    print(json.dumps({'all_ok': summary['all_checks_ok'],
                      'failed': summary['checks_failed'],
                      'E1': checks[3]['detail'] if len(checks) > 3 else None,
                      'E3_cases': cases}, ensure_ascii=False, indent=1)[:4000])
    return 0 if summary['all_checks_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
