# S2-T13：First Passage 标签

## Metadata

- task_id: S2-T13
- task_version: 1.3
- status: FULL OUTPUT VERIFIED / AWAITING HUMAN ACCEPTANCE
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T11 PASS
- supersedes: task_version 1.2
- approved_by: Muce
- approved_at: 2026-07-21T10:41:50Z

## 1. 目标

规划并交付“First Passage 标签”这一单一能力，使其可独立测试、审查和回滚。

## 2. 背景

该能力属于 Stage 2“事件研究”，必须保持 V1.3.4 的证据等级、状态语义和人工阶段门。

## 3. 规格来源

- 手册章节：§9、§11-16、附录D/J/L/N
- rule_id：EVENT-CONSUME-MARKET-EPISODE, STRATEGY-V1-PRICE-ONLY-HISTORICAL
- 数据契约：CanonicalKeyLevel, MarketEpisode, EntryIntent, path labels, cluster_id
- 系统不变量与 Reason Code：执行前从 `traceability/rules.yaml` 解析本 Task 的精确映射

## 4. 前置条件

Stage 2 Plan v1.2 与本 Task 均已人工批准；依赖项有真实 validation；适用 OPEN QUESTION 不阻塞；工作区和Stage 1 Baseline v1.0已核验。

## 5. 允许范围

只实现并验证“First Passage 标签”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

## 6. 禁止事项

禁止越过 Stage、扩大交易风险、连接未授权 API、写入密钥、修改正式规格、把 BASELINE/RESEARCH 宣称最优或 FROZEN、自动批准或继续下一 Task。

## 7. 允许修改的路径

以第21节的v1.0精确路径为准；未列路径禁止修改。

## 8. 禁止修改的路径

`docs/spec/**`、其他未批准 Stage 的实现路径、真实密钥/账户文件、历史基线和已通过的不可覆盖验证产物。

## 9. 输入

规格基线、Stage Plan、依赖 Task 的已验证产物、适用配置/manifest/hash；执行时记录精确版本。

## 10. 交付物

该能力的最小实现或研究产物、对应测试、validation/manifest、TRACEABILITY 与 `rules.yaml` 状态更新；本 DRAFT 本身不产生实现。

## 11. 实现要求

先列出适用 rule_id、允许/禁止路径和计划；使用 Decimal/时间/证据字段等已批准契约；失败动作必须唯一且可审计；不得引入未来能力。

## 12. 测试要求

覆盖正常、边界、失败和确定性场景；涉及 FROZEN/INV 时必须运行其映射测试；历史、代理、测试网与真实证据必须分级报告。

## 13. 验收标准

目标单一完成；测试真实运行且通过；无未解释追踪缺口；回滚可执行；未完成项和未运行测试如实报告；由人工验收。

## 14. 必须运行的命令

以第21节的定向pytest命令和现有统一质量门为准；全量研究CLI必须由S2-T19预注册后通过Task新版本冻结。

## 15. 完成报告格式

规则/范围 → 修改文件 → 实际命令与结果 → 追踪更新 → 未完成/开放问题 → Go/No-Go 建议；不得自动继续。

## 16. 回滚方式

按独立提交撤销本 Task 的实现与注册引用，保留 manifest、审计和失败证据；若契约已被下游消费，先执行失效传播。

## 17. 开放问题

只记录影响本 Task 的 U/CR/ADR；需要改变风险、数据边界、执行语义或 Binance 能力判断时停止并请求人工决定。

## 18. 变化触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 触发 task_version 递增和重新审批。

## 19. 失效条件

依赖 Task/Stage 重开、输入哈希变化、映射规则变化、验收测试被推翻或产物不可复现时标记 INVALIDATED，不得继续作为有效证据。

## 20. 变更历史

- 2026-07-12：v0.1，依据 Stage 2 Plan v0.1 创建，状态 DRAFT，未执行。
- 2026-07-14：v1.0，按Stage 1 Trade Identity v2与Stage 2 Plan v1.0重规划；状态DRAFT，未执行。
- 2026-07-14：v1.1，加入可扩展研究setup架构与事件说明图规划；状态DRAFT，未执行。
- 2026-07-16：v1.2，按Plan v1.2收口分组、前置S2-T19并修订DAG；状态DRAFT，未执行。
- 2026-07-21：Muce以“开始T13”批准v1.2；完成严格first-passage合同和fixture能力，
  定向测试与统一质量门通过。现有v1.2未冻结正式全量CLI，Web UI允许范围也未覆盖T13；
  提交CR-2026-023后停止，不批准T14或Stage 3。
