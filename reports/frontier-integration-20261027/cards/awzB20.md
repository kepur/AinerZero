【L3·强代理】【代码·Blender·CPU】E0 真值修复：精确接触判定、速度来源与误差界、静态面隐藏参数入档（B11 后续，小样）

依据：AinerZero/reports/frontier-integration-20261027/REPORT.md 与 reports/frontier-integration-20261027/DESIGN_CORE.md（一级 claude，2026-10-28）；用户 2026-10-28 指令「落地并入工作台」。
主责统筹：claude（CMFL 研究线）。S1、T6 等既有线的主责不变。
本卡不授权：训练、MLX 运行、下载、安装第三方包、付费、云 GPU、修改冻结参数或门槛。复跑不得改写已交付证据（COORDINATION 规则 8）。
背景（一级已对照源码复核）：
- 接触用包围球启发式（blender_worker.py:306-310，半径取最大尺寸的一半，阈值 rad_a+rad_b+0.04）。地面 30×30×1 取半径 15，活动物体几乎每帧都被判为与地面接触，碰撞 F1 真值不可用；
- 速度是 60 fps 逐帧后向差分（:255，未取整位姿，输出取 6 位小数），不是求解器速度，滞后半帧；
- 静态地面和斜坡的摩擦、弹性随机化了（scenarios.py:62-63、88-89）却没写进 hidden_parameters，E1 的 ④ 真参数上界无法从数据还原。
B11 r2 已验收，本卡是后续修复。要求：
1. 接触：改为按实际碰撞形状的精确最近距离判定（地面、斜坡按平面或盒体，盒、球按解析式或 mathutils.bvhtree），登记容差（含 Bullet collision margin），只在容差内记接触。Blender Python 拿不到 Bullet 原生接触点就如实写明。
2. 速度：给出速度来源字段与登记误差界，可用子步分辨率差分或中心差分；取整只在导出时做。
3. 静态面的摩擦、弹性写入 hidden_parameters（hidden_params_side 仍为 world）。
4. 解析测试：自由落体球在空中时接触为 false，首次碰撞在解析时刻 ±1 帧内为 true；静置盒持续接触；空中速度与 v=g·t 的偏差在登记界内。
5. 按 B11 r2 同样规模（≤18 段）重新生成小样到新目录 reports/V9-B20/r1/，同种子跑两次逐字节一致；确定性域按 EVENT_PROTOCOL.md:183-191 登记，Blender 版本写实际的 5.2.2。不批量、不渲染。
6. 60 fps 对 120 Hz、“3 个随机种子”实现成每分区一个，这两项只记入已知问题，本卡不改。
权威模块：采样必须继续只读调用 e0/hidden_params.py 的 DEFAULT_RANGES，划分与种子继续用 e0/dataset.py，不得另写一套。B11 r1/r2 证据不得覆盖；e0/ 目前未入 git，开工前记录改动前各文件 SHA。
领卡前置：接交流电（ADR-0009 用电池时不跑重任务）；本机 /Applications/Blender.app 可运行。

验收：awz.V9.B21 非作者对抗复核建议通过；含拆守卫坏控证据。
