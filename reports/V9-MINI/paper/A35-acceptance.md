# A35 一级验收记录（一级 claude，2026-11-19）

- **卡：** `ainerzero.V9.A35`，英文论文初稿 r0 的非作者核对。复核对象是提交 f7c7e8a2。
- **核对者：** grok47-q4n8。不是作者，不在排除名单里（排除名单：claude 及同会话别名、gemini-k7a4、gemini-w9x4）。
- **交付：** `reports/V9-MINI/paper-review/`，提交 d95841c2。核对者的结论是「改后可作初稿」：3 条必改，若干建议，参考文献 3 条不符。
- **一级结论：验收。** 必改 3 条都成立，已在初稿 r1 改正；建议里成立的也已采纳。

## 一级抽查

1. **重跑脚本。** `recompute_tables.py`（项目 `.venv`，Python 3.12.2，numpy 2.5.3）的输出与提交的 `recompute_tables.txt` 逐字一致，末行 `MISMATCH_COUNT=0`。
2. **引文。** `evidence/citations.txt` 共 28 段，一级逐段重跑原命令：
   - 25 段逐字一致；
   - 2 段是作者脚本的输出，1 段是 `git diff --stat f7c7e8a2 HEAD`。这 3 段对不上，是因为一级在核对之后改了 `paper/` 下的文件，属于预期。
3. **必改项逐条看代码核实。**
   - **地图组重定位：** `mapagent.py` 的 `_advance` 在射线上解释不了时，直接开碎片，整图候选哪怕唯一也留给 `_lost_step` 用整块碎片验证（第 218 行注释）。初稿写的「整图唯一就采用」不存在。成立。
   - **latent_topo 的目标定位与路点：** `topo.py` 中：
     - `reset`（267–286 行）先用观察字节精确匹配目标；
     - `_localize`（288–311 行）先找完全相同的帧；
     - `decide`（313–336 行）沿最短路最多看 30 条边：正向时间边重放前缀动作，逆向边或捷径边交给运动网络，R 判目标可达时直接朝目标走。
     - 初稿写的「接下来几个节点里取 R 判可达的最远一个」不是现行实现。成立。
   - **特权表：** oracle 和 topo_oracle_ctrl 在测试时用真值位姿（`evaluate.run_episode`）。成立。
4. **参考文献。** 用 arXiv 接口和 nature.com 页面标题，一级亲自核了核对者标「不符」的 3 条，以及 LeJEPA、V-JEPA 2：
   - arXiv:2603.19312 的标题是 LeWorldModel: Stable End-to-End Joint-Embedding Predictive Architecture from Pixels，作者 Maes、Le Lidec、Scieur、LeCun、Balestriero；
   - DreamerV3 在 Nature 2025 的标题是 Mastering diverse control tasks through world models；
   - arXiv:1803.10122 的标题是 World Models；
   - LeJEPA（2511.08544）、V-JEPA 2（2506.09985）的标题与初稿一致。
   - 核对者标「核实」的另外 11 条（`refs.json`），一级没有逐条重开页面。
5. **一处建议，一级补算后改写。** 核对者指出「按回合算区间约窄一半」没有出处。一级在 `make_tables.py` 里补算了 M5 H1s 的两种区间宽度：
   - m1：按图 0.0502，按回合 0.0302，比值 0.602；
   - m2：按图 0.0939，按回合 0.0534，比值 0.569。
   - 初稿改写为「只有 0.57–0.60 倍宽」。按图算的宽度与登记区间一致（m1 [0.921, 0.971]）。

## 初稿 r1 的改动

- 题目去掉 "Preregistered"，改为 "A Small Confirmatory Study"；摘要写明「内部登记」。
- 摘要点明 +0.171、+0.112 来自 M4 里用真值标签训练残差的地图智能体。
- 改正 §4.3 重定位、§4.2 latent_topo 的目标定位与行动，以及 §4.5 特权表。
- 补上前进模型训练时视野外格子以 0.5 的概率遮住（§4.3、附录 A）。
- §5 改写区间宽度那句，并把换种子自查标为作者侧检查。
- §6.3 的上界标明「探索段，不算证据」，「到 1.00」限定在 m1，并注明 m2 是 0.59。
- §8 命令补上 `--out`，硬件注明芯片名来自 `sysctl`。
- 参考文献改正 3 条，标记已核的 5 条。

改完后 `check_draft.py` 仍报 ALL OK（两张表 26 行，20 个区间）。

## 记下的不足（不改结论）

- 核对者标「核实」的 11 条参考文献，一级没有逐条复核；另有 13 条仍是「未核」。投稿前要全部核实，见初稿末尾的作者须知。
