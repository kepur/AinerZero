# ainerzero.V9.A35 执行报告
角色：executor；负责人：grok47-q4n8；时间：2026-11-19
任务状态：reported；实验状态：未执行
任务依据：Relay 卡 ainerzero.V9.A35，参数 v0，复核提交 f7c7e8a2；只读核对，不训练、不改已有文件
输入身份：初稿 reports/V9-MINI/paper/DRAFT.md；回合日志 reports/V9-MINI/{M4,M5}/{m1,m2}-s{0..4}/episodes.json；登记结果、judge 与 src/ainerzero/v9/mini
修改文件：只新增 reports/V9-MINI/paper-review/
实际执行：.venv/bin/python reports/V9-MINI/paper-review/recompute_tables.py；另跑作者 make_tables.py 与 check_draft.py
验证结果：表 3、表 5 逐格 OK，MISMATCH_COUNT=0；tables.txt 与现跑输出 CMP_OK；check_draft.py 为 ALL OK。Python 3.12.2，numpy 2.5.3
产物：本目录 REPORT.md、recompute_tables.py、recompute_tables.txt、evidence/citations.txt、refs.json、指标.json
失败与限制：参考文献里未打开一手页面的条目标为未核，不凭记忆判核实。没有改 DRAFT.md
交回统筹：结论是改后可作初稿。必改都是方法句和特权表，数字表没有系统性错误

## 结论

改后可作初稿。表 3、表 5 与从 `episodes.json` 独立重算的每一格一致，作者脚本也复现了已提交的 `tables.txt`，`check_draft.py` 报 ALL OK。正文里的确认段区间能在登记结果或 judge 里对上。必改集中在三处方法描述：地图重定位的第二步、`latent_topo` 的定位与路点、特权输入表里「测试时真值位姿」写成 none。这三处都能在原稿上改，不是整表数字错误。

环境是项目 `.venv`：Python 3.12.2，numpy 2.5.3。复核对象提交 `f7c7e8a2` 之后，`reports/V9-MINI/paper` 与 `src/ainerzero/v9/mini` 没有再改。

## 1. 表格独立复算

脚本 `recompute_tables.py` 不导入 `make_tables.py` 或 `check_draft.py`。五个种子的回合合在一起算成功率；m2 的规律相关子集不按短/长过滤；`episodes` 行是回合数。零写成 `0`，其余保留三位小数，与初稿的格子同一规则。

`recompute_tables.txt` 里表 3、表 5 的每一格都是 `OK`，末行 `MISMATCH_COUNT=0`。同一输出里的回合数与长目标簇数是：M4 m1 为 1523 与 186，M4 m2 为 1703 与 231，M5 m1 为 1562 与 196，M5 m2 为 1736 与 240。M4 m2 规律相关簇数是 196，M5 m2 是 178。

作者脚本另跑一次：`cmp` 现跑的 `make_tables.py` 输出与已提交 `tables.txt` 得到 `CMP_OK`；`check_draft.py` 打印 `ALL OK`。记录在 `evidence/citations.txt`。

## 2. 正文数字溯源

摘要、§3–§8 和附录 A 里，形如 `±d.ddd [±d.ddd, ±d.ddd]` 的区间，脚本逐条对照了登记结果、judge、summary、A34 验收记录和 PLAN。除摘要外都是 `VERBATIM`。

摘要五行区间是 `SIGN_NORMALIZED`：数值与登记结果相同，括号内的加号被拿掉。例如初稿写 `+0.948 [0.921, 0.971]`，M5 结果写 `+0.948 [+0.921, +0.971]`。这是符号写法，不是另一个数。严重程度：**建议**。

§6.3 的定位拆分从 M4 m2 的 `episodes.json` 重算：长目标 907 个里，`map_hybrid` 开局迷路 399、已定位 508；迷路子集成功率 0.699248，已定位 0.964567；按同一拆分，`map_analytic` 是 0.441103 与 0.862205。初稿的 0.699、0.965、0.441、0.862 是这四个值的三位小数。全部回合开局迷路比例 0.364651，长目标失败 138 个里开局迷路 120 个、比例 0.869565，对应初稿的「约 37%」和「87%」。

