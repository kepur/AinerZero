#!/bin/sh
# Wait for the main surrogate run to finish, then run the extrapolation worlds (separate lock hold).
cd "$(dirname "$0")/../../../../.."
S=reports/V9-S4-P2-DESIGN/r0-review/evidence/surrogates
until grep -q "^exit=" $S/run-main.log; do sleep 5; done
(time sh $S/run_surrogates.sh extrap) > $S/run-extrap.log 2>&1; echo exit=$? >> $S/run-extrap.log
