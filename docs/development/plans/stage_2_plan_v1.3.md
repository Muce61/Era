# Stage 2：生命周期与事件研究 Plan v1.3

## Metadata

- stage_id: S2
- plan_version: 1.3
- plan_id: stage_2_plan_v1.3
- status: APPROVED
- created_from_spec_version: V1.3.5
- source_commit: `6ad4309edcbb882f17c8f07a1a297323c7fd36ac`
- supersedes_for_new_execution: stage_2_plan_v1.2
- approved_by: Muce
- approved_at: 2026-07-23

## Boundary

Plan v1.2 evidence stays valid under its original identity. New execution uses namespaced IDs and
append-only successor evidence. BTC and ETH are separate, V1 is long-only/isolated/single-position,
and no historical execution fact may be fabricated.

## Task map

| Task | Capability |
| --- | --- |
| S2P13-T11 | seven-day theoretical lifecycle |
| S2P13-T12 | path extraction successor |
| S2P13-T13 | path metrics successor |
| S2P13-T14 | first-passage successor |
| S2P13-T15 | ambiguity successor |
| S2P13-T16 | conditional-baseline successor |
| S2P13-T17 | placebo, not authorized |
| S2P13-T18 | clustering, not authorized |
| S2P13-T19 | cluster bootstrap, not authorized |
| S2P13-T20 | preregistration Manifest |
| S2P13-T21 | Stage 2 acceptance, not authorized |

## DAG and execution limit

```text
S2P13-T20 → T11 → T12 → T13
                       └→ T14 → T15
T13 + T15 + T20 + T11 → T16
```

This approval permits implementation and validation through T16 only. T17-T21 and Stage 3 remain
locked. OQ-S2-009/010/011 are resolved. Formal execution additionally requires the independent
`FINAL_CODE_7_DAY_REHEARSAL` gate to PASS, a clean commit, exact governance hashes and a human run
receipt. No separate whole-history pre-audit is required, but the formal full-data Run must
validate and reconcile the complete range and fail closed on unknown missingness or drift.

## Lifecycle Primary

The frozen numeric, cost, censor and pass contracts are V1.3.5 §14.2. T11 preserves old paths and
creates a separate evidence family. Primary is BTC, T2 auxiliary target/stop 20/25bp and landmark
8 minutes. The 20bp target is First Passage evidence only; continuation closes at dynamic net
ticket doubling, approximately 136bp under the no-funding main-cost example. ETH and all other
registered combinations are Secondary and must be fully reported.

Funding is reported in separate tracks: signed historical settlements are Primary; adverse 1.5x,
2x and no-credit transforms are Stress. Every Stress row binds the same historical source and
cannot replace a missing Primary row. Scenario liquidation is Contract-Price net margin depletion
at `scenario_net_pnl <= -8U`, not historical Binance liquidation.

## Long-run rule

Before every full-data action, run seven complete UTC days through producer, serialization,
checkpoint/receipt, strict consumer read-back, reconciliation, Verify and UI. Any failure invalidates
the rehearsal and requires a full restart after repair.
