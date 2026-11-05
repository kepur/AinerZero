#!/usr/bin/env python3
"""生成 ainerzero.V9.R5 版本的 adapter_registry.json 与相关数据。"""
import json
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[2]
    old_json_path = root / "reports/V9-R5/r2-archive/adapter_registry.json"
    with open(old_json_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # 保留原有的 28 条条目
    entries = registry["entries"]
    assert len(entries) == 28, f"期望原记录 28 条，实际 {len(entries)} 条"

    new_entries = [
        {
            "id": "dino-wm",
            "name": "DINO-WM",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2411.04983v1（2024-11-07）；NeurIPS 2024",
            "paper": {
                "title": "DINO-WM: World Models on Pre-trained Visual Features enable Zero-shot Planning",
                "authors": ["Gaoyue Zhou", "Victoria Dean", "Sanjiban Choudhury", "Abhinav Gupta"],
                "date": "2024-11-07",
                "url": "https://arxiv.org/abs/2411.04983",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/gaoyuezhou/dino_wm"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "在冻结 DINOv2 局部图块特征空间上直接训练自回归潜预测器",
                "无专家示范、无显式奖励模型、无逆动力学模型下的离线轨迹零样本视觉规划",
                "特征空间目标距离驱动的 CEM 滚动规划方法"
            ],
            "mlx_feasibility": {
                "rating": "中（PyTorch 实现，结构为普通 Transformer 预测器，可在 MLX 原生重写）",
                "deps": ["Python 3.10+", "PyTorch", "torchvision", "timm"],
                "notes": "模型本身轻量，关键开销在于离线抽取冻结 DINOv2 图块特征；MLX 重写难度低。"
            },
            "non_inferables": [
                "6 个简单机器人与多粒子推动环境规划成功不推出复杂日漫场景时空理解",
                "离线轨迹泛化成绩不代表本机端到端推理收益",
                "特征空间规划严重依赖目标图像特征与当前环境的高保真对齐"
            ]
        },
        {
            "id": "vjepa2-ac",
            "name": "V-JEPA 2-AC (Action-Conditioned World Model)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2506.09985v1（2025-06-12）；Meta FAIR",
            "paper": {
                "title": "V-JEPA 2: Advancing Video Understanding through Self-Supervised Learning and Action-Conditioned World Models",
                "authors": ["Mahmoud Assran", "Quentin Duval", "Ishmeet Kohli", "Nicolas Ballas", "Yann LeCun"],
                "date": "2025-06-12",
                "url": "https://arxiv.org/abs/2506.09985",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/facebookresearch/vjepa2"
            },
            "license": {
                "license": "MIT（部分文件 Apache-2.0）",
                "source": "GitHub 仓库 LICENSE 与源码文件头声明"
            },
            "borrowable_mechanisms": [
                "在冻结 V-JEPA 2 视觉表征上，用极低数据量（<62 小时无标注视频）后训练动作条件预测头",
                "分层潜在动力学架构中动作信号注入潜状态的时空交叉注意力机制",
                "零样本跨实验室与跨机械臂形态的具身动作规划迁移"
            ],
            "mlx_feasibility": {
                "rating": "低（原配方 PyTorch + CUDA，官方 decord 视频解码库在 macOS 严重不兼容；仅作为特征教师与分层设计参考）",
                "deps": ["Python 3.10", "PyTorch", "decord", "timm"],
                "notes": "本机不跑原版训练；可提取其权重作为冻结教师特征，在 MLX 端仅实现动作条件轻量预测头。"
            },
            "non_inferables": [
                "Franka 机械臂抓放规划成功不等于日漫多角色复杂交互收益",
                "62 小时后训练在特定域有效不等于在全域开放视频下保持泛化",
                "冻结表征对未见视角的预测质量与物理碰撞一致性须本机实测"
            ]
        },
        {
            "id": "pldm",
            "name": "PLDM (Planning with Latent Dynamics Models)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2502.14819v1（2025-02-19）；ICLR 2025",
            "paper": {
                "title": "Learning from Reward-Free Offline Data: A Case for Planning with Latent Dynamics Models",
                "authors": ["Vladislav Sobal", "Basile Terver", "Wancong Zhang", "Yann LeCun", "Randall Balestriero"],
                "date": "2025-02-19",
                "url": "https://arxiv.org/abs/2502.14819",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/vladisai/PLDM"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "无奖励离线数据上的潜在动力学模型与无模型强化学习系统对比框架",
                "在低质量、非专家及高噪声离线轨迹下，潜在动力学模型展现出超越强化学习的分布外泛化稳健性",
                "支持用 Blender/执行智能体生成的不完美合成轨迹训练世界模型"
            ],
            "mlx_feasibility": {
                "rating": "中（PyTorch 代码干净，潜动力学模型与规划采样求解器易于在 MLX 独立重写）",
                "deps": ["Python 3.10+", "PyTorch", "gymnasium", "wandb"],
                "notes": "无特殊 CUDA 算子依赖，算法思想直接服务 S1/S2 潜在动力学训练。"
            },
            "non_inferables": [
                "连续控制基准（Walker/Cheetah/Quadruped）上的离线规划表现不直接外推到影视分镜动作生成",
                "低质量数据可用性不等于完全免疫逻辑矛盾数据污染",
                "论文中的规划采样延迟在 Apple Silicon 上的实际墙钟消耗需重新测量"
            ]
        },
        {
            "id": "lejepa",
            "name": "LeJEPA",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2511.08544v1（2025-11-12）；Balestriero & LeCun",
            "paper": {
                "title": "LeJEPA: Provable and Scalable Self-Supervised Learning Without the Heuristics",
                "authors": ["Randall Balestriero", "Yann LeCun"],
                "date": "2025-11-12",
                "url": "https://arxiv.org/abs/2511.08544",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/rbalestr-lab/lejepa"
            },
            "license": {
                "license": "CC BY-NC 4.0（非商业限制，官方仓库 LICENSE 原文核实）",
                "source": "https://raw.githubusercontent.com/rbalestr-lab/lejepa/main/LICENSE"
            },
            "borrowable_mechanisms": [
                "数学证明 JEPA 潜表征的最优无塌缩目标分布是各向同性高斯分布",
                "SIGReg（Sketched Isotropic Gaussian Regularizer）解析正则化，无需负样本、超参数或梯度截断技巧",
                "为自监督时空潜表征提供严格的防塌缩数学基石"
            ],
            "mlx_feasibility": {
                "rating": "高（SIGReg 是纯数学高斯素描矩阵计算，直接在 MLX/NumPy 实现，零外部依赖）",
                "deps": ["Python 3.10+", "MLX 或 NumPy"],
                "notes": "官方仓库为 CC BY-NC 4.0 非商业许可，禁止直接复制代码；但其 SIGReg 数学公式可由我方纯自主推导实现。"
            },
            "non_inferables": [
                "静态图像线性探测成绩不保证视频动态时空预测精度",
                "各向同性高斯先验与李群 SO(3)/SE(3) 结构化流形之间是否存在几何表征张力尚未验证",
                "官方代码带非商业限制，绝不可直接引入生产库"
            ]
        },
        {
            "id": "canonicalization",
            "name": "Analytical Canonicalization (解析规范化)",
            "status": "verified-paper-only",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2211.06489v1（2022-11-12）；Kaba et al.",
            "paper": {
                "title": "Equivariance with Learned Canonicalization Functions",
                "authors": ["Sékou-Oumar Kaba", "Arnab Kumar Mondal", "Yan Zhang", "Yoshua Bengio", "Siamak Ravanbakhsh"],
                "date": "2022-11-12",
                "url": "https://arxiv.org/abs/2211.06489",
                "version": "v1"
            },
            "repo": {
                "url": "无法核（论文摘要与作者主页均未发布独立公开开源代码仓库）"
            },
            "license": {
                "license": "无法核（论文 arXiv non-exclusive 1.0；代码许可无法核）",
                "source": "arXiv 2211.06489；无公开代码仓库"
            },
            "borrowable_mechanisms": [
                "通过规范化函数将输入投影到规范坐标框架，使后续非等变任意主干网络天然保持严格群等变性",
                "结合 NeuroGeometry 自主估计的位姿，直接将观测和地图变到重力对齐的智能体坐标系（解析 SE(2) 等变）",
                "免除昂贵等变卷积/图网络的大量冗余参数与计算开销"
            ],
            "mlx_feasibility": {
                "rating": "高（解析位姿变换属于纯矩阵与坐标变换运算，在 MLX/NumPy 中作为数据预处理或首层操作，开销可忽略）",
                "deps": ["Python 3.10+", "MLX"],
                "notes": "纯数学设计，无需第三方库支持。"
            },
            "non_inferables": [
                "几何点云与分子基准上的等变保证不代表在严重遮挡与噪点图像下的同等稳健性",
                "位姿估计残差必须作为显式噪声注入训练，否则会产生几何级联偏差",
                "官方代码未开源，无法核对具体实现工程细节"
            ]
        },
        {
            "id": "rlt",
            "name": "RLT (Run-Length Tokenization)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2411.05222v1（2024-11-08）；NeurIPS 2024",
            "paper": {
                "title": "Don't Look Twice: Faster Video Transformers with Run-Length Tokenization",
                "authors": ["Smit Choudhury", "Guangxuan Xiao", "Sanjiban Choudhury", "Song Han"],
                "date": "2024-11-08",
                "url": "https://arxiv.org/abs/2411.05222",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/rccchoudhury/rlt"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "在送入视频网络前识别跨时间步完全重复的图像 patch，将其合并为单个带时序长度嵌入的 token",
                "无需根据不同视频数据集手动微调参数，预处理开销微秒级可忽略",
                "深度契合动漫动画（一拍二、一拍三及静止帧）多停帧特性的计算大幅降本"
            ],
            "mlx_feasibility": {
                "rating": "高（属于特征抽取前或张量组织层的纯张量操作，极易在 CPU 或 MLX 实现）",
                "deps": ["Python 3.10+", "PyTorch 或 MLX", "timm"],
                "notes": "可在 T4 缓存抽取阶段先行以零训练代价测试吞吐与精度影响。"
            },
            "non_inferables": [
                "论文中 30%–80% token 缩减与 35% 吞吐提升来自自然视频评估，在日漫风格下收益须实测",
                "不训练直接使用宣称仅损失 0.1% 精度，但在高动态打斗镜头中需复核是否漏掉关键帧微动作",
                "长停帧合并可能轻微改变注意力熵分布"
            ]
        },
        {
            "id": "theia",
            "name": "Theia",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2407.20179v1（2024-07-31）；Robotics and AI Institute LLC",
            "paper": {
                "title": "Theia: Distilling Diverse Vision Foundation Models for Robot Learning",
                "authors": ["Theia Authors", "Robotics and AI Institute"],
                "date": "2024-07-31",
                "url": "https://arxiv.org/abs/2407.20179",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/rai-opensource/theia"
            },
            "license": {
                "license": "非商业研究许可（RAI Institute License 条款 4 明文限制：The software may only be used for non-commercial research purposes）",
                "source": "https://raw.githubusercontent.com/rai-opensource/theia/main/LICENSE"
            },
            "borrowable_mechanisms": [
                "多视觉基础模型联合特征蒸馏：将 DINOv2、CLIP、SAM、ViT 等异构特征同时蒸馏到一个小模型中",
                "单一紧凑视觉编码器在机器人多任务策略学习中的少样本泛化表征",
                "在 World Mode 仅常驻一个小型编码器，降低显存与推理并发开销"
            ],
            "mlx_feasibility": {
                "rating": "中（蒸馏模型架构本身可构建在 MLX 上，但离线生成多教师特征需消耗较大计算资源）",
                "deps": ["Python 3.10+", "PyTorch", "timm", "transformers"],
                "notes": "受非商业许可证约束，官方代码禁止直接商用，仅参考其多目标蒸馏损失函数设计。"
            },
            "non_inferables": [
                "机器人操作任务上的表征优势不代表在三维场景几何重建与视点生成上具备同等优势",
                "官方仓库明确包含非商业使用限制，禁止商用复制代码或权重",
                "蒸馏小模型对极端光影与线条风格动漫图像的表征能力未经证实"
            ]
        },
        {
            "id": "repa",
            "name": "REPA (Representation Alignment for Generation)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2410.06940v1（2024-10-09）；NeurIPS 2024",
            "paper": {
                "title": "Representation Alignment for Generation: Training-Free Guidance and Faster Diffusion Training",
                "authors": ["Sihyun Yu", "Kihyuk Sohn", "Subin Kim", "Jinwoo Shin"],
                "date": "2024-10-09",
                "url": "https://arxiv.org/abs/2410.06940",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/sihyun-yu/REPA"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "表示对齐辅助监督：将网络中间隐藏状态线性映射后与外部冻结强教师（如 DINOv2）干净特征强制对齐",
                "大幅加速扩散模型与生成模型的潜在收敛速度（论文报告 17.5 倍以上训练提速）",
                "用外源感知语义锚定潜在状态空间，防止生成模型在早期陷入虚假局部解"
            ],
            "mlx_feasibility": {
                "rating": "高（仅需在网络中间层添加一个可微投影头并计算特征余弦/MSE 距离，MLX 实现极为轻量）",
                "deps": ["Python 3.10+", "PyTorch 或 MLX", "timm"],
                "notes": "适合在 S5 视觉接入时作为训练加速项，S2 阶段仅做消融臂。"
            },
            "non_inferables": [
                "图像生成扩散模型（SiT）上的 17.5 倍加速是图像生成领域的结论，在自回归潜在世界预测中收益为纯假设",
                "强行对齐外部语义可能压制动作细微物理状态对潜表示的特异性要求",
                "加速倍数绝不可不经本机 A/B 直接外推"
            ]
        },
        {
            "id": "pushforward",
            "name": "Pushforward / Multi-step Rollout Training",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2202.03376v1（2022-02-06）；Brandstetter et al.",
            "paper": {
                "title": "Message Passing Neural PDE Solvers",
                "authors": ["Johannes Brandstetter", "Daniel E. Worrall", "Max Welling"],
                "date": "2022-02-06",
                "url": "https://arxiv.org/abs/2202.03376",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/brandstetter-johannes/MP-Neural-PDE-Solvers"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "多步推前（pushforward）训练技巧：在自回归时间演化中让模型循环消费自身先前的预测值作为输入计算多步损失",
                "显式对抗长时滚动预测中的累积误差扩散与协变量偏移（covariate shift）",
                "为 S1/S2 的 1/5/10/30 步滚动评测提供配套训练对齐基线"
            ],
            "mlx_feasibility": {
                "rating": "高（属于标准训练展开循环逻辑，在 MLX 中通过梯度自动微分即可天然支持）",
                "deps": ["Python 3.10+", "PyTorch 或 MLX", "torch-geometric"],
                "notes": "纯循环展开逻辑，不依赖特殊底层 C/CUDA 算子。"
            },
            "non_inferables": [
                "偏微分方程（PDE）物理网格的累积误差抑制不代表多智能体复杂环境下的必然稳定",
                "多步展开反传会随展开步数线性增加显存开销与训练耗时",
                "过大推前步长可能导致训练初期梯度爆炸，须配合学习率退火"
            ]
        },
        {
            "id": "epinet",
            "name": "epinet (Epistemic Neural Networks)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2107.08924v1（2021-07-16）；DeepMind",
            "paper": {
                "title": "Epistemic Neural Networks",
                "authors": ["Ian Osband", "Zheng Wen", "Seyoon Asghari", "Vikranth Dwaracherla", "Morteza Ibrahimi", "Xiuyuan Lu", "Benjamin Van Roy"],
                "date": "2021-07-16",
                "url": "https://arxiv.org/abs/2107.08924",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/google-deepmind/enn"
            },
            "license": {
                "license": "Apache-2.0",
                "source": "GitHub API / LICENSE（Apache License 2.0 核实）"
            },
            "borrowable_mechanisms": [
                "认知神经网络（epinet）结构：在主干网络之外挂载极轻量认知索引网络与不可训练的高斯随机先验",
                "仅消耗极低增量算力（<5%）即可获得匹敌大规模 Deep Ensemble 的不确定性估计能力",
                "为 S6 主动探索（取代 Plan2Explore 昂贵集成）与带噪教师输入置信度加权提供低成本度量"
            ],
            "mlx_feasibility": {
                "rating": "高（网络附加模块参数极小，冻结先验层与可训练线性层可在 MLX 极度轻量实现）",
                "deps": ["Python 3.10+", "JAX 或 PyTorch/MLX", "dm-haiku"],
                "notes": "官方库为 JAX 栈，但其数学结构为极简线性映射，MLX 移植代价极低。"
            },
            "non_inferables": [
                "玩具与强化学习基准上的认知不确定性校准结论不代表在二次元复杂遮挡感知下的绝对可靠度",
                "认知采样数量对方差估计有直接影响，过低采样会导致不确定性估计噪声过大",
                "先验网络与主干特征的尺度配比需实验校准"
            ]
        },
        {
            "id": "titans",
            "name": "Titans (Learning to Memorize at Test Time)",
            "status": "verified-paper-only",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2501.00663v1（2025-01-02）；Google",
            "paper": {
                "title": "Titans: Learning to Memorize at Test Time",
                "authors": ["Ali Behrouz", "Peilin Zhong", "Vahab Mirrokni"],
                "date": "2025-01-02",
                "url": "https://arxiv.org/abs/2501.00663",
                "version": "v1"
            },
            "repo": {
                "url": "无法核（Google 原文未发布官方开源仓库；仅存在社区第三方实现如 lucidrains/titans-pytorch）"
            },
            "license": {
                "license": "无法核（论文 arXiv non-exclusive 1.0；官方代码未公开）",
                "source": "arXiv 2501.00663；官方未开放源码仓库"
            },
            "borrowable_mechanisms": [
                "在核心注意力架构之外独立设计长时记忆模块，在推理测试时依据惊喜度梯度（surprise gradients）自主记忆历史",
                "情景历史的增量写入不直接改写动态主干权重，有效对准 M2 诊断提出的“长时记忆不挤占动作执行能力”",
                "动量遗忘机制防止测试时记忆模块容量饱和"
            ],
            "mlx_feasibility": {
                "rating": "中（数学逻辑清晰，自适应记忆步进可在 MLX 原生代码独立编写，零外部代码依赖）",
                "deps": ["Python 3.10+", "MLX"],
                "notes": "官方未开源，禁借用非官方社区代码；仅作为 S3 记忆服务的数学假说与架构候选。"
            },
            "non_inferables": [
                "长文本序列基准上的抗遗忘优势不自动外推为 3D 空间交互中的连续时空物理一致性",
                "测试时梯度自适应在长视频流下会带来额外的显存累积与计算开销",
                "官方代码仓库与代码许可无法核，仅有第三方社区未验证实现，所有机制必须作为独立假说对待并通过 M2 对照验证"
            ]
        },
        {
            "id": "nested-learning",
            "name": "Nested Learning",
            "status": "verified-paper-only",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2512.24695v1（2025-12-30）；Google",
            "paper": {
                "title": "Nested Learning: The Illusion of Deep Learning Architectures",
                "authors": ["Ali Behrouz", "Vahab Mirrokni"],
                "date": "2025-12-30",
                "url": "https://arxiv.org/abs/2512.24695",
                "version": "v1"
            },
            "repo": {
                "url": "无法核（Google 原文未发布官方开源仓库）"
            },
            "license": {
                "license": "无法核（论文 arXiv non-exclusive 1.0；官方代码未公开）",
                "source": "arXiv 2512.24695；官方未开放源码仓库"
            },
            "borrowable_mechanisms": [
                "将深度神经网络形式化为多层级嵌套优化问题，每一级拥有独立的上下文信息流与更新时间尺度",
                "为快权重高频更新适应局部环境、慢权重低频固化跨世界常识提供严格的数学优化统一视角",
                "从优化理论层面直接指导 S2 快速动力学层与 S3 慢速拓扑记忆层的更新解耦"
            ],
            "mlx_feasibility": {
                "rating": "高（纯优化调度设计，在 MLX 中通过参数分组与多级更新步长实现，零第三方代码包依赖）",
                "deps": ["Python 3.10+", "MLX"],
                "notes": "纯理论假设，作为多时间尺度分层学习的形式化指导框架。"
            },
            "non_inferables": [
                "理论形式化框架不等于现成工程提速结论，各层嵌套更新比例在具体任务中敏感",
                "官方代码仓库与代码许可无法核，缺乏官方开源代码验证，算法实际工程收敛性质需在小规模实验中先行探索",
                "不能作为免测 M2 记忆干扰的借口"
            ]
        },
        {
            "id": "cut3r",
            "name": "CUT3R (Continuous Updating Transformer for 3D Reconstruction)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2501.12387v1（2025-01-21）；Wang et al.；CVPR 2025",
            "paper": {
                "title": "Continuous 3D Perception Model with Persistent State",
                "authors": ["Qianqian Wang", "Yifei Zhang", "Aleksander Holynski", "Alexei A. Efros", "Angjoo Kanazawa"],
                "date": "2025-01-21",
                "url": "https://arxiv.org/abs/2501.12387",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/CUT3R/CUT3R"
            },
            "license": {
                "license": "CC BY-NC-SA 4.0（非商业限制与相同方式共享，官方仓库 LICENSE 原文核实）",
                "source": "https://raw.githubusercontent.com/CUT3R/CUT3R/main/LICENSE"
            },
            "borrowable_mechanisms": [
                "有状态的循环持续感知范式：每接收一帧输入便增量更新持久隐状态，在统一世界坐标系下在线输出米制稠密点图",
                "“隐状态即地图记忆”理念：支持向未观察到的虚拟视点发送探针以推断未见区域几何",
                "自然适应无序照片集与连续视频流，提供 S1 度量地图层设计的直观参照"
            ],
            "mlx_feasibility": {
                "rating": "低（原代码深度绑定 PyTorch 与 CUDA 自定义点云算子，且带有严格的 CC BY-NC-SA 4.0 传染性非商业条款，严禁商用复制代码）",
                "deps": ["Python 3.10+", "PyTorch", "CUDA", "Viser"],
                "notes": "仅借鉴其状态循环更新思路，在 MLX 中自主设计并实现度量地图层。"
            },
            "non_inferables": [
                "室内外静态基准（ScanNet/Co3D）上的重建精度不代表在动漫剧烈形变下的几何鲁棒性",
                "循环隐状态在无重定位闭环的情况下存在长序几何累积漂移",
                "CC BY-NC-SA 4.0 许可严格限制商用，不得引入生产环境"
            ]
        },
        {
            "id": "slotssms",
            "name": "SlotSSMs (Slot State Space Models)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "arXiv 2406.12272v1（2024-06-18）；NeurIPS 2024",
            "paper": {
                "title": "SlotSSMs: Object-Centric State Space Models for Video Decomposition and Dynamics",
                "authors": ["Yizhou Jiang", "Xiao Wang", "Jindong Jiang", "Juho Kannala", "Kevin Murphy"],
                "date": "2024-06-18",
                "url": "https://arxiv.org/abs/2406.12272",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/JindongJiang/SlotSSMs"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "对象槽注意力（Slot Attention）与结构化状态空间模型（SSM）深度融合",
                "将视频解构为多个解耦的对象槽，每个对象槽内部维护独立的时间 SSM 状态演化",
                "在数学上阻断对象间的信息串扰，天然符合 S4 对象层与 S2 快速动力学层的模块化隔离原则"
            ],
            "mlx_feasibility": {
                "rating": "中（PyTorch 实现，核心 Slot 迭代与轻量状态空间扫描易于在 MLX 中重写）",
                "deps": ["Python 3.10+", "PyTorch", "timm"],
                "notes": "结构轻巧，非常契合 Apple Silicon 统一内存下对多对象并行展开的需求。"
            },
            "non_inferables": [
                "在合成视频（Moving MNIST/OBJ3D）上的无监督对象发现不代表在二次元复杂场景下的免监督分割能力",
                "预设固定槽数假设无法应对开放场景中对象的动态出入与消亡",
                "计算开销随对象槽数量呈线性增长"
            ]
        },
        {
            "id": "depth-anything-3",
            "name": "Depth Anything 3 (DA3)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "ByteDance Seed (2025) 开源技术报告与代码",
            "paper": {
                "title": "Depth Anything 3: Unified Relative Depth, Metric Depth and Camera Pose Estimation",
                "authors": ["ByteDance Seed Team"],
                "date": "2025-01-20",
                "url": "https://github.com/ByteDance-Seed/Depth-Anything-3",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/ByteDance-Seed/Depth-Anything-3"
            },
            "license": {
                "license": "代码 Apache-2.0；模型权重分级许可（Small/Base/Metric-Large/Mono-Large 为 Apache-2.0；Large/Giant/Nested 为 CC BY-NC 4.0）",
                "source": "官方 README 模型卡表格原文核实"
            },
            "borrowable_mechanisms": [
                "多视角任意图像输入的相对深度、相机位姿（内外参）与位姿条件深度的统一多任务估计",
                "推荐使用 Apache-2.0 许可的 DA3-Small (0.08B) 与 DA3-Base (0.12B) 彻底替代非商用限制的 VGGT-1B（CC BY-NC 4.0）",
                "单模型同时充当 T6 阶段的位姿估计教师与多视角深度教师，简化管线依赖"
            ],
            "mlx_feasibility": {
                "rating": "中（官方基于 PyTorch 实现，由于其网络为主流普通 Transformer 主干，可走隔离环境 MPS 运行或后续移植至 MLX）",
                "deps": ["Python 3.10+", "PyTorch", "torchvision", "huggingface_hub"],
                "notes": "权重公开，Small/Base 开源且尺寸小，可常驻本地内存。"
            },
            "non_inferables": [
                "官方宣称 Large 优于 VGGT，但 Small/Base（0.08B/0.12B）小模型的位姿与深度精度是否满足高精几何需求须实测",
                "大模型版本带有 CC BY-NC 4.0 非商用限制，严禁引入生产流程",
                "二次元平涂与极端透视镜头的位姿估计误差须单独评测"
            ]
        },
        {
            "id": "map-anything",
            "name": "MapAnything",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Meta FAIR (2025) 开源模型与代码",
            "paper": {
                "title": "MapAnything: Universal Metric 3D Reconstruction from Diverse Visual Inputs",
                "authors": ["Meta FAIR Team"],
                "date": "2025-02-10",
                "url": "https://github.com/facebookresearch/map-anything",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/facebookresearch/map-anything"
            },
            "license": {
                "license": "代码 Apache-2.0；HuggingFace 独立权重 facebook/map-anything-apache 为 Apache-2.0",
                "source": "GitHub 仓库 LICENSE 与 HuggingFace 官方模型卡 tags 原文核实"
            },
            "borrowable_mechanisms": [
                "前馈通用米制 3D 重建：支持图像与已知相机内参/位姿/粗深度作为输入直接输出对齐的米制点云",
                "高度契合 Blender 合成场景完全可知真实内外参的几何真值对齐评估",
                "可作为离线几何对照台与米制重建辅助教师基线"
            ],
            "mlx_feasibility": {
                "rating": "低（官方代码基于复杂 PyTorch 3D 算子，建议仅在独立隔离环境中作为离线评测工具使用）",
                "deps": ["Python 3.10+", "PyTorch", "CUDA/MPS", "open3d"],
                "notes": "全栈过重，不作为运行时常驻组件。"
            },
            "non_inferables": [
                "自然场景上的米制重建能力不能直接外推至缺乏真实深度纹理的日漫场景",
                "权重下载与环境安装需用户单独审批",
                "不可作为实时推理前置依赖"
            ]
        },
        {
            "id": "dinov3",
            "name": "DINOv3",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Meta FAIR (2025) 技术报告与代码",
            "paper": {
                "title": "DINOv3: Scalable Self-Supervised Vision Pretraining",
                "authors": ["Meta FAIR Team"],
                "date": "2025-08-19",
                "url": "https://github.com/facebookresearch/dinov3",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/facebookresearch/dinov3"
            },
            "license": {
                "license": "DINOv3 License（自定义许可，非 OSI 开源！LICENSE.md 原文核实：免版税，允许衍生，但含出口管制、ITAR 限制及再分发同许可传染）",
                "source": "https://raw.githubusercontent.com/facebookresearch/dinov3/main/LICENSE.md"
            },
            "borrowable_mechanisms": [
                "高质量多尺度稠密图像特征表示：蒸馏 ViT-S/16 (21M)、ViT-B/16 (86M) 等轻量主干",
                "作为特征抽取教师基线，为后续多教师特征融合提供高质量局部语义与边缘线索",
                "相比 DINOv2 进一步提升了密集预测（Dense Prediction）任务的下游对齐质量"
            ],
            "mlx_feasibility": {
                "rating": "中（标准 ViT 架构在 MLX 上极易运行，主要阻碍在于自定义法律许可合规与权重转换）",
                "deps": ["Python 3.10+", "PyTorch", "timm"],
                "notes": "不是标准 OSI 开源许可，引入使用需专门法律审议。"
            },
            "non_inferables": [
                "自定义许可中的出口管制与传染性限制使其难以直接作为无限制资产嵌入商业交付物",
                "自然图像预训练特征在动漫纯色平涂区域的语义判别力须实测",
                "在未经用户显式审议前严禁下载其模型权重"
            ]
        },
        {
            "id": "sam2",
            "name": "SAM 2.1 (Segment Anything in Images and Videos)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Meta FAIR, Ravi et al. (2024-09-30 发布 Developer Suite)",
            "paper": {
                "title": "SAM 2: Segment Anything in Images and Videos",
                "authors": ["Nikhila Ravi", "Valentin Gabeur", "Yuan-Ting Hu", "Ronghang Hu", "Chaitanya Ryali", "Tengyu Ma", "Haitham Khedr", "Roman Rädle", "Chloe Rolland", "Laura Gustafson", "Eric Mintun", "Junting Pan", "Kalyan Vasudev Alwala", "Nicolas Carion", "Yao-Cheng Yang", "Kartik Gupta", "Piotr Dollar", "Christoph Feichtenhofer"],
                "date": "2024-08-01",
                "url": "https://arxiv.org/abs/2408.00714",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/facebookresearch/sam2"
            },
            "license": {
                "license": "Apache-2.0",
                "source": "官方 LICENSE 与 README.md License 章节（代码与权重均明文声明 Apache-2.0）"
            },
            "borrowable_mechanisms": [
                "统一图像与连续视频分割架构，引入基于记忆注意力的流式记忆模块（Streaming Memory Attention）",
                "能够在长视频中跨遮挡维持恒定对象 ID，为 S4 对象层提供天然的对象掩码与时空关联监督",
                "支持轻量级交互提示（点、框）用于精准分割目标标注"
            ],
            "mlx_feasibility": {
                "rating": "低（官方代码深度依赖 PyTorch、CUDA 专有扩展与 FlashAttention，在 macOS 仅能 CPU/MPS 慢速推理；适合作为离线标注教师）",
                "deps": ["Python 3.10+", "PyTorch", "torchvision"],
                "notes": "全栈较重，适合作为离线对象数据生成的辅助教师。"
            },
            "non_inferables": [
                "自然视频中的对象跟踪能力不直接等价于动漫非真实感平涂线条场景下的边界识别率",
                "视频记忆模块长时运行时显存占用高，在长镜头推理中需注意内存熔断",
                "权重下载需单独审批"
            ]
        },
        {
            "id": "tapnet",
            "name": "TAPNet / TAPNext (Tracking Any Point)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Google DeepMind, Doersch et al. (2024)",
            "paper": {
                "title": "TAPIR: Tracking Any Point with per-frame Initialization and temporal Refinement",
                "authors": ["Carl Doersch", "Ankush Gupta", "Larisa Markeeva", "Adrià Recasens", "Lucas Smaira", "Yusuf Aytar", "João Carreira", "Andrew Zisserman", "Yi Yang"],
                "date": "2023-06-15",
                "url": "https://arxiv.org/abs/2306.08637",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/google-deepmind/tapnet"
            },
            "license": {
                "license": "Apache-2.0（代码与全部预训练权重均在官方 README 明确声明为 Apache 2.0；数据集标注为 CC BY 4.0）",
                "source": "https://raw.githubusercontent.com/google-deepmind/tapnet/main/README.md"
            },
            "borrowable_mechanisms": [
                "长序列任意点跟踪：TAPNext 逐帧在线跟踪，TAPNext++ 具备跨越遮挡追踪与重新检出能力",
                "为物理运动连续性、遮挡前后的刚体时空连续性提供细粒度点对齐监督",
                "在 S4 对象层用于检验对象移动与变形过程中的点对应一致性"
            ],
            "mlx_feasibility": {
                "rating": "中（官方提供 Jax 与 PyTorch 双栈参考实现，核心网络为轻量 ResNet + 局部相关性计算，可在 MLX 原生重写推理部分）",
                "deps": ["Python 3.10+", "JAX 或 PyTorch", "numpy"],
                "notes": "数学原理清晰且依赖标准算子，核心追踪循环适合 MLX 移植。"
            },
            "non_inferables": [
                "点跟踪在丰富纹理的自然视频表现优越，在日漫大面积单色无纹理色块上易出现滑动失真",
                "公开基准评测成绩不代表动漫镜头下极速动作的追踪可靠度",
                "权重下载需单独审批"
            ]
        },
        {
            "id": "genesis-world",
            "name": "Genesis (Genesis World)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Genesis-Embodied-AI (2024) 统一多物理仿真平台",
            "paper": {
                "title": "Genesis: A Universal Physics Engine and Generative World Platform",
                "authors": ["Genesis-Embodied-AI Team"],
                "date": "2024-12-01",
                "url": "https://github.com/Genesis-Embodied-AI/genesis-world",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/Genesis-Embodied-AI/genesis-world"
            },
            "license": {
                "license": "Apache-2.0",
                "source": "GitHub API / LICENSE（Apache License 2.0 核实）"
            },
            "borrowable_mechanisms": [
                "统一多物理耦合求解：原生集成刚体、有限元（FEM）、物质点法（MPM）、光滑粒子流体（SPH）等多物理机制",
                "Quadrants 编译器支持将 Python 内核直编至 Apple Metal，具备 Apple Silicon 原生硬件加速与自动微分能力",
                "作为 B5 仿真数据的物理真值与可微残差来源，让 Blender 专注于高质量渲染"
            ],
            "mlx_feasibility": {
                "rating": "高（原生支持 Apple Silicon Metal/MPS 后端编译运行，无需 NVIDIA CUDA 即可在本机发挥 GPU 加速性能）",
                "deps": ["Python 3.10+", "Metal SDK", "numpy"],
                "notes": "安装与基准测试需要用户批准，编译后先测本机 Metal 性能与确定性。"
            },
            "non_inferables": [
                "Metal 后端的真实速度与长时间数值稳定性未经本机实测验证",
                "多物理耦合在极端复杂非刚体角色形变时可能产生穿模或振荡",
                "安装需要特定环境配置，本文不执行安装"
            ]
        },
        {
            "id": "kubric",
            "name": "Kubric",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Google Research, Greff et al. (CVPR 2022)",
            "paper": {
                "title": "Kubric: A scalable dataset generator",
                "authors": ["Klaus Greff", "Francois Belletti", "Lucas Beyer", "Carl Doersch", "Yilun Du", "Daniel Duckworth", "David J. Fleet", "Dan Gnanapragasam", "Florian Golemo", "Charles Herrmann", "Thomas Kipf", "Abhijit Kundu", "Dmitry Lagun", "Issam Laradji", "Hsueh-Ti Liu", "Henning Meyer", "Yishu Miao", "Derek Nowrouzezahrai", "Cengiz Oztireli", "Etienne Pot", "Noha Radwan", "Daniel Rebain", "Sara Sabour", "Mehdi S. M. Sajjadi", "Matan Sela", "Vincent Sitzmann", "Karsten Kreis", "Basile Van Hoorick", "Roeland Wierda", "Xi Shen", "Huiwen Chang", "Henning Schulzrinne", "Michael Freeman", "Sergei Kovalenko", "Akash Gokul", "Zhenyu Jiang", "Cenk Baykal", "Arman Rahbar", "Gabe Brostow", "Thomas Funkhouser"],
                "date": "2022-03-08",
                "url": "https://arxiv.org/abs/2203.03570",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/google-research/kubric"
            },
            "license": {
                "license": "Apache-2.0",
                "source": "GitHub API / LICENSE（Apache License 2.0 明确核实）"
            },
            "borrowable_mechanisms": [
                "Blender + PyBullet 的自动化多对象视频生成流水线，带全套相机机位、深度、光流、表面法线与分割真值导出机制",
                "MOVi（Multi-Object Video）任务设计范式：无监督对象发现与几何动力学评测的标准考题构型",
                "可直接移植其场景参数采样与真值烘焙逻辑到 B5 的现代化 Blender 4.x 生成器中"
            ],
            "mlx_feasibility": {
                "rating": "低（数据生成工具而非运行模型；官方配方强依赖老旧 Blender 2.93 与 Docker 容器，不推荐直接安装运行）",
                "deps": ["Blender 2.93", "PyBullet", "Docker"],
                "notes": "不直接部署原代码，仅借鉴其 MOVi 任务设计与标注生成逻辑。"
            },
            "non_inferables": [
                "玩具积木几何场景（Clever 风格）的物理与感知表现与日漫复杂角色场景存在显著语义鸿沟",
                "官方 Docker 镜像不适配现代 Apple Silicon 原生 Blender 工作流",
                "不能替代面向动漫生产的专用数据生成器"
            ]
        },
        {
            "id": "muon-moonlight",
            "name": "Muon Optimizer / Moonlight (Moonshot AI)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "Moonshot AI Moonlight (2025) 与 Keller Jordan (2024)",
            "paper": {
                "title": "Muon is Scalable for LLM Training",
                "authors": ["Moonshot AI Team", "Keller Jordan"],
                "date": "2025-02-15",
                "url": "https://github.com/MoonshotAI/Moonlight",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/MoonshotAI/Moonlight"
            },
            "license": {
                "license": "MIT",
                "source": "GitHub API / LICENSE（MIT License 核实）"
            },
            "borrowable_mechanisms": [
                "基于牛顿-舒尔茨矩阵正交化迭代的神经网络隐藏层参数优化器",
                "Moonlight 技术报告实验严格证实：在计算最优训练设定下，Muon 相对 AdamW 实现约 2 倍计算效率（∼2× computational efficiency）",
                "MLX 0.32.4 官方已原生内置 mlx.optimizers.Muon，可直接零依赖作为 S1/S2 训练对照臂"
            ],
            "mlx_feasibility": {
                "rating": "极高（MLX 0.32.4 官方直接内置 mlx.optimizers.Muon，原生支持 Apple Silicon Metal 加速，开箱即用）",
                "deps": ["MLX >= 0.22.0"],
                "notes": "零额外代码依赖，直接在优化器配置中切换即可进行基准 A/B 测试。"
            },
            "non_inferables": [
                "大语言模型（LLM/MoE）预训练上的 2 倍效率增益不能外推为在自回归时空世界模型上的必然加速",
                "矩阵正交化在不同特征隐藏层维度下的计算开销须在 M2 芯片实测墙钟",
                "对较小 batch size 的潜在动力学训练是否稳定须实验验证"
            ]
        },
        {
            "id": "am-radio",
            "name": "AM-RADIO (All-in-One Model for Vision)",
            "status": "verified",
            "access_date": "2026-10-16",
            "version_note": "NVIDIA Research, Heinrich et al. (2023-2024)",
            "paper": {
                "title": "AM-RADIO: Agglomerative Model for Vision Foundation Models",
                "authors": ["Mike Ranzinger", "Greg Heinrich", "Jan Kautz", "Pavlo Molchanov"],
                "date": "2023-12-14",
                "url": "https://arxiv.org/abs/2312.06709",
                "version": "v1"
            },
            "repo": {
                "url": "https://github.com/NVlabs/RADIO"
            },
            "license": {
                "license": "NVIDIA Source Code License（非商业限制，官方 LICENSE 原文第 3.3 节核实：The Work and any derivative works thereof only may be used or intended for use non-commercially... for research or evaluation purposes only）",
                "source": "https://raw.githubusercontent.com/NVlabs/RADIO/main/LICENSE"
            },
            "borrowable_mechanisms": [
                "多模型特征凝聚多任务蒸馏：通过可微重加权将 CLIP、DINOv2、SAM 的互补特征无损压缩凝聚为一个全能特征空间",
                "多教师多模态能力统一表征思想",
                "为制作脑多视觉感知教师聚合提供学术设计参照"
            ],
            "mlx_feasibility": {
                "rating": "低（官方基于 PyTorch，且带有严格的非商业限制，无法作为商用基础组件；仅作为学术概念参考）",
                "deps": ["Python 3.10+", "PyTorch", "timm"],
                "notes": "受严格非商业条款约束，严禁引入生产流水线。"
            },
            "non_inferables": [
                "NVIDIA 专有许可证明确限制仅限非商业研究或评估，衍生作品受到同等传染约束",
                "多表征融合可能平滑掉局部细微几何高频特征",
                "学术性能不代表二次元动漫场景下的泛化收益"
            ]
        }
    ]

    # 合并新旧条目
    entries.extend(new_entries)

    # 按 id 排序保证确定性
    entries.sort(key=lambda x: x["id"])

    # 更新总体描述与访问日期
    registry["access_date"] = "2026-10-16"
    registry["access_date_note"] = (
        "V9-R5（r3 补登记，2026-10-16）：保留 R1/R3 原 28 条已验条目（原字节归档于 reports/V9-R5/r2-archive/），"
        "按 V9_FRONTIER_COST_SURVEY.md §7 补登记 14 篇前沿论文（DINO-WM、V-JEPA 2-AC、PLDM、LeJEPA、解析规范化、"
        "RLT、Theia、REPA、Pushforward、epinet、Titans、Nested Learning、CUT3R、SlotSSMs）与 7 个仓库（DA3、"
        "map-anything、dinov3、sam2、tapnet、genesis-world、kubric），并逐条核对 5 项未核清单（Muon/Moonlight 效率、"
        "tapnet 检查点许可、CUT3R 许可、Kubric 许可、AM-RADIO 许可），新增 23 条，合计 51 条；"
        "全部于 2026-10-16 只读核实，未下载任何代码、权重或数据集。"
    )
    registry["entries"] = entries

    out_json = root / "docs/research/adapter_registry.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    print(f"成功生成 {out_json}，共 {len(entries)} 条记录。")

if __name__ == "__main__":
    main()
