# ainerzero.V9.A36 执行报告
角色：executor；负责人：grok-m4q8；时间：2026-11-19
任务状态：reported；实验状态：未执行（只读核对，未训练、未评测）
任务依据：ainerzero.V9.A36，参数 v0，复核提交 `0f775370`。非作者会话。文件范围只限 `reports/V9-MINI/paper-review-r2/`。
输入身份：工作区 HEAD `f1d14e57c482408dd3ce5325e507578bfe50fd57` 含 `0f775370`；`git diff 0f775370 -- reports/V9-MINI/paper` 为 0 行（`evidence/pdf-cmp.txt`）。回合日志与 `fig_data.json` 的 SHA-256 在 `recompute_figures.out.txt`。
修改文件：只新增本目录。未改 `DRAFT.md`、`paper/` 下已有文件、`src/`、`tests/`、`reports/V9-MINI/M4/`、`M5/`。重画图写在本目录的副本里，原 PDF 哈希未变。
实际执行：`.venv/bin/python`（Python 3.12.2，NumPy 2.5.3）跑 `recompute_figures.py`；`.venv-fig/bin/python`（matplotlib 3.10.9，NumPy 2.5.5）跑 `make_figures.py` 的副本。文献由 `fetch_refs.py` 自己打开页面，不读 `refs-evidence/`。
验证结果：图 3、图 4、图 5 与 `fig_data.json` 逐值一致（`fig345_mismatches 0`）。图 1 用 `world.make_layout` 与 `evaluate.make_tasks` 重生，字段与回合记录一致。五张 PDF 与五张 PNG 和提交版逐字节相同。29 条文献判为属实。坏对照三例都使 `check_refs.py --offline` 以退出码 1 报错。
产物：本报告；`recompute_figures.py` 与 `recompute_figures.out.txt`；`fetch_refs.py`、`fetch_refs.out.txt`、`refs.json`；`evidence/citations.txt`、`evidence/rounding.txt`、`evidence/pdf-cmp.txt`、`evidence/refs-followup.txt`、`evidence/kind-vs-dstar.txt`；`badctl/{year,author,venue}/stdout.txt`；`指标.json`。
失败与限制：未跑模型，未碰 `artifacts/locks/m0-worker.lock`。首轮文献脚本有三处自己的匹配失误（连字符、OpenReview 多条记录、RSS 年份），已按补开的页面改正，见下文。不把描述性区间当成确认性证据。
交回统筹：结论为可以作 r2。必改项无。建议项见下，不改冻结参数，不另开运行。

## 结论

可以作 r2。

必改项：无。

建议项：

1. §6.3 写 “at most 0.07 (m1)”。m1 长目标各箱里 latent_topo 的最高值是 `0.0728155340`（`fig4_m1_latent_topo_long_max`），`m1_topo_long_max_gt_0.07 True`。三位小数是 `0.073`，两位小数才是 `0.07`。m2 最高是 `0.1405622490`，`m2_topo_long_max_gt_0.14 True`，三位小数 `0.141`，两位小数 `0.14`。建议改成 `0.073` 和 `0.141`，或两边都加 about。
2. 同句 “the gap … widens with distance, from 0.956 vs 0.787 … to 0.719 vs 0.331”。这四个三位小数与复算一致（`round3_d20_self 0.956`、`round3_d20_analytic 0.787`、`round3_ge30_self 0.719`、`round3_ge30_analytic 0.331`）。两端的差从 `0.1686746988` 增到 `0.3884297521`，但 21–22 箱的差是 `0.0843373494`，`gap2122_lt_gap20 True`，不是逐箱变宽。
3. 图 1 写 “not a typical case”。选择规则成立，而且它是该运行第一张（种子 `8100000`，下标 `0`）。满足规则的图有 `27` 张，该运行共 `80` 张。它适合作说明，不宜读成这种对照很少见。
4. 图 4 上 “map_hybrid_self and map_analytic coincide”、灰带 “no goals with 11 ≤ d* ≤ 19”、以及代表 oracle 的 y=1 横线，是 `make_figures.py` 里的字面量，不是从 `fig_data.json` 算出来的。当前数据支持它们：m1 八个箱两臂相等（`fig4_m1_self_equals_analytic_all_bins True`）；m1 与 m2 的 `between_11_19` 都是 `0`；oracle 各箱都是 `1`（`fig4_m1_oracle_all_bins_1 True`、`fig4_m2_oracle_all_bins_1 True`）。字面量不会随数据更新。

