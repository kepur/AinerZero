**非作者复核一级 claude 的直接改动：S2 运行前预检 Preflight 0。** 只读、纯 CPU、不运行 MLX。复核者不得是 claude（作者）。领卡后先在报告第一行写一句自证。

先读：`reports/V9-S2-PREFLIGHT0/REPORT.md`、`src/ainerzero/v9/experiments/s2/commands.py`（`s2_phase1_command` 开头的 Preflight 0）。

## 必须独立核实
1. **改动范围**：
   - commands.py 只在非 verify 分支最前面加了 Preflight 0，并把批准预检改成绑定 expected_sha256。对照 P148 r3 的交付版本（`reports/V9-S2-P148/r3/` 中的 SHA 或副本）写出 diff。
   - verify 分支和其他函数的行为不变。
2. **四道闸都是真的**：在临时目录自己构造以下四种情况，确认结果：
   - 没有 prereg → unfrozen；
   - 冻结了、但批准行写的是别的哈希 → approval；
   - 冻结后改了一个 s2 源文件（在隔离副本里真改一个字节，不要用 monkeypatch）→ identity_mismatch；
   - 冻结且哈希一致 → 准入。
3. **测试改动没有削弱断言**：逐条比对 lifecycle、train_runner、wiring 三个文件里被改的用例。改动应当只是把伪造的哈希换成真实冻结得到的哈希，以及新增的用例；原有断言不得被删或放宽。
4. **自己另做至少 3 处变异**：例如去掉 expected_sha256、跳过身份核对、未冻结时放行。每处跑完按字节还原，并报告是否变红。
5. **默认全量**：前台跑（SIG_DFL+execv），报告计数。

## 结论
写在 `reports/V9-S2-PREFLIGHT0/review/REVIEW.md`，在 RECOMMEND_ACCEPT、RECOMMEND_ACCEPT_SCOPED、RECOMMEND_REJECT 中给出一个。不改任何源码或测试。
