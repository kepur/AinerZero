# 复核自证声明：复核者为独立二级代理 gemini-r7m2（会话 sess-d333d0d0ba05），非被验任务 ainerzero.V9.P140 作者 gemini-w4x2，亦非其同会话别名；全流程只读核对、纯 CPU 运行。

# V9.P140 S2 预登记冻结补测与校验独立复核报告

- **复核任务**：`ainerzero.V9.P141`（二级执行 Agent · verify）
- **复核对象**：`ainerzero.V9.P140`（作者：`gemini-w4x2`，待验收）
- **复核结论**：`RECOMMEND_ACCEPT`

---

## 一、修改范围核验（Scope Audit）

1. **`freeze.py` 严格单函数修改核验**：
   - 提取 `reports/V9-S2-P140/freeze.diff` 执行反向补丁恢复，经 SHA256 计算：
     - 反向恢复后散列：`0285efe7f519a5fb4fcffe33a9ed4d28f6844f2de7d9ad635ce7bdadfb76402a`；
     - 与 P132 交付版本 SHA256 100% 逐字节吻合。
   - 确证除 `approval_line` 函数内加入 64 位十六进制正则校验 `len(cleaned) != 64 or not re.fullmatch(r"[0-9a-f]{64}", cleaned)` 外，其余代码未受任何改动。
2. **测试文件扩充核验**：
   - `tests/v9/experiments/test_s2_freeze_identity.py` 新增两条单测：
     - `test_p140_cli_snippet_tamper_detected_and_names_cli_py`
     - `test_p140_approval_line_validation`
   - 测试套件总数由 6 项扩充至 8 项，全部绿灯。

---

## 二、CLI 段摘要测试真实性核验

在隔离沙箱副本中应用对抗性变异：去除 `collect_source_digests` 中对 `cli.py:s2-phase1` 的抽取逻辑。
- **运行结果**：单测 `test_p140_cli_snippet_tamper_detected_and_names_cli_py` 精准失败（退出码 1）；
- **报错详情**：`AssertionError: assert 'src/ainerzero/cli.py:s2-phase1' in res["source_digests"]`；
- **结论**：新用例能真实且敏感地捕获 CLI 片段抽取的遗漏，填补了此前 P134 变异测试发现的盲区。

---

## 三、非法输入全面拦截核验

复核者独立构造 5 种非法输入传入 `freeze.approval_line`：
1. **超长含特殊字符（64字符但含 `!`）**：抛出 `ValueError`；
2. **非十六进制字母（含 `z`）**：抛出 `ValueError`；
3. **嵌有换行符（32位 + `\n` + 31位）**：抛出 `ValueError`；
4. **内部嵌入空格（30位 + 4空格 + 30位）**：抛出 `ValueError`；
5. **全角 Unicode 伪数字（`０`*64）**：抛出 `ValueError`。
- **结论**：所有非法格式均被 `ValueError` 彻底拒绝，绝不向下游泄漏非规范批准行。

---

## 四、复核者独立对抗变异实验

在隔离沙箱中执行 2 处新增变异，跑完按字节恢复并核验 SHA256：

| 变异编号 | 变异位置与描述 | 预期拦截单测 | 测试结果 | 退出码 | 变异状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REV-P140-M1** | `freeze.py:approval_line`：去除 `.lower()` 小写归一化 | `test_p140_approval_line_validation`（大写十六进制传入用例） | **KILLED** | exit 1 | 抛出 `ValueError`，未能正常生成小写批准行。 |
| **REV-P140-M2** | `freeze.py:collect_source_digests`：修改键名为 `"cli.py"` | `test_p140_cli_snippet_tamper_detected_and_names_cli_py` | **KILLED** | exit 1 | 断言键名存在失败。 |

---

## 五、全量纯 CPU 回归与副作用核查

1. **前台全量纯 CPU 回归（SIG_DFL 还原）**：
   - 运行用时：265.49 秒；
   - 测试计数：**3542 passed, 6 deselected, 0 failed**（总计 3548 项，包含 S2 补齐的 8 项单测）；
   - 退出码：0。
2. **副作用核查**：
   - `artifacts/` 实盘比对：**0 modified, 0 added, 0 deleted**，零实盘写入。

---

## 六、综合结论

**`RECOMMEND_ACCEPT`**

V9.P140 精准响应了前期代码复核中关于 CLI 篡改测试盲区的反馈，改动严格限定在 `approval_line` 的 64 位十六进制格式校验，测试真实、变异对抗全红、全量回归 3542 项全通无副作用。建议立即予以验收通过。
