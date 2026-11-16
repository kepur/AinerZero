"""P262-sub reviewer tests (SYNTHETIC; run only inside an isolated copy, next to test_s6_prereg.py).

Reuses the author's synthetic fixture (real builder/helper/analysis, temporary synthetic git repo) and adds
reviewer-designed cases the author's suite does not contain. Each refusal case starts from the fixture that
the author's suite shows is ACCEPTED, so a refusal is attributable to the injected defect; the expected
refusal message is asserted, not just "some exception".
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from test_s6_prereg import (AN, B, PE, RAW, VERSIONS, case, invoke, report_path, rewrite,  # noqa: F401
                            synthetic_base, tree_hashes, update_report)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT).decode().strip()


def refuse(root, monkeypatch, match):
    before = tree_hashes(root)
    with pytest.raises(PE.EvidenceError, match=match):
        invoke(root, monkeypatch)
    assert not (root / 'candidate.json').exists()
    assert tree_hashes(root) == before


def rebind_cell(root, cell):
    update_report(root, lambda p: p['cells_sha256'].__setitem__(cell, B.GD.sha256_file(root / RAW / 'cells' / cell / 'cell.json')))


def rebind_eval(root, name):
    update_report(root, lambda p: p['files_sha256'].__setitem__(name, B.GD.sha256_file(root / RAW / 'eval-s6p1-probe' / name)))


def rebind_selection(root):
    """A consistent forger also recomputes the report's descriptive pick overlap (runner selection_summary)."""
    picks = {a: json.loads((root / RAW / f'cells/{a}-r0/cell.json').read_text())['tracks'][0]['picks'] for a in AN.ARMS}
    sel = {f'{a}-r0': [len(set(x) & set(y)) / max(len(x), 1) for x, y in zip(picks[a][1:], picks['E'][1:])]
           for a in ('R', 'Z', 'T', 'G')}
    update_report(root, lambda p: p.__setitem__('selection', sel))


# --- positive: what the generated preregistration freezes ----------------------------------------------------
def test_r0_positive_dump_and_manifest(case, monkeypatch):
    doc = invoke(case, monkeypatch)
    here = case / 'reports/V9-S6-PHASE1'
    m = doc['manifest']
    assert m['reports/V9-S6-PHASE1/make_prereg.py'] == B.GD.sha256_file(here / 'make_prereg.py')
    assert m['reports/V9-S6-PHASE1/prereg_evidence.py'] == B.GD.sha256_file(here / 'prereg_evidence.py')
    assert m['reports/V9-S6-DESIGN/DESIGN-r2.md'] == B.GD.sha256_file(case / 'reports/V9-S6-DESIGN/DESIGN-r2.md')
    code = B.GD.build_manifest(case, [here / 'run_s6p1.py'], src_root=case / 'src', extra=[here / 'verify_s6p1.py'])
    assert len(code) == 42 and doc['code_manifest_sha256'] == PE.manifest_sha(code)
    assert set(m) - set(code) == {'reports/V9-S6-PHASE1/make_prereg.py', 'reports/V9-S6-PHASE1/prereg_evidence.py',
                                  'reports/V9-S6-DESIGN/DESIGN-r2.md'}
    assert all(m[k] == v for k, v in code.items())
    assert doc['probe_evidence']['files_sha256']['reports/V9-S6-PHASE1/probe/EVAL-probe.json'] == doc['probe_report_sha256']
    dump = os.environ.get('P262_DUMP')
    if dump:
        Path(dump).write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True))


# --- legitimate variations that must still be accepted ---------------------------------------------------------
def test_r1_resumed_training_two_closed_ledger_rows_accepted(case, monkeypatch):
    def split(rows):
        r = rows[0]
        rows[:] = [{**r, 'start': 1000., 'last_beat': 2600., 'cells': r['cells'][:3]},
                   {**r, 'start': 5000., 'last_beat': 6600., 'cells': r['cells'][3:]}]
    rewrite(case, RAW + 'train-ledger.json', split)
    doc = invoke(case, monkeypatch)
    assert doc['probe_evidence']['training_ledger_seconds'] == 3200.


