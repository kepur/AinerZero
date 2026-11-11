# P220 非作者代码复核报告：S4 二期评测工作进程独立 MLX 编译目录（被审提交 d14e04b）

- 任务：`ainerzero.V9.P220`（层级 2 · 执行层 · 类型 review · GPU 需求：否）
- 复核者：`gemini-h8f2`（二级 执行层 · 模型 Gemini 3.8 Flash；非代码作者，作者为一级 claude）
- 被审提交：`d14e04b`（2026-11-11）
- 交付目录：`reports/V9-S4-PHASE2/worker-tmpdir-review/`

---

## 结论：建议通过

提交 `d14e04b` 针对探针 p1 失败（MLX 编译 CPU 融合内核时的链接器并发写入冲突 `ld: open() failed, errno=17`）的诊断与修法**完全成立、设计完整、测试严密、数值逐位保真**：

1. **诊断完全成立**：在实机持锁复跑 8 轮 × 6 进程并发编译测试，`shared` 模式 48 次中发生 8 次冲突失败（准确复现探针 p1 的同名内核 `Maximum` 编译失败），而 `private` 模式 48 次全部成功（零失败）；
2. **修法时序与完整性严密**：工作进程在 `init()` 第一行即调用 `private_compile_dir()`，早于任何 MLX 计算与模型构建；主进程与校验脚本在工作进程并发期间不调用 MLX 编译；替身世界实测证实修改前后输出记录**逐位完全相同**（JSON 摘要与各格数组一致）；
3. **变异消杀率 100%**：在隔离副本中测试被审引入的新测试用例，3 项关键变异（去掉调用、调用后移、目录去 pid）**全部被杀**（1 failed, 1 passed）；
4. **一期与同类风险已排查**：一期 `worker_mlx.py` 存在相同潜在风险，但在 Phase 1 运行时由于主进程先训练已经预热并填满了缓存，故未在评测中暴露。Phase 2 无训练直接评测，故本修法具有决定性保护作用。

建议统筹予以通过并推进后续冻结与 final 执行。

---

## 1. 诊断成立吗？

### 1.1 并发冲突复现实验（8 轮 × 6 进程）
在实机共享锁 `artifacts/locks/m0-worker.lock` 下，运行 `reports/V9-S4-PHASE2/probe-p1-failure/race_repro.py`：
- `shared` 模式：所有 6 个 spawn 进程共用同一个全新的空 `TMPDIR`（模拟重启后系统缓存为空的情形）；
- `private` 模式：每个进程使用独立的私有临时子目录（`d14e04b` 修法）。

执行命令：
```bash
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
    .venv/bin/python -I reports/V9-S4-PHASE2/probe-p1-failure/race_repro.py shared 6 8 $WORK
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
    .venv/bin/python -I reports/V9-S4-PHASE2/probe-p1-failure/race_repro.py private 6 8 $WORK
```

原始输出（保存于 `evidence/race_repro_shared.txt` 与 `evidence/race_repro_private.txt`）：

```text
=== Running shared mode (8 rounds x 6 processes) ===
lock held by 31841
shared round 0: 0 of 6 failed
shared round 1: 0 of 6 failed
shared round 2: 0 of 6 failed
shared round 3: 0 of 6 failed
shared round 4: 6 of 6 failed  e.g. error: [Compile::eval_cpu] Failed to compile function Cf4IBroadcastABDf4IBroadcastBAEf4OMaximumCD_VC_f4_10408321403207385874_contiguous: Failed to execute command with
shared round 5: 0 of 6 failed
shared round 6: 2 of 6 failed  e.g. error: [Compile::eval_cpu] Failed to compile function Cf4IBroadcastABDf4IBroadcastBAEf4OMaximumCD_VC_f4_10408321403207385874_contiguous: Failed to execute command with
shared round 7: 0 of 6 failed
shared: 8 failures in 8 rounds x 6 processes

=== Running private mode (8 rounds x 6 processes) ===
lock held by 32275
private round 0: 0 of 6 failed
private round 1: 0 of 6 failed
private round 2: 0 of 6 failed
private round 3: 0 of 6 failed
private round 4: 0 of 6 failed
private round 5: 0 of 6 failed
private round 6: 0 of 6 failed
private round 7: 0 of 6 failed
private: 0 failures in 8 rounds x 6 processes
```

### 1.2 结论
实验结果强力支持作者的诊断：
- 在 `shared` 模式下，第 4 轮与第 6 轮发生严重文件写冲突，报错函数签名 `Cf4IBroadcastABDf4IBroadcastBAEf4OMaximumCD_VC_f4_...` 与探针 p1 崩溃日志中的函数签名完全一致；
- 在 `private` 模式下，连续 8 轮共 48 次子进程编译 100% 成功，彻底消除竞态碰撞。

