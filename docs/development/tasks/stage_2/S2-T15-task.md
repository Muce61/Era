# S2-T15：条件随机基线

## Metadata

- task_id: S2-T15
- task_version: 1.4
- status: STOPPED / READ-ONLY AUDIT ONLY / NO AUTHORITY OR RUN
- projection_scope: HISTORICAL_PLAN_V1_2_TERMINAL
- terminal_status: STOPPED_FAILED_UNPUBLISHED
- successor_task_id: S2P13-T16
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T12 PASS; S2-T14 PASS; S2-T19 PASS
- supersedes: task_version 1.3
- approved_by: Muce
- approved_at: 2026-07-22T02:25:41Z

This Plan v1.2 identity is immutable historical evidence and is not the current Stage 2 Task.
`S2P13-T16` is its capability successor without result promotion; the failed unpublished S2-T15
chain remains non-resumable and does not block the current T20 closure.
Every later use of “current” or “当前” in this Task is scoped to its Plan v1.2 terminal snapshot
under CR-2026-034, not to the repository-wide Plan v1.7/T20 projection.

## 1. 目标

规划并交付“条件随机基线”这一单一能力，使其可独立测试、审查和回滚。

## 2. 背景

该能力属于 Stage 2“事件研究”，必须保持 V1.3.4 的证据等级、状态语义和人工阶段门。

## 3. 规格来源

- 手册章节：§9、§11-16、附录D/J/L/N
- rule_id：EVENT-CONSUME-MARKET-EPISODE, STRATEGY-V1-PRICE-ONLY-HISTORICAL
- 数据契约：CanonicalKeyLevel, MarketEpisode, EntryIntent, path labels, cluster_id
- 系统不变量与 Reason Code：执行前从 `traceability/rules.yaml` 解析本 Task 的精确映射

## 4. 前置条件

Stage 2 Plan v1.2 与本 Task 的历史方法/实现范围曾获人工批准，依赖项有真实 validation，工作区和 Stage 1 Baseline v1.0 已核验。当前 OQ-S2-009、OQ-S2-010、OQ-S2-011 阻塞所有 Authority、Binning Set、preflight、Run、resume 和 publication；只允许机器状态明确列出的只读 audit、既有证据 verify 和只读 UI。

## 5. 允许范围

历史批准范围仍作为保留记录。当前执行范围收窄为：只读全历史可用性审计、既有不可变证据校验、只读状态投影，以及 CR-2026-034 授权的治理门和测试修复。不得创建新的研究结果或写入正式运行链。

## 6. 禁止事项

禁止越过 Stage、扩大交易风险、连接未授权 API、写入密钥、修改正式规格、把 BASELINE/RESEARCH 宣称最优或 FROZEN、自动批准或继续下一 Task。当前还明确禁止 supplement 构建、Authority、bins、preflight、Run、resume、publish，以及复用任何停止或失败的准备链。

## 7. 允许修改的路径

以第21节的v1.0精确路径以及 CR-2026-034 的治理修复精确路径为准；未列路径禁止修改。

## 8. 禁止修改的路径

`docs/spec/**`、其他未批准 Stage 的实现路径、真实密钥/账户文件、历史基线和已通过的不可覆盖验证产物。T10～T14 sealed evidence 不得重写、延长或重标。

## 9. 输入

规格基线、Stage Plan、依赖 Task 的已验证产物、适用配置/manifest/hash；执行时记录精确版本。当前运行许可由 `configs/governance/current_development_state.json` 的有效 state hash 唯一决定。

## 10. 交付物

该能力的最小实现或研究产物、对应测试、validation/manifest、TRACEABILITY 与 `rules.yaml` 状态更新；当前停止状态下只允许治理修复和只读审计产物，不产生正式研究结论。

## 11. 实现要求

先列出适用 rule_id、允许/禁止路径和计划；使用 Decimal/时间/证据字段等已批准契约；失败动作必须唯一且可审计；不得引入未来能力。所有写入口必须在副作用之前通过机器治理状态门。

## 12. 测试要求

覆盖正常、边界、失败和确定性场景；涉及 FROZEN/INV 时必须运行其映射测试；历史、代理、测试网与真实证据必须分级报告。治理测试必须证明 CLI 与直接 Python 入口都无法绕过 STOPPED 状态。

