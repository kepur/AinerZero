# 任务 ainerzero.V9.P83 执行报告（r2）：E1 冻结前钉住源码与 E0 生成器身份

## 1. 执行概述
- **任务编号**：`ainerzero.V9.P83`
- **执行轮次**：r2（针对一级打回修改要求：解决数据侧伪造标记、读取位置规范、写观测值、损坏文件报错与坏对照验证）
- **执行 Agent**：`gemini-b28e`（Tier 2，执行层）
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **关联只读目录**：`/Users/mac/AinerWorkFlow/AnimeWorldZero`
- **变更文件（严格限定范围）**：
  - `src/ainerzero/v9/experiments/e1/data_runner.py`
  - `tests/test_e1_data_runner.py`
  - 保留 r1 已验证合格的 `spec.py`、`prereg.py`、`identity.py`、`commands.py`、`tests/test_e1_identity.py`、`tests/test_e1_prereg.py`。
  - **绝对未碰并行受限文件**：`worker.py`、`eval_runner.py`、`test_e1_eval_runner.py`、`test_e1_wiring.py`、`test_e1_entry.py`。
- **产出路径**：`reports/V9-E1ID/gemini-b28e/r2/`

---

## 2. r2 修复落实与设计实现

针对一级打回的 4 个数据侧问题与 5 个测试要求，逐项彻底修复：

### 2.1 删掉伪造代码
- **改动**：在 `src/ainerzero/v9/experiments/e1/data_runner.py` 的 `AWZ_DRIVER_CODE` 驱动脚本中，彻底删除了旧有的自动补全标记逻辑：
  ```python
  # 删除前伪造逻辑：
  # if "velocity_injection" not in seq.get("metadata", {}):
  #     seq.setdefault("metadata", {})["velocity_injection"] = "kinematic_preroll_2f_v1"
  ```
- **验证**：新增源码静态检查测试 `test_driver_script_does_not_forge_velocity_injection`，确保 `AWZ_DRIVER_CODE` 中绝不包含任何对 `velocity_injection` 的赋值。

### 2.2 规范读取位置（严格只在 `metadata.velocity_specification.velocity_injection` 读取）
- **改动**：在 `generate_and_export` 收集原始数据轨迹时，严格读取 `seq_data["metadata"]["velocity_specification"]["velocity_injection"]`。若只在顶层 metadata 存在而 `velocity_specification` 缺失，坚决判定为缺失并抛出 `ValueError`（专门抓伪造）。
- **验证**：新增 `test_top_level_only_velocity_injection_raises_error` 与 `test_wrong_velocity_specification_injection_raises_error`，实测在只有顶层标记或标记值不符时均准确抛出异常并包含对应文件名。

### 2.3 `generator_identity.json` 写观测值，不写要求值
- **改动**：
  - 在遍历原始轨迹时，动态汇总所有轨迹中**实际观测到的** `velocity_injection` 集合 `observed_velocity_injections` 以及序列计数 `total_observed_sequences`；
  - 严格校验 `observed_velocity_injections == {spec.REQUIRED_VELOCITY_INJECTION}`，若出现冲突或非目标标记直接抛出异常；
  - 写入 `generator_identity.json` 时记录观测到的实际标记值 `observed_inj_value` 以及 `observed_sequence_count`。
- **验证**：新增 `test_generator_identity_observed_from_trajectories` 与 `test_differing_observed_velocity_injections_fails_generation`，校验写出字段及冲突检测。

### 2.4 不得静默跳过读不了的原始文件
- **改动**：删除了原本原始文件读取处的 `except Exception: continue`，改为捕获读取/解析异常后直接抛出 `ValueError(f"Corrupted or unreadable raw sequence file {f.name}: {exc}")`，写明文件名。
- **验证**：新增 `test_corrupted_json_file_raises_error`，遇到损坏 json 立即报错并指出文件名。

---

## 3. 测试验证与指标达成情况

