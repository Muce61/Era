# Stage 1：历史数据基础

## Metadata

- stage_id: S1
- plan_version: 1.0
- status: APPROVED
- created_from_spec_version: V1.3.4
- created_from_commit: 0cf9bbd
- dependencies: Stage 0 v1.0 PASSED baseline (`stage-0-v1.0-passed`)
- supersedes: `stage_1_plan_v0.1.md`
- approved_by: Muce
- approved_at: 2026-07-12

## 1. 目标

建立BTCUSDT与ETHUSDT分离、可重复构建、可审计的H1/H2历史数据基础：读取既有1秒Contract Price，补齐并标准化Binance Trades，执行质量检查、确定性聚合、能力标签、时间切分、manifest与hash验证。

## 2. 非目标

不实现事件、标签、H3、回测、PnL策略、Binance账户/下单、Quote/Mark/Depth补造、前向采集或研究参数选择。Stage 1数据通过不等于事件优势、收益或可执行性通过。

## 3. 规格来源

- §2-3、§11、§13.3、§23-25、§29、§38、§45-46。
- 附录C、D、J、L；`DATA-HISTORICAL-NO-FAKE-EXECUTION`、`STRATEGY-V1-PRICE-ONLY-HISTORICAL`。
- 历史硬边界：`reference_ask`、`spread_bps`、`historical_recv_latency/ts_recv`、`actual_partial_fill_probability`及真实执行字段必须为NULL，不能用0或推算值填充。
- Stage 0有效能力：Decimal/时间/ID、配置快照、manifest/audit、严格契约、追踪和质量门。

## 4. 前置条件

本Plan及待执行Task分别人工批准；Stage 0基线有效；OQ-S1-001/002在涉及全量外部数据前解决；执行前记录分支、HEAD、输入路径、只读/可写边界和可用空间。

## 5. 输入基线与路径契约

- 既有资产：只读外部路径，由OQ-S1-001确认；不得移动、删除或覆盖。
- 小样本：`tests/fixtures/stage_1/`，只包含合成/裁剪且可提交的最小Contract Price与Trade样本。
- 本地工作根：建议`data/stage_1/`（已被Git忽略），含`raw/`、`normalized/`、`curated/`、`catalog/`；最终绝对路径需人工确认。
- 轻量配置：`configs/data/`；机器私有绝对路径只通过被忽略的本地配置或环境变量提供，不提交。
- 生成证据：`artifacts/manifests/stage_1/`与`artifacts/reports/stage_1/`（默认忽略）；Task Validation提交到`docs/development/validations/stage_1/`。
- 外部依赖：BTCUSDT/ETHUSDT Binance USDⓈ-M原始Trades；来源、覆盖区间和下载授权由OQ-S1-002确认。不得补历史Quote、秒级Mark、L2或自有执行。

## 6. 主要产物

数据资产审计、路径决策记录、Schema Registry、小样本fixtures、Contract Price读取器、Trades不可变原始导入与标准化、aggressor方向、质量/缺口检查、Parquet catalog/checksum、确定性K线、NULL能力门、purge/embargo、质量报告、全量运行预检/执行证据和Stage验收。

## 7. 执行顺序与并行关系

```text
T01 → T02 → ┬→ T03 ───────────────┐
            └→ T04 → T05 → T06 ──┼→ T07 → T08 → T09 ─┐
                                   └→ T10              ├→ T12 → T13 → T14 → T15
T02 → T11 ─────────────────────────────────────────────┘
```

- T03与T04可并行；T10在T03/T05/T06完成后可与T07/T08推进。
- Schema、规范化主键、分区规则和manifest格式不得并行修改。
- T01～T12以小样本/只读审计验收能力；T13为全量预检；T14才允许按批准路径执行全量下载/构建；T15汇总验收。

## 8. Task 清单

