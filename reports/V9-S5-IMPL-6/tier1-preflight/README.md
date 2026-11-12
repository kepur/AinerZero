# 一级修正（2026-11-12）：教师特征目录按分区存放；真实阶段先做输入预检

**事故：**
- 第一次真实 probe（use id `probe-20261112a`）一开跑就失败：`V-JEPA feature not found: artifacts/v9/s5/teachers/vjepa/world_0042/...`。
- 原因：教师抽取把特征按分区存到 `teachers/<teacher>/<partition>/world_XXXX/`，运行器却到 `teachers/<teacher>/world_XXXX/` 下读，少了分区这一层。P236 报告里也写过「这次没对着现盘核对」。
- 这次失败消耗了 1 次 dev 使用（上限 8 次），但一个格子都没跑，dev 上什么都没读到。

**修正（`run_s5p1.py`）：**
- 新增 `REAL_TEACHERS`：蒸馏用 pool 的 V-JEPA 与 DA2（`teachers/{vjepa,da2}/s5p1-pool`），A4 用 lab 的 V-JEPA（`teachers/vjepa/s5p1-lab`）。
- 新增 `_preflight_real_inputs()`，在 `consume_dev_use` 之前调用：pool、lab、dev 三个数据分区与三个教师目录都必须有 `manifest.json`，且至少有一个对应文件，缺任何一项都报 `GuardError`，不消耗 dev 使用，也不建运行目录。

**测试（`test_s5_runner_native.py` 末尾）：**
- `test_probe_without_real_inputs_fails_before_spending_a_dev_use`；
- `test_preflight_requires_teacher_features_stored_per_partition`：不分区的目录结构必须被拒，按分区的必须通过。

**源码坏对照（隔离副本，持锁，`mutpre.py`）：** 两处都拦住。
- P1 把教师目录改回不分区；
- P2 去掉 dev 使用前的预检。

**复核：** 这次改动并进 P238，由非作者一起复核。