def test_r2_ledger_commit_identity(case, monkeypatch):
    # commit A changes a numerical file, commit B restores it: HEAD bytes == evaluated bytes, A differs.
    runner = case / 'reports/V9-S6-PHASE1/run_s6p1.py'
    original = runner.read_bytes()
    runner.write_bytes(original + b'\n# SYNTHETIC other training code\n')
    git(case, 'add', '-A', 'reports/V9-S6-PHASE1/run_s6p1.py')
    git(case, '-c', 'user.name=SYNTHETIC', '-c', 'user.email=s@example.invalid', 'commit', '-qm', 'A')
    commit_a = git(case, 'rev-parse', 'HEAD')
    runner.write_bytes(original)
    git(case, 'add', '-A', 'reports/V9-S6-PHASE1/run_s6p1.py')
    git(case, '-c', 'user.name=SYNTHETIC', '-c', 'user.email=s@example.invalid', 'commit', '-qm', 'B')
    head = git(case, 'rev-parse', 'HEAD')
    rewrite(case, RAW + 'train-ledger.json', lambda v: v[0].__setitem__('git_head', head))
    assert invoke(case, monkeypatch)['probe_evidence']['current_git_head'] == head
    (case / 'candidate.json').unlink()
    rewrite(case, RAW + 'train-ledger.json', lambda v: v[0].__setitem__('git_head', commit_a))
    refuse(case, monkeypatch, 'code differs at committed identity')


# --- reviewer-designed refusals --------------------------------------------------------------------------------
def test_r3_ledger_total_over_probe_cap(case, monkeypatch):
    rewrite(case, RAW + 'train-ledger.json', lambda v: v.append({**v[0], 'start': 10000., 'last_beat': 16000., 'cells': []}))
    refuse(case, monkeypatch, 'actual probe training exceeded cap')


def test_r4_t_picks_differ_from_r(case, monkeypatch):
    def change(rec):
        tr = rec['tracks'][0]
        tr['picks'][3] = list(range(20000, 23000))
        tr['revealed'] = [i for ids in tr['picks'] for i in ids]
        tr['reveal_log'] = [{'call': r, 'ids': ids} for r, ids in enumerate(tr['picks'])]
    rewrite(case, RAW + 'cells/T-r0/cell.json', change)
    rebind_cell(case, 'T-r0')
    rebind_selection(case)
    refuse(case, monkeypatch, 'T/R selections')


def test_r5_pick_out_of_pool_range(case, monkeypatch):
    def change(rec):
        tr = rec['tracks'][0]
        tr['picks'][3][0] = 60000
        tr['revealed'] = [i for ids in tr['picks'] for i in ids]
        tr['reveal_log'] = [{'call': r, 'ids': ids} for r, ids in enumerate(tr['picks'])]
    rewrite(case, RAW + 'cells/E-r0/cell.json', change)
    rebind_cell(case, 'E-r0')
    rebind_selection(case)
    refuse(case, monkeypatch, 'pick IDs')


def test_r6_runner_aborted_cell_dir_is_refused_fail_closed(case, monkeypatch):
    (case / RAW / 'cells/R-r0.aborted-1').mkdir()
    refuse(case, monkeypatch, 'raw cell directory set')


def test_r7_symlink_evidence_outside_repo(case, monkeypatch, tmp_path):
    outside = tmp_path / 'outside-pools.json'
    shutil.copyfile(case / RAW / 'pools.json', outside)
    (case / RAW / 'pools.json').unlink()
    (case / RAW / 'pools.json').symlink_to(outside)
    refuse(case, monkeypatch, 'evidence outside repository')


def test_r8_counts_dtype_float_refused(case, monkeypatch):
    p = case / RAW / 'eval-s6p1-probe/errors.npz'
    with np.load(p) as d:
        arr = {k: d[k] for k in d.files}
    arr['main6/counts'] = arr['main6/counts'].astype(np.float64)
    np.savez(p, **arr)
    rebind_eval(case, 'errors.npz')
    refuse(case, monkeypatch, 'main6/counts: array shape/type/range')


def test_r9_contact_share_above_one(case, monkeypatch):
    p = case / RAW / 'eval-s6p1-probe/verify.json'
    v = json.loads(p.read_text())
    v['replay']['G-r0']['contact_share'][0][2] = 1.5
    p.write_text(json.dumps(v, sort_keys=True))
    rebind_eval(case, 'verify.json')
    update_report(case, lambda pr: pr.__setitem__('verify', v))
    refuse(case, monkeypatch, 'contact share > 1')


