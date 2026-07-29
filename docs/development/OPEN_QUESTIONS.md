# Open Questions

## OQ-S2-013 — Plan v1.8 production adapter dataflow and full-scope source binding

- status: RESOLVED BY CR-2026-050 ADDENDUM / ADR-S2-027; IMPLEMENTATION VALIDATION
  COMPLETE; FORMAL ARTIFACTS AND RUN REMAIN GATED
- task: S2P18-T11–T20 v1.0
- discovered_by: post-commit production-adapter audit at
  `c2e2e573b2631b39575d70f33770d4c96b0057e0`
- evidence:
  - the only sealed Plan v1.8 Contract Price source audit covers
    `[2020-01-01, 2020-01-08)`, while the frozen Stage 2 source period is
    `[2020-01-01, 2026-07-04)`;
  - only S2P18-T11 has a real v1.8 producer core. Existing T12–T20 producers and their source
    auditors hard-code S2P13/S2P14/S2P15/S2P16/S2P17 identities, expected Run IDs, counts and
    receipt schemas;
  - the current outer Authority freezes twelve Hash values but no immutable path-to-Hash input
    Catalog, so a producer cannot resolve and independently verify the exact bound source files;
  - the approved v1.8 Task text propagates lifecycle tracks through T12–T15 while also requiring
    T16 H2 semantic identity. Feeding OHLC-recovered boundaries into H2 First Passage would change
    the H2 estimand; silently ignoring those tracks would contradict the current downstream text;
  - the outer runner can resume only between Tasks. A producer interruption leaves its staging
    directory present and the current resume path rejects it before the producer can consume its
    checkpoint.
- affected rules/contracts/baselines:
  `DATA-HISTORICAL-NO-FAKE-EXECUTION`, `RESEARCH-H3-CONDITIONAL-ROUND-PROB`,
  ADR-S2-004 H2 Primary, CR-2026-050, ADR-S2-026, Plan v1.8 and S2P18-T11–T20. Historical
  Plan v1.7 evidence remains immutable.
- decision_required:
  1. require a full-period Contract Price source Catalog/audit before adapter freeze;
  2. add an immutable input Catalog carrying exact paths, file/Logical Hashes and roles to the
     outer Authority;
  3. keep S2P18-T12–T18 H2 on the canonical-Trades estimand and carry both lifecycle tracks on a
     separate T11→T19/T20 evidence branch; T11 remains a governance prerequisite but its OHLC
     boundary classifications are not H2 labels;
  4. permit new S2P18 producer envelopes to reuse verified mathematical engines only after removing
     old Task/Run/count constants from their input auditors; old receipts themselves cannot be
     adopted as new results;
  5. make per-Task attempts append-only and checkpoint-resumable, with a new Run required after a
     terminal producer failure.
- evidence_required: amended CR/ADR/Plan/Task contracts, full-range source audit and Catalog,
  ten real producer handlers, scalar/legacy equivalence fixtures, interrupted-task resume tests,
  T16 normalized H2 Hash equality, full fake-chain and bounded real rehearsal.
- decision: Muce approved the five-part minimum repair on 2026-07-29. The implementation adds the
  full-period source-audit/Catalog tool, immutable twelve-role input Catalog, canonical-Trades-only
  H2 branch, ten real S2P18 producer handlers and append-only retryable Task attempts. Directed and
  repository-wide validation must pass and the implementation must be frozen in a clean commit.
- remaining_gate: this resolution does not create the full-period source evidence, adapter plan,
  approval receipt, Authority or Run. Those formal artifacts require the new clean commit and the
  next separate commit-bound approval.

## OQ-S2-012 — Lifecycle producer exit-source and occupancy contract

