from pathlib import Path
import json,hashlib,subprocess
text=Path(__file__).with_name('review.py').read_text().split('fixture_identity={}')[0]
text=text.replace("P=load('g9baseline')", "spec=importlib.util.spec_from_file_location('g9suppbase',OUT/'isolated/g9baseline/__init__.py',submodule_search_locations=[str(OUT/'isolated/g9baseline')]); P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)")
exec(compile(text,str(Path(__file__).with_name('review.py')),'exec'))
# Reuse independently written evaluator without executing original evidence runner.
source=Path(__file__).with_name('review.py').read_text();exec(source[source.index('def evaluate('):source.index("results={'scope'")])
res={}
p=load('g9mut_elond_bypass',[('promotion_gate.py','e_lond_passed = bool(e_pers >= e_threshold)','e_lond_passed = True')])
a=evaluate(tests=T[:12]);b=evaluate(p,tests=T[:12]);res['elond_only_bypass']={'baseline':a,'mutant':b,'admission_flips':not a.admitted and b.admitted}
# Proper wrong-law isolation: enough worlds for e-LOND, so FactTest is sole rejection.
wrong=candidate(term='coulomb_friction',coef=.45)
wt=gen('wrong360',360,286001)
a=evaluate(cand=wrong,tests=wt)
p=load('g9mut_facttest_bypass',[('promotion_gate.py','facttest_passed = bool(math.isfinite(thr) and ft_score > thr)','facttest_passed = True')])
b=evaluate(p,cand=candidate(p,term='coulomb_friction',coef=.45),tests=wt)
res['wrong_law_facttest_only_bypass']={'baseline':a,'mutant':b,'admission_flips':not a.admitted and b.admitted}
# Truth changes held entirely outside the learner-visible observation, compare full records.
c=D[0];records=[]
for i in range(4):
    observed=dataclasses.replace(c,world_instance_id='opaque-clone-'+str(i))
    hidden_future=step(observed.next_states[-1],np.zeros(2),.1,PHI,float(i))
    r=P.MechanismSufficiencyGate(REG,domain_envelope=P.toy_slow_d_valid_envelope()).route(observed,prior(),scope_id='g9-fixed')
    records.append({'record':r,'sealed_future':hidden_future})
res['future_invariance']={'observations_equal':True,'records':records,'identical_records':all(dataclasses.asdict(records[0]['record'])==dataclasses.asdict(r['record']) for r in records)}
# Archive SHA manifest was generated with an empty self-file entry; preserve/report that discrepancy.
archive=ROOT/'reports/V9-G7/r1-archive';checks=[]
for line in (archive/'SHA256SUMS.txt').read_text().splitlines():
    h,path=line.split(None,1);p=archive/path.strip();checks.append({'file':path,'expected':h,'actual':sha(p),'matches':h==sha(p)})
res['r1_archive_manifest']=checks
# Product and old evidence file identity before/after; isolated baseline equals current reviewed source.
paths=list(SOURCE.glob('*.py'))+list((ROOT/'tests/v9/mechanism').glob('*.py'))+list((ROOT/'reports/V9-G7').rglob('*'))+list((ROOT/'reports/V9-G8').rglob('*'))+[ROOT.parent/'AnimeWorldZero/docs/adr/ADR-0014-constrained-mechanism-formation.md']
manifest={str(p):sha(p) for p in paths if p.is_file() and '__pycache__' not in str(p)}
save('evidence/reviewed_manifest.json',manifest)
res['product_snapshot_matches_current']={p.name:sha(p)==sha(OUT/'isolated/g9baseline'/p.name) for p in SOURCE.glob('*.py')}
res['git_head']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
res['source_sha256']={p.name:sha(p) for p in SOURCE.glob('*.py')}
res['sigma_provenance']={'review_covariance_fixed_before_generation':COV,'author_report_covariance':COV,'author_frozen_registration_has_nuisance_cov': 'nuisance_cov' in REG.to_dict(),'default_discover_argument':'None (hard); GLS only if explicitly passed','claim_limit':'report hard-coded covariance not a verified pre-existing ParamBelief/registration provenance certificate'}
save('supplement.json',res)
print(json.dumps(strict(res),ensure_ascii=False,allow_nan=False,indent=2))
