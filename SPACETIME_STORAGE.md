# S03：公开fixture与时空引用产物保存约定

日期：2026-10-12 · 主责统筹：Codex · 状态：**S03/S03-R1已实现并按独立CPU范围验收；342项通过，未训练或提交**。不代表模型时空能力。

依据：[原S03交付](artifacts/reports/S03-grokbot-newbot-20261012T135448+0300.md)、[独立CPU审查](artifacts/reports/S03-review-20261012.md)、[S01契约](S01_REPAIR_PLAN.md)。独立审查原S03 13项通过，并从公开数据重算两份样例全文一致；作者所报2030项全量无XML，本轮未重跑含MLX全量，不作为本次独立验收。

## 三项决定

1. **固定仓库fixture。** 两个现有episode的public.jsonl和manifest.json原样保存，共490,577字节，约479.1KiB；不复制/读取private.json。既有观察/动作/ID/分区/时间/内容摘要保持，不截短伪装原轨迹。
2. **正式引用产物单独归档。** 放到artifacts/spacetime，按分区、episode UUID和快照内容摘要组织；引用修订身份仍是EvidenceLink规范内容及supersedes_sha256，不由文件名或文字充当。
3. **报告继续放reports。** 原报告旁的两sample JSON作为原交付证据保留，不移动、不覆盖；后续归档生成独立新产物，报告引用其manifest/摘要。

## 仓库fixture

```text
tests/fixtures/c0_spacetime_v1/
├── README.md
├── fixture_manifest.json
├── development/242b7060-4a2c-4ca9-aa46-e4bbc59f4786/
│   ├── public.jsonl
│   └── manifest.json
└── train/2d457a1e-c746-48ae-8adb-59b47929d69e/
    ├── public.jsonl
    └── manifest.json
```

fixture_manifest记录格式版本、来源任务/episode/世界/分区、公开文件的大小和SHA、原manifest摘要、公开镜像范围。明确标记contract_test_only、not_for_training及不作为泛化验收。这里的train/development保留原来源分区，不表示测试夹具可自动加入训练。已反复使用的样例不能充当新世界独立能力证据。

原manifest包含private文件的声明元数据；保留原字节不代表private已复制/核对。fixture仅是公开镜像，不能作为完整重放Bundle，不能用空文件或伪造private满足旧加载器。

新增明确的load_public_trajectory入口，严格接受公开镜像的两文件目录，拒绝缺失/多余文件和symlink，复用原manifest/public摘要、头部和完整公开链校验。原load_trajectory、训练准入和replay的完整目录要求保持；不会因新增入口自动接入训练。

S03示例通过显式public-only模式读取fixture，原默认完整轨迹模式保留。测试使用这两个确定路径，缺fixture直接失败，不枚举本机artifacts/c0，也不在缺数据时整组skip；无MLX导入测试始终执行。fixture在工作区建立后仍未提交，跨机器需携带这些文件；本约定不自行授权git提交。

## 正式产物

```text
artifacts/spacetime/<partition>/<episode_id>/<snapshot_digest>/
├── evidence_links.jsonl
├── summary.json
└── manifest.json
```

snapshot_digest为规范身份内容的SHA256，身份至少绑定保存协议/格式、producer、源episode/world/分区、源public/manifest摘要、格号及各EvidenceLink规范摘要。源码/生成配置身份和每个文件的SHA/大小进入manifest；不得用系统路径名推断来源或混合训练/开发。

evidence_links.jsonl逐行保存完整EvidenceLink规范JSON，包括稳定观察引用、asserted_at_step、revision、supersedes_sha256和研究员来源；summary保存示例信息与as-of结果。不把研究员建立的关联称为学生发现，不写入observed经历或假装真实因果。

新目标目录排他创建，存在就拒绝，不覆盖旧快照。manifest在数据写完后最后发布，缺manifest或文件摘要/身份不符的目录不可消费；断写保留未完成现场，不作为completed产物。分区/UUID/摘要都必须验证，拒绝路径穿越和symlink。v0/v1只是同一逻辑链的修订；新增知识或代码版本产生新快照，不覆写旧链。

本阶段不引入SQLite索引、向量库、自动同步或模型训练接口。目录约定是可追溯的工程保存方式，不等于模型学会记忆、4D或语义。

## 本次验收范围

先保存原S03源码和13项CPU基线，再由执行者实现S03-R1，测试可移植fixture、严格public/full入口边界、格号/不可见选择、跨episode引用拒绝、归档读写/摘要/nooverwrite与原文件不变。旧trajectory套件包含reset/step/replay/private读取，本轮不运行这些路径；必要边界以静态fixture和原完整episode的公开只读加载检查，明确未验证范围。

S03不需要审计真值对照：本阶段验证引用是否匹配公开观察及修订视图，不验证物理世界真实状态。未来真实动力学/重放审计再明确范围；不为了当前JSON样例读取private。实际命令/源码/数据/产物身份与失败进入研究日志，模型路线和预算不变。

## 已验证产物

- [固定fixture与来源说明](tests/fixtures/c0_spacetime_v1/README.md)，原四公开文件490,577字节；无private文件，读取结果与两原完整episode的公开加载完全相等。
- [实现报告](artifacts/reports/S03-R1-portable-fixtures-20261012.md)：65项定向测试通过，S03 47项/public loader18项；实际生成两份不可覆盖快照。
- [独立回验](artifacts/reports/S03-R1-independent-recheck-20261012.md)、[342项XML](artifacts/reports/S03-R1-independent-tests-20261012.xml)：上述65项加此前277项CPU契约全部通过，无失败/error/skip/xfail；快照读回、源/旧sample不变及冲突拒绝另经只读核对。
- [development manifest](artifacts/spacetime/development/242b7060-4a2c-4ca9-aa46-e4bbc59f4786/5753d1680fc80038d1a56fb9675d7e1ab11cfef4bca3364cc330512eb49828e1/manifest.json)、[train manifest](artifacts/spacetime/train/2d457a1e-c746-48ae-8adb-59b47929d69e/3ce7fd64d002b18229c7bbaebf4c282b05f9f7fdf8005b5467fe9f2f92d065be/manifest.json)，分别绑定source/producer/引用身份和数据文件大小/SHA。

原完整/训练/replay入口对两文件fixture仍在目录检查处拒绝，不执行环境动作或私有读取；旧trajectory全套和含MLX全量本轮未跑。跨平台移动、真实断电恢复、恶意并发文件系统隔离、生产者认证和大规模索引未验证/未实现；fixture尚未提交，跨机器需携带。已通过的CPU保存工程不改变模型参数、培养计划或晋升状态。
