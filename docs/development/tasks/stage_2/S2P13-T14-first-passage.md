# S2P13-T14 — First-passage successor

## Metadata

- task_id: S2P13-T14
- stage_plan_version: 1.3
- task_version: 1.0
- status: APPROVED / IMPLEMENTATION AUTHORIZED / RUN GATED
- dependencies: S2P13-T12 PASS

## Contract

Apply the accepted first-passage crossing semantics to the exact S2P13-T12 path handoff.
S2P13-T14 is a sibling of S2P13-T13 and must not consume path-metric output. Preserve all
registered combinations, stable path order, BTC/ETH separation, source-gap AMBIGUOUS semantics
and historical-only evidence labels.

Implementation, tests, isolated rehearsal and read-only UI are authorized. Formal Authority/Run
and later-task execution remain gated by the chain supervisor.
