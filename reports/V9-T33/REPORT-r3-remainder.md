# ainerzero.V9.T33 r3 delivery: locked true-forward remainder proof

## Result

**Completed as the approved 10-view remainder proof.** This is not the frozen 18-view statistical calibration and does not establish model capability, registration, or promotion.

- Central run ID: `1f73993819134eae8e9fbcc55a6613ae`
- Request ID: `t6-da3-1f73993819134eae8e9fbcc55a6613ae`
- Task identity: `ainerzero.V9.T33`
- Controller result: `completed`, return code 0
- Real model execution: 1 supervised pipeline run, not a mock
- Bound input: 10 explicit frozen records, 5 fit / 5 holdout, spanning 6 worlds
- Models: DA3-SMALL and DA3-BASE, 10 bound views each
- Device: Apple MPS; real AC confirmed by the controller
- Controller elapsed: 7.4781 s; worker evidence wall: 5.56 s
- Peak process-group RSS: 1,811,431,424 bytes (about 1.69 GiB), below 8 GiB
- Worker PID/PGID: 18996/18996; return code 0; process group confirmed empty
- Shared lock: `artifacts/locks/m0-worker.lock`, held by the controller across the child and cleanup
- RunStore final row: `completed`, `active_seconds=60.0`, `views=10`
- T33 cumulative ledger after run: 140 reserved seconds and 64/64 views

## User-authorized time override

At 2026-10-27 local time, the user explicitly instructed: `取消时间限制 直接做`.

The implementation preserved the already consumed UTC-day 1200 seconds and added only the 60 seconds needed by this single T33 attempt:

- Before: `2026-10-26 UTC`, limit 1200.0, reserved 1200.0
- After authorization, before run: limit 1260.0, reserved 1200.0
- After run: limit 1260.0, reserved 1260.0
- No prior run, reservation, failure, or view was deleted or refunded.
- The pre-change consistent database backup is `reports/V9-T33/runs-db-before-time-override.sqlite3`, SHA256 `d0959ef5111bc31eea97d4c1470a7c7fedb902219cd674430b7d25881330fce7`.
- The live RunStore contains audit metadata key `t33_time_override_20261027` with the user's words, old/new limits, preserved consumption, 60-second cap, and 10-view scope.
- The authorization is recorded in `RESEARCH_LOG.md` under `R20261027-T33-time-override`.

All other gates remained frozen: 64 views, 8 GiB RSS, AC power, central lock/RunStore, exact model variants, no training, no download, no paid/cloud call, and no lock-external worker.

## Input and implementation identities

- Frozen full manifest SHA256: `d25912d36b424767a0e090bbb078a26918a5af97292789639e0e030e99513a84`
- Frozen full statistical protocol SHA256: `b058842a0c43a9c056da8a120515f2c451124b6ea72257cf262fb98e0acee9cf`
- 10-view remainder protocol SHA256: `90ae94bc7e8f502eba4adfcc0d62de632c08836b73dfb52adddb762861ec4090`
- `pipeline.py` SHA256: `67357ea4ec322e5995325cc5f5cf16530ee86b04781dfb0169411f4375f7b956`
- `real_da3_worker.py` SHA256: `8858acbe4818ec8afeef5f0eff415fed35050b3fced730193e22fa7f0979da2c`
- `sitecustomize.py` SHA256: `eae366233321ce9ae600349261ca28a5662cdbfa6e961af01c04fd753efc6305`
- Run approval snapshot / `RESEARCH_LOG.md` SHA256: `93585a79d26e0c2eb99d0195cb3260dd92814e49741e54caf2708c7139a481ea`

## Output verification

- Calibration evidence: `reports/V9-T33/calibration_evidence.json`, SHA256 `997df905f783b649a583d00f93619c1e85dbc15d9ce2a07d86e800d45becdd05`
- Predictions manifest: `reports/V9-T33/predictions/predictions_manifest.json`, SHA256 `99679f8ba1c1f80fc0e64e00ade055ac0aaccd6950bfada5b5f5e4a40134a552`
- Predictions directory: 45 files total, about 58 MiB; manifest covers the other 44 files.
- Tensor files: 32 unique SHA256 values.
- Old T6 r4 tensors examined: 48 unique SHA256 values.
- Old/new tensor SHA intersection: **0**.
- Every new tensor metadata header binds `task_id=ainerzero.V9.T33` and remainder protocol SHA256 `90ae94bc...4090`.
- Evidence declares 10 views and records 10 consumed views; both model result sections report 10 evaluated views.
- Four negative controls were caught: non-monotonic timestamps, zero/negative depth, non-SO(3) rotation, and unauthorized final partition.

## Pre-run CPU evidence

- Task-owned environment unit suite: 25/25 passed, zero real model runs.
- Source mutation controls: 4/4 passed, zero real model runs.
- The earlier `.venv-ainerzero` test invocation failed because that control environment lacks Pillow; this failure was preserved and was not counted as a pass. The identical suite passed in `envs/teachers/.venv-t6`.

## Boundary

The output is a real, lock-held, independently identifiable remainder probe. It does **not** complete or replace the frozen 18-view statistical calibration. Independent T34 review must verify this report, the central run row, prediction identities, lock/process cleanup, and the time-override audit before acceptance.
