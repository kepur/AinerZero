# 作者侧分析工具修正（不是冻结文件损坏）

原失败完整保留在 `../evidence/analysis1/`。原检查错误地把 46 文件完整冻结清单的摘要，与 `code_manifest_sha256` 比较；JSON 紧凑编码本身没有用错。

本次从保存的生产源码 AST 提取并执行纯 Python 的 `run_guard.build_manifest`/静态 import closure 与 `prereg_identity.manifest_sha`，分别按 `make_prereg.py` 和 `current_identity` 的真实调用表达式重建集合。没有导入这些仓库模块或 MLX。

- 完整冻结集合：46 文件，重建后的路径和逐文件 SHA 与 PREREG 完全相同。
- 数值代码闭包：42 文件，是 `current_identity` 实际登记的集合。
- 42 文件摘要：`dce517dfa554ad57bb60e9fec855c8954eeefd7ee75781f64ac22665dc2b29d1`，与注册值一致。
- 差集仅为下列 4 路径：
  - `reports/V9-S6-DESIGN/DESIGN-r3.md`
  - `reports/V9-S6-PHASE1/make_prereg.py`
  - `reports/V9-S6-PHASE1/prereg_evidence.py`
  - `reports/V9-S6-PHASE1/prereg_identity.py`

生产函数位置、原始调用表达式、源码 SHA 与复算结果见 `RESULTS.json`。本检查 rc=0，原失败是分析工具比较错集合，不能据此宣称真实 manifest 损坏。未改任何冻结文件或原失败证据。