## 复算

脚本 `recompute_figures.py` 不 import `fig_data.py`、`make_figures.py`、`make_tables.py`、`check_draft.py`。图 1 调用 `ainerzero.v9.mini.world.make_layout` 与 `ainerzero.v9.mini.evaluate.make_tasks`。簇是（运行 × `layout_seed`），按排序后的簇号，`numpy.random.default_rng(0)` 抽 `4000` 次，取 2.5 与 97.5 分位。环境是项目 `.venv`：Python `3.12.2`，NumPy `2.5.3`。

图 3、图 4、图 5 与 `figures/fig_data.json` 逐值比对：`fig345_mismatches 0`。

短/长标签与 d* 的定义一致：`kind_dstar_checked 60012`，`kind_dstar_mismatches 0`。图 5 各臂在同一下标上的种子、种类、d* 对齐：`fig5_arm_alignment_mismatches 0`。

## 图 3、图 4、图 5

图 3 标题上的回合数来自 oracle：m1 短 `800`、长 `762`、长目标簇 `196`；m2 短 `800`、长 `936`、长目标簇 `240`。m1 三个地图臂的长目标成功率都是 `0.9960629921`，`fig3_m1_three_map_agents_equal True`。三位小数是 `0.996`（`round3_m1_long`），与图注一致。图注写明区间只作描述，确认性比较在表 4。PNG 上 m1 三个地图臂的长目标点重合在右端，短目标也在右端；m2 的 map_analytic 长目标明显低于另外两个地图臂。这和 “m1 三者重合、m2 不重合” 一致。

图 4 分箱回合数：

- m1：`248, 248, 304, 206, 212, 174, 124, 46`。去掉 26–29 与 ≥30 之后是 `174` 到 `304`。26–29 是 `124`，≥30 是 `46`。与图注 “174–304, except 124 (26–29) and 46 (≥ 30)” 一致。
- m2：`279, 251, 270, 249, 249, 189, 128, 121`。最小 `121`，最大 `279`。与图注 “121–279” 一致。
- 两世界都没有 d* 在 11 到 19：`between_11_19 0`。没有 d* 小于 `4`，也没有大于 `99`。m1 最大 d* 是 `42`，m2 是 `51`，所以 `(30, 99)` 这一箱没有把回合漏掉。

d* = 4–5 的 latent_topo：m1 `0.5846774194`（三位 `0.585`），m2 `0.6093189964`（三位 `0.609`）。“about 0.6” 盖得住这两数，和同句的三位小数不是同一粒度。长目标各箱最高：m1 `0.0728155340`，m2 `0.1405622490`，见建议 1。

图 5，M4、m2、长目标，按 map_hybrid 的 `lost_at_start` 拆：迷路 `399` 回合、`101` 簇；已定位 `508` 回合、`130` 簇。二者之和 `907`，等于长目标总数。迷路占长目标 `0.4399117971`，百分数 `43.9911797133`，四舍五入 `44`。与新增句子 “399 of 907 (44%)” 一致。迷路占 map_hybrid 长目标失败的比例是 `0.8695652174`（失败 `138` 次，全部回合 `1703`，全部回合里迷路占 `0.3646506166`）。oracle 两组都是 `1.0000000000`。图上三位小数与复算一致：迷路 analytic `0.441`、memory `0.474`、hybrid `0.699`、self `0.707`；已定位 analytic `0.862`、memory `0.941`、hybrid `0.965`、self `0.965`。hybrid 相对 analytic 的差，迷路时 `0.2581453634`，已定位时 `0.1023622047`，`fig5_gain_larger_when_lost True`。这是差的大小，不是因果。

