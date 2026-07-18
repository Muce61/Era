# Stage Registry

Allowed statuses: `DRAFT`, `READY_FOR_APPROVAL`, `APPROVED`, `IN_PROGRESS`, `REVIEW`, `READY_FOR_FINAL_APPROVAL`, `PASSED`, `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

| Stage | Plan Version | Status | Dependencies | Baseline | Validity | Notes |
| ----- | ------------ | ------ | ------------ | -------- | -------- | ----- |
| Stage 0 | 1.0 | PASSED | NONE | `stage-0-v1.0-passed` | VALID | Final human approval 2026-07-12; validated implementation commit `692dd29`; 13 Tasks PASSED |
| Stage 1 | 1.1 | PASSED | Stage 0 PASSED | `stage-1-v1.0-passed` | VALID | Final human approval 2026-07-16; Stage baseline version 1.0 over approved Plan v1.1; Validation `docs/development/validations/stage_1_validation.md`; S1-T01～S1-T15 PASSED |
| Stage 2 | 1.2 | IN_PROGRESS | Stage 1 PASSED + VALID data baseline | NONE | READY_FOR_CR_2026_012_AUTHORITY_REFREEZE_AND_REPLACEMENT_RUN_B | Formal Run A is PUBLISHED/PASS and immutable. The CR-2026-011 replacement Run B completed all BTC monthly and packed Foundation objects but failed unpublished before Task sealing because lifetime `ru_maxrss` was enforced as a phase-local delta. CR-2026-012 implements audit-only lifetime peak plus continuously sampled 1 GiB Arrow / 3 GiB current RSS / 1 GiB phase-current delta gates; its real packing/seal profile and quality gates PASS. The failed run is terminal and cannot be reused. S2-T19 and S2-T01～S2-T09 remain PASSED; S2-T10 v1.10 is IN_PROGRESS; Groups 2～4 remain DRAFT and unexecuted. |
| Stage 3 | 0.1 | DRAFT | Stage 2 | NONE | NOT_EXECUTED | H3 成本与执行压力代理; human approval required |
| Stage 4 | 0.1 | DRAFT | Stage 3 | NONE | NOT_EXECUTED | LOCKED_HISTORICAL_REPLAY; human approval required |
| Stage 5 | 0.1 | DRAFT | Stage 4 + Execution Capability | NONE | NOT_EXECUTED | 前向数据与影子运行; human approval required |
| Stage 6 | 0.1 | DRAFT | Stage 5 | NONE | NOT_EXECUTED | 测试网协议验证; human approval required |
| Stage 7 | 0.1 | DRAFT | Stage 6 + F1 evidence | NONE | NOT_EXECUTED | 极小资金执行校准; human approval required |
| Stage 8 | 0.1 | DRAFT | Stage 7 | NONE | NOT_EXECUTED | 10 USDT 单轮实验; human approval required |
| Stage 9 | 0.1 | DRAFT | Stage 8 | NONE | NOT_EXECUTED | 复利实验评估; human approval required |
