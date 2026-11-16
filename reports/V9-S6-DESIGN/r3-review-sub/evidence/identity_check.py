#!/usr/bin/env python3
"""S6 r3 review, item 3 (pure CPU, no MLX import): can DESIGN-r3 §7.5 be checked as written, and what does it
not cover?
(1) rebuild the probe's code manifest from git history: export a33d34b with `git archive` into a scratch dir
    (argv[1]) and run run_guard.build_manifest exactly as run_s6p1.code_manifest does; compare its sha with the
    probe's recorded code_manifest_sha256 (EVAL-probe.json and train-ledger.json);
(2) the same on the current working tree (r3 not implemented yet, so it should still match);
(3) the AST form of the two values the rule placeholders, in a33d34b's run_s6p1.py;
(4) what run_guard.third_party_versions records for ('numpy', 'mlx') here, against importlib.metadata.
Usage: identity_check.py <empty scratch dir>"""
import ast
import hashlib
import importlib.metadata as md
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402

scratch = Path(sys.argv[1]); scratch.mkdir(parents=True, exist_ok=True)
assert not any(scratch.iterdir()), "scratch dir must be empty"
tar = subprocess.run(["git", "-C", str(REPO), "archive", "a33d34b", "src", "reports/V9-S6-PHASE1"], capture_output=True, check=True).stdout
tarfile.open(fileobj=io.BytesIO(tar)).extractall(scratch, filter="data")


def manifest(root):
    m = GD.build_manifest(root, [root / "reports/V9-S6-PHASE1/run_s6p1.py"], src_root=root / "src",
                          extra=[root / "reports/V9-S6-PHASE1/verify_s6p1.py"])
    return m, hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


m_old, sha_old = manifest(scratch.resolve())
m_now, sha_now = manifest(REPO)
probe = json.load(open(REPO / "reports/V9-S6-PHASE1/probe/EVAL-probe.json"))
ledger = json.load(open(REPO / "artifacts/v9/s6/phase1/probe/train-ledger.json"))
print(f"(1) a33d34b manifest from git archive: {len(m_old)} files, sha {sha_old}")
print(f"    probe EVAL code_manifest_sha256      {probe['code_manifest_sha256']}  equal: {sha_old == probe['code_manifest_sha256']}")
print(f"    probe ledger code_manifest_sha256    {ledger[0]['code_manifest_sha256']}  equal: {sha_old == ledger[0]['code_manifest_sha256']}")
print(f"(2) working tree manifest now: {len(m_now)} files, sha {sha_now}; equal to a33d34b: {sha_now == sha_old}; "
      f"differing files: {sorted(k for k in set(m_old) | set(m_now) if m_old.get(k) != m_now.get(k))}")
src = (scratch / "reports/V9-S6-PHASE1/run_s6p1.py").read_text()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SETS" for t in node.targets):
        final = dict(zip([k.value for k in node.value.keys], node.value.values))["final"]
        for k, v in zip(final.keys, final.values):
            if k.value in ("train_cap_s", "eval_limit_s"):
                print(f"(3) a33d34b SETS['final'][{k.value!r}] = {ast.unparse(v)!r}  node {type(v).__name__}")
print(f"(4) run_guard.third_party_versions -> {GD.third_party_versions(REPO, ('numpy', 'mlx'))}")
print(f"    importlib.metadata: mlx {md.version('mlx')}, mlx-metal {md.version('mlx-metal')}, numpy {md.version('numpy')}")
print(f"    probe recorded third_party: {probe['third_party']}; ledger: {ledger[0]['third_party']}")
print(f"    mlx modules loaded by this script: {sorted(m for m in sys.modules if m.startswith('mlx'))}")
