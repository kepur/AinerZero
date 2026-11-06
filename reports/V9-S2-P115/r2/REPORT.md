# ainerzero.V9.P115 r2：GridLab-S2 世界与分区入口（打回修订）

- **执行**：`composer-a7k2`；状态 completed；依据 `DESIGN-r2.md` §2 / r2.1；r1 产物保留于上级目录。
- **相对 r1**：删除 long 距离回退；距离改为位姿图动作 BFS；成对抽 (start,goal)；世界拒绝率>30% 或凑不齐 6 对长目标则重抽（≤5）；非 BFS 段≥50%；dev/final 规格带 perturb；`is_success`/`strict`；k 卡方门；变异 9 处。
- **参数对照**：25×25 / 9 房 / 门 1–2 / 柱 0–3 / 7×7 / 4 动作 / k={1:0.5,2:0.3,3:0.2} / 240 步 / long≥40 动作步 / short≤10 / 无坐标 —— 与代码一致。
- **测试 16/16**：确定性、连通、视线、无坐标、k 等价、目标歧义、多起点无回退、成功判定、世界重抽门、非 BFS≥0.5、k 卡方、分区、纯 CPU×2。
- **变异 9/9 全红**：M1 坐标 / M2 连通 / M3 视线 / M4 歧义 / M5 共享 ns / M6 恢复回退 / M7 k≡3 / M8 非BFS=0 / M9 去世界重抽。
- **小样**（tmp，1.02s）：步数全 240；long 位姿 BFS min40/max43/mean41.7；拒绝率≈0.14；UNSEEN 34.98%；非BFS 58.9%；12 规格中 4 个 perturb。
- **隔离全量**：`tests/v9/experiments/` 415 passed / 4 failed（s1 注册缺产物，非本卡范围）/ 2 skipped。
- **未改**：`s2/__init__.py`、gridlab_v1、conftest、P111/P112 文件；无 MLX / 无训练 / 无提交。
