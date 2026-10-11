# AinerZero

面向 Apple Silicon 的发育式世界模型研究工程。

设计依据见 [实现指南](IMPLEMENTATION_GUIDE.md)。**M0 工程底座已通过验收**：172 项测试通过，真实 MLX CPU / Metal GPU 自检通过。结果与边界见 [M0 验收报告](M0_VALIDATION.md)。

已实现：严格配置和快照、观察/动作数据契约、结构化日志、SQLite 运行状态与持久预算、原子恢复点、硬件检查，以及微型训练验证入口。

架构方案已更新至 v0.5，包含 [架构整改规范](ARCHITECTURE_REVISION.md) 与 [首轮学习计划](FIRST_LEARNING_PLAN.md)。当前已接通 C0 交互、公开轨迹、序列抽样、简单预测基线，以及原 653,072 参数与后续 393,232 参数 MLX 模型的短预算训练和独立开发预测评测。完整规划、持续培养与能力晋升仍未实现。

新增的 [v2 经历契约](src/ainerzero/core/experience.py) 把观察来源、动作决策者和数据分区分开，保留原 v1 接口。`ExperienceTransition` 校验请求/执行/观察的关联；`admit_training` 按明确的操作者与策略版本、辅助条件白名单检查训练准入。师生接管可以复用原观察；开发/最终测试、未知来源与未授权辅助不能混入训练。

[旧记录迁移](src/ainerzero/core/experience_migration.py) 保留 ID、内容和原来源摘要，缺失信息保持未知，统一进入隔离区；不自动认定旧 `observed` 是学生自主经历。C0 采集器已接入 v2 契约；尚无通用回放数据库或来源真实性认证，也不能仅凭单条转换证明整个实验从未接受教师帮助。

经历契约小步的历史验证：全量 252 项测试通过，包含 80 项经历/迁移测试，见 [经历契约测试报告](artifacts/reports/m01-tests.xml)。原 M0 验收报告保留其当时的 172 项结果；M0.1a 整体仍未完成。

## 首轮实验声明与预算

[pilot.yaml](configs/pilot.yaml) 单独登记小模型参数、先天机制与可变状态、无教师条件，以及单次/总实验上限。环境标为 `c0_only`，学习器为 `c0_prediction_only`，规划器仍为 `planned`。以下命令只校验配置并输出完整配置与源码摘要，不创建实验、不开始两小时计时、不加载 MLX：

```sh
.venv-ainerzero/bin/ainerzero check-pilot --config configs/pilot.yaml --output artifacts/reports/m01-pilot-manifest.json
```

[RunStore](src/ainerzero/runtime/lifecycle.py) 新增持久实验身份与总额账本：实际登记实验时开始总墙钟，校准、模型、辅助运行共用环境动作、优化更新和预测展开预算；暂停、失败或重新打开数据库不退还预留额度。首轮所有角色顺序执行，最多三个模型运行，校准仅在模型运行前进行，辅助运行不能执行优化更新。旧 schema 1 数据库在事务中升为 schema 2，保留原有 M0 记录。

有限步数 C0 采集、重放与短训练已接入预算，工作先预留再执行；短训练检查系统余量、进程/MLX 内存、电源和交换空间变化，监督进程限制最长运行时间。尚无完整长期调度器。额度预留与实际完成量分开记录，不把声明或预留当作学习成果。

机制/预算小步的历史验证：全量 411 项测试通过，见 [历史测试报告](artifacts/reports/m01-pilot-tests.xml)。[当时的声明检查结果](artifacts/reports/m01-pilot-manifest.json) 为 `valid / not_started`；该步没有执行环境动作或模型训练。

## C0 环境与可重放交互

[C0 环境](src/ainerzero/environments/c0.py) 已实现八格面板：四个输入、四个复制输出、任意字节显示、四种动作、全部可见且无延迟。普通 reset 保留同一实例规则；每个有效动作都计一步，最多 128 步。公开观察仅含符号、掩码、光标和 episode 开始标记。

