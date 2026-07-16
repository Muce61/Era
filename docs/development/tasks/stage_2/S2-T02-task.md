# S2-T02：关键位来源独立实现

## Metadata

- task_id: S2-T02
- task_version: 1.2
- status: APPROVED
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T01 PASS
- supersedes: task_version 1.1
- approved_by: Muce
- approved_at: 2026-07-16T14:33:04+08:00

## 1. 目标

规划并交付“关键位来源独立实现”这一单一能力，使其可独立测试、审查和回滚。

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

只实现并验证“关键位来源独立实现”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

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

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：分别实现rolling_low_1m、rolling_low_5m、range_low；来源之间不得共享右侧状态或提前仲裁。
- 允许修改路径：`src/era100x/research/stage_2/key_levels/sources/`、`tests/research/stage_2/key_levels/sources/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/key_levels/sources -q\`；\`uv run python scripts/run_quality_gate.py\`。只使用S2-T19锁定参数做fixture验证；全量候选运行唯一由S2-T10负责。
- 验收标准：三来源逐一通过因果性/property/边界测试；未来数据扰动不改变历史输出；BTC/ETH分别验证。
- 证据模式：\`FIXTURE_CAPABILITY\`；不得在本Task生成全量参数地形或候选数据。
