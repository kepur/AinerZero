# W3（P168）一级 claude 接手说明（2026-11-07 18:xx）

## 一级已改的生产代码（须由 P170 非作者复核覆盖）
1. **`eval_runner.py`：模块常量改为 spec 的别名**
   - `FLAT_H_CANDIDATES`、`HIER_*`、`N_FWD_DEFAULT`、`N_FWD_CURVE` 改为引用 spec；`_candidate_grid` 改为调用时读 `spec_mod`；final 与其余两处内联的 n_fwd 改为读 `spec_mod.N_FWD`。
   - 原来是字面量副本，测试对 spec 的 monkeypatch 传不进来，端到端测试因此始终按 N_FWD=4096 运行。
2. **`eval_runner.py`：删除 7 处默认规划配置回退**
   - 原来冻结配置缺少某臂时，会回退到 `{"H":32}` 或 `{"macro_horizon":6,...}`。新增 `_require_plan_choice`，缺失即抛 ValueError。
   - 由此暴露一个真 bug：训练后门中 C 臂模型的键是 `arm_c/42`，而 plan_config 按 `arm_c` 记录，所以 C 臂对照一直在静默使用默认配置。现已按去掉种子后缀的臂名查找。
3. **`commands.py`：评测调用时从 spec 显式传参**
   - 调用 plan-select、训练后门、dev 时显式传入 `n_fwd`、`max_episodes`、`n_fwd_curve`、`n_boot`；kwargs 可以覆盖。
4. **测试 `test_s2_eval_runner.py`**：3 条用例补上 C 臂的 plan_choice，1 条补全 dev 的冻结配置。评测与接线测试共 41 条通过。

## 剩余工作（交给执行者）：重写端到端测试的假臂
- **问题：** `ProductionFakeArm.encode` 沿调用栈读取 `run_episode` 局部变量中的 layout、state、goal_state，用真实状态做反向 BFS 来规划，根本不用子目标。按真实选出的配置运行时，C 臂打乱对照的降幅为 0，被判为合谋。
- **要求：**
  - 删除所有 `inspect.currentframe` 一类读调用栈的做法。
  - 好的假臂只能从观察解码位姿：测试侧从 `datasets/*/world_*/layout.json` 读取布局，构建「观察 → (世界, 位姿)」查表，可参照 `test_s2_learned_planning.py` 中的 `ObsPoseTable`、`GeoPoseArm`、`HierPoseArm`。
  - C 臂必须真正依赖子目标：例如 encode_l2 返回位置，predict_l2 按宏动作位移，下层朝子目标规划。这样打乱子目标后成功率会明显下降。
  - 坏臂（不可规划、合谋）按原意保留。
- **规模**（已写在文件里，可沿用）：
  - N_FWD=1024；N_FWD_DEV_LEVELS=(768,1024,1536)；
  - 候选网格各 1 个；HYPERPARAM_SELECTION_MAX_EPISODES=4；REGULAR_DT_SUBSET_EPISODES=1。
  - 只有 N_FWD 降到 1024，smoke 的 oracle 熔断才能通过（256 时种群为 3，oracle 的成功率为 0）。
- **验收线：**
  - 3 条端到端测试共计 ≤ 60 s，报告写明实测耗时；
  - 默认套件不导入 MLX；
  - 交回前在实盘前台跑一次不跳过任何文件的默认全量，必须 0 failed。
