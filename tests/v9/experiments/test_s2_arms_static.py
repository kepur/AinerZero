"""Static AST and pure CPU tests for S2 MLX arms implementation (ainerzero.V9.P128).

Pure CPU only (DOES NOT IMPORT MLX).
Verifies:
1. arms_mlx.py imports only approved packages (mlx, numpy, stdlib, s2.spec, s2.param_count).
2. No hardcoded integer dimension arguments exist in nn.Linear or GRUCell constructor calls.
3. s2/__init__.py does not import arms_mlx (isolated subprocess verifies mlx not in sys.modules).
4. test_s2_arms_mlx_native.py is registered in NATIVE_MODULES and excluded from default pytest collection.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
import pytest


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return current.parents[3]


def test_approved_imports_only_in_arms_mlx() -> None:
    """Verify arms_mlx.py imports only approved libraries (mlx, numpy, stdlib, s2.spec, s2.param_count)."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    assert arms_mlx_path.is_file(), f"arms_mlx.py missing at {arms_mlx_path}"

    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    approved_modules = {
        "__future__",
        "math",
        "typing",
        "dataclasses",
        "pathlib",
        "numpy",
        "np",
        "mlx.core",
        "mlx.nn",
        "mlx.optimizers",
        "mlx.utils",
        "spec",
        "param_count",
        "ainerzero.v9.experiments.s2.spec",
        "ainerzero.v9.experiments.s2.param_count",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_name = alias.name
                assert (
                    mod_name in approved_modules or mod_name.split(".")[0] in {"mlx", "numpy"}
                ), f"Unapproved import: {mod_name}"
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            assert (
                mod_name in approved_modules
                or mod_name.endswith("spec")
                or mod_name.endswith("param_count")
                or mod_name.startswith("ainerzero.v9.experiments.s2")
                or mod_name in {"__future__", "math", "typing"}
            ), f"Unapproved from-import: from {mod_name} import ..."


def test_no_hardcoded_integer_widths_in_layer_constructors() -> None:
    """Verify that nn.Linear and GRUCell constructor arguments do not contain literal integer widths."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    # Track constructor calls: nn.Linear(...), Linear(...), GRUCell(...)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id

            if func_name in {"Linear", "GRUCell"}:
                # The first two positional arguments are input_dim and output_dim / hidden_dim
                for arg_idx, arg in enumerate(node.args[:2]):
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                        pytest.fail(
                            f"Hardcoded integer width found in {func_name} at line {node.lineno}: "
                            f"arg[{arg_idx}] = {arg.value}. Widths must be referenced from spec.ARM_DIMS."
                        )


def test_s2_package_init_does_not_import_arms_mlx() -> None:
    """Verify s2/__init__.py does not import arms_mlx, preserving pure CPU package behavior."""
    repo_root = _find_repo_root()
    s2_init_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "__init__.py"
    assert s2_init_path.is_file()
    init_content = s2_init_path.read_text(encoding="utf-8")
    assert "arms_mlx" not in init_content, "s2/__init__.py must not import arms_mlx"

    # Subprocess check with -I: importing s2 does not load mlx into sys.modules
    import site
    user_site = site.getusersitepackages()
    cmd = [
        sys.executable,
        "-I",
        "-c",
        (
            f"import sys; sys.path.insert(0, '{user_site}'); sys.path.insert(0, '{repo_root}/src'); "
            "import ainerzero.v9.experiments.s2; "
            "assert 'mlx' not in sys.modules, f'mlx leaked into sys.modules: {sys.modules.keys()}'; "
            "print('s2 package pure CPU import clean')"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"s2 package import leaked MLX:\n{res.stderr}\n{res.stdout}"


def test_native_module_registered_in_conftest_and_excluded_from_collection() -> None:
    """Verify test_s2_arms_mlx_native.py is registered in NATIVE_MODULES and ignored by default."""
    repo_root = _find_repo_root()
    conftest_path = repo_root / "tests" / "conftest.py"
    conftest_content = conftest_path.read_text(encoding="utf-8")

    assert (
        '"test_s2_arms_mlx_native.py": "module-level import mlx.core/mlx.nn (S2 arms)"'
        in conftest_content
    ), "test_s2_arms_mlx_native.py missing registration in NATIVE_MODULES"

    # Run pytest collection without --native-mlx; assert test_s2_arms_mlx_native.py is not collected
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(repo_root / "tests" / "v9" / "experiments" / "test_s2_arms_mlx_native.py"),
        "--collect-only",
        "-q",
    ]
    env = dict(PYTHONPATH=f"{repo_root}/src:{repo_root}")
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert "collected 0 items" in res.stdout or res.returncode == 5 or "no tests ran" in res.stdout.lower() or "collected 0 items" in res.stderr, (
        f"Native test should not be collected by default:\n{res.stdout}\n{res.stderr}"
    )


def test_activations_use_gelu_and_no_relu() -> None:
    """Verify SharedE1Encoder and arm hidden layers use GELU activations, and ReLU is never used."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    source = arms_mlx_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 1. No relu in AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.lower() == "relu":
            pytest.fail(f"Disallowed ReLU activation found at line {node.lineno}: {node.attr}")
        if isinstance(node, ast.Name) and node.id.lower() == "relu":
            pytest.fail(f"Disallowed ReLU activation found at line {node.lineno}: {node.id}")

    # 2. Assert gelu calls exist in the model classes
    gelu_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "gelu":
                gelu_calls.append(node.lineno)
            elif isinstance(node.func, ast.Name) and node.func.id == "gelu":
                gelu_calls.append(node.lineno)

    assert len(gelu_calls) >= 10, f"Expected at least 10 GELU calls in arms_mlx.py, found {len(gelu_calls)}"


def test_arm_a_loss_free_bits_floor() -> None:
    """Verify arm_a_loss_mlx enforces the ARM_A_FREE_BITS floor using mx.maximum."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "arm_a_loss_mlx":
            func_node = node
            break

    assert func_node is not None, "arm_a_loss_mlx function not found"

    has_max = False
    references_free_bits = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            func_id = ""
            if isinstance(node.func, ast.Attribute):
                func_id = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_id = node.func.id
            if func_id == "maximum":
                has_max = True
                # Check args for free_bits or ARM_A_FREE_BITS
                for arg in node.args:
                    if isinstance(arg, ast.Name) and "free_bits" in arg.id.lower():
                        references_free_bits = True
                    elif isinstance(arg, ast.Attribute) and "ARM_A_FREE_BITS" in arg.attr:
                        references_free_bits = True

    assert has_max, "arm_a_loss_mlx must call mx.maximum for free bits floor"
    assert references_free_bits, "arm_a_loss_mlx mx.maximum call must reference free_bits"


def test_arm_a_loss_overshooting_loop_and_horizon_bound() -> None:
    """Verify arm_a_loss_mlx implements latent overshooting bounded by H_TRAIN."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "arm_a_loss_mlx":
            func_node = node
            break

    assert func_node is not None, "arm_a_loss_mlx function not found"

    # Find the outer loop over T and inner loop over tau
    found_overshoot_loop = False
    references_h_train = False
    decodes_in_overshoot = False

    for node in ast.walk(func_node):
        if isinstance(node, ast.For):
            # Check if this loop is the overshooting loop (target name tau or similar)
            target_name = getattr(node.target, "id", "")
            if "tau" in target_name:
                found_overshoot_loop = True
                # Inspect body of overshooting loop
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        fn_attr = getattr(child.func, "attr", "")
                        if fn_attr == "decode":
                            decodes_in_overshoot = True

        # Check references to H_TRAIN
        if isinstance(node, ast.Attribute) and node.attr == "H_TRAIN":
            references_h_train = True
        elif isinstance(node, ast.Name) and "h_train" in node.id.lower():
            references_h_train = True

    assert found_overshoot_loop, "arm_a_loss_mlx missing overshooting loop (tau)"
    assert references_h_train, "arm_a_loss_mlx must reference H_TRAIN bound"
    assert decodes_in_overshoot, "overshooting loop must call arm_a.decode"


def test_idm_targets_explicit_stop_gradient() -> None:
    """Verify IDM loss functions explicitly call mx.stop_gradient on target actions / macro actions."""
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    stop_gradient_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = ""
            if isinstance(node.func, ast.Attribute):
                fn_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                fn_name = node.func.id
            if fn_name == "stop_gradient":
                # record argument name if Name
                arg_names = []
                for a in node.args:
                    if isinstance(a, ast.Name):
                        arg_names.append(a.id)
                stop_gradient_calls.append((node.lineno, arg_names))

    assert len(stop_gradient_calls) >= 2, f"Expected stop_gradient calls on IDM targets, found {stop_gradient_calls}"
    # Verify target actions or target_7d is stopped
    stopped_vars = [var for _, args in stop_gradient_calls for var in args]
    assert any("target" in v for v in stopped_vars), f"Target variable not passed to stop_gradient: {stopped_vars}"


def test_arm_a_loss_return_includes_overshooting_and_mean_from_losses() -> None:
    """Verify arm_a_loss_mlx return statement sums reconstruction, KL (free bits), and overshooting terms.

    Also asserts that mean_overshoot is computed by averaging overshoot_losses.
    """
    repo_root = _find_repo_root()
    arms_mlx_path = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "arms_mlx.py"
    tree = ast.parse(arms_mlx_path.read_text(encoding="utf-8"))

    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "arm_a_loss_mlx":
            func_node = node
            break

    assert func_node is not None, "arm_a_loss_mlx function not found"

    # 1. Parse Return expression and assert it is an addition expression
    ret_nodes = [n for n in ast.walk(func_node) if isinstance(n, ast.Return)]
    assert len(ret_nodes) == 1, f"Expected exactly 1 return node in arm_a_loss_mlx, found {len(ret_nodes)}"
    ret_val = ret_nodes[0].value
    assert isinstance(ret_val, ast.BinOp) and isinstance(ret_val.op, ast.Add), (
        f"Return value must be an addition BinOp (+), found: {type(ret_val).__name__}"
    )

    def _collect_add_terms(node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _collect_add_terms(node.left) + _collect_add_terms(node.right)
        return [node]

    terms = _collect_add_terms(ret_val)
    term_names = {t.id for t in terms if isinstance(t, ast.Name)}

    # Assert all three terms are present in the addition
    assert "mean_recon" in term_names, (
        f"Reconstruction term 'mean_recon' missing from arm_a_loss_mlx return addition: {term_names}"
    )
    assert "kl_penalized" in term_names, (
        f"Free bits KL term 'kl_penalized' missing from arm_a_loss_mlx return addition: {term_names}"
    )
    assert "mean_overshoot" in term_names, (
        f"Overshooting term 'mean_overshoot' missing from arm_a_loss_mlx return addition: {term_names}"
    )

    # 2. Assert mean_overshoot is derived by averaging overshoot_losses
    mean_overshoot_from_overshoot_losses = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            target_ids = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if "mean_overshoot" in target_ids:
                has_mean_call = False
                has_overshoot_losses = False
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Call):
                        fn_name = getattr(sub.func, "attr", "") or getattr(sub.func, "id", "")
                        if fn_name == "mean":
                            has_mean_call = True
                    if isinstance(sub, ast.Name) and sub.id == "overshoot_losses":
                        has_overshoot_losses = True
                if has_mean_call and has_overshoot_losses:
                    mean_overshoot_from_overshoot_losses = True

    assert mean_overshoot_from_overshoot_losses, (
        "mean_overshoot must be computed by averaging overshoot_losses (via mx.mean or equivalent)"
    )

