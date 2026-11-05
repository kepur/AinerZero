#!/usr/bin/env python3
"""Prepare report artifacts from saved evidence; no project imports or DB open."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess
import sys
import shutil

ROOT=Path('/Users/mac/AinerWorkFlow/AinerZero'); OUT=ROOT/'reports/V9-P44'; RAW=OUT/'raw'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def now():return dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat()
def record(p):
    p=Path(p);return {'path':str(p),'exists':p.exists(),'size':p.stat().st_size if p.is_file() else None,'sha256':sha(p) if p.is_file() else None}

def main():
    # Preserve the first strict-set assertion failure artifacts before issuing
    # the corrected, explicitly bounded safety conclusion.
    for name in ('final-safety.json','finalize-commands.json','verification.json'):
        if (OUT/name).is_file() and not (OUT/('initial-'+name)).exists():
            shutil.copy2(OUT/name,OUT/('initial-'+name))
    for name in ('heartbeat-final','owner-final'):
        for suffix in ('.stdout','.stderr','.command.json'):
            p=RAW/(name+suffix)
            if p.is_file() and not (RAW/('initial-'+name+suffix)).exists():
                shutil.copy2(p,RAW/('initial-'+name+suffix))
    commands=[]
    for name,args in [('heartbeat-final',['heartbeat','ainerzero.V9.P44','--msg','P44原始证据与报告已完成：final历史访问和失败run检查点历史一致性未验证，零新运行']),
                      ('owner-final',['show','ainerzero.V9.P44','--full','--json'])]:
        argv=[sys.executable,'/Users/mac/AinerWorkFlow/AinerRelay/bin/relay']+args+['--agent','cpu-review-p43-20261025']
        start=now(); p=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=60)
        (RAW/(name+'.stdout')).write_bytes(p.stdout);(RAW/(name+'.stderr')).write_bytes(p.stderr)
        meta={'argv':argv,'cwd':str(ROOT),'started_at':start,'ended_at':now(),'returncode':p.returncode,
              'stdout':record(RAW/(name+'.stdout')),'stderr':record(RAW/(name+'.stderr'))}
        dump(RAW/(name+'.command.json'),meta);commands.append(meta)
        if p.returncode:raise RuntimeError('heartbeat/owner check failed; raw output retained')
    dump(OUT/'finalize-commands.json',commands)
    own=read(RAW/'owner-final.stdout')
    assert own['assignee']=='cpu-review-p43-20261025' and own['status']=='claimed','Lost task ownership; do not report'
    metrics=read(OUT/'P44-metrics.json'); db=read(OUT/'db-snapshot.json'); safety=read(OUT/'safety.json')
    originals_final=[record(x['path']) for x in safety['original_reports_before']]
    prod_final=[record(x['path']) for x in db['production_before']]
    clone_final=[record(x['path']) for x in db['clone_before_query']]
    final_safety={'at':now(),'originals_final':originals_final,'originals_still_unchanged':originals_final==safety['original_reports_before'],
                  'production_final':prod_final,'production_still_unchanged':prod_final==db['production_before'],
                  'clone_final':clone_final,'clone_still_unchanged':clone_final==db['clone_before_query'],
                  'clone_database_body_unchanged':clone_final[0]==db['clone_before_query'][0],
                  'clone_sidecar_note':'SQLite mode=ro created an empty WAL and a 32768-byte SHM in the unique clone directory; preserved, not deleted. DB body hash unchanged. See before/after records.',
                  'unique_clone_retained':Path(db['clone_directory']).is_dir(),'new_model_runs':0,'final_contents_read':False,'deletes':0}
    dump(OUT/'final-safety.json',final_safety)
    assert all(final_safety[k] for k in ('originals_still_unchanged','production_still_unchanged','clone_database_body_unchanged','unique_clone_retained'))
    ledger=read(OUT/'ledger-arithmetic.json'); hist=read(OUT/'checkpoint-historical-comparisons.json')
    jobs=read(OUT/'jobs-focused-summary.json'); apr=read(OUT/'approval-binding.json')
    data=read(OUT/'dataset-identity-interpretation.json'); src=read(OUT/'source-data-binding.json')
    assert len(jobs)==6 and metrics['executed_confirmed_empty']==5
    assert all(x['matches'] for x in src['source_files']) and all(x['matches'] for x in src['data_files'])
    assert data['projection_matches_frozen_data_identity'] and apr['single_section_and_single_matching_line']
    assert all(all(r[k] for k in ('approval_line_matches','approval_doc_matches','prereg_doc_matches','dataset_matches','approval_line_number_matches_current')) for r in apr['run_bindings'])
    assert metrics['completed_intermediate_checkpoint_matches']==16 and metrics['failed_intermediate_checkpoint_historical_unverified']==4
    report='''# ainerzero.V9.P44 非作者 CPU 证据修订报告
角色 executor；负责人 cpu-review-p43-20261025（tier 2 / codex）；2026-10-26；交回统筹裁决。
仅写 reports/V9-P44/；未执行 P42/P43 脚本；无新增 verify/train/eval/MLX/Blender、final 数据读取或删除。
P43 的 accepted 事件保留；建议仅按下表收窄引用，不作为全面通过、能力晋升或 r14 授权。

| 核查项 | 结论与范围 |
| --- | --- |
| 六份原始作业响应 | 已保存本人身份命令、rc、stdout/stderr；5 个执行作业真实 exec+confirmed_empty=true；1 个启动前取消，无 exec/监督记录。 |
| 不利执行事实 | arm3-seed1 rc=2，资源守卫失败；其 exec_finish.state=lost 保留，不改称 finished。 |
| final 历史零读 | **UNVERIFIED**；当前清单/文件、源码守卫、train argv 与日志只界定所见和预期路径，无独立历史访问审计。 |
| 台账与双墙钟 | 唯一副本以 mode=ro 查询；生产及副本 DB 主体 SHA 不变；副本新建空 WAL/SHM 已披露保留。真实预留和 1057.321470s，保守和 3819.310649s。 |
| 日历窗口 | 实验实际 manifest 上限 14400s；2026-10-25 18:42:26.279864+03:00 已过期，逐 run 余量不能重开窗口。 |
| R6 | L731–799 限定节仅 L798 一条有效行；5 run 冻结配置及 runner 日志绑定同一 document、批准行、行号与历史 log SHA。历史整份日志未重新认证。 |
| source/data | 当前 21 个 package 文件、5 个冻结数据文件均匹配；manifest 正确投影匹配 prereg。AWZ 当前生成器 24 文件中 2 漂移，单列，不能倒推原数据失败。 |
| params | 仅 4 个存在，均与邻接 SHA、P40 记录、归档 runner/DB receipt 对上；失败 run 无 params。 |
| 中间 checkpoint | 16 个完成 run 检查点与 runner 冻结 stdout 及 DB 终态 receipt 记录的 SHA 对上；失败 run 的 4 个只有当前哈希，历史一致性 **UNVERIFIED**。 |

原始证据、精确字段与 SHA 索引：P44-DETAILS.md、evidence-index.json；正式指标：P44-metrics.json。
保留副本：/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/ainerzero-p44-rf604yfe/control.sqlite3。
未验证：final 历史零读、失败 run 4 个中间检查点历史一致性、历史整份 RESEARCH_LOG 的重建认证；哈希一致不证明模型正确性。
P36 未触碰；不接受/拒绝任何任务；本报告没有新增运行、r14、预算、下载或发布授权。
'''
    (OUT/'P44-REPORT.md').write_text(report)
    lines=['# P44 原始证据与可复核引用','',f'生成：{now()}。摘要见 P44-REPORT.md；所有相对证据路径以 {OUT} 为根。','',
           '## 命令和原始响应','',
           'commands.json、interpret-commands.json、finalize-commands.json 保存每条审计 Relay 子进程的 argv、身份、cwd、时间、返回码和 stdout/stderr 文件。raw/*.command.json 为逐命令记录。六份 job-status stdout 字节原样保存，未把投影摘要当原始响应。',
           '本次 Python 入口实际命令：python3 reports/V9-P44/collect_evidence.py（rc=0）、python3 reports/V9-P44/interpret_evidence.py（rc=0；两次，第二次修正投影字段并复用首次原始响应）、python3 reports/V9-P44/finalize_report.py（rc=0）。入口控制台摘要见 execution-record.json。交回命令的原始返回保存在 submission/。','',
           '| 作业 | 状态 / rc | exec ID | 监督 / 归档 | raw stdout SHA256 |','| --- | --- | --- | --- | --- |']
    for j in jobs:
        sup=j.get('supervision') or {}; ex=j.get('exec_finish') or {}
        lines.append(f"| {j['label']} | {j['status']} / {j['returncode']} | {j['exec_id']} | confirmed_empty={sup.get('confirmed_empty')}; exec_state={ex.get('state')} | {j['raw_job_status_sha256']} |")
    lines += ['', 'raw/job-arm2-seed0.stdout、raw/job-arm2-seed1.stdout、raw/job-arm2-seed2.stdout、raw/job-arm3-seed0.stdout、raw/job-arm3-seed1.stdout、raw/job-arm3-seed2.stdout 是六份完整 JSON。每份实际请求均使用 cpu-review-p43-20261025，命令证据见同名前缀 .command.json。',
              'jobs-focused-summary.json 保留 exec_finish、supervision、authorization_ref、actual_argv、日志元数据。runner-receipt-bindings.json 由归档 stdout JSON 解析，实际五条 mode=train；顶层 run_id、配置快照及 reserved_active_seconds 与副本原始行逐项一致。日志实际 SHA 全与响应 logs.*.sha256 相同。',
              'raw/log-*-stdout.log 与 stderr.log 是实际归档内容。已执行 5 个作业各有完整日志；取消作业没有日志/exec/supervision，不虚构 confirmed_empty。失效或丢失执行归档不是 finished；arm3-seed1 的 lost 与真实组空两项并存。','',
              '## 只读台账副本','',f"生产路径：{db['production_before'][0]['path']}",f"唯一副本目录：{db['clone_directory']}",f"打开 URI：{db['uri']}",f"生产及副本 DB SHA256：{db['production_before'][0]['sha256']}",
              '源 WAL/SHM 在采样前后均不存在；没有漏拷贝已存在侧文件。副本 mode=ro 查询后由 SQLite 新建了0字节 -wal 和32768字节 -shm，因此“整个副本文件集合不变”为 false；副本 DB 主体哈希始终不变。未删除副本侧文件、未重建副本、未重跑查询。db-snapshot.json 与 final-safety.json 记录完整源/副本路径、前后 SHA、存在性及复制策略。副本保留至用户另行处理，本任务没有删除动作。',
              'raw/db-experiment.json、raw/db-runs.json、raw/db-daily-budget.json 包含实际 SQL、参数、mode=ro URI 和完整原始行（含 config_json/manifest_json/reason）。生产从未被 SQLite 或 RunStore 打开。final-safety.json 再次记录生产、保留副本 DB 主体和原 P42/P43 所有文件哈希不变，并单列新建副本侧文件。',
              '', '| Run | 状态 / optimizer steps | 真实 reserved（runs.active_seconds） | terminal elapsed | conservative max |','| --- | --- | ---: | ---: | ---: |']
    for r in ledger['run_breakdown']:
        lines.append(f"| {r['run_id']} | {r['state']} / {r['optimizer_steps']} | {r['reserved_active_seconds_from_runs_active_seconds']:.9f} | {r['terminal_elapsed_seconds']:.9f} | {r['conservative_wall_seconds']:.9f} |")
    lines += ['',f"真实预留和 {ledger['reserved_sum_seconds']:.12f}s；保守和 {ledger['conservative_wall_sum_seconds']:.12f}s；sum 门相对14400s余量 {14400-ledger['conservative_wall_sum_seconds']:.12f}s。",
              '精确映射：src/ainerzero/runtime/lifecycle.py L391，reserve_work L817–832；raw/lifecycle-excerpts.txt 保存行号原文。worker.py L441–495 为终态 max(reserved, updated-created) 和逐 run 求和，raw/worker-excerpts.txt 保存原文。daily_budget 是跨实验全局日账，不能无条件用日总额替代 r13 预留和。',
              f"实验创建 {ledger['calendar_created_at']}；实际 experiments.manifest_json.experiment_budget.max_wall_seconds=14400.0；截止 {ledger['calendar_deadline_local']}。lifecycle.py L434–440 同时按创建时间扣减日历窗。参见 experiment-manifest-interpretation.json。",
              '初始 ledger-arithmetic.json 中 actual_experiment_config_budget=null 只因 experiments 实际字段为 manifest_json；真正 manifest 与上限已在后续 interpretation 文件解析，原始行完整保留。','',
              '## R6 与 frozen 身份','',
              f"当前 RESEARCH_LOG SHA {apr['log']['sha256']}。限定节 L731–799，一条顶格批准行在 L798；逐节/栅栏/引用/缩进过滤后只剩该行。原文 raw/R6-current-section-verbatim.txt、带行号 raw/R6-current-section.txt；算法原文 prereg.py L101–180 见 raw/approval-parser-excerpts.txt。",
              f"prereg 文件 SHA {src['prereg_file']['sha256']}；canonical document SHA {src['canonical_document_sha256']}；包映射 canonical SHA {src['package_map_digest_recomputed']}。",
              '五条 runs.config_json.approval 都记录同一 line=APPROVED…、line_number=798、document_sha256=1cb98a21…5b30、research_log_sha256=cc1a9db00fea295310ddc1d54081c95439af1a9e91a03fa67d2fa82b1048d349。五份归档 stdout approval 同样绑定，核对结果见 approval-binding.json 和 runner-receipt-bindings.json。',
              '当前整份研究日志已有追加，因此当前整文件 SHA 与历史 snapshot SHA 不相同。本次只确认凭证记录之间一致、当前限定节有效；未获得历史整份日志的独立认证副本，不以快照 SHA 反推所有历史文字。P40 卡原始状态/事件见 raw/p40-task.stdout；没有从 accepted 状态倒推运行权限。',
              '21 个 current source package 和 5 个 train/development/export_meta 数据文件匹配 frozen expected SHA，详见 source-data-binding.json。manifest 的正确摘要投影（去掉 episodes 明细、file sizes、完整 source map 等）与 prereg.data_identity 一致，详见 dataset-identity-interpretation.json。初始整对象等式为 false 是摘要和完整 manifest 的结构差异，不是字节完整性失败。',
              'AWZ frozen source_map_digest=35c529b9d77d2b8485a0a8927bdd9929cab9089abd135987d9c792bb9f1f3310；重新计算冻结24文件摘要图一致。现有 AWZ 的 protocols/v9/__init__.py、contracts.py 两项与生成时绑定不同，其完整 expected/current SHA 已单列；不擅自重生成数据，不把后续源码漂移当作历史数据被替换。','',
              '## final 历史访问上界','',
              '实际字段是 dataset_manifest.plan.partitions=[train, development]，并有 plan.final_partition=not_generated_not_read；顶层 partitions 字段不存在。当前 named packets/final.jsonl、truth/final.jsonl 的检查仅 stat/exists，没有读其内容。raw/data-excerpts.txt 保存 require_partition final 封闭守卫，raw/worker-excerpts.txt 保存受限消费路径。',
              '五份实际 actual_argv 和归档 JSON mode=train。日志中 final training/checkpoint 词语不等于 final 分区；absence of log mentions 也不是完整访问审计。日志是程序自身输出，源码守卫是意图/当前机制；两者都不能覆盖任何历史旁路、其他读取器、曾存在后移走文件等情形。历史 final 零读明确 UNVERIFIED，本任务也不以读取 final 数据来证明未读。','',
              '## params 和中间检查点','',
              'checkpoint-inventory.json 是初始当前盘存，仅哈希未加载权重。其历史字段最初是未取得期望值的占位；随后从已保存的 runner 冻结 stdout details.checkpoints[*].sha256 和副本 runs.reason 内的完成 receipt 找到历史记录。最终逐文件结论以 checkpoint-historical-comparisons.json 为准，不能继续把全部20个 checkpoint 一概称无历史记录，也不能称全部20个都已证明。',
              '4 个 completed run：4 个 params.npz 与 sidecar/P40 ledger/runner stdout/DB receipt SHA 均一致；16 个中间 checkpoint 与 runner stdout 和 DB receipt 记录值均一致。runner stdout 的整文件 SHA 与作业终态 metadata 相同；该证据支持“与运行记录哈希一致”，不提供密码学认证、模型行为正确性或完整历史访问审计。',
              'failed run 92b694d35a324af083fc27183bb08f8c：无 params.npz；4 个中间 checkpoint 仅有本轮当前 SHA，本轮没有获得预存期望 SHA，所以历史一致性 UNVERIFIED。初始比较表里该 run 的缺失 params 行也标 UNVERIFIED，含义是不能进行不存在文件的哈希比较，不能写成第5个 params 通过。',
              '', '## 不利事实与授权边界','',
              '原 P42/P43 脚本与报告逐文件 before/after SHA 一致，未执行/覆盖。P43 之“深审后 final 零读成立”“所有5个 params 及全部 checkpoint 匹配”不能原样保留。P43 删除唯一副本导致证据不可复现的问题已以本轮 retained clone 修复，本任务不追溯改写原文件或 accepted 事件。',
              '首次 finalize_report.py 因“整个副本文件集合完全不变”的过严断言失败（SQLite只读副本侧文件新建），原失败 stderr、initial-final-safety.json 和 initial-verification.json 保留。修正核查口径为主体不变并披露侧文件，未修改原始数据或删除证据；早先 verifier 的 passed 仅覆盖当时5组检查，不作为该失败已关闭的证据。',
              '建议收窄至本报告 matrix 支持的事实；P40 仍是未完成实验，r13 窗口已关。本报告零新增运行、零预算调整，不签发 r14 或余量复用授权。P36 未触碰。',
              '', '## SHA 索引与复核','',
              'evidence-index.json 列出本目录所有已交付文件的绝对路径、大小和 SHA（索引自身除外；避免自引用）。submission 中的 report 返回发生于索引形成之后，交回后单列 submission/receipt.json，不用于改写已提交结论。verify_evidence.py 仅检查已保存摘要、SHA 索引和集合关系，不运行产品或源变异。']
    (OUT/'P44-DETAILS.md').write_text('\n'.join(lines)+'\n')
    dump(OUT/'execution-record.json',{'entrypoint_runs':[
        {'argv':['python3','reports/V9-P44/collect_evidence.py'],'cwd':str(ROOT),'returncode':0,
         'stdout_summary':{'jobs_count':6,'clone':db['clone_directory']+'/control.sqlite3','production_unchanged':True,'conservative_sum':3819.310649394989,'reserved_sum':1057.3214704760499,'deadline':'2026-10-25T18:42:26.279864+03:00','approval':True,'source_matches':21,'data_matches':5,'params':4,'intermediate_checkpoints':20},'stderr':''},
        {'argv':['python3','reports/V9-P44/interpret_evidence.py'],'invocation':1,'cwd':str(ROOT),'returncode':0,
         'stdout':'{"checkpoint_comparisons":25,"matched_recorded_hashes":20,"unverified":5,"dataset_projection_match":false,"current_generator_drift":2}','stderr':'','note':'projection included extra spec field; corrected before final report; retained raw input unchanged'},
        {'argv':['python3','reports/V9-P44/interpret_evidence.py'],'invocation':2,'cwd':str(ROOT),'returncode':0,
         'stdout':'{"checkpoint_comparisons":25,"matched_recorded_hashes":20,"unverified":5,"dataset_projection_match":true,"current_generator_drift":2}','stderr':'','note':'uses existing raw responses; no DB open or second snapshot'},
        {'argv':['python3','reports/V9-P44/finalize_report.py'],'invocation':1,'cwd':str(ROOT),'returncode':1,'stdout':'','stderr':'AssertionError: clone_still_unchanged was false because SQLite read-only clone created WAL/SHM; raw traceback retained in raw/finalize-initial.stderr'},
        {'argv':['python3','reports/V9-P44/finalize_report.py'],'invocation':2,'cwd':str(ROOT),'returncode':0,'stdout':'P44 report and final evidence index prepared','stderr':'','note':'Corrected safety assertion checks DB body and separately discloses newly created clone sidecars; no new DB query'}],
        'scope':'Audit command subprocesses have raw separate stdout/stderr. Interactive preliminary file reads and initial show/claim are in tool transcript; final conclusions use independently saved raw evidence.'})
    files=[record(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='evidence-index.json']
    dump(OUT/'evidence-index.json',{'created_at':now(),'files':files})
    print('P44 report and final evidence index prepared')
if __name__=='__main__':main()
