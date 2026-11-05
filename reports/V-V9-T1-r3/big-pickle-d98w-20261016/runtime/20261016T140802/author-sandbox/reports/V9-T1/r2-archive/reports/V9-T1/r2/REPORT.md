# ainerzero.V9.T1 r2 报告：上游来源与训练资格（回应 T14 与 A6 F3）

- 作者：Claude（一级），2026-10-16。纯 CPU；只改设计、schema、示例与核对脚本。
- r1 原件归档：`reports/V9-T1/r1-archive/`（文档 3d98bb16…、v1 schema 67d779d6…、r1 报告）。

## 改了什么（关闭表见规范 §9）
1. 新 schema `teacher_cache.v2`：来源条目分三块。
   - `upstream`：system、origin、actor、input_ref、eligibility；
   - `derivation`：教师 ID、用途、权重与预处理摘要；
   - `license`：教师许可与输入许可的交集。
2. 训练资格取交集：上游资格 ∧ 教师许可 ∧ 条目许可 ∧ 可复现等级不是 unverified ∧ 分区是 train。
3. `external_derived` 默认拒训，schema 强制；只有带 `revision_ref` 的 ADR-0005 修订路径才能改。
4. 同块多来源逐条独立判定。
5. `as_of_t_s`：用作输入的特征不得包含晚于截止时刻的帧。
6. 电源口径按入口写实：AinerZero 已取消交流电守卫，AWZ 重任务按 ADR-0009；撤回 r1 的“用电池禁跑”。

## 实际命令与结果
```bash
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -I reports/V9-T1/r2/check_teacher_cache_v2.py /Users/mac/AinerWorkFlow/AinerZero reports/V9-T1/r2/check_result_v2.json
```
- 返回码 0。
- 库级正例 1 个：同一内容块被 AWZ（external_derived）与 AinerZero（observed）两个来源引用。
- 训练资格 4 例全部符合预期：AWZ 来源拒、AinerZero 来源准、几何教师准、unverified 拒。
- 结构反例 8 个、库级反例 6 个都按预期被拒；11 个破坏自检全部变红。

## 摘要
```
e750fec28476547e7c0d6a406682b08903602b6e2577a3d80b344a9db46b97e7  docs/v9/TEACHERS_AND_CACHE.md
7cba7daa5521d55e1c557bdb5f81b4ceb59c71f214c6d69336c00f459c4fae67  contracts/v9/teacher_cache.v2.schema.json
21735f757736beaa08d67ae4ee0c9cdf375a2639cd6bfda637eab6fac7aca70d  reports/V9-T1/r2/check_teacher_cache_v2.py
```

## 未验证与限制
- 锁的结论仍是协议级模型；真实双进程复现归 T2。
- Forge 的 `teacher_feature` 映射要按 `upstream`/`derivation` 改，归 forge.V9.A2（暂停中）。
- 需要非作者复核，按 D-018 通过后才能验收；T2 仍等 T1 验收与 D-019 总门。
