"""B8 阶段 A：身份与字节不变性（独立重算，不采作者结论）。

A1. 原 r4 交付清单 reports/V9-B1/SHA256SUMS.txt 全部数据行逐行重算（RAW + JCS 列）。
A2. 原 r4 交付物/夹具 对比 B6 独立复核已验收的 baseline_manifest.json（非 B7 作者记录）。
A3. r4 vs r5-candidate：脚本字节差异、夹具/破坏 schema 差异、候选清单逐行重算（含逻辑路径重映射口径）。
A4. AWZ 只读来源身份：真实文件 == 候选 pin 的内容 SHA（只读，不改）。
A5. r4 交付树是否有 B6 复核后新增/改动的字节（mtime + 清单外文件）。
A6. 候选 metrics.json / check_result.json / REPORT.md 内部声明一致性。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

OUT = {}
log = L.RunLog('A-identity')


def parse_manifest(path):
    """解析 write_sha_manifest 的 RAW/JCS/PATH 三列格式。"""
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith('RAW_SHA256'):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        raw, jcs_col, p = parts[0], parts[1], line[line.find(parts[2], line.find(parts[1]) + len(parts[1])):].strip()
        # 更稳：按 2+ 空格切
        segs = [s for s in line.split('  ') if s.strip() != '']
        if len(segs) >= 3:
            raw, jcs_col, p = segs[0].strip(), segs[1].strip(), segs[2].strip()
        rows.append({'raw': raw, 'jcs': jcs_col, 'path': p})
    return rows


def verify_manifest(manifest_path, resolve, label):
    rows = parse_manifest(manifest_path)
    res = {'label': label, 'manifest': str(manifest_path), 'rows': len(rows),
           'raw_ok': 0, 'raw_mismatch': [], 'jcs_ok': 0, 'jcs_mismatch': [], 'missing': [],
           'missing_rows': [], 'jcs_error_rows': []}
    for r in rows:
        target = resolve(r['path'])
        if r['raw'] == 'MISSING':
            res['missing_rows'].append(r['path'])
            continue
        if not target.is_file():
            res['missing'].append({'path': r['path'], 'resolved': str(target)})
            continue
        actual = L.sha(target)
        if actual == r['raw']:
            res['raw_ok'] += 1
        else:
            res['raw_mismatch'].append({'path': r['path'], 'manifest': r['raw'],
                                        'actual': actual, 'resolved': str(target)})
        if r['jcs'].startswith('jcs_error:'):
            res['jcs_error_rows'].append({'path': r['path'], 'col': r['jcs']})
            continue
        if r['jcs'] == '-':
            continue
        if target.suffix == '.json':
            try:
                actual_j = L.jcs_sha(L.load_json(target))
            except Exception as exc:
                res['jcs_mismatch'].append({'path': r['path'], 'reason': 'recompute:' + type(exc).__name__})
                continue
            if actual_j == r['jcs']:
                res['jcs_ok'] += 1
            else:
                res['jcs_mismatch'].append({'path': r['path'], 'manifest': r['jcs'], 'actual': actual_j})
        else:
            res['jcs_mismatch'].append({'path': r['path'], 'reason': 'jcs_on_non_json:' + r['jcs']})
    log.add('manifest', **res)
    return res


# ---------------------------------------------------------------- A1
def a1_r4_manifest():
    resolve_cache = {}

    def resolve(p):
        if p.startswith('/'):
            return Path(p)
        return L.ROOT / p
    return verify_manifest(L.R4_DIR / 'SHA256SUMS.txt', resolve, 'r4-manifest')


# ---------------------------------------------------------------- A2
def a2_b6_baseline():
    base = json.load(open(L.ROOT / 'reports/V-V9-B1/r4-independent/results/baseline_manifest.json'))
    rows = base['deliverables_and_inputs']
    miss, bad = [], []
    for x in rows:
        p = Path(x['path']) if x['path'].startswith('/') else L.ROOT / x['path']
        if not p.is_file():
            miss.append(x['path'])
            continue
        if L.sha(p) != x['sha256'] or p.stat().st_size != x['size']:
            bad.append({'path': x['path'], 'want': x['sha256'], 'got': L.sha(p)})
    fixture_dir = L.ROOT / 'contracts/v9/examples/skill_proposal_v1'
    fmiss, fbad = [], []
    for x in base['fixture_tree']:
        p = fixture_dir / x['rel']
        if not p.is_file():
            fmiss.append(x['rel'])
            continue
        if L.sha(p) != x['sha256'] or p.stat().st_size != x['size']:
            fbad.append({'rel': x['rel'], 'want': x['sha256'], 'got': L.sha(p)})
    sab_base = base.get('sabotage_schemas') or []
    sdir = L.R4_DIR / 'sabotage-schemas'
    smiss, sbad = [], []
    for x in sab_base:
        rel = x if isinstance(x, str) else (x.get('rel') or x.get('path'))
        p = sdir / rel
        want = None if isinstance(x, str) else x['sha256']
        if not p.is_file():
            smiss.append(rel)
            continue
        if want is not None and L.sha(p) != want:
            sbad.append({'rel': rel, 'want': want, 'got': L.sha(p)})
    res = {'deliverables_checked': len(rows), 'deliverables_missing': miss, 'deliverables_mismatch': bad,
           'fixtures_checked': len(base['fixture_tree']), 'fixtures_missing': fmiss,
           'fixtures_mismatch': fbad, 'sabotage_checked': len(sab_base),
           'sabotage_missing': smiss, 'sabotage_mismatch': sbad,
           'b6_captured_at_utc': base.get('captured_at_utc')}
    res['ok'] = not (miss or bad or fmiss or fbad or smiss or sbad)
    log.add('b6-baseline', **res)
    return res


# ---------------------------------------------------------------- A3
def a3_candidate_vs_r4():
    cand = L.CAND
    r4 = L.R4
    diff = L.run(['diff', '-u', str(r4), str(cand)])
    added = sum(1 for ln in diff['stdout'].splitlines() if ln.startswith('+') and not ln.startswith('+++'))
    removed = sum(1 for ln in diff['stdout'].splitlines() if ln.startswith('-') and not ln.startswith('---'))
    diff_text = diff['stdout']
    diff_res = {'r4_sha256': L.sha(r4), 'candidate_sha256': L.sha(cand),
                'diff_rc': diff['rc'], 'added_lines': added, 'removed_lines': removed,
                'diff_saved': str(L.RESULTS / 'candidate-vs-r4.diff')}
    L.write_text(L.RESULTS / 'candidate-vs-r4.diff', diff_text)

    # 夹具/破坏 schema 差异（同相对路径逐字节）
    def tree_rel(base):
        return {str(p.relative_to(base)): L.sha(p) for p in Path(base).rglob('*') if p.is_file()}

    r4_fix = tree_rel(L.ROOT / 'contracts/v9/examples/skill_proposal_v1')
    cand_fix = tree_rel(L.CAND_DIR / 'fixtures')
    fix_diff = {'r4_files': len(r4_fix), 'cand_files': len(cand_fix),
                'only_r4': sorted(set(r4_fix) - set(cand_fix)),
                'only_cand': sorted(set(cand_fix) - set(r4_fix)),
                'byte_diff': sorted(k for k in set(r4_fix) & set(cand_fix) if r4_fix[k] != cand_fix[k])}
    r4_sab = tree_rel(L.R4_DIR / 'sabotage-schemas')
    cand_sab = tree_rel(L.CAND_DIR / 'sabotage-schemas')
    sab_diff = {'r4_files': len(r4_sab), 'cand_files': len(cand_sab),
                'only_r4': sorted(set(r4_sab) - set(cand_sab)),
                'only_cand': sorted(set(cand_sab) - set(r4_sab)),
                'byte_diff': sorted(k for k in set(r4_sab) & set(cand_sab) if r4_sab[k] != cand_sab[k])}

    # 候选清单逐行重算：说明作者清单的"逻辑路径"口径（交付物列按候选目录映射，不是原 r4 物理路径）
    logical = {'reports/V9-B1/check_skill_proposal.py': L.CAND,
               'reports/V9-B1/check_result.json': L.CAND_DIR / 'check_result.json',
               'reports/V9-B1/metrics.json': L.CAND_DIR / 'metrics.json',
               'reports/V9-B1/REPORT.md': L.CAND_DIR / 'REPORT.md',
               'reports/V9-B1/COORDINATOR_DECISIONS.md': L.CAND_DIR / 'COORDINATOR_DECISIONS.md',
               'reports/V9-B1/r4/SUMMARY.md': L.CAND_DIR / 'r4' / 'SUMMARY.md',
               'contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json': L.CAND_DIR / 'fixtures' / 'EXPECTATIONS.json'}

    def resolve(p):
        if p in logical:
            return logical[p]
        if p.startswith('/'):
            return Path(p)
        return L.ROOT / p
    cand_manifest = verify_manifest(L.CAND_DIR / 'SHA256SUMS.txt', resolve, 'candidate-manifest')

    # 候选清单中的"逻辑路径"与实际原 r4 文件的撞名核对：清单第 13 行说 reports/V9-B1/check_skill_proposal.py
    # 是候选字节；磁盘上同路径是原 r4 字节。记录撞名表。
    collisions = []
    for p, target in logical.items():
        phys = L.ROOT / p
        if phys.is_file():
            collisions.append({'label': p, 'manifest_resolves_to': str(target.relative_to(L.ROOT)),
                               'actual_physical_file': str(phys.relative_to(L.ROOT)),
                               'phys_sha256': L.sha(phys), 'label_target_sha256': L.sha(target) if target.is_file() else None})
    # 清单第 13 行原始文本
    row13 = [ln for ln in (L.CAND_DIR / 'SHA256SUMS.txt').read_text().splitlines()
             if 'reports/V9-B1/check_skill_proposal.py' in ln]
    res = {'script': diff_res, 'fixtures': fix_diff, 'sabotage': sab_diff,
           'candidate_manifest': cand_manifest, 'logical_path_collisions': collisions,
           'candidate_manifest_checker_line': row13,
           'original_r4_physical_checker_sha256': L.sha(L.R4)}
    log.add('candidate-vs-r4', **res)
    return res


# ---------------------------------------------------------------- A4
def a4_awz_source():
    real = L.AWZ_OBSERVATION
    got = L.sha(real)
    pinned = '01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb'
    old_path_hash = L.sha_bytes(b'AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json')
    res = {'path': str(real), 'sha256': got, 'candidate_pinned_content_sha256': pinned,
           'match': got == pinned, 'legacy_path_hash_recomputed': old_path_hash,
           'legacy_expected': 'a2971c9a293701ae588053b88dffe817d450db45dc1d16527ccdf8b0ab1a26d6',
           'legacy_match': old_path_hash.startswith('a2971c9a')}
    log.add('awz-source', **res)
    return res


# ---------------------------------------------------------------- A5
def a5_r4_tree_extra():
    base = json.load(open(L.ROOT / 'reports/V-V9-B1/r4-independent/results/baseline_manifest.json'))
    known = set()
    for x in base['deliverables_and_inputs']:
        known.add(x['path'])
    fixture_dir = L.ROOT / 'contracts/v9/examples/skill_proposal_v1'
    for x in base['fixture_tree']:
        known.add(str((fixture_dir / x['rel']).relative_to(L.ROOT)))
    for x in (base.get('sabotage_schemas') or []):
        rel = x if isinstance(x, str) else (x.get('rel') or x.get('path'))
        known.add('reports/V9-B1/sabotage-schemas/' + rel)
    # 扫描 r4 交付目录（排除 r5-candidate 候选目录）与夹具目录里的额外文件
    extra = []
    for p in L.R4_DIR.rglob('*'):
        if not p.is_file():
            continue
        rel = str(p.relative_to(L.ROOT))
        if rel.startswith('reports/V9-B1/r5-candidate/'):
            continue
        if rel not in known:
            extra.append({'path': rel, 'mtime': p.stat().st_mtime, 'size': p.stat().st_size})
    # B6 复核后的 r4 文件 mtime 检查（B6 captured_at 05:24:35Z = 08:24:35+0300）
    import datetime as _dt
    cap = _dt.datetime.fromisoformat(base['captured_at_utc'].replace('Z', '+00:00')).timestamp()
    touched_after = []
    for rel in known:
        p = Path(rel) if rel.startswith('/') else L.ROOT / rel
        if not p.is_file():
            continue
        st = p.stat()
        if st.st_mtime > cap + 1.0:
            touched_after.append({'path': rel, 'mtime': st.st_mtime,
                                  'delta_s': round(st.st_mtime - cap, 1)})
    r3_archive = [x for x in extra if x['path'].startswith('reports/V9-B1/archive/')]
    pycache = [x for x in extra if '__pycache__' in x['path']]
    other_extra = [x for x in extra if x not in r3_archive and x not in pycache]
    res = {'extra_files_in_r4_tree': extra, 'files_touched_after_b6_capture': touched_after,
           'extra_r3_archive': r3_archive, 'extra_pycache': pycache, 'extra_other': other_extra,
           'b6_capture_epoch': cap, 'note': 'r5-candidate/ 目录本身是 B7 候选，排除在 r4 交付树外单独记录'}
    log.add('r4-tree-extra', **res)
    return res


# ---------------------------------------------------------------- A6
def a6_candidate_internals():
    metrics = L.load_json(L.CAND_DIR / 'metrics.json')
    check = L.load_json(L.CAND_DIR / 'check_result.json')
    report_sha = L.sha(L.CAND_DIR / 'REPORT.md')
    counts_m = metrics.get('counts') or {}
    counts_c = check.get('counts') or {}
    diffs = {k: {'metrics': counts_m.get(k), 'check_result': counts_c.get(k)}
             for k in sorted(set(counts_m) | set(counts_c)) if counts_m.get(k) != counts_c.get(k)}
    failures = check.get('failures') or []
    control_failures = check.get('control_failures') or []
    res = {'metrics_all_ok': metrics.get('all_ok'), 'check_result_all_ok': check.get('all_ok'),
           'count_keys_equal': sorted(counts_m) == sorted(counts_c),
           'count_diffs': diffs, 'failures': failures, 'control_failures': control_failures,
           'r4_unchanged_claim_in_metrics': metrics.get('r4_unchanged'),
           'source_sha256_content': metrics.get('source_sha256_content'),
           'candidate_report_sha256': report_sha,
           'author_manifest_report_sha256': next((r['raw'] for r in parse_manifest(L.CAND_DIR / 'SHA256SUMS.txt')
                                                   if r['path'] == 'reports/V9-B1/REPORT.md'), None),
           'checker_sha256': L.sha(L.CAND)}
    res['report_manifest_stale'] = (res['author_manifest_report_sha256'] != report_sha)
    res['ok'] = (metrics.get('all_ok') is True and check.get('all_ok') is True and
                 not failures and not control_failures and res['count_keys_equal'] and not diffs)
    log.add('candidate-internals', **res)
    return res


def main():
    out = {
        'identity': L.py_identity(),
        'a1_r4_manifest': a1_r4_manifest(),
        'a2_b6_baseline': a2_b6_baseline(),
        'a3_candidate_vs_r4': a3_candidate_vs_r4(),
        'a4_awz_source': a4_awz_source(),
        'a5_r4_tree_extra': a5_r4_tree_extra(),
        'a6_candidate_internals': a6_candidate_internals(),
    }
    log.save_summary(out)
    # 精简 stdout
    print(json.dumps({
        'r4_manifest': {k: out['a1_r4_manifest'][k] for k in ('rows', 'raw_ok', 'jcs_ok', 'raw_mismatch', 'jcs_mismatch', 'missing', 'jcs_error_rows')},
        'b6_baseline_ok': out['a2_b6_baseline']['ok'],
        'b6_baseline': {k: out['a2_b6_baseline'][k] for k in ('deliverables_checked', 'deliverables_missing', 'deliverables_mismatch', 'fixtures_checked', 'fixtures_mismatch', 'sabotage_checked', 'sabotage_mismatch')},
        'candidate_script': out['a3_candidate_vs_r4']['script'],
        'candidate_manifest': {k: out['a3_candidate_vs_r4']['candidate_manifest'][k] for k in ('rows', 'raw_ok', 'raw_mismatch', 'missing', 'jcs_mismatch', 'missing_rows', 'jcs_error_rows')},
        'fixtures_diff': {k: (v if not isinstance(v, list) else len(v)) for k, v in out['a3_candidate_vs_r4']['fixtures'].items()},
        'sabotage_diff': {k: (v if not isinstance(v, list) else len(v)) for k, v in out['a3_candidate_vs_r4']['sabotage'].items()},
        'awz': out['a4_awz_source'],
        'r4_extra': {'extra_files': out['a5_r4_tree_extra']['extra_files_in_r4_tree'],
                     'touched_after_b6': out['a5_r4_tree_extra']['files_touched_after_b6_capture']},
        'candidate_internals_ok': out['a6_candidate_internals']['ok'],
        'report_manifest_stale': out['a6_candidate_internals']['report_manifest_stale'],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
