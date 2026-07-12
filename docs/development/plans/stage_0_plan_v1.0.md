# Stage 0：规格、工程地基与执行能力前置冻结

## Metadata

- stage_id: S0
- plan_version: 1.0
- status: PASSED
- created_from_spec_version: V1.3.4
- created_from_commit: cfd19ed3c9c76e8ef7fdada776bfb47cbcd50c9a
- dependencies: `spec-v1.3.4-final`
- supersedes: `stage_0_plan_v0.1.md`
- approved_by: Muce
- approved_at: 2026-07-12
- final_accepted_by: Muce
- final_accepted_at: 2026-07-12
- validation: `docs/development/validations/stage_0_validation.md`
- validated_commit: `692dd29`

## 1. 目标

把V1.3.4的工程地基、32条正式规则元数据、41个系统不变量、附录C-E契约、PnL公式、状态/Reason Code、测试门禁和Execution Capability前置边界转化为可审查、可验证的Stage 0产物。

## 2. 非目标

不下载数据、不做事件研究/H3/回放、不实现完整状态机或交易事务、不连接Binance/测试网/真实资金、不创建API Key、不选择研究最优参数、不批准任何Stage/Task。S0-T12仅离线计划与隔离骨架；网络Spike必须另行书面授权和Task版本。

## 3. 规格来源

- §4-8：冻结范围、配置、PnL、Round和风险公式的基础契约
- §17-27：能力事实、执行契约、状态/持久化责任和测试门禁
- §28、§38、§46：Stage 0门槛、停止规则和当前Go/No-Go
- 附录A-C：32条规则、配置和证据字段
- 附录D-E：事件、订单、Algo、状态、Round及事故契约（本Stage仅schema）
- 附录F：PnL公式；附录G-I：状态、INV-001～041、Reason Code
- 附录J-L：Manifest、故障场景和阶段验收；附录N/B01-B10：OPEN问题与官方能力记录

## 4. 前置条件

规格基线与`spec_import_validation.md`有效；本Plan和首个Task分别人工批准；工作区干净；所有网络/API默认关闭。批准本Plan不等于批准S0-T12未来网络Spike。

## 5. 输入基线

`spec-v1.3.4-final`（commit `28bfb76`）、规划基线`planning-v0.1`、当前代码事实和OPEN问题。开始每个Task时记录实际HEAD及依赖validation。

## 6. 主要产物

Python 3.12工程地基、确定性工具链、配置/规则/类型/审计/PnL/契约/状态基础、严格追踪检查、无网络CI、离线Spike计划以及Stage 0验收报告。行为性执行规则仍标记PLANNED并归属后续Stage。

## 7. 里程碑与执行顺序

1. S0-T01 Python项目骨架
2. S0-T02 工具链与质量命令
3. S0-T05 Decimal/时间/ID基础类型
4. S0-T03、S0-T04、S0-T09 可并行：配置、规则元数据、状态/Reason枚举
5. S0-T08 契约骨架；S0-T06 在T03/T04/T09完成后进行
6. S0-T07 在T05/T06后进行；可与已满足依赖的T08并行
7. S0-T10 Traceability检查
8. S0-T11 CI基础
9. S0-T12 离线Execution Capability Spike计划与隔离骨架
10. S0-T13 集成验收与人工Go/No-Go入口

同一共享契约不得并行修改；并行Task必须使用独立提交，合并前重跑共同质量门。

## 8. Task 清单

