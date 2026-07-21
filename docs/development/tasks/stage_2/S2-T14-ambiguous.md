# S2-T14：AMBIGUOUS 处理

## Metadata

- task_id: S2-T14
- task_version: 1.3
- status: APPROVED / IN_PROGRESS
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T13 PASS
- supersedes: task_version 1.2
- approved_by: Muce
- approved_at: 2026-07-21T13:07:08Z

## 1. 目标

规划并交付“AMBIGUOUS 处理”这一单一能力，使其可独立测试、审查和回滚。

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

只实现并验证“AMBIGUOUS 处理”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

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
- 2026-07-21：Muce以“开始t14”批准v1.2 fixture能力，从已人工验收的S2-T13提交
  `65a547386ca400c3b581bcf44c51ac1dacc4d764`独立执行。正式全量分布CLI、外部Run和Web UI
  自动识别不在v1.2允许范围内，必须先批准最小范围修订。
- 2026-07-21：v1.2纯fixture边界、分布汇总、hash和隔离测试通过；定向15项及统一质量门
  523项全部PASS。因全量分布与Web UI仍缺授权，提交CR-2026-024并停止，不启动正式Run
  或S2-T15。
- 2026-07-21：Muce以`webui接入t14，然后收尾t14`批准CR-2026-024与v1.3最小范围：
  只增加正式全量分布CLI、追加式Authority/Run/Manifest/Catalog/Verify证据、轻量仓库摘要和
  只读Web UI自动识别；不授权S2-T15+、H3、基线、placebo、聚类、bootstrap或Stage 3。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：无法由数据粒度确定顺序时必须保留AMBIGUOUS；H1主结果不利先发生并另报乐观上界。
- 允许修改路径：`src/era100x/research/stage_2/labels/ambiguity/`、`tests/research/stage_2/labels/ambiguity/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/labels/ambiguity -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：同秒双触及、无序事件、H1上下界、H2可判定路径、禁止删除/重分类歧义测试通过。
- 证据模式：\`FIXTURE_CAPABILITY + FULL DISTRIBUTION\`。无论fixture能力是否可验收，Stage 1最终PASSED与VALID data baseline之前均不得执行本Task。

## 22. S2-T14 v1.2最小歧义边界合同

- 输入只能是已验证的S2-T13 `HistoricalFirstPassageLabel`；输入hash不匹配时失败关闭，
  不得修改、删除或重新分类原始标签。
- Primary固定把`AMBIGUOUS`按失败处理；条件结果必须从分母排除`AMBIGUOUS`；理论上界将
  `AMBIGUOUS`按成功计入。三种口径必须同时保留，不得用条件结果或理论上界替代Primary。
- H1同事件同时触及目标和止损时，悲观路径标签为`STOP_FIRST`、乐观路径标签为
  `TARGET_FIRST`，但原始标签仍是`AMBIGUOUS`。
- 缺口、无观察或窗口截断等未解决来源歧义只能产生0/1成功指标边界，不得虚构悲观或
  乐观路径顺序标签。
- `TARGET_FIRST`、`STOP_FIRST`和`EXPIRED`等可判定路径的上下界必须收敛到原标签；H2
  仍使用S2-T13的V2稳定顺序，不产生同事件伪歧义。
- 分布必须按BTC/ETH、H1/H2、parameter set、target、stop和timing分别汇总；Primary率、
  排除歧义的条件率和理论上界率均由原始计数精确推导，输入shuffle不得改变hash。
- v1.3按已批准CR-2026-024增加全量分布与只读自动观测，但仍不得输出PnL、return、
  ROUND_SUCCESS、live execution、条件基线、placebo、cluster、bootstrap或Stage 2 Go/No-Go。
- 全量Run必须在创建Run ID前绑定已验收S2-T13的Authority、Run、Snapshot、Manifest、
  Catalog、代码版本、输出hash与计数；逐条扫描全部31,962,480个分类，但只发布紧凑分布，
  不复制或改写上游逐行分类。
- 最新合法Run的状态由Web UI只读自动投影；HTML不得预置PASSED，失败、篡改、symlink或
  更新但无效的证据必须失败关闭且不得回退到更旧PASS。