```sh
.venv-ainerzero/bin/ainerzero collect-c0 --experiment-id my-c0-check-01 --steps 64 --seed 0 --partition train
.venv-ainerzero/bin/ainerzero replay-c0 artifacts/c0/<上一步输出的episode_id>
```

同一个 `experiment-id` 共用一个最多 10 分钟、1,024 次环境执行的工程检查预算；每次至多 128 步、30 秒墙钟，更紧的用户配置仍生效。重放也计入原实验，失败不退还预留。检查不会自动换 ID 补跑，也不启动首轮两小时学习实验。动作来自固定随机基线，记录为 `baseline`，不是模型自己学习后的选择。训练/开发分区使用不同的世界与动作种子命名空间，当前入口不开放最终评测分区。

[轨迹目录](src/ainerzero/data/trajectory.py) 分为 `public.jsonl`（v2 观察/动作链）、`private.json`（初始完整世界状态）和 `manifest.json`（版本、大小、哈希）。普通加载与训练准入不读取私有状态；显式重放检查才恢复世界并重新执行动作，逐步比较完整观察。损坏、断链和版本不符会失败，已有 episode 不覆盖。哈希是完整性检查，不是来源认证；本步也没有实现崩溃中的自动续采。

C0 交付时的历史验证：全量 570 项测试通过，见 [历史测试报告](artifacts/reports/m1a-c0-tests.xml) 和 [实际运行报告](artifacts/reports/m1a-c0-validation.json)。

| 真实样例 | 采集步数 | 符号变化次数 | 重放 | 训练准入 |
| --- | ---: | ---: | --- | --- |
| 训练分区 | 128 | 31 | 全部一致 | 指定随机基线白名单后允许 |
| 开发分区 | 64 | 6 | 全部一致 | 拒绝 |

这两段历史样例加重放共计 384 次环境执行、0 次优化更新。40 秒是账本保守预留的活动额度，不是实测耗时。序列抽样与预测基线现已实现；目标控制与规划尚未实现。

## 序列、基线与小模型训练

[序列抽样](src/ainerzero/data/sequences.py) 只读取通过白名单准入的公开训练轨迹，抽取 20 个动作与 21 个观察，不跨 episode。前 4 步仅恢复短上下文并截断梯度，随后 16 步计损失；从 episode 中间开始时，这是零初态加短 burn-in 的近似。当前均匀抽取完整窗口，尚无完整的近期/历史/反例混合回放。

[预测基线](src/ainerzero/learning/baselines.py) 包括复制当前观察，以及按格子/当前字节统计下一字节的无动作模型，概率均做 1% 均匀平滑；统计只拟合训练数据。开发预测使用相同查询，先看 32 步支持经历，每 8 步取查询，展开 1/4 步；模型平均 8 粒子的概率后计算 NLL，另报变化格及见过/未见字节结果。所有真实反馈只更新该 episode 的信念，权重冻结，未来观察只作标签。

```sh
.venv-ainerzero/bin/ainerzero train-pilot --experiment-id my-first-fit --seed 0 --updates 100 --train-episodes 16 --development-episodes 4
```

入口采集分区独立的 C0 世界，以有效 batch 16、micro-batch 4、FP32 训练 [RSSM 预测核心](src/ainerzero/learning/pilot_model.py)。每次最多 100 次更新，受既有实验包/运行/每日额度约束；监督进程另设最长 20 分钟上限。默认 adaptive 尚无桌面闲忙探测，因此保守使用 active 档位及 25% 训练占空比；不自动扩模或启动其他运行。报告、逐步损失、数据哈希、模型/优化器/RNG 保存于独立运行目录。

`status=completed` 表示该次流程完成；是否优于基线看 `prediction_gate`。候选不会自动晋升。保存后校验相同输入和随机 key 的输出、权重、优化器与 RNG 一致；尚未实现跨进程续训入口，也不声称已验证恢复后的下一次优化更新。