- 2026-07-21：Muce批准CR-2026-023及v1.3最小全量合同；允许固定全量CLI、只读
  Authority/Run/Manifest/Catalog/Verify与Web UI自动识别。T14及Stage 3仍未批准。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：产生TARGET_FIRST/STOP_FIRST/EXPIRED/AMBIGUOUS历史标签；TARGET_TOUCHED不得替代ROUND_SUCCESS。
- 允许修改路径：`src/era100x/research/stage_2/labels/first_passage/`、`tests/research/stage_2/labels/first_passage/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/labels/first_passage -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：目标先/止损先/过期/同秒、状态生效顺序、H1/H2差异和禁止ROUND_SUCCESS字段测试通过。
- 证据模式：\`FIXTURE_CAPABILITY + FULL LABELS\`。无论fixture能力是否可验收，Stage 1最终PASSED与VALID data baseline之前均不得执行本Task。

## 22. S2-T13 v1.2最小实现合同

- 只研究LONG历史价格路径；H1使用Contract bar，H2使用Trade，BTC与ETH保持分离。
- 目标域固定为20/30/40/50/70/100 bp；止损域固定为15/20/25/30/35 bp；
  T1/T2/T3/T4 horizon固定为60/180/300/600秒，与S2-T19预注册完全一致。
- 窗口是UTC event-time左闭右开；H2顺序固定为
  `(ts_event_ns, venue_trade_id, canonical_trade_id)`。
- H1同一事件同时触及目标和止损时，原始标签为`AMBIGUOUS`，并记录手册要求的
  adverse-first主处理为`STOP_FIRST`；本Task不计算T14的乐观/悲观上下界。
- 在首个可见决策前存在缺口、没有任何观察或窗口提前截断时，不得虚构`EXPIRED`；
  必须保守标记`AMBIGUOUS`并保留来源质量、缺口、歧义和MarketEpisode lineage。
- 只有原始标签`TARGET_FIRST`才令`strict_target_first=true`。`TARGET_TOUCHED`或
  `TARGET_FIRST`均不得描述为`ROUND_SUCCESS`、PnL、return或真实执行结果。
- v1.2只批准fixture级独立能力。正式全量CLI、Authority/Manifest/Catalog发布和Web UI
  自动识别必须先批准CR-2026-023及相应v1.3合同。

## 23. S2-T13 v1.3正式全量合同

- 唯一CLI为`uv run python scripts/run_stage2_first_passage.py
  {preflight,run,resume,verify}`。`preflight`不得创建Run ID；Authority必须绑定实现commit、
  S2-T11 Snapshot、S2-T10参考价事实、只读恢复overlay、BTC/ETH计数、参数域和资源门。
- 每个MarketEpisode只使用其已冻结的`time_combination_id`及对应T1/T2/T3/T4窗口；不得
  把短路径外推为更长horizon。全体Episode必须覆盖四种timing。
- 对每个Episode分别生成H1与H2行；每行按target-major、stop-minor稳定顺序完整保存
  `6 targets × 5 stops = 30`个分类。固定532,708 Episodes对应1,065,416条路径行和
  31,962,480个分类。
- H1/H2、BTC/ETH、原始标签与保守主标签必须分离。H1同事件双触达原始为
  `AMBIGUOUS`、主处理为`STOP_FIRST`；不得生成S2-T14上下界。
- 运行按BTC/ETH独立生成，失败Run保持未发布且不可恢复；成功结果通过同卷原子发布，
  Manifest/Catalog/行哈希/文件哈希自校验。Verify只读遍历全部行，核对30组合、标签分布、
  lineage、历史证据边界与禁止字段。
- Web UI只从最新合法Authority、Run、Catalog、Verify、repository summary与validation
  联合证据推导状态；较新的失败或无效Run不得回退，HTML不得预置PASSED。
- 允许新增/修改`labels/first_passage/full_run.py`、`scripts/run_stage2_first_passage.py`、
  对应测试、S2-T13治理/summary，以及进度server、HTML和现有进度测试。其他范围不变。
