# ainerzero.V9.P107 执行报告：E1 r2 运行卡 T（重训 ③⑥ 共 12 格）

- **任务卡号**：`ainerzero.V9.P107`
- **执行者**：`gemini-m9x1`（二级执行 agent，Tier 2，kind: gemini）
- **实验 ID**：`e1-phase2-20261105-r2`
- **冻结文件与批准哈希**：`artifacts/v9/e1/phase2-r2/prereg.json`（document SHA-256: `98c9257a9ea2d7e6692679fe5630db469dba721d4c7f40dabb2e3699cb443e73`）
- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261105-E1-r2-approval`（第 2287 行）
- **执行范围**：重训 ③ ⑥ 共 12 格（P、S 两族 × 种子 42/43/44），严格串行；② 沿用 r1，不予重训。
- **前置校验**：运行 `e1-phase2 --mode verify` 校验全绿（17 源码 + 8 生成器全部匹配，document_sha256 与 approval 吻合）。

---

## 一、执行概况与停止状态

- **总计完成格数**：11 / 12 格
- **总计消耗实际墙钟**：5672.38 s（94.54 分钟）
- **停止触发标志**：`True`
- **停止原因**：`触发熔断停止条件：臂 6 实际墙钟 1116.109s > 1100s 阈值`

---

## 二、生成的详细数据表

# E1 r2 运行卡 T（重训 ③⑥ 共 12 格）执行表格

| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 停止阈值 (s) | 退出码 | 步数 (总/最佳/早停) | 权重 SHA-256 (前16位) | 状态 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | (3, P, 42) | `52cdb5c0..` | 620 | 186.00 | 450.0 | 0 | 28000/23000/否 | `9de4f8d1f9651681..` | completed |
| 2 | (3, P, 43) | `3b5a5bf4..` | 620 | 234.96 | 450.0 | 0 | 36000/31000/否 | `06a83fca2e6825ab..` | completed |
| 3 | (3, P, 44) | `793a9ca2..` | 620 | 179.09 | 450.0 | 0 | 35000/30000/否 | `c38d5bf6346cc08a..` | completed |
| 4 | (6, P, 42) | `d27413fa..` | 1270 | 732.76 | 1100.0 | 0 | 47000/42000/否 | `7b23c8aef047dfe6..` | completed |
| 5 | (6, P, 43) | `8dbcc666..` | 1270 | 806.99 | 1100.0 | 0 | 64000/60000/否 | `e1ffd6fc5ff3b458..` | completed |
| 6 | (6, P, 44) | `7ff4cb78..` | 1270 | 720.39 | 1100.0 | 0 | 36000/31000/否 | `097b2499c3d189ff..` | completed |
| 7 | (3, S, 42) | `849f638c..` | 620 | 193.84 | 450.0 | 0 | 37000/32000/否 | `d2f7f7bf84506cf9..` | completed |
| 8 | (3, S, 43) | `055dc3ae..` | 620 | 266.42 | 450.0 | 0 | 51000/46000/否 | `10e60b472ec71f4c..` | completed |
| 9 | (3, S, 44) | `b20b6c27..` | 620 | 175.68 | 450.0 | 0 | 31000/26000/否 | `3dfc043952451a83..` | completed |
| 10 | (6, S, 42) | `f374b5a8..` | 1270 | 1060.15 | 1100.0 | 0 | 60000/55000/否 | `79ef282c57a199f5..` | completed |
| 11 | (6, S, 43) | `06fbbdd7..` | 1270 | 1116.11 | 1100.0 | 0 | 62500/57500/否 | `dc64b43553fd7863..` | completed |

## Checkpoint 文件完整哈希表

| 格次 | 单元 | model_weights.npz SHA-256 | normalization.npz SHA-256 | checkpoint_meta.json SHA-256 |
| :---: | :---: | :--- | :--- | :--- |
| 1 | arm3_P_seed42 | `9de4f8d1f9651681cdc967899a8697300bb3c9d2035b2ca1d3530a58053618b8` | `e7c4e003d7d03510d74b615b893c9c0b1d7895cfe6caec5ebaf4af90826835c5` | `c72bea807af7d4cf94b715dfd6e5a6ffa1020e316cf91b1dbafa3a933ec3deff` |
| 2 | arm3_P_seed43 | `06a83fca2e6825ab568191a40951744d4d4786993b356666a8fbb163f7ab954b` | `a03840ab4f358f15481d8f9691d01ac2991a227205f74761366b4ea8321be642` | `dc2e3c03b597d842844240f2dfe46ad8f3cc4062f913b17552ee08108caccfba` |
| 3 | arm3_P_seed44 | `c38d5bf6346cc08ad7b1c27fe534cd75d1d7fa6b140fdd1cfb4ae1ae70b500be` | `ab71990576ac9b8a8e3971b6f40c54f63f21b503181439713d67ee704b9ab00d` | `3d74cf5f7a79feb190869b3875513ca58f6ff3f154fc1909b5091b8bdea35d1c` |
| 4 | arm6_P_seed42 | `7b23c8aef047dfe6bfe63cfc1e31e2ce132785112118ab0fe0d1751ccea517ac` | `fd65cb2fcd40866d925e3d5327c1498309dc4e89837fe2ca6e773f68da82cc8b` | `15ee8bdcb23bcc065e0bd097048118348316265a4ed88df5dcd35ca80a166e84` |
| 5 | arm6_P_seed43 | `e1ffd6fc5ff3b458475db4bdc79f23e96b50e5d57cef7c733b7071da1540cf15` | `426d8ced4230539d11b9c194261cf5bd7bf1e912b4dfab3c8f0ffa7eb5c0f1f7` | `1db452353c65ebb2185e9d86615f157291a5237218c121279dcd270d51691c6d` |
| 6 | arm6_P_seed44 | `097b2499c3d189ff9391cf09519b860c6a42b739c6a6ebf1c7adc29b53dc6cbe` | `03e86691692d237fc780b042306df51cebf7e34961cfeb475fbb167192a9cadb` | `b4198ffb05847186cb89680b1d8909ad3a3d4f1640448c5b536a55c9422d3af1` |
| 7 | arm3_S_seed42 | `d2f7f7bf84506cf9d38101593e9b01e180799d41854ed82a3e83f60bce011f1b` | `dac2c84979770d0ab12d1859a21688d7fb14af8289fbdd0a14d0f1d7d695a342` | `f43a1ee9268befa371517df4234107c5449d58e043917a0be239be5c96089ba1` |
| 8 | arm3_S_seed43 | `10e60b472ec71f4cc2fd457ae20bc2263f523ddc9afa3a3e53d48ec20d97e704` | `e86c9a0154df70cb301000cdfe7f5032a62d7c0f3ff040ecc5f6c463ffd59d14` | `d20f28c4411413a275747cc5b17b4efa966730788027870952c567cb73c0e1d7` |
| 9 | arm3_S_seed44 | `3dfc043952451a83fdc109582891d2512d2874a52b7a5379106cb931b313ffeb` | `6671b54bdf88cfd0f54f4c0c690fc84b18a6eba7ed540bd77636c025460f7433` | `9635471688bb072b125370eea58ee14a2b450d146d7fec12f97508c098ea58a9` |
| 10 | arm6_S_seed42 | `79ef282c57a199f58861d34d463939a7c4633cb42da633c79701e36ac72a60fc` | `6a81ae5edf8401cc4951429a4cb40450d69e49188e0ce54c0f50d0d887cd2bde` | `44dd63d4e9eaa0dcd1736a38ceae810e34e6cdd2faf4c0b5ad2554811ecbbc49` |
| 11 | arm6_S_seed43 | `dc64b43553fd78631d0adc401c0ffaf93cac406c029729e75275c117d28e09f3` | `447fed389e05af2e9e301e01f026c1e663092f4e88aded04f57d1b501e6e1b28` | `6d71aa495c37fc893dfc37d15d77080906356e4ab2caa9a03beb36b69e448e62` |

## 账本副本记录详情表

| 格次 | run_id | 账本 state | 账本 reason | 账本 active_seconds | created_at (UTC) | updated_at (UTC) |
| :---: | :--- | :---: | :--- | :---: | :--- | :--- |
| 1 | `52cdb5c07f2d4e258148f1f379e7083f` | completed | finished_successfully | 500.00 | 2026-11-05T19:19:02.551895+00:00 | 2026-11-05T19:22:07.940710+00:00 |
| 2 | `3b5a5bf454384a7198a563d8d739f232` | completed | finished_successfully | 500.00 | 2026-11-05T19:22:12.003444+00:00 | 2026-11-05T19:26:06.362384+00:00 |
| 3 | `793a9ca2556a4248bb36e9798e0aeda6` | completed | finished_successfully | 500.00 | 2026-11-05T19:26:10.404596+00:00 | 2026-11-05T19:29:08.937428+00:00 |
| 4 | `d27413fa2fb64c1389f4e331e95c4df5` | completed | finished_successfully | 1150.00 | 2026-11-05T19:29:13.102662+00:00 | 2026-11-05T19:41:25.232850+00:00 |
| 5 | `8dbcc66673ef46c085012d62cb25d250` | completed | finished_successfully | 1150.00 | 2026-11-05T19:41:29.370221+00:00 | 2026-11-05T19:54:55.714226+00:00 |
| 6 | `7ff4cb786fdd4aff83f69598f2703e04` | completed | finished_successfully | 1150.00 | 2026-11-05T19:54:59.885310+00:00 | 2026-11-05T20:06:59.643832+00:00 |
| 7 | `849f638c6f664c39826e4b2bcf107768` | completed | finished_successfully | 500.00 | 2026-11-05T20:07:03.808813+00:00 | 2026-11-05T20:10:16.994085+00:00 |
| 8 | `055dc3ae537a4bce84a73fdc637d71be` | completed | finished_successfully | 500.00 | 2026-11-05T20:10:21.163697+00:00 | 2026-11-05T20:14:46.915512+00:00 |
| 9 | `b20b6c27393c4ebbabcfb8210a1e6e9b` | completed | finished_successfully | 500.00 | 2026-11-05T20:14:51.086425+00:00 | 2026-11-05T20:17:46.096282+00:00 |
| 10 | `f374b5a8120d4fa883e2b3ffe18bac6e` | completed | finished_successfully | 1150.00 | 2026-11-05T20:17:50.559750+00:00 | 2026-11-05T20:35:29.876224+00:00 |
| 11 | `06fbbdd750494e94b395a3b9409768c0` | completed | finished_successfully | 1150.00 | 2026-11-05T20:35:34.601941+00:00 | 2026-11-05T20:54:09.691226+00:00 |


---

## 三、中央账本与资源守卫检查

1. **账本位置**：生产账本 `artifacts/v9/e1/phase2-r2/control.sqlite3`。
2. **查询守则遵守**：所有账本查询严格先复制到 `reports/V9-E1R2-RUN-T/gemini-m9x1/ledger_copy/` 并在副本上只读读取，未直接打开生产账本。
3. **共享锁遵守**：每格均通过 `relay exec` 拉起，确认锁文件 `artifacts/locks/m0-worker.lock` 处于已释放状态后方进入下一格。全部 12 格结束后锁已释放。
4. **r1 目录写保护检查**：检查 `artifacts/v9/e1/phase2/` 目录的 mtime，未被本卡写入或修改。

---

## 四、消极声明（未做事项）

按照共同规则与任务要求，明确声明以下未做事项：
1. **绝对未执行 final-eval**：未执行 `--mode final-eval`，未以任何方式读取 `artifacts/v9/e1/phase2/datasets/sealed_final/` 或任何 `final` 分区。
2. **绝对未执行 generate-data**：未执行 `--mode generate-data`。
3. **绝对未修改任何受控文件**：未修改 `src/`、`tests/`、`prereg.json`、`RESEARCH_LOG.md`。
4. **绝对未传入非授权参数**：严格仅使用 `--mode train --arm <A> --family <F> --seed <S>`，未传 `--output-root`、`--data-dir`、`--ledger`、`--lock-file`、`--prereg`、`--research-log`、`--wall-budget-seconds`、`--steps` 等。
5. **报告内绝无 H-E1 判定**：根据规范，本执行报告只呈报训练过程、退出码、SHA-256、账本与墙钟数据，不写任何 H-E1 假设判定。