M5 `latent_topo` 长目标的全图重定位均值：m1 成功回合 0.459459（四舍五入到一位是 0.5），失败回合 6.637241（一位是 6.6）；m2 成功 0.573770（0.6），失败 5.060571（5.1）。与初稿的 6.6、0.5、5.1、0.6 一致。

自监督标签与真值的一致率：m1 五个种子都是 1.0；m2 五个种子是 0.9995059236599493、0.9995836672668796、0.9993989560816154、0.9993233170154051、0.9994702211297004。四位小数落在初稿写的 0.9993–0.9996。世界模型训练秒数都在一分钟以内。`200*4*200` 与 `200*1*800` 都是 160000。网格边长 19，观察维数 329，三步动作序列数 27。

两处没有出处：

- **建议。** §5 写 “per-episode intervals would be about half as wide.” 预登记只给出一次探索对比（按回合区间不含 0、按图区间含 0），没有「大约一半宽」这个因子。
- **建议。** §8 写 “one Apple M2 Max laptop.” 十次 `result.json` 的 `machine` 都是 `arm64`，交付材料里没有 M2 Max 这个字符串。

§3 的「随机游走里约 1% 的前进一步触发未知规律」出自 PLAN §6.1，原文是「约占 1%，属于稀有事件」。它写在环境设定里，没有标成探索观察、不算证据。严重程度：**建议**。

H3 的 judge 输出是 `+0.112 [+0.068, +0.159]`，初稿表 2 写 `+0.112 [+0.066, +0.159]`。后者与 M4 结果报告逐字相同；结果报告已经说明 judge 的下界差不超过 0.002。这不是初稿抄错。

## 3. 方法描述与代码

世界尺寸、3×3 个内部 5×5 的房间、额外门概率、2 格宽冰带、传送门至少隔 8 格、5×5 视野加四向指南针、短目标 4–10、长目标至少 20、预算 `2d*+20`、规律相关的定义，与 `world.py`、`evaluate.py` 一致。预测器是 `z + predictor(...)`。拟度量、代价不超过 k 的训练目标、图记忆边阈值、27 条长度为 3 的序列、ε = 0.05，与 `model.py`、`agents.py` 一致。`latent_topo` 的正例间隔、负例间隔、捷径门槛 0.95、定位门槛 0.5 和 4 跳，以及注意力组的层数、宽度、头数、RoPE、pre-LN、`Q = 1 + scale·softplus`、Huber、Polyak τ、窗口和批量，与 `topo.py`、`attn.py` 的配置一致。自监督标签的三条来源和迷路步不入训练，与 `mapagent.py` 的 `_advance`、`residual.py` 的 `collect_self` 一致。

### 必改：重定位的第二步并不是「整图上唯一就采用」

初稿 §4.3：

> failing that, by a unique consistent pose on the whole map; failing that, it is lost

`mapagent.py` 文件头先写「找不到就在整张地图上找，唯一一致就采用」，紧接着又写「整图上唯一一致的位姿也不直接采用」。`_advance` 在射线上解释不了时，无论整图候选是不是唯一，都打开碎片，并把候选放进 `self.cands`。并回主地图要等只剩一个候选，且重叠至少 `MERGE_MIN_OVERLAP = 20`。初稿把已经作废的第二步写成了现行行为。

### 必改：`latent_topo` 的目标定位和路点不是初稿写的算法

初稿 §4.2：

> The goal is localized by R. … It then follows the farthest reachable waypoint among the next few nodes of the graph shortest path.

`TopoAgent.reset` 先用观察字节精确匹配前缀帧；只有目标观察不在前缀里时才对 R 取 argmax。本任务的目标来自前缀，正常走的是精确匹配。

`decide` 沿最短路最多看 `h_path = 30` 条边：同一处的边跳过；第一条正向边重放当时的动作；第一条逆向边或捷径边才把那个节点交给运动网络。它没有在「接下来几个节点」里用 R 挑最远的可达路点。文件头描述的是后一种算法，现行 `decide` 没有实现它。

定位也多一种回退：邻域里没有足够像的帧时，才做全图 argmax；全图仍低于 0.5 就保持原估计。观察完全相同但不在邻域内时，取相同帧列表的第一个，并计入 `relocalizations`。初稿只写了「4 跳邻域，否则全图」。

### 必改：特权表把测试时的真值位姿写成 none

初稿 §4.5：

