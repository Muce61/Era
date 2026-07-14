# Stage 3：H3 成本与执行压力代理

## Metadata

- stage_id: S3
- plan_version: 0.1
- status: DRAFT
- created_from_spec_version: V1.3.4
- created_from_commit: 28bfb764f8286d2b4f23568a81f1233bb2b57b15
- dependencies: Stage 2 PASSED
- supersedes: NONE
- approved_by: NONE
- approved_at: NONE

## 1. 目标

建立“H3 成本与执行压力代理”所需的可审计能力，并只在本阶段证据边界内形成可验收产物。

## 2. 非目标

不输出真实实盘收益或 `unconditional_live_round_success_probability`；H3 只能形成附带成交、部分成交、成本和延迟假设的 `conditional_round_success_probability`。不连接 Binance、批准 Stage 或冻结研究参数。

## 3. 规格来源

- 手册章节：§6、§10.4、§12、§14-16、§21、附录F/J/L/N
- rule_id：RESEARCH-H3-CONDITIONAL-ROUND-PROB, PNL-NO-DOUBLE-SLIPPAGE, FILL-CONTINUE-BY-REACHABILITY
- 数据契约：CostScenario, LatencyScenario, proxy fills, PnL and Round proxy outputs
- 系统不变量：以 `traceability/rules.yaml` 中 planned_stage 包含 S3 的 INV 条目为准
- Reason Code：以附录 I 和机器追踪中 planned_stage 包含 S3 的条目为准

## 4. 前置条件

本 Plan 经人工复核并转为 APPROVED；依赖基线有效；开始前重新读取代码、前一 Stage 验收和 OPEN_QUESTIONS。当前 DRAFT 不授权执行。

## 5. 输入基线

V1.3.4 规格基线 `spec-v1.3.4-final`、依赖 Stage 的 PASSED 基线及其 validation/manifest/hash；无依赖时仅使用规格基线。

## 6. 主要产物

本 Stage Task 定义的实现、测试、manifest、验证报告和追踪更新；所有路径在 Task 开始前复核。

## 7. 里程碑

契约确认 → 单能力 Task → 集成/研究验收 → 人工 Go/No-Go。任何里程碑均不自动切换状态。

## 8. Task 清单

- [S3-T01](../tasks/stage_3/S3-T01-costscenario.md)：CostScenario 数据契约
- [S3-T02](../tasks/stage_3/S3-T02-latencyscenario.md)：LatencyScenario
- [S3-T03](../tasks/stage_3/S3-T03-proxy-entry-fill.md)：Proxy Entry Fill
- [S3-T04](../tasks/stage_3/S3-T04-proxy-exit-fill.md)：Proxy Exit Fill
- [S3-T05](../tasks/stage_3/S3-T05-historical-proxy-net-pnl.md)：Historical proxy_net_pnl
- [S3-T06](../tasks/stage_3/S3-T06-task.md)：路径依赖退出回放引擎
- [S3-T07](../tasks/stage_3/S3-T07-task.md)：初始止损代理
- [S3-T08](../tasks/stage_3/S3-T08-activation.md)：Activation 与保护代理
- [S3-T09](../tasks/stage_3/S3-T09-task.md)：时间止损代理
- [S3-T10](../tasks/stage_3/S3-T10-task.md)：部分成交情景
- [S3-T11](../tasks/stage_3/S3-T11-required-target-bps.md)：required_target_bps
- [S3-T12](../tasks/stage_3/S3-T12-task.md)：条件单轮成功概率
- [S3-T13](../tasks/stage_3/S3-T13-task.md)：成本敏感性
- [S3-T14](../tasks/stage_3/S3-T14-task.md)：延迟敏感性
- [S3-T15](../tasks/stage_3/S3-T15-h3.md)：H3 报告
- [S3-T16](../tasks/stage_3/S3-T16-stage-3.md)：Stage 3 验收

## 9. 测试策略

按任务选择 unit、property、schema、integration、replay、fault injection、deterministic output、regression 或 forward validation；只报告实际运行结果。

## 10. Stage 验收门槛

满足手册第 31 节及附录 L 的 Stage 3 门槛；全部 Task 有审查和真实验证证据；追踪无未解释缺口；人工验收。

## 11. Go / No-Go 条件

GO 仅表示可提交人工审批进入下一 Stage。关键证据失败、出现 P0/裸仓风险、上游基线失效或 OPEN 问题阻塞时 NO-GO；不得用新增过滤器救援失败假设。

## 12. 风险

未来信息泄漏、证据等级混用、FROZEN 规则漂移、交易所事实变化、历史代理被误称真实执行，以及高耦合契约并发修改。

## 13. 开放问题

仅引用 `OPEN_QUESTIONS.md` 中解决阶段包含 Stage 3 的问题；不得在本计划中自行决策。

## 14. 重新规划触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 未来草案使用 DRAFT v0.2；当前 Stage 执行中则置 PLAN_REVISION_REQUIRED，产生新版本并重新人工批准。

## 15. 失效触发器

上游 Stage REOPENED、输入 manifest/hash/commit 改变、验收证据被推翻或 L2-L4 Change Request 获批时，本 Stage 及受影响下游标记 INVALIDATED。

## 16. 重开条件

失效原因有书面决定、修订 Plan 已批准、回归范围明确且所需输入基线重新建立后，才可 REOPENED。

## 17. 回滚与恢复

撤销未批准产物引用并保留审计历史；不得覆盖旧 Plan/结果。恢复从最后有效基线开始，重新执行受影响验证。

## 18. 预期基线标签

`stage-3-vX.Y-passed`（仅 PASSED 且人工批准后创建；本次不得创建）。

## 19. 变更历史

- 2026-07-12：v0.1，依据 V1.3.4 创建，状态 DRAFT，未执行。
