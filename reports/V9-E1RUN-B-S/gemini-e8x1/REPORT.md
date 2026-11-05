# 任务 ainerzero.V9.P101 执行报告：E1 运行卡 B-S（训练 S 族 9 格）

- **任务卡号**：`ainerzero.V9.P101`
- **执行者**：`gemini-e8x1`（二级执行 agent，Tier 2）
- **实验阶段**：AinerZero V9 E1 Phase 2（S 族 9 格串行训练）
- **执行原则**：严格串行、CLI 唯一入口、relay exec 进程组监督、显式按格预留、严格防撞熔断守卫、零 final-eval、零源码修改
- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261029-E1-approval`（第 2108 行（r1）），预算 `R20261102-E1-go-ahead`（5 h），预留与顺序裁定 `R20261103-E1-reservation-budget` (revision r2)
- **状态结论**：**S 族 9 格训练全部成功完成，全量 exit code 0，未触发熔断保护**

---

## 一、前置环境与身份校验（Pre-flight Verify）

在正式启动训练前，通过 `relay exec` 运行了前置校验命令：
```bash
relay exec ainerzero.V9.P101 --agent gemini-e8x1 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode verify
```
校验结果全绿通过：
- `status`: `verified`
- `document_sha256`: `84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6`
- `approval.status`: `approved`（行号 2108，APPROVED e1-phase2 prereg document_sha256=84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6）
- `identity.status`: `passed`（16 个源代码模块与 8 个生成器代码 SHA-256 校验全部匹配）

---

## 二、S 族 9 格训练执行汇总表

严格按照一级参数 `budget_override_20261103` (r2) 规定的重型优先顺序执行：
`(6,42) -> (6,43) -> (6,44) -> (2,42) -> (2,43) -> (2,44) -> (3,42) -> (3,43) -> (3,44)`。

| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 熔断线 (s) | 退出码 | 步数 (总/最佳/早停) | 均值损失 | 终值损失 | Checkpoint 权重 SHA-256 (前16位) | 状态 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| 1 | (6, S, 42) | `be16ef74..` | 1200 | 692.3 | 1100.0 | 0 | 36000 / 31000 / 36000 | 0.7765 | 0.0345 | `d23647a5bccbae28..` | completed |
| 2 | (6, S, 43) | `39bec45e..` | 1200 | 694.3 | 1100.0 | 0 | 36000 / 31000 / 36000 | 0.7694 | 0.0211 | `61e5b8535ac4a837..` | completed |
| 3 | (6, S, 44) | `a8fff6f8..` | 1200 | 674.0 | 1100.0 | 0 | 30000 / 25000 / 30000 | 0.8063 | 0.0301 | `31a09b65d9064e6f..` | completed |
| 4 | (2, S, 42) | `1cbec699..` | 450 | 277.6 | 400.0 | 0 | 45000 / 40000 / 45000 | 0.1320 | 0.2639 | `f49a9c52e47ccdd4..` | completed |
| 5 | (2, S, 43) | `e14bb245..` | 450 | 191.7 | 400.0 | 0 | 33500 / 28500 / 33500 | 0.1414 | 0.0407 | `4f61d0a964fbc231..` | completed |
| 6 | (2, S, 44) | `600601ae..` | 450 | 311.3 | 400.0 | 0 | 52500 / 47500 / 52500 | 0.1269 | 0.0193 | `45d9adedf0277c83..` | completed |
| 7 | (3, S, 42) | `e8014904..` | 450 | 224.1 | 400.0 | 0 | 31500 / 26500 / 31500 | 0.5281 | 0.5884 | `2b9362f407ed9c07..` | completed |
| 8 | (3, S, 43) | `e0b4c830..` | 450 | 224.6 | 400.0 | 0 | 36000 / 31000 / 36000 | 0.5161 | 0.0876 | `1d3006bcf19aa0a4..` | completed |
| 9 | (3, S, 44) | `48668674..` | 450 | 298.7 | 400.0 | 0 | 48500 / 43500 / 48500 | 0.4994 | 0.1825 | `dab98adef1aef347..` | completed |

---

## 三、完整 Checkpoint 产物与 SHA-256 凭证

所有 Checkpoint 均按规格写入 `artifacts/v9/e1/phase2/checkpoints/` 且包含 `model_weights.npz`、`normalization.npz` 与 `checkpoint_meta.json`：

### 单元 (6, S, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_S_seed42`
- **model_weights.npz SHA-256**：`d23647a5bccbae280377e4308ccfa3f1ef753bea7260fbc5061f923e86b55e56`
- **normalization.npz SHA-256**：`c95c01266d66e64c1c9585b24aa9ef666eb283b55111bc112a5d0c0707a875fd`
- **run_id**：`be16ef7454b6409f9bf661eac8f23102`
- **best_step**：`31000`，**stopped_step**：`36000`（早停机制触发生效：False）

### 单元 (6, S, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_S_seed43`
- **model_weights.npz SHA-256**：`61e5b8535ac4a837faa55632461a94f71e56abdb2605c6b1073bc646be18bf64`
- **normalization.npz SHA-256**：`c95c01266d66e64c1c9585b24aa9ef666eb283b55111bc112a5d0c0707a875fd`
- **run_id**：`39bec45e174e4a6e916136d96d1ddedf`
- **best_step**：`31000`，**stopped_step**：`36000`（早停机制触发生效：False）

