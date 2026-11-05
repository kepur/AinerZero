# ainerzero.V9.T2 执行报告（r2）

角色：executor（二级）· 负责人：`composer-lr94` · 时间：2026-10-20（+03）  
任务状态：reported · 实验状态：completed（纯 CPU；无训练/下载/MLX/torch）  
参数 v0：`{}` · D-021 放行 · 依据 T3 打回 F1–F13

## 0. 摘要（≤30 行）

1. 以当前盘面为 r2 起点；原 `composer-a7k2` / 迟到覆盖交付已归档至 `reports/V9-T2/r1-archive/`（F13）。
2. 重写 `cache.py`：v2 schema 落盘（`output.files[].sha256`）、写入前校验、整库 `.write.lock` + O_EXCL、同 `entry_id` 不同内容拒绝、derivation 三指纹、读路径重算 `cache_key`。
3. 重写 `mode.py` / `fake.py`：extract 每调复核 ModeGuard；TTL/release/切模式抬升 generation；可注入 RSS 探针，回落不足或探针缺失 → `unload_incomplete`。
4. F11/F12：`admission_bindings`（v2.1 schema + 规范 §10.1）；`train_eligible` 不信任盘上许可/可复现等级。
5. 测试：`pytest tests/v9/teachers/ -q` → **33 passed**（连续 3 次全绿）；`--verify-locks` / `--verify-mode-guard` exit 0。
6. 未碰 `artifacts/locks/m0-worker.lock`；无下载/安装/付费/提交推送。

## 相对上一棒

| 棒 | 说明 |
|---|---|
| opencode-de3b | 无心跳收回；其后迟到覆盖报告（见 r1-archive） |
| composer-a7k2 | 交 r1（23 passed 登记）；被 T3 打回 F1–F13 |
| composer-6091 | 认领后释放改领他卡；留下 r1-archive 笔记 |
| **本棒 composer-lr94** | 按 T3 打回整段重写 + 双进程 Barrier≥20 + admission_bindings |

## 规范改动段落

- `docs/v9/TEACHERS_AND_CACHE.md` §10.1：新增 F11/F12 段落（admission_bindings / 盘上不可信）。
- 新增 `docs/v9/TEACHERS_AND_CACHE_V2_1.md`、`contracts/v9/teacher_cache.v2_1.schema.json`。

## 实际命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
PYTHONPATH=src python3 -B -m pytest tests/v9/teachers/ -q
PYTHONPATH=src python3 -B src/ainerzero/v9/teachers/mode.py --verify-locks
PYTHONPATH=src python3 -B src/ainerzero/v9/teachers/mode.py --verify-mode-guard
```

## 验证结果

| 检查 | 结果 |
|---|---|
| pytest | 33 passed / exit 0 / ~16.3 s |
| verify-locks | ok / exit 0 |
| verify-mode-guard | all_passed / exit 0 |
| F1 同 entry 改内容 | ImmutableConflictError |
| F2/F10 schema | write 产物 `validate_schema` 空错；无 `output_sha256` |
| F3/F4 Barrier×20 | 无双接受 / 无跨分区残留 |
| F5/F6 | release/TTL 后 extract 抛 ModeViolationError |
| F7 | 探针 None 或 +3GB → UnloadIncompleteError |
| F8/F9 | derivation / key_material 篡改拒绝并 broken |
| F11/F12 | 盘上伪造不翻转 train_eligible；store_problems 报 mismatch |

## 未验证 / 风险

- 未重跑 T3 的 `reports/V-V9-T2/adversarial_suite.py`（该目录只读）；行为由本卡测试覆盖同类反例。
- 旧 v2 正例上下文无 `admission_bindings` 时：`store_problems` 不强制缺绑定错误，但 `train_eligible` 对三项 fail-closed（需调用方提供绑定）。
- 双进程锁在极高并发下已加重试；仍建议复核者单独跑 `--verify-locks`。

## 输入身份

见同目录 `metrics.json` → `source_sha256`。
