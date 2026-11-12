# P232：S5-IMPL-3 教师特征抽取脚本独立复核报告

- **复核任务**：`ainerzero.V9.P232`（AinerRelay 二级独立复核）
- **复核执行者**：`gemini-k7x2`（Tier-2 独立执行者，会话 `sess-7350d561b3fc`）
- **被复核对象**：`ainerzero.V9.P231`
- **被复核作者**：一级 `claude`（提交分支与工作区：`reports/V9-S5-IMPL-3/`）
- **复核范围**：
  - 核心脚本：`src/ainerzero/v9/experiments/s5/extract_teachers.py`
  - 测试用例：`tests/v9/experiments/test_s5_extract.py`
  - 作者报告：`reports/V9-S5-IMPL-3/REPORT.md`
- **复核环境**：纯 CPU（macOS Darwin 23.6.0 arm64，Python 3.12.2，未引入 MLX 原生运行，未碰 GPU 锁，未触碰 `artifacts/`）

---

## 1. P231 卡片要求逐条核对

对照 P231 任务卡片与实现协议要求，逐项核对代码实现、边界保护与契约测试。

### 1.1 先拿锁（Flock First）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L263-L266`
- **逐字引用**：
  > 行 263：`lock = acquire_lock(Path(lock_path))                     # lock first; nothing is written before this`
- **核对说明**：
  在 `main()` 入口中，解析参数后首先调用 `acquire_lock(Path(lock_path))`（使用非阻塞 `fcntl.LOCK_EX | fcntl.LOCK_NB`）。若锁被占用，立即打印 `lock busy` 并直接返回退出码 75（`EXIT_LOCK_BUSY = 75`），在拿锁成功前不创建输出目录、不构造教师模型实例、不写任何磁盘文件。对应测试 `test_lock_busy_exits_75_and_writes_nothing` 验证了锁冲突时退出码为 75 且不写入任何内容。

### 1.2 输出布局与数据类型（Layout & Dtype）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L58`、`#L155`、`#L167`
- **逐字引用**：
  > 行 58：`VJEPA_OUT = (1568, 1024)`  
  > 行 155：`want_shape = VJEPA_OUT if teacher == "vjepa" else (8, DA2_OUT_HW, DA2_OUT_HW)`  
  > 行 167：`if y.shape != want_shape or y.dtype != np.float16:`
- **核对说明**：
  - V-JEPA 输出严格规范为 `[1568, 1024]` fp16（16 帧对应 8 个时间步，每个步 $14\times 14=196$ 块，$8\times 196 = 1568$，特征维度 1024）；
  - DA2 输出严格规范为 `[8, 56, 56]` fp16（8 帧，每帧 $56\times 56$）；
  - `run()` 循环内对教师输出的 shape 与 dtype 进行双重强制断言，若不符则抛出 `RuntimeError`；对应测试 `test_wrong_teacher_output_is_refused` 与 `test_vjepa_run_feeds_the_preprocessed_clip` / `test_da2_run_layout` 全部通过。

### 1.3 可断点续抽（Resumability via Ledger）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L149-L150`、`#L160-L162`
- **逐字引用**：
  > 行 160：`if rel in ledger:`  
  > 行 161：`    n_skip += 1`  
  > 行 162：`    continue`
- **核对说明**：
  抽取脚本维护输出目录下的 `progress.jsonl` 行账本。每次启动时先由 `_read_ledger()` 装载已完成条目，若当前片段的相对路径已在账本中，则直接累加 `n_skip` 并跳过计算，避免重复开销；对应测试 `test_resume_after_crash_does_not_recompute` 模拟中途崩溃恢复场景，验证续跑时已写入片段被跳过、未重复计算。

### 1.4 防篡改与残留文件检查（Tamper & Stray Protection）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L153`、`#L164`、`#L170-L173`
- **逐字引用**：
  > 行 153：`if not p.exists() or sha256_file(p) != sha:`  
  > 行 164：`raise RuntimeError(f"output exists but is not in the ledger: {rel}")`
- **核对说明**：
  - 启动续跑时，逐个校验已记录在 `progress.jsonl` 中的文件 SHA256，文件缺失或内容被修改立即抛出 `RuntimeError("tampered or missing output: ...")`；
  - 写入前若发现目标路径已存在文件但未登记在账本中，立即抛出 `RuntimeError("output exists but is not in the ledger: ...")`，防止污染或混合不同分区产物；
  - 写入采用原子写入范式：先写入 `.tmp` 临时文件，再通过 `os.replace` 原子重命名，杜绝进程意外中断留下半写文件；
  - 对应测试 `test_tampered_output_is_refused` 和 `test_stray_output_not_in_ledger_is_refused` 均严格断言拦截。

### 1.5 拒绝向预登记分区抽取（Registered Partitions Refusal）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L63`、`#L146-L147`
- **逐字引用**：
  > 行 63：`REGISTERED_PARTITIONS = frozenset({"s5p1-final", "s5p1-final-shift"})`  
  > 行 147：`raise PermissionError(f"{meta.get('partition')} is a registered partition; teachers are not extracted for it")`