- [S0-T01](../tasks/stage_0/S0-T01-python-project-skeleton.md)：Python 项目骨架；依赖 `spec-v1.3.4-final`
- [S0-T02](../tasks/stage_0/S0-T02-tooling-and-test-framework.md)：依赖、格式化、类型检查和测试框架；依赖 `S0-T01`
- [S0-T03](../tasks/stage_0/S0-T03-effective-config-snapshot.md)：配置层级与有效配置快照；依赖 `S0-T05`
- [S0-T04](../tasks/stage_0/S0-T04-rule-metadata.md)：Rule Metadata；依赖 `S0-T05`
- [S0-T05](../tasks/stage_0/S0-T05-decimal-time-identifiers.md)：Decimal、时间戳和标识基础类型；依赖 `S0-T02`
- [S0-T06](../tasks/stage_0/S0-T06-manifest-audit-contracts.md)：Manifest 与审计日志契约；依赖 `S0-T03, S0-T04, S0-T05, S0-T09`
- [S0-T07](../tasks/stage_0/S0-T07-pnl-contract.md)：PnL 口径基础契约；依赖 `S0-T05, S0-T06`
- [S0-T08](../tasks/stage_0/S0-T08-core-data-contracts.md)：核心数据契约骨架；依赖 `S0-T03, S0-T04, S0-T05, S0-T09`
- [S0-T09](../tasks/stage_0/S0-T09-state-reason-enums.md)：状态与 Reason Code 枚举；依赖 `S0-T05`
- [S0-T10](../tasks/stage_0/S0-T10-traceability-check.md)：Traceability 自动检查；依赖 `S0-T04, S0-T08, S0-T09`
- [S0-T11](../tasks/stage_0/S0-T11-ci-foundation.md)：CI 基础；依赖 `S0-T02, S0-T07, S0-T08, S0-T09, S0-T10`
- [S0-T12](../tasks/stage_0/S0-T12-execution-capability-spike-plan.md)：Binance Execution Capability Spike 计划与隔离骨架；依赖 `S0-T03, S0-T06, S0-T08, S0-T09, S0-T11`
- [S0-T13](../tasks/stage_0/S0-T13-stage-0.md)：Stage 0 集成验收；依赖 `S0-T01, S0-T02, S0-T03, S0-T04, S0-T05, S0-T06, S0-T07, S0-T08, S0-T09, S0-T10, S0-T11, S0-T12`

## 9. 测试策略

Stage 0实际运行unit、property、schema、deterministic-output、governance和offline-mock测试。FI-01～20及交易行为测试只验证“已映射/可表达”，不得伪称已通过；它们属于Stage 6。所有命令由S0-T02建立并被本地与CI共同调用。

## 10. Stage 验收门槛

- 13个Task均有独立提交、validation、真实命令与退出码；S0-T13质量门全绿。
- 32/32正式规则、41/41 INV、附录C-E契约、附录I Reason和附录K测试均有唯一归属；Stage 0基础测试与延后行为测试明确分离。
- PnL固定算例、Decimal属性、配置hash、schema覆盖、枚举覆盖、traceability严格检查均通过。
- S0-T12证明网络默认硬阻断，U-001～U-003保持OPEN/下游BLOCKED；不得把离线mock写成Binance能力通过。
- 未创建数据、业务策略、交易所连接、密钥或后续Stage实现。
- 形成DRAFT验收报告，由人工决定是否PASSED；系统不得自动改状态。

## 11. Go / No-Go 条件

建议GO进入人工验收仅当第10节全部满足。任一FROZEN元数据不一致、INV重复、契约缺字段、PnL双扣、质量命令不可复现、网络隔离失败或追踪缺口均NO-GO。Algo能力未知允许Stage 0工程地基验收，但必须保持live/Stage5自动状态BLOCKED。

## 12. 风险

最大风险是把schema骨架误当完整执行实现、把离线Spike误当官方能力证据、把PLANNED测试误写PASSED，以及多个Task同时修改共享枚举/契约。依赖图和路径所有权用于阻止这些风险。

## 13. 开放问题

U-001（workingType）、U-002（Algo状态映射）、U-003（适配器覆盖）需要未来授权Spike/F1证据，不需要在批准本工程地基Plan前决定；它们阻塞执行适配选型、影子自动状态和small-live。当前没有必须由用户预先选择的技术风险参数。

## 14. 重新规划触发器

Python/工具链不可用、包边界冲突、规格或Binance官方事实变化、契约/枚举/公式需改、S0-T12需要网络授权、实际命令与计划不一致时，生成v1.1+并重新审批。

## 15. 失效触发器

规格基线、依赖锁、配置hash、契约schema、规则/INV注册、PnL公式、状态/Reason枚举或质量门变化使相应Task及消费者INVALIDATED；不得覆盖旧validation。

## 16. 重开条件

失效原因已记录，影响范围和回归命令明确，新Plan/Task版本人工批准，且最后有效基线可恢复后方可REOPENED。

## 17. 回滚与恢复

每Task独立提交并可反向提交；共享契约回滚前先失效消费者。保留v0.1、失败证据和审计记录，不用重写历史。

## 18. 预期基线标签

`stage-0-v1.0-passed`，在全部真实验收和人工最终批准后创建。该条件已于2026-07-12满足。

## 19. 变更历史

- 2026-07-12：v0.1，初始泛化草案。
- 2026-07-12：v1.0，完成规格/测试分配、依赖重排、路径隔离、实际命令和可执行验收修订；状态DRAFT。
- 2026-07-12：S0-T01～S0-T13全部PASSED，集成验收PASS，用户最终批准；v1.0冻结为最终已验收版本。
