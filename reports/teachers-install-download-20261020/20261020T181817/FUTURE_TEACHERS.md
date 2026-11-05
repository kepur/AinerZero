# 后续教师官方准备清单（仅元数据，不下载权重）
读取时间 2026-10-20；精确 revision、字节、权重 SHA256 见 future-teachers-official-manifest.json，保存的官方 API 响应可复核。

| 卡 | 精确型号 / 原生文件 | 权重传输字节 | 许可 | 建议 |
|---|---|---:|---|---|
| T6 | DA3-SMALL / model.safetensors | 137,248,940 | Apache-2.0 | 先 Small；Base 留到 Small 消费与 MPS 可行性明确后 |
| T6 | DA3-BASE / model.safetensors | 541,518,028 | Apache-2.0 | 独立第二批，不装 Large/Giant/Nested |
| T10 | SAM 2.1 Hiera Tiny / sam2.1_hiera_tiny.pt | 156,008,466 | Apache-2.0 | 只选原生 .pt 与 YAML，不同时下 Transformers safetensors 副本 |
| T10 | BootsTAPIR / bootstapir_checkpoint_v2.pt | 218,886,140 | Apache-2.0 | 适合先做 PyTorch 点跟踪；原始 TAPIR 更小为 124,348,474 bytes |
| T10 | TAPNext / bootstapnext_ckpt.npz | 776,980,182 | Apache-2.0 | 默认 JAX 路线；不能声称免 JAX |
| T10 | TAPNext++ / tapnextpp_ckpt.pt | 2,532,282,370 | Apache-2.0 | 单权重已超过 T4 原 2GB，独立预算 |
| T12 | map-anything-apache / model.safetensors | 4,914,062,480 | Apache-2.0 | 未找到该 Apache 型号的小号变体；单独大流量批次 |

依赖与源码：
- DA3 官方 commit 3d835ec1a5802d64a8b8b15f817a1ab54809bfe4。pyproject 要求 torch>=2、torchvision、numpy<2，且默认包含 xformers/open3d/pycolmap 等；不能直接宣称完整默认安装可在 M2/MPS 使用。下一张环境卡先冻结最小推理依赖与精确软件锁，明确是否需要上游可选化，禁止静默绕过依赖。
- SAM2 官方 commit 2b90b9f5ceec907a1c18123530e92e794ad901a4。要求 torch>=2.5.1、torchvision>=0.20.1、hydra-core/iopath/numpy/Pillow/tqdm。安装默认尝试 CUDA 扩展；Apple Silicon 应按官方 SAM2_BUILD_CUDA=0 路线单独核验，MPS 数值正确性待运行卡。
- TAPNet 官方 commit 730cda1c730877cfedbe01bf87fb1cadb78a565d。当前 README 的 License and Disclaimer 明确列出所有相关检查点为 Apache-2.0，HF 官方 google/tapnet 也为 apache-2.0。默认 pyproject 无条件拉 JAX/chex/haiku 等，torch 是 extra；不能用 pip install .[torch] 声称只有 PyTorch。须另冻结 PyTorch-only 路线，不在本轮安装。
- MapAnything 官方 commit 3d10cf7a3016fc0f9bb13a071ee66c47b10be0d9。pyproject 有 uniception==0.1.7、opencv-python-headless==4.10.0.84、rerun-sdk~=0.24.1/hydra 等；torch 依赖链与 MPS 算子尚需专门环境锁，不装 all，也不额外下载统一接口所列外部教师。
- PyPI 官方 torch 当前 2.14.1 的本机 Python 3.12 arm64 wheel 为 127,307,099 bytes，SHA256 420dbf314c180ee4b86e9bc00aee5746a7d6e5bacdd7df925af671ed393f0b2e。此为单 wheel，不是完整 PyTorch/torchvision 依赖预算；完整传输量尚未知，不能宣称后续环境预算闭合。

T6/T10/T12 的小型号权重与元数据字节已知，但完整源码压缩包与所有软件依赖传输量未冻结，不能据此发布“全部安装只需这些字节”。分期建议：T4 准备完成 → T6 Small 最小环境预检 → SAM2 Tiny → BootsTAPIR → 需要时 DA3 Base；MapAnything 与 TAPNext++ 另批。每批保持一个总下载流、50GiB 磁盘守卫、模型限速 2MiB/s；本报告不构成推理/训练预算。

官方页面：[DA3 Small](https://huggingface.co/depth-anything/DA3-SMALL)、[DA3 Base](https://huggingface.co/depth-anything/DA3-BASE)、[SAM2 Tiny](https://huggingface.co/facebook/sam2.1-hiera-tiny)、[TAPNet](https://github.com/google-deepmind/tapnet)、[TAPNet 权重](https://huggingface.co/google/tapnet)、[MapAnything Apache](https://huggingface.co/facebook/map-anything-apache)。
