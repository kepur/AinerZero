# P253 r2：沙盒改为揭示时才模拟，并按复核补测试

**执行者：一级 claude。** 第一版的交付在上一级目录 `../REPORT.md`，以下称 r1，保留原样。这一版处理两份复核：

- **P253 非作者复核**（`../../sandbox-module-review/REPORT.md`）：结论是打回小修。代码本身没有缺陷，测试缺 4 处，交付文件也过期了。
- **DESIGN-r1 非作者复核**（`../../r1-review-sub/REPORT.md`）的必修 2、3：
  - 候选池里一半是重复状态；
  - 「偷读封存标签」的负对照写不出来，因为没有机制能抓到。

**本交付尚未经非作者复核。复核卡是 P256，同时派了独立子代理。**

## 设计变更：标签在揭示时才生成

r1 的做法：`CandidatePool` 把 `make_pool` 算好的全部标签封存在 `_sealed_labels` 里，由 `reveal` 取出。复核指出两个问题：

- 同一个进程里的普通属性，谁都能直接读，不留任何痕迹；
- 用 deepcopy 或 pickle 复制池子，标签会一起带走。

r2 的做法：
- `CandidatePool(states_by_n, labeller=sim_labels, pool_type=...)` 只存状态，状态内部用 float64 保存。
- `reveal(ids)` 依次：
  1. 先查重；
  2. 调用 `_simulate`，在其中调用模拟器；
  3. 模拟成功后才登记，并写日志；
  4. 只返回本次揭示的样本。
- 未选中样本的结果从未计算过，进程里不存在，所以没有东西可偷读。
- `sim_labels` 与 `learned_mlx.make_pool` 用同一套标注算法：
  - 第 1 步按样本单独走，并记录接触；
  - 再走到第 10 步；
  - 取第 1、5、10 步的结果，转成 float32。
- native 测试用脚本化的随机数驱动 `make_pool`，让它抽到同样的状态，两边标签逐位相同。
- 候选去重由 `cells.candidate_source` 负责：按 (世界, 步) 不放回抽样，构造时断言没有重复。

## 复核意见的处理

| P253 复核 | r2 |
|---|---|
| 必修 1：dunder 绕过 `reveal`（N1） | `test_class_members_are_the_documented_ones` 断言类上的 dunder 只有 `__init__`、`__len__`。`test_only_reveal_reaches_the_labeller` 用 AST 断言：只有 `reveal` 引用 `_simulate`；只有 `__init__`、`_simulate` 引用 `_labeller`。变异 S6（加 `__getitem__` 调 `_simulate`）被杀死 |
| 必修 2：同分测试分辨不出原型（N3） | 新测试 `test_pick_top_ties_at_scale`：200 个编号、三档分数，并断言原型的 argsort 结果不同。变异 S4（改回 argsort）被杀死 |
| 必修 3：交付文件过期 | 本目录重出；`SHA256SUMS.txt` 统一以本目录为基准 |
| 应修 4：第二次 `reveal` 的返回值（N2） | `test_reveal_returns_exactly_this_calls_samples_with_their_labels` 检查第二次只返回本次的样本。变异 S8 被杀死 |
| 应修 5：`states()` 返回视图（N5） | 断言 `owndata`，再把返回数组改回可写并写入，断言池内不变。变异 S7 被杀死 |
| 应修 7：`reveal([])`、负编号 | `reveal([])` 报错。`_canon` 查负编号；`pick_top`、`pick_geo` 还按分数或标志数组的长度查上界。变异 S9 被杀死 |
| 卡外 8：候选池一半重复 | `cells.candidate_source` 改为不放回抽取并去重 |
| 卡外 9：deepcopy、pickle 带走标签，可用公开状态重算标签 | 未揭示的标签不存在，deepcopy、pickle 带不走。重算靠 `W.physics`，挑选期由 `cells.sealed()` 封住，见 native 测试 |

## 测试

- 纯 NumPy（`numpy-tests.log`）：`test_s6_sandbox.py` 24 项，`test_s6_cells_static.py` 4 项。

  ```
  ............................                                             [100%]
28 passed in 1.99s
  ```
- native：经锁运行，与 `test_s6_cells_native.py`、`test_s6_epinet_mlx.py`、`test_s6p1_runner_native.py` 一起跑，共 33 项全部通过（`native-tests.log`，2026-11-15 重启后重跑）。其中 `test_s6_sandbox_native.py` 5 项：

  ```
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s6_sandbox_native.py tests/v9/experiments/test_s6_cells_native.py tests/v9/experiments/test_s6_epinet_mlx.py tests/v9/experiments/test_s6p1_runner_native.py
  lock held by 3616
.................................                                        [100%]
33 passed in 75.92s (0:01:15)
  ```

## 变异

脚本 `reports/V9-S6-PHASE1/impl-evidence/mutate_pure.sh`，原始输出在 `mutate_pure.log`。其中沙盒的 12 个变异：

```
== baseline: 57 passed in 1.92s
== S1 states() simulates every candidate: 2 failed, 55 passed in 1.96s
== S2 reveal registers before simulating: 1 failed, 56 passed in 1.98s
== S3 pick_top ties by id descending: 2 failed, 55 passed in 2.03s
== S4 pick_top uses the prototype argsort: 1 failed, 56 passed in 2.20s
== S5 reveal does not check repeats: 1 failed, 56 passed in 2.02s
== S6 a dunder hands out any outcome: 2 failed, 55 passed in 2.02s
== S7 states() returns read-only views of the internal arrays: 1 failed, 56 passed in 1.99s
== S8 reveal returns every revealed sample so far: 1 failed, 56 passed in 1.96s
== S9 picks accept negative ids: 3 failed, 54 passed in 2.02s
== S10 geo_flags drops the overlapping-and-approaching clause: 1 failed, 56 passed in 2.08s
== S11 sim_labels sets only one side of a contact: 1 failed, 56 passed in 2.02s
== S12 sim_labels rolls one step too many: 1 failed, 56 passed in 1.97s
== restored: 57 passed in 2.04s
```

- S11（接触矩阵只写一侧）第一轮存活。原因是测试抽到的 3 个状态里恰好没有盘间接触。
- 已把测试改成显式挑有接触的状态，复跑后被杀死。上面是复跑后的输出。
