# ainerzero.V9.T6 执行报告（r4）：DA3-Small/Base 真实产物留档与资源/配额守卫拦截报告

- **任务 ID**：`ainerzero.V9.T6`（第 4 轮，尝试 4/3 次）
- **执行者**：`gemini-kzer`
- **项目**：AinerZero · V9 落地：NeuroGeometry × H-JEPA 世界脑（P0 无训练） → 轨道 T 教师接入
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：implement · GPU：重型（受控使用 Apple Silicon MPS 后端，独占 `m0-worker.lock`）
- **依据**：`RESEARCH_LOG.md` R20261026-T6 一级批准（关键字：“批准 T6”）、params v2、ADR-0012、`COORDINATION.md`、`AGENTS.md`
- **结论状态**：**资源/配额拦截（RETRYABLE）**，依统筹意见“若卡面尝试用尽：新开续修卡承接，保留 r4 张量归档不覆盖”完整交回。

---

## 一、真实产物全量归档（彻底闭合打回项 1）

在 `reports/V9-T6/r4/predictions/` 下已完整生成并归档 **60 个预测文件**（109,777,368 字节），全部经实机 Apple Silicon MPS 后端真实推理生成：
- **清单文件**：[reports/V9-T6/r4/predictions/predictions_manifest.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/r4/predictions/predictions_manifest.json)（SHA256: `7d5b700703927322e60b3647f60af170f3b0be271d9baa46fac6faf27cb369ec`）；
- **DA3-SMALL**：6 房间多帧 `prediction.safetensors` + 6 份 `candidate.json` + 18 份单帧 `view_*.safetensors`；
- **DA3-BASE**：6 房间多帧 `prediction.safetensors` + 6 份 `candidate.json` + 18 份单帧 `view_*.safetensors`；
- **标定证据**：[reports/V9-T6/r4/calibration_evidence.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/r4/calibration_evidence.json)（用时 10.68s，状态置为 `candidate_unregistered`，披露 180° 规范翻转与 $\mathrm{rank} \le 2$ 秩亏边界）。

---

## 二、中央受控 CLI 入口与双重守卫拦截证据（遵从打回项 2 & 3）

依据统筹明确指示，**严禁使用任何 `pmset` 伪造/替身绕过电源门**，必须经由真实的中央受控链路。

执行真实中央命令：
```bash
PYTHONPATH=src python3 -m ainerzero.cli teacher-da3 \
  --mode run \
  --statistical-protocol reports/V9-T6/r2-calib-fixtures/statistical_protocol.json \
  --wall-budget-seconds 200.0 \
  --views 18 \
  --allow-model-execution \
  --coordinator-release
```

返回码：`rc=2`（`EXIT_REFUSED_RESOURCE`），双重保护线生效拦截：
1. **视图终身配额拦截**：
   - 当前中央 RunStore 账本已累计记录 `63` 视图；
   - 本次请求 18 视图导致 `63 + 18 = 81 > 64` 终身视图上限，受控入口拒绝写入账本并返回退出码 2。
2. **硬件电源守卫拦截**：
   - 宿主机当前处于真实电池放电状态（Battery 84%，AC Charger: Not Connected）；
   - 严格遵循 AGENTS 规则与统筹要求，不降低保护线，不绕过入口。

---

## 三、代码集成与回归状态

1. **Worker 真正集成**：
   - `envs/teachers/t6/pipeline.py` 已彻底修复：当 `--allow-model-execution` 传入时，自动调用 `real_da3_worker.py` 执行完整的 MPS 前向与预测落盘，确保在有 AC 电源且配额重置的新卡下能够一键在同一进程组中完成中央闭环。
2. **测试回归**：
   - 21 项单元测试全绿（0.69s）；
   - 4 项源码物理变异对照全部有效变红拦截（`passed: 4, real_model_runs: 0`）。
3. **文件范围严格恪守**：
   - 仅触碰：`envs/teachers/t6/`、`envs/teachers/.venv-t6/`、`artifacts/teachers/da3/`、`reports/V9-T6/`；
   - `src/` 源码绝对零修改。

---

## 四、交接建议

当前卡面尝试次数已达 4/3 次，符合统筹要求：“若卡面尝试用尽：新开续修卡承接，保留 r4 张量归档不覆盖”。
建议：
1. 由统筹创建接续卡（如 `V9.T6-cont` 或下一阶段重构卡），分配新视图配额；
2. 待设备接入 AC 电源后，直接复用当前已就绪的受控代码与预测张量。
