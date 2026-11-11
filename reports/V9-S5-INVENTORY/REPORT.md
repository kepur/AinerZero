# ainerzero.V9.P224 S5 视觉强化可行性只读盘点

角色：executor；负责人：grok47-w3p9；时间：2026-11-11
任务状态：reported；实验状态：未执行（只读，未训练、未下载、未安装）
参数 v0：`base_commit=af16dcc`，`deliver_dir=reports/V9-S5-INVENTORY/`。`git rev-parse --short HEAD` 为 `af16dcc`，与参数一致。
范围：只写本目录。许可只引用读到的原文；读不到许可文件就写「未找到许可文件」，不把模型卡上的 `license:` 字段当成许可正文。

命令入口：`python3 reports/V9-S5-INVENTORY/evidence/inventory_s5.py`（elapsed 见 `evidence/00-elapsed.txt`：`elapsed_s=5.004`）。

## 0. 已读的架构与开题句

- 教师合一：`ARCHITECTURE_V9.md` 第 43 行。缓存齐后把多个冻结教师蒸馏成一个小 MLX 学生编码器，World Mode 只常驻它；本机收益待 S5 实测。
- 式 10：同文件第 151 行。同一位置图块 `‖p_t − p_{t−1}‖_∞ < τ` 则并入上一个 token，游程编码；`τ` 登记时冻结。
- 式 11：第 152 行。`L_align = 1 − cos(h_φ(z^{(l)}), sg(T(x)))`，仅 S5 及其消融，`η` 登记时冻结。
- S5 一行：第 182 行。学生端编码器蒸馏与微调、多教师合一、教师对齐作加速项、RLT 开关、E6 真实视频泛化；需批准；对象 ID 不泄露；遮挡与 3D 关系分开报；外部预训练如实标注；未知尺度显式标记。
- 本机集成：第 214–222 行。M2 Max 96GB、无 CUDA；离线教师 + 特征缓存 + 原生 MLX 小学生；教师不常驻。
- 降本：第 284–286 行。RLT、多教师合一、式 11 的落点与「论文数字不是本机实测」。
- E4：第 328 行。无教师、深度教师（DA2/DA3）、V-JEPA 2.1、组合；不含 VGGT。下载与运行需批准（T4 已批准部分）。
- E6：第 330 行。未见相机、材质、光照与真实短视频；数据下载与许可需批准。
- 开题：`RESEARCH_LOG.md` 第 3651–3667 行 `R20261111-S5-start`。用户原话「Approve S5 budget」。批准的是本机 MLX：蒸馏、多教师合一、式 11、RLT。不包括新下载、付费、云 GPU、CC-BY 进训练、超出登记预算的运行。T4 已验收，T8 已验收，DA3（T6）阻塞、T35 失败，下游用 S1 一期主干（E1 已收口）。具体总小时数、每格上限、种子数仍要一级在设计稿里写定。

接力台（`evidence/09-relay-cards.json`，命令 `relay show <id> --json`）：

| 卡 | 状态 | 标题要点 |
|---|---|---|
| P5 | draft | S5 实现草稿。卡面仍写「训练预算待用户批准」。前置 P3 cancelled、T4 accepted、T8 accepted |
| P6 | draft | 复核 P5 |
| T4 | accepted | V-JEPA 2.1 ViT-L MLX + Core ML Depth Anything V2 Small |
| T8 | accepted | RLT numpy 参考实现 |
| T6 | blocked | DA3-Small/Base。attempts 5 |
| T35 | failed | 18 视图标定。接力台结果头是 r2：深度形状不一致，预测只留下一部分 |

P5 卡面和开题记录不一致：卡面第 13 行仍写批准前不得训练，开题第 3654–3657 行已经批准本机 MLX，但具体格子预算还没冻结。本盘点不改参数。

## 1. 教师

`artifacts/teachers/` 下只有三组，没有别的权重目录。`find` 见领取后第一次目录列举；逐文件字节与 SHA256 全文在 `evidence/01-teacher-sha256.txt`。下面的 SHA 与该文件逐字相同。T4 报告第 30–32 行写下的 V-JEPA SHA 与本次重算一致。

### 1.1 V-JEPA 2.1 ViT-L（MLX）

