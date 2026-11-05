# 任务 ainerzero.V9.P101 执行报告：E1 运行卡 B-S（训练 S 族 9 格）

- **任务卡号**：`ainerzero.V9.P101`
- **执行者**：`gemini-v9s1`（二级执行 agent，Tier 2）
- **实验阶段**：AinerZero V9 E1 Phase 2（S 族 9 格串行训练）
- **执行原则**：严格串行、CLI 唯一入口、relay exec 进程组监督、显式按格预留、严格防撞熔断守卫、零 final-eval、零源码修改
- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261029-E1-approval`（第 2106 行），预算 `R20261102-E1-go-ahead`（5 h），预留与顺序裁定 `R20261103-E1-reservation-budget` (revision r2)
- **状态结论**：**格 1 准入被拒（Budget exhausted: experiment_wall_seconds_budget），按第 4 条规则立即停下交回，不重试，不调参**

---

## 一、前置环境与身份校验（Pre-flight Verify）

在正式启动训练前，通过 `relay exec` 运行了前置校验命令：
```bash
relay exec ainerzero.V9.P101 --agent gemini-v9s1 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode verify
```
校验结果全绿通过：
- `status`: `verified`
- `document_sha256`: `db75d096a048b505718690c6aec4d4f8a4d2cede4d0b32658fd395eb7c5beafd`
- `approval.status`: `approved`（行号 2106）
- `identity.status`: `passed`（16 个源代码模块与 8 个生成器代码 SHA-256 校验全部匹配）

---

## 二、S 族 9 格训练执行汇总表

严格按照一级参数 `budget_override_20261103` (r2) 规定的重型优先顺序执行：
`(6,42) -> (6,43) -> (6,44) -> (2,42) -> (2,43) -> (2,44) -> (3,42) -> (3,43) -> (3,44)`。

| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 熔断线 (s) | 退出码 | 步数 (总/最佳/早停) | 均值损失 | 终值损失 | Checkpoint 权重 SHA-256 (前16位) | 状态 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| 1 | (6, S, 42) | `—` | 1200 | 0.6 | 1100.0 | 1 | — / — / — | — | — | `—` | **rejected** (Budget exhausted) |
| 2 | (6, S, 43) | `—` | 1200 | — | 1100.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 3 | (6, S, 44) | `—` | 1200 | — | 1100.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 4 | (2, S, 42) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 5 | (2, S, 43) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 6 | (2, S, 44) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 7 | (3, S, 42) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 8 | (3, S, 43) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |
| 9 | (3, S, 44) | `—` | 450 | — | 400.0 | — | — / — / — | — | — | `—` | skipped (停下不跑) |

---

## 三、格 1 执行失败与被拒详情（Failure & Root Cause Analysis）

### 1. 执行命令与原始退出输出
- **命令**：
  ```bash
  relay exec ainerzero.V9.P101 --agent gemini-v9s1 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode train --arm 6 --family S --seed 42 --wall-budget-seconds 1200
  ```
- **耗时**：0.568 秒
- **退出码**：`1`
- **stdout JSON 原文**：
  ```json
  {
    "status": "failed",
    "mode": "train",
    "stage": "execution_failed",
    "message": "Budget exhausted: experiment_wall_seconds_budget"
  }
  ```

### 2. 根因剖析（Root Cause Analysis）
- 中央账本数据库：`artifacts/v9/e1/phase2/control.sqlite3`
- 实验记录：`experiments` 表中 `experiment_id = "e1-phase2-20261029-r0"`
  - `created_at`: `1793661008.024385`（对应本地时间 `2026-11-03 01:10:08`）
  - 实验登记预算：`max_wall_seconds: 18000.0`（即 5 小时物理日历窗口）
- 依据中央生命周期守卫源码 `src/ainerzero/runtime/lifecycle.py`（第 433–437 行与第 587–593 行）：
  ```python
  remaining.update(
      wall_seconds=max(
          0.0,
          budget["max_wall_seconds"]
          - max(0.0, instant - row["created_at"], totals["active_seconds"]),
      ),
      ...
  )
  ...
  if experiment.remaining["wall_seconds"] <= 0:
      rejection = BudgetExceeded("experiment_wall_seconds_budget", experiment.remaining)
  ```
- 在本次执行时刻 `2026-11-03 11:10:18`，距实验创建时刻已过去 **36010 秒**（约 10 小时），超过了实验清单中的 `max_wall_seconds = 18000.0`。因此 `remaining["wall_seconds"] = 0.0`，在准入阶段即被中央守卫抛出 `BudgetExceeded("experiment_wall_seconds_budget")`。
- **与 active_seconds 的关系**：中央账本中已预留的 `active_seconds` 累计为 `9600.0s`（数据生成 P98 预留 3600s + P 族训练 P100 预留 6000s），原本在 `18000.0s` 算力预算内尚有 `8400.0s` 额度可用。但因为实验对象注册时间是凌晨 01:10，距离现在的日历墙钟超过了 5 小时限制。

### 3. 执行规则遵循与停跑
依据任务卡规则第 4 条：
> **“4. 任何一格被拒（例如 `phase_budget_exceeded` 或 `lock_busy`）或失败：停下，不重试，交回已完成的格。”**
> **“任何一格失败、被拒或超时：不重试、不调参，保留原样，在卡上说明后交回（只交已完成部分）。重跑须由一级登记。”**

执行者严格遵循规则，不私自修改数据库 `created_at`、不调参、不改动任何源码，立即停下并交回。

---

## 四、预算管理与防撞熔断守卫验证

1. **共享锁状态核对**：
   - 锁文件 `artifacts/locks/m0-worker.lock` 确认已处于完全释放状态（大小 0 字节），无任何遗留进程。
2. **中央账本状态**：
   - 当前账本累计 `active_seconds`：`9600.0s`，包含已完成的 10 个运行（1 个数据生成 + 9 个 P 族训练）。格 1 未能在数据库创建运行记录，账本保持原样。

---

## 五、消极声明（未做事项）

按照规范与安全守则，严正声明：
1. **绝对零 final-eval**：未执行任何 `--mode final-eval` 命令。
2. **绝对零封存数据触碰**：未以任何方式读取或打开 `artifacts/v9/e1/phase2/datasets/sealed_final/` 下的数据文件。
3. **绝对零源码与数据库篡改**：未修改 `src/`、`tests/`、`prereg.json`、`RESEARCH_LOG.md`，亦未擅自修改 `control.sqlite3` 的 `created_at` 绕过预算守卫。
4. **唯一入口**：所有调用均通过 `.venv/bin/python -m ainerzero.cli e1-phase2` 权威入口触发，并由 `relay exec` 监督拉起。
5. **不私自重试**：失败被拒后严格按要求立即停止，交回报告等待一级裁定与重整。
