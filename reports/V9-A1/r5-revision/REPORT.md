# ainerzero.V9.A5 r2 报告：ARCHITECTURE_V9 r5（回应 ainerzero.V9.A6 非作者审议）

- 作者：Claude（一级），2026-10-16。只修设计，未改任何科学门、参数、训练代码或预算；没有训练、下载、运行。
- r4 原件归档：`reports/V9-A1/r5-revision/r4-archive/ARCHITECTURE_V9.r4.md`（e69a0e1c…，与审议输入一致）；r4 与审议证据保留。

## 交付
- `ARCHITECTURE_V9.md` r5，sha256 `ea786389bcbab33686544c7fb20b2f54ac2a6a7f56bea60bad8eb3e6b19c634d`。§11 逐项关闭：
  - F1：持久世界权威归 AinerHub，AWZ 管运行与求值；新增三系统与三平面职责视图；
  - F2：`UpdateScheduler` 只用于学习侧；式 12b；§8.6 信息边界；
  - F3：引用 TEACHERS_AND_CACHE r2；
  - F4：式 12a 的活跃集合、宽相、传递闭包与确定性域；D-019 总门；
  - C1：引用 G1 约定；
  - 电源口径、Serafina、命名空间、外部能力边界。
- 配套修订：
  - Event/v1 r1：awz.V9.A8 已重交，§4 世界侧与学习侧分开，§4.1–§4.3 补全；
  - TEACHERS_AND_CACHE r2：ainerzero.V9.T1 已重交，复核卡 T17；
  - D-019 代码放行总门 awz.V9.A10：已加为 21 张暂停或新建代码卡的前置。

## 未解决（不在本卡）
- 落地方案中“19 与 12 不是同一个基线”“E3 原稿已有 CAS 设计、尚未实现验收”的收口：由 awz.V9.A5 r2 处理。
- 学生能否用 AWZ 观察训练：需登记 ADR-0005 修订并由用户决定。

## 复核
- 本卡不自验收，由新建的非修订作者复核卡复核：逐项核 §11 关闭表、r4 归档 SHA，并确认没有科学参数、门槛或预算变化。
