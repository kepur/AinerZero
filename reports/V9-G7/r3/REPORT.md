# G7 r3 作者实现报告（待非作者复核）

执行者 codex-g7-r3，tier 2 / kind codex；用户授权后普通领取，初次缺 deep 被拒，父级授予一天后成功领取。仅修改 mechanism 源码/测试及本 r3 目录；不自行验收、不晋升。

## 修复与证据

- **G9 F1**：门内从当前候选、D、prior 与通过 ExecutablePriorChecker 的库重建冻结 null 配方，按语义律内容比较完整集合，不能用列表长度或 ID 认证。29 个同 ID / 不同 ID 空律均拒绝；单个系数改动、少一个对照、换 D 但沿用旧对照均拒绝。规范对照可准入。零裁剪备选项会与空律重合，因此构造器去重（合并同名项、去零项），门再次拒绝重复语义；若去重后不足原统计分母则失败关闭，不补造候选、不改 tau/delta/n_req。
- **内容绑定**：decision 新增 recipe SHA 与 binding SHA，绑定 registration、D 数值内容、C_clean 内容、prior mean/cov、候选律与预期/实际 null 律。源文件 SHA 另见清单。配方评分仍是既有双侧 NIS 窗口比例，严格超过阈值；任何统计门槛未放宽。
- **G9 F2**：保留已打开测试集 ID，同时预留历史 world_instance_id 和不含名字的观测内容 SHA。D/C/T 当次亦比较内容交集。旧 T 只改 test_data_id、连 world/context/object/time 名字一起改均拒绝；拒绝步骤的 T 同样不可重用。新独立世界推进 t=2，重新消费预算。每个完整 decision 只追加世界 ID / 内容摘要；在评分前预留，后续异常也不能在同一实例重新打开暴露的 T。
- **G9 F3**：默认仍是 nuisance_cov=None 的硬投影。GLS 与关闭投影的发现返回 diagnostic_only=True，晋升门明确拒绝该标记；不将有限 GLS 当硬正交，不将其恢复率算作默认能力。新增硬投影默认一致性、硬正交/GLS 非正交及诊断晋升拦截测试。
- 旧 r2 测试的晋升正控原通过 GLS 发现获得；本轮改成显式固定的玩具真机制，以隔离晋升门测试。它不是硬投影成功发现证据，亦不涉及真实来源认证。GLS 发现测试仍保留作诊断。

## CPU 结果

最终 pytest：**41 passed in 10.23s**，rc=0，见 evidence/pytest-final.txt。

sealed-probes/metrics.json：规范真机制准入；非空错误机制拒绝；F1/F2/F3 三个单处源码变异分别被抓到（3/3）。每个变异先在真包确认正控；变异仅在临时目录，未写产品源码。

每格 10 次，每次 6 个合成世界（固定 seed 见 verify_r3.py）：

| 方法 | 纯参数假发现 | W20/dt .01/σ .003 精确 drag 支持 | W16/dt .015/σ .0025 G8类设定精确支持 |
|---|---|---|---|
| 默认硬投影 | 0/10 | 8/10 | 2/10 |
| GLS 仅诊断 | 0/10 | 10/10 | 10/10 |

这里的“恢复”仅是支持集合，不保证系数精确；两组生成与 G9 独立夹具不同，不能混用其 3/10、7/10 或 r2 的 20/20。硬投影吸收共线机制的代价仍在，未通过换算法或改门槛掩盖。

## 实际命令与失败保留

所有测试/探针均经 `/Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.G7 --agent codex-g7-r3 --` 执行，持续登记及心跳，日志有 rc、PGID 和 confirmed_empty=true。

```sh
env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest tests/v9/mechanism -q -p no:cacheprovider
env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B reports/V9-G7/r3/verify_r3.py --out reports/V9-G7/r3/evidence/sealed-probes
```

复核时 --out 必须指向不存在的新目录；默认不重写交付。verify_r3.py 复用作者测试辅助器，**只是作者 CPU 验证，不能充当外部独立证据**。

第一轮 27 passed/3 failed：严格重复校验暴露原配方内零裁剪备选重复；第二轮含新增测试 30 passed/10 failed，仍是该缺陷。修正构造器去重后 40 passed，再加诊断拦截后 41 passed。原失败日志 pytest-initial.txt、pytest-r3.txt 原样保留；后续所有日志亦保留。未把失败改写为成功。

## 身份、完整性与限制

HEAD、候选逐文件 SHA、共用 interfaces 身份、ADR 与冻结 registration 身份见 evidence/manifest.json。mechanism 是未跟踪工作树代码，HEAD 不是候选提交。before.json 保存修改前摘要；r1-archive/r2 原字节完整性复核见 manifest。原 r1 清单自身的历史自引用瑕疵不修。

- 历史状态当前限同一 OneSidedPromotionGate 实例；无跨进程持久账本/恢复入口，不宣称已实现。完整决定追加可审计摘要，但启动新实例会丢历史，调用方必须保持单一序列所有者。
- 内容指纹防原样换名，不是物理世界认证；修改数值、重采样或截取窗口后再更换世界 ID，仍需要外部可信采样/世界来源机制。不能证明任意世界独立性。
- 配方由门内确定性重建、源码与内容 SHA 可审计，不是第三方签名证书；自定义库由调用方提供，本卡不认证任意可执行库的真实来源。退化配方直接拒绝，未新增 null 统计有效性证明。
- diagnostic_only 是诚实 API 元数据，不防恶意调用方手造对象移除标记；没有 Σφ 事前来源证书，GLS 只保留诊断，不推荐晋升。
- 未运行真实数据/模型/MLX/训练，无下载/安装/付费/生产部署，未触碰共享模型锁与 RunStore；真实预算预留与消耗均 0。CPU 工作不申报为模型能力。
- 未提交/推送；未改科学冻结参数、根研究文件或 r1/r2。未全面证明 e-process 条件均值、独立性假设、FDR 或一般恢复能力。请父统筹安排非作者复核本 r3 精确文件 SHA；作者不自行独立验收。
