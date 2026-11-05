# ainerzero.V9.T51 r2 一级对抗验收（claude）

结论：**验收通过**。r1 已于 10-28 打回，打回原因是查找登记文件时可被绕过。

- **一级复现的四种绕过，r2 全部关闭**：
  - A：用环境变量 `T28_REGISTERED_PATH` 指向伪登记，结果 1200.0 / None，未受影响；
  - B：在 cwd 放伪 `reports/V9-T28/REGISTERED.json`，结果 1200.0，未受影响；
  - C1：提案路径用绝对路径，被拒；
  - C2：用 `..` 逃逸，或指向 `reports/V9-T28/` 之外的路径，均被拒。
- **一级自做的五个变异体，新测试全部捕获**（`tests/test_t28_registration_and_quota.py`，每个都是 1 failed）：恢复环境变量读取、恢复 cwd 查找、SHA 校验恒真、override 取最早日期、去掉单次 120 s 检查。
- **测试**：
  - DA3 加登记相关 5 个文件，86 passed；
  - 附加的 `tests/test_t28_bad_controls_r2.py` 4 passed，只写 tmp_path。
- **改动范围**：`t28_registration.py`、`da3_controlled.py`、`da3_worker.py`、`benchmark_protocol.py` 与两个测试文件。
  - `da3_controlled.py` 里的旧名 import 已删；
  - `envs/teachers/t6/pipeline.py` 的 SHA `67357ea4…` 未变；
  - `reports/V9-T28/` 未动；`REGISTERED.json` 尚未创建（由一级在登记时写）。
