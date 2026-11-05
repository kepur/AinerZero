# ainerzero.V9.T47 官方元数据与字节清单报告：T10/T12 教师选型

- **任务编号**：`ainerzero.V9.T47`
- **执行代理**：`gemini-u7w4`（二级执行层，kind: gemini）
- **类型**：research（教师接入元数据与字节清单，**绝不下载**）
- **依据与文件范围**：`reports/V9-TPREP/gemini-u7w4/`
- **合规声明**：全程**零下载模型权重、零 pip/conda 安装、零修改隔离环境、零 GPU/模型调用**；所有元数据均通过官方 GitHub / Hugging Face REST API 获取并交叉比对。

---

## 1. 核心结论与推荐总览（≤10 行）

1. **T10 对象掩码（SAM 2.1）**：代码与权重均为 **Apache-2.0**（**可用**）。首选推荐 **`sam2.1-hiera-tiny`**（148.69 MB safetensors），显存与算力极省，M2 Max 吞吐极佳；`sam2.1-hiera-small`（175.77 MB）为精细备选。
2. **T10 点跟踪（TAPNet / BootsTAPIR / TAPNext）**：官方 README 明确授权所有预训练检查点均为 **Apache-2.0**（**可用**）。首选推荐 **`bootstapir_checkpoint_v2.pt`**（208.75 MB），原生 PyTorch 权重，免装 JAX，推理开销适中；备选在线因果版（208.75 MB）与长时跟踪 TAPNext++（2.36 GB）。
3. **T12 米制重建（MapAnything）**：存在两类变体，官方 **`facebook/map-anything-apache`** 权重采用 **Apache-2.0**（**可用**，4.58 GB），排除了非商用学术数据；而基础版 `facebook/map-anything` 为 **CC-BY-NC-4.0**（**不可用**，含 NC 限制）。
4. **推荐组合磁盘预算**：Tiny (149 MB) + BootsTAPIR (209 MB) + MapAnything Apache (4.58 GB) = **~4.94 GB**（约 5.29 GB 物理落盘），远低于 16 GB 重型上限。
5. **环境兼容性**：现有 `envs/teachers/.venv-t6`（torch 2.14.1, numpy 2.5.4, einops 0.8.2, safetensors, pycolmap, trimesh）与推荐选型核心依赖完全兼容；全部支持 Apple MPS 硬件加速。

---

## 2. 教师元数据与字节清单明细

### 2.1 T10 对象掩码教师：SAM 2.1

