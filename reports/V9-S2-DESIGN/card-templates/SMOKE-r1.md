**S2 smoke 登记运行（r1，≤ 20 分钟）。** 执行者为一级 claude（用户 11-07 授权一级直接跑已登记运行）。

## 依据
- **预登记 r1：** `artifacts/v9/s2/phase1/prereg.json`，document_sha256 `726eb56b…`；批准行见 RESEARCH_LOG `R20261106-S2-approval`。
- **预算：** smoke ≤ 1200 s，计入总额 10 h（R20261106-S2-budget）。

## 命令（只用 CLI 默认值，不传任何路径参数）
`relay exec ainerzero.V9.<本卡> --agent claude --wall-timeout 1320 -- caffeinate -i .venv/bin/python -m ainerzero s2-phase1 --mode smoke`

## 规则
- 失败不重试、不调参，保留原样交回。
- smoke 第 2 步推算的总预算若超过 10 h，回用户。
- 不运行 final，不读任何 `sealed_final`。
