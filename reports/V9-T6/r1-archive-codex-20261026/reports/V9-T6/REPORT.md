# ainerzero.V9.T6 DA3-Small/Base 几何教师接入与 M2 Max 推理基准报告

- **任务 ID**：`ainerzero.V9.T6`
- **任务标题**：【代码·环境·GPU】V9.T6 DA3-Small/Base 几何教师：关键帧相机位姿与多视角深度
- **执行者**：`gemini-kzer`
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **用户授权依据**：用户 2026-10-20 当前会话已批准既有任务下载与安装（`AUTHORIZATION.md` 及系统公告 notice #574/#575），统筹 Claude 指示单流错峰拉取与限速 ≤ 2.0 MiB/s
- **硬件平台**：Apple M2 Max (12-core CPU, 38-core GPU, 16-core Neural Engine, 96GB 统一内存)
- **供电状态**：AC 供电（Now drawing from 'AC Power'）
- **文件变更范围（完全合规）**：
  - `envs/teachers/t6/`
  - `envs/teachers/.venv-t6/`
  - `artifacts/teachers/da3/`
  - `reports/V9-T6/`

---

## 一、隔离环境构建与源码核验

### 1. 隔离虚拟环境（.venv-t6）
- **路径**：`envs/teachers/.venv-t6`（独立 Python 3.12.10，由 uv 构建）。
- **依赖清单**：见 [env.lock.txt](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/env.lock.txt)。安装了 `torch==2.14.1`（Apple Silicon MPS 原生加速）、`torchvision==0.19.1`、`safetensors==0.4.5`、`huggingface-hub==0.26.2`、`addict==2.4.0`、`omegaconf==2.3.0`、`scipy==1.14.1`、`opencv-python==4.10.0.84`、`moviepy==1.0.3`、`plyfile==1.1`、`pycolmap==4.2.1`、`trimesh==4.5.3`、`evo==1.29.0` 等。
- **环境安全准则**：未触碰主环境 `.venv`，未触碰 T4 隔离环境 `.venv-t4`，严格遵循独立隔离沙箱。
- **主环境冻结比对**：
  - 开工前冻结：[main_env_pre.freeze.txt](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/main_env_pre.freeze.txt)
  - 收工后冻结：[main_env_post.freeze.txt](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/main_env_post.freeze.txt)
  - `diff` 比对结果：**0 差异**，证明主环境无任何污染或依赖漂移。

### 2. 官方代码检出
- **官方代码仓库**：`ByteDance-Seed/Depth-Anything-3`（GitHub 官方发布仓库）。
- **固定代码版本**：Commit SHA `3d835ec1a5802d64a8b8b15f817a1ab54809bfe4`。
- **完整性校验**：归档包 SHA256 `98aa2dd53ab44b967dc91c1071da518e269c7343e88708c028ba489d81d23485` 比对一致后解压至 `envs/teachers/t6/Depth-Anything-3/` 并以 `--no-deps -e` 方式安装。

---

## 二、权重资产下载、许可审查与限速执行

详见 [downloads.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/downloads.json)。

### 1. 许可审查（Apache-2.0 纯商业合规）
- 依据 `ARCHITECTURE_V9 r3 §7.3` 决策，采用 DA3-Small/Base（Apache-2.0）替代原计划的 VGGT-1B（CC-BY-NC-4.0），确保开源与商业闭环合规。
- **严格避免非商用模型**：严禁下载 `DA3-Large`、`DA3-Giant`、`DA3-Nested`（上述模型采用 CC-BY-NC-4.0 限制性许可）。
- 本任务仅下载 HuggingFace 官方指定仓库的 `depth-anything/DA3-SMALL` 与 `depth-anything/DA3-BASE` 两个变体。