**首次实跑已完成：100 次更新、约 93 秒；训练损失下降，但新世界预测变差，未通过基线门槛。** 候选未晋升。详情见 [首次训练报告](M2A_FIRST_FIT.md)；[全量 676 项测试通过](artifacts/reports/m2a-tests.xml)。工程流程可用与模型能力达标分开记录。

## 失败诊断与同数据对照

[失败诊断报告](M2B_FAILURE_DIAGNOSIS.md) 已记录正式冻结复现：旧模型约 99.3% 的概率质量落在训练同位置见过的字节上，输入符号置零后预测几乎不变。当前证据支持位置字节记忆与符号输入利用不足；不能据此把所有原因归结为单一超参数。

```sh
.venv-ainerzero/bin/ainerzero diagnose-pilot --source-report artifacts/reports/m2a-first-training.json --experiment-id my-frozen-check
.venv-ainerzero/bin/ainerzero train-pilot --experiment-id my-relabel-check --dataset artifacts/pilot/<来源运行目录>/dataset.json --symbol-augmentation per_window_permutation --seed 0 --updates 100 --train-episodes 16 --development-episodes 4
```

冻结诊断不更新权重，复用公开轨迹，受相同工作锁和预算账本约束；监督进程至多 180 秒，实际模型检查预留窗口为 90 秒。训练复用清单时校验公开数据哈希、分区、世界唯一性及操作者准入，不重新产生环境交互。两条命令使用不同实验 ID，是不同的预登记条件；每日额度仍共用。

符号换名增强默认关闭。开启后，每个训练窗口使用独立字节双射，在时间和位置上保持同一映射，输入与目标同步换名；开发数据原样评测。这是人工指定的归纳偏置，不是新世界知识或新的独立交互。增强 RNG 与抽样/模型 RNG 分开保存；同后端载入检查仍不等于已经验证续训。

这一轮 [725 项测试通过](artifacts/reports/m2b-tests.xml)。实际对照结果及下一步范围统一写入 [诊断报告](M2B_FAILURE_DIAGNOSIS.md)，不根据训练曲线自动扩大模型或追加训练。

## 当前观察已能保存并重建

[M2c 观察优先实验](M2C_OBSERVATION_FIRST.md) 已通过当前观察的独立门槛。原 653,072 参数对照未通过；更小的共享符号候选 `pilot_shared_symbol_v1` 为 **393,232 参数**，开发集 544 个可见符号全部重建正确，每个位置均为 100%。它从可学习嵌入写入内部状态，经独立的可学习读出层重建，没有固定复制输入的输出捷径。

保存权重与临时 h/z 后能正确读回；遮掉输入后准确率为 0%。从已保存权重继续执行 100 次动作预测更新后，重建仍为 100% / NLL 0.0996；动作预测 1/4 步 NLL 为 0.3362 / 1.1382，仍不如复制基线，未晋升候选。这不代表长期记忆、动作规律或规划已通过。

```sh
.venv-ainerzero/bin/ainerzero train-observation --structure shared_slots --dataset artifacts/pilot/<来源运行目录>/dataset.json --experiment-id my-observation-check
# 需要权重巩固时，显式提供上述运行中的 reconstruction 恢复点；优化器重新初始化。
.venv-ainerzero/bin/ainerzero train-observation --structure shared_slots --dataset artifacts/pilot/<来源运行目录>/dataset.json --initial-checkpoint <重建恢复点目录> --experiment-id my-observation-consolidation
```

默认 `--structure paired` 保留原结构/整帧观察写入结构对照；`shared_slots` 只运行更小的共享符号候选。每个候选先做 750 次当前帧重建更新，通过逐位置准确率、NLL、输入置零与状态保存检查后，才允许最多 100 次动作更新。巩固必须显式指定来源；配置、架构、阶段和数据摘要都必须匹配，不支持把 action_prediction 恢复点误作重建来源，也不声称精确续接旧优化轨迹。

