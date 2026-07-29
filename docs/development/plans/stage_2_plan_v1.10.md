# Stage 2 Plan v1.10：密封证据复用、真实断点恢复与全流程性能优化

## Metadata

- plan_id: `stage_2_plan_v1.10`
- stage_id: `S2`
- plan_version: `1.10`
- status: `APPROVED / IMPLEMENTED_VALIDATED / PREPARE_PENDING / FORMAL RUN NOT AUTHORIZED`
- approved_by: `Muce`
- approved_at: `2026-07-29`
- decision: `ADR-S2-029`
- predecessor: `stage_2_plan_v1.9 / SUPERSEDED_UNEXECUTED`
- implementation_authority: `docs/spec/system_manual_v1.3.5_final.md`

## 决定

Plan v1.10 使用 `S2P110-T11`～`S2P110-T20`。它保留 Plan v1.9 的四命令 Solo Runtime，
但将输入准备改为密封证据驱动，并对语义未变化的 T12～T18 使用只读 adoption。
旧证据不复制、不改名、不重写；任何 adoption 不兼容均在 Authority 前失败关闭，不自动
退回全量重跑。

```text
prepare -> sealed inputs/adoption lock -> one exact approval
run     -> T11 new lifecycle
        -> T12-T18 sealed adoption descriptors
        -> T19/T20 new synthesis
        -> final Manifest/Verify -> atomic publication
```

## Task DAG

```text
T11 -------------------------------┐
T12 -> T13 --------┐               │
  └--> T14 -> T15 -+-> T16 -> T17 -> T18 -> T19 -> T20
```

T16 不再绑定未消费的 T11 lifecycle output。T11 与 H2 只在 T19 汇合。

## 硬门

1. `prepare` 只采用 Hash 闭合的 Stage 1、T10、supplement、funding 和历史正式证据。
2. 不允许对全量 canonical Trades price 列执行 Python 对象物化或 `to_pylist()`。
3. T12～T18 必须逐项通过 sealed-adoption validator；不兼容即
   `BLOCKED_SEALED_ADOPTION_INCOMPATIBLE`。
4. 输入锁必须记录 `SEALED_INCREMENTAL_V1`、adoption bundle Hash 和所有定向复核。
5. Authority 必须绑定 clean commit、Policy、preregistration、contract bundle、
   inputs-lock 和 adoption bundle Hash，并先于 Run。
6. retryable Task attempt 必须从已验证 checkpoint cursor 继续；terminal failure 不可恢复。
7. Task 完成后写一次不可变文件清单；下游不重复 Hash 内容，最终 Verify 仍完整重验新输出。
8. 历史 H2 Primary FAIL 和 lifecycle INCONCLUSIVE 不变；Stage 3 永远锁定。

## 研究边界

BTC/T2/20bp/25bp、matching、AMBIGUOUS、30-cell、TRAIN-only quintile、cluster、seed 和
BTC/ETH 隔离不变。Contract Price 只提供粗粒度历史边界，不代表真实成交。不得研究移动
止损、真实 PnL、Stage 3 或用 lifecycle 覆盖 H2。

## 执行状态

本 Plan 的批准只允许实现、fixture、隔离性能验证、冻结干净 commit，以及之后执行一次
真实 `prepare`。`prepare` 产生精确 inputs-lock 后必须停止；Authority、Run、resume 和
publication 仍需要新的 commit/input-lock/adoption-bundle 人工批准。