- 目录名即 HF revision：`artifacts/teachers/t4-approved/b0674736bad10eb16bd765942a9065e7e2ee9a54/`。
- `config.json` 第 2–15 行：`model_type=vjepa2-vit-l-rope`，`variant=vit-l-rope`，`embed_dim=1024`，`depth=24`，`patch_size=16`，`num_frames=64`，`tubelet_size=2`，`img_size=384`。配置写 64 帧；T4 实测输入是 16 帧（见下），两处不要混成一个数。
- 权重：

| 文件 | 字节 | SHA256 |
|---|---:|---|
| `encoder.safetensors` | 1218752536 | `7a68c25e3515108f81a88c3157ab5aa41322e0b49faf135c35cca147130c8e19` |
| `predictor.safetensors` | 91908429 | `c601a96f4bdb852ade8c5334b0a8e1beaa7461b60566387ad7a134ee437c2bf7` |
| `config.json` | 861 | `36a174637ddd2976efbe3e166e2c54359afbe2f4cbff67573f71f0691634eb96` |
| `split_model.json` | 944 | `8681855d8bf614758fec95dde10f017a1171ecc232130ae8a3de2f4a4df1a2c5` |
| `README.md` | 1074 | `3424969988eab48453eafd1fbc4fadb1b1dff79ad89f44b819a845a8c1dd2529` |

- 权重目录内未找到许可文件（`evidence/02-license-files.json` 在 `artifacts/teachers` 下是空的）。`README.md` 第 3 行只有模型卡字段 `license: mit`，不是许可正文。
- 移植代码的许可正文在另一路径：`envs/teachers/src/vjepa2-mlx/LICENSE`（1384 字节）。第 1–18 行写明这是 MIT，并写「The original V-JEPA 2 / V-JEPA 2.1 code and model weights are released by Meta Platforms, Inc. under the MIT License」。第 10–18 行授予包括 `sell` 在内的不限用途，条件是保留版权声明和本许可声明。全文没有 non-commercial 字样。这是代码树里的 LICENSE，不是权重目录里的文件。

T4 实测（`reports/V9-T4/bench.json`，报告表在 `reports/V9-T4/REPORT.md` 第 88–91 行）：

- 输入：`input_shape` `[1,3,16,384,384]`，分辨率 384×384，16 帧，精度 float32（`bench.json` 第 11–28 行）。
- 输出：`[1,4608,1024]`（第 29–33 行）。
- 稳态：中位 clip 吞吐 `1.1117312275761457` clip/s，帧吞吐 `17.78769964121833` fps，范围 12.715…–25.286… fps（第 46–57 行）。每千样本外推 `899.4979858398438` 秒（第 59 行）。
- 内存：`rss_peak_bytes=3036528640`（报告写成 2.89 GB / 2895.859375 MB），`mlx_peak_memory_bytes=5537497172`（报告写成 5.28 GB）（第 67–74 行）。
- 单样本特征 `18874368` 字节（18.00 MB），每千样本缓存 `18874368000` 字节（第 61–66 行）。

### 1.2 Depth Anything V2 Small（Core ML，F16 与 F32 两套）

- 目录 revision：`artifacts/teachers/t4-approved/cfef6f6f2a70783dedc0bfae40cecbc2052285d3/`。
- `README.md` 第 5 行模型卡字段 `license: apache-2.0`。第 27–28 行表内写 Small 变体 24.8M 参数，F32 包 99.2 MB、F16 包 49.8 MB。这不是许可正文。
- 权重目录及 `artifacts/teachers` 下未找到许可文件。因此不从字段名推断商用、署名或非商用条款。

| 文件 | 字节 | SHA256 |
|---|---:|---|
| F16 `weight.bin` | 49419072 | `fa60d9b6a155734f59029ebb882fd54e549bfaee3539c1a9cbd2cbbab64a0fed` |
| F16 `model.mlmodel` | 399433 | `44ac97a3efcfd52113183fb2862ff59cd0368e9ec2e30a90a54980dd11407042` |
| F32 `weight.bin` | 98821504 | `6b02236f9b6c8c4694904f89c0fc84c3b6175cde43f9f918f77948708c36b58d` |
| F32 `model.mlmodel` | 366829 | `dfd7fd461ab2544f4951e757a59d878d6af93b5544541ed534329d84e958f0c9` |
| `README.md` | 3900 | `a3280768d250f8a0c38f1f60971284e9658bc000eeb897eab126e20bd7cdee46` |

T4 实测的是 F16（`bench.json` 第 90 行 `precision: float16`），输入分辨率 518×392，一帧。三种 compute unit：

