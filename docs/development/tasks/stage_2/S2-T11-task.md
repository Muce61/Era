# S2-T11：路径提取

## Metadata

- task_id: S2-T11
- task_version: 1.3
- status: PASSED
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T10 PASS
- supersedes: task_version 1.2
- approved_by: Muce
- approved_at: 2026-07-21T02:19:21Z
- accepted_by: Muce
- accepted_at: 2026-07-21T02:47:07Z

## 1. 目标

规划并交付“路径提取”这一单一能力，使其可独立测试、审查和回滚。

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

只实现并验证“路径提取”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

## 6. 禁止事项

禁止越过 Stage、扩大交易风险、连接未授权 API、写入密钥、修改正式规格、把 BASELINE/RESEARCH 宣称最优或 FROZEN、自动批准或继续下一 Task。

## 7. 允许修改的路径

以第21节和第22节的精确路径为准；未列路径禁止修改。

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

以第21节的定向pytest命令和现有统一质量门为准；全量研究CLI由第22节冻结。

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
- 2026-07-21：v1.3，CR-2026-021获人工批准；冻结全量路径提取CLI、切片索引输出、恢复、验证和只读输入边界。
- 2026-07-21：正式Run、只读Verify、完整质量门和自动UI通过后，Muce人工验收并收尾；状态PASSED。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：按exchange event time及v2稳定顺序提取H1/H2路径，保留来源、质量、歧义和episode lineage。
- 允许修改路径：`src/era100x/research/stage_2/paths/extraction/`、`tests/research/stage_2/paths/extraction/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/paths/extraction -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：UTC边界、窗口截断、同时间排序、冲突事实、缺口、input shuffle与lineage测试通过；正式产物需全量。
- 证据模式：\`FIXTURE_CAPABILITY + FULL OUTPUT\`。无论fixture能力是否可验收，Stage 1最终PASSED与VALID data baseline之前均不得执行本Task。

## 22. S2-T11 v1.3 全量执行契约（CR-2026-021）

- 唯一CLI：`uv run python scripts/run_stage2_path_extraction.py {preflight,run,resume,verify}`。
- 固定输入：S2-T10 Run `stage2-g1-v2-b-20260720T111704Z-9c4b7c423a04` 的已发布
  snapshot `df15b9cbb208a6f921b3a68bee24be44f77e83eb2c8ac1582ef942b108708d33`，以及其绑定的
  Stage 1 v1.0 Trades logical hashes；全部只读。
- 路径窗口：从 `MarketEpisode.available_at_ts` 开始，按其已注册 `time_combination_id`
  使用 T1/T2/T3/T4 的 60/180/300/600 秒 horizon；UTC event ns、左闭右开，并在固定
  source end 截断。
- 正式 H1/H2 输出采用逐 episode 的可精确还原切片索引：H1 引用已发布 Contract Price
  日分区及语义哈希；H2 引用 Stage 1 Trades 文件 byte/logical hash、row-group ordinal 和
  event bounds。切片内的 H2 身份与稳定顺序仍严格为 `(instrument, canonical_trade_id)` 和
  `(ts_event_ns, venue_trade_id, canonical_trade_id)`；引用不会改变、过滤或按 venue ID 去重事实。
- BTCUSDT 与 ETHUSDT 分开写入、计数和哈希；PRICE/FLOW lineage 均保留，绝不池化研究结论。
- 新输出根：`/Volumes/FuckingLife/era100x_stage2/runs/<s2t11-run-id>/`，包含独立
  `staging/published/manifests/reports/logs/tmp`；不得把固定 S2-T10 Run 作为输出根。
- `preflight` 在创建 Run ID 前冻结输入、代码、配置、输出策略和空间门；`run` 只创建唯一新
  Run；`resume` 要求哈希完全一致并逐文件验证已完成输出；`verify` 只读且拒绝缺失、符号链接、
  哈希漂移、冲突或覆盖。
- 允许新增：`scripts/run_stage2_path_extraction.py`、`tests/scripts/test_stage2_path_extraction.py`、
  本Task直接相关 manifest/config/summary，以及CR-2026-021批准的已有实现、测试、validation、
  traceability和只读UI可观测性路径。
- 输出仅限 episode path index、H1/H2 path slices、source quality/gap/ambiguity、lineage、catalog、
  manifest、receipt和quality report；不计算或输出 S2-T12 及以后指标。
