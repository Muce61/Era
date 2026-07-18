# Stage Registry

Allowed statuses: `DRAFT`, `READY_FOR_APPROVAL`, `APPROVED`, `IN_PROGRESS`, `REVIEW`, `READY_FOR_FINAL_APPROVAL`, `PASSED`, `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

| Stage | Plan Version | Status | Dependencies | Baseline | Validity | Notes |
| ----- | ------------ | ------ | ------------ | -------- | -------- | ----- |
| Stage 0 | 1.0 | PASSED | NONE | `stage-0-v1.0-passed` | VALID | Final human approval 2026-07-12; validated implementation commit `692dd29`; 13 Tasks PASSED |
| Stage 1 | 1.1 | PASSED | Stage 0 PASSED | `stage-1-v1.0-passed` | VALID | Final human approval 2026-07-16; Stage baseline version 1.0 over approved Plan v1.1; Validation `docs/development/validations/stage_1_validation.md`; S1-T01～S1-T15 PASSED |
| Stage 2 | 1.2 | IN_PROGRESS | Stage 1 PASSED + VALID data baseline | NONE | READY_FOR_V2_RUN_B_EXECUTION_APPROVAL | Formal Run A is PUBLISHED with Quality PASS, 9508/9508 complete, zero failed/UNKNOWN and immutable published logical/physical hashes. CR-2026-009 remains APPROVED with implementation and validation complete; a new write-once Authority Bundle covers all 4,752 Stage 1 instrument-days, accepts only Catalog-authorized monthly or exact-day archives, and repeats deterministically without creating Run B. S2-T19 and S2-T01～S2-T09 remain PASSED; S2-T10 remains IN_PROGRESS; Groups 2～4 remain DRAFT and unexecuted. Separate human approval is required before V2 Run B. |
| Stage 3 | 0.1 | DRAFT | Stage 2 | NONE | NOT_EXECUTED | H3 成本与执行压力代理; human approval required |
| Stage 4 | 0.1 | DRAFT | Stage 3 | NONE | NOT_EXECUTED | LOCKED_HISTORICAL_REPLAY; human approval required |
| Stage 5 | 0.1 | DRAFT | Stage 4 + Execution Capability | NONE | NOT_EXECUTED | 前向数据与影子运行; human approval required |
| Stage 6 | 0.1 | DRAFT | Stage 5 | NONE | NOT_EXECUTED | 测试网协议验证; human approval required |
| Stage 7 | 0.1 | DRAFT | Stage 6 + F1 evidence | NONE | NOT_EXECUTED | 极小资金执行校准; human approval required |
| Stage 8 | 0.1 | DRAFT | Stage 7 | NONE | NOT_EXECUTED | 10 USDT 单轮实验; human approval required |
| Stage 9 | 0.1 | DRAFT | Stage 8 | NONE | NOT_EXECUTED | 复利实验评估; human approval required |