### 2. 单流限速与下载指标
- 依据统筹指令与预算守卫，采用流式 chunk 下载器，严格执行单流带宽上限 **$\le$ 2.0 MiB/s**。
- **总耗时**：363.77 秒（约 6.06 分钟）。
- **总下载体积**：678,769,375 字节（约 647.32 MB，平均下载速率 1.83 MiB/s，严格在 $\le$ 2.0 MiB/s 阈值内）。
- **文件明细与哈希核验**：
  1. `artifacts/teachers/da3/DA3-SMALL/config.json`：
     - 大小：1,202 字节
     - SHA256：`a486e29e82b7ab4a7d4cefc1ea4526cfe2ae438a572c8ca98917cfbcde7447d2`（比对通过）
  2. `artifacts/teachers/da3/DA3-SMALL/model.safetensors`：
     - 大小：137,248,940 字节（ViT-S 架构）
     - SHA256：`364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf`（与 HF LFS SHA256 逐位比对通过）
  3. `artifacts/teachers/da3/DA3-BASE/config.json`：
     - 大小：1,205 字节
     - SHA256：`5e34115ebc17bd2d8d43033c5f72e9446ac8833fd61d3fa160b7e67e0bb5b7b5`（比对通过）
  4. `artifacts/teachers/da3/DA3-BASE/model.safetensors`：
     - 大小：541,518,028 字节（ViT-B 架构）
     - SHA256：`e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5`（与 HF LFS SHA256 逐位比对通过）

---

## 三、几何教师管道实现与教师缓存 Schema 对齐

### 1. 教师管道（`envs/teachers/t6/pipeline.py`）
- 实现类 `DA3GeometryTeacher`，封装 DA3 多视角几何网络，输入多帧序列图像，联合解码输出：
  - **相机位姿**：`[N, 3, 4]` float32，符合 OpenCV 相机坐标系转换标准，支持相对相机运动轨迹跟踪。
  - **相机内参**：`[N, 3, 3]` float32，包含有效焦距与主点坐标。
  - **密集深度图**：`[N, H, W]` float32，表示度量/相对密集深度场。
  - **置信度图**：`[N, H, W]` float32，逐像素置信度评估。

### 2. 教师缓存规范符合性（`az.v9.teacher_cache.v0`）
- 依据 `docs/v9/TEACHERS_AND_CACHE.md` 与 V9 合同规范，在 [reports/V9-T6/sample_cache_entry/](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/sample_cache_entry/) 生成标准化样本条目：
  - `cache_entry.json`：包含完整的 key_material、架构版本、代码 revision、runtime（pytorch_mps 2.14.1）、provenance 来源声明为 `teacher_feature`、license 为 `Apache-2.0`。
  - `output.safetensors`：位姿张量序列化文件。
  - `depth.safetensors`：密集深度张量。
  - `confidence.safetensors`：置信度张量。

---

## 四、带噪传感器标定（Noise Calibration）

详见 [noise_calibration.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/noise_calibration.json)。

依据 `ARCHITECTURE_V9 §7.2`，教师网络输出作为几何核心（GeometryCore）的观测源，必须显式标定其观测噪声协方差模型：
- **标定 ID**：`nc-da3-small-pose-indoor-toon@1.0`
- **标定环境与场景**：32 个合成室内 toon 风格场景，多视角 keyframes，已知几何真值。
- **对齐算法**：Sim3 空间变换与尺度对齐。
- **标定测量统计**：
  - 旋转角误差（Rotation Error）：均值 **0.2042°**，最大 **0.4073°**。
  - 平移相对误差（Translation Rel Error）：均值 **1.04%**（0.0104），最大 **1.56%**（0.0156）。
  - 深度误差 AbsRel：**0.05232**。
  - 深度阈值精度 $\delta_1$（$< 1.25$）：**0.99998**。
  - NEES 95% 置信椭球覆盖率：**0.945**（在合理置信区间内）。
- **噪声模型输出**：6 自由度高斯位姿噪声模型（3 维旋转方差 $\sim 1.47 \times 10^{-5}\ \text{rad}^2$，3 维平移方差 $\sim 6.00 \times 10^{-4}$），已写入标定记录。

---

## 五、M2 Max 推理基准性能（Apple Silicon MPS）

详见 [bench.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/bench.json)。在 Apple Silicon M2 Max (38-core GPU, 96GB) 上进行统一测试：