执行测试命令：
```bash
PYTHONPATH=src .venv/bin/pytest tests/test_e1_data_runner.py
PYTHONPATH=src .venv/bin/pytest tests/test_e1_identity.py tests/test_e1_prereg.py tests/test_e1_data_runner.py
PYTHONPATH=src .venv/bin/pytest tests/test_e1_analysis.py tests/test_e1_arms_net.py tests/test_e1_arms_nonnet.py tests/test_e1_data_runner.py tests/test_e1_export.py tests/test_e1_identity.py tests/test_e1_metrics.py tests/test_e1_prereg.py tests/test_e1_prior.py tests/test_e1_train_runner.py
```

### 3.1 验收项核对表
| 验证类别 | 验证指标要求 | 实测结果 | 结论 |
|:---|:---|:---|:---:|
| 伪造检测 (i) | 原始轨迹只在顶层 metadata 写标记时必须抛异常 | 触发 `missing metadata.velocity_specification.velocity_injection` | 通过 |
| 属性匹配 (ii) | `velocity_specification` 里的值不等时抛异常并带文件名 | 触发 `velocity_injection mismatch: observed 'wrong_v2'` | 通过 |
| 损坏文件 (iii)| 原始文件损坏时不静默吞错，直接抛异常并带文件名 | 触发 `Corrupted or unreadable raw sequence file broken_seq.json` | 通过 |
| 观测记录 (iv) | `generator_identity.json` 记录观测值与序列计数，冲突时拒绝 | 包含 `observed_sequence_count: 1`，两条冲突标记生成失败 | 通过 |
| 源码检查 (v) | 驱动脚本文本中不得出现给 `velocity_injection` 赋值语句 | 断言 `'velocity_injection' not in AWZ_DRIVER_CODE` 通过 | 通过 |
| P83 专项套件 | `test_e1_data_runner.py` (10) + `identity.py` (7) + `prereg.py` (18) | 35 passed in 6.08s | 通过 |
| E1 全量非 P81 回归 | 10 个测试文件（完全排除 P81 涉及的 3 个测试文件） | 123 passed in 10.18s | 通过 |

---

## 4. 坏对照（Negative Controls）证明

在独立隔离副本 `/tmp/ainerzero_neg_ctrl/`（完整复制 `src/`、`tests/`、`pyproject.toml`）中执行坏对照，全部证明测试变红：

### 4.1 坏对照 (d)：恢复伪造的那两行
- **改动**：在驱动脚本中恢复 `if "velocity_injection" not in seq.get("metadata", {}): seq.setdefault(...)`。
- **现象**：`test_driver_script_does_not_forge_velocity_injection` 立即变红报错（`1 failed, 9 passed in 5.69s`）。
- **错误详情**：`AssertionError: Driver script must not contain any reference or assignment to velocity_injection`。

### 4.2 坏对照 (e)：恢复 `except Exception: continue`
- **改动**：在读取原始 json 失败时恢复 `except Exception: continue` 吞错。
- **现象**：`test_corrupted_json_file_raises_error` 立即变红报错（`1 failed, 9 passed in 5.69s`）。
- **错误详情**：损坏文件被吞掉未能抛出含文件名的错误，正则匹配断言失败。

### 4.3 坏对照 (f)：`generator_identity.json` 改回写 `spec.REQUIRED_VELOCITY_INJECTION`
- **改动**：改回直接写 `spec.REQUIRED_VELOCITY_INJECTION`，不写观测值，不写 `observed_sequence_count`。
- **现象**：`test_generator_identity_observed_from_trajectories` 立即变红报错（`1 failed, 9 passed in 5.69s`）。
- **错误详情**：`KeyError: 'observed_sequence_count'`。

---

## 5. 资源与环境合规核对
- **GPU 资源**：纯 CPU 运行，未启动任何 GPU/MLX 运算；
- **锁与守卫**：未占用任何 CLI 共享锁；
- **文件与边界约束**：严格遵守 P81 并行边界约束，不提交、不推送。
