# P238 之后一级补测与复验（2026-11-12）

**补测（`test_s5_runner_native.py`，b5859fc）：**
- 修好 `test_final_partition_cell_is_refused_before_any_cell`。一级加预检后，这条测试没写输入桩，先被预检拦下，报错中断。
- 补五条测试，对应复核者指出的 M1–M5：
  - final 各种名字（含 `-shift`）都被拒；
  - 只篡改第二个文件的 SHA 也要失败；
  - 子进程抛异常时报出该异常，且不记完成；
  - 预检要求 lab 教师目录；
  - 预检要求数据文件，不只要清单。

**复验：** `mutations-15.py`，原始输出在 `mutations-15-output.txt`。
- 副本用 `git archive HEAD` 导出。第一次用 rsync 复制工作树，把 P239、P240 的未提交改动带了进去，副本基线就失败了，那一轮作废。
- 基线：29 passed。
- 15 处改动全部被拦下，每处都由对应的测试拦下：
  - R1–R8：一级原有的八处；
  - M1–M5：复核者提出的五处；
  - P1–P2：预检的两处。
