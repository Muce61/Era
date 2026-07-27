# S2P14-T17 — Placebo signal

## Metadata

- task_id: S2P14-T17
- task_version: 1.0
- stage_plan_version: 1.4
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- dependency: verified formal `S2P13-T16`
- approved_by: Muce
- approved_at: 2026-07-27

## Rules

- `EVENT-CONSUME-MARKET-EPISODE`
- `STRATEGY-V1-PRICE-ONLY-HISTORICAL`
- `DATA-HISTORICAL-NO-FAKE-EXECUTION`
- `INV-005`
- `INV-011`

## Allowed files

- `src/era100x/research/stage_2/baselines/placebo/**`
- `tests/research/stage_2/baselines/placebo/**`
- `scripts/run_stage2_placebo.py`
- CR-approved read-only progress UI files
- Plan v1.4 policy/configuration, this Task, validation and traceability
- new append-only external Plan v1.4 evidence after separate formal approval

## Forbidden files and actions

- `docs/spec/**`
- Plan v1.3, policy v2 and all old evidence
- Stage 1, T16 producer semantics and trading execution
- T18–T21 and Stage 3
- any outcome read before the blind-selection seal

## Acceptance

Directed tests and the complete quality gate must pass. Formal engineering PASS additionally
requires one commit-bound approval, Authority-before-Run, 456-group reconciliation, independent
Verify and evidence-driven UI PASS. Research remains
`DESCRIPTIVE_ONLY_CLUSTERING_BOOTSTRAP_PENDING`.
