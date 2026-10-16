# ainerzero.V9.G1 S0数学核心交付

- 执行者`codex-exec-r2-20261016`，真实Codex子代理，同R2身份；只report不accept不next。
- 交付：SE2/SE3五运算、点/向量作用、左右切空间高斯/Adjoint协方差、已知body运动与局部不变EKF更新、重力SE2×高度、锚定Gauss-Newton图。
- 实现前固定CPU登记：`reports/V9-G1/r1-codex-20261016/cpu_registration.json`，SHA256=`5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6`。
- 49项CPU性质通过；12种真实运算/守卫变异全部AssertionError/exit1；Ruff通过。
- 主值/近pi、左右误差、协方差、gauge与未观测自由度均明示；不实现G3 operator、不声称RGB warp或估计误差是唯一误差源。
- 两路24步已知运动学条件参考：固定旋转平移滤波最大误差0.0096113<=界0.0096246；图L2由0.252389降为0.0100955<=界0.1406544。
- 完整SE2-EKF误套平移界有真实失败，step9误差0.013251>0.013069，原脚本/日志/登记保留。修复为显式“已知固定旋转”条件Gaussian参考，未改界/噪声/种子，不声称一般EKF全路径界验收。
- GridLab来自现有apply；AWZ来自现有Trajectory2D解析小房间路径，未启动渲染/真实传感/模型；不是感知或3D能力成绩。
- 模型预算/训练/推理/更新0；无下载/安装/RunStore写入/提交推送/删除。
- 详细报告`reports/V9-G1/r1-codex-20261016/report.md`；API边界`src/ainerzero/v9/geometry/README.md`。
- 结果`reference-results-r1.json`；失败`reference-first-failure.log`与`run_reference-failed-r1.py`。
- CPU测试XML、变异日志/argv、登记与源码SHA均在同报告目录，交G2独立复核。
