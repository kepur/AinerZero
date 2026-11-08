# S2 集成 W11：世界重抽上限 30，生成器只认 spec 一处定义（一级 claude，2026-11-08）

## 依据
- **用户批准：** 11-08「批准改为 30」（RESEARCH_LOG `R20261108-S2-redraw-30`）。
- **起因：** 登记运行 P188 在 train 第 11 个世界失败；全量模拟表明冻结的上限 5 次在登记规模下不可行（`R20261108-S2-data-r2-failed`，`reports/V9-S2-DATA-r2/worldscan/`）。

## 改动
1. **`spec.py`：** 末尾追加 `MAX_REDRAW_RETRIES = 30`，原有的 `= 5` 那一行不动，遵守「只追加」的规则；`MAX_REJECTION_RATE` 仍为 0.30。
2. **`world.py`：**
   - `import spec`；
   - `WORLD_REJECTION_RATE_THRESHOLD`、`WORLD_REDRAW_MAX` 改为 spec 的别名；
   - `prepare_world_with_long_pairs(max_world_redraws=None, rejection_threshold=None)` 与 `world_rejection_requires_redraw(threshold=None)` 在调用时读取 spec；
   - `max_world_redraws < 1` 时报错。
   - **修正的缺陷：** 原来 prereg 记录的是 `spec.MAX_REDRAW_RETRIES`，生成器读的却是 world.py 里另一份常量，而且这份常量在函数定义时就绑定成了默认值。
3. **新增默认用例 `tests/v9/experiments/test_s2_world_redraw.py`，共 8 条，CPU 运行约 8 s：**
   - spec 的取值，以及别名与 spec 一致；
   - prereg 草稿记录的就是生成器用的值；
   - 登记种子里最难的世界用默认值都能通过，且重抽次数与扫描结果完全一致：train 11 需 8 次（即 P188 失败的那个世界），train 173 需 20 次，dev 14 需 17 次；
   - 调用时读取 spec：上限改回 5 时 train 11 报错，门槛改大时判定随之改变；
   - 上限小于 1 时报错。

## 证据
- **新用例与相关用例：** world、spec、prereg 共 58 条，全部通过。
- **坏对照：** 在隔离副本中运行（`mutations.txt`），5 处全部变红，还原后 8 条通过。

  | # | 变异 | 结果 |
  |---|---|---|
  | M1 | 上限写死为 5 | 3 条失败 |
  | M2 | 去掉 spec 的覆盖值 | 5 条失败 |
  | M3 | 判定函数的门槛写死 | 1 条失败 |
  | M4 | 生成器门槛放宽到 0.5 | 4 条失败 |
  | M5 | 去掉上限检查 | 1 条失败 |

- **默认全量：** SIG_DFL+execv，不跳过任何文件；3733 passed，7 deselected，0 failed，用时 1101 s；实盘 artifacts 的 lstat 前后差异为 0（`pytest_full_tail.txt`）。

## 对冻结和运行的影响
- 改动后要冻结 r3。prereg 里 `world.max_redraw_retries` 变为 30，world.py 和 spec.py 的源码摘要也随之变化。
- **smoke：** r2 的登记 smoke（P187）的 4 个世界都在 5 次以内通过，上限无论 5 还是 30，接受的布局都一样，所以 smoke 的结果不受影响，r3 下继续沿用，不重跑。train 模式取的是账本里最近一次通过的 smoke。
- **数据：** P188 在 `datasets/train` 留下了 0–10 号世界的部分文件，重跑前改名归档，不删除。
- **预算：** train 数据的准备时间约多 460 s（全量扫描实测），仍在每格 3600 s 之内。
