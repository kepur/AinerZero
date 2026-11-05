# ainerzero.V9.B10 非作者 CPU 复核（2026-10-18）

验证者：beamfree-x7q2（非 B7 任何版作者）；只读核对，未改源码/候选/r4/r5/旧 B8/B9。
候选 checker SHA256 = 9f88993a…（125440 B）；原 r4 checker = 37d4308f…（未改）；r5 基线 = 5b28818b…。

1. 身份证据迁移复算：`_identity-r5-stale/` 中 SHA256SUMS.txt = 65a3ada3…、check_result.json = ef9a4bd1… 与 B7 报告记录逐字一致；README 显式标旧。当前身份在 `_evidence-baton6/staging-run1/`：check_result.json = 4fb8d5c3…（238802 B）、SHA256SUMS.txt = 8bbce04f…（55440 B）。候选根目录无 check_result/SHA256SUMS（守卫拦截），与 B7 声明一致。
2. 重复键复算：`reports/V-V9-B1/probe_variants.json` 含重复键；`--suite` rc=1、all_ok=false、failures=["probe:b5_probe_variants_unreadable"]、stderr 0 B、无 traceback（日志 logs/suite-dup-probe.*）。
3. 输出守卫抽查：6 类重叠/别名/已含证据/非目录场景均 rc=2、stderr 0 B、写前拒绝（logs/guard-case1..6.*）。
复用旧 SHA 证据：r4 checker、r5 候选、B9 有效负面、B7 报告；本轮新执行仅身份 SHA 复算 + 1 次默认 suite + 6 次守卫拒绝，未重复全套多轮。
限制：未跑合法新输出完整 suite（B7 已有）、未验证值级隐写/真实 AWZ/模型能力；不自动采用、不晋升。
