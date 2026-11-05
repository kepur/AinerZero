#!/usr/bin/env python3
"""Consistency checks on saved CPU evidence only; no product execution."""
from pathlib import Path
import hashlib
import json
import math
import datetime as dt

OUT=Path(__file__).resolve().parent; RAW=OUT/'raw'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def main():
    checks=[]
    index=read(OUT/'evidence-index.json')
    for x in index['files']:
        assert sha(x['path'])==x['sha256'],f"Changed indexed evidence: {x['path']}"
    checks.append('All previously indexed evidence SHA256 values verified')
    jobs=read(OUT/'jobs-focused-summary.json')
    assert len(jobs)==6 and len({j['job_id'] for j in jobs})==6
    for j in jobs:
        raw=read(j['raw_job_status_path']); command=read(RAW/('job-'+j['label']+'.command.json'))
        assert command['returncode']==0 and 'cpu-review-p43-20261025' in command['argv']
        assert raw['id']==j['job_id'] and sha(j['raw_job_status_path'])==j['raw_job_status_sha256']
        if raw['status']=='canceled':
            assert raw['attempt']==0 and raw.get('exec_id') is None and raw.get('supervision') is None and raw.get('started_at') is None
        else:
            assert raw['exec_id']==raw['exec_finish']['id']
            assert raw['supervision']['confirmed_empty'] is True and raw['supervision']['members_left']==[]
            assert raw['actual_argv'][raw['actual_argv'].index('--mode')+1]=='train'
            assert all(x['matches_recorded_sha'] for x in j['log_integrity'])
    assert [j['status'] for j in jobs].count('completed')==4
    assert [j['status'] for j in jobs].count('failed')==1
    assert next(j for j in jobs if j['label']=='arm3-seed1')['exec_finish']['state']=='lost'
    checks.append('Six raw job responses, command identity, exec binding, archived log SHA and cancellation distinction verified')
    rows=read(OUT/'raw/db-runs.json')['rows']; ledger=read(OUT/'ledger-arithmetic.json')
    assert len(rows)==5
    assert math.isclose(sum(float(r['active_seconds']) for r in rows),1057.3214704760499,abs_tol=1e-9)
    assert math.isclose(sum(max(float(r['active_seconds']),float(r['updated_at'])-float(r['created_at'])) for r in rows),3819.310649394989,abs_tol=1e-9)
    assert ledger['calendar_expired'] is True
    ex=read(OUT/'experiment-manifest-interpretation.json')
    assert ex['cap_from_actual_experiment_budget']==ex['cap_from_frozen_prereg']==14400
    assert ex['manifest_hash_expected']==ex['manifest_hash_recomputed']
    checks.append('Raw ledger mapping, exact arithmetic, experiment manifest identity and calendar cap verified')
    hist=read(OUT/'checkpoint-historical-comparisons.json')
    assert len(hist)==25
    assert sum(x['kind']=='params' and x['exists'] for x in hist)==4
    assert sum(x['kind']=='intermediate_checkpoint' and x['historical_match_status']=='MATCHES_RECORDED_RUNNER_AND_DB_RECEIPT' for x in hist)==16
    assert sum(x['kind']=='intermediate_checkpoint' and x['historical_match_status']=='UNVERIFIED' for x in hist)==4
    for x in hist:
        if x['exists']:assert sha(x['path'])==x['current_sha256']
        if x['historical_match_status']=='MATCHES_RECORDED_RUNNER_AND_DB_RECEIPT':
            assert x['current_sha256']==x['expected_runner_frozen_stdout_sha256']==x['expected_DB_terminal_receipt_sha256']
    checks.append('Four params and sixteen intermediate recorded-hash comparisons verified; failed run absent params and four historical unknowns preserved')
    metrics=read(OUT/'P44-metrics.json')
    assert (OUT/'P44-REPORT.md').is_file() and (OUT/'P44-DETAILS.md').is_file()
    assert metrics['final_historical_zero_read']=='UNVERIFIED' and metrics['r14_authorized'] is False and metrics['new_model_runs']==0
    assert read(OUT/'dataset-identity-interpretation.json')['projection_matches_frozen_data_identity'] is True
    assert read(OUT/'approval-binding.json')['single_section_and_single_matching_line'] is True
    safety=read(OUT/'final-safety.json')
    assert safety['originals_still_unchanged'] and safety['production_still_unchanged'] and safety['clone_database_body_unchanged']
    assert safety['clone_still_unchanged'] is False
    assert safety['clone_final'][1]['size']==0 and safety['clone_final'][2]['size']==32768
    for field in ('originals_final','production_final','clone_final'):
        for x in safety[field]:
            if x['exists']:assert sha(x['path'])==x['sha256']
            else:assert not Path(x['path']).exists()
    assert safety['unique_clone_retained']
    checks.append('Report boundary, R6 scope, dataset projection, unchanged production/clone DB body/originals verified; newly created clone WAL/SHM explicitly disclosed')
    result={'status':'passed','checks':checks,'count':len(checks),'new_product_runs':0,'at':dt.datetime.now(dt.timezone.utc).isoformat()}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    # Extend the already verified index with the verifier and its fresh result.
    files=[{'path':str(p),'size':p.stat().st_size,'exists':True,'sha256':sha(p)} for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence-index.json']
    (OUT/'evidence-index.json').write_text(json.dumps({'created_at':result['at'],'files':files},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
