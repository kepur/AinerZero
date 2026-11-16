"""S6 freeze identity (DESIGN-r3 §7 item 5), pure CPU: runner difference limited to three constants, probe manifest
recomputed from git, current code identity, library versions from metadata, MLX_* environment."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HERE = REPO / "reports/V9-S6-PHASE1"
spec = importlib.util.spec_from_file_location("s6_prereg_identity_test", HERE / "prereg_identity.py")
PI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PI)

GIT = Path(os.environ.get("S6_PREREG_GIT_REPO", REPO))      # git history (an isolated mutation copy has none)
PROBE_COMMIT = "a33d34b5cb8d06800f584a0abcfd788d16f80fcb"
PROBE_MANIFEST_SHA = "839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3"
OLD_FINAL = '"reps": dict(C.REPLICATES), "worlds": (200, 100), "train_cap_s": 6.0 * 3600, "eval_limit_s": 3600},'
OLD_THIRD = 'THIRD_PARTY = ("numpy", "mlx")'


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT).decode().strip()


@pytest.fixture(scope="module")
def old_runner():
    src = git(GIT, "show", f"{PROBE_COMMIT}:{PI.RUNNER_REL}") + "\n"
    assert src.count(OLD_FINAL) == 1 and src.count(OLD_THIRD) == 1
    return src


def r3(src, train="19800", eval_="5400", third='("numpy", "mlx.core")'):
    out = src.replace(OLD_FINAL, OLD_FINAL.replace("6.0 * 3600", train).replace('"eval_limit_s": 3600', f'"eval_limit_s": {eval_}'))
    return out.replace(OLD_THIRD, f"THIRD_PARTY = {third}")


# --- runner_diff ---------------------------------------------------------------------------------------------------
def test_the_registered_change_passes(old_runner):
    proof = PI.runner_diff(old_runner, r3(old_runner))
    assert proof["old"] == {"train_cap_s": 21600.0, "eval_limit_s": 3600, "third_party": ["numpy", "mlx"]}
    assert proof["new"] == {"train_cap_s": 19800, "eval_limit_s": 5400, "third_party": ["numpy", "mlx.core"]}
    assert len(proof["masked_tree_sha256"]) == 64
    # comments are not part of the syntax tree
    assert PI.runner_diff(old_runner, r3(old_runner) + "\n# a comment\n")["new"] == proof["new"]


def test_no_change_is_refused(old_runner):
    with pytest.raises(PI.IdentityError, match="plain numeric literal"):     # the old 6.0 * 3600 is not a literal
        PI.runner_diff(old_runner, old_runner)
    with pytest.raises(PI.IdentityError, match="frozen runner train_cap_s"):
        PI.runner_diff(old_runner, r3(old_runner, train="21600"))


@pytest.mark.parametrize("variant,match", [
    (lambda s: r3(s, train="5.5 * 3600"), "plain numeric literal"),
    (lambda s: r3(s, train="19801"), "frozen runner train_cap_s"),
    (lambda s: r3(s, eval_="5400 + 0"), "plain numeric literal"),
    (lambda s: r3(s, eval_="True"), "plain numeric literal"),
    (lambda s: r3(s, train='__import__("os").getpid()'), "plain numeric literal"),
    (lambda s: r3(s, third='("numpy", "mlx.core", "scipy")'), "THIRD_PARTY differs"),
    (lambda s: r3(s, third='("numpy", "mlx")'), "THIRD_PARTY differs"),
    (lambda s: r3(s).replace('"train_cap_s": 2.5 * 3600', '"train_cap_s": 3.0 * 3600'), "beyond the three"),
    (lambda s: r3(s).replace("DANGLING_CHARGE_S = 900", "DANGLING_CHARGE_S = 901"), "beyond the three"),
    (lambda s: r3(s) + "\nSETS = dict(SETS)\n", "exactly once"),
    (lambda s: r3(s) + "\nprint('extra')\n", "beyond the three"),
    (lambda s: r3(s).replace('"""S6 一期运行器', '"""S6 一期运行器（改）', 1), "beyond the three"),
    (lambda s: r3(s).replace("import numpy as np", "import numpy as np\nimport os"), "beyond the three"),
])
def test_any_other_change_is_refused(old_runner, variant, match):
    with pytest.raises(PI.IdentityError, match=match):
        PI.runner_diff(old_runner, variant(old_runner))


def test_old_value_may_be_folded_but_new_may_not(old_runner):
    # the probe runner's 6.0 * 3600 folds to 21600.0; a probe runner with a non-product expression is refused
    with pytest.raises(PI.IdentityError, match="plain numeric literal"):
        PI.runner_diff(old_runner.replace("6.0 * 3600, \"eval_limit_s\": 3600},", "6.0 * 3600 + 0, \"eval_limit_s\": 3600},"), r3(old_runner))
    with pytest.raises(PI.IdentityError, match="probe runner train_cap_s"):
        PI.runner_diff(old_runner.replace("6.0 * 3600, \"eval_limit_s\": 3600},", "5.0 * 3600, \"eval_limit_s\": 3600},"),
                       r3(old_runner))


# --- probe tree from git ---------------------------------------------------------------------------------------------
def test_probe_manifest_is_recomputed_from_git():
    with PI.probe_tree(GIT, PROBE_COMMIT) as (root, manifest, sha):
        assert sha == PROBE_MANIFEST_SHA and len(manifest) == 42
        assert (root / PI.RUNNER_REL).read_text(encoding="utf-8").count(OLD_THIRD) == 1
    assert not root.exists()                                   # the export is removed afterwards
    with pytest.raises(PI.IdentityError, match="full 40-character"):
        with PI.probe_tree(GIT, "a33d34b"):
            pass


# --- current identity in a synthetic repository ---------------------------------------------------------------------
@pytest.fixture
def synthetic(tmp_path, old_runner):
    root = tmp_path / "repo"
    data = subprocess.run(["git", "archive", PROBE_COMMIT, "src", PI.RUNNER_REL, PI.VERIFY_REL], cwd=GIT,
                          capture_output=True, check=True).stdout
    root.mkdir()
    subprocess.run(["tar", "-x", "-C", str(root)], input=data, check=True)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "probe")
    probe_commit = git(root, "rev-parse", "HEAD")
    (root / PI.RUNNER_REL).write_text(r3(old_runner), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "r3")
    return root, probe_commit


def test_current_identity_accepts_the_registered_change(synthetic):
    root, probe_commit = synthetic
    with PI.probe_tree(root, probe_commit) as (probe_root, manifest, sha):
        assert sha == PROBE_MANIFEST_SHA
        cur = PI.current_identity(root, probe_root, manifest)
    assert cur["changed"] == [PI.RUNNER_REL] and cur["head"] == git(root, "rev-parse", "HEAD")
    assert cur["runner_diff"]["new"]["third_party"] == ["numpy", "mlx.core"]


def test_current_identity_refuses_other_files_and_uncommitted_code(synthetic):
    root, probe_commit = synthetic
    analysis = root / "src/ainerzero/v9/experiments/s6/analysis.py"
    analysis.write_text(analysis.read_text() + "\n# drift\n")
    with PI.probe_tree(root, probe_commit) as (probe_root, manifest, _):
        with pytest.raises(PI.IdentityError, match="other than the runner"):
            PI.current_identity(root, probe_root, manifest)
    git(root, "checkout", "-q", "--", str(analysis.relative_to(root)))
    runner = root / PI.RUNNER_REL
    runner.write_text(runner.read_text() + "\n# uncommitted\n")
    with PI.probe_tree(root, probe_commit) as (probe_root, manifest, _):
        with pytest.raises(PI.IdentityError, match="not committed"):
            PI.current_identity(root, probe_root, manifest)


# --- libraries and environment ------------------------------------------------------------------------------------
def test_final_versions_come_from_metadata_without_importing_mlx():
    code = ("import sys, importlib.util; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
            "spec = importlib.util.spec_from_file_location('pi', %r); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "import json; print(json.dumps([m.final_versions(), sorted(k for k in sys.modules if k.split('.')[0] == 'mlx')]))"
            % (str(REPO / "src"), str(HERE), str(HERE / "prereg_identity.py")))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    versions, mlx_modules = json.loads(out)
    assert set(versions) == {"numpy", "mlx.core"} and "unknown" not in versions.values()
    assert mlx_modules == []


def test_distributions_record_versions_and_records():
    d = PI.distributions()
    assert set(d) == {"mlx", "mlx-metal", "numpy"}
    assert all(len(v["record_sha256"]) == 64 and v["version"] for v in d.values())
    assert d["mlx"]["version"] == PI.final_versions()["mlx.core"]


def test_mlx_environment_variables_refuse():
    assert PI.mlx_environment({"PATH": "/bin"}) == {}
    with pytest.raises(PI.IdentityError, match="MLX_"):
        PI.mlx_environment({"MLX_METAL_DEBUG": "1"})
