"""B8 阶段 D：fixture / suite JSON 入口的重复键行为（隔离副本里做，不动真实交付物）。

D1. 篡改已提交夹具（committed fixtures）某个 JSON 加同值重复键 → suite 行为；
D2. 篡改 suite 的回归输入 reports/V-V9-B1/probe_variants.json 加同值重复键 → suite 行为；
D3. 在夹具目录新增一个重复键 JSON 文件 → suite 行为；
D2b. 候选 strict 副本（rescue: 关掉 suite 的 strict 读入）→ 同一 D2 输入是否无 traceback 完成
     （证明 strict 载入是承重守卫，且失败模式是未捕获异常而不是异常退出）。
每次运行记录 argv/rc/stdout/stderr/traceback/耗时；全部在 /tmp 隔离副本。
""" 
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L

HERE = Path(__file__).resolve().parents[1]
TMP = Path('/tmp/b8-suite-tamper')
LOG = L.RunLog('D-fixture-suite')
TB = 'Traceback (most recent call last)'
Q = chr(34) * 3


def build_repo(root):
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(L.CAND_DIR, root / 'reports/V9-B1/r5-candidate')
    shutil.copytree(L.ROOT / 'contracts/v9', root / 'contracts/v9')
    (root / 'reports/V-V9-B1').mkdir(parents=True)
    shutil.copy2(L.ROOT / 'reports/V-V9-B1/probe_variants.json', root / 'reports/V-V9-B1/probe_variants.json')
    (root / 'docs/v9').mkdir(parents=True)
    for rel in ('docs/v9/SKILL_PROPOSAL.md', 'docs/v9/SKILL_PROPOSAL_COORDINATION.md',
                'docs/v9/TEACHERS_AND_CACHE.md', 'ARCHITECTURE_V9.md'):
        src = L.ROOT / rel
        if src.is_file():
            shutil.copy2(src, root / rel)
    return root / 'reports/V9-B1/r5-candidate'


def run_suite(script, label):
    rec = L.run([L.PY, '-I', str(script), '--suite'], timeout=2400)
    rec['label'] = label
    rec['has_traceback'] = TB in rec['stderr']
    try:
        rec['parsed'] = json.loads(rec['stdout'])
    except Exception:
        rec['parsed'] = None
    LOG.add('suite-run', **{k: v for k, v in rec.items() if k != 'parsed'})
    return rec


def short(rec):
    p = rec.get('parsed') or {}
    return {'label': rec['label'], 'rc': rec['rc'], 'has_traceback': rec['has_traceback'],
            'all_ok': p.get('all_ok'), 'failures_head': (p.get('failures') or [])[:3],
            'stderr_head': rec['stderr'][:300].replace('\n', ' | '),
            'stdout_head': rec['stdout'][:300], 'duration_s': rec['duration_s']}


def patch_suite_strict_off(cand_path):
    """把 suite 读入 probe 与夹具 JSON 的 strict 去掉（只用于破坏对照副本）。"""
    src = cand_path.read_text(encoding='utf-8')
    subs = [
        ("probes = load_json(probe_path, strict=True)", "probes = load_json(probe_path)"),
        ("p = load_json(target_fixture / 'valid' / row['proposal_file'], strict=True)",
         "p = load_json(target_fixture / 'valid' / row['proposal_file'])"),
        ("obj = load_json(p, strict=True)", "obj = load_json(p)"),
    ]
    for old, new in subs:
        assert old in src, old
        src = src.replace(old, new)
    out = cand_path.with_name('check_skill_proposal_nostrict.py')
    out.write_text(src, encoding='utf-8')
    return out


