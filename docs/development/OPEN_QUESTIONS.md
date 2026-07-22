# Open Questions

## OQ-S2-009 — Does a public venue Trade ID discontinuity prove an H2 source gap?

- status: RESOLVED BY CR-2026-031 AND ADR-S2-010 / AUDIT GATES REMAIN
- discovered_by: read-only review of P3/F3 T13/T15 source-gap outcomes
- affected_scope: Stage 1 quality semantics; T11 H2 paths; T12 path metrics; T13 first-passage;
  T14 ambiguity; T15 conditional baseline
- proposed_resolution: CR-2026-031 + ADR-S2-010
- evidence: Official checksum-bound 2026 archives contain 800,104,791 BTC and 1,255,571,071 ETH
  public Trade rows while skipping 1,170,244 and 1,811,220 numeric venue IDs respectively. All
  184 daily partitions per instrument exist. The skipped-ID fraction is about 0.14%, but the
  legacy any-discontinuity rule makes 703/705 BTC and 1,148/1,151 ETH unpublished P3/F3 primary
  T2 rows source-gap AMBIGUOUS.
- decision_needed: decide whether an uncorroborated numeric ID jump remains a hard semantic gap or
  becomes a reportable anomaly/sensitivity dimension, and define the independent evidence needed
  for `VERIFIED_PUBLIC_TRADE_GAP`.
- decision: Muce approved CR-2026-031 and ADR-S2-010 at `2026-07-22T15:39:25Z`. A bare numeric
  venue-ID jump is an uncorroborated anomaly, not sufficient proof of a missing public Trade.
- remaining_gates: the read-only audit, affected-version scope, reason-code mapping, invalidation
  graph and successor plan require explicit evidence and approval before implementation.
- boundary: no evidence rewrite, synthetic Trade, Authority, Run or publication under the revised
  semantic before the remaining gates pass. Existing sealed evidence remains immutable.

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

New questions must record discovery/source, affected rules/contracts/baselines, evidence required, owner, status, and linked ADR/CR. No unresolved question may be answered by assumption.

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

## OQ-S2-009 audit record

- Discovery/source: read-only diagnosis of sealed T13 H2 labels and the unpublished T15
  P3/F3 primary selection on 2026-07-22. Stage 1 Catalogs show complete daily partitions and
  checksum-bound official public Trades, while their exchange-provided numeric IDs contain many
  small discontinuities. Binance's public source description identifies the field and endpoint but
  does not promise integer continuity.
- Affected rules/contracts/baselines: `EVENT-CONSUME-MARKET-EPISODE`,
  `STRATEGY-V1-PRICE-ONLY-HISTORICAL`, ADR-2026-001 Trade Identity v2, S1-T07 quality semantics,
  T11 H2 path quality, T12 inherited path-metric quality, T13 source-gap classification, T14
  ambiguity bounds and T15 upstream label binding. Stage 1 raw facts and all accepted sealed
  evidence remain immutable.
- Evidence required: instrument/year/month discontinuity inventory; archive/checksum and
  Catalog/object reconciliation; range-size and adjacent-event-time distributions; explicit
  separation of uncorroborated ID jumps, verified missing public facts and source-integrity
  failures; legacy-versus-proposed P1/P2/P3 and F0-F3 impact; approved official cross-source proof
  if any skipped ID is promoted to a verified public-Trade gap.
- Owner/status: Muce / `RESOLVED` at `2026-07-22T15:39:25Z`; read-only audit authorized, code and
  successor evidence remain blocked by the recorded gates.
- Linked governance: [CR-2026-031](changes/CR-2026-031.md),
  [ADR-S2-010](decisions/ADR-S2-010-venue-trade-id-discontinuity.md) and preserved
  [ADR-2026-001](decisions/ADR-2026-001-trade-identity-v2.md).

U-001～U-003 remain OPEN after Stage 0 final approval. They block only their recorded downstream execution/adaptation scopes and do not invalidate the offline Stage 0 v1.0 baseline.

All OPEN questions assigned to Stage 2 or later remain OPEN after Stage 1 final approval. They do not invalidate the Stage 1 v1.0 historical data baseline, but continue to block their recorded downstream research or execution scope.
