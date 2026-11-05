# C0 时空契约固定公开夹具 v1

仅用于 `contract_test_only`；**not_for_training**。这是已使用过的两个研究 episode 的公开字节副本，不是新环境、独立能力验收或泛化证明。不修改原观察来源、分区或世界，也不把研究员建立的引用称为学生发现。

| 相对路径 | 原来源 | 分区 | world_id | 转移数 |
| --- | --- | --- | --- | ---: |
| development/242b7060-4a2c-4ca9-aa46-e4bbc59f4786 | artifacts/c0/242b7060-4a2c-4ca9-aa46-e4bbc59f4786 | development | f639e915-95ad-5122-89b5-ccc9cd207ff6 | 64 |
| train/2d457a1e-c746-48ae-8adb-59b47929d69e | artifacts/c0/2d457a1e-c746-48ae-8adb-59b47929d69e | train | 554d4bfc-e6ac-5f7c-bd82-99f972c16057 | 128 |

各 episode 仅复制 `public.jsonl` 和原 `manifest.json`，合计 **490,577 bytes**。两文件逐字节不变；原 manifest 中的 private 文件描述仍保留，但 **private.json 从未复制或读取**。所有实际大小、SHA256、run/episode/世界/分区及来源路径登记在 [fixture_manifest.json](fixture_manifest.json)。来源 HEAD 是复制时仓库身份，不声称原采集发生在这个 commit。

用显式 `load_public_trajectory` 或样例脚本的 `--public-only` 读取。该 profile 只允许两个文件，复用原 public 哈希、header 和观察链校验。默认 `load_trajectory`、训练准入和重放仍要求完整三文件；不能把公开夹具当完整训练/重放产物。

```sh
PYTHONPATH=src .venv-ainerzero/bin/python -B examples/c0_spacetime_refs.py tests/fixtures/c0_spacetime_v1/development/242b7060-4a2c-4ca9-aa46-e4bbc59f4786 --public-only --cell 0 --archive-root artifacts/spacetime
```

测试固定读取本目录的两套夹具，不遍历本机 `artifacts/c0`；缺失即测试失败，不整体 skip。归档按分区/episode/内容摘要命名，已有目标拒绝覆盖；运行上例之前应检查是否已有同身份归档。
