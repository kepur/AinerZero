# P261 最小入口修复

仅修改 make_prereg.py、新增 prereg_evidence.py、新增 CPU 测试及本目录。先领取后编辑；保留所有并发改动。

不导入运行器/cells/MLX；静态读取真实源码配置，读取 probe 原始闭包，重算既有纯 NumPy analysis。代码 manifest 继续使用 runner + verify 的原有42文件，不纳入 builder；正式冻结 manifest 另纳入 builder/helper/design。这样构建器修复不改训练数值源码身份，不要求无意义重训。

F1：严格类型、完整格/轮/重放/复训/pool，逐文件哈希与原始 picks/reveals/weights、errors、worlds、ledger闭环；重算门、描述量和选择统计，允许科学门失败。
F2：冻结入口验证训练ledger、eval报告、当前源码及已提交源码的同一数值manifest。probe ledger git_head 原运行器写 null，不能伪装有提交身份；用报告git commit的源码字节与当前已提交源码对照弥补。run_eval自身仍未修复。
F3：正有限耗时、精确集合、cell/round/ledger/report计时核对，28格/6h/1h及原外推式不变；全部校验与JSON序列化先于排他写输出。

验证：明确标为合成的完整CPU夹具，真实builder/helper；只替换禁止MLX的版本查询接缝。正例含失败科学门，逐类损坏零写入；预算边界；至少4个副本变异并保存原始输出；对原42文件前后SHA审计。真实eval完成后仅只读调用validator，绝不写正式prereg/final。
