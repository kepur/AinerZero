# B8 复核运行记录（原命令 / rc / traceback / 耗时）

由 results/logs/*.jsonl 自动汇总；完整 stdout/stderr 在 JSONL 里。

## A-identity-20261017T090722.jsonl

```
```

## A-identity-20261017T090727.jsonl

```
```

## A-identity-20261017T090730.jsonl

```
```

## A-identity-20261017T090747.jsonl

```
```

## B-entries-source-20261017T090922.jsonl

```
# base-cand                                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# base-r4                                        rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-cand                              rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand                      rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-cand-nostrict                     rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand-nostrict             rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-r4                                rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-smuggle-r4                        rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-context-cand                               rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-cand-nostrict                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
```

## B-entries-source-20261017T090931.jsonl

```
# base-cand                                      rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# base-r4                                        rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-cand                              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand                      rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-cand-nostrict                     rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand-nostrict             rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-r4                                rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-smuggle-r4                        rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-context-cand                               rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-cand-nostrict                      rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-r4                                 rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context_r4.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-reply-cand                                 rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-cand-nostrict                        rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-r4                                   rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# registry-illegal-cand                          rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-disable-norm-cand             rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f --disable world_id_normalization
# registry-illegal-cand-nopropguard              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-r4                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4.json --expected-context-sha256 a6d77c998a033c5b86f1aa4e14a731e44b56c29459b53a6811043b519377af0d
# registry-illegal-nested-cand                   rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-cand-nopropguard       rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-r4                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4_nested.json --expected-context-sha256 e56aec5d6eedcd48f6b3be55da4ac3843483e9f79b0b562c911eb7f648fe6142
# registry-legal-cand                            rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# registry-legal-r4                              rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# source-missing-cand                            rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand                         rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand                              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-missing-cand-nosourceguard              rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand-nosourceguard           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand-nosourceguard                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-drift-path-unchanged-cand               rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-old-pin-cand                            rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_old_pin.json --expected-context-sha256 565e81dbd402acf9bb1678c481757f474297c76c2d549954bf12ddce33137b9a
# source-old-pin-r4-env-missing                  rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-path-sha-drift-cand                     rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_bad_path_sha.json --expected-context-sha256 ca4df25e15913febb3857b23cbd35962bce257677df2597a0ec50cfcb86c68d4
# source-adv-ctx-sha-cand                        rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_adv_source_sha.json --expected-context-sha256 b442d06c04c881089a5dbf33e1da95db3e70511b13450e19ca0ff4e3a7f4b162
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-env-real-cand                           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json"}
# source-missing-all-disable-cand                rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334 --disable ability --disable actor --disable budget --disable evidence --disable handle --disable jcs_fail_closed --disable outcome_window --disable params --disable schema --disable ttl
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
```

## B-entries-source-20261017T090956.jsonl

```
# base-cand                                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# base-r4                                        rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-cand                              rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand                      rc=1   traceback=False 0.18s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-cand-nostrict                     rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand-nostrict             rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-r4                                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-smuggle-r4                        rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-context-cand                               rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-cand-nostrict                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-r4                                 rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context_r4.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-reply-cand                                 rc=1   traceback=False 0.18s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-cand-nostrict                        rc=0   traceback=False 0.18s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-r4                                   rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# registry-illegal-cand                          rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-disable-norm-cand             rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f --disable world_id_normalization
# registry-illegal-cand-nopropguard              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-r4                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4.json --expected-context-sha256 a6d77c998a033c5b86f1aa4e14a731e44b56c29459b53a6811043b519377af0d
# registry-illegal-nested-cand                   rc=1   traceback=False 0.25s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-cand-nopropguard       rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-r4                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4_nested.json --expected-context-sha256 e56aec5d6eedcd48f6b3be55da4ac3843483e9f79b0b562c911eb7f648fe6142
# registry-legal-cand                            rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# registry-legal-r4                              rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# source-missing-cand                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand                         rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand                              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-missing-cand-nosourceguard              rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand-nosourceguard           rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand-nosourceguard                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-drift-path-unchanged-cand               rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-old-pin-cand                            rc=1   traceback=False 0.18s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_old_pin.json --expected-context-sha256 565e81dbd402acf9bb1678c481757f474297c76c2d549954bf12ddce33137b9a
# source-old-pin-r4-env-missing                  rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-path-sha-drift-cand                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_bad_path_sha.json --expected-context-sha256 ca4df25e15913febb3857b23cbd35962bce257677df2597a0ec50cfcb86c68d4
# source-adv-ctx-sha-cand                        rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_adv_source_sha.json --expected-context-sha256 b442d06c04c881089a5dbf33e1da95db3e70511b13450e19ca0ff4e3a7f4b162
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-env-real-cand                           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json"}
# source-missing-all-disable-cand                rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334 --disable ability --disable actor --disable budget --disable evidence --disable handle --disable jcs_fail_closed --disable outcome_window --disable params --disable schema --disable ttl
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
```

## B-entries-source-20261017T091023.jsonl

```
# base-cand                                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# base-r4                                        rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-cand                              rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand                      rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-cand-nostrict                     rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand-nostrict             rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-r4                                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-smuggle-r4                        rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-context-cand                               rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-cand-nostrict                      rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-r4                                 rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context_r4.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-reply-cand                                 rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-cand-nostrict                        rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-r4                                   rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# registry-illegal-cand                          rc=1   traceback=False 0.23s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-disable-norm-cand             rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f --disable world_id_normalization
# registry-illegal-cand-nopropguard              rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-r4                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4.json --expected-context-sha256 a6d77c998a033c5b86f1aa4e14a731e44b56c29459b53a6811043b519377af0d
# registry-illegal-nested-cand                   rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-cand-nopropguard       rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-r4                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4_nested.json --expected-context-sha256 e56aec5d6eedcd48f6b3be55da4ac3843483e9f79b0b562c911eb7f648fe6142
# registry-legal-cand                            rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# registry-legal-r4                              rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# source-missing-cand                            rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand                         rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand                              rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-missing-cand-nosourceguard              rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand-nosourceguard           rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand-nosourceguard                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-drift-path-unchanged-cand               rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-old-pin-cand                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_old_pin.json --expected-context-sha256 565e81dbd402acf9bb1678c481757f474297c76c2d549954bf12ddce33137b9a
# source-old-pin-r4-env-missing                  rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-path-sha-drift-cand                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_bad_path_sha.json --expected-context-sha256 ca4df25e15913febb3857b23cbd35962bce257677df2597a0ec50cfcb86c68d4
# source-adv-ctx-sha-cand                        rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_adv_source_sha.json --expected-context-sha256 b442d06c04c881089a5dbf33e1da95db3e70511b13450e19ca0ff4e3a7f4b162
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-env-real-cand                           rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json"}
# source-missing-all-disable-cand                rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334 --disable ability --disable actor --disable budget --disable evidence --disable handle --disable jcs_fail_closed --disable outcome_window --disable params --disable schema --disable ttl
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
```

## B-entries-source-20261017T091059.jsonl

```
# base-cand                                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# base-r4                                        rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-cand                              rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand                      rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-cand-nostrict                     rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-smuggle-cand-nostrict             rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-proposal-r4                                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-proposal-smuggle-r4                        rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_proposal_smuggle.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-context-cand                               rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-cand-nostrict                      rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# dup-context-r4                                 rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_context_r4.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# dup-reply-cand                                 rc=1   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-cand-nostrict                        rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_strict.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# dup-reply-r4                                   rc=0   traceback=False 0.17s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py reply --reply /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/dup_reply.json
# registry-illegal-cand                          rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-disable-norm-cand             rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f --disable world_id_normalization
# registry-illegal-cand-nopropguard              rc=1   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-r4                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4.json --expected-context-sha256 a6d77c998a033c5b86f1aa4e14a731e44b56c29459b53a6811043b519377af0d
# registry-illegal-nested-cand                   rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-cand-nopropguard       rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_propguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-cand-noregpropguard           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_noregpropguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property.json --expected-context-sha256 16b788ee00fe772bd5ab2a36fa5e7cdeba93341b4315b48672fa7ad7a2a4fd5f
# registry-illegal-nested-cand-noregpropguard    rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_noregpropguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_nested.json --expected-context-sha256 99f16c51e07b6cf8a8247f56a36ed7d7723fcd6bb4e687fdc4913199521b140a
# registry-illegal-nested-r4                     rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_illegal_property_r4_nested.json --expected-context-sha256 e56aec5d6eedcd48f6b3be55da4ac3843483e9f79b0b562c911eb7f648fe6142
# registry-legal-cand                            rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# registry-legal-r4                              rc=0   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# source-missing-cand                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand                         rc=1   traceback=False 0.23s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand                              rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-missing-cand-nosourceguard              rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-unreadable-cand-nosourceguard           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.unreadable.json"}
# source-drift-cand-nosourceguard                rc=0   traceback=False 0.21s
$ /usr/local/bin/python3 -I /tmp/b8-probe/patched/reports/V9-B1/r5-candidate/check_skill_proposal_sourceguard.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-drift-path-unchanged-cand               rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-old-pin-cand                            rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_old_pin.json --expected-context-sha256 565e81dbd402acf9bb1678c481757f474297c76c2d549954bf12ddce33137b9a
# source-old-pin-r4-env-missing                  rc=0   traceback=False 0.31s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/valid/01_valid_minimal_handle_target.json --context /Users/mac/AinerWorkFlow/AinerZero/contracts/v9/examples/skill_proposal_v1/contexts/01_valid_minimal_handle_target.json --expected-context-sha256 21302ef5f3c504e5280243c321ce91f2bb04a22d5195135b05dbd852b8b7706d
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
# source-path-sha-drift-cand                     rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_bad_path_sha.json --expected-context-sha256 ca4df25e15913febb3857b23cbd35962bce257677df2597a0ec50cfcb86c68d4
# source-adv-ctx-sha-cand                        rc=1   traceback=False 0.19s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/ctx_adv_source_sha.json --expected-context-sha256 b442d06c04c881089a5dbf33e1da95db3e70511b13450e19ca0ff4e3a7f4b162
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/observation_packet.drift.json"}
# source-env-real-cand                           rc=0   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334
# env_extra: {"AWZ_OBSERVATION_PATH": "/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json"}
# source-missing-all-disable-cand                rc=1   traceback=False 0.20s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py gate --proposal /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_proposal.json --context /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/tests/cases/base_context.json --expected-context-sha256 1119dca6b2927fced6da234e033e7d53f17b4aea47b46435d3419b3e990a3334 --disable ability --disable actor --disable budget --disable evidence --disable handle --disable jcs_fail_closed --disable outcome_window --disable params --disable schema --disable ttl
# env_extra: {"AWZ_OBSERVATION_PATH": "/tmp/b8-probe/sources/does-not-exist.json"}
```

## C-suite-20261017T091152.jsonl

```
# c1-default-run                                 rc=0   traceback=False 84.81s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# c2-output-run1                                 rc=0   traceback=False 86.76s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite --output-dir /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/results/suite/run1
# c2-output-run2                                 rc=0   traceback=False 81.35s
$ /usr/local/bin/python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite --output-dir /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-B1/r5-independent/results/suite/run2
# c3-outdir-r4-dir                               rc=0   traceback=False 80.78s
$ /usr/local/bin/python3 -I /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite --output-dir /tmp/b8-outdir/repo/reports/V9-B1
# c3-outdir-cand-dir                             rc=0   traceback=False 80.54s
$ /usr/local/bin/python3 -I /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite --output-dir /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate
# c3-outdir-fixtures                             rc=0   traceback=False 80.25s
$ /usr/local/bin/python3 -I /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite --output-dir /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate/fixtures
# c3-default-readonly-in-copy                    rc=1   traceback=False 0.42s
$ /usr/local/bin/python3 -I /tmp/b8-outdir/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
```

## D-fixture-suite-20261017T093127.jsonl

```
# d1-fixture-dup-tamper                          rc=1   traceback=False 0.40s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# d3-extra-fixture-dup                           rc=1   traceback=False 0.44s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# d2-probe-dup-tamper                            rc=1   traceback=True  89.42s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
```

## D-fixture-suite-20261018T084607.jsonl

```
# d1-fixture-dup-tamper                          rc=1   traceback=False 0.45s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# d3-extra-fixture-dup                           rc=1   traceback=False 0.49s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# d2-probe-dup-tamper                            rc=1   traceback=True  89.16s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal.py --suite
# d2b-probe-dup-nostrict                         rc=0   traceback=False 84.71s
$ /usr/local/bin/python3 -I /tmp/b8-suite-tamper/repo/reports/V9-B1/r5-candidate/check_skill_proposal_nostrict.py --suite
```