| compute unit | 稳态 fps 中位 | 每千帧外推秒 | RSS 峰值字节 |
|---|---:|---:|---:|
| CPU_AND_NE | 38.56157544888709 | 25.93255043029785 | 3036528640 |
| CPU_AND_GPU | 报告表第 92 行写 40.4 fps；json 在第 130 行起 | 报告表 24.78 s | 同表 2.89 GB |
| ALL | 33.68702412696373（json 第 216 行） | 报告表 29.69 s | 同表 2.89 GB |

CPU_AND_NE 的首帧延迟 `0.03587508201599121` 秒，加载 `10.03713321685791` 秒（json 第 91–92 行）。单帧深度 `406112` 字节（第 119 行）。报告建议 World Mode 用 CPU_AND_NE（`REPORT.md` 第 96–99 行）。

### 1.3 DA3-SMALL / DA3-BASE

权重在 `artifacts/teachers/da3/`，不是 T4 批准包。

| 模型 | config | 权重字节 | SHA256 |
|---|---|---:|---|
| DA3-SMALL | `config.json` 第 2 行 `model_name=da3-small`；第 15 行骨干 `"name": "vits"` | 137248940 | `364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf` |
| DA3-BASE | `config.json` 第 2 行 `model_name=da3-base`；第 15 行骨干 `"name": "vitb"` | 541518028 | `e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5` |

- 这两个目录里只有 `config.json` 和 `model.safetensors`。未找到许可文件。
- 代码树 `envs/teachers/t6/Depth-Anything-3/LICENSE` 是 Apache License 2.0 全文（11355 字节）。第 66–71 行版权授予 reproduce、Derivative Works、publicly display/perform、sublicense、distribute，无收费、无 royalty。第 76–80 行专利授予包含 `offer to sell, sell`。第 89–110 行再分发必须附上本许可证、修改声明，并保留版权与归属声明；有 NOTICE 时要带上。全文检索没有 “non-commercial” 字样。该 LICENSE 在代码检出里，不在 `artifacts/teachers/da3/` 权重旁。
- `envs/teachers/t6/Depth-Anything-3/README.md` 第 223–224 行的表把 DA3-BASE、DA3-SMALL 的 License 列写成 `Apache 2.0`。这是表内标签，不是许可正文。
- T4 的 `bench.json` 没有 DA3。DA3 的吞吐、内存峰值、输入分辨率：T4 报告里未查到。T6/T35 的预测张量见第 2 节，那不是稳态基准。

`du -sh artifacts/teachers` 为 `2.0G`（t4-approved `1.4G`，da3 `647M`）。

## 2. 教师特征缓存

### 2.1 已经抽过的

视觉教师的训练特征缓存：未查到。

- `artifacts/v9/teachers/` 只有 `benchmark/runs.db`（及 shm/wal）。`evidence/04-prediction-and-teacher-bench.json` 里该目录 safetensors/npz/npy/json 计数为 0。
- T4 报告第 110 行：「未写入 T2 缓存」。基准用的是程序化张量（第 112 行），没有落成可训练特征库。
- 按文件名在 `artifacts/`（跳过 `artifacts/reports`）搜到的 4 份 `teacher-cache*.npz` 是 M2 动作保持 logits，不是视觉特征。例：`artifacts/pilot/pilot-77e301a3fbd34b0a99c89276364b918e/teacher-cache-manifest.json` 第 11–21 行 `teacher_logits` 为 float32、形状 `[256,2,8,256]`；第 36 行协议 `m2m_d_m2d_distilled_action_preservation_v1`。四份 npz 各 4459286 字节（`evidence/03-feature-name-hits.json`）。

DA3 标定预测（不是 V-JEPA/DA2 特征缓存，也没有登记成训练缓存）：

- `reports/V9-T6/r4/predictions/`：61 个 json/safetensors，109788715 字节，其中 safetensors 48 个。抽读 `da3_base/t6-analytic-room-03/view_1.safetensors` 头：`depth` F32 `[378,504]`，`confidence` F32 `[378,504]`，`camera_pose` F32 `[3,4]`，`intrinsics` F32 `[3,3]`（`evidence/04-prediction-and-teacher-bench.json`）。T6 报告第 15 行写 60 个预测文件、109777368 字节；本次多计到的 1 个是清单 json，字节差在清单本身。
- `reports/V9-T35/predictions/`：5 个文件、9149011 字节。抽读 `da3_small/t6-analytic-room-00/view_1.safetensors`，深度同样是 F32 `[378,504]`。元数据键含 `model`、`world_key`、`view_idx`。接力台 T35 结果写明 r2 在形状不一致处失败，只留下一部分 da3_small 预测。

