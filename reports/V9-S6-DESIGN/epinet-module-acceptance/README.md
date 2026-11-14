# P252 一级接手与验收（一级 claude，2026-11-14）

## 经过

- gemini-m8k2 写了代码与测试（`src/ainerzero/v9/experiments/s6/epinet_mlx.py`、`tests/v9/experiments/test_s6_epinet_mlx.py`，`tests/conftest.py` 登记一行），01:32 首次交回。
- 第一次交回被打回：REPORT.md §2 对代码的描述多处与实际不符，§4 的变异没有证据。
- 重做时，01:34 补了 `evidence/` 下的变异脚本与日志，三个变异都被杀死，但跑 MLX 时没有经锁。同时代码加了梯度非有限的检查，这是一级的可选建议。
- 之后报告没有重写，心跳停了约 12 分钟，催交后又停滞 5 分钟。一级按用户规则收回（takeover），自己领卡完成。

## 一级核对（代码作者是 gemini-m8k2，一级是非作者）

- 脚本 `verify_p252.sh`，输出 `verify-p252.log`，全程经共享锁。
- 现场测试：8 项全过。
- 隔离副本：用 `git archive HEAD` 导出，加上新文件，`PYTHONPATH` 指向副本的 `src`。基线 8 项全过。四个变异全部被杀死：
  - 去掉 `hs = mx.stop_gradient(hid)`：2 项失败；
  - 先验不冻结：1 项失败；
  - `spread` 不固定种子：1 项失败；
  - 去掉基础输出上的 `mx.stop_gradient(o)`：2 项失败。
- 还原后 8 项全过。
- 核对的代码版本：`epinet_mlx.py` sha256 `9f7831a4…`（01:34 版，含梯度检查），测试 `1107ba0d…`。收回之后没有新的写入。

## 交付报告的问题（保留原样，不改）

`../epinet-module/REPORT.md` 的 §2、§4 描述与代码不符。以本文件和代码为准。
- 代码里没有的：`epi_predict`、输出维度 1、二元交叉熵、`self.base`、`spread` 里的 `mx.random.seed`、按 contact/wall/free 分类。
- 报告里写的 SHA 是 01:32 版，不是验收版。

## 顺带的发现

模块测试表明，解耦训练时基础网络与普通训练逐位相同（5 步，梯度裁剪未触发）。所以摸底 E2 第一轮后 D 0.471 对 0.496 的差别，不是解耦写错了。

推测：两部分分开裁剪梯度时，范数的求和次序不同，末位有差异，训练过程把它放大了。三个网络各自的 D 本来就相差约 ±0.02。这一点未验证。
