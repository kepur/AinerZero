# ainerzero.V9.G10 执行报告
角色：executor；负责人：composer-6201；时间：2026-10-28
任务状态：reported；实验状态：completed（只读 CPU 复核；不自行 accept）
任务依据：ainerzero.V9.G10 参数 v1；验证对象 ainerzero.V9.G7 r3（作者 codex-g7-r3）
输入身份：HEAD `2de6caef0820894520271a8943761cc0b3cf8c22`；mechanism 为未跟踪工作树；registration_sha=`1c66d40dfc5b0231f5396754871f6c1712358a5e596fd680ccebb716b324c7a3`；FACTTEST_RECIPE_SHA=`526b10b7faeffdc105de1e85f54a368b730040ce30748d063c3197f326ed9d4a`；逐文件 SHA 与作者 `reports/V9-G7/r3/evidence/manifest.json` 产品条目一致
修改文件：仅新建 `reports/V9-G10/**`（独立夹具/隔离变异副本/报告）；未改产品源码、冻结参数、r1/r2 归档
实际执行：见下；零模型预算；未提交/推送
验证结果：独立夹具全部目标点成立；拆门 3/3；作者回归 41 passed；建议主责验收，本卡不自行 accept
产物：`reports/V9-G10/REPORT.md`、`metrics.json`、`review.py`、`evidence/`、`isolated/`、`SHA256SUMS.txt`
失败与限制：见文末；独立发现恢复率与作者夹具数值不同（不同生成器），不作能力晋升依据
交回统筹：建议对 G7 r3 就 G9 F1/F2/F3 修复予以验收；本复核不构成模型/时空能力声明

## 裁决建议

- **建议主责：accept G7 r3 针对 G9 阻塞项的修复；本卡不自行 accept/reject。**
- 执行者 `composer-6201`（tier2/composer），非 G7 作者名单成员；未参与实现；独立 RK4 夹具，不导入作者测试作独立证据。
- G9 原 F1（29 重复空律洗白）、F2（T 改名重用）、F3（GLS 当默认硬约束）在当前产品上均已失败关闭或如实分界。

## 独立核对（目标点）

| 检查 | 结果 |
|---|---|
| 29 同 ID 空律 | `admitted=False`；原因 frozen recipe/content mismatch or duplicate semantic null laws |
| 29 不同 ID 空律 | 同上拒绝；`facttest_passed=False` |
| 换 ID 错误候选（coulomb 冒充好 ID） | 拒绝（FactTest + e-LOND） |
| T 仅改 test_data_id | `ValueError` N3 historical test world/content reused |
| T 改名 world/context/object/time 但数组相同 | 同上拒绝 |
| 拒绝后仍预留 T | 再次打开同内容 → N3 |
| 新独立世界 | step 2；内容 SHA 无交集；可继续评分 |
| 原正例（规范 null + drag） | `admitted=True` |
| 默认=硬投影；GLS `diagnostic_only` | 默认匹配 hard；GLS 诊断；诊断标记晋升拒绝 |
| 硬/GLS 参数内积 | hard≈1.43e-16；GLS≈0.0709（非硬正交） |
| 非空错误机制 3 组 | 0/3 准入 |
| 真实拆门坏控 | recipe/history/diagnostic 旁路 **3/3 捕获** |

## 实际命令与退出码

```sh
# rc=0，墙钟 ~5s；stdout/stderr → evidence/review-*.txt
relay exec ainerzero.V9.G10 --agent composer-6201 -- \
  env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B reports/V9-G10/review.py

# rc=0，41 passed in 8.90s（仅作者回归，不作独立证据）
relay exec ainerzero.V9.G10 --agent composer-6201 -- \
  env -u PYTHONPATH PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest tests/v9/mechanism -q -p no:cacheprovider
```

## 身份与归档

- 产品 mechanism/tests 与作者 r3 manifest 逐文件 SHA 匹配。
- r1-archive / r2 相对其 SHA256SUMS：除已知 r1 `SHA256SUMS.txt` 自引用空文件瑕疵外全部匹配；失败日志 `pytest-initial.txt` / `pytest-r3.txt` 仍在。
- 冻结 registration（含 tau_cal=0.1、delta_cal=0.05 → n_req=29）未改；recipe SHA 与作者报告一致。

## 独立发现探针（披露，异于作者夹具）

每格 10×6 世界；独立 RK4，非作者 `verify_r3.py`：

| 设定 | 方法 | 纯参数假发现 | 精确 drag 支持 |
|---|---|---|---|
| W20/dt.01/σ.003 | hard | 1/10 | 4/10 |
| 同上 | GLS 诊断 | 0/10 | 10/10 |
| W16/dt.015/σ.0025 | hard | 2/10 | 8/10 |
| 同上 | GLS 诊断 | 2/10 | 9/10 |

与作者报告（hard 8/10 与 2/10；GLS 各 10/10）不可混用；两边都显示硬投影恢复低于 GLS，且 GLS 不得算默认能力。作者已分列披露，本复核确认代码默认与诊断门禁一致。

## 限制（不扩大声称）

- 历史账本仍限单实例内存；内容指纹非物理世界认证。
- `diagnostic_only` 为 API 元数据，不防恶意手造对象。
- 本卡零模型/MLX/下载/付费；未触共享锁/RunStore；未改源码。
- 作者 pytest 与本独立夹具均非跨分布能力证明；不自动晋升。