- **核对说明**：
  在 `run()` 开头读取输入目录的 `manifest.json`，若 `meta["partition"]` 包含在 `REGISTERED_PARTITIONS`（`s5p1-final` 或 `s5p1-final-shift`）中，立即抛出 `PermissionError`，完全阻止对预登记最终测试集的任何特征抽取；对应测试 `test_registered_partitions_are_refused` 在参数化下对两个分区均验证了防御有效性。

### 1.6 输出清单记录完整元信息（Manifest Identity & Metadata）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L180-L194`
- **逐字引用**：
  > 行 183：`"input_manifest_sha256": sha256_file(in_manifest),`
- **核对说明**：
  输出的 `manifest.json` 包含：
  - 输入目录清单 SHA256（`input_manifest_sha256`）；
  - 教师权重 SHA256（由 `extra_manifest` 注入）；
  - 代码身份：git HEAD 与本脚本 `extract_teachers.py` 的 SHA256 哈希；
  - 依赖环境版本（`mlx_version` 或 `coremltools_version`）；
  - 预处理参数规范（均值、方差、裁剪区间、重采样方式）；
  - 运行统计（处理数、跳过数、总耗时、中位每项耗时）；
  - 进度账本 SHA256（`ledger_sha256`）。
  对应测试 `test_world_range_and_manifest` 验证了清单字段及其哈希一致性。

### 1.7 教师模型权重 SHA256 校验（Weights Integrity）
- **结论**：**成立**
- **代码出处**：`src/ainerzero/v9/experiments/s5/extract_teachers.py#L99-L106`
- **逐字引用**：
  > 行 104：`raise RuntimeError(f"teacher weight SHA mismatch: {base / rel}: {sha} != {want}")`
- **核对说明**：
  脚本硬编码了 T4 批准的权重文件哈希清单（`VJEPA_SHA` 含 4 个文件，`DA2_SHA` 含 2 个文件）。在真实教师构建函数 `make_vjepa()` 和 `make_da2()` 中，均首先调用 `verify_weights()` 逐文件核对哈希，若有任何不匹配立即抛出 `RuntimeError`，杜绝静默加载不同版本权重；对应测试 `test_weight_sha_check_rejects_mismatch` 验证了哈希不匹配时被直接拒绝。

---

## 2. 与 `explore_s5a.py` 预处理逐行对比分析

核对 `extract_teachers.py` 与第 A 轮摸底脚本 `reports/V9-S5-DESIGN/tier1-explore/explore_s5a.py` 的预处理逻辑一致性：

### 2.1 V-JEPA 预处理对比
- **`explore_s5a.py`（§3，行 155–156、166）**：
  ```python
  mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)[:, None, None, None]
  std = np.array([0.229, 0.224, 0.225], dtype=np.float32)[:, None, None, None]
  x = (clip.transpose(3, 0, 1, 2).astype(np.float32) / 255.0 - mean) / std
  ```
- **`extract_teachers.py`（行 73–76）**：
  ```python
  mean = np.asarray(IMAGENET_MEAN, dtype=np.float32)[:, None, None, None]
  std = np.asarray(IMAGENET_STD, dtype=np.float32)[:, None, None, None]
  x = (clip.transpose(3, 0, 1, 2).astype(np.float32) / 255.0 - mean) / std
  return x[None]
  ```
- **对比结论**：**完全一致（成立）**。
  通道转置顺序 `(3, 0, 1, 2)`（RGB 优先）、归一化系数（除以 255.0）、ImageNet 标准均值方差广播方式与输出布局 `[1, 3, 16, 224, 224]` 完全一致。

### 2.2 DA2 预处理与下采样对比
- **`explore_s5a.py`（§2，行 124–125）**：
  摸底脚本在整幅 $(518, 392)$ 上评估 Spearman 相关系数，遇到尺寸不匹配时采用 `Image.BILINEAR` 缩放到 $(518, 392)$。
- **`extract_teachers.py`（行 60–62、85–87）**：
  ```python
  DA2_CROP = (63, 455)          # middle 392 of 518 columns
  DA2_OUT_HW = 56
  crop = np.ascontiguousarray(depth[:, DA2_CROP[0]:DA2_CROP[1]].astype(np.float32))
  img = Image.fromarray(crop, mode="F").resize((DA2_OUT_HW, DA2_OUT_HW), Image.BOX)
  return np.asarray(img, dtype=np.float32).astype(np.float16)
  ```
