#!/bin/bash
shasum -a 256 \
  src/ainerzero/v9/experiments/s1/spec.py \
  src/ainerzero/v9/experiments/s1/prereg.py \
  src/ainerzero/v9/experiments/s1/worker.py \
  src/ainerzero/v9/experiments/s1/commands.py \
  tests/v9/experiments/test_s1_r12_ordering.py \
  tests/v9/experiments/test_s1_r12_registration.py \
  tests/v9/experiments/test_s1_r13_registration.py \
  artifacts/v9/s1/phase1/r13/draft_preregistration.json \
  artifacts/v9/s1/phase1/r13/pre_registration.json \
  artifacts/v9/s1/phase1/r13/pre_registration.json.sha256 \
  artifacts/v9/s1/phase1/r13/dataset_ref.json \
  artifacts/v9/s1/phase1/control.sqlite3 \
  artifacts/v9/s1/phase1/eval_report.json > reports/V9-P9/r13/evidence/sha256sums.txt
