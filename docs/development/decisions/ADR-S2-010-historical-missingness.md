# ADR-S2-010 — Historical missingness is typed and fail-closed

## Status

APPROVED — 2026-07-22T16:27:27Z by Muce

## Context

S2-T15's 61-bar volatility feature requires one hour of prior complete bars. The first completed
BTC P1 block contains 61 unavailable grid anchors at the accepted historical boundary. This can be
a legitimate causal warmup boundary, but treating every missing value as the same condition would
confuse dataset start, declared gaps, unbound evidence, invalid values and complete zero-activity
windows.

## Proposed decision

Adopt CR-2026-031's mutually exclusive missingness taxonomy and fail-closed actions:

1. Boundary warmup is an explicit exclusion only after an instrument-wide audit proves the source
   boundary and exact expected count.
2. Declared gaps preserve the already approved AMBIGUOUS treatment where applicable.
3. Unbound partitions, receipt drift and Hash drift block the full Run.
4. Complete zero activity and complete zero-observation H2 windows are valid observed states, not
   missing data.
5. No imputation, shortened feature window, silent period shift or missing-as-zero conversion is
   permitted.
6. Every grid, Episode, control and lifecycle row must reconcile once under an availability or
   exclusion state.

## Consequences

The full BTC/ETH audit may reveal more exclusions or a true upstream defect. Either is reported as
evidence rather than corrected after seeing match coverage or delta. No new Authority or formal
Run is permitted until OQ-S2-009 is resolved and the expected exclusion inventory is frozen.
