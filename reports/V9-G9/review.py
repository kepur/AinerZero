from pathlib import Path
import sys, hashlib, json, math, shutil, importlib.util, dataclasses, subprocess, traceback
import numpy as np
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'src/ainerzero/v9/mechanism'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def strict(x):
    if dataclasses.is_dataclass(x): return strict(dataclasses.asdict(x))
    if isinstance(x,dict): return {str(k):strict(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)): return [strict(v) for v in x]
    if isinstance(x,np.ndarray): return strict(x.tolist())
    if isinstance(x,(float,np.floating)): return float(x) if math.isfinite(x) else str(float(x))
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,np.bool_): return bool(x)
    return x
def save(name,x): (OUT/name).write_text(json.dumps(strict(x),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def load(name,changes=()):
    dest=OUT/'isolated'/name
    dest.mkdir(parents=True,exist_ok=False)
    for p in SOURCE.glob('*.py'): shutil.copyfile(p,dest/p.name)
    for fn,old,new in changes:
        p=dest/fn; text=p.read_text(); assert text.count(old)==1,(fn,old,text.count(old)); p.write_text(text.replace(old,new))
    spec=importlib.util.spec_from_file_location(name,dest/'__init__.py',submodule_search_locations=[str(dest)])
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
P=load('g9baseline')
REG=P.default_cmfl_registration(); PHI=np.array([9.81,.25,1.2]); COV=np.diag([1.5,.25,.6]); SCALE=np.array([2.,.2,.5])
def prior(p=P): return p.ParamBelief(PHI,COV,SCALE)
# Independently coded vector field + RK4; no product simulator/integrator used for fixture generation.
def rhs(s,u,phi,drag):
    a=u-phi[1]*s[2:]-phi[2]*s[:2]-np.array([0.,phi[0]])-drag*np.linalg.norm(s[2:])*s[2:]
    return np.r_[s[2:],a]
def step(s,u,dt,phi,drag):
    a=rhs(s,u,phi,drag);b=rhs(s+dt*a/2,u,phi,drag);c=rhs(s+dt*b/2,u,phi,drag);d=rhs(s+dt*c,u,phi,drag)
    return s+dt*(a+2*b+2*c+d)/6

def gen(prefix,n,seed,W=20,dt=.01,sigma=.004,drag=.55,param=False,p=P):
    rng=np.random.default_rng(seed);out=[]
    for i in range(n):
        phi=PHI+np.array([rng.uniform(-1.4,1.4),rng.uniform(.1,.35),rng.uniform(-.5,.5)]) if param else PHI
        s=np.array([rng.uniform(.8,2.8),rng.uniform(-2.7,-.8),rng.uniform(2.2,4.2),rng.uniform(-3.8,-1.8)])
        actions=rng.uniform(-3,3,(W,2)); states=[];nxt=[]
        for u in actions:
            states.append(s.copy());s=step(s,u,dt,phi,0. if param else drag);nxt.append(s+rng.normal(0,sigma,4))
        out.append(p.ObservationContext(context_id=f'{prefix}:{i}',world_instance_id=f'{prefix}/{i}',t_start=0,object_keys=('particle',),dt=dt,integrator='rk4',states=np.array(states),next_states=np.array(nxt),actions=actions,innovation_cov=np.eye(4)*sigma**2,env_family=REG.env_families[i%3]))
    return out

def candidate(p=P,term='quadratic_drag',coef=.55):
    return p.DiscoveredCandidate('g9-fixed-'+term,'sindy',(term,),np.array([coef]),((coef,coef),),(),0.,1,'G9-D',1,'single_step')
D=gen('D',9,281001); C=gen('C',24,281002); T=gen('T',60,281003)
fixture_identity={}
for name,ctxs in [('D',D),('C',C),('T',T)]:
    payload=[{f.name:getattr(c,f.name) for f in dataclasses.fields(c)} for c in ctxs];save('evidence/fixture_'+name+'.json',payload); fixture_identity[name]=sha(OUT/('evidence/fixture_'+name+'.json'))

def evaluate(p=P,cand=None,tests=None,nulls=None,cal=None,gate=None,ids=('G9-D','G9-C','G9-T'),tid='G9-test'):
    cand=candidate(p) if cand is None else cand
    nulls=p.build_facttest_null_controls(cand,D,prior(p),p.default_basis_library()) if nulls is None else nulls
    return (gate or p.OneSidedPromotionGate(REG)).evaluate_and_promote(cand,prior(p),discovery_contexts=D,calibration_contexts=C if cal is None else cal,test_contexts=T if tests is None else tests,discovery_data_id=ids[0],calibration_data_id=ids[1],test_data_id=ids[2],test_id=tid,producer='g9-independent-evaluator',trusted_context={'verified_producer':'g9-independent-evaluator','isolated_evaluator':True},facttest_null_candidates=nulls)
results={'scope':'CPU NumPy only; independent RK4 fixtures; no author tests imported','registration':REG.to_dict(),'fixture_sha256':fixture_identity}
def record(name,fn):
    try: value=fn();results[name]=strict(value);print(name,json.dumps(strict(value),ensure_ascii=False,allow_nan=False),flush=True);return value
    except Exception as e:
        results[name]={'exception':repr(e),'traceback':traceback.format_exc()};print(name,traceback.format_exc(),flush=True)
base=record('positive',evaluate)
record('small_elond',lambda:evaluate(tests=T[:12]))
record('label_missing',lambda:evaluate(tests=[dataclasses.replace(c,env_family=None) for c in T]))
record('label_undeclared',lambda:evaluate(tests=[dataclasses.replace(c,env_family='not-registered') for c in T]))
record('label_conflict',lambda:evaluate(tests=T+[dataclasses.replace(T[0],env_family=REG.env_families[1],context_id='conflicting')]))
record('null_insufficient',lambda:evaluate(nulls=[candidate(coef=0)]*28))
record('null_bad_recipe_duplicates',lambda:evaluate(nulls=[candidate(coef=0)]*29))
record('null_bad_recipe_distinct_ids',lambda:evaluate(nulls=[dataclasses.replace(candidate(coef=0),candidate_id=f'forged-{i}') for i in range(29)]))
record('wrong_nonempty',lambda:[evaluate(cand=candidate(term='coulomb_friction',coef=.45),tests=gen('wrong'+str(i),120,282000+i)) for i in range(3)])
record('null_threshold_unreachable',lambda:P.calibrate_facttest_threshold([.1]*28,.1,.05))
# Actual repeated worlds reused under a new data label: N3 must reject actual sets, not merely strings.
def reuse():
    g=P.OneSidedPromotionGate(REG); a=evaluate(gate=g);b=evaluate(gate=g,ids=('G9-D','G9-C','G9-T-renamed'),tid='G9-retest');return {'first':a,'same_T_new_label':b}
record('retest_same_worlds_new_label',reuse)
# Per-context contraction, orthogonality, and GLS -> hard limit checked with new random vectors.
def projection():
    out={};ctx=gen('projection',12,283001,W=16,dt=.015,sigma=.0025,param=True);rng=np.random.default_rng(283002);views=[rng.normal(size=c.states.shape) for c in ctx];stl=P.WeakFormSTLSQ()
    hard=stl._compute_context_orthogonal_bases(ctx,PHI,'single_step',None);hp=stl._project_views_orthogonal(views,hard)
    for tag,cov in [('hard',None),('gls',COV),('limit',COV*1e14)]:
        bs=stl._compute_context_orthogonal_bases(ctx,PHI,'single_step',cov);pv=stl._project_views_orthogonal(views,bs)
        out[tag]={'max_energy_ratio':max(float(np.sum(a*a)/np.sum(b*b)) for a,b in zip(pv,views)),'max_parameter_inner_product':max(float(np.max(np.abs(q.T@a.reshape(-1)))) for q,a in zip(hard,pv)),'max_distance_to_hard':max(float(np.max(np.abs(a-b))) for a,b in zip(pv,hp))}
    return out
record('projection',projection)
def discovery():
    rows=[]
    for W,dt,sig in [(20,.01,.004),(16,.015,.0025)]:
        for mode,cov in [('hard',None),('gls',COV)]:
            for typ in ['param','structural']:
                candidates=[]
                for i in range(10):
                    cs=gen('discover',6,284000+i,W=W,dt=dt,sigma=sig,param=typ=='param')
                    c=P.WeakFormSTLSQ().discover(cs,PHI,rng=np.random.default_rng(285000+i),nuisance_cov=cov)
                    candidates.append({'terms':c.active_terms,'coef':c.coefficients,'attempts':c.total_candidates_attempted})
                rows.append({'W':W,'dt':dt,'sigma':sig,'mode':mode,'type':typ,'nonempty':sum(bool(c['terms']) for c in candidates),'exact_drag_support':sum(c['terms']==('quadratic_drag',) for c in candidates),'n':10,'candidates':candidates})
    return rows
record('discovery',discovery)
# Frozen parameters not changed; nuisance covariance is a fixed sensitivity comparison, NOT an endorsed new default.
def routing():
    c=D[0];futures=[{'hidden_future':i,'in_slow_domain':bool(i%2)} for i in range(6)]
    routes=[P.MechanismSufficiencyGate(REG,domain_envelope=P.toy_slow_d_valid_envelope()).route(c,prior(),scope_id='g9').route_code.value for f in futures]
    no=P.MechanismSufficiencyGate(REG).route(c,prior(),scope_id='g9').route_code.value
    ood=dataclasses.replace(c,states=c.states+np.array([10.,0.,0.,0.]),next_states=c.next_states+np.array([10.,0.,0.,0.]))
    o=P.MechanismSufficiencyGate(REG,domain_envelope=P.toy_slow_d_valid_envelope()).route(ood,prior(),scope_id='g9').route_code.value
    return {'same_observation_hidden_future_routes':routes,'no_envelope':no,'ood_from_covariates':o,'observation_fields':[f.name for f in dataclasses.fields(c)]}
record('routing',routing)
# Six independently authored source mutations, in copies under this card's allowed directory.
mutations=[
('elond','promotion_gate.py','e_lond_passed = bool(e_pers >= e_threshold)','e_lond_passed = False'),
('family','promotion_gate.py','fam = ctx.env_family if ctx.env_family is not None else ""','fam = self.registration.env_families[0]'),
('facttest','promotion_gate.py','facttest_passed = bool(math.isfinite(thr) and ft_score > thr)','facttest_passed = False'),
('finite_sample','promotion_gate.py','(1.0 - registration.alpha_dom) * (n_cal + 1)','(1.0 - registration.alpha_dom) * n_cal'),
('projection','discovery.py','proj = flat.copy() if q_c.size == 0 else flat - q_c @ (q_c.T @ flat)','proj = flat.copy() if q_c.size == 0 else flat - 2.5 * q_c @ (q_c.T @ flat)'),
('null_threshold','promotion_gate.py','return float("inf"), n + 1','return float(scores[-1])+1e-6, n')]
matrix=[]
for name,fn,old,new in mutations:
    p=load('g9mut_'+name,[(fn,old,new)])
    if name in ('elond','family','facttest'):
        b=evaluate();m=evaluate(p);changed=b.admitted and not m.admitted;detail={'baseline':b,'mutant':m};kind='true_success_destroyed'
    elif name=='finite_sample':
        f=lambda q:q.calibrate_conformal_domain(D,C[:18],prior(q),REG)
        b=f(P);m=f(p);changed=not b.certificate_valid and m.certificate_valid;detail={'baseline':b,'mutant':m};kind='ordinary_negative_bypass'
    elif name=='projection':
        stl=P.WeakFormSTLSQ();bs=stl._compute_context_orthogonal_bases(D,PHI,'single_step');vs=[(b@np.ones(b.shape[1])).reshape(c.states.shape) for b,c in zip(bs,D)];b=stl._project_views_orthogonal(vs,bs)
        try: p.WeakFormSTLSQ._project_views_orthogonal(vs,bs);changed=False;err=None
        except AssertionError as e:changed=True;err=str(e)
        detail={'baseline_max_energy':max(float(np.sum(x*x)) for x in b),'mutant_assertion':err};kind='ordinary_invariant_violation'
    else:
        b=P.calibrate_facttest_threshold([.1]*28,.1,.05);m=p.calibrate_facttest_threshold([.1]*28,.1,.05);changed=math.isinf(b[0]) and math.isfinite(m[0]);detail={'baseline':b,'mutant':m};kind='ordinary_negative_bypass'
    row={'mutation':name,'caught':bool(changed),'kind':kind,'detail':detail};matrix.append(row);print('MUTATION',name,changed,flush=True)
results['six_mutations']=strict(matrix)
save('metrics.json',results)
print('DONE',flush=True)