- **官方仓库**：[facebookresearch/sam2](https://github.com/facebookresearch/sam2)（commit `2b90b9f5ceec907a1c18123530e92e794ad901a4`，main 分支）
- **代码许可**：`Apache-2.0`（[LICENSE](https://github.com/facebookresearch/sam2/blob/main/LICENSE)）
- **权重许可**：`Apache-2.0`（Hugging Face 官方 Model Card 标明 `license: apache-2.0`，Meta 官方全量开源商用可）
- **许可状态**：**可用**（符合 Apache-2.0 规则）
- **检查点清单**：
  | 检查点名称 | 格式 | 字节数 (bytes) | 体积 (MB) | 官方 Hugging Face LFS OID (SHA256) | 推荐状态 |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | **sam2.1-hiera-tiny** | `model.safetensors` | 155,908,064 | 148.69 MB | `48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7` | **强烈推荐（首选）** |
  | sam2.1-hiera-tiny | `sam2.1_hiera_tiny.pt` | 156,008,466 | 148.78 MB | `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69` | 备用权重 |
  | **sam2.1-hiera-small**| `model.safetensors` | 184,305,280 | 175.77 MB | `0a4067b11ce1e23d5229203f11c718a823060d15a4b23fa2372a7d4b77cbbc60` | **备选（高精细度）** |
  | sam2.1-hiera-small| `sam2.1_hiera_small.pt` | 184,416,285 | 175.87 MB | `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38` | 备用权重 |
- **依赖与 Apple MPS**：
  - 核心依赖：`torch>=2.3.1`, `torchvision>=0.18.1`, `pillow`, `safetensors`。
  - Apple MPS 支持：**支持**（支持 MPS 前向推理生成掩码）。
  - `.venv-t6` 兼容性：`torch==2.14.1`、`torchvision==0.29.1`、`pillow==13.0.0` 均已具备，可直接适配纯 PyTorch 或 safetensors 加载。

---

### 2.2 T10 点跟踪教师：TAPNet / BootsTAPIR / TAPNext

- **官方仓库**：[google-deepmind/tapnet](https://github.com/google-deepmind/tapnet)（commit `730cda1c730877cfedbe01bf87fb1cadb78a565d`，main 分支）
- **代码许可**：`Apache-2.0`（[LICENSE](https://github.com/google-deepmind/tapnet/blob/main/LICENSE)）
- **权重许可审查**：
  > 官方 README `## License and Disclaimer` 原文：
  > *"All pre-trained model checkpoints released in this repository and linked from this README (including TAP-Net, TAPIR, BootsTAPIR, TAPNext, TAPNext++, and TRAJAN weights) are also licensed under Apache 2.0."*
- **许可状态**：**可用**（明确属于 Apache-2.0）
- **检查点清单（优先 PyTorch 格式）**：
  | 检查点模型 | 权重文件 | 字节数 (bytes) | 体积 | 官方 Hugging Face LFS OID (SHA256) | 推荐状态 |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | **BootsTAPIR** | `bootstapir_checkpoint_v2.pt` | 218,886,140 | 208.75 MB | `8493c7a69e02c85b9382fbb3c7b8b539b36bc08ede744b9e99feb739a0129f4b` | **强烈推荐（首选）** |
  | Online BootsTAPIR | `causal_bootstapir_checkpoint.pt` | 218,887,028 | 208.75 MB | `87c1e752cf5ce56e3e2f7da460aeb4d40fc826d04ef2939bade86a5c7495377f` | 备选（在线因果） |
  | TAPNext | `bootstapnext.pth` | 978,292,409 | 932.97 MB | `425eeff19437554a74742e1a9e1077dd1059248ecdd77a84c689ea2847fa80a4` | 备选（较高精度） |
  | TAPNext++ | `tapnextpp_ckpt.pt` | 2,532,282,370 | 2.36 GB | `cb96a43444ccb4fbdb25d800b88c7ba196179a526e78f01b021a16b1c1eff6da` | 备选（超长时跟踪） |
- **依赖与 Apple MPS**：
  - 核心依赖：`torch>=2.0.0`, `numpy`, `scipy`, `einops`, `pillow`。
  - Apple MPS 支持：**支持**（PyTorch 权重基于纯 PyTorch 通用算子，完全支持 MPS / CPU 加速）。
  - `.venv-t6` 兼容性：`torch==2.14.1`、`numpy==2.5.4`、`scipy==1.18.1`、`einops==0.8.2` 已全部安装就绪；选择 PyTorch 检查点彻底免除了 JAX/XLA 的环境污染风险。

---

### 2.3 T12 米制重建教师：MapAnything（Apache 变体审查）

- **官方仓库**：[facebookresearch/map-anything](https://github.com/facebookresearch/map-anything)（commit `3d10cf7a3016fc0f9bb13a071ee66c47b10be0d9`，main 分支）
- **代码许可**：`Apache-2.0`（[LICENSE](https://github.com/facebookresearch/map-anything/blob/main/LICENSE)）
- **变体对比与许可审查**：
  - **`facebook/map-anything-apache`（Apache 变体）**：
    - 权重协议：`Apache-2.0`
    - 许可状态：**可用**（允许商用与开源整合）
    - 训练数据：官方从训练集剥离了所有非商用数据集，保证全链路协议合规。
    - 检查点：`model.safetensors`，字节数 **4,914,062,480**（4.58 GB），LFS OID `fa06c0fdccefc5048e072c85935d5789b1e36b307f3859033c17f9dcb9fd5201`。
    - 推荐状态：**强烈推荐（唯一合规选项）**。
  - **`facebook/map-anything`（标准学术版）**：
    - 权重协议：`CC-BY-NC-4.0`（非商业用途限制）
    - 许可状态：**不可用**（根据项目规则，带 NC 的标记为不可用）
    - 训练数据：包含学术限制非商用数据集。
    - 检查点：`model.safetensors`，字节数 **4,914,062,480**（4.58 GB），LFS OID `981f060c64664dff3272b5f5a823d350abe71a2f144444db4cfc325f3ed5a3a0`。
- **依赖与 Apple MPS**：
  - 核心依赖：`torch`, `torchvision`, `safetensors`, `huggingface_hub`, `einops`, `pycolmap`, `trimesh`, `scipy`, `opencv-python`。
  - Apple MPS 支持：**支持**（纯 Transformer 端到端架构，完全支持在 Apple MPS 与 CPU 上进行单帧与多视图三维重建前向）。
  - `.venv-t6` 兼容性：`envs/teachers/.venv-t6` 已预装 `torch==2.14.1`、`safetensors==0.8.0`、`huggingface_hub==2.3.0`、`einops==0.8.2`、`pycolmap==4.2.1`、`trimesh==5.2.0` 等全部核心包，环境 100% 匹配。

---

## 3. 推荐选型组合与磁盘预算汇总

| 类别 | 教师选型 | 推荐检查点文件 | 权重许可 | 磁盘字节数 (bytes) | 估算体积 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **T10 掩码** | SAM 2.1 | `facebook/sam2.1-hiera-tiny/model.safetensors` | Apache-2.0 (可用) | 155,908,064 | 148.69 MB |
| **T10 点跟踪** | BootsTAPIR | `google/tapnet/bootstapir_checkpoint_v2.pt` | Apache-2.0 (可用) | 218,886,140 | 208.75 MB |
| **T12 几何重建**| MapAnything Apache | `facebook/map-anything-apache/model.safetensors` | Apache-2.0 (可用) | 4,914,062,480 | 4.58 GB |
| **合计** | **推荐黄金组合** | **3 个检查点文件** | **全部 Apache-2.0** | **5,288,856,684** | **~4.93 GB** |

> **预算评估**：推荐组合总计约 4.93 GB，完全在 16 GB 轻量教师限制之内，在 M2 Max 机器上部署与缓存毫无存储压力。

---

## 4. 关键风险点与防范建议

1. **MapAnything 变体防混淆**：
   - 官方同时存在 `facebook/map-anything`（CC-BY-NC 4.0）与 `facebook/map-anything-apache`（Apache 2.0）。必须严格通过 URL / Hugging Face Repo ID 锁定为 `facebook/map-anything-apache`（OID `fa06c0fd...`），严防拉取 NC 污染模型。
2. **TAPNet 避免引入 JAX 栈**：
   - TAPNet 原生论文基于 JAX，但官方提供了完整的 PyTorch 检查点（如 `bootstapir_checkpoint_v2.pt`）。必须选用 PyTorch 格式检查点，直接利用 `.venv-t6` 的现有 torch 2.14.1，严禁引入 JAX/Flax，避免 macOS 上的编译兼容风险。
3. **严格遵守下载闸门**：
   - 本卡仅完成官方元数据与字节清单登记；实际下载部署必须待后续 T 轨道任务由统筹与用户明确批准预算后，走指定隔离脚本实施。

---

## 5. 交付产物

- [`MANIFEST.json`](MANIFEST.json)：机器可读的结构化官方元数据、字节数、SHA256 与依赖表。
- [`REPORT.md`](REPORT.md)：本选型研究报告。
- [`SHA256SUMS.txt`](SHA256SUMS.txt)：交付文件的完整校验码。