抽取时的教师与参数：T6 报告第 17–18 行写 DA3-SMALL 与 DA3-BASE、6 房间；分辨率以上面 safetensors 头为准（378×504）。V-JEPA / DA2 的抽取参数：未查到已落盘的特征，只有第 1 节的基准输入规格。

### 2.2 数据在手、还没抽视觉特征的

- S1 数据包：`artifacts/v9/s1/datasets/8234f2f3…ad26/`。`dataset_manifest.json` 第 12–19 行：train 2000 episodes / 9500 packets，development 200 episodes / 950 packets。内容是结构化 observation，不是像素（第 4 节）。没有对应的 V-JEPA 或 DA2 特征文件。
- E1 学生/评测 json：`artifacts/v9/e1/phase2/datasets/`。`evidence/08-interface-samples.json`：student 2400 文件、89810316 字节；evaluator 2400 文件、43609796 字节；raw 2801 文件、484506428 字节。无 png/mp4（`evidence/05-visual-media.json` 的 `az-e1.files=0`）。
- AWZ 报告目录里的像素：63 个报告子目录合计 16782 个媒体文件、1068401989 字节，其中 png 16719、mp4 36、jpg 24、webp 3（由 `05-visual-media.json` 汇总）。36 个 mp4 全部 ffprobe 成功：854×480、`avg_frame_rate=24/1`、`nb_frames` 合计 7000（`evidence/14-ffprobe-sample.json`）。这些是报告里的渲染和探针，不是已登记的 S5 训练集，也没有抽过教师特征。

## 3. 视觉数据与许可

没有一份「许可正文已读到、并且已经登记可进训练」的像素训练集。下面按盘上实际文件写。CC-BY：Forge 库 52 行的 `license_id` 只有 `CC0-1.0`（44）、`GPL-3.0-or-later`（4）、`MIT + GPL-3.0-or-later`（4），没有 CC-BY。用户未批准 CC-BY 进训练；本库当前行里未查到 CC-BY。

### 3.1 结构化仿真（不是像素）

S1 与 E1 是自制的仿真记录，不是图像。S1 包说明写训练路径只读 packets，truth 另文件（`src/ainerzero/v9/experiments/s1/data.py` 第 10–14 行）。E0 生成器在 `AnimeWorldZero/python/animeworld/e0/`，该目录 32 个文件全是 `.py`/`.pyc`，没有图像。

几何真值不能进学生输入的部分：

- S1：`payload_features`（`data.py` 第 675–708 行）只写入相对位置、presence、confidence、外观类 one-hot 和 ego delta，拼成 72 维（`spec.py` 第 465–476 行 `detection_slots=6`、`feature_dim=72`；6×11+6=72）。不读取对象 ID。真值在 `truth/*.jsonl`，首行键含 `world_key`、`scene_id`、`world`（`evidence/08-interface-samples.json`）。训练说明写 packets 不含真值字段（`data.py` 第 12–14 行）。
- E1：`export.py` 第 62–76 行禁止学生侧出现 `family`、`world_key`、`hidden_parameters`、`mechanisms`、`paired_p_world_key`、`contacts`、`contact_specification`、`paired_p_id`、`paired_p_opaque_id`、`s_world_key`、`p_world_key`，以及前缀 `s_`、`seq_s_`。学生帧里仍有物体类型名和位置/速度（第 481–504 行）。抽读 `student/S/development/a0dbf6178e57ce81.json`：40 帧，对象名为 `BouncingBox`、`BouncingSphere`，键是 position、linear_velocity、orientation、angular_velocity。`SOURCE_FPS=60`（`export.py` 第 55 行）是状态序列的帧率，不是渲染视频帧率。

### 3.2 AnimeWorldZero 像素

