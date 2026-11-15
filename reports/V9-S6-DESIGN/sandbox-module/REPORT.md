# P253 S6 沙盒候选池与挑选函数：交付

**执行者：一级 claude 接手。** 卡片放出 3 小时无人领取，期间没有二级 agent 在线（`pgrep -fl "cli.py next"` 为空），按用户 11-14 睡前指示由一级接手实现。**本交付尚未经非作者复核，不能当作已验收。**

对应设计稿 `reports/V9-S6-DESIGN/DESIGN-r0.md` §2–§3。

## 改了哪些文件

| 文件 | 说明 |
|---|---|
| `src/ainerzero/v9/experiments/s6/sandbox.py`（新） | `CandidatePool`、`pick_random`、`pick_top`、`pick_geo`、`geo_flags`；纯 NumPy，只导入 `numpy` 和 `s4.world`（纯 NumPy，取 `RADIUS`、`DT`） |
| `tests/v9/experiments/test_s6_sandbox.py`（新） | 纯 NumPy，19 项 |
| `tests/v9/experiments/test_s6_sandbox_native.py`（新） | 导入 MLX，4 项：对照真 `make_pool` 与 `gated.geo_gate` |
| `tests/conftest.py` | `NATIVE_MODULES` 加 1 行 |
| `tests/v9/experiments/test_s6_epinet_mlx.py` | 加 1 行 `pytestmark = pytest.mark.native_mlx`（P252 漏了；一级在本卡顺手补） |
| `tests/v9/experiments/test_s5_final_native.py` | 加 1 行模块级 `pytest.importorskip("mlx.core")`（P245 遗留：只在子进程里导入 MLX，登记清单检查判它「登记了却是 CPU」） |

没有改 `s6/__init__.py`、`s4/` 下任何文件，没有写 `artifacts/`（锁文件由 `hold_lock` 管）。

**卡外的两行修补：** 跑仓库自带的登记清单检查 `tests/test_cpu_collection.py` 时，HEAD 上已有 2 项失败：
- `test_native_modules_carry_native_mark`：`test_s6_epinet_mlx.py` 缺 `pytestmark`；
- `test_native_module_inventory_is_complete`：`test_s5_final_native.py` 登记了，但收集时不导入 MLX。

本卡的新 native 测试一开始也缺 `pytestmark`。三处都补上后，这项检查 3/3 通过（`cpu-collection.log`）。这两处测试基础设施的修补超出卡片的「只新建」范围，由一级决定并在此写明。

## 接口要点

- **`CandidatePool(pool)`**
  - 构造：输入 `make_pool` 的结果。状态 `p v pil` 存进 `_states`，其余字段（标签）存进 `_sealed_labels`，两者都是拷贝。
  - 全局编号：按 (盘数升序, 下标) 扁平化，与原型 `explore_s6a.flat_pool` 同序。
  - `states()`：每个盘数一组 `{id, p, v, pil}` 只读拷贝，不含标签。
  - `remaining()`：未揭示编号，升序。
  - `revealed_ids()`：已揭示编号，按揭示顺序。
  - `log()`：每次揭示一条 `{"call", "ids"}`，返回拷贝。
  - `reveal(ids)`：唯一读标签的公开入口。
    - 返回与输入同类型的池（真运行时即 `learned_mlx.Pool`，不导入 MLX）。
    - 按盘数分组，组内保持给定顺序，与原型 `explore_s6a.subset` 一致。
    - 跨次或同次重复都报错；越界报 `IndexError`。
    - 先全部检查再登记，失败时不留半截状态。
  - `revealed_pool()`：迄今揭示的全部样本，即训练池；没揭示过时不碰标签。
- **挑选函数**
  - 共同点：只吃分数、标志或状态，不吃标签。`remaining` 先 `np.unique` 规范化，所以调用方给的顺序不影响结果；重复编号报错；`k` 越界报错。
  - `pick_random`：`rng.choice(升序 remaining, k, replace=False)`。与原型第 0 轮 `rng.choice(len(allp), per, replace=False)` 逐位一致（有测试）。
  - `pick_top`：`np.lexsort((rem, -score[rem]))`，分数降序、同分按编号升序。剩余样本里有非有限分数就报错。
  - `pick_geo`：先从被标记的里随机取，不够时从 `setdiff1d(rem, take)` 随机补。随机数流与原型 `explore_s6f` 逐位一致（有测试）。
- **`geo_flags(states)`**
  - 与 `gated.geo_gate` 同一算式，按 float64 计算，按样本取 any。
  - 编号覆盖不全时报错；只少最后一组时数组变短，`pick_geo` 下标越界报错，不会静默。

## 测试原始输出

纯 NumPy（`numpy-tests.log`）：

```
...................                                                      [100%]
19 passed in 1.50s
```

Native，经锁（`native-tests.log`；同时回归 P252 的 epinet 测试）：

```
............                                                             [100%]
12 passed in 1.98s
```

命令：

