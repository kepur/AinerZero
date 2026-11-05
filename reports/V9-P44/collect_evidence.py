#!/usr/bin/env python3
"""Report-only P44 evidence collection. No project imports or model execution.

This is a new implementation, not an import/execution of P42/P43. Every
subprocess is an explicit read-only Relay status/prompt or a task heartbeat.
Only this report directory and one retained mkdtemp DB clone are written.
"""
from pathlib import Path
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
OUT = ROOT / 'reports/V9-P44'
RAW = OUT / 'raw'
RAW.mkdir(parents=True, exist_ok=True)
CLI = '/Users/mac/AinerWorkFlow/AinerRelay/bin/relay'
AGENT = 'cpu-review-p43-20261025'
EXP = 's1-phase1-20261024-r13'
DOC_SHA = '1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30'
FILE_SHA = '9868b913d3cea59acc860e17b6362afcbbb746990e0ddb4962bc6b78123e0f0d'
JOBS = [
 ('arm2-seed0','job-b7ecc70f9dbe4a0882ede4a66234c258','19f2d1eb4bf04da4909d87501348028d'),
 ('arm2-seed1','job-31a550d855ff4940b23bdee9846eea1f','7d155060fecc4070a9a68e95fb3761fa'),
 ('arm2-seed2','job-fb2c4adcc4cc4679b39a03702c16a972','1678cc1cc5d1468dabb3e86a16a45e97'),
 ('arm3-seed0','job-f3a2b32b41364407ad35a09142b08ea3','403ae816720c4ad9b4f75ecd86e7b109'),
 ('arm3-seed1','job-53bec0edbd484eac8ea3128a1a24dde1','92b694d35a324af083fc27183bb08f8c'),
 ('arm3-seed2','job-c35dfe45eb30437bb1fb0aad856e1fc6',None),
]
COMMANDS = []
OPS = []

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')

def canonical(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def record(path):
    p=Path(path)
    return {'path':str(p), 'exists':p.exists(), 'size':p.stat().st_size if p.is_file() else None,
            'sha256':sha(p) if p.is_file() else None}

def cmd(name, args):
    argv=[sys.executable,CLI]+args+['--agent',AGENT]
    start=now()
    p=subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=60)
    (RAW/(name+'.stdout')).write_bytes(p.stdout)
    (RAW/(name+'.stderr')).write_bytes(p.stderr)
    meta={'argv':argv,'cwd':str(ROOT),'started_at':start,'ended_at':now(),'returncode':p.returncode,
          'stdout':record(RAW/(name+'.stdout')), 'stderr':record(RAW/(name+'.stderr'))}
    dump(RAW/(name+'.command.json'),meta)
    COMMANDS.append(meta)
    dump(OUT/'commands.json',COMMANDS)
    if p.returncode:
        raise RuntimeError(f'{name} failed rc={p.returncode}; raw output retained')
    return p.stdout

def copy_text(path, dest):
    p=Path(path)
    data=p.read_bytes()
    (RAW/dest).write_bytes(data)
    return record(p)

def numbered_excerpt(path, ranges, dest):
    lines=Path(path).read_text().splitlines()
    text=''.join(f'{i}: {lines[i-1]}\n' for lo,hi in ranges for i in range(lo,min(hi,len(lines))+1))
    (RAW/dest).write_text(text)
    return {'source':record(path),'ranges':ranges,'saved':record(RAW/dest)}

