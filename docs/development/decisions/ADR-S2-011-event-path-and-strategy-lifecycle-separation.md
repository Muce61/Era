# ADR-S2-011 — Raw event paths and strategy lifecycle are separate evidence objects

## Status

APPROVED DIRECTION — 2026-07-22T16:27:27Z by Muce; implementation blocked by OQ-S2-010

## Context

Fixed event horizons answer what the market did after a MarketEpisode without assuming a position
management rule. A complete strategy instead needs an entry, quantity, exit decisions, costs and
a closure condition. Combining both in one mutable path would allow an exit rule to erase later
market facts and would make it impossible to test whether a time exit was too early.

The proposed survivor hypothesis also creates immortal-time and selection bias if long-lived
events are compared naively with all events. A valid comparison must start at a preregistered
landmark among lifecycles that were all still at risk at that same instant.

## Proposed decision

1. Keep T1-T4 raw event paths immutable and independent of every exit rule.
2. Represent T12-T14 outputs as derived metrics/labels, never as path mutation.
3. Add any full-strategy replay as a separate variable-length evidence family.
4. Reserve `POSITION_FLAT` for real execution. Historical strategy research uses
   `THEORETICAL_FULLY_FLAT` and carries H2 or H3 evidence level on every row/report.
5. Only H3 may calculate `scenario_net_exitable_pnl` and scenario net expectancy. It must not
   reuse the F1/live `estimated_exit_net_pnl` field. Values are conditional proxies, not
   historical executable or live returns.
6. Evaluate delayed activation at frozen landmarks using outcome-blind risk sets and frozen
   subgroup/multiplicity rules.
7. Treat a lifecycle still open at the maximum horizon as right-censored, not as a win, loss or
   silently closed position.
8. Do not use the new study to rewrite the existing T2 Primary or to select a new universal or
   conditional time rule without a separately registered validation experiment.

## Consequences

The raw path remains reusable for multiple exit hypotheses, while a strategy lifecycle can answer
whether a proxy position eventually exits fully. The cost is a new H3 contract and potentially
longer data windows. Implementation remains blocked until OQ-S2-010 freezes exact landmarks,
activation, near-zero, cost, closure and censor definitions.

## Seven-day validation

The raw-path separation passes over 1,211 real T1-T4 rows with byte-identical sources after
T12/T13 consumption. The lifecycle side cannot execute: T11 stops at 600 seconds and 19 Primary
T4/H2 rows are still `EXPIRED`. This confirms that the lifecycle must use a separate
variable-length source and cannot mutate or stretch the accepted T1-T4 event evidence in place.

## Append-only SRP role

本ADR属于[SRP-S2-001](../special_research_points/SRP-S2-001.md)。A层原始路径无豁免；B层
仅声明对锁定回放一次、T1～T4固定600秒边界和U-011统一时间退出基线的局部豁免。三项
豁免尚未逐项获批，当前不生效。数据真实性、H3条件解释、理论完整平仓、右删失、阶段门和
全部未声明规则继续适用。
