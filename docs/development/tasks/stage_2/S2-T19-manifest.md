# S2-T19：预注册实验 Manifest

## Metadata

- task_id: S2-T19
- task_version: 1.3
- status: PASSED
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: Stage 1 PASSED / VALID; Stage 2 Plan v1.2 APPROVED; input data baseline confirmed; no blocking OPEN QUESTION
- supersedes: task_version 1.2
- approved_by: Muce
- approved_at: 2026-07-16T15:24:31+08:00

## 1. 目标

在任何Stage 2实现或研究运行之前，交付可版本化、可验证且不可覆盖的预注册Manifest能力；本Task只定义和锁定研究输入，不执行收益研究或产生研究结论。

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

只实现并验证“预注册实验 Manifest”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

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

OQ-S2-004 已由Muce人工决定并通过[ADR-S2-004](../../decisions/ADR-S2-004-primary-research-definition.md)关闭，Blocking Scope为NONE。其值仅为BASELINE/RESEARCH预注册定义，不是最优或FROZEN。

其他情况下，只记录影响本 Task 的 U/CR/ADR；需要改变风险、数据边界、执行语义或 Binance 能力判断时停止并请求人工决定。

## 18. 变化触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 触发 task_version 递增和重新审批。

## 19. 失效条件

依赖 Task/Stage 重开、输入哈希变化、映射规则变化、验收测试被推翻或产物不可复现时标记 INVALIDATED，不得继续作为有效证据。

## 20. 变更历史

- 2026-07-16：v1.3，依据CR-2026-002与ADR-S2-005冻结第一组事件构造基线和CLI；Muce批准，状态APPROVED / NOT_EXECUTED。

- 2026-07-12：v0.1，依据 Stage 2 Plan v0.1 创建，状态 DRAFT，未执行。
- 2026-07-14：v1.0，按Stage 1 Trade Identity v2与Stage 2 Plan v1.0重规划；状态DRAFT，未执行。
- 2026-07-14：v1.1，加入可扩展研究setup架构与事件说明图规划；状态DRAFT，未执行。
- 2026-07-16：v1.2，按Plan v1.2收口分组、前置S2-T19并修订DAG；状态DRAFT，未执行。
- 2026-07-16：Plan v1.2 与本 Task 由 Muce 批准；状态 APPROVED / NOT_EXECUTED，OQ-S2-004 阻塞执行。
- 2026-07-16：OQ-S2-004由ADR-S2-004正式关闭；Blocking Scope为NONE，本Task仍为APPROVED / NOT_EXECUTED。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：在任何Stage 2业务Task开始前冻结研究运行Manifest Schema、`parameter_set_id/parameter_set_version`、Stage 1 baseline tag/commit/data_run_id/manifest/schema/logical hashes、代码版本、UTC时间切分与purge/embargo、instrument、evidence_level、`setup_id/setup_version/context_model_id/context_version`、允许指标、禁止指标、参数域、匹配放宽、失败线、seed、输出目录、run布局、原子发布/不可覆盖规则和失效条件。第一组全量运行配置必须在S2-T10之前锁定且append-only。
- 允许修改路径：`src/era100x/research/stage_2/manifests/`、`tests/research/stage_2/manifests/`、`configs/research/stage_2/`、`artifacts/manifests/stage_2/`，以及本Task validation/TRACEABILITY。禁止修改Stage 1实现/数据、\`docs/spec/**\`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/manifests -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：所有必填字段、版本和hash可验证；BTC/ETH配置隔离；允许/禁止指标白名单生效；输出根必须来自OQ-S2-001决定；结果产生后拒绝修改或覆盖；失效传播、台账追加、未知setup/参数集/数据基线拒绝测试通过；第一组Manifest可被T01～T10只读引用。不得读取结果调参，不得生成候选事件、收益指标或研究结论。
- 证据模式：\`PREREGISTRATION_GATE\`；这是第一组和整个Stage 2的首个Task。

## 22. ADR-S2-004预注册Manifest要求

Manifest必须完整、机器可验证地锁定[ADR-S2-004](../../decisions/ADR-S2-004-primary-research-definition.md)的T1～T4及唯一Primary T2、P1～P3、不可放宽字段、UTC四小时bucket、训练折quintile边界、L0～L5、5 controls、排除规则、`matching_seed=20260716`、Episode等权基线、AMBIGUOUS三种报告、cluster定义、5000次percentile bootstrap、`bootstrap_seed=20260716`、F1～F10、BH FDR `q<=0.10`及ETH分类。任一必填定义缺失或五分位bin无效必须BLOCKED。OQ关闭不代表本Task已执行或PASS；状态仍为APPROVED / NOT_EXECUTED。

## 23. ADR-S2-005事件构造绑定

This Task freezes both preregistration and execution Manifest layers, the 20 OFAT parameter sets, Stage 1 physical and logical hashes, Contract Price inventory hash, approved external-root space gate and the single CLI contract from ADR-S2-005. It generates no candidate event or research result.

## 24. Append-only S2-T15 v1.4 preregistration addendum

Approved by Muce at 2026-07-22T02:25:41Z under CR-2026-026 and ADR-S2-009. This addendum does
not alter the earlier T19 Manifest or delete prior registrations. It freezes only the executable
S2-T15 v1.4 conditional-baseline contract: three feature IDs and formulas; exact setup/context;
active-key-level distance enabled and never relaxed; P1/P2/P3 five-block expanding F0-F3 folds;
3600-second backward purge and 600-second forward embargo; deterministic daily-offset grid and
seed 20260716; outcome-blind three-layer control identity; T13 row-label and T14 aggregate-policy
bindings; one five-control selection per H2 path shared across the 30-cell frozen combination
order; complete-zero-Trade AMBIGUOUS semantics; and fail-closed reconciliation.

The exact executable values and invalidation list are in
[ADR-S2-009](../../decisions/ADR-S2-009-conditional-baseline-v1.4.md) and
[CR-2026-026](../../changes/CR-2026-026.md). No S2-T16+, bootstrap, CI, F1, PnL, Stage 3 or live
execution is added. Authority remains forbidden until final-code quality gates pass; Run ID is
created only by the approved T15 `run` command after sealed bins and preflight.

## 25. Proposed append-only lifecycle sub-hypothesis addendum

Status: **APPROVED DIRECTION / NUMERIC CONTRACT OPEN / NOT EXECUTABLE**. Muce approved the
two-layer evidence direction and sub-hypothesis at `2026-07-22T16:27:27Z`. Linked governance is
[CR-2026-032](../../changes/CR-2026-032.md),
[ADR-S2-011](../../decisions/ADR-S2-011-event-path-and-strategy-lifecycle-separation.md) and
OQ-S2-010.

The proposed sub-hypothesis is preserved verbatim:

> 事件在存活较长时间、尚未激活、且净可退出 PnL 接近零时，后续目标优先概率和净期望是否提高？

Raw T1-T4 event paths remain immutable and exit-rule-free. Any complete-strategy research must be
a separate variable-length H3 evidence family from theoretical entry through
`THEORETICAL_FULLY_FLAT` or an explicit right-censor state. It must not use the real-execution term
`POSITION_FLAT`, alter the T2 Primary, or calculate PnL from H1/H2 facts alone.

This section intentionally freezes no numeric contract. Implementation and Authority/Run creation
are blocked until human approval defines all OQ-S2-010 landmarks, activation, near-zero band,
cost/fill/closure, maximum horizon, censor, subgroup and multiplicity values in a new Plan/Task
version. The three possible interpretations—delayed activation, momentum decay, or conditional
time rules—must all be reported; observing one does not authorize post-hoc rule replacement.
