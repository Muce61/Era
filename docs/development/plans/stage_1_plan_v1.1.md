# Stage 1：历史数据基础

## Metadata

- stage_id: S1
- plan_version: 1.1
- status: APPROVED
- created_from_spec_version: V1.3.4
- created_from_commit: c25c2a4
- dependencies: Stage 0 PASSED
- supersedes: stage_1_plan_v1.0
- approved_by: Muce
- approved_at: 2026-07-14

## 1. 目标

在不越过历史H2能力边界的前提下，构建BTCUSDT与ETHUSDT分离、可恢复、可审计、确定性的Contract Price与Binance官方Trades数据基础，并采用ADR-2026-001 Trade Identity v2保留全部不同官方成交事实。

## 2. 非目标

不实现事件研究、H3/F1、回测收益、账户API、测试网、下单、实盘或Stage 2能力；不伪造历史Quote、接收延迟、部分成交或真实滑点。

## 3. 规格来源

V1.3.4 §2-3、§11、§23-25、阶段1、附录C/D/J/L；`DATA-HISTORICAL-NO-FAKE-EXECUTION`、`STRATEGY-V1-PRICE-ONLY-HISTORICAL`、`INV-013`；CR-2026-001与ADR-2026-001只细化L2数据身份，不修改正式规格。

## 4. 前置条件

Stage 0基线有效；只读Contract根与外盘工作根可用；官方公开归档授权成立；S1-T13磁盘门PASS。

## 5. 输入基线

Contract根`/Users/muce/1m_data/klines_data_usdm_1s_agg`只读；工作根`/Volumes/FuckingLife/era100x_stage1`；有效raw归档按官方checksum不可变复用。旧v1 run为INVALIDATED且staging不得复用。

## 6. 主要产物

`stage1-trades-v2` schema、规范化与质量实现、分区Parquet、Catalog、Manifest、报告、验证及可恢复全量run。

## 7. 里程碑

T02/T05/T07/T08/T09/T12完成v2重开；T06/T10/T11回归；T14 v1.5重新全量构建；T15保留DRAFT等待显式批准。

## 8. Task 清单

S1-T01～T13既有验收保留；CR影响的T02/T05/T07/T08/T09/T12升级v1.1，T06/T10/T11执行回归，T14升级v1.5。S1-T15不自动执行。

## 9. 测试策略

覆盖规范Decimal身份、完全重复、venue冲突保留、月/日集合匹配与不匹配、稳定排序/hash/catalog、K线不漏不重、BTC/ETH隔离、NULL边界、purge/embargo、全量质量门。

## 10. Stage 验收门槛

162归档完成；双symbol发布；冲突交叉验证通过；确定性重建和全量质量门通过；所有缺口和异常显式报告；无BLOCKER。

## 11. Go / No-Go 条件

仅T14 PASS后可请求S1-T15审批。月/日事实集合不一致、checksum变化、schema冲突、磁盘门失败或hash漂移均No-Go。

## 12. 风险

官方归档可能替换；外盘或长任务可能中断；冲突组可能新增。checkpoint、checksum、不可变发布与失效传播控制这些风险。

## 13. 开放问题

OQ-S1-005已由CR-2026-001解决。新来源分歧必须新建OQ/CR，不自行选择事实。

## 14. 重新规划触发器

Schema、身份字段、官方来源语义、覆盖区间、数据根或质量门变化。

## 15. 失效触发器

输入checksum、schema、identity算法、排序、逻辑hash、配置hash或代码commit变化。

## 16. 重开条件

上游Stage重开、官方checksum变化、发布后发现来源分歧或确定性失败。

## 17. 回滚与恢复

保留raw；废弃run标INVALIDATED；不复制旧staging；用同run checkpoint恢复，或用新commit/config生成新run。

## 18. 预期基线标签

Stage最终人工验收后另建；本计划不创建Stage 1 tag或baseline。

## 19. 变更历史

- 2026-07-14：v1.1，纳入CR-2026-001与Trade Identity v2，人工批准执行；不改变V1.3.4。
