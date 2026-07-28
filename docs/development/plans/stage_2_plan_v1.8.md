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