## 图 1

M5/m2-s0 的 `eval_seed0` 是 `8100000`，世界配置 `ice_rooms 2`、`portals 2`，前缀预设 `400`。选择规则是该运行中第一张有规律相关长目标、且 map_hybrid_self 到达、latent_topo 没到的图。命中种子从 `8100000` 开始，`fig1_chosen_is_first True`。用 `make_tasks` 重生后，任务数 `6`，日志里该种子也是 `6` 条，`fig1_episode_mismatches 0`。网格、传送门、前缀、起点、六个目标、高亮下标、目标视野与 `fig_data.json` 一致：`fig1_field_mismatches []`。

网格 `19×19`。前缀步数 `400`，起点是前缀最后一个位姿。目标 `6` 个，短 `2`、长 `4`。有两个目标落在同一格 `(17, 5)`。高亮目标下标 `3`，d* = `20`，规律相关，种类 long；map_hybrid_self 与 map_analytic 为 `1`，latent_topo 与 latent_attn 为 `0`。冰面连通块 `2`，冰格 `20`；传送门对 `2`，传送门格 `2`。目标视野 `5×5`。PNG 标题是种子 `8100000`、400 步前缀；右侧写着 d* = 20、law-relevant，以及 self/analytic reached、topo/attn failed。地板没有按颜色着色。星标之外能看见的目标圈是四个，加上两个目标共用一格，和六个目标一致。

## 画图脚本与重跑

`make_figures.py` 的数值来自 `fig_data.json`，或是写死的常量。图 1 的 d*、到达/失败、种子来自数据；“400-step” 和 “5×5” 是常量，复算分别是前缀 `400` 步、视野 `5×5`。图 3 的回合数和区间端点来自数据；“d* ≥ 20” 和 “4 ≤ d* ≤ 10” 是常量，与任务定义以及 `kind_dstar_mismatches 0` 一致。图 5 的 n 和三位小数来自数据。图 2 整张是常量，没有实验数据，见下节。

在 `.venv-fig` 里对脚本副本重跑。五张 PDF 与五张 PNG 都是 `IDENTICAL`。原文件哈希未变，其中 `fig1_map.pdf` 为 `b46058a27dca4461e8009df31c380177f1678f44a126d5618ed588ad1cbea22e`。matplotlib `3.10.9`。重跑时 matplotlib 提示 created 时间戳很低；逐字节比较仍然相同。

## 图 2 对照代码

图上的说法和代码一致。出处是 `evidence/citations.txt` 里的 grep/sed 原文。

- 事件记忆：`map_analytic` 是 `memory=False`（`evaluate.py:201`）。`map_memory`、`map_hybrid`、`map_hybrid_self`、`map_ungated`、`map_ungated_aug` 是 `memory=True`（`evaluate.py:203` 到 `211`）。图上写 “all but map_analytic”。
- 前进模型输入：`RAY_LEN = 6`，`RAY_CLASSES = 5`，五类是未知、墙、冰、传送门、地板（`world.py:363` 到 `376`）。
- 并图：`MERGE_MIN_OVERLAP = 20`（`mapagent.py:35`）。只剩一个候选且重叠不少于这个数才并回（`mapagent.py:265`）。不一致的偏移在这之前就被丢掉。
- 残差只在事件样本上训练：`event = out != analytic_outcome(rays)`，然后 `fm.resid.fit(x[event], out[event], ...)`（`residual.py:130` 到 `136`）。
- map_hybrid 的标签来自真值前进结果（`run.py` 里 `R.collect`，`residual.py` 的 `forward_outcome`）。map_hybrid_self 的标签来自 `collect_self`：解析先验智能体自己的定位；迷路期间不记；真值只用于统计，不进训练（`residual.py:149` 起，`run.py` 里 `fms["gated_self"] = R.fit("gated", sx, sy, ...)`）。
- “200 training maps” 对应 medium 预设的 `layouts` 为 200（`run.py` 的 grep）。图 1 读到的 m2-s0 预设前缀是 `400`，与 medium 预设同一套任务设定。

