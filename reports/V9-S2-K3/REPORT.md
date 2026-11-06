# ainerzero.V9.P112 执行报告
角色：executor；负责人：composer-m7k2；时间：2026-11-06
任务状态：reported；实验状态：completed（纯 CPU，无训练）
任务依据：V9-S2-DESIGN/DESIGN-r0.md §4/§7；参数 v1；用户 11-06「走 S2」方向，训练预算未批
修改文件：`s2/__init__.py`（空壳，P111 未交）、`fwd_counter.py`、`planner.py`、`test_s2_planner.py`、`reports/V9-S2-K3/`
实际执行：NumPy 参考规划器 + 隔离变异；pytest SIG_DFL 前台；无 MLX / 无下载 / 无提交

## 计数单位
对任意网络函数一次单元素求值 = 1；批大小 B 计 B。编码器（含目标编码）计入。硬预算 `N_fwd` 超出立刻 `ForwardBudgetExceeded`，不静默截断。决策输出 `snapshot()` 分项。

## 玩具世界
带墙直线走廊（y=2，x=1..60）+ 解析点质量；动作离散 {N,S,W,E}；`encode` 恒等；`predict_l1`/`predict_l2` 为已知动力学（宏动作 oracle 重复 s₂ 微步）。

## 测试清单（8）
闭式计数+编码器分项；预算−1 抛错；防作弊嵌套 predict；flat 近目标成功率≥0.8；显式 rng 可复现；下层代价经 E₂（含 encode_l2 调用数）；分层远目标（≥40 步）同 `N_fwd` 下成功率>flat；无 MLX import。

## 变异表（隔离副本，字节还原+SHA）
| ID | 手段 | 结果 |
|---|---|---|
| K3-M1 | 不计 encode | RED |
| K3-M2 | 超预算静默截断 | RED |
| K3-M3 | 下层绕过 E₂ | RED |
| K3-M4 | 全局 `np.random` | RED |
全部 caught；见 `mutations.json`。

## 默认全量计数
- S2 套件：8 passed
- 默认全量（SIG_DFL 前台）：**3455 passed, 6 deselected**（259.63s）；本会话未另存改前快照（约 +8 本卡用例）
- `s2/__init__.py`：P111 未到，本卡建空文件（无 MLX），留给 K1/P111 合并

## 交回统筹
分层>flat 仅为 oracle 玩具健全性，非科学结论。参数 v1 未改。训练/数据/final 仍待批。
产物：`metrics.json`、`sha256.json`、`mutations.json`、`run_mutations.py`、`pytest-*.txt`
