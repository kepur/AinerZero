# P43 limited acceptance and evidence repair

2026-10-26, codex. The user designated Codex to take over Claude's coordination. Claude nevertheless accepted P43 at 09:35:04. Preserve that event and all original files. Acceptance is limited to supported facts; it is not authority for r14.

## Findings from direct source inspection

- `audit_item2_final_partition_bound` sets `all_job_argvs_train_only = True` but never checks it; `training_argv_mode` is a literal. An absent log is silently skipped. `dataset_manifest_partitions=[]` is emitted, so the report's claim that this field registered train/development is unsupported. Present files, source guards, and declared paths bound the intended workflow but do not prove historical zero reads without access auditing. Final historical zero-read remains unverified.
- `audit_item3_reserved_active_seconds` correctly uses `runs.active_seconds`, consistent with lifecycle.py RunRecord mapping; however it deletes its unique clone and does not persist clone path or raw rows. Do not execute it again or overwrite its metrics. A fresh read-only clone may recover reproducible evidence, without deleting anything.
- Job status is projected into selected fields; raw command results are not preserved. The report's five executed jobs versus one canceled-before-launch distinction is plausible and must be backed by complete raw status snapshots.
- Four params.npz files have adjacent historical SHA files; the failed run has no params.npz. Checkpoint hashes are newly computed inventory, not comparisons against independent historical hashes. The claim that all five params and all checkpoints match recorded SHA is false.
- The bounded R6 approval check improves on P42. Exact original section and source references must accompany any final result; current approval does not reopen the expired experiment window.

## P44 report-only repair

Scope only `reports/V9-P44/`. Do not modify P42/P43, product source, root research conclusions, production DB, final dataset contents, or P36. Read prior scripts but do not execute/import their main workflows. No train/eval/verify/MLX/Blender, installation, downloads, paid services, deletes, commits or push.

1. Save every actual command/return code/stdout/stderr. Obtain six raw `relay --json job-status` responses as the reviewer's own identity. Preserve exec binding, supervision and log metadata, including canceled-before-launch with no exec rather than inventing confirmed_empty.
2. If DB rows are needed: hash production DB and any WAL/SHM; create a unique mkdtemp, copy DB and any extant sidecars, open only the copy with SQLite URI mode=ro. Save source/clone paths, before/after SHA and relevant raw rows. Leave the clone in place. Avoid opening RunStore against production. If snapshot changes concurrently, record inconsistency rather than retry silently.
3. Distinguish observed filesystem inventory, intended code/argv paths, and unavailable historical access evidence. Mark historical final zero-read UNVERIFIED unless actual independent access evidence exists. Do not read final data to prove absence of reads.
4. Preserve reproducible real reservation mapping and conservative per-run arithmetic; no config fallback or reset of budget.
5. Separate four params with expected SHA from failed run lacking params and checkpoint current hashes lacking historical expected SHA. Only claim comparisons actually made. Check source/data hashes as needed without loading weights.
6. Deliver a concise item matrix, raw evidence index with SHA and references, explicit unverified items, and zero new run authority. Ordinary input checks are not source mutations; no mutation tests are required for this report-only task.