图 2 没有把 “≥ 20”“6 cells”“200” 从 `fig_data.json` 读出来。它们是常量，和上面的代码一致。

## 参考文献

初稿参考文献节有 `29` 行，脚本有 `29` 个键。`fetch_refs.py` 自己请求 arXiv API、Crossref、会议论文集页、OpenReview、MLX README、Open Library 和 ICLR 2018 海报日程。最终 `FINAL_STATUS {'属实': 29}`。写全了作者的条目已逐个核对，包括 Balestriero 与 LeCun、Davison 与 Hinkley、Ha 与 Schmidhuber、Hannun、Digani、Katharopoulos 与 Collobert、Maes、Le Lidec、Scieur、LeCun 与 Balestriero、Parisotto 与 Salakhutdinov、Savinov、Dosovitskiy 与 Koltun、Thrun、Burgard 与 Fox、以及 Kaelbling、LeCun 各一人。

需要单独说明的四条：

- Hafner 等 2020：首轮自动挑选命中 CoRR 2019。补查 OpenReview，forum `zISkM0D80Y` 的 venue 是 `ICLR 2020`，作者与标题一致。arXiv 年份 `2019` 是预印本。初稿写 ICLR 2020，属实。
- Savinov、Dosovitskiy 与 Koltun 2018：dblp 记录 venue 为 `ICLR (Poster) 2018`。ICLR 2018 官方日程页有该标题和这三位作者。属实。
- LeCun 2022：OpenReview 档案上传 `OpenReview.net/Archive/-/Direct_Upload`，forum `BZ5a1r-kVsf`，venue 字段为空，cdate 年份 `2022`，作者只有 Yann LeCun。初稿写 OpenReview, 2022，属实。
- Zeng 等 2020：TRO 的 Crossref 记录是 2020。RSS 记录是 2019、Robotics: Science and Systems XV，对应括号里的 RSS 2019。RSS 作者字段有 Rodriquez、A.Funkouser 这种登记拼写；初稿写 et al.，不把登记拼写算成初稿错误。

`check_refs.py` 核的是：规范化标题、第一作者姓、年份、发表处子串；初稿写全作者时还核人数和顺序；arXiv 预印本作为会议论文的第二来源时用 `TITLE_ONLY`，不核那条的年份和发表处；并检查初稿里有对应的一行。它不核：引文是否支撑所在句子、页码、et al. 后面没写出的作者、括号里的别名（V-JEPA、DreamerV3、MERLIN）是否出现在正式标题里。这些别名不在正式标题里，初稿放在括号中，不构成标题错误。

坏对照在 `check_refs.py` 的副本上做，`--offline`，不改原脚本：

- 把 Davison 的期望年份改成 1998：退出码 1，报 `year 1997`，并报初稿行里没有 1998。
- 把 Ha 的期望第一作者改成 Schmidhuber：退出码 1，报第一作者是 David Ha，并报初稿对不上。
- 把 Hafner 2025 的期望发表处改成 Science：退出码 1，报 venue 是 Nature。

## 正文说法

新增图注里的计数、种子、d*、成功率和三位小数都能在复算输出或 `evidence/rounding.txt` 里找到，除了建议 1 里 “at most 0.07” 比未舍入的最高值更紧。图 3、图 4、图 5 的图注都写了 Descriptive，或写明区间只作描述、确认性比较在表 4。没有把这些区间写成门限已经通过。图 5 的 “account for” 在原有句子里是失败构成比 `0.8695652174`，不是单独的因果估计；新增句子写的是份额。