| 位置 | 规模 | 分辨率 / 帧率 | 许可文件 |
|---|---|---|---|
| `assets/identities/heroine_001/v1/textures/eye.png` | 1 张，765 字节 | 64×64 PNG | 旁边未找到许可文件 |
| `godot/assets/heroine_001/heroine_001_eye.png` | 1 张，765 字节 | 64×64 PNG | 未找到许可文件 |
| `godot/render`、`godot/acis` | 0 个媒体文件 | 未查到 | 未找到许可文件 |
| `reports/` 下 63 组 | 见 2.2：16719 png + 36 mp4 等 | 抽到的成片多为 854×480；36 个 mp4 全是 854×480、24 fps、共 7000 帧。另有裁剪图（例如 588×720）和拼图（例如 2135×480），不是单一分辨率 | 这些报告目录未找到许可文件 |

对象 ID / 几何真值：这些 png/mp4 是渲染产物。未查到与每帧绑定、且声明「不得进学生输入」的对象 ID 清单。仿真真值边界以 3.1 的代码为准，不能自动套到这些像素上。

Rose 相关渲染（例如 `reports/CF-H5`、`CF-H7`、`CF-H9`）用的角色在 Forge 里是待审，见 3.3。不能因为画面是本机渲的就写成可训练。

### 3.3 AinerForge 素材库

`data/library/library.db` 只读查询（`evidence/06-forge-library-db.json`）：`assets` 52 行。status：`usable` 49、`quarantine` 2、`license_pending` 1。category 含 lighting/hdri 15、prop 若干、plugin 8、character/vrm 2、motion/clip 3。这些多数是 blend/hdr/vrm/插件，不是视频帧。

许可正文：资产旁未找到 CC0 法律文本文件。库里的 `license` 列是 JSON，`license_id` 为上面三个值，`evidence` 指向白名单或内嵌 meta。按本任务规则，这不是许可文件原文，所以不把「CC0-1.0」写成已经读过的 CC0 条款，也不据此声明可以进训练。

特别标出：

- Rose `polygonalmind_100avatars-r1_rose` 有两行。revision 1：`status=usable`，`license_id=CC0-1.0`，evidence 写 VRM meta `licenseName=CC0`。revision 2：`status=license_pending`，`license_id` 仍是 `CC0-1.0`，evidence 追加「2026-11-09 用户决定降为许可待审」。当前有效状态以 revision 2 的 `license_pending` 为准。未批准进训练。
- 隔离：`plugin_sun_position` revision 1 quarantine，`license_id=GPL-3.0-or-later`；`plugin_vrm_addon` revision 1 quarantine，`license_id=MIT + GPL-3.0-or-later`。许可正文未在资产旁读到。
- 附件预览 4 张 PNG，512×768，在 `attachments/polygonalmind_100avatars-r1_rose/2/inspection/previews/`，属于 Rose 检查图。
- `thumbs/` 2816 张 PNG，抽样多为 512×512，是缩略图，不是训练视频。

CC-BY：52 行里未查到。没有「CC-BY 待审」资产可列。约束本身仍在（开题第 3657 行）。

## 4. 世界脑主干

### 4.1 代码

- S1 一期：`src/ainerzero/v9/experiments/s1/`。预登记原文写明没有视觉教师臂：`prereg.py` 第 377 行 `phase: S1 phase 1 (structured restricted observation arms; no visual-teacher arm)`。
- E1：`src/ainerzero/v9/experiments/e1/`。网络在 `arms_net.py`。`DEFAULT_INPUT_DIM=24`（第 63–66 行）：`HISTORY_K=4` × `STATE_DIM_PER_BODY=6`（x,y,z,vx,vy,vz）× `DEFAULT_NUM_BODIES=1`。输出 6 维。注册参数量 6150（`spec.py` 第 175–176 行）。

### 4.2 已训练权重

- S1：`artifacts/v9/s1/phase1/runs/<run_id>/checkpoints/updates-{0,439,878,1755}.npz`。单文件大约 641526、833782 或 1099830 字节。逐文件 SHA 在 `evidence/07-checkpoints.json`。`du`：`artifacts/v9/s1` 136M，其中 phase1 118M。
- E1 phase2：`artifacts/v9/e1/phase2/checkpoints/arm{2,3,6}_{S,P}_seed{42,43,44}/model_weights.npz`，每份 25812 字节，另有 `normalization.npz` 1792 字节。phase2-r2 同样有一套。抽读 `phase2/checkpoints/arm2_S_seed42/model_weights.npz`：`fc1.weight` 形状 `(64, 24)` float32，`fc2.weight` `(64, 64)`，`out.weight` `(6, 64)`，参数合计 6150。与 `DEFAULT_INPUT_DIM=24` 一致。
- 输入接口：S1 是结构化向量，不是像素、也不是视觉 token。`payload_features` 产出 72 维 float32。E1 是 24 维状态历史，不是像素。V-JEPA 基准输出是 `[1,4608,1024]` token，对不上这两个输入。

