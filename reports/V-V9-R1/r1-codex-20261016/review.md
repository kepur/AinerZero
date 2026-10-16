# ainerzero.V9.R2 独立复核 r1

复核者：`codex-exec-r2-20261016`，真实身份为 Codex 子代理，tier 2 / kind codex；R1 作者为 `musespark-7f3q`。访问日期：2026-10-16（+03）。**不建议按当前字节验收 R1；先补修，再独立复核。** 此报告不办理 accept/reject，不改登记表或源码。

## 决定与必修项

1. **不成立：THICK 没有可找到的官方代码、依赖未知、任何实现都须重新推导。** [作者网站](https://cgumbsch.github.io/blog/thick) 直接链接 [TF2 官方实现](https://github.com/CognitiveModeling/THICK) 与 [JAX 官方重实现](https://github.com/CognitiveModeling/thix)。TF2 的 [LICENSE](https://github.com/CognitiveModeling/THICK/blob/main/LICENSE) 为 MIT，版权年份 2024。R1 的 `repo`、`license`、MLX 依赖说明及相应不可推断项需要改成与这条证据一致的表述。JAX 的根目录未见 LICENSE，**不能把 TF2 的 MIT 套用给 JAX**。没有运行任一实现。
2. **不成立：Stable WorldModel 论文日期 2026-05-26。** [arXiv 官方记录](https://arxiv.org/abs/2605.21800) 明示 v1 于 **2026-05-20** 提交。MD 与 JSON 均写错，应同时修正。标题、作者、v1、代码 MIT 和主要机制一致。
3. **V-JEPA 2.1 主结论成立，但来源登记有缺失。** 本轮直接打开 [2.1 论文](https://arxiv.org/abs/2603.14482)：v1=2026-03-15，v3=2026-06-11。R1 的 2026-03-16 已正确标注为仓库发布日期，不能将其另判为错误提交日期；但 `paper.url` 实际指向仓库，没有记录论文版本。补直接论文地址与版本，分别保留发布日期。原执行报告已诚实披露未打开该论文，此处关闭了“论文机制无法核”项。

这些是原卡“逐条核版本、许可与原文，指出缺失”的落实，没有扩大下载、运行或性能门槛。R1 的机器结构和不可推断项普遍齐全，不能以此抵消以上事实错误。

## 逐条结果

| 条目 | 论文身份与日期/版本 | 代码许可 | 机制与结论 | 总判定 |
|---|---|---|---|---|
| H-JEPA | v1 2026-10-05，一致 | MIT，一致 | 分层 action-conditioned JEPA、自顶向下子目标一致；73.3% 是官方 README 的 AntMaze 数字 | 一致 |
| LeWM | 首稿 2026-03-13 / v3 2026-06-03，一致 | MIT，一致 | SIGReg、CEM、192维表征与约15M/最高48×均有原文；不能推出本机收益 | 一致 |
| V-JEPA 2/2.1 | 2 为 v1 2025-06-11；2.1 为 v3 2026-06-11；原表只记发布日 | MIT主体、三个所列文件 Apache-2.0，一致 | Dense Predictive Loss / Deep Self-Supervision 一致；decord 的 macOS 问题有官方原文 | 一致但缺直接论文URL与版本 |
| DreamerV3 | v2 2024-04-17 / 首稿2023-01-10，一致 | MIT，一致 | categorical表征、想象轨迹、JAX、Linux/Mac Python3.11+、DreamerV2重实现声明均一致；Nature2025见README引用 | 一致 |
| Stable WorldModel | v1真实提交日2026-05-20；原表05-26 | MIT，一致 | collect/train/MPC、FoV与CEM/iCEM/MPPI一致 | 不一致 |
| EGNN | v3 2022-02-16 / 首稿2021-02-19，一致 | MIT，一致 | 旋转/平移/反射/置换等变和轻量中间表示一致，官方代码PyTorch1.7.1 | 一致 |
| Slot Attention | v2 2020-10-14 / 首稿2020-06-26，一致 | 父仓Apache-2.0，一致 | 竞争绑定、可交换slots、TF2.2+、CLEVR首次自动下载17.7GB及不可比ARI说明一致 | 一致 |
| THICK | 作者网站与代码确认题目/作者/ICLR2024 spotlight；OpenReview受challenge，camera-ready字节无法核 | TF2 MIT；JAX根许可无法核 | 稀疏context/高层仅预测切换一致；“无官方代码”被作者链路反证 | 不一致；camera-ready无法核 |

逐条官方地址、网页访问引用位置及限制见 `source_review.json`。**一致不等于复现成功**：MLX 评级是静态适配意见，EGNN“移植成本最低”的相对排序没有测量支撑，宜标为意见；未做任何模型导入、推理、训练或性能实验。THICK 的论文版本无法核，必须保留未知，不得以作者页代替 camera-ready 文件身份。

## 独立 CPU 验证与真实非零反事实

实际命令（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）：

```text
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent codex-exec-r2-20261016 --tier 2 --kind codex --note 'Codex 子代理；本轮仅 V9.R2 独立复核；无可验证外部模型身份'
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.R2 --agent codex-exec-r2-20261016
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay show ainerzero.V9.R1 --full
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay prompt ainerzero.V9.R1
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay prompt ainerzero.V9.R2
python3 -B reports/V-V9-R1/r1-codex-20261016/run_controls.py
```

最后一条父进程 exit 0。独立编写 `independent_check.py`，**未导入、复用或执行 R1 校验器**。15 个真实子进程的 argv、输入 SHA、退出码和日志在 `controls.json`：

- 原件结构 baseline：exit 0；原件 Stable 日期、THICK 仓库、THICK 许可三项事实断言分别 **exit 1**，保留三个失败日志。
- 正对照：只在报告目录的临时测试副本替换以上三项事实，exit 0。该副本只是校验器对照，其他文案仍为原件，**不是修订登记表或候选交付**，不能拿它算修复完成。
- 新增10个不利反例：删除条目、重复ID、损坏论文URL、不存在日历日期、清空许可、清空不可推断项、伪造论文日期、伪造THICK不存在、伪造THICK许可（MD同步伪造）、只篡改MD许可。**全部由真实断言触发 exit 1**，非手写退出码、非仅字符串宣称变红。
- 原件结构通过但事实失败，说明只核键值非空不够。事实检查器使用本轮人工浏览的一手来源记录作 oracle；它自身不联网，不能把固定预期值当成“自动核实论文”。

临时路径：`/Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-R1/r1-codex-20261016/tmp`，未创建外部临时库。全部输入、日志与不利副本保留；未下载代码、权重、数据集；只读访问研究网页、README和许可网页。真实模型预算预留=0，实际模型工作=0，优化更新=0；没有接触 RunStore 或检查点。

## 身份与边界

`input_sha256.json` 保存原件4个输入的SHA，脚本末尾重算全部不变并断言。被验身份与 R1 原SHA清单逐项一致：

| 文件 | SHA256 |
|---|---|
| docs/research/ADAPTER_REGISTRY.md | 21274990656574142a79126eda2032eb9f6de11cee2d2aeb56f2aa827ac12656 |
| docs/research/adapter_registry.json | 3a3f9929cad81e7b84bda544641ce84986b05e3a7c5ecb7ef61c7ef5eb0c0299 |
| reports/V9-R1/validate_registry.py | 2b95ed15b6fdc1030c65aa6f3df0ae73f55a8c79093d5e6759a05b3d090dd602 |
| reports/V9-R1/SHA256SUMS.txt | e894dd805197f633f3bfdde70a04cf9ed1665b201c6e89653a232aacddc4d4c6 |

本轮报告与脚本SHA见 `SHA256SUMS.txt`；该清单不自哈希。网页事实保存为带URL的人工核对记录，不保存整站HTML，不声称已冻结远端仓库commit或网页字节。未验证仓库安装、复现、全部子文件许可、模型权重/数据集许可、macOS运行、MLX移植、AWZ/C0收益。

失败访问也保留：OpenReview forum/PDF/attachment均跳challenge，API网页工具内部失败，urllib因本机证书链失败，curl API返回403；没有绕过TLS或challenge。Slot Attention目录页一次失败，显式官方README页成功。详见 `source_review.json.network_failures_preserved`，访问失败不被当成“来源不存在”。

交回方式：Relay report（不 accept、不自动续领）。建议一级把必修项回传 R1 作者，保留本次负报告，修订时新建证据版本；本报告自身属于独立复核完成，R1整体建议未通过。
