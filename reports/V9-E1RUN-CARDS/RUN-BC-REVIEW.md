**非作者复核 E1 训练（B-P、B-S）与 dev 评测（C）。** 只读，零运行（只允许 `--mode verify`）。

先读同目录 `COMMON.md`。复核者不得是 B-P、B-S、C 任一卡的作者或其同会话别名，领卡先在卡上自证一行。

逐项亲验，每项附命令和原样输出：
1. **账本**（只读打开 `control.sqlite3`）：
   - 列出本实验全部运行行：模式、臂、族、种子、状态、active_seconds；
   - 合计不超过 18000 s，训练合计不超过 10800 s，dev 合计不超过 1800 s；
   - **没有任何 final-eval 行**。
2. **checkpoint**：18 个文件都存在，SHA 与 B 卡报告一致；随机抽 2 个，读出 best_step，与报告一致。
3. **dev 指标**：随机抽 3 格，用账本或输出目录里的原始结果复算 e_10 的宏平均，与 C 卡汇总表一致。
4. **sealed_final 未被读取**：没有 read_once 标记；修改时间不晚于数据生成结束。
5. **冻结未被改动**：prereg.json 及其 `.sha256`、RESEARCH_LOG 批准节、src/ainerzero/v9/experiments/e1/ 的源码与冻结文档钉住的摘要一致（`--mode verify` 的 identity 为 passed）。

结论写「建议通过」或「建议打回」，并列出必须改的点。
