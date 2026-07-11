# Open Questions

These questions are inherited from V1.3.4 Appendix N. They do not block planning, but block the stated downstream scope until evidence and human decision exist.

| ID | Question | Status | Evidence Stage | Blocking Scope | Decision Boundary |
| --- | --- | --- | --- | --- | --- |
| U-001 | MARK_PRICE或CONTRACT_PRICE | OPEN | Execution Spike+F1 | small-live | 人工决定；不得由Codex冻结 |
| U-002 | Algo active status映射和适配器事件完整性 | OPEN | Stage 0 Spike | 影子自动状态 | 人工决定；不得由Codex冻结 |
| U-003 | Nautilus适配是否覆盖Algo Service | OPEN | Stage 0 Spike | 执行适配选型 | 人工决定；不得由Codex冻结 |
| U-004 | 正常退出IOC回退时限和滑点包络 | OPEN | Stage 5/7 | small-live | 人工决定；不得由Codex冻结 |
| U-005 | stop_trigger_to_fill_stress_bps | OPEN | Stage 7 | 100x开仓门 | 人工决定；不得由Codex冻结 |
| U-006 | mark_contract_divergence_stress_bps | OPEN | Stage 5 | 100x开仓门 | 人工决定；不得由Codex冻结 |
| U-007 | 关键位优先级、合并容差、episode间隔和re-arm | OPEN | Stage 2 | 事件冻结 | 人工决定；不得由Codex冻结 |
| U-008 | max_target_bps_allowed_for_event | OPEN | Stage 2/3 | 部分成交条件 | 人工决定；不得由Codex冻结 |
| U-009 | 15-35bp止损范围 | OPEN | Stage 2/3/5/7 | small-live | 人工决定；不得由Codex冻结 |
| U-010 | 激活和阶梯参数 | OPEN | Stage 3/4 | 持仓规则 | 人工决定；不得由Codex冻结 |
| U-011 | 时间退出参数 | OPEN | Stage 2/3 | 持仓规则 | 人工决定；不得由Codex冻结 |
| U-012 | H3成本、延迟和尾部情景 | OPEN | Stage 3/5/7 | H3解释范围 | 人工决定；不得由Codex冻结 |
| U-013 | F1无条件单轮概率能否支持多轮 | OPEN | Stage 5/7/8 | Stage 9 | 人工决定；不得由Codex冻结 |
| STAGE9-CAPACITY | 复利后期容量、杠杆档位和冲击 | OPEN | Stage 9 | 多轮复利 | 人工决定；不得由Codex冻结 |

New questions must record discovery/source, affected rules/contracts/baselines, evidence required, owner, status, and linked ADR/CR. No unresolved question may be answered by assumption.