---

## 2. 修法完整吗？

### 2.1 设置时序追踪（静态代码追踪）
- 工作进程生命周期由 `evaluate_parallel`（`run_s4p2.py:184`）中的 `ProcessPoolExecutor(WORKERS, mp_context=ctx, initializer=WK.init, initargs=(weights,))` 管理；
- 在 `spawn` 模式下，子进程启动时首先导入 `worker_p2` 模块（仅定义类与函数，无任何全局 MLX 计算），随后立即调用 `initializer`，即 `worker_p2.init(weights)`；
- 在 `worker_p2.init` 中：
  ```python
  def init(weights: Mapping[str, str]) -> None:
      private_compile_dir()
      mx.set_default_device(mx.cpu)
      models, counters, dyn = build_models(weights)
  ```
  第一行即调用 `private_compile_dir()`；
- `build_models` 仅做模型实例化（`L.Dynamics`）与权重加载（`d.load_weights`），此时尚未执行任何前向计算或 `mx.eval`。
因此，`private_compile_dir()` 严格保证在子进程发生第一次 MLX 计算/编译之前执行。

### 2.2 MLX 编译缓存时机动态实验
针对「MLX 何时确定缓存目录」开展独立探针实验：
在新子进程中：
1. 设置 `TMPDIR = dir_a`，触发第一个内核编译（`nn.relu` 广播操作）；
2. 修改 `os.environ["TMPDIR"] = dir_b`，`tempfile.tempdir = None`；
3. 触发第二个新内核编译（`nn.gelu` 乘法操作）；
4. 重新触发第一个内核的另一尺寸操作。

实验原始输出（`evidence/mlx_cache_timing_detail.txt` 与 `evidence/mlx_cache_timing_same_op.txt`）：
```text
files in dir_a initially: ['.../dir_a/mlx/0.32.2/cpu/libCf4IBroadcastABDf4IBroadcastBAEf4OMaximumCD_VC_f4_10408321403207385874_contiguous.so', '.../Cf4...cpp']
files in dir_a after pattern 2: ['.../dir_a/mlx/0.32.2/cpu/libCf4IBroadcast...so', '.../Cf4...cpp']
files in dir_b after pattern 2: ['.../dir_b/mlx/0.32.2/cpu/libEf4IBroadcastABFf4IBroadcastBAGf4IDivide...so', '.../Ef4...cpp']
```
实验结论：
- MLX 在生成新内核的编译目标时，动态读取当刻的 `TMPDIR` 环境变量；
- 已经编译并加载过的内核会在当前进程内部缓存（无需重写磁盘）；
- **关键启示**：如果在进程初始化阶段未能先设置私有 `TMPDIR`，一旦发生任何编译，该内核就会落入公共共享目录，从而引发与其他工作进程的写碰撞。因此在 `init()` 第一行设置 `private_compile_dir()` 是唯一安全完备的时机。

### 2.3 主进程与校验脚本的并发风险分析
审查 `run_s4p2.py` 执行流：
1. **主进程**：在 `evaluate_parallel` 执行期间（行 184–202），主进程仅通过 `wait()` 等待子进程 Future，并在收到数据时追加写入 `worlds.partial.jsonl`，完全不调用 MLX。主进程自身的 `student_check` 发生在行 293，此时 `ProcessPoolExecutor` 已完全退出并回收，无并发；
2. **校验脚本 `verify_labels_p2.py`**：纯 Python 标准库实现，不导入 `ainerzero`，更不导入 `mlx`；
3. **校验脚本 `verify_replay_p2.py`**：虽然使用 MLX，但它是在行 295 通过 `independent_check` 单进程串行启动的，此时工作进程池早已完全销毁，不存在并发写冲突。

### 2.4 数值逐位一致性验证
编写独立比对脚本（`evidence/numerical_parity.py`），对替身世界 `standin-s4p2-test`（6 盘，60 步）分别使用修法前逻辑（全局 TMPDIR）与修法后逻辑（私有 TMPDIR）进行全量评测，比对输出的全部格输出与指标。

原始输出（`evidence/numerical_parity.txt`）：
```text
lock held by 32999
JSON records are bitwise identical! Length: 10175
All cell evaluations and metrics are bitwise identical!
```
结果证实：私有编译目录仅隔离磁盘写入文件句柄，编译产生的机器码与执行结果**逐位完全一致**，不影响任何评测数值与判定结论。