- status: RESOLVED BY CR-2026-042 / ADR-S2-019
- task: S2P13-T11 v1.0
- discovered_by: CR-2026-041 production-producer wiring
- evidence: The approved lifecycle engine accepts `protection_exit` and `structure_exit`, but no
  sealed input, formula or deterministic producer contract supplies either value. The repository
  also does not freeze Contract Price versus Trade crossing precedence, the funding-notional
  basis at each settlement, or the exact single-position event-conflict replay.
- decision: Muce approved the minimum price-only producer contract on 2026-07-23. Protection and
  structure are explicitly not modeled; Contract Price owns valuation/liquidation/funding
  notional; Trades own target/stop; fixed quantity uses `800 / entry`; policy timelines are
  independent and right-censoring never implies flat.
- boundary: no default-false exit flags, no invented structure/protection facts, no formal
  Authority/bin/Run, no final-code rehearsal, no S2P13-T17+ and Stage 3 remains locked.

## OQ-S2-008 — S2-T15 strict Decimal receiver and final successor recovery

- status: RESOLVED BY CR-2026-029 / IMPLEMENTATION GATES REMAIN
- task: S2-T15 v1.4
- proposed_resolution: CR-2026-029
- evidence: The CR-2026-028 successor completed `456 / 456` outcome-blind groups, then failed
  unpublished before the first control H2 outcome because canonical JSON encoded
  `control_entry_price` as a string while strict validation requires a `Decimal` instance.
- decision_needed: approve or reject the minimum receiver conversion, invalidation of the failed
  successor chain and exactly one final replacement Authority/bin/Run chain.
- boundary: no in-place override, no partial-result publication, no contract change, no S2-T16+,
  and Stage 3 remains locked.
- decision: Muce approved the minimum strict Decimal receiver correction, invalidation of the
  failed CR-2026-028 successor chain and exactly one final replacement chain at
  `2026-07-22T14:12:52Z`.
- remaining_gates: regression tests, full quality, fresh audit, corrected Authority/TRAIN bins and
  final preflight must PASS before the final Run ID.

## OQ-S2-007 — S2-T15 sealed Episode Context receiver and successor recovery

- status: RESOLVED BY CR-2026-028 / SUCCESSOR FAILURE TRACKED BY OQ-S2-008
- discovered_by: first formal S2-T15 v1.4 Run
- proposed_resolution: CR-2026-028
- evidence: BTC 220,201/220,201 and ETH 312,507/312,507 have complete, conflict-free
  `(trigger_id, event_parameter_set_id)` bindings and all bound trigger states are `UP/PASS`.
- decision_required: approve the direct sealed price-trigger Context binding, a read-only supplement
  for 4,752 legacy `price_triggers` receipts, and exactly one successor Authority/bin/Run chain.
- decision: Muce approved the sealed trigger Context binding, 4,752-partition read-only supplement,
  invalidation of the first unpublished chain and exactly one successor chain at
  `2026-07-22T08:53:43Z`.