def main():
    repo = build_repo(TMP / 'repo')
    results = {}
    # ---------- D1：篡改已提交夹具（同值重复键） ----------
    fix = repo / 'fixtures/valid/01_valid_minimal_handle_target.json'
    obj = L.load_json(fix)
    text = json.dumps(obj, ensure_ascii=False, indent=2) + '\n'
    anchor = '  "confidence": 0.6,'
    assert anchor in text
    fix.write_text(text.replace(anchor, anchor + '\n' + anchor), encoding='utf-8')
    r = run_suite(repo / 'check_skill_proposal.py', 'd1-fixture-dup-tamper')
    results['d1_fixture_dup'] = short(r)
    results['d1_fixture_dup']['stdout_contains_FIXTURE_MISMATCH'] = 'FIXTURE MISMATCH' in r['stdout']
    # 还原 D1 篡改
    L.write_json(fix, obj)

    # ---------- D3：新增重复键夹具文件 ----------
    extra = repo / 'fixtures/valid/999_extra_dup.json'
    prop = L.load_json(repo / 'fixtures/valid/01_valid_minimal_handle_target.json')
    txt = json.dumps(prop, ensure_ascii=False, indent=2) + '\n'
    txt = txt.replace(anchor, anchor + '\n' + anchor)
    extra.write_text(txt, encoding='utf-8')
    r3 = run_suite(repo / 'check_skill_proposal.py', 'd3-extra-fixture-dup')
    results['d3_extra_fixture_dup'] = short(r3)
    results['d3_extra_fixture_dup']['stdout_contains_FIXTURE_MISMATCH'] = 'FIXTURE MISMATCH' in r3['stdout']
    extra.unlink()

    # ---------- D2：篡改 suite 回归输入 probe_variants.json（同值重复键） ----------
    probe = TMP / 'repo/reports/V-V9-B1/probe_variants.json'
    pobj = L.load_json(probe)
    first = pobj[0]
    ptext = json.dumps(pobj, ensure_ascii=False, indent=2) + '\n'
    key = first['key']
    # 在文件里第一个 "key": "..." 之后插入同值重复键
    needle = '    "key": ' + json.dumps(key, ensure_ascii=False) + ','
    if needle not in ptext:
        needle = '"key": ' + json.dumps(key, ensure_ascii=False) + ','
    assert needle in ptext, 'probe key anchor missing'
    probe.write_text(ptext.replace(needle, needle + '\n' + needle, 1), encoding='utf-8')
    r2 = run_suite(repo / 'check_skill_proposal.py', 'd2-probe-dup-tamper')
    results['d2_probe_dup'] = short(r2)
    # 还原 probe，再生成 strict-off 副本
    shutil.copy2(L.ROOT / 'reports/V-V9-B1/probe_variants.json', probe)
    probe.write_text(ptext.replace(needle, needle + '\n' + needle, 1), encoding='utf-8')
    nostrict = patch_suite_strict_off(repo / 'check_skill_proposal.py')
    r2b = run_suite(nostrict, 'd2b-probe-dup-nostrict')
    results['d2b_probe_dup_nostrict'] = short(r2b)
    results['d2b_probe_dup_nostrict']['patched_sha256'] = L.sha(nostrict)

    # 断言
    checks = [
        {'label': 'd1', 'ok': results['d1_fixture_dup']['rc'] == 1
         and results['d1_fixture_dup']['stdout_contains_FIXTURE_MISMATCH']
         and not results['d1_fixture_dup']['has_traceback']},
        {'label': 'd3', 'ok': results['d3_extra_fixture_dup']['rc'] == 1
         and results['d3_extra_fixture_dup']['stdout_contains_FIXTURE_MISMATCH']
         and not results['d3_extra_fixture_dup']['has_traceback']},
        {'label': 'd2-strict-traceback', 'ok': results['d2_probe_dup']['rc'] == 1
         and results['d2_probe_dup']['has_traceback']},
        {'label': 'd2b-nostrict-no-traceback-completes',
         'ok': results['d2b_probe_dup_nostrict']['has_traceback'] is False
         and results['d2b_probe_dup_nostrict']['rc'] == 0
         and results['d2b_probe_dup_nostrict']['all_ok'] is True},
    ]
    summary = {'identity': L.py_identity(), 'results': results, 'checks': checks,
               'checks_failed': [c for c in checks if not c['ok']],
               'all_checks_ok': all(c['ok'] for c in checks),
               'note': 'D2/D2b 各跑一遍完整 suite；D1/D3 在夹具字节比对层提前返回。'}
    LOG.save_summary(summary)
    print(json.dumps({'results': results, 'checks': checks,
                      'all_ok': summary['all_checks_ok']}, ensure_ascii=False, indent=1))
    return 0 if summary['all_checks_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
