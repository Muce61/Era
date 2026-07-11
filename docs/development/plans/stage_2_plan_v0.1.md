# Stage 2：事件研究

## Metadata

- stage_id: S2
- plan_version: 0.1
- status: DRAFT
- created_from_spec_version: V1.3.4
- created_from_commit: 28bfb764f8286d2b4f23568a81f1233bb2b57b15
- dependencies: Stage 1 PASSED
- supersedes: NONE
- approved_by: NONE
- approved_at: NONE

## 1. 目标

建立“事件研究”所需的可审计能力，并只在本阶段证据边界内形成可验收产物。

## 2. 非目标

不开发完整实盘系统、执行适配器、真实订单状态机或后续 H3/F1 能力；不自动连接 Binance、批准 Stage 或修改 FROZEN 规则。研究阈值保持 BASELINE/RESEARCH，不得声明最优或升级为 FROZEN。

## 3. 规格来源

- 手册章节：§9、§11-16、附录D/J/L/N
- rule_id：EVENT-CONSUME-MARKET-EPISODE, STRATEGY-V1-PRICE-ONLY-HISTORICAL
- 数据契约：CanonicalKeyLevel, MarketEpisode, EntryIntent, path labels, cluster_id
- 系统不变量：以 `traceability/rules.yaml` 中 planned_stage 包含 S2 的 INV 条目为准
- Reason Code：以附录 I 和机器追踪中 planned_stage 包含 S2 的条目为准

## 4. 前置条件

本 Plan 经人工复核并转为 APPROVED；依赖基线有效；开始前重新读取代码、前一 Stage 验收和 OPEN_QUESTIONS。当前 DRAFT 不授权执行。

## 5. 输入基线

V1.3.4 规格基线 `spec-v1.3.4-final`、依赖 Stage 的 PASSED 基线及其 validation/manifest/hash；无依赖时仅使用规格基线。

## 6. 主要产物

本 Stage Task 定义的实现、测试、manifest、验证报告和追踪更新；所有路径在 Task 开始前复核。

## 7. 里程碑

契约确认 → 单能力 Task → 集成/研究验收 → 人工 Go/No-Go。任何里程碑均不自动切换状态。

## 8. Task 清单

- [S2-T01](../tasks/stage_2/S2-T01-canonicalkeylevel.md)：CanonicalKeyLevel
- [S2-T02](../tasks/stage_2/S2-T02-task.md)：关键位来源独立实现
- [S2-T03](../tasks/stage_2/S2-T03-task.md)：关键位归一化与仲裁
- [S2-T04](../tasks/stage_2/S2-T04-sweep-episode.md)：Sweep Episode
- [S2-T05](../tasks/stage_2/S2-T05-reclaim.md)：Reclaim
- [S2-T06](../tasks/stage_2/S2-T06-hold.md)：Hold
- [S2-T07](../tasks/stage_2/S2-T07-task.md)：价格启动门
- [S2-T08](../tasks/stage_2/S2-T08-flow.md)：Flow 门研究版本
- [S2-T09](../tasks/stage_2/S2-T09-marketepisode-id.md)：MarketEpisode ID 与消费规则
- [S2-T10](../tasks/stage_2/S2-T10-task.md)：候选事件全量生成
- [S2-T11](../tasks/stage_2/S2-T11-task.md)：路径提取
- [S2-T12](../tasks/stage_2/S2-T12-mfe-mae-time-to-activation.md)：MFE / MAE / Time-to-Activation
- [S2-T13](../tasks/stage_2/S2-T13-first-passage.md)：First Passage 标签
- [S2-T14](../tasks/stage_2/S2-T14-ambiguous.md)：AMBIGUOUS 处理
- [S2-T15](../tasks/stage_2/S2-T15-task.md)：条件随机基线
- [S2-T16](../tasks/stage_2/S2-T16-task.md)：安慰剂信号
- [S2-T17](../tasks/stage_2/S2-T17-task.md)：事件聚类
- [S2-T18](../tasks/stage_2/S2-T18-cluster-bootstrap.md)：Cluster Bootstrap
- [S2-T19](../tasks/stage_2/S2-T19-manifest.md)：预注册实验 Manifest
- [S2-T20](../tasks/stage_2/S2-T20-stage-2.md)：Stage 2 研究验收

## 9. 测试策略

按任务选择 unit、property、schema、integration、replay、fault injection、deterministic output、regression 或 forward validation；只报告实际运行结果。

## 10. Stage 验收门槛

满足手册第 30 节及附录 L 的 Stage 2 门槛；全部 Task 有审查和真实验证证据；追踪无未解释缺口；人工验收。

## 11. Go / No-Go 条件

GO 仅表示可提交人工审批进入下一 Stage。关键证据失败、出现 P0/裸仓风险、上游基线失效或 OPEN 问题阻塞时 NO-GO；不得用新增过滤器救援失败假设。

## 12. 风险

未来信息泄漏、证据等级混用、FROZEN 规则漂移、交易所事实变化、历史代理被误称真实执行，以及高耦合契约并发修改。

## 13. 开放问题

仅引用 `OPEN_QUESTIONS.md` 中解决阶段包含 Stage 2 的问题；不得在本计划中自行决策。

## 14. 重新规划触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 未来草案使用 DRAFT v0.2；当前 Stage 执行中则置 PLAN_REVISION_REQUIRED，产生新版本并重新人工批准。

## 15. 失效触发器

上游 Stage REOPENED、输入 manifest/hash/commit 改变、验收证据被推翻或 L2-L4 Change Request 获批时，本 Stage 及受影响下游标记 INVALIDATED。

## 16. 重开条件

失效原因有书面决定、修订 Plan 已批准、回归范围明确且所需输入基线重新建立后，才可 REOPENED。

## 17. 回滚与恢复

撤销未批准产物引用并保留审计历史；不得覆盖旧 Plan/结果。恢复从最后有效基线开始，重新执行受影响验证。

## 18. 预期基线标签

`stage-2-vX.Y-passed`（仅 PASSED 且人工批准后创建；本次不得创建）。

## 19. 变更历史

- 2026-07-12：v0.1，依据 V1.3.4 创建，状态 DRAFT，未执行。
