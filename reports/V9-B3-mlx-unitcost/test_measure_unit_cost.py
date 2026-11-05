"""Only CPU tests. A fresh process audits the full dryrun and forbids MLX import."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("p28_measure", HERE / "measure_unit_cost.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@pytest.mark.parametrize("name", ["final/packets.jsonl", "FINAL.json", "prefix-final-cache/data.json"])
def test_final_path_refused_before_read(tmp_path, name):
    with pytest.raises(m.BoundaryViolation, match="sealed path"):
        m.safe_path(tmp_path / name)


def test_final_symlink_target_refused(tmp_path):
    target = tmp_path / "final-secret"
    target.mkdir()
    alias = tmp_path / "innocent-name"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(m.BoundaryViolation, match="sealed path"):
        m.safe_path(alias / "packets.jsonl")


def test_manifest_is_first_twelve_development_scenes_and_batch_one():
    sequences, samples = m.load_inputs()
    assert samples["N"] == 12 and samples["partition"] == "development"
    assert [row["scene_id"] for row in samples["episodes"]] == [f"s1-development-e3-{i:05d}" for i in range(12)]
    assert samples["total_frames"] == 60 and samples["total_transitions"] == 48
    assert len(sequences) == 12 and all(sequence["obs"].ndim == 2 for sequence in sequences)
    assert {row["family"] for row in samples["episodes"]} == {"e3_identity"}


@pytest.mark.parametrize("name", sorted(m.FORBIDDEN))
def test_training_or_checkpoint_backend_method_cannot_be_reached(name):
    class Poison:
        def __getattribute__(self, attr):
            raise AssertionError("forbidden backend was accessed")
    with pytest.raises(m.BoundaryViolation, match="forbidden"):
        getattr(m.ReadOnlyBackend(Poison()), name)


def test_script_has_no_optimizer_or_backward_construction_calls():
    tree = ast.parse((HERE / "measure_unit_cost.py").read_text())
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    forbidden = {"Adam", "AdamW", "SGD", "Optimizer", "value_and_grad", "backward", "make_optimizer",
                 "optimizer_update", "save_params", "save_checkpoint", "RunStore", "load_d_candidate",
                 "d_candidate_fixed_batch", "d_candidate_forward_loss"}
    assert not [name for name in calls if name.rsplit(".", 1)[-1] in forbidden]


def test_unit_timer_waits_for_eval_and_uses_completed_memory(tmp_path):
    sequences, _ = m.load_inputs()
    now = [0.0]
    model = m.FakeArm("arm2")
    original = model.forward_terms
    def forward(*args, **kwargs):
        now[0] += 2.0
        return original(*args, **kwargs)
    model.forward_terms = forward
    class Backend(m.FakeBackend):
        def eval(self, *values):
            now[0] += 5.0
        def encode(self, model, row):
            now[0] += 3.0
            return super().encode(model, row)
        def probe_graph(self, model, memory, pose=None):
            assert memory["steps"] == 4
            now[0] += 4.0
            return super().probe_graph(model, memory, pose)
    result = m.measure_arm("arm2", model, m.ReadOnlyBackend(Backend()), sequences, tmp_path, clock=lambda: now[0])
    assert result["status"] == "completed"
    assert model.calls == 3 + 48 + 48  # warmup + primary + 12 product-sequence checks
    for name, samples, seconds in (("forward", 48, 7), ("encode", 60, 3), ("probe_graph", 36, 4)):
        item = result[name]
        assert len(item["warmup"]) == 3 and item["samples"] == samples
        assert item["first_call_seconds"] == seconds
        assert item["median_seconds"] == item["p90_seconds"] == item["max_seconds"] == seconds
    saved = json.loads((tmp_path / "arm2.json").read_text())
    assert saved == result
    cross = result["step_sequence_per_transition"]
    assert cross["samples"] == 12 and sum(row["transitions"] for row in cross["rows"]) == 48
    assert all(row["seconds_per_transition"] == row["seconds"] / 4 for row in cross["rows"])


def test_returned_pose_predictions_and_memory_sync_are_inside_timer(tmp_path):
    sequences, _ = m.load_inputs()
    now = [0.0]
    memory_array_type = type("array", (), {"__module__": "mlx.core"})
    memory_leaf = memory_array_type()
    memory_leaf.ready = False
    class Deferred:
        def __init__(self, value, seconds):
            self.value, self.seconds = value, seconds
        def __array__(self, dtype=None, copy=None):
            now[0] += self.seconds
            return np.asarray(self.value, dtype=dtype)
        def copy(self):
            return self.value.copy()
    model = m.FakeArm("arm2")
    original = model.forward_terms
    def forward(*args, **kwargs):
        now[0] += 2
        terms = original(*args, **kwargs)
        memory_leaf.ready = False
        memory = {**terms[4], "deferred_leaf": memory_leaf}
        return terms[0], terms[1], Deferred(terms[2], 1), Deferred(np.zeros((1, 2)), 2), memory
    model.forward_terms = forward
    class Backend(m.FakeBackend):
        def eval(self, *values):
            if any(isinstance(v, memory_array_type) for v in values):
                now[0] += 4
                memory_leaf.ready = True
            else:
                now[0] += 5
        def encode(self, model, row):
            now[0] += 3
            return super().encode(model, row)
        def probe_graph(self, model, memory, pose=None):
            assert memory["deferred_leaf"] is memory_leaf and memory_leaf.ready
            now[0] += 4
            return super().probe_graph(model, memory, pose)
    result = m.measure_arm("arm2", model, m.ReadOnlyBackend(Backend()), sequences, tmp_path, clock=lambda: now[0])
    assert result["forward"]["median_seconds"] == 2 + 5 + 1 + 2 + 4
    assert result["forward"]["first_call_seconds"] == 14
    assert all(row["seconds"] == 14 for row in result["forward"]["measured"])
    assert result["step_sequence_per_transition"]["samples"] == 12


def test_failure_preserves_completed_forward_json(tmp_path):
    sequences, _ = m.load_inputs()
    class Backend(m.FakeBackend):
        def encode(self, *args):
            raise RuntimeError("test encode refusal")
    with pytest.raises(RuntimeError, match="encode refusal"):
        m.measure_arm("arm2", m.FakeArm("arm2"), m.ReadOnlyBackend(Backend()), sequences, tmp_path)
    saved = json.loads((tmp_path / "arm2.json").read_text())
    assert saved["status"] == "partial" and saved["forward"]["samples"] == 48
    assert "encode" not in saved


def test_extrapolation_is_arithmetic_and_never_double_counts_sequences():
    results = {arm: {"status": "completed", **{name: {"median_seconds": median, "p90_seconds": median * 2}
               for name, median in (("forward", 1), ("encode", 2), ("probe_graph", 3))}} for arm in m.ARMS}
    result = m.extrapolate(results)
    expected = 1492 + 3500 * 2 + 800 * 3
    assert all(row["median_seconds"] == expected for row in result["per_arm_seed"].values())
    assert result["nine_eval_invocations_arithmetic"]["median_seconds"] == expected * 9
    assert "cannot certify" in result["budget_verdict"]


def test_resource_guard_keeps_boot_zero_baseline_and_refuses_swap(monkeypatch):
    import psutil
    from types import SimpleNamespace
    from ainerzero.v9.experiments.s1 import resource_gate
    monkeypatch.setattr(psutil, "boot_time", lambda: m.BOOT_EPOCH)
    captured = []
    def collect(**kwargs):
        captured.append(kwargs["swap_baseline_bytes"])
        return resource_gate.ResourceSnapshot(process_rss_bytes=0.1 * 2**30,
                system_available_bytes=20 * 2**30, swap_used_bytes=1.01 * 2**30,
                swap_baseline_bytes=kwargs["swap_baseline_bytes"], disk_free_bytes=100 * 2**30)
    monkeypatch.setattr(resource_gate, "collect", collect)
    with pytest.raises(m.BoundaryViolation, match="swap_growth_limit"):
        m.assert_resources()
    assert captured == [0.0]


def test_changed_boot_refuses_even_with_zero_swap(monkeypatch):
    import psutil
    from ainerzero.v9.experiments.s1 import resource_gate
    monkeypatch.setattr(psutil, "boot_time", lambda: m.BOOT_EPOCH + 1)
    monkeypatch.setattr(resource_gate, "collect", lambda **kwargs: resource_gate.ResourceSnapshot(
        system_available_bytes=20 * 2**30, disk_free_bytes=100 * 2**30))
    with pytest.raises(m.BoundaryViolation, match="boot differs"):
        m.assert_resources()


def test_real_mode_requires_freeze_before_attempt_marker(tmp_path):
    with pytest.raises(m.BoundaryViolation, match="freeze reply"):
        path = tmp_path / "missing-freeze.json"
        path.write_text('{}')
        m.validate_freeze(path, {})
    assert not m.ONCE.exists()


@pytest.mark.parametrize("case", ["existing", "new", "symlink", "outside_write", "sqlite", "other_mkdir"])
def test_real_worker_lock_io_boundary_in_cpu_subprocess(tmp_path, case):
    code = r'''
import importlib.abc, importlib.util, json, sys
from pathlib import Path
attempts=[]
class NoMlx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            attempts.append(fullname)
            raise AssertionError('CPU lock fixture attempted MLX import')
sys.meta_path.insert(0, NoMlx())
spec=importlib.util.spec_from_file_location('p28_lock',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from ainerzero.cli import worker_lock
base=Path(sys.argv[2]);case=sys.argv[3]
host=base/'host';(host/'artifacts').mkdir(parents=True)
parent=host/'artifacts/locks'
if case == 'symlink':
    target=host/'real-parent';target.mkdir();parent.symlink_to(target,target_is_directory=True)
elif case != 'new':
    parent.mkdir()
lock=parent/'m0-worker.lock'
if case != 'new':lock.write_text('fixture only')
output=base/'output';output.mkdir()
module.ROOT=host
module.install_io_guard(output)
state='accepted'
try:
    if case in ('existing','new','symlink'):
        with worker_lock(lock):
            (output/'lock-proof.txt').write_text('real flock acquired and released')
    elif case == 'outside_write':
        (host/'illicit.txt').write_text('must never be written')
    elif case == 'sqlite':
        import sqlite3
        sqlite3.connect(output/'forbidden.db')
    elif case == 'other_mkdir':
        (output/'unregistered-child').mkdir()
except module.BoundaryViolation:
    state='refused'
assert not (host/'illicit.txt').exists()
assert not (output/'forbidden.db').exists()
assert not (output/'unregistered-child').exists()
if case == 'new':assert not parent.exists()
print(json.dumps({'case':case,'state':state,'mlx_attempts':attempts,
    'mlx_loaded':any(x=='mlx' or x.startswith('mlx.') for x in sys.modules)}))
'''
    result = subprocess.run([sys.executable, "-c", code, str(HERE / "measure_unit_cost.py"), str(tmp_path), case],
                            capture_output=True, text=True, timeout=30)
    (tmp_path / "lock-boundary.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout)
    assert proof["state"] == ("accepted" if case == "existing" else "refused")
    assert proof["mlx_attempts"] == [] and proof["mlx_loaded"] is False


def test_entire_cpu_dryrun_imports_no_mlx_and_creates_no_optimizer(tmp_path):
    output = tmp_path / "cpu-dryrun"
    assert not output.exists(), "preserve earlier outputs; use a new test invocation directory"
    code = r'''
import importlib.abc, importlib.util, json, sys
from pathlib import Path
attempts=[]
class NoMlx(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mlx' or fullname.startswith('mlx.'):
            attempts.append(fullname)
            raise AssertionError('CPU dryrun attempted MLX import')
sys.meta_path.insert(0, NoMlx())
spec=importlib.util.spec_from_file_location('p28_dry', sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=module.FakeBackend
class PoisonOptimizerBackend(original):
    def make_optimizer(self, *args, **kwargs):
        raise AssertionError('optimizer constructor reached')
    def value_and_grad(self, *args, **kwargs):
        raise AssertionError('backward reached')
module.FakeBackend=PoisonOptimizerBackend
rc=module.main(['--mode','dry','--output',sys.argv[2]])
print('CPU_PROOF='+json.dumps({'rc':rc,'mlx_attempts':attempts,'mlx_loaded':any(x=='mlx' or x.startswith('mlx.') for x in sys.modules)}))
'''
    result = subprocess.run([sys.executable, "-c", code, str(HERE / "measure_unit_cost.py"), str(output)],
                            capture_output=True, text=True, timeout=120)
    (tmp_path / "cpu-dryrun-process.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"mlx_attempts": []' in result.stdout and '"mlx_loaded": false' in result.stdout
    saved = json.loads((output / "run.json").read_text())
    assert saved["status"] == "cpu_dryrun_completed_not_model_timing" and saved["real_model_runs"] == 0
    assert saved["mlx_imported"] is False and saved["source_identity_unchanged"] is True
    assert saved["arms"]["arm1"]["status"] == "not_applicable"
    for arm in m.ARMS:
        assert (output / (arm + ".json")).is_file()
        assert saved["arms"][arm]["status"] == "completed"
    assert not m.ONCE.exists()
