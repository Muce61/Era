# ADR-S2-022 — Same-stratum non-event placebo

## Status

APPROVED — 2026-07-27 by Muce

## Decision

Use a T16-pool, outcome-blind placebo:

1. For each matched real event, select one unique-in-group non-event candidate with the frozen
   L0–L4 matching order and seed `20260716`.
2. Exclude the real event's original five controls, overlapping information spans and registered
   same-family events.
3. Match five controls to the selected fake event. If fewer than five exist, record UNMATCHED and
   do not replace the fake event.
4. Seal all selections before reading outcome fields.
5. Reuse T16's verified H2 outcome matrices and 30-combination order.

## Consequences

The method measures whether similarly constructed non-events produce a spurious descriptive
signal. It does not perform clustering, bootstrap, CI, FDR or a final hypothesis decision.