> True poses at test time | none

`evaluate.py` 的 `run_episode` 把真值位姿交给 `Oracle.act_pose`，并把真值位姿、地图和任务交给 `act_privileged`。`TopoOracleControl.act_privileged` 用真值最短路走向路点所在格。这两类输入在 §4.4 和表 1 里有特权标记，但特权总表写成没有任何智能体在测试时使用真值位姿。地图组本身不用真值坐标，这一行仍把 oracle 和 `topo_oracle_ctrl` 漏掉了。

### 建议

- 前进模型训练对视野以外的格子以 `mask_prob = 0.5` 置为未知（`residual.collect`）。初稿只写了 `map_ungated_aug` 额外遮近处格，概率 0.15。近处遮挡的句子是对的，远处遮挡没有写。
- §8 的命令没有 `--out`。`run.py` 里 `--out` 是必填，缺了就不能跑。预登记里的命令有输出目录。

## 4. 措辞与口径

两份预登记要求：不写「架构被证明正确」，M5 还不写「潜空间方法不行」。初稿 §7 明确否定了这三句：显式地图一般优于学到的记忆、潜空间或 Transformer 学不会这个任务、整套架构「正确」。§6.3 把 `latent_attn` 限定在这个实现和 160000 环境步。两个世界的门和表是分开报的。§6.4 的标题是 not evidence，里面的 0.994、0.019、秩相关和 70%、90%、0.989、0.979、300 样本时的 0.79、0.51、3 个事件，都能在 PLAN §4 与 §6.4 对上。只报告的比较标了 “no gates”，并写明不把门控与先验乐观混在一起当作门控的证据。

M4 m1 长目标上，`map_hybrid` 与 `map_analytic`、`map_hybrid_self` 与 `map_analytic` 的成功标记不一致次数都是 0。摘要里「规律已知时不更差」对这两种标签都成立。

仍建议改的口径：

- **建议。** 题名用 Preregistered。§2 和 §5 写了内部冻结，不是公开登记。文末作者注已经指出这一点。正文没有把复核者写成人类审稿人，但也没有写明是另一个 AI agent；作者注第 2 条要求投稿前写明。
- **建议。** §5 把「另换五个随机种子、多项式簇权重」放在复算段。A34 验收写的是「作者侧的自查（不算非作者复算）」，端点变动不超过 0.003。同一段前面已经说明非作者复算沿用了作者的随机数顺序，这句本身没有夸大。
- **建议。** 摘要里先说自监督标签的地图智能体胜过六类学到的记忆（这是 M5 的 H1s），下一句的 `+0.171` 和 `+0.112` 是 M4 里用真值标签的 `map_hybrid`。数字各自有出处，句子没有点明换了智能体。
- **建议。** §6.3 的探索上界写了 “Reaching 1.00 requires…”。PLAN §10.4 的同一句在 §10.5，但表里「站过的格、任意方向」在 m2 是 0.59，不是 1.00。40 与 68 是 PLAN §10.3 的探索回合数，0.20、0、0.45、0.10 与 §10.4 的表一致。这段标了 exploration-stage，但没有放进 §6.4 的 “not evidence”。

没有把确认段写成「架构被证明」或「Transformer 做不到」。

## 5. 参考文献

`refs.json` 每条一个状态。打开了一手页面或会议/出版社页面的，才标核实。没有打开的标未核。

不符有三条：

- Ha 与 Schmidhuber：NeurIPS 2018 的题名是 Recurrent World Models Facilitate Policy Evolution；World Models 是 arXiv:1803.10122 的题名。
- Hafner 等 DreamerV3：Nature 2025 的题名是 Mastering diverse control tasks through world models，不是初稿的 diverse domains。
- Maes 等：arXiv:2603.19312 的题名是 LeWorldModel: Stable End-to-End Joint-Embedding Predictive Architecture from Pixels。初稿只写了 LeWorldModel (LeWM)。第一作者和年份相符。

Bardes 等的 V-JEPA 标未核：abs 页没有写 TMLR，检索里还有 ICLR 2025 的 poster 页，本轮没有打开 TMLR 出版社页面。其余未打开页面的条目在 `refs.json` 里标未核。作者注已经要求投稿前核参考文献，这三条不符按 **建议** 改，不改变实验结论。
