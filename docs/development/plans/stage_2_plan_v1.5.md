# Stage 2 Plan v1.5 — Cluster bootstrap

## Metadata

- plan_id: `stage_2_plan_v1.5`
- stage_id: `S2`
- plan_version: `1.5`
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- approved_by: Muce
- approved_at: 2026-07-27
- source_commit: `ab4a7a8fa06a6ac9f5733ceab2e10b9a61bf8957`
- implementation_authority: `docs/spec/system_manual_v1.3.5_final.md`

## Boundary

Plan v1.4 and its final T17 successor remain immutable historical evidence. This Plan authorizes
only `S2P15-T18` cluster-bootstrap implementation, tests, read-only source audit, format smoke and
UI projection. A formal Run remains gated by a later commit-bound approval. T19–T21 and Stage 3
remain locked.

## DAG

```text
S2P13-T16 verified formal evidence
  + S2P14-T17 verified formal evidence
  → S2P15-T18 cluster bootstrap
```

## Evidence statement

T18 produces statistical H2 historical evidence for real-event, placebo and paired contrasts.
Engineering PASS and statistical results remain separate. T18 does not issue the final Stage 2
Primary or ETH replication decision and cannot authorize Stage 3.
