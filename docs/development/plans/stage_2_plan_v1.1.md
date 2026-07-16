# Stage 2：事件研究

## Metadata

- stage_id: S2
- plan_version: 1.1
- status: DRAFT
- created_from_spec_version: V1.3.4
- created_from_commit: c984fb4
- dependencies: Stage 1 PASSED + Stage 1 data baseline ESTABLISHED
- supersedes: stage_2_plan_v1.0
- approved_by: NONE
- approved_at: NONE

## 1. 目标

建立BTCUSDT与ETHUSDT严格分离、可扩展但不绕过规格边界的事件研究能力：从已批准的`stage1-trades-v2`与Contract Price数据生成CanonicalKeyLevel、Sweep/Reclaim/Hold、价格与Flow门、MarketEpisode、路径标签、条件基线、安慰剂、聚类与cluster bootstrap证据；通过版本化`ResearchSetup`、`ContextModel`和注册表，使未来适合高杠杆研究的新行情上下文可以独立接入。Stage 2是事件增量的真实Go/No-Go门，不证明真实执行收益。

## 2. 非目标

不实现H3成本/PnL、历史真实滑点、执行适配、下单、状态机、测试网、实盘、10 USDT或复利；不开发完整生产策略；不把TARGET_TOUCHED/TARGET_FIRST称为ROUND_SUCCESS；不把BASELINE/RESEARCH参数写成最优或FROZEN；不借助插件接口引入做空、突破追涨或其他未获V1.3.4批准的策略家族。

## 3. 规格来源

- V1.3.4 §3、§9、§11-16、§25、§27、§30、附录C/D/J/L/N。
- FROZEN：`EVENT-CONSUME-MARKET-EPISODE`、`STRATEGY-V1-PRICE-ONLY-HISTORICAL`、`INV-005`、`INV-011`、`INV-013`、`GATE-STAGE-2`。
- RESEARCH契约：CanonicalKeyLevel、MarketEpisode、EntryIntent研究字段、cluster_id、预注册G1 Context函数。
- L2输入决定：CR-2026-001、ADR-2026-001 Trade Identity v2。

## 4. 前置条件

以下条件全部满足前，本Plan和所有Task不得批准或执行：S1-T14 PASS；S1-T15 PASS；用户最终批准Stage 1；Stage 1 data baseline登记且VALID；published manifest/catalog/schema/hash可读；Stage 2 v1.1重新核对；OQ-S2-001/002得到人工决定；用户批准Stage 2。当前Stage 1运行期间只允许维护本DRAFT文档。

## 5. 输入基线

- 仅消费最终批准的Stage 1 published baseline，不消费raw、staging、checkpoint或未发布分区。
- Trades schema固定为`stage1-trades-v2`；唯一事实键为`(instrument, canonical_trade_id)`，稳定顺序为`(ts_event_ns, venue_trade_id, canonical_trade_id)`。
- 同venue ID不同canonical事实全部保留；冲突标签进入质量/敏感性报告，不得按venue ID折叠或静默过滤。
- H1只消费Contract Price；H2消费Trades事实与aggressor side。BTC/ETH分开配置、运行、报告、聚类和验收，禁止混合训练/统计。
- `ResearchSetup`固定事件家族、门集合和标签口径；`ContextModel`只能以因果、预注册特征输出上下文标签或`ALLOW_LONG`，不得更改MarketEpisode消费语义。当前唯一可执行setup为`KEY_LOW_SWEEP_RECLAIM_HOLD_V1`；未来新上下文必须独立版本化和预注册。
- 每次运行固定Stage 1 baseline tag/commit、dataset version、manifest hash、logical data hash、schema hash和时间覆盖。

## 6. 主要产物

版本化研究契约与setup/context注册表、fixture级确定性实现、预注册manifest、BTC/ETH独立候选事件与路径数据、标签/基线/安慰剂/聚类/bootstrap报告、事件说明图与真实证据卡、实验台账、validation与Traceability。大型研究产物只写经批准的Stage 2外部工作根；仓库只保存代码、配置、fixture、轻量manifest/report/validation。

## 7. 里程碑与执行顺序

`T01 输入/契约/注册表 → T19 预注册 → T02 → T03 → T04 → T05 → T06 → T09 → T07`。T08在T06后独立构建V1_FLOW；T10在T07/T09及已冻结manifest后通过注册表生成全量候选，分别运行V1_PRICE和V1_FLOW。之后`T11 → T12/T13 → T14 → T15/T16/T17 → T18 → T21事件说明图/证据卡 → T20`。不得因编号顺序把T19延后到观察结果之后。

## 8. Task 清单与数据门

