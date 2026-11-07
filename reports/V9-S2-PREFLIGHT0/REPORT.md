# 一级 claude 直接改动：S2 运行前预检 Preflight 0（2026-11-07）

用户 11-07 指示：「你直接一级二级全做」。按惯例，一级自己写的代码仍交非作者复核。

## 缺口
- 原 `s2/commands.py` 在非 verify 模式下调用 `_check_approval_preflight(research_log)` 时没有传 `expected_sha256`。结果是：任何格式合法的批准行都会被放行，不管它是不是对应当前冻结的预登记。
- 身份核对只在 verify 模式里做，运行模式不核对代码是否与冻结版本一致。E1 每次运行前都会做这项核对。

## 改动
1. **`s2_phase1_command` 新增 Preflight 0**，在所有非 verify 模式最前面执行：
   - `prereg.json` 不存在 → 拒绝，stage=unfrozen，exit 3；
   - `identity.verify_frozen_identity` 不通过 → 拒绝，stage=identity_mismatch 或 identity_verification，exit 1；
   - 读不到冻结的 document_sha256，或格式不对 → 拒绝；
   - 批准预检改为 `_check_approval_preflight(research_log, expected_sha256=冻结文档 SHA)`。
2. **测试**：
   - `test_s2_lifecycle.py` 新增 `_freeze_and_approve`：在 tmp 里真实冻结一次，再写入匹配的批准行。(b)(c)(d)(f) 四个用例改用它；(a) 改为「已冻结、没有批准行」。
   - 新增 4 个用例：g 未冻结；h 批准行写的是别的哈希；i 源码身份不符（monkeypatch 摘要）；j 冻结且哈希一致，准入。
   - `test_s2_train_runner.py::test_duplicate_execution_via_worker_commands` 改为真实冻结后再批准。
   - `test_s2_wiring.py::test_commands_dispatch_to_runners` 同样改为真实冻结后再批准。

## 结果
- S2 三个测试文件共 43 passed。
- 默认全量 3621 passed / 0 failed / 6 deselected（前台 SIG_DFL+execv，297 s）。
- 改动后的 SHA 见 `sha256.txt`；`commands.py.after` 是改动后文件的副本。s2 目录尚未入 git，所以没有 git diff；复核时请对照 P148 r3 交付时的 commands.py。