- [S1-T01](../tasks/stage_1/S1-T01-asset-path-audit.md) 现有资产与路径审计
- [S1-T02](../tasks/stage_1/S1-T02-schema-fixtures.md) Schema Registry与样本数据契约
- [S1-T03](../tasks/stage_1/S1-T03-contract-price-reader.md) 1秒Contract Price读取与校验
- [S1-T04](../tasks/stage_1/S1-T04-raw-trades-ingest.md) Binance Trades不可变原始获取/导入
- [S1-T05](../tasks/stage_1/S1-T05-trades-normalization.md) Trades标准化
- [S1-T06](../tasks/stage_1/S1-T06-aggressor-side.md) 主动买卖方向解析
- [S1-T07](../tasks/stage_1/S1-T07-integrity-gaps.md) 去重、异常、时间倒退与缺口检测
- [S1-T08](../tasks/stage_1/S1-T08-parquet-catalog.md) Parquet分区、catalog与checksum
- [S1-T09](../tasks/stage_1/S1-T09-deterministic-bars.md) 确定性K线聚合
- [S1-T10](../tasks/stage_1/S1-T10-historical-null-boundary.md) 历史NULL与证据能力边界
- [S1-T11](../tasks/stage_1/S1-T11-purge-embargo.md) 时间切分、purge与embargo
- [S1-T12](../tasks/stage_1/S1-T12-quality-sample-acceptance.md) 数据质量报告与样本验收
- [S1-T13](../tasks/stage_1/S1-T13-full-data-preflight.md) 全量数据运行计划与预检
- [S1-T14](../tasks/stage_1/S1-T14-full-data-build.md) 全量数据构建与可重复性验证
- [S1-T15](../tasks/stage_1/S1-T15-stage-1-acceptance.md) Stage 1集成验收

## 9. 测试策略

使用Stage 0冻结的Python 3.12/uv/pytest/Hypothesis/Ruff/mypy/统一质量门。覆盖schema、unit、property、deterministic output、integration和regression；小样本必须含重复Trade ID、乱序、缺秒、边界时间、maker/taker两侧、NULL字段与损坏文件。真实全量只产生数据质量证据，不替代确定性fixture测试。

## 10. Stage 验收门槛

- BTC/ETH分别报告；Trades覆盖、缺口、重复、时间范围和聚合一致性可核验。
- 同一输入/配置/代码重复构建得到相同catalog、partition checksum和manifest hash。
- H1/H2能力标签正确；历史Quote/recv/execution字段保持NULL，不能为0。
- 无未来泄漏；purge不少于最大特征回看加最大episode/持仓窗口，embargo规则进入manifest。
- 小样本全部Task PASS；全量T14 PASS；所有输入hash、数据质量限制和未覆盖区间明确。

## 11. Go / No-Go

仅上述门槛全部满足才可提交人工验收。路径未确认、Trades来源不明、输入被写入、hash不稳定、时区/单位不明、缺口未解释、NULL被填0或全量未运行均为NO-GO。不得用事件研究结果修复数据失败。

## 12. 风险

本地资产命名/格式未知、存储容量不足、外部归档缺月、Trade ID语义变化、时区/毫秒微秒混用、Parquet版本影响hash、聚合边界漂移以及Stage 0顶层包允许清单需受控增加`data`。

## 13. 开放问题

- OQ-S1-001：只读输入根、Stage 1可写根、容量/保留策略。
- OQ-S1-002：Binance Trades获取方式、允许网络下载与目标覆盖区间。
- 两项不阻塞规划及T02～T12小样本开发；阻塞T13最终预检与T14全量运行。

## 14. 重新规划触发器

输入格式/路径、schema、Trade ID/side语义、分区、聚合、时间单位、数据hash、依赖锁或规格变化；未来草案使用DRAFT v1.1，执行期变化进入PLAN_REVISION_REQUIRED并重新审批。

## 15. 失效触发器

Stage 0基线重开、输入或配置hash变化、schema/归一化/聚合规则变化、全量源替换、重复构建不一致或L2-L4 CR批准时，使相关Task、数据baseline及下游Stage失效。

## 16. 重开条件

失效原因书面决定、受影响数据明确隔离、修订Plan获批、回归范围与重新构建成本确认后才可REOPENED。

## 17. 回滚与恢复

代码按Task独立提交回滚；原始输入只读且不可删除；生成分区采用新run_id写入，不覆盖旧run；失败manifest保留并标记INVALIDATED。

## 18. 预期基线标签

`stage-1-v1.0-passed`及对应data baseline，仅在T15 PASS和人工最终批准后创建。

## 19. 变更历史

- 2026-07-12：v0.1，初始泛化草案。
- 2026-07-12：v1.0，按Stage 0真实实现重构为15个Task，冻结路径/样本/全量边界和可执行验证命令；状态DRAFT。
