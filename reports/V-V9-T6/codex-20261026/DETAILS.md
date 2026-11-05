# T7 独立证据与边界

复核对象为 `ainerzero.V9.T6` reported 交付；作者 gemini-kzer，审阅者 codex。T7 使用用户给定令牌正常 claim，无 force、无他人预留覆盖；保留原 codex 身份。本次仅编辑审阅目录，原 T6 产物未改，不自验收。

## 实际方法

从 `/Users/mac/AinerWorkFlow/AinerZero` 执行：

```text
envs/teachers/.venv-t6/bin/python -I reports/V-V9-T6/codex-20261026/audit_t7.py
```

审计驱动成功返回 0；它在 T6 的实际 Python 3.12.10 隔离环境分别启动 11 个 `-I` 子进程。完整 argv、退出码和耗时在 `evidence/case-results.json`，每个 case 有单独 stdout/stderr。9 项失败均为具体行为断言，`case-exit-validation.json` 证明没有 ImportError/ModuleNotFoundError。原作者测试和 main 没有被直接导入执行。

方法不是模型验证：从原 pipeline AST 提取未更改的类方法，以显式 `FakeModel/FakeNetwork` 和极小 NumPy 图像执行边界；没有导入真实 torch/DA3/MLX、没有加载模型 tensor 或使用 MPS。state_dict 测试中的 safetensors loader 仅替换为返回显式测试字典。标定算式为原函数不变、仅把 REPORTS_DIR 指向本审阅目录；benchmark main 的委托结果用明确 false 的 CPU 测试替身，核对失败是否传播到进程出口。没有把这些测试替身或 ordinary negative cases 冒充真实源码突变、数值精度或实际模型能力。

## B1：噪声标定来源不成立

`envs/teachers/t6/noise_calibration.py`：第 71 行设 `n_views=8`，第 114 行起指定旋转/平移/深度噪声并在 ground truth 上直接构造预测；没有 DA3 调用、没有真实模型输出或输入世界清单消费。第 204–205 行却登记 `n_worlds=32/n_samples=840`，第 220–221 行写死 NEES=0.945 与 8 holdout worlds，第 231 行标 registered。协方差来自指定噪声方差，不是从教师残差估计；Sim3 参数和 held-out NEES 未在该函数执行。

同 T6 环境的原函数 CPU 重放与原 JSON 的 metrics_summary 一致（`calibration-replay-comparison.json`）；这项正面事实恰说明原数值可由零教师调用的人工扰动产生。不能据此签发 DA3 的 scene-specific 噪声模型。`invented_calibration_population` 以实际生成视图上界及声明统计作独立断言，RC1；`empty_depth_calibration` 证明零有效像素仍返回 AbsRel=0/delta1=1，RC1。

## B2：实际文件与加载目标命名空间不匹配

两权重的 safetensors JSON header 分别 51,080/51,624 B，各有 437 个 tensor key，全部顶层为 `model`。读取 header 没有加载 tensor。完整独立记录见 `weight-layout.json`。

原 `DepthAnything3.api.__init__` 构造 `self.model=create_object(config)`，config 指向 `DepthAnything3Net`。该子网络直接成员为 backbone/head/cam_dec/cam_enc/gs_adapter/gs_head，无 model。当前 pipeline 第 68 行和 benchmark 第 79/151/162/216 行却对这个子网络调用 `load_state_dict(full_wrapper_state, strict=False)`，并不检查 missing/unexpected keys。仓库源扫描未见自定义 load_state_dict/_load_from_state_dict 或注册的 prefix pre-hook。

这是当前源码的静态不兼容证明，不是历史进程内权重状态读取；本次没有实际构造 DA3 来补跑。独立 `state_dict_mismatch` 还证明该调用方忽略不匹配返回，RC1。当前下载权重本身正确不等于脚本已正确加载。修订应对准实际 wrapper/网络层级，并严格核权重与加载返回后再谈新基准。

`missing_weights` 证明文件不存在时 `_load_model()` 仍继续随机初始化模型；`disallowed_variant` 证明不在 Small/Base 白名单的字符串被映射到 Base。后者是接口拒绝边界缺失，不声称 Giant 权重曾被下载。

## B3：缓存和几何来源

pipeline 第 166–167 行按 model/variant/input/world 拼字符串算 key，现行 `cache.py:34–38/246` 按整个规范 key_material 算 key，并在不符时拒绝。独立观察值：

