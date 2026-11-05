"""G3 deliberate-break controls: every mutation must make the property tests red.

Each mutant is a real subprocess: the canonical module is copied to a temporary
directory, exactly one registered textual mutation is applied, the module's
relative imports are rewired to absolute imports (harness shim, applied to the
control too), and pytest runs against the *same* test file through
``AINERZERO_CANONICAL_OVERRIDE``.  A control mutant with only the import shim
must pass; every functional mutation must fail with a real non-zero exit code.

No persistent source file is modified: mutants live in a temporary directory
that is removed afterwards.  Exit code: 0 only if the control passes and all
three mutations are caught.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src/ainerzero/v9/geometry/canonical.py"
TEST_FILE = ROOT / "tests/v9/geometry/test_canonical.py"
RESULT_FILE = pathlib.Path(__file__).resolve().parent / "mutation-results.json"

IMPORT_SHIM = (
    ("from .belief import TangentGaussian",
     "from ainerzero.v9.geometry.belief import TangentGaussian"),
    ("from .gravity import GravityFrame",
     "from ainerzero.v9.geometry.gravity import GravityFrame"),
    ("from .lie import SE2, SE3, boxplus, vector",
     "from ainerzero.v9.geometry.lie import SE2, SE3, boxplus, vector"),
)

CONTROL = ("control-import-shim-only", ())

MUTATIONS = (
    (
        "inverse-direction-g-instead-of-g-inverse",
        (
            "    return SE3.inverse(canonical_lift(belief))",
            "    return canonical_lift(belief)",
        ),
    ),
    (
        "full-se3-missing-gravity-alignment",
        (
            "    def lift(self):\n"
            '        """Return ``L = frame.lift(g(mu_hat), 0) in SE(3)`` (zero vertical shift)."""\n'
            "        return self.frame.lift(self.planar(), 0.0)",
            "    def lift(self):\n"
            '        """MUTATED: full SE(3) estimate instead of the gravity-aligned part."""\n'
            "        if self.belief.group is SE2:\n"
            "            return self.frame.lift(self.planar(), 0.0)\n"
            "        return np.array(self.belief.mean, copy=True)",
        ),
    ),
    (
        "grid-rotation-direction-reversed",
        (
            "    return SE2.compose(SE2.inverse(source_frame), target_frame)",
            "    return SE2.compose(source_frame, target_frame)",
        ),
    ),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def apply_import_shim(text, name):
    for old, new in IMPORT_SHIM:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{name}: import shim anchor found {count} times: {old!r}")
        text = text.replace(old, new)
    return text


def apply_mutation(text, name, replacement):
    if not replacement:
        return text
    old, new = replacement
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{name}: mutation anchor found {count} times: {old!r}")
    return text.replace(old, new)


def run_pytest(mutant_path, log_path):
    env = dict(os.environ)
    env["AINERZERO_CANONICAL_OVERRIDE"] = str(mutant_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "pytest", str(TEST_FILE), "-q", "-p", "no:cacheprovider"]
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.write("AINERZERO_CANONICAL_OVERRIDE=" + str(mutant_path) + "\n\n")
        log.flush()
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    output = log_path.read_text(encoding="utf-8")
    failed = [line.split("::", 1)[1].split(" ")[0]
              for line in output.splitlines() if line.startswith("FAILED ")]
    return result.returncode, failed, output


def main():
    original = SOURCE.read_text(encoding="utf-8")
    source_sha = sha256(original.encode("utf-8"))
    test_sha = sha256(TEST_FILE.read_bytes())
    runs = []
    all_caught = True
    with tempfile.TemporaryDirectory(prefix="ainerzero-g3-mutants-") as tmp:
        tmpdir = pathlib.Path(tmp)
        for name, replacement in (CONTROL, *MUTATIONS):
            mutant_text = apply_import_shim(original, name)
            mutant_text = apply_mutation(mutant_text, name, replacement)
            mutant_path = tmpdir / f"canonical_mutant_{name.replace('-', '_')}.py"
            mutant_path.write_text(mutant_text, encoding="utf-8")
            log_path = pathlib.Path(__file__).resolve().parent / f"mutation-{name}.log"
            returncode, failed, output = run_pytest(mutant_path, log_path)
            if replacement:
                caught = returncode != 0
                all_caught = all_caught and caught
                outcome = "caught-red" if caught else "SURVIVED"
            else:
                caught = None
                outcome = "pass-green" if returncode == 0 else "CONTROL-FAILED"
                all_caught = all_caught and returncode == 0
            entry = {
                "name": name,
                "kind": "control" if not replacement else "mutation",
                "outcome": outcome,
                "returncode": returncode,
                "caught": caught,
                "failed_tests": failed,
                "log": log_path.name,
                "mutant_sha256": sha256(mutant_text.encode("utf-8")),
            }
            runs.append(entry)
            print(f"{name}: rc={returncode} {outcome} failed={len(failed)} -> {log_path.name}")
            if output.rstrip().splitlines():
                print("  " + output.rstrip().splitlines()[-1])
            sys.stdout.flush()
    result = {
        "task": "ainerzero.V9.G3",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": source_sha,
        "test": str(TEST_FILE.relative_to(ROOT)),
        "test_sha256": test_sha,
        "import_shim": list(IMPORT_SHIM),
        "all_caught": all_caught,
        "runs": runs,
    }
    RESULT_FILE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nall_caught={all_caught} -> {RESULT_FILE.relative_to(ROOT)}")
    if not all_caught:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