## 13. 验收标准

目标单一完成；测试真实运行且通过；无未解释追踪缺口；回滚可执行；未完成项和未运行测试如实报告；由人工验收。治理修复 PASS 不等于 T15 研究 PASS。

## 14. 必须运行的命令

以第21节的定向pytest命令、`python scripts/check_governance_state.py --strict` 和现有统一质量门为准。当前不得运行全量研究 CLI 的写模式。

## 15. 完成报告格式

规则/范围 → 修改文件 → 实际命令与结果 → 追踪更新 → 未完成/开放问题 → Go/No-Go 建议；不得自动继续。

## 16. 回滚方式

按独立提交撤销本 Task 的实现与注册引用，保留 manifest、审计和失败证据；若契约已被下游消费，先执行失效传播。不得通过回滚治理门来恢复旧的写权限。

## 17. 开放问题

- OQ-S2-005 已由 CR-2026-026 和 ADR-S2-009 关闭。
- OQ-S2-006 已由 CR-2026-027 的 append-only 只读补证关闭。
- OQ-S2-007 和 OQ-S2-008 的历史修复记录保留，但其旧 successor 授权不覆盖当前停止状态。
- OQ-S2-009：全历史 BTC/ETH 可用性审计仍未完成，阻塞 T15 Authority/bin/Run。
- OQ-S2-010：完整 lifecycle landmark/H3/censor 合同未冻结，阻塞生命周期实现。
- OQ-S2-011：SRP 框架未实现，已批准豁免仍不可执行。

需要改变风险、数据边界、执行语义或 Binance 能力判断时停止并请求人工决定。

## 18. 变化触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit、聚类方式、机器治理状态或其 state hash 变化；或发现与 V1.3.4/Binance 官方事实冲突。触发 task_version/治理版本复核和重新审批。

## 19. 失效条件

依赖 Task/Stage 重开、输入哈希变化、映射规则变化、验收测试被推翻或产物不可复现时标记 INVALIDATED，不得继续作为有效证据。单个旧 CR、旧 audit 或旧 Authority 不得覆盖更新后的 STOPPED 状态。

## 20. 变更历史

- 2026-07-12：v0.1，依据 Stage 2 Plan v0.1 创建，状态 DRAFT，未执行。
- 2026-07-14：v1.0，按Stage 1 Trade Identity v2与Stage 2 Plan v1.0重规划；状态DRAFT，未执行。
- 2026-07-14：v1.1，加入可扩展研究setup架构与事件说明图规划；状态DRAFT，未执行。
- 2026-07-16：v1.2，按Plan v1.2收口分组、前置S2-T19并修订DAG；状态DRAFT，未执行。
- 2026-07-21：Muce以`进入t15`批准v1.2方法fixture能力，从已收尾的S2-T14提交
  `2190d31639bebaa01e6e2462b55b57f43b03c286`独立执行。正式全量CLI、外部Run和Web UI
  自动识别不在v1.2允许范围内，必须先批准CR-2026-025与Task v1.3。
- 2026-07-21：v1.2条件匹配fixture、16项定向测试及553项统一质量门全部PASS；正式全量
  研究与Web UI仍未运行，Task保持开放并等待CR-2026-025人工决定，不启动S2-T16。
- 2026-07-21：Muce批准CR-2026-025与v1.3最小全量/UI范围。Run前审计确认仓库及Git全
  历史缺少波动率/Trades活跃度公式、split/fold边界、精确purge/embargo和非事件control
  锚点规则；按OQ-S2-005在Authority/Run创建前阻塞。没有创建或修改任何全量证据。
- 2026-07-22：Muce批准CR-2026-026、ADR-S2-009、v1.4与T19 append-only addendum，冻结
  三项特征、关键位距离、扩展滚动F0-F3、3600/600秒信息区间、三层control身份、T13逐行
  标签/T14 aggregate-only绑定、30格共享5个controls及全量对账。OQ-S2-005关闭；代码和
  质量门通过前仍禁止Authority，`run`前仍禁止Run ID。
- 2026-07-22：v1.4只读audit确认T10固定输入的14,256个Group-1收据缺失DatasetSpec要求
  的字段分布摘要，当前`CatalogReaderV2`以`distribution digest mismatch`拒绝读取。记录
  OQ-S2-006并在Authority、bins、Run和UI PASS之前停止；未修改任何T10密封成果。
