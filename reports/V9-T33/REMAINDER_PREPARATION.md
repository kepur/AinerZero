# T33 B-prime remainder preparation

Status at 2026-10-26T20:53:29Z: **prepared and parked on the UTC daily budget gate; no real model run in this preparation**.

## Authorized scope

- Tier-1 answer `#651` rejected any quota expansion.
- This attempt is limited to a centrally supervised, lock-held, true-forward remainder proof of at most 10 declared views.
- It is not the frozen 18-view statistical calibration and must not be reported as one.
- No training, downloads, paid calls, threshold changes, or lock bypass are authorized.

## Frozen and derived inputs

- Frozen manifest: `reports/V9-T6/r2-calib-fixtures/manifest.json`, SHA256 `d25912d36b424767a0e090bbb078a26918a5af97292789639e0e030e99513a84`.
- Frozen statistical protocol: `reports/V9-T6/r2-calib-fixtures/statistical_protocol.json`, SHA256 `b058842a0c43a9c056da8a120515f2c451124b6ea72257cf262fb98e0acee9cf`.
- Derived remainder protocol: `reports/V9-T33/remainder_protocol.json`, SHA256 `90ae94bc7e8f502eba4adfcc0d62de632c08836b73dfb52adddb762861ec4090`.
- The remainder selects 10 explicit frozen records: 5 fit and 5 holdout views spanning all 6 frozen worlds.

## Implementation binding

- `pipeline.py` SHA256 `67357ea4ec322e5995325cc5f5cf16530ee86b04781dfb0169411f4375f7b956` reads the controller-generated run spec and refuses unless its task/view count matches the remainder protocol.
- `real_da3_worker.py` SHA256 `8858acbe4818ec8afeef5f0eff415fed35050b3fced730193e22fa7f0979da2c` consumes only those selected rows and records the same protocol identity in evidence and tensor metadata.
- Extra MPS/CPU/FP16 consistency forwards were removed from this remainder worker so undeclared views cannot hide outside the controller count.
- A nonempty predictions directory is refused, preserving prior candidates/failures instead of overwriting them.

## Verification already completed

- Relay-supervised CPU suite: 25/25 passed; models loaded/run: 0.
- Relay-supervised mutation controls: 4/4 passed; real model runs: 0.
- Read-only controller inspect: AC power, weights verified, shared lock configured, views `54 + 10 = 64`, T33 cumulative wall reservation `80 + 60 <= 1200`, `can_run: true` at the T33 cumulative gates.
- One initial test invocation used `.venv-ainerzero`, which lacks Pillow, and produced 18 import errors. The same suite was then run in the task-owned `envs/teachers/.venv-t6` environment and passed 25/25. The failed invocation is preserved in the conversation/command evidence and is not counted as a pass.

## Remaining gate

The central RunStore row for UTC `2026-10-26` is `1200.0 / 1200.0` seconds. T33 is parked without acquiring the shared lock or starting a model. After UTC rollover, recheck every gate and allow exactly one 10-view, 60-second attempt if all remain green.
