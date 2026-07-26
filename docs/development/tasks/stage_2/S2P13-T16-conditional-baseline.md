# S2P13-T16 — Conditional-baseline successor

## Metadata

- task_id: S2P13-T16
- stage_plan_version: 1.3
- task_version: 1.1
- status: APPROVED / COVERAGE REPAIR IMPLEMENTED / SUCCESSOR RUN GATED
- dependencies: S2P13-T11 PASS; S2P13-T13 PASS; S2P13-T15 PASS; S2P13-T20 frozen

## Contract

Run the approved outcome-blind conditional baseline using immutable S2-T10 foundation evidence,
the exact S2P13-T11 lifecycle gate, S2P13-T13 metrics, S2P13-T15 ambiguity policy and frozen
S2P13-T20 preregistration. Preserve TRAIN-only bins, all registered combinations, five-control
selection, BTC/ETH separation, complete reconciliation and historical conditional evidence labels.

No legacy accepted Run constant may substitute for a successor handoff. Rehearsal may use isolated
non-formal bins only to exercise production schemas; formal bins remain forbidden until the final
rehearsal passes and a later commit-bound human approval is recorded.

Implementation, tests, isolated rehearsal and read-only UI are authorized. S2P13-T17+ and Stage 3
remain forbidden.

## Coverage repair

CR-2026-045 and ADR-S2-021 replace the control-side daily aggregate gap flag with
`H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1`. Event and control cells must now use the same
window-local gap-before-decision semantics. New reports and Verify records must expose each side's
gap-affected count and rate. The completed predecessor is preserved as engineering PASS but is
research-rejected; this Task file does not authorize a replacement Run.
