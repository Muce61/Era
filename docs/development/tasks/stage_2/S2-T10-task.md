# S2-T10：候选事件全量生成

## Metadata

- task_id: S2-T10
- task_version: 1.9
- status: IN_PROGRESS
- stage_id: S2
- stage_plan_version: 1.2
- created_from_spec_version: V1.3.4
- created_from_commit: b7d4ff3d18dcfc515feb8892659cb0b186cd68f8
- dependencies: S2-T01 PASS; S2-T02 PASS; S2-T03 PASS; S2-T04 PASS; S2-T05 PASS; S2-T06 PASS; S2-T07 PASS; S2-T08 PASS; S2-T09 PASS; S2-T19 PASS; locked Group-1 Manifest; CR-2026-007 APPROVED; CR-2026-008 APPROVED
- supersedes: task_version 1.8
- approved_by: Muce
- approved_at: 2026-07-17T19:09:18+08:00
- execution_started_at: 2026-07-17T19:09:18+08:00

## 1. 目标

规划并交付“候选事件全量生成”这一单一能力，使其可独立测试、审查和回滚。

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

只实现并验证“候选事件全量生成”及其直接契约、测试和追踪；允许为该单一能力增加最小审计证据。

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

CR-2026-004 and CR-2026-005 are RESOLVED / IMPLEMENTED / VALIDATED. Their identity and unique
Sweep-start-minute ownership corrections remain binding and are not reopened by v1.8.

CR-2026-006 remains APPROVED / IN_PROGRESS only for the already-running release child of source
Run A `stage2-g1-full-a-20260716T144233Z-366a541b7956`. The legacy CR-2026-006 parent is stopped
and must not create its planned legacy Run B.

Muce approved [CR-2026-007](../../changes/CR-2026-007.md) and
[CR-2026-008](../../changes/CR-2026-008.md). S2-T10 v1.8 therefore keeps the Run A release child,
builds the complete Feature Foundation, performs a fresh V2 Group-1 reconstruction as Run B, and
requires exact layout-independent semantic equivalence before PASS. This approval changes no
Plan v1.2 dependency edge and does not authorize S2-T11～S2-T20.

## 18. 变化触发器

schema、标签、成本模型、事件定义、数据/配置哈希、git commit 或聚类方式变化；或发现与 V1.3.4/Binance 官方事实冲突。 触发 task_version 递增和重新审批。

## 19. 失效条件

依赖 Task/Stage 重开、输入哈希变化、映射规则变化、验收测试被推翻或产物不可复现时标记 INVALIDATED，不得继续作为有效证据。

## 20. 变更历史

- 2026-07-17：v1.8，Muce批准CR-2026-007与CR-2026-008的混合切换：当前Run A发布子进程
  继续，旧CR-2026-006父流程及其legacy Run B停止；新的Run B必须从冻结Stage 1完整构建
  Feature Foundation并全量重算Group 1，随后与正式Run A执行逐owner-day精确语义比较。
  Plan v1.2分组和Task DAG不变，Task保持IN_PROGRESS。

- 2026-07-17：v1.7，Muce批准CR-2026-006 L2发布工具版本分离。固定复用已完成
  9508/9508的v1.6 Run A staging，仅以append-only supplement、单扫描可恢复发布器完成深度
  校验和发布；事件生成器、研究语义、参数、Stage 1、preregistration与config均不变。
  Run A PASS后才可创建全新的Run B；双运行验收前Task保持IN_PROGRESS。

- 2026-07-16：Muce关闭CR-2026-005并授权冻结新Execution Manifest以及执行全新的Run A / Run B
  双全量确定性构建；Task恢复IN_PROGRESS，禁止复用旧staging和进入后续组。

- 2026-07-16：v1.6 Option A实现与受控真实双重放PASS；Task状态
  APPROVED_FOR_REEXECUTION，等待新的全量运行人工批准，未创建Execution Manifest或run_id。

- 2026-07-16：v1.6，Muce批准CR-2026-005 Option A，仅修复Sweep-start UTC分钟所有权与runner失败终态并执行受控诊断；状态IN_PROGRESS，禁止创建全量run。

- 2026-07-16：v1.5 Run A完成BTC PRICE 2376/2376日构造后，在2020-04-27 finalization发现两个same identity/different payload冲突并保持未发布失败；创建CR-2026-005，Task状态BLOCKED，未创建Run B。

- 2026-07-16：v1.5，Muce批准CR-2026-004 L2及Case C按新身份拆分；重开Task以修复candidate identity、partition ownership和dedup finalization，本轮禁止创建全量run。

- 2026-07-16：v1.5修复、前50日双重放和全部质量门PASS；状态APPROVED_FOR_REEXECUTION。本轮未创建Execution Manifest或全量run。

- 2026-07-16：CR-2026-003路径修复及回归通过；全量前审计发现保留的BTC PRICE前50日分区3,781行中仅971个唯一candidate identity，2,810行为重复且均被标记included。创建CR-2026-004，Task状态BLOCKED，未创建新run。

- 2026-07-16：v1.4，Muce批准CR-2026-003，仅允许修复Stage 1 Catalog到`archive=YYYY-MM/date=YYYY-MM-DD`的物理路径解析并以全新run重新执行；状态REOPENED。

- 2026-07-16：v1.3 full run在首个BTCUSDT Flow分区因Stage 1 Trades物理路径解析遗漏`archive=YYYY-MM`层失败；2376/9504分区完成、无发布，状态FAILED；CR-2026-003待决策。

- 2026-07-16：v1.3，依据CR-2026-002与ADR-S2-005冻结第一组事件构造基线和CLI；Muce批准，状态APPROVED / NOT_EXECUTED。