- remaining_gates: implementation quality, supplement and fresh audit must PASS before Authority;
  successor preflight must PASS before the single successor Run ID.

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
| OQ-S2-001 | Stage 2大型候选、路径、标签和研究报告的外部可写根、不可变发布布局、保留策略与空间门是什么？ | RESOLVED | Stage 2 replanning | NONE | 2026-07-16T14:33:04+08:00 Muce批准：根为`/Volumes/FuckingLife/era100x_stage2`；布局`runs/<run_id>/{staging,published,manifests,reports,logs,tmp}`；峰值×1.20空间门；外盘不可用直接BLOCKED且无备用根；published/manifests/reports append-only并长期保留；失败staging审计前不得清理，清理需人工批准和审计记录；无效运行Manifest、报告和失效记录永久保留。 |
| OQ-S2-002 | Stage 2预注册的主标的、主假设、主标签、主匹配方案，以及U-007/U-008/U-009/U-011参数域与失败线是什么？ | RESOLVED | Stage 2 preregistration | NONE | 2026-07-16T14:33:04+08:00 Muce批准：BTC primary、ETH independent secondary；严格TARGET_FIRST_STRICT高于同标的条件随机基线，AMBIGUOUS主结果按失败；primary target/stop=20/25bp，target域20/30/40/50/70/100，stop域15/20/25/30/35，max target=100；merge域5/10/15(primary10)，gap域60/300/900(primary300)s，re-arm域300/900/1800(primary900)s；primary时间30/30/180s；cluster=instrument×UTC week，bootstrap=5000，双侧95%CI。U-007/U-008/U-009/U-011仍为RESEARCH，不冻结最终参数；补充精确定义见ADR-S2-004。 |
| OQ-S2-003 | Stage 2事件说明是否需要类似带K线、步骤、门和研究问题的可视化图片？ | RESOLVED | Stage 2 reporting | NONE | 2026-07-14 Muce明确要求加入。Plan v1.2将带显著水印的`EVENT_EXPLAINER`与真实数据驱动的`EVENT_EVIDENCE_CARD`折入S2-T20验收报告要求，不再保留独立S2-T21；正式证据必须确定性、可追溯且不得伪造历史或执行字段。精确字体/配色和渲染依赖在S2-T20批准前冻结。 |
| OQ-S2-004 | 2026-07-16审批引用的T1/T3/T4精确时间组合、三个预注册时期、条件随机匹配bin/固定放宽层级和主失败线在仓库及全部本地历史中均无定义；其精确值是什么？ | RESOLVED | Stage 2 preregistration completion | NONE | 2026-07-16T14:51:38+08:00 Muce人工批准完整定义；见[ADR-S2-004](decisions/ADR-S2-004-primary-research-definition.md)。T2是唯一Primary；P1/P2/P3、L0～L5、5 controls、matching/bootstrap seed 20260716、AMBIGUOUS失败、F1～F10与ETH分类均已预注册。全部为BASELINE/RESEARCH，不是最优或FROZEN。 |
| OQ-S2-005 | ADR-S2-004声称沿用已批准的1m波动率和Trades活跃度公式，但仓库及全部Git历史均无公式本体；正式条件基线也缺少split/fold边界、精确purge/embargo长度和非事件control锚点生成规则。精确定义是什么？ | RESOLVED | S2-T15 full conditional baseline | NONE | 2026-07-22T02:25:41Z Muce批准CR-2026-026、ADR-S2-009、S2-T15 v1.4及T19 append-only addendum；冻结三特征、关键位距离、F0-F3滚动折、3600/600秒、daily grid、三层control identity、T13/T14绑定和全量对账。未知结果不预先获批。 |
| OQ-S2-006 | 固定T10的14,256个Group-1关键位/MarketEpisode分区收据未携带其DatasetSpec要求的`field.*`分布摘要，当前权威`CatalogReaderV2`因此拒绝读取。T15应如何获得可验证且不改写密封T10的只读输入？ | RESOLVED | S2-T15 upstream binding | NONE | 2026-07-22T03:24:18Z Muce批准独立CR-2026-027；只读补证已验证14,256/14,256，T10修改为0，新audit PASS。正式Authority仍需最终干净提交和最终治理Hash重审计。 |
| OQ-S2-009 | T15已准备BTC/P1/B0的210,240个grid anchors中，首61个因61-bar回看越过历史起点而`PRICE_FEATURE_UNAVAILABLE`；BTC/ETH全范围是否还有边界warmup、声明gap或未绑定分区，分别怎样处理？ | RESOLVED / MIGRATED TO EXECUTION GATE | S2P13-T11～T16 final-code rehearsal | NONE | 缺失分类和失败动作已经明确。CR-2026-040确认“最终代码7天端到端短跑”是执行规范而非待决问题，并迁移为`FINAL_CODE_7_DAY_REHEARSAL`门。短跑未通过前正式Authority/bin/Run仍禁止；正式全量Run继续对未知缺失、未绑定和Hash漂移硬失败。 |
| OQ-S2-010 | “存活较长、尚未激活、净可退出PnL接近零”各自精确定义什么，理论策略从何时入场、怎样运行到完全平仓、何时右删失，以及如何避免幸存者偏差？ | RESOLVED / FUNDING LOCAL HISTORY HUMAN ACCEPTED | S2P13-T11 lifecycle | NONE | 生命周期定义由CR-2026-036/037冻结。CR-2026-038短跑完成官方抽样并识别毫秒取整；Muce随后明确免除逐月全历史官方核对和独立preflight绑定。BTC/ETH各7,128条完整本地历史经Hash、唯一性、连续性验证后接收；不声称逐月官方一致。 |
| OQ-S2-011 | “特异研究点”能否局部豁免FROZEN研究规则；哪些规则可豁免、哪些事实/安全/治理规则永不可豁免，探索输出怎样与正式证据隔离？ | RESOLVED | Plan v1.3 research governance | NONE | CR-2026-033/ADR-S2-012框架已实现默认继承、显式豁免、未知/通配符/Hash漂移拒绝和正式消费者隔离；仓库级Ruff、strict mypy、strict Traceability、strict governance及678项测试通过。CR-2026-039关闭本OQ并将其从正式生命周期门禁移除。框架继续供未来自由研究使用；SRP、CR、ADR历史全部保留。 |
| OQ-S2-012 | S2P13-T11全量生产器应从哪里得到保护退出、结构退出，Contract Price与Trade同刻如何排序，资金费按什么名义金额结算，单仓冲突如何跳过事件？ | RESOLVED | S2P13-T11 lifecycle producer | NONE | CR-2026-042/ADR-S2-019冻结最小price-only代理：保护/结构明确不建模；Contract Price估值和资金费；Trades触发目标/止损；独立单仓时间线。 |

