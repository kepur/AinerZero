# P237 之后一级补测（2026-11-12）

P237（gemini-r7b2）复核一级给 P235 补的三条测试，自己做了 4 处坏对照，J1、J3 被拦住，J2、J4 漏网。

- **J2 漏网是真缺口。** 在 RLT 下，`predict` 给 R2、R3 的 GridHead 传 `mask=None` 时，没有测试能发现。
  - 新增 `test_predict_grid_logits_ignore_dropped_token_values`：学生在被并掉位置分别输出 0 和 1e3，`predict` 的 `r2_logit`、`r3_logit`、`r1_logd` 都必须一致。
  - 在一级的隔离副本里持锁复验，J2 被这条测试拦住。见 `mutJ.txt`。
- **J4 是等价改动，不补测。** 它把还原后的 token 喂给 GridHead。只要 mask 照传，被并掉的位置在注意力池化里权重为 0，换成什么 token 都不影响输出，任何行为测试都区分不出来。设计稿 r1「实现阶段补记」第 3 条只要求 GridHead 照旧用 keep 掩码，没有规定喂哪一份 token，两种写法都合规。
