# G9 外部独立复核 G7 r2

## 摘要（正式提交）

- **裁决：request_changes；建议主责退修 G7 r2，不自行 accept/reject 实现。**
- 执行者 `codex-g9-review-20261028`，tier 2 / kind codex；只领取 G9，未参与被审对象实现/发布，不继承作者测试作为独立证据。
- F1：FactTest 只查数量和得分，不验证冻结配方；29 份重复空律（不同 ID 亦同）→ **admitted=True**。
- F2：N3 只记录测试数据字符串；相同 T 世界换 test_data_id → 第 2 步再次 **admitted=True**。
- F3：有限 GLS 为收缩白化，非 ADR D2-7 硬正交；作者推荐 GLS 仍需设计裁决与 Σφ 预冻结来源证据。
- 已确认：逐上下文能量不增、硬正交/GLS 极限；e-LOND 合取且单独绕过翻转准入；显式族缺失/冲突/未登记拒绝；三族 e 值不同。
- 非空错误机制普通负例 **0/3 准入**；另独立 360 世界探针只被 FactTest 拒绝，绕过该门即准入。
- 独立拆门 **6/6 捕获**（3 真成功破坏，3 普通负例/不变量），另 2 个“只绕过一门”准入翻转。
- 作者回归 **30 passed in 6.23s**，仅回归；独立生成器未导入作者测试、G8 生成器或产品积分器。
- 零模型/MLX/下载/付费/生产重启部署；未触碰 A22 health/plist，未改源代码/协议/真实账本/锁。

## 对象与复现身份

- 工作树 HEAD `2de6caef0820894520271a8943761cc0b3cf8c22`。mechanism 是未跟踪工作树文件，不能把 HEAD 冒称候选提交；以如下逐文件 SHA256 和隔离副本为准。
- ADR：`../AnimeWorldZero/docs/adr/ADR-0014-constrained-mechanism-formation.md`（accepted），SHA 见 `evidence/reviewed_manifest.json`。
- 先读本地 AGENTS/README/COORDINATION/AGENT_TASKS/RESEARCH_LOG、G9 prompt、G7 relay 全报告、r2 报告、G8 F1–F4、ADR D2/D3；注册后普通 claim，无 force。

| 文件（src/ainerzero/v9/mechanism/） | SHA256 |
|---|---|
| `registration.py` | `1b54ead54726504841b2b6c1ad14c3b757b23943d92f09a846679957396fcd81` |
| `sufficiency_gate.py` | `c2fc775d88fe678a0ceaea42e6f51d946d1d19eebf3cd37152260c84dd29c436` |
| `discovery.py` | `be599dca421a472825a4ae03e7de7a53f8c114b9424db2ec21fd083482bf18f6` |
| `__init__.py` | `7d1c5608f44d6e1ad9732365a04f291fa6b881c0d706895b1d007176ddb6a5c9` |
| `identification.py` | `eb3edd8286cf0ad4cfe00afe51f6b4421468ceb49fc9f482f1f9d2d9e8d82c05` |
| `toy_worlds.py` | `91458c1475f276f7641be1d86c8813f5c9d2a0bc3eb1bee6011c9fd349387d28` |
| `promotion_gate.py` | `c0f8a4897aece4f3a08f45789ff745a37a7df9880b5c77b33e92043ae0cff3ff` |

`isolated/g9baseline/` 固定审查对象；每个变异体均只在本卡目录下复制变异。独立 RK4 的向量场、积分和数据由 `review.py` 自写；唯一使用的产品数据容器是 ObservationContext。固定种子 D=281001、C=281002、T=281003，D/C/T 各 9/24/60 个不同世界。冻结参数 REG 原样使用；比较用 Σφ=diag(1.5,0.25,0.60) 在生成前声明，与作者报告相同，**不把此比较冒称新登记/批准默认值**。夹具全部值与 SHA 在 `evidence/fixture_*.json`、metrics。

## 阻塞发现

### F1 — FactTest 坏配方未失败关闭

位置：promotion_gate.py:625–643。只将 `facttest_null_candidates` 转成列表并判断 len>=29，没有配方 SHA、系数分布/重复语义检查或可信构造来源绑定。正确候选在规范 null 配方得分 0.916667、阈值 0.041667，可准入；换成 29 份系数为 0 的同一候选，阈值降为 0，仍准入。给每份空律不同 candidate_id 也准入，故仅去重 ID 不足以修复。28 份则拒绝，说明仅样本数防线有效。这里没有声称“正确机制变错误”；证明的是卡面要求的“坏配方必须拒绝”不成立、标定证书可由退化输入洗白。应绑定冻结 null 配方、生成数据身份和实际候选内容，不能由任意列表长度认证。

### F2 — N3 重测隔离仅按名字

位置：promotion_gate.py:505–510。首次对 T 60 世界准入，第二次保持所有 T 数组及 world_instance_id 完全相同，只将 test_data_id 改为 G9-T-renamed/test_id 改为 G9-retest，仍准入。第二步会消耗新序列预算，但未满足 ADR D3-3 N3 的“与所有历史 T 世界不相交”。D/C/T 当次世界交集检查存在，不能替代跨步检查。应在门的只追加证据状态绑定并检查历史世界/数据内容身份，拒绝旧世界换标签。

### F3 — GLS 推荐不等于现行硬约束；Σφ 来源证据不足

ADR D2-7 明写“硬约束在灵敏度子空间正交补”。代码 discover 的实际默认 `nuisance_cov=None` 仍是硬投影，这是合规默认；报告所谓“默认推荐 GLS”不是代码默认。有限 GLS 与参数基内积最大 **0.54146**，硬投影为 **1.70e-15**，所以不能凭能量不增称满足硬正交。Σ×1e14 时与硬投影最大差 **2.40e-8**，极限正确。