New questions must record discovery/source, affected rules/contracts/baselines, evidence required, owner, status, and linked ADR/CR. No unresolved question may be answered by assumption.

## OQ-S2-012 audit record

- Discovery/source: CR-2026-041 changed the orchestration handoff from an output-only Hash to a
  complete upstream artifact contract. While designing the real S2P13-T11 producer, the only
  lifecycle observation model was found to require `protection_exit` and `structure_exit`
  booleans. Repository-wide search found no historical source or approved deterministic formula
  for those values.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, `DATA-HISTORICAL-NO-FAKE-EXECUTION`,
  `EXEC-EXIT-COORDINATOR-ONLY`, V1.3.5 §12.1/§14.2 and S2P13-T11. Plan v1.2 evidence and all
  sealed files remain unchanged.
- Additional unresolved producer choices: exact Contract Price/Trade trigger precedence; whether
  funding amount uses fixed entry notional or time-varying proxy notional; and deterministic
  single-position conflict handling for the immediate-exit and continue-holding timelines.
- Evidence required: approved CR/ADR and directed fixtures proving deterministic exits, funding,
  collision handling, BTC/ETH separation, no future facts and no Stage 3/live claim.
- Owner/status: Muce / `RESOLVED` by CR-2026-042 and ADR-S2-019 on 2026-07-23.
- Linked governance: [CR-2026-041](changes/CR-2026-041.md),
  [CR-2026-042](changes/CR-2026-042.md),
  [ADR-S2-019](decisions/ADR-S2-019-minimum-price-only-lifecycle-producer.md),
  [ADR-S2-014](decisions/ADR-S2-014-stage2-conditional-h3-lifecycle.md) and
  [S2P13-T11](tasks/stage_2/S2P13-T11-lifecycle.md).

## OQ-S2-009 audit record

- Discovery/source: Muce stopped the active T15 bin preparation after a read-only progress view
  exposed data unavailability. The complete BTC/P1/B0 prepared block has 210,179 available and 61
  unavailable price-feature anchors; the exact unavailable range is
  `2020-01-01T00:00:09Z` through `2020-01-01T01:00:09Z` at one-minute intervals.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, `DATA-HISTORICAL-NO-FAKE-EXECUTION`, S2-T15 v1.4 feature,
  split and reconciliation contracts. Stage 1 and sealed T10-T14 bytes remain unchanged.