def test_r10_pools_extra_replicate(case, monkeypatch):
    rewrite(case, RAW + 'pools.json', lambda v: v.__setitem__('1', 'c' * 64))
    refuse(case, monkeypatch, 'candidate pools: incorrect key set')


def test_r12_committed_runner_with_12h_final_cap_refused(case, monkeypatch):
    """Consistent world where the RUNNER itself (committed) raises the final cap and the probe evidence was
    produced by that runner: only the builder's literal 6h/1h pins can refuse it."""
    here = case / 'reports/V9-S6-PHASE1'
    runner = here / 'run_s6p1.py'
    src = runner.read_text()
    old = '"train_cap_s": 6.0 * 3600'
    assert src.count(old) == 1
    runner.write_text(src.replace(old, '"train_cap_s": 12.0 * 3600'))
    git(case, 'add', '-A', 'reports/V9-S6-PHASE1/run_s6p1.py')
    git(case, '-c', 'user.name=SYNTHETIC', '-c', 'user.email=s@example.invalid', 'commit', '-qm', '12h')
    head = git(case, 'rev-parse', 'HEAD')
    code = B.GD.build_manifest(case, [runner], src_root=case / 'src', extra=[here / 'verify_s6p1.py'])
    sha = PE.manifest_sha(code)
    rewrite(case, RAW + 'train-ledger.json', lambda v: v[0].__setitem__('code_manifest_sha256', sha))
    # the forged runner's sets, as the runner itself would report them (pins bypassed for this read only)
    monkeypatch.setattr(PE, 'same', lambda a, e, label: None if label in ('final training cap',) else ORIG_SAME(a, e, label))
    sets = PE.source_sets(case)
    monkeypatch.setattr(PE, 'same', ORIG_SAME)
    assert sets['final']['train_cap_s'] == 43200.0
    update_report(case, lambda p: p.update(sets=sets, code_manifest_sha256=sha, git_head=head))
    refuse(case, monkeypatch, 'final training cap')


ORIG_SAME = PE.same


def test_r13_replay_first_ok_false_but_passed_true(case, monkeypatch):
    p = case / RAW / 'eval-s6p1-probe/verify.json'
    v = json.loads(p.read_text())
    v['replay']['Z-r0']['first_ok'] = False
    p.write_text(json.dumps(v, sort_keys=True))
    rebind_eval(case, 'verify.json')
    update_report(case, lambda pr: pr.__setitem__('verify', v))
    refuse(case, monkeypatch, 'first picks replay')


@pytest.mark.parametrize('elapsed,ok', [(3600, True), (3600.01, False)])
def test_r11_probe_eval_wall_clock_boundary(case, monkeypatch, elapsed, ok):
    update_report(case, lambda p: p.__setitem__('elapsed_s', elapsed))
    if ok:
        invoke(case, monkeypatch)
    else:
        refuse(case, monkeypatch, 'inconsistent/excessive eval wall clock')


# --- characterisation (what is NOT checked; documented, not asserted as desired) -------------------------------
def test_c1_report_verify_seconds_downward_edit_is_accepted(case, monkeypatch):
    """Self-reported verify/eval timings have no raw anchor: one positive edit lowers the estimate."""
    base = invoke(case, monkeypatch)['budget']['estimated_eval_s']
    (case / 'candidate.json').unlink()
    update_report(case, lambda p: p.__setitem__('verify_seconds', 1.0))
    doc = invoke(case, monkeypatch)
    assert doc['budget']['estimated_eval_s'] < base
    print('C1 estimated_eval_s', base, '->', doc['budget']['estimated_eval_s'])


def test_c2_cell_record_extra_key_is_accepted(case, monkeypatch):
    rewrite(case, RAW + 'cells/R-r0/cell.json', lambda v: v.__setitem__('forged_note', 'anything'))
    rebind_cell(case, 'R-r0')
    invoke(case, monkeypatch)


def test_c3_report_extra_top_level_key_is_accepted(case, monkeypatch):
    update_report(case, lambda p: p.__setitem__('late_violations', ['changed: something']))
    invoke(case, monkeypatch)
