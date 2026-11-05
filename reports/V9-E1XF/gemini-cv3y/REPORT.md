# 任务报告 ainerzero.V9.P77：E1 后续：export 支持真实 B25 S 族格式与彻底移除 data_runner 绕行

## 1. 任务基本信息
- **任务编号**：`ainerzero.V9.P77`
- **执行 Agent**：`gemini-cv3y`（二级执行 agent，code 类型）
- **所属阶段**：AnimeWorld Zero · V9 落地世界系统侧 (E1 实验体系)
- **文件范围**：
  - `src/ainerzero/v9/experiments/e1/export.py`
  - `src/ainerzero/v9/experiments/e1/data_runner.py`
  - `tests/test_e1_export.py`
  - `tests/test_e1_data_runner.py`
  - `reports/V9-E1XF/gemini-cv3y/`
- **交付状态**：`completed`

---

## 2. 背景与问题定位

在 AnimeWorld Zero (AWZ) 真实物理数据生成（`_pure_hidden.py` / `blender_worker.py`）中，S 族的物理机制（`mechanisms`，形如 `[{"id": "quadratic_drag_v1", ...}]`）以及与 P 族的配对标识（`paired_p_world_key`，形如 `"ramp_roll_p_seed1001"`）均注入存放在 `metadata["hidden_parameters"]` 字典内。

在原有 `export.py` 中：
1. `all_obj_names = sorted(list(set(list(hidden_params.keys()) + list(first_frame_objs.keys()))))` 直接将 `hidden_params` 的全部键名当作刚体物体名称处理。
2. 随后在遍历 `all_obj_names` 时执行 `h_info.get("is_active", True)`，当处理到 `"mechanisms"` 键时，`h_info` 为 `list` 类型，抛出 `AttributeError: 'list' object has no attribute 'get'`。
3. 在此前 P75 紧急调试中，曾临时在 `data_runner.py` 中引入 `adapt_s_sequence_for_export` 辅助函数从 `hidden_parameters` 中弹出这两个键放到顶层 `metadata` 规避崩溃。
4. 本任务从根源修正 `export.py` 的解析与防泄漏逻辑，支持官方规范的真实 B25 格式，并彻底删除 `data_runner.py` 内部的绕行适配代码。

---

## 3. 具体实现方案

### 3.1 `export.py` 核心修改
1. **定义注册的非物体配置键常量**：
   ```python
   NON_OBJECT_HIDDEN_KEYS: frozenset[str] = frozenset({
       "mechanisms",
       "paired_p_world_key",
   })
   ```
2. **静态几何转换过滤**：
   在 `convert_static_geometry` 循环中，若 `name in NON_OBJECT_HIDDEN_KEYS or not isinstance(obj_meta, Mapping)`，直接跳过，防止将全局机制解析为静态碰撞体。
3. **物体识别与属性提取**：
   在 `export_sequence` 中构造 `object_hidden_params`，显式过滤掉 `NON_OBJECT_HIDDEN_KEYS` 及非 Mapping 项，确保后续活跃刚体与静态环境构建只处理真实的刚体对象。
4. **机制与配对信息的双源提取与解耦**：
   - `mechanisms` 优先从 `metadata` 获取，若无则从 `hidden_params` 中提取。
   - `paired_p_world_key` 优先从 `metadata` 获取，若无则从 `hidden_params` 中提取。
   - 提取出的信息仅写入 `eval_view`（评测方真值端），并在 `eval_view["hidden_parameters"]` 中保留纯净的物体级物理参数；
   - 学生端视图（`student_view`）严格经过 `assert_no_leakage` 门禁，机制与真实配对标识绝对不外泄。

### 3.2 `data_runner.py` 清理与规范化
1. **删除临时绕行**：
   彻底删除了 `adapt_s_sequence_for_export` 函数及其在 `train`、`development`、`final` 导出循环中的所有调用。
2. **规范常量引用**：
   直接从统一规范 `from ainerzero.v9.experiments.e1.spec import FAMILIES as DEFAULT_FAMILIES` 导入，消除硬编码。
3. **安全提取配对键**：
   更新寻找配对 P 序列时的键提取逻辑：
   `pwk = meta.get("paired_p_world_key") or meta.get("hidden_parameters", {}).get("paired_p_world_key")`，兼容所有来源。

### 3.3 测试用例增补 (`tests/test_e1_export.py`)
1. **`test_real_b25_s_family_hidden_parameters_export`**：
   构建符合 AWZ B25 真实规范的 S 族序列（`mechanisms` 与 `paired_p_world_key` 位于 `hidden_parameters`）。
   - 验证导出顺利执行，无类型异常；
   - 验证学生视图通过 `assert_no_leakage`；
   - 验证学生端 `active_bodies` 及各帧 `objects` 中均不含非物体键；
   - 验证评测端 `s_eval["mechanisms"]` 正确接收到机制列表且 `paired_p_opaque_id` 与配对的 P 序列学生不透明 ID 完全一致；
   - 验证 `s_eval["hidden_parameters"]` 仅包含有效物体。
2. **`test_convert_static_geometry_ignores_non_object_keys`**：
   验证当 `hidden_parameters` 混入 `NON_OBJECT_HIDDEN_KEYS` 时，`convert_static_geometry` 安全忽略，不产生异常碰撞体。

---

## 4. 验证与测试结果

### 4.1 导出与数据生成模块测试
```bash
.venv-ainerzero/bin/pytest tests/test_e1_export.py tests/test_e1_data_runner.py -v
============================== 14 passed in 6.22s ==============================
```
全部 14 项单元测试均通过，无任何失败。

### 4.2 完整 E1 实验非 entry 测试套件
```bash
.venv-ainerzero/bin/pytest tests/test_e1_*.py -k "not entry" -v
====================== 92 passed, 11 deselected in 9.21s =======================
```
92 项回归测试全部通过，证明修改未对原有模型网络、前向先验、评测指标、预登记逻辑产生任何不良回归。

---

## 5. 源码突变坏对照（Bad Controls）证据

在独立临时沙箱环境中运行 `reports/V9-E1XF/gemini-cv3y/run_bad_controls.py`，执行 2 项真实源码突变测试：

| 对照编号 | 突变操作 | 预期结果 | 实测表现 | 结论 |
|---|---|---|---|---|
| **Bad Control 1** | 移除 `export.py` 中的 `NON_OBJECT_HIDDEN_KEYS` 过滤，将 `hidden_parameters` 中的所有键均作为刚体物体解析 | `test_real_b25_s_family_hidden_parameters_export` 出现 `AttributeError` 崩溃 | `AttributeError: 'list' object has no attribute 'get'`（exit code 1） | **RED (有效拦截)** |
| **Bad Control 2** | 人为将 `mechanisms` 注入 `student_view` 中 | `assert_no_leakage` 门禁触发 `LeakageError` | `LeakageError: Forbidden key 'mechanisms' found at $`（exit code 1） | **RED (有效拦截)** |

详细日志已记录于 `reports/V9-E1XF/gemini-cv3y/bad_controls_summary.json`。

---

## 6. 交付物清册与校验码
交付目录 `reports/V9-E1XF/gemini-cv3y/` 包含以下文件：
- `before/export.py`（修改前备份）
- `before/data_runner.py`（修改前备份）
- `run_bad_controls.py`（自动化坏对照执行脚本）
- `bad_controls_summary.json`（坏对照测试执行明细）
- `metrics.json`（结构化指标记录）
- `REPORT.md`（本报告）
- `SHA256SUMS.txt`（校验和文件）