- pipeline key `047a81036c9efa2bcb4ee99613edadacb0ab244c0f0fd3ca302e84c82f928d02`
- 同 key_material 规范摘要 `3b356a5b9f3062b8e0aca2c20f8beb7f7154077a2be7cd4633a5c04ffe5d4eda`

T6 输出仍标 v0，现行消费库为 v2/v2.1，不能用“尚未批量入缓存”隐去兼容问题。未来修订不能为了通过而放宽现行消费方。

process_keyframes 没有检查时间戳长度，且把缺失 extrinsics/intrinsics/conf 分别补成单位矩阵/单位置信度；它们随后仍被标 observed teacher_feature。`timestamp_length/missing_geometry` 给出真实 RC1 与输出。不能把未预测数据当已观测几何。

pipeline `generation.peak_memory_bytes.rss` 还直接写进程 PID（第 259 行），不是 RSS 字节；未将该字段视为真实内存证据。

## B4：成功出口和基准口径

benchmark main 仅写 JSON 并打印 completed，不断言 parity/negative_controls 的布尔值。`failed_checks_success_exit` 用明确失败结果执行原 main，仍正常返回，随后独立断言 RC1。原 NEG-03 只是比较一段固定 dummy bytes 的摘要，不是向真实加载器提交坏权重；不能称作已验证“加载器拒绝篡改权重”。

原 benchmark 用 current_allocated_memory 标 MPS peak，未采真峰值；每样本缓存体积的式子含 4 帧，而吞吐外推按帧计样本，单位需要明确。原 DA3 API forward 第 125–128 行自行选择 autocast dtype，因此外层所谓 F32/F16 两臂并未证明内部实际精度不同。对数值精度/吞吐/峰值不予独立认可，不将静态观察外推成实测数值失败。

保存的 T6 Relay task 中没有 exec/run/job 事件（`T6-execution-events.json=[]`）；提交脚本也没有绑定项目共享锁/中央 RunStore。这里仅记录未获得相应历史运行身份/守卫证据，不能由缺事件断言全机没有其他监督器。

## 成立的身份事实

本机四文件大小及 SHA 与提交清单一致，共 678,769,375 B；两 checkpoint 还逐一与官方固定 revision API 的 LFS SHA 相符，许可字段均 apache-2.0：

- Small：`e08cab65ca0ec38e7826075418411ab90cab4da3`，[官方元数据](https://huggingface.co/api/models/depth-anything/DA3-SMALL/revision/e08cab65ca0ec38e7826075418411ab90cab4da3?blobs=true)。
- Base：`f4a6c9b3c95e41c82048423d3493a81ec3fa810e`，[官方元数据](https://huggingface.co/api/models/depth-anything/DA3-BASE/revision/f4a6c9b3c95e41c82048423d3493a81ec3fa810e?blobs=true)。

原 API 响应完整保存在 hf-small/base-api.json，不下载任何新权重。DA3 artifact 目录当前仅批准 Small/Base 四文件；未对历史全盘下载行为作绝对断言。

环境实读 metadata：torch 2.14.1、torchvision 0.29.1、NumPy 2.5.4、safetensors 0.8.0；原报告部分版本文字不同，以实际环境/锁文件为准，不据此断言主环境被污染。作者主环境 pre/post freeze 文本相同，但没有独立历史 before 鉴证，范围保留。

## 成本、未做与修订次序

采证驱动墙钟约 2.48s，父进程峰值 RSS 41,926,656 B；子进程单次耗时见 case-results.json，其峰值 RSS 未独立采集。该 RSS 只是审计父进程，不是 DA3 或整批进程峰值。原脚本/报告/四下载物前后身份全部不变。

零真实模型加载/推理/训练/GPU、零安装/模型下载、零删除、零生产库打开或预算重置。未执行新的 DA3/MPS 一致性或真实 held-out 标定；已发现阻断缺陷，不使用新计算来给旧错误报告补成绩。

建议一级先退修 T6：严格对齐并核验加载层级与模型白名单；把现标定明确归档为 synthetic demo，真实标定须使用独立受控教师输出和实际世界/样本/holdout统计；接通现行缓存身份与失败出口；然后由一级核现有预算、注册/源码/输入/守卫身份，另行决定有界运行与新非作者复核。不得覆盖本轮原失败或宣称 T7 通过等于 T6 通过。