- 2026-07-22：Muce批准独立CR-2026-027，以内容寻址对象逐分区重算缺失摘要并生成
  append-only只读补证；原T10保持不变。补证和新audit PASS前仍禁止Authority/Bins/Run。
- 2026-07-22：首份只读补证验证`14,256 / 14,256`且T10修改为0；新audit PASS。正式
  Authority/TRAIN bins/Run/Verify生产链路已实现并通过588项全仓质量门，但尚未创建任何
  Authority、Binning Snapshot或Run ID，等待最终代码干净提交及最终治理Hash重审计。
- 2026-07-22～23：后续失败链、七天 rehearsal、缺失审计和 lifecycle/SRP 治理形成当前
  STOPPED 状态；无正式 T15 结果，S2-T16+ 与 Stage 3 保持禁止。
- 2026-07-23：CR-2026-034/ADR-S2-013 授权机器 current-state authority 和 fail-closed 写门，
  不授权研究 Run。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：按预注册变量匹配条件随机基线，并只按预注册层级放宽；每个instrument/setup/context独立匹配和报告，不得观察结果后选方案或跨setup借用有利基线。
- 允许修改路径：`src/era100x/research/stage_2/baselines/conditional/`、`tests/research/stage_2/baselines/conditional/`，以及本Task validation/TRACEABILITY。CR-2026-034 另允许机器治理状态、治理检查器和对应测试。禁止修改Stage 1实现/数据、`docs/spec/**`和Stage 3+。
- 验证命令：`uv run python -m pytest tests/research/stage_2/baselines/conditional -q`；`uv run python scripts/run_quality_gate.py`；`uv run python scripts/check_governance_state.py --strict`。当前全量研究写模式不得执行。
- 验收标准：匹配/放宽/失败、时间切分、purge/embargo、确定性抽样和manifest一致性通过；正式结论必须全量。当前还必须证明 STOPPED 门在 CLI 和直接入口均 fail-closed。
- 证据模式：`METHOD_FIXTURE + FULL_RESEARCH_REQUIRED / CURRENTLY_STOPPED`。治理修复不改变正式研究仍未完成的事实。

## 22. CR-2026-025批准后的v1.3范围与阻塞门

CR-2026-025批准只读绑定T10/T13/T14/T19输入、正式Authority/Run/Manifest/Catalog/Verify、
最小全量CLI和只读自动UI投影。该范围不包含S2-T16+。后续 CR/OQ 与当前机器状态可进一步
收紧操作权限；旧批准不得作为当前执行许可。

## 23. CR-2026-026与ADR-S2-009的v1.4执行合同

CR-2026-026和ADR-S2-009保留为方法和历史执行合同。其冻结内容包括：61根1m bar的
Decimal RMS波动率；完整60秒Trades activity；S2-T07 causal EMA20 context；启用且不放宽
的active canonical key-level distance quintile；五块扩展滚动F0-F3；3600秒purge与600秒
embargo；每日确定性offset grid；outcome-blind anchor/candidate/outcome三层身份；全部已注册
H2 parameter/timing path和30个target×stop cells；T13逐行与T14 aggregate-only绑定；全量
Episode/control/cell对账。完整无Trade为AMBIGUOUS，不得写为EXPIRED。

CLI历史合同为`audit`、`freeze-authority`、`freeze-bins`、`preflight`、`run`、`verify`；当前
`configs/governance/current_development_state.json` 只允许 read-only audit 和既有证据 verify。
任何恢复写模式都需要新的人工批准、state hash、七天 rehearsal、fresh audit 和授权收据。

## 24. CR-2026-034 Plan v1.2 terminal STOPPED override

本节优先于任何旧的“implementation ready”“final successor”或“clean commit 后可运行”表述。
At that Plan v1.2 terminal snapshot, status was STOPPED;
`formal_t15_result_exists=false`; Stage 3 was locked; SRP was not executable.
机器状态的有效 hash 必须与 CR-2026-034/ADR-S2-013 和本 Task 投影一致。状态未正式变更前，
任何 Authority、bin、preflight、Run、resume、supplement build 或 publish 调用都必须在副作用
之前失败。
