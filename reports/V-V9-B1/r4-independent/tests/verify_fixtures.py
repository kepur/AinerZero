"""V9.B6 独立复核：夹具路径/大小写独立性、EXPECTATIONS、交付 SHA 清单重算。

不复用作者 --suite 结论；SHA256SUMS.txt 的每一行、EXPECTATIONS 的每一份夹具、
REPORT/metrics/relay 报告里的哈希都自己重算并对照。
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'
RES.mkdir(parents=True, exist_ok=True)


def walk_keys(obj, found=None, path=''):
    found = [] if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.append((path + '/' + str(k), k))
            walk_keys(v, found, path + '/' + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_keys(v, found, path + '[%d]' % i)
    return found


def main():
    exp = L.load(L.FIXTURE / 'EXPECTATIONS.json')
    cases = exp['cases']
    res = {}

    # ---------- 1) 文件树与计数
    files = sorted(p for p in L.FIXTURE.rglob('*') if p.is_file())
    rels = [str(p.relative_to(L.FIXTURE)) for p in files]
    top = Counter(r.split('/')[0] for r in rels)
    prop_cases = [c for c in cases if c.get('dir') in ('valid', 'invalid')]
    reply_cases = [c for c in cases if c.get('dir') not in ('valid', 'invalid')]
    res['file_count'] = len(files)
    res['top_dirs'] = dict(top)
    res['proposal_cases'] = {'total': len(prop_cases),
                             'valid': sum(1 for c in prop_cases if c['dir'] == 'valid'),
                             'invalid': sum(1 for c in prop_cases if c['dir'] == 'invalid')}
    res['reply_cases'] = {'total': len(reply_cases),
                          'valid': sum(1 for c in reply_cases if c['expected_decision'] == 'valid'),
                          'invalid': sum(1 for c in reply_cases if c['expected_decision'] == 'invalid')}
    # 期望：236 = contexts113 + valid18 + invalid94 + replies 10 + EXPECTATIONS 1
    res['count_consistent_236'] = (len(files) == 236 and
                                   top.get('contexts') == 113 and top.get('valid') == 18 and
                                   top.get('invalid') == 94 and top.get('replies') == 10 and
                                   top.get('EXPECTATIONS.json') == 1)

    # ---------- 2) 大小写/同 inode 碰撞（自写扫描）
    casefold_names = {}
    inodes = {}
    for p, r in zip(files, rels):
        st = p.stat()
        casefold_names.setdefault(r.casefold(), []).append(r)
        inodes.setdefault(st.st_ino, []).append(r)
    res['casefold_collisions'] = {k: v for k, v in casefold_names.items() if len(v) > 1}
    res['inode_collisions'] = [v for v in inodes.values() if len(v) > 1]
    res['no_collision'] = not res['casefold_collisions'] and not res['inode_collisions']
    # 声明 inode 数 / 唯一 inode 数
    res['file_count'] = len(files)
    res['unique_inodes'] = len(inodes)
    res['distinct_paths_all'] = len({str(p) for p in files}) == len(files)

    # ---------- 3) 每个 case 的路径/哈希/pin 重算
    bad = []
    for c in cases:
        if c.get('dir') in ('valid', 'invalid'):
            pp = L.FIXTURE / c['dir'] / c['proposal_file']
            cp = L.FIXTURE / 'contexts' / c['context_file']
            if not pp.is_file():
                bad.append({'name': c['name'], 'what': 'proposal_missing'})
                continue
            if not cp.is_file():
                bad.append({'name': c['name'], 'what': 'context_missing'})
                continue
            if L.sha_file(pp) != c['proposal_sha256']:
                bad.append({'name': c['name'], 'what': 'proposal_raw_sha'})
            ctx = L.load(cp)
            if L.jcs_sha(ctx) != c['context_sha256']:
                bad.append({'name': c['name'], 'what': 'context_jcs_sha'})
            if c['context_sha256_jcs'] != c['context_sha256']:
                bad.append({'name': c['name'], 'what': 'context_sha_columns_differ'})
        else:
            sub = 'valid' if c['expected_decision'] == 'valid' else 'invalid'
            rp = L.FIXTURE / 'replies' / sub / c['reply_file']
            if not rp.is_file():
                bad.append({'name': c['name'], 'what': 'reply_missing'})
            elif L.sha_file(rp) != c['reply_sha256']:
                bad.append({'name': c['name'], 'what': 'reply_raw_sha'})
    res['case_pin_sha_errors'] = bad

    # ---------- 4) 声明文件集合 == 磁盘文件集合（夹具不多不少）
    declared = set()
    for c in cases:
        if c.get('dir') in ('valid', 'invalid'):
            declared.add('/'.join([c['dir'], c['proposal_file']]))
            declared.add('/'.join(['contexts', c['context_file']]))
        else:
            sub = 'valid' if c['expected_decision'] == 'valid' else 'invalid'
            declared.add('/'.join(['replies', sub, c['reply_file']]))
    declared.add('EXPECTATIONS.json')
    # 文档 §15 F2 明确交付含「1 基线」：contexts/baseline.json 是重构基线上下文，不是冗余文件
    if (L.FIXTURE / 'contexts' / 'baseline.json').is_file():
        declared.add('contexts/baseline.json')
    disk = set(rels)
    res['declared_not_on_disk'] = sorted(declared - disk)
    res['on_disk_not_declared'] = sorted(disk - declared)
    res['fixture_set_matches_declaration'] = not res['declared_not_on_disk'] and \
        not res['on_disk_not_declared']

    # ---------- 5) 拼写别名（r4 F2）：每条 alias 都在内容里，大小写变体各自独立文件
    alias_rows = [c for c in prop_cases if c.get('alias_key')]
    alias_bad = []
    for c in alias_rows:
        pp = L.FIXTURE / c['dir'] / c['proposal_file']
        try:
            doc = L.load(pp)
        except Exception as e:  # pragma: no cover
            alias_bad.append({'name': c['name'], 'what': 'unreadable', 'err': str(e)})
            continue
        keys = [k for _, k in walk_keys(doc)]
        if c['alias_key'] not in keys:
            alias_bad.append({'name': c['name'], 'alias': c['alias_key'], 'what': 'alias_not_in_content'})
    res['alias_case_count'] = len(alias_rows)
    res['alias_errors'] = alias_bad
    # 只在大小写上不同的别名必须有不同路径/inode/内容（Entity_Id vs ENTITY_ID 回归）
    groups = {}
    for c in alias_rows:
        groups.setdefault(c['alias_key'].casefold(), []).append(c)
    case_only_groups = {k: v for k, v in groups.items() if len({x['alias_key'] for x in v}) > 1}
    pair_checks = []
    for k, v in case_only_groups.items():
        rows = []
        for c in v:
            pp = L.FIXTURE / c['dir'] / c['proposal_file']
            st = pp.stat()
            rows.append({'name': c['name'], 'alias': c['alias_key'], 'file': c['proposal_file'],
                         'inode': st.st_ino, 'sha256': L.sha_file(pp),
                         'pin': c['context_sha256'], 'ctx_file': c['context_file']})
        distinct = (len({r['file'] for r in rows}) == len(rows) and
                    len({r['inode'] for r in rows}) == len(rows) and
                    len({r['sha256'] for r in rows}) == len(rows))
        pair_checks.append({'casefold': k, 'rows': rows, 'distinct': distinct})
    res['alias_case_pairs'] = pair_checks
    # 专门回归 B5 F2：Entity_Id / ENTITY_ID 两个拼写是否都有独立产物
    ent = [c for c in alias_rows if c['alias_key'] in ('Entity_Id', 'ENTITY_ID')]
    res['b5F2_entity_id_pair'] = [
        {'name': c['name'], 'alias': c['alias_key'], 'file': c['proposal_file'],
         'inode': (L.FIXTURE / c['dir'] / c['proposal_file']).stat().st_ino,
         'sha256': L.sha_file(L.FIXTURE / c['dir'] / c['proposal_file']),
         'context_file': c['context_file'], 'pin': (c['context_sha256'] or '')[:16]}
        for c in ent]
    res['all_fixture_names_lowercase'] = all(r == r.lower() for r in rels)
    res['name_has_numeric_prefix'] = all(
        r.split('/')[-1].split('_')[0].isdigit() or r.split('/')[-1] in ('baseline.json',
                                                                          'EXPECTATIONS.json')
        for r in rels)
    # 盘上每个文件名在大小写不敏感卷上都唯一（casefold 已查），且引用的 66 个拼写别名都在内容里
    res['alias_spelling_groups'] = {k: [x['alias_key'] for x in v]
                                    for k, v in sorted(case_only_groups.items())}

    # ---------- 6) SHA256SUMS.txt 逐行重算
    sums = (L.ROOT / 'reports/V9-B1/SHA256SUMS.txt').read_text(encoding='utf-8').splitlines()
    sections, cur = {}, 'preamble'
    sections[cur] = []
    for line in sums:
        if line.startswith('## '):
            cur = line[3:].strip()
            sections[cur] = []
        else:
            sections[cur].append(line)
    row_bad, rows = [], 0
    for sec in ('交付物（raw / jcs）', '只读输入（raw / jcs）', '夹具（raw / JCS 上下文身份）'):
        for line in sections.get(sec, []):
            if not line.strip() or 'RAW_SHA256' in line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                row_bad.append({'sec': sec, 'line': line, 'what': 'parse'})
                continue
            raw, jcs_col, path = parts[0], parts[1], parts[2]
            rows += 1
            p = L.ROOT / path
            if not p.is_file():
                row_bad.append({'sec': sec, 'path': path, 'what': 'missing'})
                continue
            if L.sha_file(p) != raw:
                row_bad.append({'sec': sec, 'path': path, 'what': 'raw_mismatch',
                                'claimed': raw, 'actual': L.sha_file(p)})
            if jcs_col != '-':
                try:
                    if L.jcs_sha(L.load(p)) != jcs_col:
                        row_bad.append({'sec': sec, 'path': path, 'what': 'jcs_mismatch'})
                except Exception as e:
                    if not jcs_col.startswith('jcs_error:'):
                        row_bad.append({'sec': sec, 'path': path, 'what': 'jcs_exc:' + type(e).__name__})
    res['sums_total_data_lines'] = len([l for l in sums if l.strip()])
    res['sums_rows_checked'] = rows
    res['sums_errors'] = row_bad
    res['sums_sections'] = {k: len([l for l in v if l.strip()]) for k, v in sections.items()}

    # ---------- 7) 报告/指标/relay 数据里的哈希 vs 磁盘
    metrics = L.load(L.ROOT / 'reports/V9-B1/metrics.json')
    hash_report = []
    for rel, h in (metrics.get('artifacts') or {}).items():
        p = L.ROOT / rel
        actual = L.sha_file(p) if p.is_file() else 'MISSING'
        hash_report.append({'source': 'metrics.artifacts', 'path': rel, 'claimed': h,
                            'actual': actual, 'match': h == actual})
    for rel, h in (metrics.get('inputs_read_only') or {}).items():
        candidates = [L.ROOT / rel]
        if '...' in rel and rel.startswith('AinerRelay/'):
            base = Path('/Users/mac/AinerWorkFlow/AinerRelay')
            name = rel.rsplit('/', 1)[-1]
            candidates.extend(sorted(base.rglob(name)))
        if rel.startswith('AnimeWorldZero/'):
            candidates.append(Path('/Users/mac/AinerWorkFlow') / rel)
        p = next((c for c in candidates if c.is_file()), None)
        actual = L.sha_file(p) if p else 'MISSING'
        hash_report.append({'source': 'metrics.inputs_read_only', 'path': rel, 'claimed': h,
                            'actual': actual, 'match': h == actual})
    # B4 在接力台 report 里声明的 artifacts 也应与磁盘一致
    import subprocess
    try:
        rp = subprocess.run([L.VENV_PY, '-I', '/Users/mac/AinerWorkFlow/AinerRelay/bin/relay',
                             '--json', 'show', 'ainerzero.V9.B4', '--full'],
                            capture_output=True, text=True, timeout=30)
        relay_payload = json.loads(rp.stdout) if rp.stdout.strip() else None
    except Exception:
        relay_payload = None
    relay_artifacts = None
    if relay_payload:
        relay_artifacts = (relay_payload.get('result_data') or {}).get('artifacts')
    if relay_artifacts:
        for rel, h in relay_artifacts.items():
            p = L.ROOT / rel
            actual = L.sha_file(p) if p.is_file() else 'MISSING'
            hash_report.append({'source': 'relay.V9.B4.report.data.artifacts', 'path': rel,
                                'claimed': h, 'actual': actual, 'match': h == actual})
    res['hash_report'] = hash_report
    res['hash_report_mismatches'] = [x for x in hash_report if not x['match']]

    # ---------- 8) check_result.json 计数 vs EXPECTATIONS 重算
    cr = L.load(L.ROOT / 'reports/V9-B1/check_result.json')
    counts = cr['counts']
    rules = Counter(c['rule'] for c in prop_cases if c['rule'])
    ctrl_rows = [c for c in prop_cases if c.get('control')]
    res['recount'] = {
        'cases_total': len(prop_cases),
        'positive_cases': res['proposal_cases']['valid'],
        'negative_cases': res['proposal_cases']['invalid'],
        'distinct_rules': len(rules),
        'control_rows': len(ctrl_rows),
        'reply_cases': len(reply_cases),
        'reply_negative': res['reply_cases']['invalid'],
    }
    res['counts_match'] = {
        'cases_total': counts['cases_total'] == res['recount']['cases_total'],
        'positive_cases': counts['positive_cases'] == res['recount']['positive_cases'],
        'negative_cases': counts['negative_cases'] == res['recount']['negative_cases'],
        'distinct_rules': counts['distinct_rules_with_counterexample'] == res['recount']['distinct_rules'],
        'controls': counts['controls'] == res['recount']['control_rows'],
        'reply_cases': counts['reply_cases'] == res['recount']['reply_cases'],
    }
    res['rules'] = dict(sorted(rules.items()))
    res['check_result_all_ok'] = cr.get('all_ok')
    res['check_result_failures'] = cr.get('failures')
    res['check_result_control_failures'] = cr.get('control_failures')
    res['check_result_nonisolated_reasons'] = cr.get('controls_non_isolated_by_design')
    res['author_counts'] = counts

    # ---------- 9) TTL 边界夹具的 tick 值（供 B1 闭区间复核引用）
    ttl_rows = []
    for c in prop_cases:
        if not c['name'].startswith(('valid_ttl', 'ttl_')):
            continue
        pp = L.FIXTURE / c['dir'] / c['proposal_file']
        cp = L.FIXTURE / 'contexts' / c['context_file']
        p, ctx = L.load(pp), L.load(cp)
        ttl_rows.append({'name': c['name'], 'dir': c['dir'],
                         'basis_t_ticks': p['basis']['t_ticks'], 'ttl_ticks': p['ttl_ticks'],
                         'current_tick': ctx['round']['current_tick'],
                         'right_endpoint': p['basis']['t_ticks'] + p['ttl_ticks']})
    res['ttl_boundary_rows'] = ttl_rows

    L.write_json(RES / 'fixture_results.json', res)
    print(json.dumps({k: res[k] for k in ('file_count', 'top_dirs', 'proposal_cases', 'reply_cases',
                                         'no_collision', 'unique_inodes', 'count_consistent_236',
                                         'alias_case_count', 'sums_rows_checked',
                                         'hash_report_mismatches', 'counts_match',
                                         'check_result_all_ok', 'declared_not_on_disk',
                                         'on_disk_not_declared', 'b5F2_entity_id_pair')},
                     ensure_ascii=False, indent=1))
    print('alias pairs distinct:', [(x['casefold'], x['distinct']) for x in pair_checks])
    print('sums errors:', res['sums_errors'][:5], 'count', len(res['sums_errors']))
    print('case errors:', res['case_pin_sha_errors'][:5], 'count', len(res['case_pin_sha_errors']))
    ok = (res['count_consistent_236'] and res['no_collision'] and res['fixture_set_matches_declaration']
          and not res['sums_errors'] and not res['case_pin_sha_errors'] and all(res['counts_match'].values()))
    print('FIXTURE_VERDICT', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