| Task | 能力 | Fixture可验收 | 依赖published全量证据 |
| --- | --- | --- | --- |
| S2-T01 | Stage 2输入契约、ResearchSetup/ContextModel注册表与CanonicalKeyLevel schema | 是 | baseline绑定需全量 |
| S2-T19 | 预注册实验Manifest/台账 | 是 | 必须绑定baseline hash |
| S2-T02 | 三类关键位来源独立实现 | 是 | 参数地形需全量 |
| S2-T03 | 关键位归一化、合并与仲裁 | 是 | U-007证据需全量 |
| S2-T04 | Sweep episode | 是 | 事件频率需全量 |
| S2-T05 | Reclaim | 是 | 参数地形需全量 |
| S2-T06 | Hold/失效 | 是 | 参数地形需全量 |
| S2-T09 | MarketEpisode身份、消费与re-arm | 是 | 消费审计需全量 |
| S2-T07 | G0-G3价格启动门 | 是 | 通过率需全量 |
| S2-T08 | G4 Flow研究变体 | 是 | 仅H2全量证据 |
| S2-T10 | BTC/ETH候选事件全量生成 | 否 | 是 |
| S2-T11 | 路径提取 | 是 | 正式产物需全量 |
| S2-T12 | MFE/MAE/Time-to-Activation | 是 | 是 |
| S2-T13 | First Passage标签 | 是 | 是 |
| S2-T14 | AMBIGUOUS与H1上下界 | 是 | 是 |
| S2-T15 | 条件随机基线 | 方法可 | 是 |
| S2-T16 | 安慰剂信号 | 方法可 | 是 |
| S2-T17 | 事件聚类 | 方法可 | 是 |
| S2-T18 | Cluster Bootstrap/CI | 方法可 | 是 |
| S2-T21 | 事件说明图与真实事件证据卡 | 模板可 | 正式证据卡需全量 |
| S2-T20 | Stage 2研究验收 | 否 | 是 |

## 9. 测试策略

每个实现Task运行定向unit/property/schema/deterministic测试和`uv run python scripts/run_quality_gate.py`。重点覆盖无右侧确认、UTC边界、同时间v2稳定顺序、输入打乱不改变输出、BTC/ETH与setup/context隔离、缺口硬门、冲突事实不丢失、同episode不重复消费、AMBIGUOUS不被删除、purge/embargo、无未来泄漏、manifest先于结果且不可覆盖。注册表必须证明fixture dummy setup可接入而核心编排器无需修改，未知/未批准setup拒绝运行。事件图必须由规范事件记录确定性渲染，示意图带`ILLUSTRATIVE_FIXTURE`水印，真实图携带run/data/config/hash且不得伪造Bid/Ask、执行、成本或滑点。全量研究CLI必须由T19冻结后写入相应Task新版本，当前不得虚构。

## 10. Stage 验收门槛

Stage 2全部Task PASS；主假设/主标的/主标签/参数域/匹配放宽层级/失败线预注册；宽松候选总体和所有尝试版本完整入账；BTC/ETH及setup/context分别报告；独立cluster数与CI达到预注册门或明确NO-GO；条件随机基线与安慰剂比较完整；多时期方向一致性、事件频率、日历等待、参数邻域、AMBIGUOUS/H1上下界完整；注册表扩展/隔离门通过；事件说明图和真实证据卡可复现、可追溯且不伪造能力；无未来泄漏；不输出H3/F1或真实收益结论。

## 11. Go / No-Go条件

GO仅允许请求Stage 3人工审批。事件相对条件基线无稳定增量、cluster/CI门失败、多时期方向不一致、安慰剂同样有效、结果依赖单一最佳参数、数据/manifest/hash失效、BTC/ETH混合或泄漏时NO-GO。禁止验证失败后添加过滤器救援同一实验。

## 12. 风险

右侧确认、观察后改manifest、venue ID误作主键、冲突事实静默丢弃、H1/H2字段混用、同episode被不同setup/context重复消费、相关episode伪装独立样本、历史标签误称真实成交、生成式图片或示意数据冒充真实事件证据、全量产物写入Git。

## 13. 开放问题

- OQ-S2-001：Stage 2外部可写工作根、保留/发布布局及空间门。
- OQ-S2-002：主标的、主假设、主标签、主匹配方案和U-007/U-008/U-009/U-011的预注册参数域/失败线。
- U-007～U-011保持RESEARCH；本Plan不代替人工选择。Stage 1尚未产生data baseline也是硬阻塞。

## 14. 重新规划触发器

Stage 1 schema/dataset/manifest/hash变化；Trade Identity或排序变化；事件、标签、匹配、聚类、purge/embargo、参数域、主指标、代码/config hash变化；上游Stage重开。

## 15. 失效触发器

任何输入data hash、schema hash、git commit、config/manifest hash、事件定义、标签、聚类或匹配放宽规则变化，使相关候选、标签、报告、CI和Stage evidence标记INVALIDATED并重建。

## 16. 重开条件

Stage 1 baseline失效；官方checksum导致上游分区重建；锁定研究发现泄漏/身份错误；关键研究方法经L3 CR修改；Stage 2验收证据不可复现。

## 17. 回滚与恢复

代码按Task独立提交回滚；实验产物append-only，以run_id和hash隔离；失败/旧实验保留并标INVALIDATED，不覆盖或删除；恢复只消费同一有效baseline与manifest。

## 18. 预期基线标签

仅人工最终批准后创建Stage 2 experiment/stage baseline；本DRAFT不创建tag、不批准Task、不写研究产物。

## 19. 变更历史

- 2026-07-12：v0.1，初始20 Task草案。
- 2026-07-14：v1.0 DRAFT，按Stage 1 Trade Identity v2与真实代码结构重新规划；T19前置；明确fixture/full-data边界和Stage 1最终门；未执行任何Task。
- 2026-07-14：v1.1 DRAFT，增加可扩展ResearchSetup/ContextModel注册表与S2-T21事件说明图/真实证据卡；当前仍只允许V1.3.4 FROZEN事件家族；未执行任何Task。
