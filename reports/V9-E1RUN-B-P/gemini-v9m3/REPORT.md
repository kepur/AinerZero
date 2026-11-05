# 任务 ainerzero.V9.P100 执行报告：E1 运行卡 B-P（训练 P 族 9 格）

- **任务卡号**：`ainerzero.V9.P100`
- **执行者**：`gemini-v9m3`（二级执行 agent，Tier 2）
- **实验阶段**：AinerZero V9 E1 Phase 2（P 族 9 格串行训练）
- **执行原则**：严格串行、CLI 唯一入口、relay exec 进程组监督、显式按格预留、严格防撞熔断守卫、零 final-eval、零源码修改
- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261029-E1-approval`（第 2106 行），预算 `R20261102-E1-go-ahead`（5 h），预留与顺序裁定 `R20261103-E1-reservation-budget`

---

## 一、前置环境与身份校验（Pre-flight Verify）

在正式启动训练前，通过 `relay exec` 运行了前置校验命令：
```bash
relay exec ainerzero.V9.P100 --agent gemini-v9m3 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode verify
```
校验结果全绿通过：
- `status`: `verified`
- `document_sha256`: `db75d096a048b505718690c6aec4d4f8a4d2cede4d0b32658fd395eb7c5beafd`
- `approval.status`: `approved`（行号 2106）
- `identity.status`: `passed`（16 个源代码模块与 8 个生成器代码 SHA-256 校验全部匹配）

---

## 二、P 族 9 格训练执行汇总表

严格按照一级参数 `budget_override_20261103` 规定的重型优先顺序执行：
`(6,42) -> (6,43) -> (6,44) -> (2,42) -> (2,43) -> (2,44) -> (3,42) -> (3,43) -> (3,44)`。

| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 熔断线 (s) | 退出码 | 步数 (总/最佳/早停) | 均值损失 | 终值损失 | Checkpoint 权重 SHA-256 (前16位) | 状态 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| 1 | (6, P, 42) | `b32b21a8..` | 1100 | 842.8 | 1000.0 | 0 | 30500 / 25500 / 30500 | 0.7395 | 0.1417 | `7f3a0bd12df18443..` | completed |
| 2 | (6, P, 43) | `249854a5..` | 1100 | 965.8 | 1000.0 | 0 | 48000 / 43000 / 48000 | 0.7100 | 0.0107 | `de7b4f1b5bd9ed5f..` | completed |
| 3 | (6, P, 44) | `f5a2977c..` | 1100 | 962.6 | 1000.0 | 0 | 43500 / 38500 / 43500 | 0.7453 | 0.0025 | `9af47cebdd4d9f6e..` | completed |
| 4 | (2, P, 42) | `45842889..` | 450 | 191.0 | 400.0 | 0 | 35500 / 30500 / 35500 | 0.1446 | 0.8450 | `54b91b53af2197cd..` | completed |
| 5 | (2, P, 43) | `8a955e03..` | 450 | 304.5 | 400.0 | 0 | 56000 / 51000 / 56000 | 0.1297 | 0.0068 | `3377c451d2589fee..` | completed |
| 6 | (2, P, 44) | `0c975ab1..` | 450 | 206.6 | 400.0 | 0 | 41500 / 36500 / 41500 | 0.1386 | 0.0143 | `fa3190b28a265467..` | completed |
| 7 | (3, P, 42) | `5baaa702..` | 450 | 137.8 | 400.0 | 0 | 23500 / 18500 / 23500 | 0.5389 | 0.2075 | `828bab7db46828e4..` | completed |
| 8 | (3, P, 43) | `8c9aa881..` | 450 | 210.7 | 400.0 | 0 | 33500 / 28500 / 33500 | 0.5103 | 0.9309 | `554c9b7d53580d0b..` | completed |
| 9 | (3, P, 44) | `0d660578..` | 450 | 206.3 | 400.0 | 0 | 33500 / 28500 / 33500 | 0.5051 | 0.0628 | `0810062679309818..` | completed |

---

## 三、完整 Checkpoint 产物与 SHA-256 凭证

所有 Checkpoint 均按规格写入 `artifacts/v9/e1/phase2/checkpoints/` 且包含 `model_weights.npz`、`normalization.npz` 与 `checkpoint_meta.json`：

### 单元 (6, P, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_P_seed42`
- **model_weights.npz SHA-256**：`7f3a0bd12df18443b4ba8fa36ebc9f87007930c4b62549cfe4a82efbcb73b925`
- **normalization.npz SHA-256**：`1aab6fb34ba767d7ed0d8b72b41567999a110acdfea5c2d1bd266fab38bdeb84`
- **run_id**：`b32b21a8d90c414ab070441537981e40`
- **best_step**：`25500`，**stopped_step**：`30500`（早停机制触发生效）

### 单元 (6, P, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_P_seed43`
- **model_weights.npz SHA-256**：`de7b4f1b5bd9ed5f2b125cc5a75d93eb1a02da3d61226c35e5a956c7b698f391`
- **normalization.npz SHA-256**：`d82810a2cfe149256c803f4c2bbe5e1ef9ab75af2830d4fdd1a3b04c5c80c7f7`
- **run_id**：`249854a555c8493095d63865ec21504f`
- **best_step**：`43000`，**stopped_step**：`48000`（早停机制触发生效）