### 4.3 下游指标，以及学生编码器能不能直接接上

- S1 指标在 `src/ainerzero/v9/experiments/s1/metrics.py`：`localization_error`（第 73 行）、`observation_prediction_metrics`（第 126 行）、`topology_edge_metrics`、`few_shot_transition_metrics`、`memory_interference`、`metric_suite_report`（第 672 行）等。吃的是位姿、观测预测和回合表，不是教师 token。
- E1 指标在 `src/ainerzero/v9/experiments/e1/metrics.py`：`compute_position_error`（第 81 行）、`compute_horizon_position_errors`、`compute_collision_f1`（第 390 行）、`compute_ballistic_energy_drift`、`summarize_inference_latency`。吃的是位置/碰撞，不是编码器嵌入。
- 蒸馏后的学生编码器不能直接接上。S1 一期没有视觉教师臂；E1 第一层权重把输入钉在 24 维。要接，得另写适配，并把 72 维或 24 维接口改成登记过的新输入。那不是现在的权重能直接吃的。

## 5. RLT

- 位置：`src/ainerzero/v9/tokenization/rlt.py`。函数 `rlt_frame_dropping(video_chunks, tau)`（第 26–48 行）。输入 `[T, H/p, W/p, D]` 的图块特征，不是像素。返回 `retained [K,D]`、`run_lengths`、`positions`、`restoration`、`retention_rate`。只 `import numpy`（第 23 行）。
- 全 `src/` 检索：`rlt_frame_dropping` 只在这个文件里定义，没有训练循环调用它。
- 测试：`tests/v9/tokenization/test_rlt.py`。ast 数到 18 个 `test*` 函数，文件中没有 `import mlx`（`evidence/10b-rlt-ast.txt`）。T8 报告第 134–139 行写 18 项通过、0.09 秒。T8 卡 status=accepted。
- 接进 MLX 训练还缺：MLX 实现（现在是 numpy）；从像素或从教师 token 网格喂进 `[T,H/p,W/p,D]` 的接线（没有调用点）；登记并冻结的 `τ`（式 10 要求登记时冻结，盘上未查到 S5 的 τ）；开/关对照的训练循环。这些都可以在现有代码上写，不需要下载。

## 6. 成本粗估

只使用 T4 已测速率和 B3 已测原语。分辨率和任务都对不上的地方单独写明，不把外推写成新的实测。

### 6.1 在现有像素上按 T4 速率抽一遍

速率来源：`bench.json` V-JEPA `throughput_clip_per_s_median=1.1117312275761457`（16 帧、384×384）；DA2 CPU_AND_NE `throughput_fps_median=38.56157544888709`（518×392，一帧）。算术原文在 `evidence/15-cost.txt`。

现有成片：36 个 mp4、7000 帧、854×480、24 fps。不是 T4 的输入尺寸。若仍套用 T4 速率（不重新测）：

- DA2：7000 / 38.56157544888709 = 181.53 秒 = 0.0504 小时。
- V-JEPA：把 7000 帧切成 16 帧片段得 437.5 段；437.5 / 1.1117312275761457 = 393.53 秒 = 0.109 小时。片段是否对齐、854×480 缩放到 384×384 的耗时，未测。

若把报告目录全部 16719 张 png 都当 DA2 的一帧（分辨率混杂，含拼图和裁剪）：433.57 秒 = 0.120 小时。这些 png 没有登记成连续 16 帧片段，所以不对它们做 V-JEPA 片段估计。

DA3：未查到可外推的稳态吞吐，不算小时数。

上述像素还没有「可进训练」的许可结论（第 3 节）。数字只是「如果拿去抽特征，按 T4 速率要多久」。

### 6.2 小 MLX 学生每千样本

`reports/V9-B3-mlx-unitcost/指标.json` 是 S1 结构化臂的推理原语，不是视觉学生编码器，也不是训练步。第 167–180、206–219、246–259 行的中位秒数 ×1000：

