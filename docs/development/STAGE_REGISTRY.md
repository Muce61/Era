# Stage Registry

Allowed statuses: `DRAFT`, `READY_FOR_APPROVAL`, `APPROVED`, `IN_PROGRESS`, `REVIEW`, `PASSED`, `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

| Stage | Plan Version | Status | Dependencies | Baseline | Validity | Notes |
| ----- | ------------ | ------ | ------------ | -------- | -------- | ----- |
| Stage 0 | 0.1 | DRAFT | NONE | NONE | NOT_EXECUTED | 规格、工程地基与执行能力前置冻结; human approval required |
| Stage 1 | 0.1 | DRAFT | Stage 0 | NONE | NOT_EXECUTED | 历史数据基础; human approval required |
| Stage 2 | 0.1 | DRAFT | Stage 1 | NONE | NOT_EXECUTED | 事件研究; human approval required |
| Stage 3 | 0.1 | DRAFT | Stage 2 | NONE | NOT_EXECUTED | H3 成本与执行压力代理; human approval required |
| Stage 4 | 0.1 | DRAFT | Stage 3 | NONE | NOT_EXECUTED | LOCKED_HISTORICAL_REPLAY; human approval required |
| Stage 5 | 0.1 | DRAFT | Stage 4 + Execution Capability | NONE | NOT_EXECUTED | 前向数据与影子运行; human approval required |
| Stage 6 | 0.1 | DRAFT | Stage 5 | NONE | NOT_EXECUTED | 测试网协议验证; human approval required |
| Stage 7 | 0.1 | DRAFT | Stage 6 + F1 evidence | NONE | NOT_EXECUTED | 极小资金执行校准; human approval required |
| Stage 8 | 0.1 | DRAFT | Stage 7 | NONE | NOT_EXECUTED | 10 USDT 单轮实验; human approval required |
| Stage 9 | 0.1 | DRAFT | Stage 8 | NONE | NOT_EXECUTED | 复利实验评估; human approval required |