### 单元 (6, P, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_P_seed44`
- **model_weights.npz SHA-256**：`9af47cebdd4d9f6e11172849e5b7bfbbfa4c4f8eff8d2c871dd72535944632ef`
- **normalization.npz SHA-256**：`a4f89b400bf7b34ba2e281cb45d6f92f8d5c1462cb6946eeab96b732cabdb39a`
- **run_id**：`f5a2977c754e46c48353d81d2be284f7`
- **best_step**：`38500`，**stopped_step**：`43500`（早停机制触发生效）

### 单元 (2, P, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_P_seed42`
- **model_weights.npz SHA-256**：`54b91b53af2197cd977ea70eb1ee8677c2d5e6fbb3d232996dbb2f606a71e287`
- **normalization.npz SHA-256**：`5ed265a63e667394ea7991c1b26c9f00250db0729116f1bc0d65690a66188ad5`
- **run_id**：`45842889943c449ab144a8a8f68bf8cd`
- **best_step**：`30500`，**stopped_step**：`35500`（早停机制触发生效）

### 单元 (2, P, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_P_seed43`
- **model_weights.npz SHA-256**：`3377c451d2589fee2ae5bb3ba46f5d34846751d3843bab0a55a016bceaf66dc6`
- **normalization.npz SHA-256**：`3deb756a558c9107d15131ce9a054ce1832b1a79e72e77c45ddee33eb1eea9be`
- **run_id**：`8a955e03955c4e3a890336122f22a58a`
- **best_step**：`51000`，**stopped_step**：`56000`（早停机制触发生效）

### 单元 (2, P, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_P_seed44`
- **model_weights.npz SHA-256**：`fa3190b28a2654677192358b0eedabc15fb7f486c8219c464b9dcaebee4b5ddb`
- **normalization.npz SHA-256**：`54d71079de5c9bfd26824b9a87dff9a7c3d78c3ee4763efba031e299babcc55d`
- **run_id**：`0c975ab139a64b62b7d5b6fc7ea9c964`
- **best_step**：`36500`，**stopped_step**：`41500`（早停机制触发生效）

### 单元 (3, P, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_P_seed42`
- **model_weights.npz SHA-256**：`828bab7db46828e483169b56408596f052264f6a77592fb0152adc97ab964dde`
- **normalization.npz SHA-256**：`511b56f8b17f87752787a4caea154528a5e93e9c3a0241f7e3fd138d925b24ff`
- **run_id**：`5baaa702770c49b39046ecd896d2a74a`
- **best_step**：`18500`，**stopped_step**：`23500`（早停机制触发生效）

### 单元 (3, P, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_P_seed43`
- **model_weights.npz SHA-256**：`554c9b7d53580d0bb34806a6a7bf6049e868f231a1fcd34b527eeb5b28c886dc`
- **normalization.npz SHA-256**：`fee01eafb69aa96d3e4ea07f2075fb235dfd96cdcdd54f0ed2f02a0a628b4fb9`
- **run_id**：`8c9aa881822d4c1ea6130230fdc0a93a`
- **best_step**：`28500`，**stopped_step**：`33500`（早停机制触发生效）

### 单元 (3, P, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_P_seed44`
- **model_weights.npz SHA-256**：`08100626793098185ea9f95448fce87a04bee573a6a31e82be0cf43ad88a8d8b`
- **normalization.npz SHA-256**：`fee01eafb69aa96d3e4ea07f2075fb235dfd96cdcdd54f0ed2f02a0a628b4fb9`
- **run_id**：`0d6605781b98413a947a9a763b448647`
- **best_step**：`28500`，**stopped_step**：`33500`（早停机制触发生效）

---

## 四、预算管理与防撞熔断守卫验证

1. **防撞熔断守卫**：
   - 臂 6 阈值 1000s：实际分别为 842.8s、965.8s、962.6s，全部低于 1000s 保护线。
   - 臂 2/3 阈值 400s：实际分别为 191.0s、304.5s、206.6s、137.8s、210.7s、206.3s，全部低于 400s 保护线。
   - 9 格实际总运行墙钟：**4028.1s**（约 67.1 分钟）。

2. **中央账本累计预留额度核对（`artifacts/v9/e1/phase2/control.sqlite3`）**：
   - 数据生成卡 P98 预留：`3600.0s`
   - 本卡 P100 训练 9 格预留：`3 × 1100s + 6 × 450s = 6000.0s`
   - 当前账本累计预留 active_seconds：`9600.0s`
   - 阶段实验总上限：`18000.0s`（5 小时），完全处于上限安全范围内（剩余额度 `8400.0s`，足够后续 S 族 9 格与 dev 评测）。

3. **共享锁状态核对**：
   - 锁文件 `artifacts/locks/m0-worker.lock` 在每格训练间歇及 9 格训练结束后均已自动释放，内容为空，无任何进程挂留。

---

## 五、消极声明（未做事项）

按照规范与安全守则，严正声明：
1. **绝对零 final-eval**：未执行任何 `--mode final-eval` 命令。
2. **绝对零封存数据触碰**：未以任何方式读取或打开 `artifacts/v9/e1/phase2/datasets/sealed_final/` 下的数据文件。
3. **绝对零源码修改**：未修改 `src/`、`tests/`、`prereg.json` 或 `RESEARCH_LOG.md`。
4. **唯一入口**：所有训练均由 `.venv/bin/python -m ainerzero.cli e1-phase2` 权威入口触发，并由 `relay exec` 绑定监督拉起，未绕过 CLI，未另起未监督进程。
5. **无云 GPU/付费/外部依赖**：全部计算在本机单实例串行完成，无外部下载与网络请求。