- Evidence required: final-code seven-complete-UTC-day producer-to-UI rehearsal with exact
  boundary/gap/unbound/invalid/zero-observation classification, consumer read-back,
  reconciliation and immutable Hashes. The formal full-data Run retains the same fail-closed
  checks over the complete range.
- Owner/status: Muce / `RESOLVED`; CR-2026-040 classifies the final-code seven-day end-to-end
  rehearsal as the independent `FINAL_CODE_7_DAY_REHEARSAL` execution gate rather than an open
  question. The earlier boundary audit remains supporting evidence but cannot satisfy that gate.
- Linked governance: [CR-2026-031](changes/CR-2026-031.md) and
  [ADR-S2-010](decisions/ADR-S2-010-historical-missingness.md).

## OQ-S2-010 audit record

- Discovery/source: Muce requested separate exit-rule-free event paths and a complete theoretical
  strategy lifecycle, with a preregistered delayed-activation/decay sub-hypothesis.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, `DATA-HISTORICAL-NO-FAKE-EXECUTION`,
  `EXEC-EXIT-COORDINATOR-ONLY`, U-010, U-011 and U-012. Accepted T1-T4 raw evidence and the sole
  Primary T2 remain unchanged.
- Evidence required: the V1.3.5 definitions are now frozen. Formal execution additionally requires
  immutable signed historical funding rows with settlement timestamp, availability, Hash and gap
  bindings for BTCUSDT and ETHUSDT. Contract Price/canonical Trades are the approved H3 proxy and
  must not be relabeled as historical Mark Price.
- Owner/status: Muce / `OPEN`; CR-2026-035 and ADR-S2-014/015 freeze the task contract. A
  2026-07-23 read-only inventory found no funding dataset in the fixed T10 snapshot,
  Stage 1/2 external roots or repository registry. Price-only implementation tests may continue;
  Authority, formal rehearsal and Run remain blocked.
- Resolved sub-decisions: CR-2026-036/ADR-S2-016 approve the Contract Price H3 proxy and make T2
  20bp auxiliary only. Continuation exits at the first observation with net scenario PnL at least
  10U, so the no-funding main-cost threshold is approximately 136bp and increases with accumulated
  funding.
- CR-2026-037/ADR-S2-017 freeze Primary signed historical funding, adverse 1.5x/2x and no-credit
  Stress tracks. Theoretical liquidation is net margin depletion at `scenario_net_pnl <= -8U` on
  the Contract Price proxy; historical Mark and exchange bracket inputs are no longer required.
- CR-2026-038 found the existing local BTC/ETH funding candidates and authorizes a read-only
  month-by-month comparison against Binance official archives. Official rows win discrepancies
  without modifying legacy files. The isolated seven-day rehearsal precedes full-history
  acceptance; no lifecycle Authority or Run is authorized by this CR.
- Linked governance: [CR-2026-032](changes/CR-2026-032.md) and
  [ADR-S2-011](decisions/ADR-S2-011-event-path-and-strategy-lifecycle-separation.md).

## OQ-S2-011 audit record

- Discovery/source: Muce requested a framework-level `SPECIAL_RESEARCH_POINT` for freer research,
  with the explicit constraint that only declared rule exemptions stop applying and every
  undeclared rule continues to apply.
- Affected rules/contracts/baselines: all 32 formal v1.3.4 registry rules are currently `FROZEN`;
  S2-T19 v1.3 is already PASSED. The proposal therefore cannot be implemented by silently editing
  the registry, preregistration or a passed Manifest.
- Evidence required: completed implementation and repository-wide quality/traceability proof for
  the approved exemption schema, non-waivable set, default inheritance, unknown/wildcard/hash-drift
  rejection and formal-pipeline rejection.