M2c 阶段 [779 项测试通过](artifacts/reports/m2c-tests.xml)。[详细报告](M2C_OBSERVATION_FIRST.md) 保留所有失败对照、实际 3,100 次更新与候选位置；后续沿用这一较小模型处理变化样本和多步误差。

## 变化样本与四步预测对照

[M2d 对照](M2D_CHANGED_MULTISTEP.md) 已完成：保持 393,232 参数，对同一父模型分别进行原方法、变化加权、变化加权加四步训练，各 100 次更新。重建均保持 544/544；变化命中仍为一步 0/7、四步 0/25，预测门槛均未通过。四步损失缓解了变化加权组的多步误差，但真实变化预测仍未通过，历史利用情况尚待单独验证，候选未晋升。

```sh
.venv-ainerzero/bin/ainerzero train-dynamics --experiment-id my-dynamics-comparison --dataset artifacts/pilot/<来源运行目录>/dataset.json --initial-checkpoint artifacts/pilot/<来源运行目录>/checkpoints/<动作候选run_id> --output artifacts/reports/my-dynamics-comparison.json
```

固定三组各 100 次更新、相同权重起点及随机抽样；变化权重仅用于训练，评测保留原始分数。四步分支不读中间观察。相同更新次数不代表相同计算量。`--arm changed_four_step` 可显式选择单一已声明条件，程序不自动换 ID 重试。

本轮两次运行时长中断均保留证据，实际共 309 次更新；[797 项测试通过](artifacts/reports/m2d-tests.xml)，三个完成候选保存检查通过。详细数值、资源争用诊断和所有候选见 [M2d 报告](M2D_CHANGED_MULTISTEP.md)。

## 冻结模型的历史诊断

[M2e 历史诊断](M2E_HISTORY_DIAGNOSIS.md) 已完成：同一四步候选的权重逐张量未变，没有训练或新环境交互。完整/清空/打乱较早历史的四步总体 NLL 为 **0.9190 / 3.4011 / 0.8889**，但三者变化命中均为 0/25。持续状态有影响，尚未证明能正确利用动作—结果关联；下一步检查短延迟信息能否由独立探针读出，不扩模。

```sh
.venv-ainerzero/bin/ainerzero diagnose-history --dataset artifacts/pilot/<来源运行目录>/dataset.json --checkpoint artifacts/pilot/<来源运行目录>/checkpoints/<动作候选run_id> --experiment-id my-history-diagnosis --output artifacts/reports/my-history-diagnosis.json
```

额外历史重建先记账再执行，沿用原查询与随机键；模型、数据和恢复点契约不匹配会拒绝执行。实际诊断 17.48 秒、39,488 个逻辑工作单位，重建仍为 544/544。[826 项测试通过](artifacts/reports/m2e-tests.xml)，[证据核对](artifacts/reports/m2e-verification.json) 已完成。

## M2f 短延迟读出诊断

M2f 阶段：[短延迟读出诊断](M2F_DELAYED_READOUT.md) 已完成，实际 11.00 秒，910 项测试通过。学生 393,232 参数保持冻结；外部读出器对过去 1/2/4 步变化符号的开发命中为 1/77、2/124、5/207，无历史两组均为 0，但其跨世界总体读出远劣于复制当前。原符号解码与当前重建仍为 100%；公开轨迹统计显示探针训练符号支持有限，不能把探针泛化失败解释为学生没有记忆。下一小步先校准外部读出：固定当前通路加残差，并加零延迟对照，暂不改学生或扩模。

M2g 阶段：[固定当前通路与残差读出](M2G_RESIDUAL_READOUT.md) 已完成，12.09 秒、962 项测试通过。零延迟原密集读出开发准确率为 70.23%，固定当前通路为 100%，确认外部读出存在泛化限制。残差三组的变化回读仍为 0/77、0/124、0/207；完整历史保住了 1/2 步未变化符号，4 步仍有损伤。学生 393,232 参数、权重未变、重建仍为 544/544，未晋升。该阶段提出转向一步上一观察保留任务，后续实测见 M2h。

