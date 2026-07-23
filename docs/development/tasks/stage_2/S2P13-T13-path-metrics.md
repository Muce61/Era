# S2P13-T13 — Path metrics successor

## Metadata

- task_id: S2P13-T13
- stage_plan_version: 1.3
- task_version: 1.0
- status: APPROVED / IMPLEMENTATION AUTHORIZED / RUN GATED
- dependencies: S2P13-T12 PASS

## Contract

Compute the accepted historical path metrics from the exact S2P13-T12 handoff. No Plan v1.2 Run
or Snapshot constant may satisfy the successor input. Preserve raw path identity and windows,
BTC/ETH separation, H1/H2 evidence labels, Decimal determinism, missingness and lineage.

Implementation, tests, isolated rehearsal and read-only UI are authorized. Formal Authority/Run
and later-task execution remain gated by the chain supervisor.
