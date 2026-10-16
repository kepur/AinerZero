# ainerzero.V9.T1 报告：教师与缓存规范 v0

- 作者：Claude（一级），2026-10-16。只写设计，没有下载、安装、训练或 GPU 运行。
- 交付：
  - `docs/v9/TEACHERS_AND_CACHE.md`：三模式规则、缓存、坐标与时间、噪声标定方法、授权清单与内存分账、给后续卡的接口要求、未决项；
  - `contracts/v9/teacher_cache.v0.schema.json`：JSON Schema 2020-12，两种记录 `cache_entry` 与 `noise_calibration`；
  - `contracts/v9/examples/teacher_cache/`：5 个正例、19 个结构反例、4 个语义反例，以及 `EXPECTATIONS.json`；
  - `reports/V9-T1/make_examples.py`（生成正反例）与 `reports/V9-T1/check_teacher_cache.py`（核对）。

## 实际命令

```bash
python3 -I reports/V9-T1/make_examples.py /Users/mac/AinerWorkFlow/AinerZero
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -I reports/V9-T1/check_teacher_cache.py /Users/mac/AinerWorkFlow/AinerZero reports/V9-T1/check_result.json
```

- 两个 AinerZero 环境都没有 jsonschema。因此只读借用 AWZ 的 `.venv`（jsonschema 4.26.0）运行核对，没有安装任何东西。
- 结果：返回码 0。
  - 正例 5/5 通过；
  - 结构反例 19/19 被拒，且每个都在预期字段上命中预期关键字；
  - 语义反例 4/4 结构合法、但被跨字段检查按预期理由拒绝；
  - 8 个破坏自检全部变红，每个都被对应的反例抓住。

## 核对内容

| 类别 | 内容 |
|---|---|
| 结构反例（19） | 考场分区写进缓存；用帧序号代替时间；权重清单为空；来源写成 `teacher_claim`；特征教师带米制尺度；几何教师尺度写 `not_applicable`；RLT 缺阈值；RLT 缺 token 统计；`numeric` 可复现等级缺容差；特征教师带噪声模型；坐标变换行列式符号为 0；许可链接非 https；摘要大写；许可范围缺项；噪声标定用了考场分区；登记的噪声模型覆盖率低于 0.90；登记时世界数不足 30；掩码教师用高斯模型；Student-t 缺自由度 |
| 语义反例（4） | `cache_key` 不等于 `key_material` 规范 JSON 的摘要；`derived_by` 与 `teacher_id` 不一致；未批准的教师（`approval_ref = null`）；时间戳不单调 |
| 破坏自检（8） | 分区允许 `final`；来源类型放开为任意字符串；去掉覆盖率区间；去掉特征/几何尺度规则；去掉 RLT 统计规则；关掉 cache_key、单调性、批准三项语义检查 |

## 摘要

| 文件 | sha256 |
|---|---|
| docs/v9/TEACHERS_AND_CACHE.md | c386bb371dd13f54f6735f6f60d7d4971e26aa66771f4b2f1763b09426c2dfdc |
| contracts/v9/teacher_cache.v0.schema.json | 55c899b7517b2a3f66f39bf383f2dd222a39f31937f88b4c998962b40df41d30 |
| reports/V9-T1/make_examples.py | 1b2ca56f3c7476e13f6b81b4be61ddfe4cd1cdf84e49dcfe80c9228d07b0549d |
| reports/V9-T1/check_teacher_cache.py | 3f5648ab5bb4d7992d576d18e10e65c25c5481574f5dd002c3396876cd5ec774 |
| contracts/v9/examples/teacher_cache/EXPECTATIONS.json | 3ebde5a4d36afd4a4fe071c7dd65f6c80bcb38883254fdb5059e6dc35fda89bc |

## 未验证与限制

- 内存上限（§1.1）、计算单元选择（§1.5）、可复现等级（§2.3）、各教师常驻内存（§5）都是规划值，等 T4 实测回填。
- 示例里的哈希是确定性占位值，不对应真实文件。DA3 的批准编号 `R20261016-T6-placeholder` 是占位，T6 未获批准。
- schema 只管结构。跨字段规则（cache_key、derived_by、批准、时间单调）必须由 T2 的读写代码实现；本核对脚本里的 `semantic_problems` 是参考写法，不是生产代码。
- `generation.started_at` 声明了 `date-time` 格式，但 jsonschema 默认不强制格式。
- 文件锁 `teacher-mode.lock` 和 `ModeGuard` 只是设计，T2 实现。旧 M2 CLI 不改。
- 新来源类型 `teacher_feature`、新包类型 `teacher_features` 要等 forge.V9.A1 加入 APACK 词表后才正式成立。
- 本文没有经过非 claude 一级审议。