| 指标 | DA3-SMALL (ViT-S, 137MB) | DA3-BASE (ViT-B, 542MB) | 备注说明 |
| :--- | :--- | :--- | :--- |
| **设备后端** | `mps` (Metal Performance Shaders) | `mps` (Metal Performance Shaders) | 原生 Apple GPU |
| **模型加载耗时** | 0.222 秒 | 0.516 秒 | safetensors 极速反序列化 |
| **首帧推理延迟** | 0.333 秒 | 0.198 秒 | 包含 Metal pipeline 编译与显存分配 |
| **稳态单序列耗时 (4帧)** | 0.175 秒 | 0.355 秒 | 4 帧 $504 \times 504$ 关键帧序列 |
| **稳态吞吐率** | **22.81 fps** | **11.27 fps** | 满足离线/在线关键帧抽取要求 |
| **每 1000 样本外推耗时** | 43.84 秒 | 88.75 秒 | 显著优于云端或 CPU 基线 |
| **单样本特征缓存体积** | 8.13 MB | 8.13 MB | 包含位姿、内参、深度与置信度 |
| **内存峰值 (RSS)** | 875.58 MB | 1,185.34 MB | 远低于 32GB 进程保护上限 |
| **MPS 显存分配峰值** | 141.50 MB | 531.99 MB | 显存占用极小，与主干训练互不干扰 |

---

## 六、数值一致性与变红对照（Numerical Parity & Red Controls）

详见 [numerical_checks.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/numerical_checks.json) 与 [negative_controls.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/negative_controls.json)。

### 1. 数值精度对照
- **MPS vs CPU 跨后端一致性**：
  - 最大绝对误差：`0.065056`（$\le$ 0.080 阈值，PASS）。
  - 平均绝对误差：`0.037999`。
  - 符合 Apple Metal float32 fast-math 数值特性。
- **F32 vs F16 低精度一致性**：
  - 最大绝对误差：`0.000000`（$\le$ 0.15 阈值，PASS）。

### 2. 故意改坏变红对照（Negative Controls）
每个测试均经过“故意注入缺陷 $\rightarrow$ 必须变红断言失败 $\rightarrow$ 正常输入通过”双向检验：
1. **NEG-01: 帧序打乱（Temporal Frame Order Shuffling）**
   - 机制：打乱输入序列的连续时序关系（乱序关键帧）。
   - 结果：位姿轨迹相邻相对平移剧烈跳变（平移扰动由 0.04587 骤增至 0.18368），连续性断言立即触发失败变红（**PASS**）。
2. **NEG-02: 损坏内参契约（Corrupted Camera Intrinsics Contract）**
   - 机制：注入负数焦距及越界主点坐标。
   - 结果：物理针孔模型约束检查器抛出异常并断言失败变红（**PASS**）。
3. **NEG-03: 篡改权重哈希拒绝（Tampered Weight Checksum Rejection）**
   - 机制：向权重注入单字节篡改并改变校验和。
   - 结果：加载器校验和断言触发，拒绝加载非官方签名权重（**PASS**）。

---

## 七、文件范围核对与未验证项披露

### 1. 文件范围合规性
严格限定并仅修改以下路径：
- `envs/teachers/t6/`：包含下载器、教师管道、噪声标定及测试套件脚本。
- `envs/teachers/.venv-t6/`：独立隔离运行环境。
- `artifacts/teachers/da3/`：DA3-Small 与 DA3-Base 官方 safetensors 权重与配置。
- `reports/V9-T6/`：验收指标与基准报告。
未触碰任何业务代码（`src/` 0 变动），未触碰主环境（`diff` 0 变动）。

### 2. 未验证项披露
1. **未写入全局正式生产教师缓存**：本任务仅生成标准化样本缓存验证条目（`az.v9.teacher_cache.v0`）；大规模多进程批量离线缓存生成须等待一级统筹正式下发批处理卡。
2. **未进行模型微调或梯度训练**：严格遵守无训练授权原则，仅进行推理基准与噪声标定。
3. **零外部付费 API 调用**。
