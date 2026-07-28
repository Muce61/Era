# Stage Registry

Allowed statuses: `DRAFT`, `READY_FOR_APPROVAL`, `APPROVED`, `IN_PROGRESS`, `REVIEW`, `READY_FOR_FINAL_APPROVAL`, `PASSED`, `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

This current projection must match `configs/governance/current_development_state.json`,
`docs/development/CURRENT_STAGE.md` and the active per-Plan Policy. Strict governance validation
fails closed on any mismatch. Historical Plan/Task status remains in its original CR, ADR,
validation and immutable Policy rather than being presented as the current Stage row.

| Stage | Plan Version | Status | Dependencies | Baseline | Validity | Notes |
| ----- | ------------ | ------ | ------------ | -------- | -------- | ----- |
| Stage 0 | 1.0 | PASSED | NONE | `stage-0-v1.0-passed` | VALID | Final human approval 2026-07-12; validated implementation commit `692dd29`; 13 Tasks PASSED |
| Stage 1 | 1.1 | PASSED | Stage 0 PASSED | `stage-1-v1.0-passed` | VALID | Final human approval 2026-07-16; Stage baseline version 1.0 over approved Plan v1.1; Validation `docs/development/validations/stage_1_validation.md`; S1-T01～S1-T15 PASSED |
| Stage 2 | 1.7 | BLOCKED | Stage 1 PASSED + VALID data baseline + immutable Plan v1.2–v1.6 evidence chain | NONE | STAGE2_NO_GO_CURRENT_EVIDENCE | Plan v1.2 S2-T15 remains historical `STOPPED_FAILED_UNPUBLISHED`; its capability successor is Plan v1.3 `S2P13-T16`, so the legacy terminal state is not the current Task and is not a T20 dependency blocker. Plans v1.3–v1.7 completed their separately approved T16–T20 ceilings. S2P17-T20 passed engineering, publication, reconciliation and independent Verify, but BTC and ETH Primary both failed and lifecycle evidence remains `INCONCLUSIVE_SOURCE_GAP_CENSORING`. This is not Stage 2 research PASS. T21 was not executed and Stage 3 remains locked. |
| Stage 3 | 0.1 | DRAFT | Stage 2 | NONE | NOT_EXECUTED | H3 成本与执行压力代理; Stage 3 remains locked; human approval required |
| Stage 4 | 0.1 | DRAFT | Stage 3 | NONE | NOT_EXECUTED | LOCKED_HISTORICAL_REPLAY; human approval required |
| Stage 5 | 0.1 | DRAFT | Stage 4 + Execution Capability | NONE | NOT_EXECUTED | 前向数据与影子运行; human approval required |
| Stage 6 | 0.1 | DRAFT | Stage 5 | NONE | NOT_EXECUTED | 测试网协议验证; human approval required |
| Stage 7 | 0.1 | DRAFT | Stage 6 + F1 evidence | NONE | NOT_EXECUTED | 极小资金执行校准; human approval required |
| Stage 8 | 0.1 | DRAFT | Stage 7 | NONE | NOT_EXECUTED | 10 USDT 单轮实验; human approval required |
| Stage 9 | 0.1 | DRAFT | Stage 8 | NONE | NOT_EXECUTED | 复利实验评估; human approval required |