作者 run_r2.py:32 固定 PRIOR_COV，:99 显式传给 GLS，CMFLRegistration 无 nuisance_cov 或其来源登记字段；报告称应来自 ParamBelief，但未提供独立可核验的事先冻结/估计数据证书。**不能据此断言作者实际事后调参**，也不能确认未调参。若将 GLS 作为建议候选，须先由主责裁决 ADR 偏离及 Σ 来源；保持硬投影时则必须按下表披露其较低恢复，不能引用 GLS 20/20 代替硬约束能力。

## 已确认与独立测量

- 随机视图 12 上下文最大能量比：硬 0.9839164、GLS 0.9841122，均不增。
- 正例三族 e 值 9939.02 / 9988.29 / 9636.96，互不相同；E_pers 为三者最小。
- 每族 4 世界时 bootstrap/FactTest 等均过，仅 e-LOND 拒绝（4.3977 < 32.8987）；只将 e_lond_passed 改 True → 准入，接线有效。
- 标签缺失、未注册、同世界冲突分别拒绝；名字不含族信息，未靠 ID 猜测。
- 错误 coulomb_friction 0.45 替 drag 0.55 的 3 组新 120 世界测试均拒绝；它们还被 e-LOND 拒绝，不能把这 3 组称“FactTest 唯一承重”。
- 另 360 世界夹具 E_pers 足够，其余所有门通过，FactTest 唯一拒绝；只绕过 FactTest → 准入（supplement）。
- 未达阈值所需 null 数时直接阈值返回 `"inf"`（metrics 字符串），未放宽门槛。
- 去掉 in_slow_domain 后，4 个相同可见观测、不同密封未来与不透明世界 ID 的完整 route/reason/NIS 记录一致；无包络拒为 OOD，超盒协变量亦为 OOD。仅证明所测边界，不声称全系统无泄漏。

发现比较（每格固定 10 次、每次 6 新世界）：

| W / dt / σ | 方法 | 世界 | 非空发现 | 精确 drag 支持 |
|---|---|---|---|---|
| 20 / 0.01 / 0.004 | hard | param | 0/10 | 0/10 |
| 20 / 0.01 / 0.004 | hard | structural | 4/10 | 3/10 |
| 20 / 0.01 / 0.004 | gls | param | 0/10 | 0/10 |
| 20 / 0.01 / 0.004 | gls | structural | 10/10 | 10/10 |
| 16 / 0.015 / 0.0025 | hard | param | 0/10 | 0/10 |
| 16 / 0.015 / 0.0025 | hard | structural | 8/10 | 7/10 |
| 16 / 0.015 / 0.0025 | gls | param | 1/10 | 1/10 |
| 16 / 0.015 / 0.0025 | gls | structural | 10/10 | 10/10 |

“纯参数非空”是假发现；“结构精确支持”只计支持集合，不保证系数精确。两设定 GLS 为 10/10 恢复，但第二设定纯参数假发现 1/10；硬投影为 3/10 与 7/10。小样本玩具结果，不代表一般性能或 FDR 保证。

## 拆门矩阵与证据性质

| 单处变异 | 夹具性质 | 观测 |
|---|---|---|
| e_lond_passed=False | 真成功坏控 | 原来准入 → 拒绝 |
| 显式标签强制都归第一族 | 真成功坏控 | 原来准入 → 缺族拒绝 |
| facttest_passed=False | 真成功坏控 | 原来准入 → 拒绝 |
| 共形 k 去掉 n+1 | 普通负例绕门 | n=18 原证书无效 → 错误有效 |
| 投影系数 1→2.5 | 普通不变量坏控 | 参数方向视图触发能量增大断言 |
| 不可达 null 阈值 inf→max+ε | 普通负例绕门 | 28 null 的不可达阈值变有限 |

前 3 个是有效正例被破坏，后 3 个不是准入层面的真成功坏控。另 2 个单门旁路提供小样本正机制与大样本错误机制的准入翻转。没有将“普通负例本来就拒绝”冒称捕获了唯一承重门。

## 旧证据完整性、实际命令与限制

- 当前 7 个产品源码与起始隔离副本逐字节一致。G7/G8/旧 r1 文件均只读；全清单见 reviewed_manifest 和 end_manifest_check。
- r1 archive 的 14 个非自引用条目均匹配原 SHA。其 SHA256SUMS.txt 自引用期望空文件 SHA，却实际非空，这是现存清单生成瑕疵；不能据此宣称本轮改坏归档。r1 历史报告不更新。
- 新探针实际命令：`.venv/bin/python -B reports/V9-G9/review.py`、`.venv/bin/python -B reports/V9-G9/supplement.py`，各 rc=0；stdout/stderr 全保存在 evidence。
- 回归：`env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest tests/v9/mechanism -q -p no:cacheprovider`，rc=0，30 passed。它只作作者回归，不作独立证据。
- 本卡证据在本目录；pytest 自身 tmp_path 为临时副本，不涉及产品/生产；未提交、未推送。
- 未跑真实数据、MLX/训练/模型，不碰 RunStore/共享锁。无真实预算预留及消耗。未审计 A22 部署/health/plist，未进行生产探针。
- 未全面证明 e-process 条件均值假设、任意协方差精确白化、整个 8 路由跨分布召回或系统级生产能力。Σφ 事前来源未获独立证据。
- 仅建议主责处理上述发现；G9 完成不等于 G7 验收或能力晋升。正式 relay report 不带 --next，按用户约束本卡交回即停。
