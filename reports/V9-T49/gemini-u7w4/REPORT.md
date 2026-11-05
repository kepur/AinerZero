# ainerzero.V9.T49 执行报告：T10/T12 教师权重与代码受控下载

- **任务编号**：`ainerzero.V9.T49`
- **执行代理**：`gemini-u7w4`（二级执行层，kind: gemini）
- **类型**：code（官方权重与代码受控下载，不装包、不运行）
- **文件范围**：`envs/teachers/t10/`、`envs/teachers/t12/`、`reports/V9-T49/`
- **规则遵守**：
  1. **单流限速 ≤ 2 MiB/s**：全程严格单流下载，速率受控（实测平均 0.87 ~ 1.91 MiB/s，绝不超限）；
  2. **零环境污染**：未 pip/conda 安装任何包，完全不动 `envs/teachers/.venv-t6`，不动 `runs.db` 与 `m0-worker.lock`；
  3. **零模型运行**：仅下载权重并校验 SHA256，未加载或执行任何模型；
  4. **磁盘余量充裕**：下载前磁盘余量 3.4 TiB，下载后余量 3.4 TiB，增量 4.93 GB，完全在预算内。

---

## 1. 权重下载与 SHA256 校验结果

所有权重文件均通过 Hugging Face 官方直链（绑定固定 commit）以单流限速下载，下载完成后当场比对官方 LFS OID / SHA256，全部 100% 一致：

| 目标模型 | 本地落盘路径 | 来源 Commit | 文件字节数 (B) | 预期 / 实测 SHA256 (LFS OID) | 用时 (s) | 平均速率 | 校验状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SAM 2.1 Tiny** | `envs/teachers/t10/weights/sam2.1-hiera-tiny/model.safetensors` | `de431c4...` | 155,908,064 | `48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7` | 171.48s | 0.87 MiB/s | **逐位吻合 (OK)** |
| **BootsTAPIR v2** | `envs/teachers/t10/weights/tapnet/bootstapir_checkpoint_v2.pt` | `5d3fb48...` | 218,886,140 | `8493c7a69e02c85b9382fbb3c7b8b539b36bc08ede744b9e99feb739a0129f4b` | 112.77s | 1.85 MiB/s | **逐位吻合 (OK)** |
| **MapAnything Apache** | `envs/teachers/t12/weights/map-anything-apache/model.safetensors` | `00f9c24...` | 4,914,062,480 | `fa06c0fdccefc5048e072c85935d5789b1e36b307f3859033c17f9dcb9fd5201` | 2455.68s | 1.91 MiB/s | **逐位吻合 (OK)** |
| **合计** | **3 份权重** | — | **5,288,856,684** (约 4.93 GB) | — | **2742.5s** (45.7m) | — | **全部通过** |

---

## 2. 官方代码仓库检出与状态核验

代码均采用 `git clone --filter=blob:none` 并检出到指定 commit，状态经 `git status --porcelain` 检查完全干净：

| 仓库名称 | 本地目录 | 目标 Commit | 实际 HEAD Commit | Tree SHA | 工作区状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **sam2** | `envs/teachers/t10/src/sam2` | `2b90b9f5ceec907a1c18123530e92e794ad901a4` | `2b90b9f5ceec907a1c18123530e92e794ad901a4` | `64becbca23f880e0056449377496da248a74da43` | **Clean (干净)** |
| **tapnet** | `envs/teachers/t10/src/tapnet` | `730cda1c730877cfedbe01bf87fb1cadb78a565d` | `730cda1c730877cfedbe01bf87fb1cadb78a565d` | `a71c1320696a23e6c8cecf975991cccdcc76cdd8` | **Clean (干净)** |
| **map-anything** | `envs/teachers/t12/src/map-anything` | `3d10cf7a3016fc0f9bb13a071ee66c47b10be0d9` | `3d10cf7a3016fc0f9bb13a071ee66c47b10be0d9` | `453fce8a09dd67811f112a6c09bb946e7277d2a9` | **Clean (干净)** |

---

## 3. 许可凭证记录

已按规范在各教师根目录下写入完整的许可溯源元数据：
- `envs/teachers/t10/LICENSE.provenance.json`：包含 SAM 2.1 与 TAPNet 代码及权重的开源 Apache-2.0 来源、commit、大小与 SHA256；
- `envs/teachers/t12/LICENSE.provenance.json`：包含 MapAnything Apache 版代码与权重的开源 Apache-2.0 来源、commit、大小与 SHA256。

---

## 4. 产物清单与文件校验

- `reports/V9-T49/gemini-u7w4/REPORT.md`：本交付报告；
- `reports/V9-T49/gemini-u7w4/downloads.json`：下载细节与耗时指标记录；
- `reports/V9-T49/gemini-u7w4/downloader.py`：速率受控下载器源码；
- `reports/V9-T49/gemini-u7w4/download.log`：完整下载过程与周期心跳日志；
- `reports/V9-T49/gemini-u7w4/SHA256SUMS.txt`：报告目录文件校验单。
