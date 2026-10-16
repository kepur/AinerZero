# AinerZero — M2 Max 96GB 无 CUDA 集成与训练降本方案

日期：2026-10-16。状态：架构规划，未在目标机器实测。

## 核心结论

采用离线教师 + 特征缓存 + 原生 MLX 小型世界状态预测器 + Blender 仿真真值。不要全量移植 CUDA 项目，也不要把每个教师都常驻内存。

## 组件矩阵

| 项目 | 本地策略 | 用途 | 优先级 |
|---|---|---|---|
| V-JEPA 2.1 | 社区 MLX | 视频潜在特征教师 | P0 |
| V-JEPA2-AC | 社区 MLX | 动作条件预测参考 | P0 |
| Depth Anything V2 Small | Apple Core ML | 快速深度教师 | P0 |
| VGGT-1B | 社区 PyTorch MPS | 相机、深度、点云教师 | P0 |
| WorldJEPA | MPS / 算法重写 | 冻结编码器、SIGReg、损失 | P1 |
| Depth Anything 3 | 验证 MPS | 后续精度升级 | P1 |
| Blender | macOS 原生 | 合成真值、物理仿真 | P0 |
| BlenderWorld | 移植任务格式和确定性评测 | 验证可编辑场景 | P1 |
| WorldForge | 移植投影/重投影/warp 算法 | 相机轨迹控制 | P1 |
| Gaussian Splatting | Metal 可视化优先 | 3D/4D 显示 | P2 |
| Hunyuan3D | 社区 MPS，单独服务 | 资产生成，不默认做训练教师 | P2 |
| Cosmos | 不部署 | 参考训练方法 | P3 |

## 运行模式

- Teacher Mode：教师模型单独运行，写入离线缓存。保存模型版本、坐标系、时间戳、置信度。
- Train Mode：仅 MLX AinerZero 预测器及缓存常驻，避免 MPS/MLX 内存争用。
- World Mode：轻量编码器 + AinerZero + Blender/视频后端，按需加载几何教师。

## 模块分工

1. 输入层：真实视频、图像、Blender 程序化仿真、动作事件。
2. 视觉编码：V-JEPA2.1；Depth Anything V2 输出相对深度；VGGT 估计相机及多视角几何。
3. 对象融合：对象关联、坐标规范化、遮挡状态、状态不确定性。
4. 核心预测：MLX 原生小型 action-conditioned dynamics model，状态 z(t+1)=f(z(t),a(t),memory)。
5. 外部记忆：场景图、事件日志、持久对象 ID、快照。
6. 输出：Blender 可编辑场景、物理仿真、LTX 视觉合成。
7. 评测：BlenderWorld 部分任务 + 多步预测误差 + 遮挡身份保持 + 物理约束。

## 分阶段实施

### 第 0 阶段：1 周
建立隔离环境、版本锁定、模型加载与数值一致性测试。测试 M2 Max 上的内存峰值、首帧延迟、吞吐。

### 第 1 阶段：1–2 周
运行 V-JEPA2.1 MLX、Depth Anything V2 Core ML；VGGT 仅对关键帧批处理。建立缓存 schema，避免重复推理。

### 第 2 阶段：2–4 周
Blender 生成刚体运动、碰撞、遮挡和相机运动数据。每个样本保存真值状态和对应视觉特征。训练 5M–30M 参数的预测器原型，进行 1/5/10/30 步评测。

### 第 3 阶段：2–4 周
加入动作条件和长期记忆，V-JEPA2-AC 作教师/参考；测试特征蒸馏和预测一致性。与纯状态监督、纯视觉监督比较。

### 第 4 阶段：3–6 周
WorldForge 几何 warp，BlenderWorld 小型任务集，LTX 后端可视化。先评估效果，再考虑移植更复杂的 Metal 算子。

## 训练成本预算（情景估计，不是实测）

基线 A：从零训练完整视觉基础模型和世界预测器，训练计算设为 100 单位。冻结预训练视觉编码器、只训练小型预测器，训练计算可在假设下降到 1–10 单位，即减少约 90–99%。这一比较不是同等能力保证，也未计教师推理、数据生成、评测、开发成本。

基线 B：已有预训练编码器，只训练同规模预测器。离线缓存减少重复教师推理；总计算节省取决于 epoch 数、教师成本和缓存读取，粗略预算 0–60%，需测量。

示例：教师特征提取 20 GPU 小时等价计算，预测器每轮 1 小时，训练 50 轮。若每轮重跑教师则 50*(20+1)=1050 单位；缓存后 20+50=70 单位，理论计算节省 93.3%。但这是极端例子，且两种流程训练质量、I/O、设备利用率未必相同。

另一示例：教师只占每轮 0.1 小时、预测器每轮 1 小时，50 轮则 55 vs 50.1，节省 8.9%。

成本总额 = 电力 + 设备折旧 + 教师推理 + 模型训练 + 渲染 + 开发人工 + 存储。已有 M2 Max 上无需新增 GPU 采购，但不意味着训练成本为零。

## 量化验收

- 预训练教师数值正确、运行不崩溃；缓存重跑哈希与版本可复现。
- 1/5/10/30 步位置、姿态、速度预测误差，碰撞事件 F1，物体 ID switch 次数。
- 以恒速度/物理解析/Blender 真值/冻结 JEPA 特征为基线做消融。
- 每千个样本教师推理时间、缓存大小、训练每轮耗时、峰值内存、能耗。
- 同质量阈值下计算训练成本节省，不只比较训练时长。

## 风险

- 社区 MLX/MPS 代码未必覆盖全部模型结构，需对齐官方权重与预处理。
- VGGT/Depth Anything 估计的几何和尺度存在歧义，不能视为绝对真值。
- 机器人动作条件模型不等于通用物理预测器。
- 教师蒸馏可能继承错误，仿真训练有 sim-to-real gap。
- Hunyuan3D 2.1 许可地域限制及禁止输出训练其他 AI 模型，须单独法律审查。

## 参考链接

- https://github.com/dgrauet/vjepa2-mlx
- https://huggingface.co/mlx-community/V-JEPA2-AC-vitg
- https://developer.apple.com/machine-learning/models/
- https://github.com/jmanhype/vggt-mps
- https://github.com/certeslabs/worldjepa
- https://github.com/QwenLM/BlenderWorld
- https://github.com/Westlake-AGI-Lab/WorldForge
- https://github.com/VladimirTalyzin/hunyuan3d-2.1-mac-rocm
- https://huggingface.co/tencent/Hunyuan3D-2.1/blob/main/LICENSE