- **对比结论**：**演进完全合理且符合设计规范（成立）**。
  - **裁剪依据**：学生输入为正方形视场 $(224, 224)$，对应 DA2 渲染画面的正中央正方形 $392 \times 392$。总宽度 518 列中取中间 392 列即为列索引 $[63:455]$（$63 + 392 = 455$，$518 - 455 = 63$，左右各留 63 像素边距），完全对齐相机中心视角。
  - **下采样依据**：$392 / 56 = 7.0$ 为整倍数关系。采用 `PIL.Image.BOX` 执行精确的 $7\times 7$ 均匀面积平均（Area Average / Box Filter），数学上严格等价于 $7\times 7$ 块均值池化，杜绝了双线性插值（`BILINEAR`）在高对比度物体边缘产生的振铃与伪影。

---

## 3. 独立设计的源码坏对照（C1–C4）

为独立验证 `tests/v9/experiments/test_s5_extract.py` 测试套件的防线有效性与严密性，设计并执行了 4 个新的源码变异（C1–C4），不与 P231 作者的 B1–B10 重复。

所有变异均在隔离临时目录中通过自动化脚本 `reports/V9-S5-IMPL-3/review/evidence/mutations.py` 运行，基线与变异输出完整记录在 `evidence/mutations-output.txt`。

| 编号 | 变异位置与内容 | 设计意图与机理 | 结果 | 击杀该变异的测试 |
|---|---|---|---|---|
| **C1** | `vjepa_input` 中移除 `clip.dtype != np.uint8` 类型检查 | 若传入已归一化的 float32 数组，缺少 dtype 校验将导致重复除以 255.0，造成严重数值衰减 | **KILLED** | `test_vjepa_preprocess_layout_and_values` (1 failed, 12 passed) |
| **C2** | `iter_items` 中将 `worlds[0] <= w < worlds[1]` 变异为 `worlds[0] < w < worlds[1]` | 模拟边界栅栏错误（fencepost error），跳过下界世界号 `worlds[0]` | **KILLED** | `test_world_range_and_manifest` (1 failed, 12 passed) |
| **C3** | `verify_weights` 中将 `if sha != want:` 变异为 `if False and sha != want:` | 模拟模型权重 SHA 校验失效或被绕过，允许损坏/篡改的权重通过 | **KILLED** | `test_weight_sha_check_rejects_mismatch` (1 failed, 12 passed) |
| **C4** | `DA2_CROP` 将 `(63, 455)` 变异为 `(63, 454)`（391 列） | 模拟 1 像素偏差破坏 $7\times 7$ 整数倍网格，导致面积平均网格偏移 | **KILLED** | `test_da2_target_takes_middle_columns_and_area_averages` (1 failed, 12 passed) |

**变异测试小结**：4/4 新设计变异均被契约测试准确捕获并击杀，证明测试套件对数据类型守卫、世界号半开区间边界、外部权重真实性校验以及图像下采样几何对齐均具备灵敏的拦截能力。

---

## 4. 脆弱性与边缘情况分析（Vulnerabilities & Edge Cases）

1. **根目录路径写死深度（`ROOT = Path(__file__).resolve().parents[5]`）**：
   - *现状*：脚本第 26 行将 `ROOT` 定义为当前文件上溯 5 级的父目录。如果将来脚本被移动至其他目录层级，`ROOT` 指向将失效。
   - *评估*：当前属于稳定目录结构，在阶段 S5 内不影响执行；后续若有重构建议由统一配置注入或通过查找 `.git` 根目录定位。
2. **Core ML / DA2 在纯 CPU 测试环境与真实运行环境的解耦**：
   - *现状*：在纯 CPU 测试环境中，`test_s5_extract.py` 采用 fake teacher 测试流程，真实 `make_da2()` 仅在拥有 Core ML 运行时的特定 python 环境（`envs/teachers/.venv-t4`）中被实际调用。
   - *评估*：设计契约合理，符合“纯 CPU 快速回归、真实教师持锁冒烟”的工程守则。作者在 P231 报告中已通过真实冒烟验证了逆深度与对数深度的负相关性（Spearman $-0.949$）。
3. **输入目录缺失 `manifest.json`**：
   - *现状*：`run()` 假定 `in_dir / "manifest.json"` 必定存在。若输入目录未物化完成即调用，会直接触发 `FileNotFoundError`。
   - *评估*：符合预期，因物化脚本规范要求必须先生成清单，不具备清单的分区禁止被消费。
4. **并发冲突与脏目录保护**：
   - *现状*：脚本通过 `acquire_lock` 杜绝多进程竞争同一 GPU/CPU 任务；若 `--out` 目录残留其他批次且未在当前账本中的文件，脚本在行 164 会主动抛出 `RuntimeError` 拒绝写入。
   - *评估*：这是强有力的防御性设计，防止脏文件混入特征库。

---

## 5. 综合结论与验收建议

- **综合结论**：**成立（Pass）**
- **验收建议**：`src/ainerzero/v9/experiments/s5/extract_teachers.py` 完全满足 P231 任务卡片及 S5 设计稿要求。所有 13 项契约测试在纯 CPU 下毫秒级通过，原有 B1–B10 变异与复核设计的 C1–C4 变异均被有效拦截，预处理逻辑与前期摸底高度自洽，建议验收通过。
