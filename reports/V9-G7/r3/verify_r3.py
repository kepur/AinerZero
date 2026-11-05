"""Author-only CPU evidence; explicit fresh --out directory, never rewrites delivery."""
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/v9/mechanism'))
import ainerzero.v9.mechanism as pkg
import test_cmfl_r2_adversarial as adv
import test_cmfl_r3_integrity as integrity
from ainerzero.v9.mechanism.promotion_gate import FACTTEST_RECIPE_SHA

parser = argparse.ArgumentParser()
parser.add_argument('--out', required=True, type=Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
results = {'kind': 'author CPU evidence; no independent acceptance', 'recipe_sha': FACTTEST_RECIPE_SHA,
           'recovery': {}, 'mutations': {}}
stl = pkg.WeakFormSTLSQ(threshold=0.20)
for mode, cov in [('hard_default', None), ('gls_diagnostic_only', adv.PRIOR_COV)]:
    counts = {'parameter_false_discoveries': 0, 'structural_exact_support': 0,
              'g8like_structural_exact_support': 0, 'trials_per_cell': 10}
    for k in range(10):
        rng = np.random.default_rng(3000 + k)
        cand = stl.discover(adv._worlds(pkg, rng, 'P', 6, mech='none', coeff=0., phi_dev=True),
                            pkg.DEFAULT_PHI, rng=rng, nuisance_cov=cov)
        counts['parameter_false_discoveries'] += int(bool(cand.active_terms))
        rng = np.random.default_rng(4000 + k)
        cand = stl.discover(adv._worlds(pkg, rng, 'S', 6), pkg.DEFAULT_PHI, rng=rng, nuisance_cov=cov)
        counts['structural_exact_support'] += int(cand.active_terms == ('quadratic_drag',))
        rng = np.random.default_rng(600 + k)
        ctxs = adv._g8_like_drag_windows(rng, 6)
        cand = stl.discover(ctxs, pkg.DEFAULT_PHI, rng=np.random.default_rng(700+k), nuisance_cov=cov)
        counts['g8like_structural_exact_support'] += int(cand.active_terms == ('quadratic_drag',))
    results['recovery'][mode] = counts

mutations = {
    'F3_diagnostic_bypass': ('        if candidate.diagnostic_only:', '        if False:',
                            integrity.test_gls_diagnostic_candidate_cannot_promote),
    'F1_recipe_bypass': ('        elif not recipe_valid:', '        elif False:',
                         lambda: integrity.test_frozen_recipe_rejects_content_attacks('different_id')),
    'F2_history_bypass': ('        if t_worlds & self._used_test_worlds or t_content & self._used_test_contents:',
                          '        if False:', lambda: integrity.test_historical_world_and_content_replay_rejected(True)),
}
for name, (old, new, probe) in mutations.items():
    probe()  # true success control first
    with tempfile.TemporaryDirectory(prefix='g7-r3-mutant-') as tmp:
        dst = Path(tmp) / name
        shutil.copytree(ROOT / 'src/ainerzero/v9/mechanism', dst, ignore=shutil.ignore_patterns('__pycache__'))
        path = dst / 'promotion_gate.py'
        text = path.read_text()
        assert text.count(old) == 1
        path.write_text(text.replace(old, new))
        sys.path.insert(0, tmp)
        mutant = importlib.import_module(name)
        integrity.pkg = mutant
        caught = False
        try:
            probe()
        except BaseException as exc:
            caught = True
            results['mutations'][name] = {'caught': True, 'exception': type(exc).__name__, 'message': str(exc)[:600]}
        finally:
            integrity.pkg = pkg
            sys.path.remove(tmp)
        assert caught, name

# Fixed true mechanism positive and nonempty wrong mechanism negative.
d, c, t, cand = integrity.fixture()
nulls = pkg.build_facttest_null_controls(cand, d, adv._prior(pkg), adv._valid_lib(pkg))
gate = pkg.OneSidedPromotionGate(pkg.default_cmfl_registration())
dec = integrity.evaluate(gate, d, c, t, cand, nulls)
assert dec.admitted
from dataclasses import asdict, replace
results['positive'] = asdict(dec)
wrong = replace(cand, active_terms=('coulomb_friction',))
nulls_wrong = pkg.build_facttest_null_controls(wrong, d, adv._prior(pkg), adv._valid_lib(pkg))
neg = integrity.evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, wrong, nulls_wrong)
assert not neg.admitted
results['nonempty_wrong_control'] = asdict(neg)
results['fixture_sha'] = {'D': sorted(__import__('ainerzero.v9.mechanism.promotion_gate', fromlist=['_context_content'])._context_content(x) for x in d),
                         'nulls': [dict(terms=n.active_terms, coefficients=n.coefficients.tolist()) for n in nulls]}
(args.out / 'metrics.json').write_text(json.dumps(results, indent=2, allow_nan=False))
print(json.dumps({'recovery': results['recovery'], 'mutations': results['mutations'], 'positive': dec.admitted,
                  'wrong': neg.admitted}, indent=2))