---

## 3. 测试抓得住吗？（变异消杀）

在 `git archive d14e04b` 隔离副本中，使用 `evidence/mutate_worker_review.py` 对新测试 `tests/v9/experiments/test_s4p2_worker_native.py` 进行消杀检验。

原始输出（`evidence/mutants_worker.txt`）：

```text
lock held by 33142
== clean_worker: 工作进程测试基线（不改源码）
   imported from copy: ['.../clean_worker/src/ainerzero/v9/experiments/s4/worker_p2.py']
   result: baseline-ok  exit=0  2 passed in 2.08s

== M01_remove_call_in_init: 变异 1：去掉 init() 里的 private_compile_dir() 调用
   imported from copy: ['.../M01_remove_call_in_init/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/worker_p2.py: -'def init(weights: Mapping[str, str]) -> None:\n    private_compile_dir()'
                                                 +'def init(weights: Mapping[str, str]) -> None:'
   result: killed  exit=1  1 failed, 1 passed in 2.32s
   FAILED tests/v9/experiments/test_s4p2_worker_native.py::test_init_sets_the_directory_before_anything_else

== M02_call_after_build_models: 变异 2：将 private_compile_dir() 挪到 build_models 之后
   imported from copy: ['.../M02_call_after_build_models/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/worker_p2.py: -'private_compile_dir()\n    mx.set_default_device(mx.cpu)\n    models, counters, dyn = build_models(weights)'
                                                 +'mx.set_default_device(mx.cpu)\n    models, counters, dyn = build_models(weights)\n    private_compile_dir()'
   result: killed  exit=1  1 failed, 1 passed in 2.03s
   FAILED tests/v9/experiments/test_s4p2_worker_native.py::test_init_sets_the_directory_before_anything_else

== M03_dir_without_pid: 变异 3：目录不带 pid，即所有进程共用一个目录
   imported from copy: ['.../M03_dir_without_pid/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/worker_p2.py: -'d = Path(tempfile.gettempdir()) / "ainerzero-mlx-cpu" / str(os.getpid())'
                                                 +'d = Path(tempfile.gettempdir()) / "ainerzero-mlx-cpu"'
   result: killed  exit=1  1 failed, 1 passed in 1.43s
   FAILED tests/v9/experiments/test_s4p2_worker_native.py::test_each_worker_compiles_into_its_own_directory
```

### 变异结果分析
- **M01（去掉调用）**：被 `test_init_sets_the_directory_before_anything_else` 杀死；
- **M02（调用后移）**：被 `test_init_sets_the_directory_before_anything_else` 杀死；
- **M03（目录去 pid，共用目录）**：被 `test_each_worker_compiles_into_its_own_directory` 杀死。测试中通过断言 `r["dir"].endswith(f"ainerzero-mlx-cpu/{r['pid']}")` 以及 `a["dir"] != b["dir"]` 双重拦截，有效保证目录必须携带独立 pid。测试无需补充，现有防护已足够充分。

---

## 4. 其他地方是否有同类风险？

全仓库静态检索 `ProcessPoolExecutor` 与 `mp.get_context("spawn")`：
1. **一期评测工作进程 `src/ainerzero/v9/experiments/s4/worker_mlx.py`**：
   `init(weights, refs)` 中未设置私有编译目录。一期之所以在实际运行中没有崩溃，是因为一期流程包含模型训练环节，主进程在训练阶段已在主进程的 `$TMPDIR` 下预先编译好了所有内核并写入缓存；而在二期（P2）中，不进行任何训练，重启机器后若直接进入 6 工作进程并行评测，各进程同时面对全新空缓存，遂暴露出此竞态漏洞。
   一期已收口归档，此处记录存档，不作修改。
2. **摸底脚本 `reports/V9-S4-P2-DESIGN/tier1-explore/explore_p2g.py`**：
   使用的是 `worker_p2.init`，已自动继承本修法，不存在风险。
3. **其他进程池**：如一期诊断脚本 `diag_nonfinite.py` 仅用于离线单次诊断，无生产影响。

---

## 5. 实盘测试复跑原始输出

在工作树中经共享锁全量复跑 S4 二期测试：
1. `test_s4p2_worker_native.py`（新测试）：**2 passed in 2.88s**；
2. `test_s4_gated.py`：**12 passed in 0.30s**；
3. `test_s4_analysis_p2.py`：**68 passed in 13.89s**。

守卫核查：除本复核报告目录外，未改动任何源码或已有测试；未生成或写入任何 `artifacts/` 违规世界。
