# ainerzero.V9.T32 停止交接审计报告：T6 被阻塞前的 strict 加载与自有组停止证据

- **任务 ID**：`ainerzero.V9.T32`
- **任务标题**：【停止交接·CPU】补存T6被阻塞前的strict加载与自有组证据
- **执行者**：`gemini-7a2b`（前次 T6 持有人，对口领取）
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：audit · GPU：否（纯 CPU 审计与证据封存）
- **依据与约束**：
  - 用户 AGENTS 工作规则：所有真实模型工作复用现有 CLI、共享锁、中央 RunStore 和预算/资源守卫；
  - 统筹 Claude 指示（#614 stop_request / #618 change_request）：T6 因前置 T26 核心入口硬缺陷（缺失进程组父监督、未提供可执行适配器时在预算预留后抛异常、视图配额非累计等）已被置为 `[阻塞]`；
  - 范围限定：仅修改 `reports/V9-T32/`，严禁碰源码、严禁重启 T6 模型推理、严禁触碰用户其他服务。

---

## 一、T6 停止事实与协同确认

1. **收到停止请求**：
   - 收到消息 `#614 stop_request` 与 `#618 change_request`，统筹明确指出 T26 入口缺陷，已下发工单 T30（修复）与 T31（复核），并要求停止旧 T6 真实权重加载。
   - 接力台任务 `ainerzero.V9.T6` 已由统筹变更为 `[阻塞]` 状态。
2. **停止操作与进程清理**：
   - 收到指示后，立即停止了计划中的 `guarded_runner.py` 调度；
   - 未在生产中央 RunStore（`artifacts/v9/teachers/benchmark/runs.db`）创建新作业，未产生任何活跃秒数消耗；
   - 未获取或占用共享锁 `artifacts/locks/m0-worker.lock`；
   - 检查系统进程列表，无任何残余 worker 进程，自有进程组确认为空。

---

## 二、被阻塞前的 `strict=True` 权重加载与单视角探索证据

在 T6 收到 stop_request 之前，执行者针对 r2 打回原因（`strict=True` 外层包装器加载报错）进行了深入排查并完成了精确技术验证：

### 1. 原始报错根因分析
当使用 `DepthAnything3(model_name="da3-small")` 并执行 `load_state_dict(state, strict=True)` 时，PyTorch 抛出以下 6 个缺失键错误：
```
RuntimeError: Error(s) in loading state_dict for ExplicitPrecisionDA3:
    Missing key(s) in state_dict:
        "model.head.scratch.output_conv2_aux.1.2.weight",
        "model.head.scratch.output_conv2_aux.1.2.bias",
        "model.head.scratch.output_conv2_aux.2.2.weight",
        "model.head.scratch.output_conv2_aux.2.2.bias",
        "model.head.scratch.output_conv2_aux.3.2.weight",
        "model.head.scratch.output_conv2_aux.3.2.bias"
```
**根因定位**：
检查官方 HuggingFace safetensors 权重字典发现，在 `output_conv2_aux` 辅助头中：
- level 0 包含 `.0.weight/.bias` (Conv2d)、`.2.weight/.bias` (LayerNorm)、`.5.weight/.bias` (Conv2d)；
- level 1、2、3 仅包含 `.0.weight/.bias` 与 `.5.weight/.bias`，在 `.2` 位置无任何权重参数（在训练网络中 level 1..3 未施加 LayerNorm，而是无参数恒等映射 `nn.Identity()`）。
- `Depth-Anything-3` 源码中对所有 levels 均无差别构建了 `nn.LayerNorm`，导致 levels 1..3 产生了未在权重中出现的 6 个多余参数。

### 2. 精确对齐验证与 `strict=True` 匹配结果
将 levels 1..3 的位置 2 映射为 `nn.Identity()` 后，在 `.venv-t6` 环境中加载 `artifacts/teachers/da3/` 官方权重：
- **DA3-SMALL**：
  - 缺失键（Missing Keys）：`0`
  - 未知键（Unexpected Keys）：`0`
  - 返回结果：`<All keys matched successfully>`
- **DA3-BASE**：
  - 缺失键（Missing Keys）：`0`
  - 未知键（Unexpected Keys）：`0`
  - 返回结果：`<All keys matched successfully>`

### 3. 单视角探索测试记录（单帧探测）
在收到 stop_request 之前，曾使用单帧 fixture 图像（`reports/V9-T6/r2-calib-fixtures/t6-analytic-room-00/view-0/rgb.png`）进行了 MPS 管道单次调用测试：
- 图像尺寸：`280x210`
- 前向耗时：`2.7766s`
- 深度输出形状：`[1, 378, 504]`，数值范围 `[0.3049, 1.4643]`
- 位姿输出形状：`[1, 3, 4]`
- 测试完成后立即执行 `t.close()`，MPS 显存与模型引用彻底释放。

---

## 三、现场状态审计与事实边界

| 审计项目 | 状态 / 测量值 | 事实裁定 |
| :--- | :--- | :--- |
| **共享互斥锁 `m0-worker.lock`** | 未占用，`flock(LOCK_EX \| LOCK_NB)` 现测完全空闲 | **CLEAN (Zero Lock Hold)** |
| **生产中央台账 `runs.db`** | 本次会话新增写入 = 0，产生 active_seconds = 0.0s | **CLEAN (Zero DB Pollution)** |
| **残余进程监督** | `ps aux` 检索 `real_da3_worker` / `guarded_runner` 均无进程 | **CONFIRMED_EMPTY** |
| **DA3-SMALL 权重 SHA-256** | `364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf` | **BYTE_STABLE (137,248,940 B)** |
| **DA3-BASE 权重 SHA-256** | `e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5` | **BYTE_STABLE (541,518,028 B)** |

---

## 四、未验证项与风险披露（严格禁止假冒闭合）

依据指令，未实际完成的项严格如实披露为 **UNVERIFIED**：
1. **18 视图完整标定与噪声协方差登记**：**UNVERIFIED**。因 T26 入口被叫停，未启动完整 18 视图批量标定，未向生产系统登记噪声协方差矩阵。
2. **中央 RunStore 完成态登记**：**UNVERIFIED**。未在生产数据库产生 completed 状态的 T6 run。
3. **全局教师缓存写入**：**UNVERIFIED**。未向 `artifacts/v9/teachers/` 写入任何正式缓存。
4. **模型能力验收通过**：**UNVERIFIED**。本卡为停止审计交接，不代表亦不替代 T6 的能力门禁通过。
5. **任务后续走向**：T6 维持 `[阻塞]` 状态，待 T30 修复与 T31 复核通过后方由一级统筹恢复，不在本卡做任何恢复或重启尝试。

---

## 五、交接裁定

**裁定结论：STOPPED_COMPLIANT（停止合规，证据已封存）**
所有已有工作均已如实归档，进程彻底清理，生产资源零污染，停止指令已完整落实。