| 臂 | 参数量 | encode 每千次（秒） | forward 每千次（秒） |
|---|---:|---:|---:|
| arm2 | 207519 | 0.604458 | 2.577104 |
| arm3 | 159455 | 0.543313 | 2.495104 |
| arm4 | 274031 | 0.561959 | 2.513896 |

进程峰值 RSS `0.105224609375` GiB，MLX 峰值 `0.0010523833334445953` GiB（第 98–100 行）。一次真实测量墙钟 `outer_wall_seconds=3.330`（第 13 行）。

视觉学生编码器的训练步每千样本：未查到。不把 forward 乘一个倍数去冒充训练时间。

### 6.3 常驻内存

没有教师和学生同时加载的实测。可引用的分项：

- V-JEPA 进程 RSS 峰值 3036528640 字节，MLX 峰值 5537497172 字节（T4，单模型）。
- DA2 进程 RSS 峰值同样记为 3036528640 字节（T4；与 V-JEPA 数字相同，是各次基准自己的峰值，不是相加）。
- S1 小臂进程 RSS 峰值 0.105 GiB（B3）。

不把这些数相加写成「已测常驻」。架构第 218 行要求教师不常驻；World Mode 只常驻学生编码器，而这个编码器还不存在。

## 7. 缺口（对照架构第 182 行的 S5）

| 缺口 | 要不要下载 | 要不要用户另批 | 能否只用现有东西做 |
|---|---|---|---|
| S5 设计稿与冻结的格子预算（小时、种子、τ、η）。P5/P6 仍是 draft | 否 | 开题已批本机 MLX 的范围；具体格子预算还没写定，要一级在设计稿里登记，不是本盘点能填的 | 材料够写设计稿。不能直接开训 |
| V-JEPA 与 DA2 的特征缓存 | 否，权重已在 | 抽特征是一次登记运行，不是这次只读盘点。开题允许本机 MLX，但要按卡登记预算 | 教师和少量像素都在。许可还没过（第 3 节），不能把报告像素直接当训练集 |
| 多教师里的 DA3 | Small/Base 权重已在，不必为这两份再下载 | 要。开题第 3657 行写明不包括尚未接入的 DA3。T6 blocked，T35 failed | 不能。没有可用的接入和稳态基准 |
| 学生编码器代码，以及接到 72 维 / 24 维主干的适配 | 否 | 训练本身在已批的本机 MLX 范围内，仍要设计稿把接口和预算写死 | 代码现在接不上（第 4 节）。可以新写，不用下载 |
| 式 11 对齐头和 η | 否 | η 必须在登记时冻结（架构第 152 行），现在未查到冻结值 | 缺的是设计和一次训练，不是文件 |
| RLT 的 MLX 路径和冻结 τ | 否 | τ 要在登记时冻结 | numpy 参考已验收。训练接线未做 |
| E6 真实视频 | 要下载 | 要。架构第 330 行和开题第 3657 行都把真实视频数据排除在这次批准之外 | 不能。盘上未查到真实视频数据集 |
| CC-BY 素材进训练 | 未查到需要新下的 CC-BY 包 | 即使用户以后想用，也要另批。当前库没有 CC-BY 行 | 不靠 CC-BY 也能讨论现有文件，但现有文件自己的许可正文大多未找到 |
| Rose / 来源不在白名单的角色渲染 | 否 | 要。库中 revision 2 已是 `license_pending` | 不能把 Rose 渲染放进训练 |
| 对象 ID 不泄露的视觉路径 | 否 | 视觉输入上的泄露测试还没有，因为没有视觉学生 | S1/E1 的结构化禁真值规则不能代替像素路径的测试 |
| E4 完整成本（提取 + 数据生成的小时与电量） | 否 | 跑 E4 要另登记 | 现在只有 T4 的推理速率，没有端到端 E4 |

参数意见（不改 v0）：P5 卡面「训练预算待用户批准」与 `R20261111-S5-start` 已经批准的范围不一致。一级写设计稿时应以开题那一节的排除项为准，并补上还没冻结的格子预算。

## 未查到（不补写）

- DA2、DA3 权重目录内的许可文件。
- 资产旁边的 CC0 / CC-BY 法律文本。
- V-JEPA、DA2 的已落盘训练特征缓存。
- DA3 稳态吞吐和内存峰值。
- 视觉学生编码器的训练步计时，以及教师与学生同进程常驻内存。
- 真实短视频数据（E6）。
- S5 的冻结 τ、η、种子和每格小时上限。