M2h 阶段：[一步上一观察保留](M2H_ONE_STEP_MEMORY.md) 已完成实现、1,075 项测试和一次固定 100 次更新，实际 57.22 秒。模型仍为 393,232 参数，仅更新已有 GRU；有界符号兼容性为 256/256，但开发上一帧读回仅 5.03%、变化命中 2/77，未过筛查。原四步动作准确率从 93.49% 降至 1.82%；重建仍为 544/544。候选仅留档，原检查点未替换。该阶段提出冻结参数消融，后续结果见 M2i。

M2i 阶段：[GRU 干扰消融](M2I_GRU_INTERFERENCE.md) 已完成，42.49 秒、1,235 项测试通过，0 次训练更新。恢复候选前半参数后，四步动作准确率从 1.82% 回到 58.33%，仍低于原模型 93.49%；四步 NLL 差距仅恢复 21.89%。变化记忆仍为 2/77，总体读回降至 3.06%。原模型与候选评测逐值复现；三组权重未变、未晋升。该阶段提出验证最短写入，后续训练与结果见 M2j。

M2j 阶段：[单条反馈边记忆拟合](M2J_MICRO_MEMORY_FIT.md) 已完成。修复梯度容器兼容问题后固定训练 200 次，108.93 秒、1,402 项测试通过。16 条训练经历的 128 个符号及 29 个变化符号，在两组随机条件下均 100% 读回；连续训练记忆为 29.44%，连续开发记忆仅 1.10%、变化 0/77。一步/四步动作准确率保持 98.18%/93.49%，但 NLL 略差。393,232 参数保持，282,128 个冻结参数逐位未变，未晋升。后续配对诊断已完成，见 M2k。

M2k 阶段：[同样本零状态/历史对照](M2K_PAIRED_MEMORY_DIAGNOSIS.md) 已完成，75.14 秒、1,523 项测试通过，全部权重未变、0 次更新。已拟合样本在两种条件下均 100%；排除与拟合样本相同的上一观察后，其余训练查询为 42.63% / 34.76%。开发世界即使零状态也仅 0.37%，带历史 0.78%，但 NLL 更差、变化命中由 3/127 降至 0/127。输入泛化不足与部分历史干扰并存，未晋升。下一步保持小模型、零状态和一步任务，先增加训练输入多样性；该训练的结果见 M2l。

M2l 阶段：[多样输入一步记忆拟合](M2L_DIVERSE_MEMORY_FIT.md) 已于 2026-10-07 完成，固定 200 次更新，230.17 秒、1,699 项测试通过。零状态 / 带历史总体为 77.38% / 72.35%（历史减零 −5.02 个百分点）；上一观察不在训练池中的 505 条训练查询零状态达 86.36%，开发世界仍仅 1.34% / 0.00%。一步/四步动作准确率保持 98.18%/93.49%，重建 544/544；开发留存筛查未通过，未晋升。

最新 M2m-a：[零更新槽位干扰诊断](M2MA_SLOT_INTERFERENCE_DIAGNOSIS.md) 已完成。2026-10-11 首次运行因系统内存余量守卫中止（留档）；经批准于 2026-10-12 用新实验 `m2ma-slot-interference-20261012-r1` 重跑完成，158.27 秒，106,496 单位，0 次更新，权重未变，1,794 项测试通过。零状态下，同位置见过的格 93.98%，同位置未见的格仅 1.04%；开发世界见过的格也只有 2.80%。单格替换成该位置未见的字节，替换格准确率 0.10%，其余 7 格仅下降 0.36 个百分点。判定 R1 成立、R2 不成立：主因是逐位置符号身份覆盖，单格跨槽干扰未证实。按规则支持由用户登记 M2m 阶段 B（一致换名训练），不自动启动。[报告](artifacts/reports/m2ma-slot-interference-r1.json)、[核对](artifacts/reports/m2ma-verification.json)。