def main():
    started=now()
    originals=[p for d in ('V9-P42','V9-P43') for p in (ROOT/'reports'/d).rglob('*') if p.is_file()]
    originals_before=[record(p) for p in originals]
    cmd('task-before',['show','ainerzero.V9.P44','--full','--json'])
    cmd('p43-task',['show','ainerzero.V9.P43','--full','--json'])
    cmd('task-prompt',['prompt','ainerzero.V9.P44'])
    cmd('heartbeat-start',['heartbeat','ainerzero.V9.P44','--msg','正在保存六份runner原始状态、保留只读台账副本与证据边界'])
    correction=copy_text('/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261026/P43-SCOPE-CORRECTION.md','P43-SCOPE-CORRECTION.md')
    # Historical input scripts and reports are copied as text, never executed.
    for folder in ('V9-P42','V9-P43'):
        for p in (ROOT/'reports'/folder).iterdir():
            if p.is_file():
                copy_text(p,folder+'--'+p.name)
    source_refs=[]
    for rel,ranges,name in [
        ('src/ainerzero/runtime/lifecycle.py',[(350,455),(790,845)],'lifecycle-excerpts.txt'),
        ('src/ainerzero/v9/experiments/s1/worker.py',[(412,534),(1780,1845),(2480,2545)],'worker-excerpts.txt'),
        ('src/ainerzero/v9/experiments/s1/data.py',[(1,120)],'data-excerpts.txt'),
        ('src/ainerzero/v9/experiments/s1/prereg.py',[(70,255)],'approval-parser-excerpts.txt')]:
        source_refs.append(numbered_excerpt(ROOT/rel,ranges,name))

    jobs=[]
    for label,jid,rid in JOBS:
        b=cmd('job-'+label,['job-status',jid,'--json'])
        obj=json.loads(b)
        # Keep raw command bytes above; only the derived summary is projected.
        sup=obj.get('supervision') or {}
        logs=[]
        for channel,meta in (obj.get('logs') or {}).items():
            p=Path(meta['path']) if meta.get('path') else None
            entry={'channel':channel,'metadata':meta,'current':record(p) if p else None}
            if p and p.is_file():
                # Runner logs contain training output, not dataset contents.
                dest='log-'+label+'-'+channel+'.log'
                copy_text(p,dest)
                entry['saved']=record(RAW/dest)
                entry['matches_recorded_sha']=sha(p)==meta.get('sha256')
                text=(RAW/dest).read_text(errors='replace')
                entry['lines_containing_final']=[{'line':i,'text':s} for i,s in enumerate(text.splitlines(),1) if re.search(r'\bfinal\b',s,re.I)]
                entry['lines_containing_run_id']=[{'line':i,'text':s} for i,s in enumerate(text.splitlines(),1) if rid and rid in s]
            logs.append(entry)
        argv=obj.get('actual_argv') or []
        jobs.append({'label':label,'job_id':jid,'expected_run_id_from_author_ledger':rid,
                     'status':obj.get('status'),'returncode':obj.get('returncode'),'reason':obj.get('reason'),
                     'started_at':obj.get('started_at'),'ended_at':obj.get('ended_at'),
                     'exec_id':obj.get('exec_id'),'exec_finish':obj.get('exec_finish'),
                     'supervision':sup,'actual_argv':argv,
                     'mode_from_actual_argv':argv[argv.index('--mode')+1] if '--mode' in argv else None,
                     'logs':logs,'raw_response':str(RAW/('job-'+label+'.stdout'))})
    dump(OUT/'jobs-summary.json',jobs)

    # Production is never opened by SQLite or any project API. Hash and byte-copy only.
    prod=ROOT/'artifacts/v9/s1/phase1/control.sqlite3'
    source_paths=[Path(str(prod)+s) for s in ('','-wal','-shm')]
    prod_before=[record(p) for p in source_paths]
    clone_dir=Path(tempfile.mkdtemp(prefix='ainerzero-p44-'))
    clone=clone_dir/prod.name
    copies=[]
    for p in source_paths:
        if p.is_file():
            dest=clone_dir/p.name
            shutil.copy2(p,dest)
            copies.append({'source':str(p),'clone':str(dest),'sha256':sha(dest)})
    clone_before=[record(clone_dir/p.name) for p in source_paths]
    dbmeta={'production_before':prod_before,'clone_directory':str(clone_dir),'copies':copies,
            'clone_before_query':clone_before,'uri':clone.as_uri()+'?mode=ro',
            'copy_policy':'DB and extant WAL/SHM byte copies; production hash-only; no deletes; clone retained'}
    dump(OUT/'db-snapshot.json',dbmeta)
    con=sqlite3.connect(dbmeta['uri'],uri=True)
    con.row_factory=sqlite3.Row
    queries=[('sqlite-schema','SELECT name,sql FROM sqlite_master ORDER BY name',()),
             ('experiment','SELECT * FROM experiments WHERE experiment_id=?',(EXP,)),
             ('runs','SELECT * FROM runs WHERE experiment_id=? ORDER BY created_at',(EXP,)),
             ('daily-budget','SELECT * FROM daily_budget ORDER BY local_date',())]
    result={}
    for name,query,params in queries:
        rows=[dict(r) for r in con.execute(query,params).fetchall()]
        result[name]=rows
        dump(RAW/('db-'+name+'.json'),{'query':query,'parameters':params,'rows':rows,'opened_database_uri':dbmeta['uri']})
    con.close()
    dbmeta['clone_after_query']=[record(clone_dir/p.name) for p in source_paths]
    dbmeta['production_after_query']=[record(p) for p in source_paths]
    dbmeta['production_unchanged_through_query']=prod_before==dbmeta['production_after_query']
    dbmeta['clone_unchanged_through_query']=clone_before==dbmeta['clone_after_query']
    dbmeta['clones_match_source_before']=all(next(x for x in prod_before if x['path']==c['source'])['sha256']==c['sha256'] for c in copies)
    dump(OUT/'db-snapshot.json',dbmeta)

    prereg_path=ROOT/'artifacts/v9/s1/phase1/r13/pre_registration.json'
    doc=json.loads(prereg_path.read_text())
    copy_text(prereg_path,'pre_registration.json')
    bindings={'prereg_file':record(prereg_path),'expected_file_sha256':FILE_SHA,'canonical_document_sha256':canonical(doc),
              'expected_document_sha256':DOC_SHA,'experiment_id':doc['experiment_id'],
              'package_map_digest_expected':doc['source_identity']['package_map_digest'],
              'package_map_digest_recomputed':canonical(doc['source_identity']['package_files'])}
    bindings['source_files']=[{'path':p,'expected':s,'current':record(ROOT/p),'matches':(ROOT/p).is_file() and sha(ROOT/p)==s} for p,s in doc['source_identity']['package_files'].items()]
    ds_root=ROOT/'artifacts/v9/s1/datasets'/doc['data_identity']['dataset_digest']
    data_files=[]
    for p,s in doc['data_identity']['files'].items():
        if 'final' in p.lower():
            data_files.append({'path':p,'status':'NOT_READ_final_excluded'})
            continue
        data_files.append({'path':p,'expected':s,'current':record(ds_root/p),'matches':(ds_root/p).is_file() and sha(ds_root/p)==s})
    bindings['data_files']=data_files
    # Read metadata only; never read any final partition contents.
    manifest_path=ds_root/'dataset_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    copy_text(manifest_path,'dataset_manifest.json')
    bindings['dataset_manifest']=record(manifest_path)
    bindings['manifest_plan_partitions']=manifest.get('plan',{}).get('partitions')
    bindings['manifest_top_level_partitions']=manifest.get('partitions')
    bindings['manifest_final_plan']=manifest.get('plan',{}).get('final_partition')
    bindings['manifest_matches_prereg_data_identity']=manifest==doc['data_identity']
    # Existence checks only for named final files; do not open/hash them.
    bindings['final_files_existence_only']=[{'path':str(ds_root/p),'exists':(ds_root/p).exists(),'contents_read':False} for p in ('packets/final.jsonl','truth/final.jsonl')]
    bindings['final_history_zero_read']='UNVERIFIED: no independent historical access audit; intended paths, present inventory and non-observation in logs do not prove zero historical reads'

    # Independent section scanner: ignores fenced, quoted and indented code and checks all credentials.
    log_path=ROOT/'RESEARCH_LOG.md'
    log_lines=log_path.read_text().splitlines()
    spans=[]; approved=[]; fence=None; section=None
    for n,line in enumerate(log_lines,1):
        m=re.match(r'^\s{0,3}(`{3,}|~{3,})',line)
        if m:
            mark=m.group(1)[0]
            fence=None if fence==mark else mark if fence is None else fence
            continue
        if fence: continue
        if re.match(r'^##\s+',line):
            if section is not None: spans[-1]['end_line']=n-1
            section=None
            if re.match(r'^## R20261021-P1-stageA-budget(?:[：:].*)?\s*$',line):
                spans.append({'start_line':n,'end_line':len(log_lines)}); section=len(spans)-1
            continue
        if section is None or line.startswith(('    ','\t')) or line.lstrip().startswith('>'): continue
        m=re.fullmatch(r'APPROVED s1-phase1 prereg document_sha256=([0-9a-f]{64})',line.strip())
        if m: approved.append({'line_number':n,'line':line.strip(),'document_sha256':m.group(1)})
    approval={'log':record(log_path),'section_spans':spans,'qualifying_rows':approved,
              'single_section_and_single_matching_line':len(spans)==1 and len(approved)==1 and approved[0]['document_sha256']==DOC_SHA}
    if spans:
        lo=min(s['start_line'] for s in spans);hi=max(s['end_line'] for s in spans)
        numbered_excerpt(log_path,[(lo,hi)],'R6-current-section.txt')
        (RAW/'R6-current-section-verbatim.txt').write_text('\n'.join(log_lines[lo-1:hi])+'\n')
    approval['historical_log_full_hash_difference_is_expected_after_appends']=True

    run_records=[]; checkpoint_inventory=[]; run_bindings=[]
    author_ledger=json.loads((ROOT/'reports/V9-S1-r13/run_ledger.json').read_text())
    copy_text(ROOT/'reports/V9-S1-r13/run_ledger.json','P40-run_ledger.json')
    for row in result['runs']:
        cfg=json.loads(row['config_json'])
        reserved=float(row['active_seconds']); elapsed=float(row['updated_at'])-float(row['created_at'])
        if not math.isfinite(reserved) or reserved<0 or not math.isfinite(elapsed) or elapsed<0:
            raise RuntimeError('Malformed raw ledger value; no clamping allowed')
        rid=row['run_id']; run_dir=ROOT/'artifacts/v9/s1/phase1/runs'/rid
        run_records.append({'run_id':rid,'request_id':row['request_id'],'state':row['state'],'optimizer_steps':row['optimizer_steps'],
                            'reserved_active_seconds_from_runs_active_seconds':reserved,'terminal_elapsed_seconds':elapsed,
                            'conservative_wall_seconds':max(reserved,elapsed),'config_contains_reserved_active_seconds':'reserved_active_seconds' in cfg})
        snapshot=cfg.get('approval') or {}
        run_bindings.append({'run_id':rid,'arm_id':cfg.get('arm_id'),'seed':cfg.get('seed'),
                             'preregistration_sha256':cfg.get('preregistration_sha256'),'dataset_digest':cfg.get('dataset_digest'),
                             'approval_snapshot':snapshot,'approval_line_matches':snapshot.get('line')==(approved[0]['line'] if len(approved)==1 else None),
                             'approval_doc_matches':snapshot.get('document_sha256')==DOC_SHA,
                             'prereg_doc_matches':cfg.get('preregistration_sha256')==DOC_SHA,
                             'dataset_matches':cfg.get('dataset_digest')==doc['data_identity']['dataset_digest'],
                             'approval_line_number_matches_current':snapshot.get('line_number')==(approved[0]['line_number'] if len(approved)==1 else None)})
        for name in ('run_info.json','completion.json','params.npz.sha256'):
            if (run_dir/name).is_file(): copy_text(run_dir/name,rid+'--'+name)
        param=run_dir/'params.npz'; sidecar=run_dir/'params.npz.sha256'
        expected=sidecar.read_text().strip().split()[0] if sidecar.is_file() else None
        p40=next((x.get('checkpoint_sha256') for x in author_ledger['trains'] if x.get('run_id')==rid),None)
        checkpoint_inventory.append({'run_id':rid,'kind':'params','current':record(param),'expected_sidecar':expected,
                                     'expected_P40_ledger':p40,'matches_sidecar':sha(param)==expected if param.is_file() and expected else None,
                                     'matches_P40_ledger':sha(param)==p40 if param.is_file() and p40 else None,
                                     'expected_origin':'adjacent SHA sidecar + P40 author ledger; no independent timestamp/authentication claim'})
        for p in sorted((run_dir/'checkpoints').glob('*.npz')):
            checkpoint_inventory.append({'run_id':rid,'kind':'intermediate_checkpoint','current':record(p),
                                         'historical_expected_sha256':None,'historical_match':'UNVERIFIED: no separately preserved historical expected SHA obtained',
                                         'hash_only_no_model_loading':True})
    approval['run_bindings']=run_bindings
    dump(OUT/'approval-binding.json',approval)
    dump(OUT/'source-data-binding.json',bindings)
    dump(OUT/'checkpoint-inventory.json',checkpoint_inventory)
    exp=result['experiment'][0]
    exconfig=json.loads(exp['config_json']) if 'config_json' in exp else {}
    budget=exconfig.get('budget',{}).get('max_wall_seconds',14400.0)
    # r13 cap is frozen in prereg; report both actual experiment config and frozen cap.
    cap=float(doc['timing']['phase_wall_max_seconds'])
    ledger={'raw_experiment_row':exp,'run_breakdown':run_records,'reserved_sum_seconds':sum(r['reserved_active_seconds_from_runs_active_seconds'] for r in run_records),
            'conservative_wall_sum_seconds':sum(r['conservative_wall_seconds'] for r in run_records),
            'frozen_phase_cap_seconds':cap,'calendar_created_at':exp['created_at'],
            'calendar_deadline_unix':float(exp['created_at'])+cap,
            'calendar_deadline_local':dt.datetime.fromtimestamp(float(exp['created_at'])+cap,dt.timezone(dt.timedelta(hours=3))).isoformat(),
            'audit_instant_unix':time.time(),'calendar_expired':time.time()>float(exp['created_at'])+cap,
            'daily_budget_is_global_not_r13_only':'Raw daily rows retained; do not equate global daily reserved_seconds with this experiment sum',
            'actual_experiment_config_budget':exconfig.get('budget')}
    dump(OUT/'ledger-arithmetic.json',ledger)

    originals_after=[record(p) for p in originals]
    safety={'started_at':started,'ended_at':now(),'original_reports_before':originals_before,'original_reports_after':originals_after,
            'original_reports_unchanged':originals_before==originals_after,
            'production_end':[record(p) for p in source_paths],
            'production_unchanged_entire_audit':prod_before==[record(p) for p in source_paths],
            'new_model_runs':0,'old_audit_scripts_executed':False,'final_data_contents_read':False,'deletes':0,
            'clone_retained':clone.exists(),'no_authority_for_r14':True}
    dump(OUT/'safety.json',safety)
    cmd('heartbeat-complete',['heartbeat','ainerzero.V9.P44','--msg','六份原始job-status和唯一只读副本已留存，正在整理结论与未验证项'])
    dump(OUT/'collection-summary.json',{'started_at':started,'ended_at':now(),'jobs_count':len(jobs),'db_clone_directory':str(clone_dir),
                                       'source_references':source_refs,'scope_correction_source':correction})
    files=[record(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence-index.json']
    dump(OUT/'evidence-index.json',{'created_at':now(),'files':files})
    print(json.dumps({'jobs':[(j['label'],j['status'],j['exec_id'],j['supervision'].get('confirmed_empty')) for j in jobs],
                      'clone':str(clone),'production_unchanged':safety['production_unchanged_entire_audit'],
                      'conservative_sum':ledger['conservative_wall_sum_seconds'],'reserved_sum':ledger['reserved_sum_seconds'],
                      'deadline':ledger['calendar_deadline_local'],'approval':approval['single_section_and_single_matching_line'],
                      'source_matches':sum(x['matches'] for x in bindings['source_files']),
                      'data_matches':sum(x.get('matches',False) for x in bindings['data_files']),
                      'params':sum(x['kind']=='params' and x['current']['exists'] for x in checkpoint_inventory),
                      'intermediate_checkpoints':sum(x['kind']=='intermediate_checkpoint' for x in checkpoint_inventory)},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
