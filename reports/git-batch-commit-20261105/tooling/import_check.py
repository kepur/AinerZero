"""Import every ainerzero.v9 module and ainerzero.cli from an isolated tree (no MLX-only paths).

Usage: python3 import_check.py <tree_name>   (tree_<name>/ under this directory)
Writes logs/import_<name>.json. Runs in a fresh interpreter with PYTHONPATH=<tree>/src.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/mac/AinerWorkFlow/AinerZero"
CHILD = r'''
import importlib, json, os, pkgutil, sys
import ainerzero, ainerzero.v9
assert ainerzero.__file__.startswith(os.environ["TREE"]), ainerzero.__file__
names = ["ainerzero.cli"] + sorted(m.name for m in pkgutil.walk_packages(ainerzero.v9.__path__, "ainerzero.v9."))
ok, bad = [], {}
for n in names:
    try:
        importlib.import_module(n); ok.append(n)
    except Exception as e:  # record, keep going
        bad[n] = f"{type(e).__name__}: {e}"
mlx = sorted(m for m in sys.modules if m == "mlx" or m.startswith("mlx."))
print(json.dumps({"imported": len(ok), "failed": bad, "mlx_modules_loaded": mlx}))
'''


def main(name):
    tree = os.path.join(HERE, f"tree_{name}")
    env = dict(os.environ, PYTHONPATH=os.path.join(tree, "src"), TREE=tree, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([f"{REPO}/.venv/bin/python", "-c", CHILD], cwd=tree, env=env, capture_output=True, text=True)
    out = {"tree": name, "exit": r.returncode, "stderr_tail": r.stderr.strip().splitlines()[-5:]}
    if r.returncode == 0:
        out.update(json.loads(r.stdout.strip().splitlines()[-1]))
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    with open(os.path.join(HERE, "logs", f"import_{name}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: out.get(k) for k in ("tree", "exit", "imported", "failed", "mlx_modules_loaded")}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