- Owner/status: Muce / `RESOLVED`; CR-2026-033 / ADR-S2-012 are approved, the isolated framework is
  implemented, and repository-wide Ruff, strict mypy, strict Traceability, strict governance and
  678 tests passed. CR-2026-039 removes this OQ from the formal lifecycle gate. SRP-S2-001
  EX-001/002/003 remain expired for new Plan v1.3 runs; no exploratory output is promoted.
- Linked governance: [CR-2026-033](changes/CR-2026-033.md) and
  [ADR-S2-012](decisions/ADR-S2-012-special-research-point.md); first classified point:
  [SRP-S2-001](special_research_points/SRP-S2-001.md).

## OQ-S2-005 audit record

- Discovery/source: CR-2026-025 post-approval pre-Run audit on 2026-07-21; repository-wide search
  plus `git log --all` history search. ADR-S2-004, Stage 2 Plan v1.2, S2-T08 and the immutable T19
  Manifest reference approved formulas or safety constraints but do not contain executable values.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, ADR-S2-004 matching/quintile/invalidation contract,
  S2-T19 preregistration and S2-T15 v1.3. Stage 1 and accepted T10/T13/T14 evidence are unaffected.
- Evidence required: exact causal volatility formula and lookback; exact causal Trades-activity
  formula and lookback; UTC split/fold boundaries and assignment; exact purge/embargo duration;
  deterministic non-event control-anchor grid, exclusion and outcome-source rule; a new immutable
  preregistration version binding these values before an Authority or Run ID exists.
- Owner/status: Muce / `RESOLVED` at 2026-07-22T02:25:41Z.
- Linked governance: [ADR-S2-009](decisions/ADR-S2-009-conditional-baseline-v1.4.md),
  [CR-2026-026](changes/CR-2026-026.md), preserved
  [ADR-S2-004](decisions/ADR-S2-004-primary-research-definition.md) and
  [CR-2026-025](changes/CR-2026-025.md).

## OQ-S2-006 audit record

- Discovery/source: S2-T15 v1.4 mandatory read-only audit at `2026-07-22T03:00:27Z`, upstream
  binding Hash `a1f73a8f115262efa47f735593d4b142493e2baede551f0a193ff82ea7929f92`. The fixed T10
  Manifest declares distribution fields, but 4,752 `canonical_key_levels` receipts and 9,504
  PRICE/FLOW `market_episodes` receipts have an empty `distributions` tuple. A direct accepted
  Catalog read fails closed with `distribution digest mismatch for parameter_set_id`.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, Runtime V2 Catalog integrity, CR-2026-026 upstream binding
  and S2-T15 v1.4. T10 bytes and its historical PASS record remain immutable and are not rewritten.
- Evidence required: an append-only input binding that the current authority reader can validate,
  or an approved new read-only receiver contract defining an equally strict replacement check for
  the absent distribution digests; deterministic tests and a new PASS audit are required before
  Authority or bins.
- Owner/status: Muce / `RESOLVED` at `2026-07-22T03:24:18Z`;首份supplement Manifest Hash为
  `2ccb7d71…d71c`，新audit upstream binding Hash为`c964e890…a03`。最终代码干净提交和
  最终治理Hash重审计仍是Authority前置门。
- Linked governance: [CR-2026-027](changes/CR-2026-027.md),
  [CR-2026-026](changes/CR-2026-026.md) and
  [ADR-S2-009](decisions/ADR-S2-009-conditional-baseline-v1.4.md).

U-001～U-003 remain OPEN after Stage 0 final approval. They block only their recorded downstream execution/adaptation scopes and do not invalidate the offline Stage 0 v1.0 baseline.

All OPEN questions assigned to Stage 2 or later remain OPEN after Stage 1 final approval. They do not invalidate the Stage 1 v1.0 historical data baseline, but continue to block their recorded downstream research or execution scope.
