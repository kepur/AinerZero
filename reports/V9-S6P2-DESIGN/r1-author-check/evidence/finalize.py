"""Condense delivery summaries and seal report-local checksums; no tests or model work."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
E = OUT / 'evidence'


def write_json(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')


detail = json.loads((OUT / 'metrics.json').read_text())
(OUT / 'metrics.json').rename(E / 'detailed-results.json')
q = json.loads((E / 'quantiles.json').read_text())
c = json.loads((OUT / 'corrected-check/RESULTS.json').read_text())
provenance_rel = 'reports/V9-S6P2-DESIGN/r1-handoff/I-ROUND-PROVENANCE.txt'
provenance_data = (ROOT / provenance_rel).read_bytes()
(E / 'I-ROUND-PROVENANCE.author-log.txt').write_bytes(provenance_data)
provenance = {'path': str(ROOT / provenance_rel), 'sha256': hashlib.sha256(provenance_data).hexdigest(),
              'classification': 'author tool log excerpt, NOT a sealed runtime manifest',
              'recorded_author_tool_call_utc': '2026-11-16T20:40:08.428Z',
              'historical_environment': {'S6P2_WORLDS':600,'S6P2_BIG':60,'S6P2_TINY':30,'S6P2_LARGE':30,'S6P2_NS':'s6x-p2i-cand'},
              'historical_argv_arms': ['O+','U+','Q+','W+','R+'],
              'per_rounds_steps_lr': 'omitted in historical launch; original source defaults 1500/4/1000/0.001 match results config',
              'not_executed_here': True}
write_json(E / 'provenance-summary.json', provenance)
last = []
for row in detail['input_files']:
    p = ROOT / row['path']
    sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    if sha != row['sha256']:
        last.append({'path': row['path'], 'snapshot_sha256': row['sha256'], 'current_sha256': sha})
write_json(E / 'delivery-input-drift.json', last)
frozen = detail['phase1_frozen']
identity_paths = ['reports/V9-S6P2-DESIGN/tier1-explore/results-p2i.json',
                  'reports/V9-S6P2-DESIGN/tier1-explore/run-p2i.log',
                  'reports/V9-S6P2-DESIGN/tier1-explore/explore_p2f.py',
                  'src/ainerzero/v9/experiments/s6/world_b.py',
                  'tests/v9/experiments/test_s6_world_b.py',
                  'reports/V9-S6-PHASE1/PREREG-r1.json',
                  'reports/V9-S6P2-DESIGN/DESIGN-r1.md']
identities = {r['path']:r['sha256'] for r in detail['input_files'] if r['path'] in identity_paths}
summary = {'schema':'s6p2-r1-author-check-summary-v1',
           'role':'P269 auxiliary author-side CPU delivery check; NOT independent design acceptance',
           'status':'scoped_checks_pass_with_preserved_checker_failures_and_provenance_limits',
           'created_utc':datetime.now(timezone.utc).isoformat(),
           'pytest':{'rc':detail['tests']['returncode'],'passed':12,'elapsed_s_reported':1.96,
                     'raw_stdout':'evidence/pytest.stdout.log','raw_stderr':'evidence/pytest.stderr.log',
                     'initial_attempt_rc':3,'initial_attempt':'evidence/attempt1/',
                     'mlx_loaded_or_attempted':False,'outside_delivery_test_writes':False},
           'numeric_checks':{'arms':5,'rounds_each':4,'log_numeric_fields_matched':180,'per_net_means_matched':200,
                             'first_round_exact_equal':True,'pick_count_checks':60,'failed_checks':0},
           'final_H':detail['final_H'],'final_H_O_minus':detail['final_H_difference_O_minus'],
           'GO_point':detail['GO']['value'],'formal_gate_accepted':False,
           'O_decoy_rounds_2_to_4':detail['decoy_rounds_2_to_4']['O+'],
           'decoy_semantics':'tiny_world = tiny + large decoys; last-round 0.021333 is not three-round 0.031556',
           'config':{'results':detail['config']['recorded_results'],'candidate_worlds':600,'big':60,'tiny':30,'large':30,
                     'namespace':'s6x-p2i-cand','source':'evidence/provenance-summary.json (author log, not sealed runtime manifest)'},
           'phase1_freeze':{'prereg_path':frozen['prereg_path'],'files_checked':46,'matches':46,
                            'numerical_closure_files':42,'code_manifest_sha256':c['numerical_42_sha256'],
                            'code_digest_match':True,'correction':'corrected-check/RESULTS.json'},
           'quantiles':{r['revision']:{'t':r['t_ppf'],'repeat_halfwidth':r['repeat_layer_halfwidth_coefficient']} for r in q['rows']},
           'r0_2_4313_rounding_correct':q['r0_2_4313_correct'],
           'formal_design_user_stated':q['formal_design_user_stated'],
           'input_sha256':identities,'shared_workspace_changed_paths':[r['path'] for r in last],
           'evidence_index':{'full_numeric_records':'evidence/numeric-comparison.json',
                             'input_identities':'evidence/inputs-before.json','freeze_46_paths':'evidence/frozen-after.json',
                             'quantiles':'evidence/quantiles.json','manifest_correction':'corrected-check/RESULTS.json',
                             'initial_analysis_failure':'evidence/analysis1/','test_import_write_guard':'evidence/pytest-guard.json'},
           'limitations':['Current source SHA does not prove historical execution source SHA.',
                          'Metrics are checks of saved exploration JSON/log and per-network aggregates, not replayed model inference.',
                          'No confidence interval or design acceptance inferred from single exploration repeat.',
                          'Concurrent edits to coordination/research/design are preserved; calculation uses saved snapshot.'],
           'model_budget_reserved':0,'model_work_completed':0}
write_json(OUT / 'metrics.json', summary)
with (OUT / 'corrected-check/CORRECTION.md').open('x') as f:
    f.write('''# 作者侧分析工具修正（不是冻结文件损坏）

原失败完整保留在 `../evidence/analysis1/`。原检查错误地把 46 文件完整冻结清单的摘要，与 `code_manifest_sha256` 比较；JSON 紧凑编码本身没有用错。

本次从保存的生产源码 AST 提取并执行纯 Python 的 `run_guard.build_manifest`/静态 import closure 与 `prereg_identity.manifest_sha`，分别按 `make_prereg.py` 和 `current_identity` 的真实调用表达式重建集合。没有导入这些仓库模块或 MLX。

- 完整冻结集合：46 文件，重建后的路径和逐文件 SHA 与 PREREG 完全相同。
- 数值代码闭包：42 文件，是 `current_identity` 实际登记的集合。
- 42 文件摘要：`dce517dfa554ad57bb60e9fec855c8954eeefd7ee75781f64ac22665dc2b29d1`，与注册值一致。
- 差集仅为下列 4 路径：
  - `reports/V9-S6-DESIGN/DESIGN-r3.md`
  - `reports/V9-S6-PHASE1/make_prereg.py`
  - `reports/V9-S6-PHASE1/prereg_evidence.py`
  - `reports/V9-S6-PHASE1/prereg_identity.py`

生产函数位置、原始调用表达式、源码 SHA 与复算结果见 `RESULTS.json`。本检查 rc=0，原失败是分析工具比较错集合，不能据此宣称真实 manifest 损坏。未改任何冻结文件或原失败证据。
''')
rows = '\n'.join(f"| {a} | {detail['final_H'][a]:.12f} | {detail['final_H_difference_O_minus'].get(a,0):+.12f} |" for a in ['O+','U+','Q+','R+','W+'])
with (OUT / 'CHECKS.md').open('x') as f:
    f.write(f'''# S6P2 r1 作者侧 CPU 交付检查

限定作者侧辅助；P269 由 codex 持有，本次未占新卡，不构成独立设计验收或运行授权。只写本目录；没有模型加载、MLX 导入、摸底复跑、源码/测试/设计修复或 git add/commit/push。

## 结果与 rc

- 指定命令 `.venv/bin/python -m pytest tests/v9/experiments/test_s6_world_b.py -q`：**12 passed in 1.96s，rc=0**。完整 stdout、stderr、rc、argv 和环境调整见 `evidence/pytest.*` / `evidence/pytest-command.json`。
- NumPy 测试：检查了测试、world_b、world-A、sandbox 的实际 import；运行时 guard 记录 MLX 导入及尝试均为 0，越界写入为 0。额外第三方 pytest 插件未加载；cache、临时文件和 logging 全部定向本目录。
- 五臂 × 四轮：**180/180** 日志数值按原 `.3f`（picks）/`.4f`（指标）精度一致，含每轮 H、D_A、all_A 和三种 picks 比例；额外核对全部 **200/200** 网络指标均值及 **60/60** 整数 picks 计数。首轮所有公共指标、picks、per_net 精确相同，O 专有布局诊断除外；不据此证明选样 ID 或权重逐位相同。
- 数值分析、补充 quantile、生产 manifest 修正检查：**rc 均为 0**。不追加其他测试。

## 末轮点值

O+ 为日志代号，正式主臂名 N+。

| 臂 | 最终 H | O+ 相对该臂的 H 差 |
|---|---:|---:|
{rows}

GO = `(H(O+)−H(R+)) − 0.5×(H(W+)−H(R+))` = **{detail['GO']['value']:.12f}**。只有一个探索重复，没有正式区间，不能称门通过。

O 第 2–4 轮诱饵比例为 **0.049333333333、0.024000000000、0.021333333333**；计数 74、36、32，每轮分母 1500，因此三轮合计 **142/4500 = 0.031555555556**。`tiny_world` 同时含小诱饵与大诱饵；末轮 0.021333333333 不等于三轮均值。

## t 与重复层半宽

以一期 `s6/analysis.py` 的 t_cdf/_invert/t_ppf 纯 math 函数 AST 计算，并用独立 Student 密度 Simpson 积分交叉核对（CDF 残差 <1e-12）；r0 另用 70 位 Decimal、df4 闭式核对。

| 版本 | K / m / df | t 临界值 | 重复层半宽系数 t/√K |
|---|---|---:|---:|
| r1 | 10 / 10 / 9 | 3.68966239230421 | 1.1667736956747021 |
| r0 | 5 / 9 / 4 | 5.436591556004132 | 2.4313176570253185 |

r1 写 **3.689662、1.166774** 正确；r0 写 **2.4313** 按四位小数舍入正确，无需修正。r0 数学概率的高精度半宽为 2.43131765702533477098…；与 float 输入的尾位差异不影响上述舍入。重复层半宽约缩小 52.0106%，世界层仍须另合并。详见 `evidence/quantiles.json`。

按用户本轮明确的正式规模记录：N+,R+,E+,Q+,U+,W+,N− 共 7 臂 × 10 = **70 格、210 网络、840 权重**，m10、df9，旧门不降。本次不验收整体设计，也不新增实现或运行。

## 一期冻结与分析工具修正

实际 PREREG 路径：`/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-PHASE1/PREREG-r1.json`，字段 `manifest`。实际 46 个路径及逐项 expected/actual SHA 完整列于 `evidence/frozen-before.json` 和 `evidence/frozen-after.json`：**46/46 一致**。

原分析错误地把完整 46 文件集合摘要与 42 文件数值闭包摘要比较，属于**分析工具失败，非真实冻结失败**。原失败输出与脚本保留于 `evidence/analysis1/`。已在 `corrected-check/` 从生产 build_manifest/current_identity/make_prereg 的源码 AST 独立重建两个集合；46 文件完全匹配，42 文件 SHA 正好为注册值 **dce517dfa554ad57bb60e9fec855c8954eeefd7ee75781f64ac22665dc2b29d1**。差集四条具体路径见 `corrected-check/CORRECTION.md`；未修改原证据。

## 来源、配置与边界

results 配置为 per=1500、rounds=4、steps=1000、lr=0.001。补充读取作者提供的 `r1-handoff/I-ROUND-PROVENANCE.txt`（2026-11-16T20:40:08.428Z 工具调用）：600 世界，60 big、30 tiny、30 large，namespace `s6x-p2i-cand`，启动省略上述四参数而沿用默认值。此来源是**作者工具日志，不是密封运行 manifest**；只读保存为 `evidence/I-ROUND-PROVENANCE.author-log.txt`，未执行其中命令。起点/测试分区、源码默认值和 SHA 身份见 `evidence/detailed-results.json`、`evidence/provenance-summary.json`、`evidence/inputs-before.json`。

当前源码 SHA 不能冒充历史执行源码身份；没有重跑推理或读取检查点验证。共享工作区期间协调文件、研究记录与设计稿被他人更新，均未撤销或覆盖；数值核对使用保存的输入快照，具体变化见 `evidence/delivery-input-drift.json`。初读时设计里的 I 轮占位符在快照保存前已由作者补齐，不记作当前缺陷。

首次 pytest 因本检查自加的严格写保护拒绝默认 `/dev/null` logging 而 rc=3，尚未执行测试；原 stdout/stderr/rc 保留在 `evidence/attempt1/`。将 logging 明确指到交付目录后通过，没有修源码或测试。所有既有失败证据保留。

输入 SHA 集中记录在 `evidence/inputs-before.json`；结果摘要在 `metrics.json`；完整数字比较在 `evidence/numeric-comparison.json`。`SHA256SUMS.txt` 覆盖本目录所有文件（自身除外），含原始输出、脚本、输入快照与修正证据。
''')
write_json(E / 'delivery-rc.json', {'pytest':detail['tests']['returncode'],
    'numeric_analysis':int((E/'analysis.rc.txt').read_text()),
    'quantiles':int((E/'quantiles.rc.txt').read_text()),
    'corrected_production_manifest':int((OUT/'corrected-check/rc.txt').read_text()),
    'preserved_initial_pytest':3,'preserved_initial_analysis':'incorrect-set comparison (logical failure, process rc=0)'})
files = sorted(p for p in OUT.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt')
with (OUT / 'SHA256SUMS.txt').open('x') as f:
    for p in files:
        f.write(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(OUT)) + '\n')
for line in (OUT / 'SHA256SUMS.txt').read_text().splitlines():
    sha, rel = line.split('  ', 1)
    assert hashlib.sha256((OUT/rel).read_bytes()).hexdigest() == sha
print(json.dumps({'path':str(OUT),'pytest_rc':0,'quantile_rc':0,'corrected_manifest_rc':0,
                  'frozen_files':'46/46','sha256_entries_verified':len(files),'summary_bytes':(OUT/'metrics.json').stat().st_size,
                  'shared_changes':[r['path'] for r in last]},ensure_ascii=False))
