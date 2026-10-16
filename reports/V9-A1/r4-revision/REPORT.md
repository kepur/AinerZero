# ainerzero.V9.A5 报告：ARCHITECTURE_V9 r4（Codex r3 审议强制修订 + v10 工程验证层）

- 作者：Claude（一级），2026-10-16。只修设计，没有改任何科学门、参数、训练代码或预算，没有训练、下载或运行。
- 用户相关决定：AWZ D-019，原话「先不要动代码 先改写架构  架构方案和任务落地 再开始实现代码任务」。19 张写代码的实现卡已暂停。

## 先归档
- `reports/V9-A1/r4-revision/r3-archive/`：
  - `ARCHITECTURE_V9.r3.md`（ebaf1c4b…）；
  - `V9_RESEARCH_SURVEY.r3.md`（51f6a984…）。
- 两者与 Codex 审议登记的输入 SHA（`reports/V9-A1/codex-r3-review-20261016/input-sha256.json`）一致。

## 交付
| 文件 | sha256 | 说明 |
|---|---|---|
| ARCHITECTURE_V9.md（r4） | e69a0e1ce7cb92187961de387fc84d4fb390aab84ed2e4682601f39566521dda | §9 逐项关闭 Codex 意见；§8 v10 工程验证层；§10 v10 吸收与改正 |
| docs/research/V9_RESEARCH_SURVEY.md | 1dc744ea4a59403423063faff7d4fc422bcf02bb541fed2bc3f2763ab2daf636 | 末尾追加 §9 r4 勘误（THICK 官方代码、V-JEPA 2.1 论文版本、引用口径），原文不改 |
| docs/research/AinerZero_v10_Architecture_Validation.source.md | 79b6547cc27cf8900553fd738144768435e086b382532e4c00241cf62b9d3c0f | 用户 v10 原件存档 |

## 关闭情况
- Codex 逐节意见 12 项，全部在 r4 有对应处理，见 ARCHITECTURE_V9 §9。
- 未解决项（需要别处决定，不在本卡）：
  1. “Serafina” 是否就是 AinerRelay：待用户确认；确认前不新建调度器。
  2. AWZ 实时出口观察能否进入训练（ADR-0005 修订）：待用户决定。
  3. 新契约 Event/v1、WorldSnapshot v1.2（几何引用、碰撞体、关系）：只在 §8.2 立项，契约本身由 AWZ 新卡设计。
  4. 七个接口（新增 `UpdateScheduler`）意味着 ainerzero.V9.B2 要改写卡面；B2 现处暂停，任务落地时改写。

## 约束核对
- 科学门、训练预算、冻结参数：未改。
- G1 已登记的 CPU 容差与 fixture：未改，§5 S0 行写明。
- 训练暂停：不变。v10 中需要训练、下载、渲染、批量生成的实验全部标为“需批准”。

## 复核
- 本卡不自验收。由 ainerzero.V9.A6 的非修订作者复核：逐项核关闭表、归档 SHA，并确认没有科学参数、门槛或预算变化。
