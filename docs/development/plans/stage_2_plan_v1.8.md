# Stage 2 Plan v1.8 — 生命周期修复、T11/T16 加速与完整 successor 重跑

## Metadata

- plan_id: `stage_2_plan_v1.8`
- stage_id: `S2`
- plan_version: `1.8`
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- approved_by: Muce
- approved_at: 2026-07-28
- base_commit: `29bc5492eb187e934175867311f1efde1af9c876`
- implementation_authority: `docs/spec/system_manual_v1.3.5_final.md`
- preregistration: `configs/research/stage_2/s2p18_t11_t20_repair_v1.json`

## 目标与边界

本 Plan 修复生命周期来源缺口的可观测证据链，并对 T11/T16 做结果等价的性能重构。
它不修改 BTC H2 Primary，不把生命周期改为 H2 Primary，不研究移动止损，不进入
Stage 3。Plan v1.7 及更早的 Run、Manifest、报告和失败状态全部保持不可变。

## 实施门

- Contract Price 来源必须先通过独立归档链、覆盖、重复秒、空秒与 Hash 审计；
- T11/T16 在固定语料上必须语义等价、至少 `2×`、峰值 RSS 不超过 `3 GiB`；
- 允许单元测试、属性测试、固定七日 rehearsal 和性能测量；
- 正式 Run 必须在干净 commit 后由人工单独批准，并按 Authority-before-Run 执行。

## DAG

```text
T11 → T12 → T13 ┐
  └────→ T16 ───┼→ T17 → T18 ┐
T12 → T14 → T15 ┘              ├→ T19 → T20
T11 ────────────────────────────┘
```

每个任务必须完成 producer、Catalog、Manifest、Verify、报告和 Hash 对账后才能解锁下游。
T20 必须分别报告历史 H2、successor H2、两条生命周期轨及性能变化。默认 Stage 3 继续锁定。

## 正式运行编排

正式链使用 `scripts/run_stage2_v18.py`。批准回执必须同时绑定干净代码 SHA、Policy Hash、
预注册 Hash、来源审计 Hash 和完整十 Task adapter plan Hash。Authority 在任何 Run ID
之前冻结十二类命名输入的绝对路径、文件 SHA-256 与语义 binding Hash。Contract Price
输入必须来自覆盖 `[2020-01-01, 2026-07-04)` 的逐分区 Catalog，且逐分区 Hash 在 T11
消费前重验。每个 producer 由 Authority 绑定其可执行文件 Hash，并须
输出绑定同一 Authority、代码 SHA、adapter plan 和上游 receipt Hash 的正式 receipt。

H2 和生命周期的数据流分开：T12–T18 只重跑 canonical Trades H2；Contract Price OHLC
生命周期轨只从 T11 进入 T19/T20，不得成为 H2 标签。旧实现只允许作为数学引擎被新
S2P18 envelope 调用，旧 receipt、Authority、Run、任务身份与固定结果计数不得复用。

Run 使用唯一锁和 append-only checkpoint 链。可恢复进程中断保留同一 Run，并以新的
append-only Task attempt 重试；旧 attempt、checkpoint 与日志不得删除。任一非恢复型
producer、依赖、输入或 Hash 失败，
当前 Run 终态为 FAILED 且保持 unpublished；不得原地修成 PASS。十 Task 完成后才允许
构建总 Catalog/Manifest、创建同卷候选发布、执行完整 Hash Verify，并在 Verify PASS 后
写入 publication receipt。正式 Run 批准与 adapter plan 都必须在新干净 commit 冻结后
另行记录；本实现提交本身不授权执行。