```sh
.venv-ainerzero/bin/ainerzero diagnose-memory-coverage \
  --dataset artifacts/pilot/pilot-b27a34514fe74ba2a969bad3c24d3ee3/dataset.json \
  --checkpoint artifacts/pilot/pilot-92e978f05bb941768a34f13a76ddf3f5/checkpoints/f33974c9-b86f-4429-9ea9-8ea0e733142a \
  --candidate-checkpoint artifacts/pilot/pilot-ff914460c9c64154909a24a2b0257f0c/checkpoints/e83c54e7-6dcd-4a32-950f-8c4b725423d8 \
  --source-report artifacts/reports/m2l-diverse-memory.json \
  --experiment-id <新的实验ID> \
  --output artifacts/reports/<本次报告>.json
```

新增 `diagnose-recall` 入口，复用现有数据和检查点；9 个外部探针独立保存，训练轨迹拟合后才评分开发轨迹。学生 0 更新、新环境 0 动作，重建仍为 544/544，42,368 个逻辑工作单位与账本一致。[完整结果](artifacts/reports/m2f-recall.json)、[核对记录](artifacts/reports/m2f-verification.json)和[910 项测试](artifacts/reports/m2f-tests.xml)均已保存。

## 安装

需要本机已有 Python 3.12、uv；保留原 `.venv`，使用单独的 `.venv-ainerzero`。

```sh
UV_PROJECT_ENVIRONMENT=.venv-ainerzero uv sync --locked --extra metal --no-python-downloads
```

不会下载预训练权重或数据集。无 MLX 时仍可运行基础测试，依赖 MLX 的测试会明确跳过；微型网络自检需要 MLX。本轮完整验收在本机 Apple Silicon 上完成，未验证其他平台。

## M0 可用入口

```sh
.venv-ainerzero/bin/ainerzero check-config --config configs/brain0.yaml
.venv-ainerzero/bin/ainerzero doctor --require-gpu --output artifacts/reports/hardware.json
.venv-ainerzero/bin/ainerzero smoke --device cpu --output-dir artifacts/m0
.venv-ainerzero/bin/ainerzero smoke --device gpu --output-dir artifacts/m0
.venv-ainerzero/bin/python -m pytest
```

`smoke` 只对随机初始化的微型网络做有限步数的合成数据测试，验证前向、梯度、参数更新、持久预算和恢复点；不会启动 Brain-0 培养或后台服务。GPU 不可用时明确失败，不静默改为 CPU。

默认自检包含原始训练 64 步、从中点恢复后重演 32 步，共实际执行 96 次更新；报告分别记录。每次运行将配置、日志和恢复点写入独立目录。共享预算保存在 `artifacts/control.sqlite3`，更改报告输出目录不会重置预算。`reserved_*` 是工作前保守预留额度，实际完成次数另行记录，不能把预留时间当作实测耗时。

`configs/brain0.yaml` 保留旧 schema 的模型与资源规划值；首轮小模型使用独立的 `configs/pilot.yaml`，由 `check-pilot` 严格检查。M0 自检的实际网络为 `4 → 16 → 2`、FP32、114 参数，使用独立的测试优化器设置，并写入报告；修改 Brain-0 网络维度不会改变这个自检网络。

固定小批次的一步写入可拟合；M2l 增加训练输入多样性后，训练分布内零状态读回明显提高，但开发世界仍几乎为零，历史仍有净负影响。M2m-a 零更新诊断显示主因是逐位置符号覆盖（R1 成立），单格跨槽干扰未证实（R2 不成立）；下一步由用户决定是否登记 M2m 阶段 B 一致换名训练。随后补齐 Bundle、C1–C4 和最小实验台。两小时是首轮实验包预算上限，不保证在该时间内学会。M4 完成长程调度与完整控制台。当前没有前端、API 或管理后台地址。
