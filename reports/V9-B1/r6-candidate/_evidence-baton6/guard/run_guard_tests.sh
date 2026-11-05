#!/bin/bash
# B7 第6棒：输出路径守卫负例（全部在 /tmp staging 上；真实候选不作写入目标）
set -u
PY=/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python
STAGE=/tmp/b7r6-stage/repo
CAND=$STAGE/reports/V9-B1/r6-candidate
CK=$CAND/check_skill_proposal.py
EV=/tmp/b7r6-evidence/guard
run() { # label outputdir [env assignments...]
  local label=$1; shift
  local out=$1; shift
  ( cd "$STAGE" && "$PY" -B "$CK" --suite --output-dir "$out" >"$EV/$label.out" 2>"$EV/$label.err" )
  echo "$?" > "$EV/$label.rc"
}
mkdir -p /tmp/b7r6-target-fresh /tmp/b7r6-target-evidence
ln -sfn "$CAND" /tmp/b7r6-symlink-alias
cp -p /tmp/b7r6-out1/check_result.json /tmp/b7r6-target-evidence/check_result.json
cp -p /tmp/b7r6-out1/SHA256SUMS.txt /tmp/b7r6-target-evidence/SHA256SUMS.txt
sha256sum /tmp/b7r6-target-evidence/check_result.json /tmp/b7r6-target-evidence/SHA256SUMS.txt > "$EV/evidence_before.sha256"
run G1_same_input_dir "$CAND"
run G2_ancestor_of_input "$STAGE/reports/V9-B1"
run G3_descendant_of_input "$CAND/fixtures/valid"
run G4_symlink_alias /tmp/b7r6-symlink-alias
run G5_output_is_file /tmp/b7r6-out1/check_result.json
run G6_output_has_evidence /tmp/b7r6-target-evidence
run G8_env_source_ancestor "$CAND/fixtures"
run G9_repo_root_ancestor "$STAGE"
sha256sum /tmp/b7r6-target-evidence/check_result.json /tmp/b7r6-target-evidence/SHA256SUMS.txt > "$EV/evidence_after.sha256"
# G8 with AWZ_OBSERVATION_PATH 覆盖到夹具文件（来源路径也须纳入输入保护集）
( cd "$STAGE" && AWZ_OBSERVATION_PATH="$CAND/fixtures/valid/01_valid_minimal_handle_target.json" \
  "$PY" -B "$CK" --suite --output-dir "$CAND/fixtures" >"$EV/G8b_env_source.out" 2>"$EV/G8b_env_source.err" ); echo $? > "$EV/G8b_env_source.rc"
echo '--- rc table ---'
for f in "$EV"/*.rc; do echo "$(basename "$f" .rc) rc=$(cat "$f")"; done
diff "$EV/evidence_before.sha256" "$EV/evidence_after.sha256" && echo 'EVIDENCE_UNCHANGED=yes'
grep -l Traceback "$EV"/*.err && echo 'TRACEBACK_FOUND' || echo 'NO_TRACEBACK_IN_ANY_STDERR'
