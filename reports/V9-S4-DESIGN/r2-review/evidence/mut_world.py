"""世界模块的变异（复核者自写）。每个变异复制 src/ainerzero、tests/conftest.py、test_s4_world.py、pyproject.toml 到临时目录，改一处（恰好一次、过语法检查），跑世界测试。
用法：mut_world.py <副本根> <输出 json>"""
import ast, json, os, shutil, signal, subprocess, sys, tempfile
from pathlib import Path
BASE, OUT = Path(sys.argv[1]), Path(sys.argv[2])
HERE = Path(__file__).resolve().parent
F = "src/ainerzero/v9/experiments/s4/world.py"
T = "tests/v9/experiments/test_s4_world.py"
M = [
    ("wall_log_wrong_sign", "(lo[0] & (v[0, :, d] < 0)) | (hi[0] & (v[0, :, d] > 0))", "(lo[0] & (v[0, :, d] > 0)) | (hi[0] & (v[0, :, d] < 0))"),
    ("pillar_always_reflect", "back = hit & (vn < 0)", "back = hit"),
    ("disk_log_overlap_not_approach", "for i, j in zip(*np.nonzero(approach[0])):", "for i, j in zip(*np.nonzero(ok[0])):"),
    ("disk_push_only_when_approaching", "push = np.where(ok, 2 * RADIUS - dist, 0.0)", "push = np.where(approach, 2 * RADIUS - dist, 0.0)"),
    ("impulse_half", "dv = np.where(approach[..., None], rel[..., None] * nrm, 0.0)", "dv = np.where(approach[..., None], 0.5 * rel[..., None] * nrm, 0.0)"),
    ("disks_need_three", "if disks and n > 1:", "if disks and n > 2:"),
    ("view_ignores_pillars", "and not line_blocked(np.array([x, y]), q, pillars))", ")"),
    ("view_range_strict_half", "math.hypot(d[0], d[1]) <= VIEW_RANGE", "math.hypot(d[0], d[1]) <= VIEW_RANGE / 2"),
    ("no_shuffle", "        ar.shuffle(pairs)\n", "        pass\n"),
    ("student_view_leaks_ids", '"detections": step.detections.copy()}', '"detections": step.detections.copy(), "truth_ids": step.truth_ids.copy()}'),
    ("events_need_no_detection", " and k in detected[last] and k in detected[t]:", ":"),
    ("window_old", "for s in range(last, t))", "for s in range(last + 1, t))"),
    ("window_includes_b", "for s in range(last, t))", "for s in range(last, t + 1))"),
    ("events_gap_one_allowed", "t - last > 1 and", "t - last > 0 and"),
    ("registered_empty", 'REGISTERED = frozenset({"s4p1-final"})', "REGISTERED = frozenset()"),
    ("guard_after_seed", "    if namespace in REGISTERED and not allow_registered:\n        raise PermissionError", "    _ = derive_seed(namespace, 'probe')\n    if namespace in REGISTERED and not allow_registered:\n        raise PermissionError"),
    ("batched_log_copy_last", "for i, j in zip(*np.nonzero(approach[0])):", "for i, j in zip(*np.nonzero(approach[-1])):"),
]
def copy_tree(dst):
    shutil.copytree(BASE / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "tests/v9/experiments").mkdir(parents=True)
    shutil.copy2(BASE / "tests/conftest.py", dst / "tests/conftest.py"); shutil.copy2(BASE / T, dst / T); shutil.copy2(BASE / "pyproject.toml", dst / "pyproject.toml")
def pytest(dst):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}; env["PYTHONPATH"] = str(dst / "src"); env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run([sys.executable, str(HERE / "pyt.py"), str(dst), "-q", "-x", "-p", "no:cacheprovider", T], env=env, capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout[-300:]
res = []
with tempfile.TemporaryDirectory(prefix="s4w-mut-") as tmp:
    base = Path(tmp) / "base"; copy_tree(base); rc, tail = pytest(base); print("unmutated", rc, flush=True)
    assert rc == 0, tail
    for name, old, new in M:
        d = Path(tmp) / name; copy_tree(d); f = d / F; t = f.read_text()
        if t.count(old) != 1:
            res.append({"name": name, "status": "stale", "count": t.count(old)}); print(name, "STALE", t.count(old)); shutil.rmtree(d); continue
        t = t.replace(old, new); ast.parse(t); f.write_text(t)
        rc, tail = pytest(d)
        import re
        m = re.search(r"FAILED \S+::(\S+)", tail)
        res.append({"name": name, "status": "killed" if rc else "SURVIVED", "by": m.group(1) if m else None})
        print(name, res[-1]["status"], res[-1]["by"], flush=True); shutil.rmtree(d)
OUT.write_text(json.dumps(res, indent=1)); print("killed", sum(r["status"] == "killed" for r in res), "of", len(res))
