"""P240 源码坏对照。只改副本，先断言目标不是实盘仓库。

用法（必须在持锁进程里跑，本脚本自己不再抢锁）:
  .venv/bin/python reports/V9-S5-FIX-2/evidence/mutations.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PY = str(LIVE / ".venv/bin/python")


def refuse(path: Path) -> Path:
    resolved = path.resolve()
    assert resolved != LIVE, "refusing to mutate the live repository"
    assert LIVE not in resolved.parents, "refusing to mutate inside the live repository"
    assert not str(resolved).startswith(str(LIVE) + "/"), "refusing to mutate inside the live repository"
    return resolved


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p240-flathead-mut-"))
    root = refuse(tmp)
    shutil.copytree(LIVE / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(LIVE / "tests", root / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(LIVE / "pyproject.toml", root / "pyproject.toml")
    refuse(root)

    heads = root / "src/ainerzero/v9/experiments/s5/heads.py"
    train = root / "src/ainerzero/v9/experiments/s5/train.py"
    refuse(heads)
    refuse(train)

    muts: list[tuple[str, Path, str, str, list[str]]] = [
        (
            "M1_read_tube0",
            heads,
            "last = tokens.reshape(B, 8, 196, d)[:, 7]",
            "last = tokens.reshape(B, 8, 196, d)[:, 0]",
            ["-k", "test_flat_head_reads_only_the_last_tube"],
        ),
        (
            "M2_mean_pool_before_flatten",
            heads,
            "        scores = self.score(self.norm(last)).reshape(B, 196 * self.k)\n"
            "        return self.position(scores).reshape(B, self.out[0], self.out[1])",
            "        scores = self.score(self.norm(last))\n"
            "        pooled = mx.mean(scores, axis=1, keepdims=True)\n"
            "        scores = mx.broadcast_to(pooled, (B, 196, self.k)).reshape(B, 196 * self.k)\n"
            "        return self.position(scores).reshape(B, self.out[0], self.out[1])",
            ["-k", "test_flat_head_output_changes_when_positions_swap"],
        ),
        (
            "M3_bce_pos_weight",
            heads,
            '        return nn.losses.binary_cross_entropy(\n'
            '            logits, t, with_logits=True, reduction="mean"\n'
            "        )",
            '        w = 1.0 + 9.0 * t\n'
            '        return nn.losses.binary_cross_entropy(\n'
            '            logits, t, weights=w, with_logits=True, reduction="mean"\n'
            "        )",
            ["-k", "test_flat_head_loss_is_unweighted_mean_bce"],
        ),
        (
            "M4_predict_skips_restore",
            train,
            '        r2_logit = heads_container["r2"](r1_tokens)\n'
            '        r3_logit = heads_container["r3"](r1_tokens)',
            '        r2_logit = heads_container["r2"](tokens)\n'
            '        r3_logit = heads_container["r3"](tokens)',
            ["-k", "test_rlt_flat_head_receives_restored_tokens"],
        ),
        (
            "M5_train_heads_skips_restore",
            train,
            '                logits_r2 = model_heads["r2"](r1_tokens)\n'
            "                l_r2 = model_heads[\"r2\"].loss(logits_r2, r2_mx)\n"
            "\n"
            '                logits_r3 = model_heads["r3"](r1_tokens)',
            '                logits_r2 = model_heads["r2"](b_tokens)\n'
            "                l_r2 = model_heads[\"r2\"].loss(logits_r2, r2_mx)\n"
            "\n"
            '                logits_r3 = model_heads["r3"](b_tokens)',
            ["-k", "test_rlt_flat_head_receives_restored_tokens"],
        ),
        (
            "M6_constant_logits",
            heads,
            "        return self.position(scores).reshape(B, self.out[0], self.out[1])",
            "        return mx.zeros((B, self.out[0], self.out[1]))",
            ["-k", "test_flat_head_train_ap_above_positive_rate"],
        ),
    ]

    env = dict(**{k: v for k, v in __import__("os").environ.items()}, PYTHONPATH=str(root / "src"))

    def run(extra: list[str]) -> tuple[int, str]:
        r = subprocess.run(
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", "-rf",
             "tests/v9/experiments/test_s5_train_mlx.py", *extra],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-8:])
        return r.returncode, tail

    print("copy", root, flush=True)
    print("imports", subprocess.run(
        [PY, "-c", "import ainerzero,inspect; print(ainerzero.__file__)"],
        cwd=root, env=env, capture_output=True, text=True,
    ).stdout.strip(), flush=True)

    failed_kill = False
    only = set(sys.argv[1:])
    for name, path, old, new, extra in muts:
        if only and name not in only:
            continue
        refuse(path)
        orig = path.read_text()
        n = orig.count(old)
        if n != 1:
            print(f"{name}: ANCHOR {n}", flush=True)
            failed_kill = True
            continue
        base_rc, base_tail = run(extra)
        if base_rc != 0:
            print(f"{name}: BASELINE_FAIL {base_rc}\n{base_tail}", flush=True)
            failed_kill = True
            continue
        path.write_text(orig.replace(old, new, 1))
        refuse(path)
        rc, tail = run(extra)
        path.write_text(orig)
        status = "KILLED" if rc != 0 else "SURVIVED"
        if rc == 0:
            failed_kill = True
        print(f"{name}: {status} rc={rc}\n{tail}", flush=True)
    return 1 if failed_kill else 0


if __name__ == "__main__":
    sys.exit(main())
