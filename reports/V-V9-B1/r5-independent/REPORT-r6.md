# ainerzero.V9.B8 非作者独立复核 r6（B7 候选 d902876a… 与原 r4 不变）

角色：verify（非 B7 作者）· 执行者 deepseek-flash-4up8（接第 1 棒 deepseek-h7m2 的 harness，身份已更正）· 2026-10-18 · 状态 reported（只建议，不采用/不改旧 r4）
对象：B7 最终 r6 候选 `reports/V9-B1/r6-candidate/check_skill_proposal.py` = `d902876a…`；原 r4 = `37d4308f…`；B6 已验收 baseline 448 项；B7 报告 r6 交付（972 条 R6_SHA256SUMS、T1–T10）。范围只写 `reports/V-V9-B1/r5-independent/r6-20261018/`，原 r4/候选/contracts/docs/真实 AWZ 只读。
实际执行（纯 CPU，无训练/MLX/ORT/GPU/下载/付费/提交；`/usr/local/bin/python3` 3.12.2 + jsonschema 4.21.1；全部子进程 234 条记录见 COMMANDS.md 与 logs/）：
  A 身份：r4 清单 254/254 raw 重算通过（241 JCS + 3 个既定 jcs_error 夹具）；B6 baseline 448/448；候选/原 r4/AWZ 观察源 pin/旧路径哈希均独立复核；r4 树无 B6 后改动。
  B 入口反例（38 次 CLI / 37 检查全过）：自写文本手术构造重复键字节 → proposal/context/reply 三入口 rc=1 `schema_invalid`、stderr 无 traceback；关 strict 副本三入口真实 accepted（不是异常退出）。非法登记属性名 → rc=1 `forbidden_property`；单关一层仍被另一层拒，双层全关后 accepted（真实漏检）；嵌套位置同验。来源内容漂移但路径不变 → rc=1 `context_observable_source_content_drift`（缺失/不可读同）；关来源守卫副本 accepted；r4 旧 pin/旧 env fail-open 行为如实记录。自写 JCS 与作者 112 个 context pin 交叉 112/112。
  C suite：默认 `--suite` 只读 rc=0/all_ok、112 例（18 正/94 反），候选 974/r4 1301/contracts 383/docs 3 文件树前后零变化（约 80s）。r6 新增 output-dir 守卫实测：输出=r4 祖先/候选自身/fixtures 后代/symlink 别名/普通文件 5 例均 rc=2 对应错误码、无 traceback、受保护字节 0 变化；指向已有证据目录 rc=2 `output_evidence_exists` 且两文件 SHA 不变。
  C/E 新输出 suite：全新 /tmp 目录 rc=0/all_ok/112 例、恰写 `check_result.json`+`SHA256SUMS.txt`；两次输出逐字节一致（check_result `8192b347…`、SHA 清单 `ece3e489…`）；候选树/r4/contracts/docs 前后不变。
  D 夹具/suite 入口：夹具被篡改/新增 → 干净 `FIXTURE MISMATCH` rc=1；suite 回归输入 `reports/V-V9-B1/probe_variants.json` 重复键仍抛未捕获 ValueError（rc=1 + traceback），关 strict 副本则 all_ok —— F4 缺陷在 r6 未修（守卫承重但失败形态不干净）。
  F 终验：候选树 437、原 r4 交付树 764、contracts 383、docs 3、AWZ 源、B8 只读输入全部逐字节不变；r4 对 B6 baseline 448/448、对自清单 254/254 通过。
发现（非运行阻断，供一级裁定）：
  1) r6 候选交付证据陈旧：`SHA256SUMS.txt` 仍登记 r5 的 REPORT.md sha `e128141f`（当前 `fd88d33b`），且 236 处逻辑路径为 `reports/V9-B1/r5-candidate`；`check_result.json` 同为 r5 目录名时代产物（与本次全新输出不同）。`R6_SHA256SUMS.txt` 是另一份 972 条当前身份清单，但候选目录内证据未重生成。
  2) suite 回归输入重复键路径 F4 未修：`probe_variants.json` 重复键 → traceback（应干净 fail-closed）。
  3) 候选 `metrics.json` 是 B7 棒级交付指标，不是 suite 输出指标（suite 身份以 check_result.json 为准）；A 的 count 对比因此不适用，非缺陷。
建议（只建议、不采用、不授权运行）：r6 可接受为候选；接受前补 1) 证据重生成或显式标旧、2) F4 干净失败。原 r4 全字节不变；r6 vs r5 差异仅在 checker（+191/−23 行，diff 已留存）。
未验证：真实 AWZ 门禁/内核/消费者隔离、production 运行；本复核只证明参考核对器行为与字节不变性，不构成采用、能力或运行授权。
证据：`reports/V-V9-B1/r5-independent/{REPORT-r6.md,metrics-r6.json,r6-20261018/{results,tests,identity.json,COMMANDS.md,SHA256SUMS.txt}}`；原 REPORT.md/既有证据未覆盖。