```
.venv/bin/python -m pytest -q tests/v9/experiments/test_s6_sandbox.py
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q --native-mlx tests/v9/experiments/test_s6_sandbox_native.py tests/v9/experiments/test_s6_epinet_mlx.py
```

## 测什么

- **`states()` 字段**：只有 `{id, p, v, pil}`，与源数组一致，只读；编号顺序同 `flat_pool`。
- **拷贝而非视图**：改源池后，`states()` 与 `reveal()` 都不受影响。
- **公开接口拿不到标签**：把 `_sealed_labels` 换成一读就抛 `AssertionError` 的替身后：
  - 全流程都不触发：`states`、`geo_flags`、三个挑选函数、`remaining`、`revealed_ids`、`log`、`revealed_pool`，以及 `dir()` 里所有可无参调用的公开成员；
  - 只有 `reveal` 触发（正对照）。
- **公开成员白名单**：正好是 `{states, remaining, revealed_ids, log, reveal, revealed_pool}`。
- **AST 检查**：只有 `__init__` 和 `_take` 引用 `_sealed_labels`。
- **`reveal` 返回值**：与源池对应行逐位一致，类型保持；在真 `make_pool` 上与原型 `subset` 逐字段逐位一致（native）。
- **重复揭示**：跨次或同次重复、越界都报错，且失败调用不留下部分揭示。
- **日志与池**：`log`、`remaining`、`revealed_pool` 顺序正确，`log()` 返回拷贝。
- **三个挑选函数**：确定性、个数、不重复、只从 `remaining` 挑、与调用顺序无关、`k` 越界报错、重复编号报错。
- **`pick_top`**：同分按编号升序；非有限分数只在 `remaining` 内才报错。
- **`pick_geo`**：先取标记、再补未标记；全标记、零标记两种情形；与原型随机数流一致。
- **`geo_flags` 手算情形**：
  - 一步内相接；
  - 背离；
  - 太远；
  - 重叠且相向；
  - 重叠且背离；
  - 静止；
  - 平行同速；
  - 恰好相切且切向滑过（b = c = 0，不标记）。
- **`geo_flags` 与 `gated.geo_gate`**：在 1500 个真实样本上逐样本一致，且两种结果都出现，检查有效；边界样本上也一致（native）。
- **标签含义**：被标记样本的盘接触比例 > 0.5，未标记的 < 0.05（native；说明揭示的接触标签与几何标志对得上）。
- **训练池**：`revealed_pool()` 可直接用于 `learned_mlx.batches`（native）。

## 变异（`mutate.sh`，原始输出 `mutate.log`）

隔离副本：`git archive HEAD src tests pyproject.toml`，加上本卡新增和改动的 4 个文件；`PYTHONPATH` 指向副本的 `src`，日志首行确认模块从副本加载。经锁运行，副本基线 23/23 通过。

```
copy: /var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T//p253-mut.mYoHJv
module from /var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p253-mut.mYoHJv/src/ainerzero/v9/experiments/s6/sandbox.py
== baseline: 23 passed in 1.36s
replaced 1
== M1 states() also carries a label field (p1): 3 failed, 20 passed in 1.40s
replaced 1
== M2 pick_top ties by id descending: 1 failed, 22 passed in 1.33s
replaced 1
== M3 reveal does not check repeats: 1 failed, 22 passed in 1.38s
replaced 1
== M4 geo_flags drops the overlapping-and-approaching clause: 2 failed, 21 passed in 1.39s
replaced 1
== M5 geo_flags ignores approach (b < 0) in the touch-within-dt clause: 2 failed, 21 passed in 1.51s
replaced 1
== M6 reveal skips the log: 2 failed, 21 passed in 1.35s
replaced 1
== M7 a public property leaks the label store: 2 failed, 21 passed in 1.39s
replaced 1
== M8 picks do not sort remaining (caller order leaks into the draw): 2 failed, 21 passed in 1.33s
replaced 1
== M9 pick_geo fills from all remaining (may repeat a flagged pick): 3 failed, 20 passed in 1.38s
replaced 1
== M10 reveal returns rows in sorted order, not the given order: 3 failed, 20 passed in 1.35s
== restored: 23 passed in 1.40s
```

- 卡片要求的 3 个都杀死：M1 `states()` 多带标签字段，M2 `pick_top` 同分改降序，M3 `reveal` 不查重复。
- 另加 7 个，也都杀死：几何两个分支、日志、公开属性泄漏、`remaining` 不排序、补足重复、揭示行序。
- **M5 首轮存活：** 去掉相接分支里的 `b < 0`。
  - 分析：这个变异只在 b = 0 且 c = 0（恰好相切、切向运动）时与原式不同，其他情形里 `tau ≥ 0` 已蕴含 `b < 0`。
  - 补救：补了这个手算情形和 native 边界对照，复跑后杀死。上面贴的是复跑后的完整输出。

## 未做 / 留给复核

- 非作者复核：建议核对 `geo_flags` 与 `geo_gate` 的逐行等价，并检查有没有绕过封存的公开路径。
- 运行器还没接入本模块。接入时以本模块为权威，原型里的 `subset`、`flat_pool` 和挑选代码退役。
