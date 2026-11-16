#!/bin/zsh
# P264 author mutations of the freeze entry (make_prereg, prereg_evidence, prereg_identity). Pure CPU.
# Isolated copy: git archive HEAD + the working-tree files of this change; PYTHONPATH -> copy src.
set -u
ROOT=/Users/mac/AinerWorkFlow/AinerZero
PY=$ROOT/.venv/bin/python
WORK=$(mktemp -d "${TMPDIR:-/tmp}/s6-prereg-mut.XXXXXX")
cd $ROOT
git archive HEAD src tests pyproject.toml reports/V9-S6-PHASE1 reports/V9-S6-DESIGN | tar -x -C $WORK
for f in reports/V9-S6-PHASE1/make_prereg.py reports/V9-S6-PHASE1/prereg_evidence.py reports/V9-S6-PHASE1/prereg_identity.py \
         reports/V9-S6-PHASE1/run_s6p1.py reports/V9-S6-DESIGN/DESIGN-r3.md \
         tests/v9/experiments/test_s6_prereg.py tests/v9/experiments/test_s6_prereg_identity.py; do
  mkdir -p $WORK/$(dirname $f); cp $f $WORK/$f
done
cd $WORK
export PYTHONPATH=$WORK/src PYTHONDONTWRITEBYTECODE=1
T="tests/v9/experiments/test_s6_prereg.py tests/v9/experiments/test_s6_prereg_identity.py"
H=reports/V9-S6-PHASE1
for f in make_prereg prereg_evidence prereg_identity; do cp $H/$f.py $H/$f.py.orig; done
restore() { for f in make_prereg prereg_evidence prereg_identity; do cp $H/$f.py.orig $H/$f.py; done; }
# The copy has no git history: the tests take the probe commit from the real repository's history.
export S6_PREREG_GIT_REPO=$ROOT
run() { $PY -m pytest -q -x -p no:cacheprovider $=T 2>&1 | tail -1; }
echo "== baseline: $(run)"
mutate() {  # file name old new
  restore
  $PY - "$1" "$3" "$4" <<'PYEOF'
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
assert s.count(old) >= 1, f"anchor not found in {p}: {old[:60]!r}"
open(p, "w").write(s.replace(old, new))
PYEOF
  echo "== $2: $(run)"
}
mutate $H/make_prereg.py "P1 builder skips the report anchor" '    PE.require(hashlib.sha256(data).hexdigest() == PROBE_REPORT_SHA256, "probe report SHA differs from the recorded anchor")' '    pass'
# P2: both anchor checks gone
restore
$PY - <<'PYEOF'
p="reports/V9-S6-PHASE1/make_prereg.py"; s=open(p).read()
s=s.replace('    PE.require(hashlib.sha256(data).hexdigest() == PROBE_REPORT_SHA256, "probe report SHA differs from the recorded anchor")','    pass'); open(p,"w").write(s)
p="reports/V9-S6-PHASE1/prereg_evidence.py"; s=open(p).read()
s=s.replace("    require(hashlib.sha256(closure.read(probe)).hexdigest() == expected_sha, 'probe report SHA differs from the recorded anchor')","    closure.read(probe)"); open(p,"w").write(s)
PYEOF
echo "== P2 no anchor anywhere: $(run)"
mutate $H/prereg_evidence.py "P3 source_sets attribute whitelist dropped" "                require(isinstance(n.value, ast.Name) and n.value.id == 'C' and n.attr in c_attributes," "                require(True or isinstance(n.value, ast.Name) and n.value.id == 'C' and n.attr in c_attributes,"
mutate $H/prereg_evidence.py "P4 budget from the probe record's (old) caps" "def estimate_budget(pr, final):" "def estimate_budget(pr, final):
    final = pr['sets']['final']"
mutate $H/prereg_evidence.py "P5 probe sets read from the current code" "    sets = source_sets(probe_root, final_caps=OLD_CAPS)" "    sets = source_sets(repo, final_caps=NEW_CAPS)"
mutate $H/prereg_evidence.py "P6 ledger commit not checked" "        if row['git_head'] is not None:" "        if False:"
mutate $H/make_prereg.py "P7 MLX_* environment not checked" "    environment = PI.mlx_environment()" "    environment = {}"
mutate $H/make_prereg.py "P8 versions with the old semantics" "    versions = PI.final_versions()" "    versions = PE.cpu_versions(REPO)"
mutate $H/make_prereg.py "P9 identity module not frozen" ", Path(PE.__file__).resolve(), Path(PI.__file__).resolve()]" ", Path(PE.__file__).resolve()]"
mutate $H/make_prereg.py "P10 any design accepted" ' and design.name == "DESIGN-r3.md"' ''
mutate $H/make_prereg.py "P11 MLX install date not checked" '    PE.require(mtime is not None and mtime < start,' '    PE.require(True or mtime is not None and mtime < start,'
mutate $H/prereg_identity.py "P12 current code may be uncommitted" '    require(not _git(repo, "status", "--porcelain", "--", *current), "the code to freeze is not committed")' '    pass'
mutate $H/prereg_identity.py "P13 other files may differ" '    require(changed == [RUNNER_REL], f"files other than the runner differ from the probe' '    require(True or changed == [RUNNER_REL], f"files other than the runner differ from the probe'
mutate $H/prereg_identity.py "P14 new value may be an expression" '        values[name] = _number(final.values[idx[0]], fold=old)' '        values[name] = _number(final.values[idx[0]], fold=True)'
restore
echo "== restored: $(run)"
