import json
from pathlib import Path
P=Path('/Users/mac/AinerWorkFlow/AinerZero/reports/character-first-landing-20261017/workbench')
AZ='/Users/mac/AinerWorkFlow/AinerZero'
AWZ='/Users/mac/AinerWorkFlow/AnimeWorldZero'
report=AZ+'/reports/character-first-landing-20261017'
plan=AWZ+'/docs/design/CHARACTER_FIRST_LANDING_PLAN.md'
adr=AWZ+'/docs/adr/ADR-0013-character-first-production.md'
claim=json.loads((Path(report)/'source-before.json').read_text())
doc_files=[x['path'] for x in claim['edited_existing_files']]+[plan,adr,report+'/CLAIM.md',report+'/REPORT.md',report+'/source-before.json',report+'/source-after.json']
ctx=[AZ+'/AGENTS.md',AZ+'/COORDINATION.md',AWZ+'/AGENTS.md',AWZ+'/COORDINATION.md',AZ+'/ARCHITECTURE_BASELINE.md',AWZ+'/docs/design/V9_LANDING_PLAN.md',AZ+'/reports/architecture-character-first-20261017/PROPOSAL.md',AZ+'/reports/architecture-character-first-20261017/REVIEW.md',report+'/CLAIM.md',plan]
common='用户本轮“好的那工作台和方案落地”授权仅文档/任务落地。当前跨仓文档范围由主责明确授权，未扩大 projects.related_roots；不含实现、Schema、测试、模型、训练、渲染、下载、付费、提交、推送或服务部署。awz.V9.A10 保持 draft，原业务前置与所有冻结身份不变。'
def task(seq,title,kind,tier,deps,verifies,scope,prompt,acceptance):
 return {'project':'awz','phase':'CF','track':'A','seq':seq,'title':title,'kind':kind,'tier':tier,'status':'ready','prompt':common+'\n'+prompt,'params':{'execution_authorization':'design_only','module_hint':'0.1','run_authorized':False,'all_new_runtime_budgets':'unapproved','extension_id':'CF-r1-20261017'},'acceptance':acceptance,'context_files':ctx,'file_scope':scope,'depends_on':deps,'verifies':verifies,'workdirs':[AWZ],'needs_gpu':0,'needs':['text'],'dedupe_key':'cf-r1-20261017-awz-A'+str(seq),'max_attempts':3,'max_stalls':5,'lease_s':1800,'actor':'codex-cf-20261017'}
a1=task(1,'【文档】Character First 架构与方案落地（当前整理归档）','design',2,[],[],doc_files,'当前文档作者 proposal_writer。先读 CLAIM 和 source-before；在领取文件内整合现行 v9 r5 与 CF 扩展，按真实消费者缺口拆小任务、复用旧卡。改旧文档前逐字节备份与身份校验，保留原报告/附件/冻结基线。提交 REPORT/source-after；不得自验。','交付 ADR-0013、正式落地计划、原入口追加指针与来源身份；任务逐项保留 A10/原业务依赖、文件范围、非作者搭档及反例。坏对照：AinerZero 被生产前置、World Compiler 获世界写权、ready 实现或未批预算冒充批准，必须被标为不允许。原冻结 JSON/旧候选字节不变。')
a2=task(2,'【只读复核】独立核对 Character First 发布候选（非文档作者）','verify',2,['awz.CF.A1'],['awz.CF.A1'],[report+'/INDEPENDENT_REVIEW.md'],'当前非作者 character_inventory。按 A1 精确 source-after 身份只读逐项核对正文/消费者/任务依赖/文件范围，审阅所有新文档和改动入口。报告只写 INDEPENDENT_REVIEW.md；不得修作者正文、不做 CPU/运行测试。检查现场旧卡状态和 related_roots 不能当已有授权。','非作者报告引用最终被审 SHA/改动范围；核对三系统权威、120Hz/音频锁/单写者、ADR-0007、来源隔离、拆卡与非作者配对、旧前置/暂停/预算；实际反例逐项指出拦截条款。发现阻碍必修项即报告，不能通过 accepted/文档完成推断能力通过。')
a3=task(3,'【一级】Character First 设计发布与工作台落地验收','decision',1,['awz.CF.A1','awz.CF.A2'],[],[report+'/DECISION.md',report+'/workbench/registration-result.json',report+'/workbench/overview.md','/Users/mac/AinerWorkFlow/AinerRelay/modules/modules.v1.json'],'主责 Codex 依据 A2 非作者复核对最终文档身份办理设计范围验收。核对每张实际新卡与模块归档、原卡状态/依赖、项目 roots 未变；只在独立报告建议通过且必修项关闭后验收。记录 CF 文档发布与运行/能力未验证的边界。','非作者建议通过；精确 SHA 与任务 ID/seq/depends_on/verifies/文件范围逐项匹配；新实现保持 blocked，A10 draft，旧 gated 任务/项目元数据不变；所有新卡唯一模块归档，成熟度与 paused 不变；不得把设计接受写成代码总门/能力/预算通过。')
(P/'current-doc-payloads.json').write_text(json.dumps([a1,a2,a3],ensure_ascii=False,indent=2)+'\n')
(P/'phase-track-payloads.json').write_text(json.dumps({'phases':[{'project':'awz','code':'CF','title':'Character First 制作能力升级','goal':'角色表演、跨工具编译与可编辑交付；文档/任务先落地，所有新增实现和运行保持门控。','actor':'codex-cf-20261017'},{'project':'hub','code':'CF','title':'Character First 制作脑升级','goal':'复用制作计划和表演接口，补消费者与编辑链；不新增世界权威。','actor':'codex-cf-20261017'}],'tracks':[{'project':'awz','phase':'CF','code':'A','title':'架构与工作台落地','actor':'codex-cf-20261017'}]},ensure_ascii=False,indent=2)+'\n')
print(P/'current-doc-payloads.json')