- 2026-07-12：v0.1，依据 Stage 2 Plan v0.1 创建，状态 DRAFT，未执行。
- 2026-07-14：v1.0，按Stage 1 Trade Identity v2与Stage 2 Plan v1.0重规划；状态DRAFT，未执行。
- 2026-07-14：v1.1，加入可扩展研究setup架构与事件说明图规划；状态DRAFT，未执行。
- 2026-07-16：v1.2，按Plan v1.2收口分组、前置S2-T19并修订DAG；状态DRAFT，未执行。

## 21. Stage 2 Plan v1.2执行覆盖（优先于旧版通用占位）

- 数据与能力边界：仅从Stage 1 published baseline全量生成宽松候选；由已批准ResearchSetup/ContextModel注册表驱动，核心编排器不得按具体行情类型分支硬编码；BTC/ETH、setup/context、V1_PRICE/V1_FLOW分run，输出append-only。
- 允许修改路径：`src/era100x/research/stage_2/features/foundation/`、现有Stage 2 registry的
  最小扩展、`src/era100x/research/stage_2/runtime_v2/`、
  `src/era100x/research/stage_2/pipelines/v2/`、
  `src/era100x/research/stage_2/pipelines/candidates/`及其对应
  `tests/research/stage_2/`路径；还允许V2固定入口
  `scripts/run_stage2_research.py`、经S2-T19冻结的V1候选CLI、V2
  Manifest/Catalog/receipt、本Task validation和Traceability。禁止修改Stage 1实现/数据、
  `docs/spec/**`和Stage 3+。
- 验证命令：\`uv run python -m pytest tests/research/stage_2/pipelines/candidates -q\`；\`uv run python scripts/run_quality_gate.py\`。全量研究CLI须由S2-T19冻结后再写入Task新版本，不得当前虚构。
- 验收标准：全量coverage/hash/manifest一致，无staging输入、无跨标的/跨setup/context证据混合、无重复episode、未知setup硬失败、所有尝试版本入账；同一MarketEpisode不能因setup/context不同而重复消费；仅fixture不得PASS。
- 证据模式：\`FULL_DATA_REQUIRED\`。无论fixture能力是否可验收，Stage 1最终PASSED与VALID data baseline之前均不得执行本Task。

## 22. ADR-S2-004预注册绑定

S2-T10只能只读消费S2-T19锁定且引用[ADR-S2-004](../../decisions/ADR-S2-004-primary-research-definition.md)的第一组Manifest。全量候选须按instrument、T1～T4、P1～P3和split/fold隔离，保存配置/hash并append-only；本Task不执行匹配、First-passage、bootstrap或F1～F10统计。v1.4仅按已批准CR-2026-003修复物理路径解析；失败run不得恢复、复用、覆盖或清理。

## 23. ADR-S2-005事件构造绑定

For the immutable V1 Run A compatibility path, this Task uses only
`uv run python scripts/run_stage2_group1_candidates.py {preflight,run,resume,verify}`. That V1
command remains bound to its locked Manifest and is not the V2 Run B interface.

S2-T10 v1.8 Run B must use the fixed V2 entry point
`uv run python scripts/run_stage2_research.py {preflight,build-foundation,run-group1,resume,release,verify,compare}`.
Every mutating subcommand requires the locked V2 Execution Manifest; resume requires identical
content keys and hashes; verify is read-only. Under CR-2026-009, compare may only write one
append-only deterministic evidence report and therefore requires a write probe and run lock.
The fixed operator preparation scripts are `freeze_stage2_v2_authorities.py` and
`record_stage2_v2_quality_evidence.py`; the three `diagnose_stage2_v2_*_rss.py` scripts are
DIAGNOSTIC_ONLY. A sealed Foundation staging authority may feed Group 1 inside the same Run B,
while publication remains a single combined atomic snapshot. No later-stage labels, metrics or
research conclusions are produced.

## 24. CR-2026-007 V2平台绑定

S2-T10 v1.8 may build only the Feature Foundation, fail-closed registry, content-addressed build
graph, logical owner-day receipts, layout-independent Catalog and current Group-1 compatibility
projection defined by [ADR-S2-006](../../decisions/ADR-S2-006-hybrid-v2-feature-foundation.md).
Only the already approved setup, context and variants may execute. The Foundation must preserve
causal availability and Stage 1 evidence capability; physical compaction cannot change logical
ownership or merge instruments, variants, research roles or parameter sets.

The current Run A release child remains isolated and immutable. A fresh V2 Run B must begin from
the frozen Stage 1 authorities, publish the complete Foundation, reconstruct every Group-1
partition and produce the full compatibility projection. No Run A artifact may be reused as a
Run B input.

## 25. CR-2026-008确定性验收绑定

Run A and Run B may differ in file count, physical path, compression and byte hash, but every
canonical owner-day projection must match exactly in row count, empty state, canonical logical
hash, ID association, payload hash, ownership, inclusion and registered distributions. Any
semantic mismatch fails S2-T10; sampling or tolerance is forbidden.

Future event Tasks, only after separate approval, must follow Tier F/E/D. An event whose
primitives already exist in a frozen Feature Snapshot performs two complete event computations
from that snapshot and must not rescan raw Stage 1 Trades. A missing primitive blocks execution
until a separately approved Foundation extension is built and validated.

## 26. CR-2026-011 production memory correction

S2-T10 v1.9 may change only Runtime V2 Foundation physical processing and resource evidence. It
must preserve the 1 GiB Arrow inflight hard limit, stream authoritative Trades row groups, release
source tables after dependent features are sealed, and enforce separately recorded current-RSS and
baseline-relative peak-RSS gates calibrated from approved real-data profiles. This correction may
not change any logical row, hash, identity, availability, parameter, source authority or Group-1
comparison rule. The failed v1.8 Run B is terminal and cannot be resumed or reused.
