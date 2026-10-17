# AnimeWorld Zero（AWZ）

一个确定性的日漫世界：同一个 3D 角色在持续存在的世界里活动，用线条渲染出片。人物始终一致，可以换风格、换色调、出多语言版本，每秒画面的成本以秒计算。同一个世界也给 [AinerZero](https://github.com/kepur/AinerZero) 提供带真值、可封存的时间、空间和语义经验，先用来考它，经批准后才用来训练。

**现在的阶段：R1 —— 只做 T00–T05 加 W0，不训练神经网络。** 第一目标是可重复渲染的 30 秒、480p、24 FPS 黑白线条动画（Gate A）。

## 文档地图

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 总体架构 v1.1（主文档） |
| [docs/ACIS.md](docs/ACIS.md) | 人物身份系统：身份锁定、视角形变、480p 脸部细节分级、身份校验 |
| [docs/PERFORMANCE.md](docs/PERFORMANCE.md) | 台词、配音、口型：日漫 5 种口型，时间线跟着配音伸缩 |
| [docs/NOVEL_TO_WORLD.md](docs/NOVEL_TO_WORLD.md) | 对接 AinerHub 小说翻译系统（`ainer.scene/v1`） |
| [docs/AINERZERO_BRIDGE.md](docs/AINERZERO_BRIDGE.md) | 与 AinerZero 的接口：只导出 → 只评测 → 批准后才训练 |
| [docs/adr/](docs/adr/) | 决策记录 ADR-0001–0008 |
| [contracts/](contracts/) | JSON Schema：episode v1、人物身份包 v1、风格包 v1，以及样例 |
| [docs/spec/](docs/spec/) | 用户原始规范 v1.0（存档不改） |
| [docs/design/](docs/design/) | 实施前设计报告（grokbot-newbot，只读调研） |
| [AGENT_TASKS.md](AGENT_TASKS.md) | R1 任务卡（可领取） |
| [COORDINATION.md](COORDINATION.md) / [AGENTS.md](AGENTS.md) | 分工与工作规则 |
| [RESEARCH_LOG.md](RESEARCH_LOG.md) | 用户决定、统筹决定、事实依据 |

## 关键决定（详见 ADR）

| 项 | 决定 |
|---|---|
| 引擎 | Godot 4.7.2；Jolt 只管仅视觉的运动；人物移动和碰撞用解析方式 |
| 真值 | 只在 Python 世界内核里，Godot 按状态日志回放渲染 |
| 时间 | 模拟 120Hz（能被 24/12/30/60fps 整除）；三个时钟；计数式 RNG |
| 渲染 | 禁用 TAA 和时序效果；2 倍超采样；PNG 序列再用 VideoToolbox 编码 |
| 数据来源 | 渲染数据算 `external_derived`；辅助类型用枚举，对齐 AinerZero；许可只收自产和 CC0；分区为 train/development/final/quarantine |
| GPU | 同一时刻只跑一个重任务；AinerZero 锁被占时直接放弃，不等待 |
| 人物 | ACIS 身份包不可变、状态可变；调色板锁定；网络只能在约束内修饰外观 |

## 目录（按任务逐步建立）

```text
contracts/                 # 语言中立的数据契约
docs/                      # 架构、ADR、规范、设计报告
python/animeworld/         # kernel（世界内核）、data（episode、切分、来源）
python/worldbrain/         # baselines、eval（R1 只做 W0）
godot/                     # Godot 4.7.2 项目：world_player、environment、render
assets/identities/         # ACIS 身份包与注册表（自产或 CC0）
tools/                     # check.sh、locks.py、env_report.py、render 工具
tests/                     # 只跑 CPU 的测试
reports/<task_id>/         # 执行报告与证据（小文件）
datasets/  experiments/    # 不可变数据与运行产物（不进 git）
```

## 本机

Apple M2 Max · 96GB 统一内存 · macOS 27.2 · Godot 4.7.2（`/Applications/Godot.app`）· Blender 5.2.2 · Python 3.12。所有性能数字写实测值。
