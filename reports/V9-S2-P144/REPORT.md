# ainerzero.V9.P143（交回目录 P144）：S2 评测 runner

- **执行**：`composer-a7k2`；completed；依据 DESIGN-r2 §4/§5/§7；看板 ID=P143，产物目录=`reports/V9-S2-P144/`。
- **实现**（`s2/eval_runner.py`，纯 CPU，无 MLX）：
  1. `run_plan_select`：仅 train 规格；flat H∈{16,32,48}；分层宏视野×预算比；成功率优先、平局取更小计算量；冻结 JSON。
  2. `run_dev_eval`：冻结超参、长/短/规则 dt、N_fwd 三档曲线、train-only 探针拟合、分簇差值；账本计数，第 3 次拒绝；超 N_fwd 作废。
  3. `run_final_eval`：独立 `APPROVED s2-phase1 final-eval document_sha256=`（拒预登记行与引用块）；read_once 标记；门判定看差值与下界与 δ_pred。
- **测试 11/11**：拒 dev 选参、最优 H、平局、dev×3 拒、探针 train-only、预算作废、final 批准/引用块/只读一次、门下界、纯 CPU。
- **变异 5/5 全红**：M1 放行 dev / M2 关计数 / M3 预登记充当 final / M4 二次只读 / M5 忽略下界。
- **隔离全量**：500 passed / 4 failed（既有 s1 注册缺产物）/ 2 skipped。
- **SHA**：见 `metrics.json` / `file_shas.json`。未改其他 s2/e1/conftest；无 artifacts / 无提交。
