"""Real complete-source single-region CPU controls, never product flags."""
from __future__ import annotations
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1]
REPORT = SRC.parents[2] / 'reports/V9-T6/r2'
SPECS = [
    ('weight_sha', 'pipeline.py', 'if actual != expected:', 'if False:'),
    ('timestamp_count', 'pipeline.py',
     'if not isinstance(values, (list, tuple)) or len(values) != count:', 'if False:'),
    ('prediction_finite', 'pipeline.py',
     'if not np.issubdtype(array.dtype, np.floating) or not np.isfinite(array).all():', 'if False:'),
    ('failed_results', 'benchmark_suite.py',
     "if any(not isinstance(v, dict) or v.get('passed') is not True for v in numerical.values()):", 'if False:'),
]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def child(module_path, guard, mode, fixture_root):
    import numpy as np
    spec = importlib.util.spec_from_file_location('owned_isolated_source', module_path)
    m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    try:
        if guard == 'timestamp_count':
            values = [0., .5] if mode == 'positive' else ([0.] if mode == 'target' else [0., float('nan')])
            result = m.validate_timestamps(values, 2)
        elif guard == 'weight_sha':
            directory = fixture_root / mode
            config = (directory/'config.json').read_bytes()
            good = b'GOOD'
            m.APPROVED['DA3-SMALL'] = {'model_name':'da3-small', 'revision':'TEST_ONLY',
                'config.json':(len(config),digest(config)),
                'model.safetensors':(len(good),digest(good))}
            result = m.inspect_weights('DA3-SMALL', directory)
        elif guard == 'prediction_finite':
            values = dict(depth=np.ones((2,4,4),np.float32),conf=np.ones((2,4,4),np.float32),
                extrinsics=np.repeat(np.eye(4,dtype=np.float32)[None],2,axis=0)[:,:3],
                intrinsics=np.repeat(np.eye(3,dtype=np.float32)[None],2,axis=0))
            if mode == 'target':values['extrinsics'][0,0,0]=np.nan
            if mode == 'unrelated':values['conf'] *= -1
            result = m.checked_predictions(type('Prediction',(),values)(),2)
        elif guard == 'failed_results':
            numerical={'parity':{'passed':mode != 'target'}}
            controls=[{'clean_returncode':0,'bad_returncode':0 if mode=='unrelated' else 1,
                       'expected_error':'BAD_INPUT','observed_error':'BAD_INPUT'}]
            result=m.validate_results(numerical,controls)
        else:
            raise RuntimeError(guard)
    except ValueError as exc:
        print(json.dumps({'outcome':'rejected','error':str(exc),'source_sha256':digest(module_path.read_bytes()),'real_models_loaded':0}))
        return 1
    print(json.dumps({'outcome':'accepted','source_sha256':digest(module_path.read_bytes()),'real_models_loaded':0}))
    return 0

def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix='source-controls-',dir=REPORT))
    results=[];commands=[]
    for guard,filename,before,after in SPECS:
        source=(SRC/filename).read_text()
        assert source.count(before)==1,(guard,'guard region must occur exactly once')
        mutant=source.replace(before,after,1)
        assert mutant.replace(after,before,1)==source,(guard,'inverse must be byte identical')
        root=out/guard;root.mkdir()
        baseline_path=root/'baseline.py';mutant_path=root/'mutant.py'
        baseline_path.write_text(source);mutant_path.write_text(mutant)
        (root/'change.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True),mutant.splitlines(True),fromfile='baseline.py',tofile='mutant.py')))
        fixtures=root/'fixtures';fixtures.mkdir()
        for mode in ['positive','target','unrelated']:
            d=fixtures/mode;d.mkdir()
            (d/'config.json').write_text(json.dumps({'model_name':'da3-base' if mode=='unrelated' else 'da3-small'}))
            (d/'model.safetensors').write_bytes(b'EVIL' if mode=='target' else b'GOOD')
        table={}
        for version,path in [('baseline',baseline_path),('mutant',mutant_path)]:
            for mode in ['positive','target','unrelated']:
                argv=[sys.executable,'-I',str(Path(__file__).resolve()),'--child',str(path),guard,mode,str(fixtures)]
                p=subprocess.run(argv,capture_output=True,timeout=15)
                label=version+'-'+mode
                (root/(label+'.stdout')).write_bytes(p.stdout);(root/(label+'.stderr')).write_bytes(p.stderr)
                observation=json.loads(p.stdout)
                assert not p.stderr,(guard,label,p.stderr.decode())
                table[label]={'rc':p.returncode,**observation}
                commands.append({'guard':guard,'mode':label,'argv':argv,'rc':p.returncode})
        expected={'baseline-positive':0,'mutant-positive':0,'baseline-target':1,'mutant-target':0,
                  'baseline-unrelated':1,'mutant-unrelated':1}
        assert all(table[k]['rc']==v for k,v in expected.items()),(guard,table)
        assert (SRC/filename).read_text()==source,'product source changed during control'
        results.append({'guard':guard,'complete_original_file':str(SRC/filename),
            'baseline_sha256':digest(source.encode()),'mutant_sha256':digest(mutant.encode()),
            'inverse_sha256':digest(mutant.replace(after,before,1).encode()),
            'inverse_byte_identical':True,'all_three_directions_proven':True,'observations':table})
    payload={'real_isolated_source_controls':len(results),'passed':len(results),'results':results,
             'commands':commands,'artifact_root':str(out),'product_source_mutations':0,
             'real_model_runs':0,'all_artifacts_retained':True}
    (out/'results.json').write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps({'result_file':str(out/'results.json'),'passed':len(results),'real_model_runs':0}))

if __name__=='__main__':
    if '--child' in sys.argv:
        i=sys.argv.index('--child');raise SystemExit(child(Path(sys.argv[i+1]),sys.argv[i+2],sys.argv[i+3],Path(sys.argv[i+4])))
    main()
