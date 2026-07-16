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
| OQ-S0-001 | S0-T08 要求新增顶层 `era100x/contracts`，但 S0-T01 验收测试仅允许顶层 `foundation`；同时强制命令要求 `scripts/check_contract_coverage.py`，而该路径未列入 S0-T08 允许修改范围。 | RESOLVED | Stage 0 | NONE | 2026-07-12 Muce 人工批准：顶层显式允许清单为 `foundation`、`contracts`；保留未知顶层包阻断测试；允许 S0-T08 修改 `tests/test_package_import.py` 并新增覆盖检查脚本。Task 范围修正，不改变正式规格；无需 CR。 |
| OQ-S1-001 | Stage 1数据路径、容量与保留策略 | RESOLVED | Stage 1 | NONE | 当前工作根：`/Volumes/FuckingLife/era100x_stage1`（2026-07-13人工批准）。旧根`/Users/muce/1m_data/era100x_stage1`为SUPERSEDED且不得写入。Contract根永久只读；raw/published不可覆盖，不自动清理；T14要求可用空间不少于峰值×1.20。 |
| OQ-S1-002 | Binance Trades来源、授权和覆盖 | RESOLVED | Stage 1 | NONE | 2026-07-12人工决定：仅官方公开USDⓈ-M Trades归档，无账户/API Key/私有接口；BTCUSDT/ETHUSDT目标为本地Contract实际覆盖与官方可用区间交集，候选`[2020-01-01,2026-07-04)`；缺口如实记录。 |
| OQ-S1-003 | 如何满足Stage 1全量构建磁盘安全门？ | RESOLVED | Stage 1 T13 | NONE | 2026-07-13人工批准常驻外盘工作根`/Volumes/FuckingLife/era100x_stage1`；真实写探针通过。20%空间门、不可变和保留策略不变；以T13 v1.1复验结果为准。 |
| OQ-S1-004 | checksum有效的官方Trades月包跨日期交错后，同一UTC日期内部仍出现时间/Trade ID倒退；是否允许审计化外部排序？ | RESOLVED | Stage 1 T14 | NONE | 2026-07-13 Muce人工批准：按`(ts_event_ns, trade_id, canonical row)`磁盘外部稳定排序；排序前后行数、倒退计数、重复分类、输入hash和逻辑hash必须报告；冲突重复/非法值仍失败。无CR。 |
| OQ-S1-005 | 官方ETHUSDT 2025-08归档中`venue_trade_id=6299136398`存在两条不同成交事实，如何处置？ | RESOLVED | Stage 1 T14 | NONE | 2026-07-14 Muce批准CR-2026-001/ADR-2026-001：两条官方事实全部保留，以canonical事实身份去重并携带冲突标签；月包/日包canonical集合一致才允许发布。月包SHA-256为`464bdf18378ff90fea7cc4e019436f22b954e74a172554aa4b300498142e5cfc`。 |
| OQ-S2-001 | Stage 2大型候选、路径、标签和研究报告的外部可写根、不可变发布布局、保留策略与空间门是什么？ | OPEN | Stage 2 replanning | Stage 2 approval | 需Muce在Stage 2批准前指定；不得写入Stage 1工作根或Git仓库，不得自行沿用未批准路径。选项、影响和推荐见`reviews/stage_2_planning_approval_review_v1.2.md`；推荐不等于决定。 |
| OQ-S2-002 | Stage 2预注册的主标的、主假设、主标签、主匹配方案，以及U-007/U-008/U-009/U-011参数域与失败线是什么？ | OPEN | Stage 2 preregistration | S2-T19 and Stage 2 approval | 需Muce人工决定；Codex不得从已观察数据选择最有利设定。BTC/ETH仍必须分别研究，未选为primary者作为预注册secondary。选项、影响和推荐见`reviews/stage_2_planning_approval_review_v1.2.md`；推荐不等于决定。 |
| OQ-S2-003 | Stage 2事件说明是否需要类似带K线、步骤、门和研究问题的可视化图片？ | RESOLVED | Stage 2 reporting | NONE | 2026-07-14 Muce明确要求加入。Plan v1.2将带显著水印的`EVENT_EXPLAINER`与真实数据驱动的`EVENT_EVIDENCE_CARD`折入S2-T20验收报告要求，不再保留独立S2-T21；正式证据必须确定性、可追溯且不得伪造历史或执行字段。精确字体/配色和渲染依赖在S2-T20批准前冻结。 |

New questions must record discovery/source, affected rules/contracts/baselines, evidence required, owner, status, and linked ADR/CR. No unresolved question may be answered by assumption.

U-001～U-003 remain OPEN after Stage 0 final approval. They block only their recorded downstream execution/adaptation scopes and do not invalidate the offline Stage 0 v1.0 baseline.

All OPEN questions assigned to Stage 2 or later remain OPEN after Stage 1 final approval. They do not invalidate the Stage 1 v1.0 historical data baseline, but continue to block their recorded downstream research or execution scope.
