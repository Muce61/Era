# V1.3.4 Development Roadmap v0.1

Status: DRAFT. This roadmap authorizes no implementation.

| Stage | Name | Status | Primary Dependency | Gate |
| --- | --- | --- | --- | --- |
| Stage 0 | 规格、工程地基与执行能力前置冻结 | DRAFT | NONE | 人工审批后方可执行 |
| Stage 1 | 历史数据基础 | DRAFT | Stage 0 | 人工审批后方可执行 |
| Stage 2 | 事件研究 | DRAFT | Stage 1 | 人工审批后方可执行 |
| Stage 3 | H3 成本与执行压力代理 | DRAFT | Stage 2 | 人工审批后方可执行 |
| Stage 4 | LOCKED_HISTORICAL_REPLAY | DRAFT | Stage 3 | 人工审批后方可执行 |
| Stage 5 | 前向数据与影子运行 | DRAFT | Stage 4 | 人工审批后方可执行 |
| Stage 6 | 测试网协议验证 | DRAFT | Stage 5 | 人工审批后方可执行 |
| Stage 7 | 极小资金执行校准 | DRAFT | Stage 6 | 人工审批后方可执行 |
| Stage 8 | 10 USDT 单轮实验 | DRAFT | Stage 7 | 人工审批后方可执行 |
| Stage 9 | 复利实验评估 | DRAFT | Stage 8 | 人工审批后方可执行 |

Stage lifecycle: `DRAFT → READY_FOR_APPROVAL → APPROVED → IN_PROGRESS → REVIEW → PASSED`; exceptional states are `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`. Every Stage begins only after current-code and prior-acceptance review, a versioned Plan, and explicit human approval. Future drafts may advance v0.1→v0.2 without changing completed stages. Upstream reopening invalidates affected downstream evidence. Stage 9 only evaluates whether a separate compounding protocol is worth proposing; it does not implement automatic compounding.

Global stop rules: event edge failure, H3 turning negative, tick-path direction collapse, naked/duplicate risk, F1 cost outside approved stress, locked replay failure, or reports/features improving while the registered core metric does not. Stopping does not authorize parameter rescue.
