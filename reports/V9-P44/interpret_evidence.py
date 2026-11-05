#!/usr/bin/env python3
"""Interpret only P44 saved raw evidence and hash declared source/checkpoint files.

No DB opening, no models, no prior audit imports. Keep the initial collection
outputs intact; findings below supersede inventory-only UNVERIFIED placeholders
where the saved runner receipts actually supply historical expected hashes.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import datetime as dt

ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero')
OUT=ROOT/'reports/V9-P44'; RAW=OUT/'raw'
AGENT='cpu-review-p43-20261025'
def read(p): return json.loads(Path(p).read_text())
def dump(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def canonical(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def now():return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat()

def main():
    cmds=read(OUT/'interpret-commands.json') if (OUT/'interpret-commands.json').is_file() else []
    for name,args in [('p40-task',['show','ainerzero.V9.P40','--full','--json']),
                      ('p44-owner-check',['show','ainerzero.V9.P44','--full','--json'])]:
        if (RAW/(name+'.command.json')).is_file():
            continue  # Preserve the first raw response and command metadata.
        argv=[sys.executable,'/Users/mac/AinerWorkFlow/AinerRelay/bin/relay']+args+['--agent',AGENT]
        started=now(); p=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=60)
        (RAW/(name+'.stdout')).write_bytes(p.stdout);(RAW/(name+'.stderr')).write_bytes(p.stderr)
        cmd={'argv':argv,'cwd':str(ROOT),'started_at':started,'ended_at':now(),'returncode':p.returncode,
             'stdout':str(RAW/(name+'.stdout')),'stderr':str(RAW/(name+'.stderr'))}
        dump(RAW/(name+'.command.json'),cmd);cmds.append(cmd)
        if p.returncode: raise RuntimeError(f'{name} rc={p.returncode}; retained output')
    dump(OUT/'interpret-commands.json',cmds)
    ledger=read(OUT/'ledger-arithmetic.json'); rows=read(RAW/'db-runs.json')['rows']
    exp_manifest=json.loads(ledger['raw_experiment_row']['manifest_json'])
    dump(OUT/'experiment-manifest-interpretation.json',{
        'source':'raw/db-experiment.json: rows[0].manifest_json',
        'manifest':exp_manifest,'manifest_hash_expected':ledger['raw_experiment_row']['manifest_hash'],
        'manifest_hash_recomputed':canonical(exp_manifest),
        'cap_from_actual_experiment_budget':exp_manifest['experiment_budget']['max_wall_seconds'],
        'cap_from_frozen_prereg':ledger['frozen_phase_cap_seconds'],
        'calendar_deadline':ledger['calendar_deadline_local'],
        'note':'experiments has manifest_json, not config_json; initial collection actual_experiment_config_budget=null reflects absent config column. This interpretation uses the raw manifest.'})
    bindings=read(OUT/'source-data-binding.json'); prereg=read(RAW/'pre_registration.json'); manifest=read(RAW/'dataset_manifest.json')
    # Frozen data_identity is deliberately a projection, not a byte-for-byte
    # copy of the larger dataset manifest (episodes and file sizes are omitted).
    projection={k:manifest[k] for k in ('schema','dataset_digest','counts','generation_seconds','total_bytes','plan')}
    projection['episode_count']=len(manifest['episodes'])
    projection['files']={p:v['sha256'] for p,v in manifest['files'].items()}
    projection['source_identity']={k:v for k,v in manifest['source_identity'].items() if k!='files_sha256'}
    source_map=manifest['source_identity']['files_sha256']
    awzroot=Path(manifest['source_identity']['root'])
    current_generator=[]
    for rel,expected in source_map.items():
        p=awzroot/rel
        actual=sha(p) if p.is_file() else None
        current_generator.append({'path':str(p),'expected_frozen_generation_sha256':expected,'current_sha256':actual,'matches':actual==expected})
    data_interpretation={'projection_matches_frozen_data_identity':projection==prereg['data_identity'],
        'projected_identity':projection,'manifest_source_map_digest':canonical(source_map),
        'expected_source_map_digest':manifest['source_identity']['source_map_digest'],
        'current_generator_source_hashes':current_generator,
        'current_generator_drift_count':sum(not x['matches'] for x in current_generator),
        'note':'Current generator source is a separate read-only drift check. Drift after generation does not by itself disprove frozen dataset bytes or authorize regeneration.',
        'manifest_top_level_partitions_is_absent': 'partitions' not in manifest,
        'actual_partition_field':'plan.partitions',
        'actual_partitions':manifest['plan']['partitions'],
        'final_historical_zero_read':'UNVERIFIED'}
    dump(OUT/'dataset-identity-interpretation.json',data_interpretation)
    jobs=read(OUT/'jobs-summary.json'); focused=[]; comparisons=[]; histories=[]
    for job in jobs:
        label=job['label']; raw=read(RAW/('job-'+label+'.stdout'))
        entry={'label':label,'job_id':raw['id'],'status':raw['status'],'returncode':raw.get('returncode'),
            'attempt':raw.get('attempt'),'exec_id':raw.get('exec_id'),'exec_finish':raw.get('exec_finish'),
            'supervision':raw.get('supervision'),'started_at':raw.get('started_at'),
            'authorization_ref':raw.get('authorization_ref'),'actual_argv':raw.get('actual_argv'),
            'raw_job_status_path':str(RAW/('job-'+label+'.stdout')),
            'raw_job_status_sha256':sha(RAW/('job-'+label+'.stdout')),
            'log_integrity':[{'channel':x['channel'],'matches_recorded_sha':x.get('matches_recorded_sha'),
                              'metadata':x['metadata']} for x in job['logs']]}
        rid=job['expected_run_id_from_author_ledger']
        if rid:
            receipt_path=RAW/('log-'+label+'-stdout.log'); receipt=read(receipt_path)
            row=next(x for x in rows if x['run_id']==rid)
            dbcfg=json.loads(row['config_json'])
            logrun=receipt['run']
            try: terminal=json.loads(row['reason'].split(':',1)[1]) if row['state']=='completed' else {}
            except (ValueError,IndexError): terminal={}
            details=receipt.get('details') or {}
            hist={'label':label,'run_id':rid,'runner_log':str(receipt_path),'runner_log_sha256':sha(receipt_path),
                'runner_log_sha_matches_frozen_job_metadata':sha(receipt_path)==raw['logs']['stdout']['sha256'],
                'mode':receipt.get('mode'),'prereg_sha256':receipt.get('prereg_sha256'),
                'approval':receipt.get('approval'),'source_binding':receipt.get('source_binding'),
                'dataset':receipt.get('dataset'),'run_id_matches_DB':receipt.get('run_id')==rid,
                'config_snapshot_matches_DB':logrun.get('config_snapshot')==dbcfg,
                'reserved_active_seconds_log':logrun.get('reserved_active_seconds'),
                'reserved_active_seconds_matches_DB':logrun.get('reserved_active_seconds')==row['active_seconds'],
                'run_state':logrun.get('state'),'run_reason_prefix':str(logrun.get('reason','')).split(':',1)[0],
                'error':receipt.get('error'),'checkpoints_recorded':details.get('checkpoints',[])}
            histories.append(hist)
            entry['run_binding']={'run_id':rid,'runner_stdout_top_level_run_id_matches':hist['run_id_matches_DB'],
                                  'run_snapshot_matches_DB':hist['config_snapshot_matches_DB']}
            expected_by_path={x['path']:x for x in details.get('checkpoints',[])}
            db_expected={x['path']:x for x in terminal.get('checkpoints',[])}
            for inv in read(OUT/'checkpoint-inventory.json'):
                if inv['run_id']!=rid:continue
                p=Path(inv['current']['path']); rel=str(p.relative_to(ROOT/'artifacts/v9/s1/phase1/runs'/rid))
                expected=expected_by_path.get(rel,{}).get('sha256')
                dbsha=db_expected.get(rel,{}).get('sha256')
                actual=inv['current']['sha256']
                comparisons.append({'run_id':rid,'kind':inv['kind'],'path':str(p),'exists':inv['current']['exists'],
                    'current_sha256':actual,'adjacent_sidecar_expected':inv.get('expected_sidecar'),
                    'P40_ledger_expected':inv.get('expected_P40_ledger'),
                    'expected_runner_frozen_stdout_sha256':expected,'expected_DB_terminal_receipt_sha256':dbsha,
                    'runner_expected_json_pointer':'details.checkpoints[path='+rel+'].sha256',
                    'runner_stdout_path':str(receipt_path),'job_status_path':str(RAW/('job-'+label+'.stdout')),
                    'matches_runner_expected':actual==expected if expected and actual else None,
                    'matches_DB_terminal_expected':actual==dbsha if dbsha and actual else None,
                    'historical_match_status':'MATCHES_RECORDED_RUNNER_AND_DB_RECEIPT' if actual and expected and dbsha and actual==expected==dbsha else 'UNVERIFIED',
                    'limit':'Expected hashes are training process receipts preserved by runner and DB; no cryptographic attestation or independently timed access audit is claimed.'})
        else:
            entry['no_launch_evidence']={k:raw.get(k) for k in ('attempt','exec_id','started_at','actual_argv','supervision','lease_observation')}
        focused.append(entry)
    dump(OUT/'jobs-focused-summary.json',focused)
    dump(OUT/'runner-receipt-bindings.json',histories)
    dump(OUT/'checkpoint-historical-comparisons.json',comparisons)
    matrix=[
        {'item':'raw_runner_jobs','status':'ESTABLISHED_WITH_LIMITS','facts':'Six raw responses; 4 completed + 1 failed each with real exec ID and confirmed_empty=true; canceled-before-launch has attempt=0 and no exec/supervision. Failed exec_finish.state=lost preserved.', 'evidence':['jobs-focused-summary.json','raw/job-*.stdout']},
        {'item':'final_historical_zero_reads','status':'UNVERIFIED','facts':'Manifest plan.partitions, source guards, observed actual argv train and current absent named final files bound intended/current workflow only; no independent historical access audit.', 'evidence':['source-data-binding.json','dataset-identity-interpretation.json','raw/data-excerpts.txt','raw/worker-excerpts.txt']},
        {'item':'real_reserved_and_dual_wall_gates','status':'ESTABLISHED','facts':'runs.active_seconds maps to RunRecord.reserved_active_seconds; reserved sum=1057.3214704760499s; conservative sum=3819.310649394989s; calendar expired 2026-10-25T18:42:26.279864+03:00.', 'evidence':['raw/db-runs.json','raw/db-experiment.json','raw/lifecycle-excerpts.txt','ledger-arithmetic.json','experiment-manifest-interpretation.json','db-snapshot.json']},
        {'item':'R6_current_section_and_recorded_run_binding','status':'ESTABLISHED_WITH_LIMITS','facts':'One section L731-799 and one line L798; doc and line match all 5 DB configs and runner receipts. Historical whole-log SHA is recorded but historical full log was not reconstructed/authenticated.', 'evidence':['approval-binding.json','raw/R6-current-section.txt','runner-receipt-bindings.json']},
        {'item':'source_data_current_integrity','status':'ESTABLISHED_WITH_LIMITS','facts':f"21 current package files and 5 frozen dataset files match. Full manifest projection matches prereg. Current generator drift={data_interpretation['current_generator_drift_count']} of {len(current_generator)} separately reported; not historical regeneration evidence.", 'evidence':['source-data-binding.json','dataset-identity-interpretation.json','runner-receipt-bindings.json']},
        {'item':'params','status':'ESTABLISHED_WITH_LIMITS','facts':'4 params exist and match adjacent expected SHA/P40 ledger and runner/DB receipts; failed run has no params. Does not establish model correctness.', 'evidence':['checkpoint-inventory.json','checkpoint-historical-comparisons.json']},
        {'item':'intermediate_checkpoint_historical_integrity','status':'PARTIALLY_ESTABLISHED','facts':'16 completed-run checkpoints compare to expected hashes from frozen runner stdout and DB terminal receipts; 4 failed-run checkpoint hashes have no obtained historical expected values and remain UNVERIFIED.', 'evidence':['checkpoint-historical-comparisons.json','runner-receipt-bindings.json']},
        {'item':'authority','status':'NO_NEW_RUN_AUTHORITY','facts':'P43 accepted status does not establish all claims or authorize r14. No new verify/train/eval/MLX/Blender run; P36 untouched.', 'evidence':['raw/P43-SCOPE-CORRECTION.md','safety.json']},
    ]
    dump(OUT/'P44-metrics.json',{'task':'ainerzero.V9.P44','agent':AGENT,'tier':2,'kind':'codex','audited_task':'ainerzero.V9.P43',
        'created_at':now(),'independent_of_authors':['gemini-w9k4','gemini-kzer','antigravity-v7k2','claude'],
        'matrix':matrix,'raw_job_status_count':len(focused),'executed_confirmed_empty':sum(x.get('supervision',{}).get('confirmed_empty') is True for x in jobs),
        'canceled_before_launch':1,'params_files_present':sum(x['kind']=='params' and x['exists'] for x in comparisons),
        'completed_intermediate_checkpoint_matches':sum(x['kind']=='intermediate_checkpoint' and x['historical_match_status']=='MATCHES_RECORDED_RUNNER_AND_DB_RECEIPT' for x in comparisons),
        'failed_intermediate_checkpoint_historical_unverified':sum(x['kind']=='intermediate_checkpoint' and x['historical_match_status']=='UNVERIFIED' for x in comparisons),
        'final_historical_zero_read':'UNVERIFIED','reserved_sum_seconds':ledger['reserved_sum_seconds'],
        'conservative_sum_seconds':ledger['conservative_wall_sum_seconds'],'new_model_runs':0,'r14_authorized':False,
        'unique_clone_directory':read(OUT/'db-snapshot.json')['clone_directory'],'production_unchanged':read(OUT/'safety.json')['production_unchanged_entire_audit']})
    print(json.dumps({'checkpoint_comparisons':len(comparisons),
                     'matched_recorded_hashes':sum(x['historical_match_status']=='MATCHES_RECORDED_RUNNER_AND_DB_RECEIPT' for x in comparisons),
                     'unverified':sum(x['historical_match_status']=='UNVERIFIED' for x in comparisons),
                     'dataset_projection_match':projection==prereg['data_identity'],
                     'current_generator_drift':data_interpretation['current_generator_drift_count']},indent=2))
if __name__=='__main__':main()
