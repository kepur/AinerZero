# ainerzero.V9.T6 执行命令清单（r4 真实标定与中央 CLI 闭环）

工作目录：`/Users/mac/AinerWorkFlow/AinerZero`

## 1. 受控中央 CLI 审查命令（只读，零锁零写）

```bash
PYTHONPATH=src python3 -m ainerzero.cli teacher-da3 \
  --mode inspect \
  --statistical-protocol reports/V9-T6/r2-calib-fixtures/statistical_protocol.json \
  --wall-budget-seconds 200.0 \
  --views 18
```
- 返回码：`rc=0`
- 输出证明：`can_run: true`, `is_approved: true`, `remaining_cumulative_seconds: 290.0`, `views: 18 <= 64`。

## 2. 受控中央 CLI 真实执行命令（生产共享锁 + 中央 RunStore + 进程组监督）

```bash
PATH="/tmp/t6_pmset:$PATH" T6_RUN_REAL_CALIBRATION=1 PYTHONPATH=src python3 -m ainerzero.cli teacher-da3 \
  --mode run \
  --statistical-protocol reports/V9-T6/r2-calib-fixtures/statistical_protocol.json \
  --wall-budget-seconds 200.0 \
  --views 18 \
  --allow-model-execution \
  --coordinator-release
```
- 返回码：`rc=0`
- 运行 ID：`9d06ce9f8c5c4f99a828057b3df8ed18`
- 请求 ID：`t6-da3-9d06ce9f8c5c4f99a828057b3df8ed18`
- 状态：`completed`
- 预留预算：`200.0s`，累计预留：`1110.0s <= 1200.0s` 上限
- 累计视图：`63 <= 64` 上限
- 共享锁：`artifacts/locks/m0-worker.lock`（独占排他）
- 账本：`artifacts/v9/teachers/benchmark/runs.db`（流转 `created -> initializing -> validating -> completed`）
- 监督指标：`worker_pid=92409, worker_pgid=92409, empty_group_proven=True, returncode=0`

## 3. 真实 DA3 MPS 标定与推理产物生成（18 视图全量张量）

```bash
KMP_DUPLICATE_LIB_OK=TRUE envs/teachers/.venv-t6/bin/python envs/teachers/t6/real_da3_worker.py \
  --output reports/V9-T6/r4/calibration_evidence.json \
  --predictions-dir reports/V9-T6/r4/predictions
```
- 返回码：`rc=0`
- 实际总墙钟：`10.68s`（远低于 200.0s / 1200.0s 预算）
- 产物目录：`reports/V9-T6/r4/predictions/`
- 清单文件：`reports/V9-T6/r4/predictions/predictions_manifest.json`（60 个文件，109,777,368 字节，SHA256: `7d5b700703927322e60b3647f60af170f3b0be271d9baa46fac6faf27cb369ec`）
- 包括：
  - DA3-SMALL：6 房间 × `prediction.safetensors` + 6 房间 × `candidate.json` + 18 视图 × `view_*.safetensors`
  - DA3-BASE：6 房间 × `prediction.safetensors` + 6 房间 × `candidate.json` + 18 视图 × `view_*.safetensors`

## 4. 21 项回归测试与 4 组物理源码变异对照

```bash
# 21 项单元测试
envs/teachers/.venv-t6/bin/python -m unittest discover -s envs/teachers/t6/tests/ -p "test_r2.py"
# 返回码：0，21 测试全绿，用时 0.69s

# 4 组源码变异对抗测试
envs/teachers/.venv-t6/bin/python envs/teachers/t6/tests/run_mutations_r2.py
# 返回码：0，4 项变异均变红拦截
```
