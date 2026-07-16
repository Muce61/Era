# Stage Registry

Allowed statuses: `DRAFT`, `READY_FOR_APPROVAL`, `APPROVED`, `IN_PROGRESS`, `REVIEW`, `READY_FOR_FINAL_APPROVAL`, `PASSED`, `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

| Stage | Plan Version | Status | Dependencies | Baseline | Validity | Notes |
| ----- | ------------ | ------ | ------------ | -------- | -------- | ----- |
| Stage 0 | 1.0 | PASSED | NONE | `stage-0-v1.0-passed` | VALID | Final human approval 2026-07-12; validated implementation commit `692dd29`; 13 Tasks PASSED |
| Stage 1 | 1.1 | IN_PROGRESS | Stage 0 PASSED | NONE | PARTIALLY_EXECUTED | CR-2026-001 Trade Identity v2 approved; S1-T01～S1-T14 PASSED; 162/162 run published and scheduler regression closed; S1-T15 DRAFT pending integration acceptance |
| Stage 2 | 1.1 | DRAFT | Stage 1 PASSED + VALID data baseline | NONE | NOT_EXECUTED | Extensible setup/context registry and deterministic event explainer/evidence-card planning added; OQ-S2-001/002 and final Stage 1 gate block approval; no Task executed |
| Stage 3 | 0.1 | DRAFT | Stage 2 | NONE | NOT_EXECUTED | H3 成本与执行压力代理; human approval required |
| Stage 4 | 0.1 | DRAFT | Stage 3 | NONE | NOT_EXECUTED | LOCKED_HISTORICAL_REPLAY; human approval required |
| Stage 5 | 0.1 | DRAFT | Stage 4 + Execution Capability | NONE | NOT_EXECUTED | 前向数据与影子运行; human approval required |
| Stage 6 | 0.1 | DRAFT | Stage 5 | NONE | NOT_EXECUTED | 测试网协议验证; human approval required |
| Stage 7 | 0.1 | DRAFT | Stage 6 + F1 evidence | NONE | NOT_EXECUTED | 极小资金执行校准; human approval required |
| Stage 8 | 0.1 | DRAFT | Stage 7 | NONE | NOT_EXECUTED | 10 USDT 单轮实验; human approval required |
| Stage 9 | 0.1 | DRAFT | Stage 8 | NONE | NOT_EXECUTED | 复利实验评估; human approval required |
