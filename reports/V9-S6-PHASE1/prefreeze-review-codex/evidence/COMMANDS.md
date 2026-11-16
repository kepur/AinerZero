# P259 命令与原始输出

仓库 cwd：`/Users/mac/AinerWorkFlow/AinerZero`；Relay cwd：`/Users/mac/AinerWorkFlow/AinerRelay`。

```text
python3 bin/relay register --agent codex-s6freeze-rv-1115 --tier 2 --kind codex --skills code,math
python3 bin/relay claim ainerzero.V9.P259 --agent codex-s6freeze-rv-1115
python3 bin/relay prompt ainerzero.V9.P259 --agent codex-s6freeze-rv-1115
python3 bin/relay heartbeat ainerzero.V9.P259 --agent codex-s6freeze-rv-1115 --msg <当次状态>
```

以上注册/领取/心跳的原始结果由 Relay 任务事件和本聊天工具记录保留；没有将成功领取误当运行授权。

| 命令/动作 | 原始证据 |
|---|---|
| `git rev-parse HEAD` | head-before.txt / head-after.txt |
| `git status --short` | git-status-before.txt |
| `git status --porcelain --untracked-files=no` | tracked-status-after.txt |
| `git show --format=fuller a33d34b -- <四个增量文件>` | delta.txt，文件首行保存 argv |
| `git archive --format=tar a33d34b5cb8d06800f584a0abcfd788d16f80fcb ...` | archive-command.json（完整 argv），snapshot/ 为导出字节 |
| `git show a33d34b:<path>`，逐行编号、SHA256 与工作树 SHA 对照 | citations.txt / input-identities.json |
| `.venv-ainerzero/bin/python -B <本目录>/evidence/cpu_review.py`，最初夹具路径错误 | cpu-review.out / cpu-results.json（保留，不作结论证据） |
| 同命令，输入改放 archive 根下 | cpu-review-r2.out / cpu-results-r2.json |
| `.venv-ainerzero/bin/python -B <本目录>/evidence/cpu_review.py r3` | cpu-review-r3.out / cpu-results-r3.json |
| 禁止 MLX 导入的驱动内 `pytest.main([...])`，如下 | static-tests.out |

静态检查驱动：

```python
import sys, importlib.abc
from pathlib import Path
sys.dont_write_bytecode = True
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'mlx' or name.startswith('mlx.'):
            raise RuntimeError('Forbidden MLX import ' + name)
sys.meta_path.insert(0, Deny())
import pytest
root = Path('reports/V9-S6-PHASE1/prefreeze-review-codex/snapshot').resolve()
rc = pytest.main(['-q', '-c', '/dev/null', '--rootdir', str(root),
                  '--confcutdir', str(root), '-p', 'no:cacheprovider',
                  str(root/'tests/v9/experiments/test_s6_cells_static.py')])
print('MLX_IN_SYS_MODULES', any(n == 'mlx' or n.startswith('mlx.') for n in sys.modules))
raise SystemExit(rc)
```

复现 CPU harness 应使用新的 run label，避免覆盖现有合成证据，例如 `cpu_review.py recheck1`；`r3` 另加了 NaN/Inf/缺臂/零世界/训练上限临界输入。归档不得把 SYNTHETIC 输出移作正式 PREREG。

未执行任何 git add/commit/push/reset/checkout、模型 CLI、共享锁操作、MLX 测试或世界生成。
