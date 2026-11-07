# W3 r3（P168）：一级 claude 收尾（2026-11-07 19:xx–21:xx）

- **作者：** gemini-7k2q（r1）、gemini-8f4b（r2）、一级 claude（r3）
- **复核：** P170 须由 gemini-b7x4 承担，排除 7k2q、8f4b、claude
- **过程：** 「S2 W3 r3」新会话被拉起后，确认未作任何改动即结束。

## r3 改动（在 0a28618 之后，另见 `reports/V9-S2-W3/r3-tier1/NOTES.md`）

### 1. 门槛阈值收入 spec 与预登记
- `spec` 追加 `ACTION_SENSITIVITY_FLOOR = 0.05`、`SUBGOAL_DROP_FLOOR = 0.10`、`MAX_DEV_EVALS = 2`。这三个值原先只以字面量写在 eval_runner 里，没有进预登记。
- eval_runner：模块常量改为 spec 的别名；基线区间的默认值取 spec；dev 次数上限在调用时读 spec。
- commands 在训练后门调用处显式传入三个阈值。
- prereg 的 gates 段加入这三项，并在 `validate` 中逐项比对。

### 2. 端到端测试假臂重写，不再读取任何真值
- 删除 `inspect.currentframe` 读取调用栈的做法、`pose_dists`、`compute_pose_distances_to_goal`。
- 改为按臂名设种子的固定随机投影：
  - `encode` 为 tanh(P·x)；
  - `predict_l1` 为 z + sensitivity·W[a]·dt；
  - `encode_l2` 取 z1 的前缀；合谋的 C 臂输出常数，使下层用不到子目标；
  - `predict_l2` 为 z2 + u·U。
- 好路径测试只放宽按成功率判的两道门（基线区间、子目标降幅），因为随机假臂到达不了目标。两条拦截测试保留登记阈值，并由生产变异证明这两道门确实接通。

### 3. smoke 的 MLX 边界
- 把唯一用到 MLX 的 SIGReg 对齐检查抽成 `smoke.mlx_sigreg_alignment`，在函数内部才导入 MLX，生产行为不变。
- 端到端测试只替换这个边界函数和 `adapters_mlx.make_mlx_arm`，默认套件因此不再导入 MLX。修改前，几何模块的两条「只用 CPU」检查会因此失败；修改后两条都通过。

### 4. 提速
- smoke 之后把 N_FWD 降到 256（smoke 的 oracle 熔断需要 1024）。
- dev 的 N_FWD 档位改为单档 (256,)；dev 和 final 每世界 1 对起终点。
- smoke 缩为 2 个世界、每世界 2 个回合、4 条长目标规格。
- dev 只真跑 1 次，次数上限改为在账本中写入计数来模拟，该上限另有单测覆盖。
- 删除三条冗余的命令行接线测试：好路径流水线已经通过 `cli.main` 依次跑完 smoke、generate-data、train、plan-select、dev-eval，且只替换 MLX 边界，满足 Y7。

### 5. 补用例
- 冻结配置缺少规划选择时拒绝；
- C 臂对照缺少 C 的规划选择时拒绝。

## 验证
- **端到端测试 3 条：** 合计 57.5 s（pipeline 31.4 s，两条拦截测试各 12.7 s）。
- **生产变异（隔离副本）：**

  | 变异 | 结果 |
  |---|---|
  | M1 关闭合谋判定 | 变红 |
  | M2 关闭敏感性判定 | 变红 |
  | M3 恢复默认配置回退 | 第一轮存活；补用例后 1 failed，变红 |
  | M4 恢复 C 臂默认选择 | 1 failed，变红 |

  脚本与结果见 `w3mut*.py`、`mutations_*.json`。
- **默认全量（不跳过任何文件，前台 SIG_DFL+execv）：** 3721 passed, 7 deselected, 0 failed。用时 1032 s，比此前同类全量（547–640 s）长，可能与当时机器负载有关，请复核者在空载时复测。
- **实盘：** artifacts 前后 lstat 比对（mtime、ctime、size、ino）差异为 0。
