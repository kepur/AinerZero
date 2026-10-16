# AinerZero / AnimeWorld Zero v10.0

## 目标与约束
- M2 Max 96GB，macOS，无 CUDA；MLX 原生可训练核心。
- 保留 AnimeWorld Core 作为唯一权威世界状态，Serafina 负责工具调度，Blender 负责首版物理与渲染。
- FAST/MID/SLOW 记忆；外部教师仅提供带来源和置信度的证据，不直接写入 Brain Core。
- 验证事件驱动稀疏更新与物理+神经残差预测是否在相同质量下优于基线。

## v10 模块
1. Perception/Teacher Gateway：V-JEPA MLX、Depth Anything V2 Core ML、VGGT MPS（可选），离线缓存特征和元数据。
2. Persistent World Core：稳定 object_id、scene graph、pose、velocity、geometry_ref、uncertainty、timestamp、version；事件溯源与快照。
3. Spatial Geometry：相机/尺度校准、深度、点云、Mesh、collider、关系图；区分可观测量和推断量。
4. Hybrid Dynamics：Bullet/Blender 确定性物理 + MLX residual predictor；局部依赖图、dirty-set、阈值回退。
5. Memory/Learning：FAST 工作状态、MID 经验与假设、SLOW 验证过的技能；失败样本主动采样。
6. Rendering/Assets：Blender Mesh/PBR/NPR 首选；3DGS/Metal、LTX、UE、Godot 为后期可替换适配器。
7. Serafina Orchestrator：任务队列、工具权限、缓存、检查点、超时、崩溃恢复。
8. Independent Research Plane：隔离训练集/验证集/测试集，基线、消融、随机种子、性能追踪。

## 核心接口
WorldState = {world_id, tick, timestamp, coordinate_frame, objects:[{id,pose,velocity,geometry_ref,collider_ref,relations,confidence}], events, evidence_refs, version}
Event = {event_id, tick, source, affected_ids, event_type, payload, evidence_ref}
TeacherOutput = {teacher_id, model_version, input_hash, coordinate_frame, output_ref, confidence, provenance, license_tag}

## 训练与更新
- 状态转移：S_(t+1) = Physics(S_t,a_t) + G_theta(local_graph, event, history)；残差仅应用于连续状态变量，离散事件另行预测。
- Dirty-set 由动作、接触、遮挡、新观测及不确定性触发；沿依赖图传播，设最大扩展半径与全量回退。
- 模型从 0.1M–2M 参数起步，后续 2M–10M，确有必要才尝试 20M–30M；冻结教师，训练缓存特征。
- 任何学习更新必须通过独立测试、版本晋升与回滚机制。

## 关键验证实验
### E0 可复现基线
Blender 生成球体、盒子、桌子、斜坡、遮挡等 1k–10k 短序列，保存精确 pose、velocity、contact、camera。3 个随机种子，固定数据划分。
### E1 物理+残差
对比：纯物理、纯 MLX、物理+MLX 残差。指标：未来 1/5/10/30 步位置误差、碰撞 F1、能量漂移、推理延迟。
### E2 稀疏更新
100/1000 对象，1%/5%/20% 对象变化。对比：全量更新、仅 dirty-set、dirty-set+依赖传播。指标：端到端毫秒、GPU 时间、峰值内存、误差、回退率。
### E3 遮挡与持久身份
对象出视野后重新出现；测 IDF1、重识别正确率、世界状态误差、事件日志回放一致性。
### E4 教师价值
无教师、深度教师、V-JEPA、VGGT、组合；比较同质量所需训练时间、教师提取成本、缓存占用、泛化误差。
### E5 跨后端
同一 WorldState 分别驱动 Blender Mesh 与可选 3DGS；检查对象位置、视角一致性和资产编辑性。
### E6 真实视频泛化
未见相机、材质、照明和真实短视频；标记未知尺度，避免将伪标签当真值。

## 判定门槛（实验预注册目标，不是已有成果）
- E2：在误差不显著劣于全量基线前提下，事件稀疏率 5% 时端到端状态更新时间减少 >= 30%；否则回退或重新设计。
- E1：物理+残差在未见场景的 10 步位置误差优于纯物理和纯 MLX 中的更好者 >= 10%，且碰撞 F1 不下降。
- E3：确定性事件重放状态哈希一致；有不确定观测时单独评估概率校准。
- E4：计入教师提取与数据生成的完整成本，报告达到同一精度所需小时和电量，而非只报训练迭代速度。

## 里程碑
- 第 1–3 天：WorldState schema、Blender 仿真生成器、事件日志、确定性回放、基线。
- 第 4–7 天：MLX 小型残差预测器，E1；训练/推理 profiler。
- 第 8–14 天：Dirty-set 调度、E2/E3、3 seeds、首份可复现报告。
- 第 3–6 周：V-JEPA/Depth 教师消融、真实视频迁移、BlenderWorld 结构评测适配。
- 后续：VGGT、Hunyuan3D 资产、Metal 3DGS、Godot/UE/LTX；各项先做兼容性和许可证审查。

## 成本模型
T_total = T_data_generation + T_teacher_extract + T_train + T_eval + T_engineering.
Saving = 1 - T_total(v10)/T_total(baseline)，仅在相同数据、任务和目标质量下比较。
训练时长和成本不能在没有 M2 Max 实测 benchmark 前保证；从零训练大型基础模型不是等价质量基线。

## 不做事项
- 首版不移植 Cosmos/WorldForge 完整 CUDA 链。
- 不把 3DGS 当成物理或语义世界状态。
- 不允许教师未经验证直接修改长期知识。
- 不承诺实时生成开放世界或达到 Genie 级画质。