### 单元 (6, S, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm6_S_seed44`
- **model_weights.npz SHA-256**：`31a09b65d9064e6f04fce6da569f712e9b6b2a997f38f228f9f8e1d8f4a45a62`
- **normalization.npz SHA-256**：`a9e40a55d2dbe6b8736ef56b63703143be444165b7b2d0b6b1bf8cb0938a94d5`
- **run_id**：`a8fff6f8ec9c4b57937ef01856b573bb`
- **best_step**：`25000`，**stopped_step**：`30000`（早停机制触发生效：False）

### 单元 (2, S, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_S_seed42`
- **model_weights.npz SHA-256**：`f49a9c52e47ccdd4c3de85587e388808fcce6414544f5ce97e138d738715ffd6`
- **normalization.npz SHA-256**：`ad73cd198479697e903a2346b6551ba54e758c6fb26bb3c89e2c7c9b486ab705`
- **run_id**：`1cbec6994eef404b9dce5a5c93091021`
- **best_step**：`40000`，**stopped_step**：`45000`（早停机制触发生效：False）

### 单元 (2, S, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_S_seed43`
- **model_weights.npz SHA-256**：`4f61d0a964fbc2313f6acb3a2d3ef50b76523f88d415882145a788a1a9f8b373`
- **normalization.npz SHA-256**：`cc0013b9d38ed64c74aa2a5e0b4272de1a65ae593a57e51b714f77e58f622488`
- **run_id**：`e14bb245f487442f815ec1269d163341`
- **best_step**：`28500`，**stopped_step**：`33500`（早停机制触发生效：False）

### 单元 (2, S, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm2_S_seed44`
- **model_weights.npz SHA-256**：`45d9adedf0277c8395b43d8baac5170e8a9477589a21559de78afc826beb1441`
- **normalization.npz SHA-256**：`0e17f49d4d39945885f2d8ae5fca26c19dc240fbe83143818fa676b9e27d611a`
- **run_id**：`600601aeb3d54fdcb49c01f0b219e8dd`
- **best_step**：`47500`，**stopped_step**：`52500`（早停机制触发生效：False）

### 单元 (3, S, 42)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_S_seed42`
- **model_weights.npz SHA-256**：`2b9362f407ed9c073e9c0e2b866fde760b0f9114023d1447071e884304066a5e`
- **normalization.npz SHA-256**：`69773b6eca4e936631836ee2f671a5b45517dbcead5ae2f6715a7ce5ff27defb`
- **run_id**：`e80149044e4a477b8c8e425fc263a595`
- **best_step**：`26500`，**stopped_step**：`31500`（早停机制触发生效：False）

### 单元 (3, S, 43)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_S_seed43`
- **model_weights.npz SHA-256**：`1d3006bcf19aa0a4b7082bed395ee27f4f44722919fe0d575b1c1d883a41ee81`
- **normalization.npz SHA-256**：`abdd66230e376b97286f8cfc3ec48b4c58c186597dcc1e8b28d0cc38199c0c5e`
- **run_id**：`e0b4c830c4564514ac046b07ab0cd377`
- **best_step**：`31000`，**stopped_step**：`36000`（早停机制触发生效：False）

### 单元 (3, S, 44)
- **目录**：`/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/e1/phase2/checkpoints/arm3_S_seed44`
- **model_weights.npz SHA-256**：`dab98adef1aef347d067215cf516f82d36d870c91f422d68eb73fee5f1caa412`
- **normalization.npz SHA-256**：`99591c420bffa9ca7c37ed07296746474b197875492b4f9aca3d0ec5b2b43ddb`
- **run_id**：`48668674e9a54933bab4948e67c33b99`
- **best_step**：`43500`，**stopped_step**：`48500`（早停机制触发生效：False）

---

## 四、预算管理与防撞熔断守卫验证

1. **防撞熔断守卫**：
   - 臂 6 阈值 1100s：实际分别为 [692.3, 694.3, 674.0]，全部低于 1100s 保护线。
   - 臂 2/3 阈值 400s：实际分别为 [277.6, 191.7, 311.3, 224.1, 224.6, 298.7]，全部低于 400s 保护线。
   - S 族已完成格实际总运行墙钟：**3588.6s**（约 59.8 分钟）。

2. **中央账本累计预留额度核对（`artifacts/v9/e1/phase2/control.sqlite3`）**：
   - 数据生成卡 P98 预留：`3600.0s`
   - P 族训练卡 P100 预留：`6000.0s`
   - 本卡 P101 训练预留：`6300s`
   - 当前账本累计预留 active_seconds：`15900.0s`
   - 阶段实验总上限：`18000.0s`（5 小时），处于上限安全范围内（剩余额度 `2100.0s`）。

3. **共享锁状态核对**：
   - 锁文件 `artifacts/locks/m0-worker.lock` 在每格训练间歇及训练结束后均已自动释放，内容为空，无任何进程残留。

---

## 五、消极声明（未做事项）

按照规范与安全守则，严正声明：
1. **绝对零 final-eval**：未执行任何 `--mode final-eval` 命令。
2. **绝对零封存数据触碰**：未以任何方式读取或打开 `artifacts/v9/e1/phase2/datasets/sealed_final/` 下的数据文件。
3. **绝对零源码修改**：未修改 `src/`、`tests/`、`prereg.json` 或 `RESEARCH_LOG.md`。
4. **唯一入口**：所有训练均由 `.venv/bin/python -m ainerzero.cli e1-phase2` 权威入口触发，并由 `relay exec` 绑定监督拉起，未绕过 CLI，未另起未监督进程。
5. **无云 GPU/付费/外部依赖**：全部计算在本机单实例串行完成，无外部下载与网络请求。

