# ADR-S2-009 — S2-T15 v1.4 Conditional Random Baseline

## Status

APPROVED — 2026-07-22T02:25:41Z by Muce

## Context

ADR-S2-004 froze the broad L0-L5 design but left OQ-S2-005 executable details undefined.
ADR-S2-006 is already assigned to Feature Foundation and cannot be reused. Manual §13.1 requires
distance to key level, and §13.3 requires rolling time splits and a purge covering the complete
feature/outcome span. T14 publishes aggregate ambiguity policy rather than Episode rows.

## Decision

Use the exact CR-2026-026 contract. In particular:

1. Freeze causal 61-bar RMS volatility and complete 60-second Trades activity formulas.
2. Reuse the accepted S2-T07 closed-1H causal EMA20 implementation for control context.
3. Enable causal active-key-level distance, freeze TRAIN-only distance quintiles by
   instrument/period/fold/parameter set and never relax that quintile.
4. Use the fixed five-block expanding folds F0-F3; only F3 is HOLDOUT.
5. Require the full `[anchor-3600s, anchor+600s)` information span inside one evaluation split.
6. Select controls without outcomes. One H2 path gets one five-control selection shared by the
   frozen 30 target/stop cells.
7. Bind event labels to T13. Bind T14 only as aggregate AMBIGUOUS policy evidence.
8. Preserve T13 H2 semantics: complete zero-observation windows are AMBIGUOUS; source binding
   failure is a run-level hard failure.
9. Report historical conditional evidence only; T15 cannot decide the Stage 2 Primary hypothesis.

## Consequences

The baseline is deterministic and cannot choose controls from their outcomes. More Episodes may
be UNMATCHED because distance, parameter, timing and split remain exact. Low coverage or negative
delta is a research result, not permission to change the contract. Any listed contract change
invalidates Authority, bin snapshots and Run and requires a new CR/ADR/task version.
