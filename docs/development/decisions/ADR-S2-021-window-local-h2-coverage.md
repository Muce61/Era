# ADR-S2-021 — Window-local H2 coverage parity

## Status

APPROVED — 2026-07-26 by Muce

## Context

T13 event labels detect gaps from adjacent facts inside each extracted H2 path and only reject a
label when a gap precedes its decision. T16 controls instead used a daily aggregate quality flag,
so an anomaly anywhere on a date invalidated every selected control window on that date. The two
sides therefore did not measure comparable observability.

## Decision

Freeze `H2_WINDOW_INTERNAL_GAP_BEFORE_DECISION_V1` as the shared event/control coverage contract.
For controls, detect venue-ID gaps and reversals from adjacent facts ordered by
`(ts_event_ns, venue_trade_id, canonical_trade_id)` inside `[anchor, anchor+horizon)`. Apply the
same gap-before-decision rule as T13. Keep complete zero-Trade windows as
`AMBIGUOUS / NO_OBSERVATIONS`, keep unbound or hash-drifted partitions as run-level failures, and
do not treat conflicting venue IDs as missing facts.

Every future T16 summary and Verify must report event and control gap-affected rates separately.
Equal rates are not assumed or required, but both rates must come from this exact contract and
remain visible for human research acceptance.

## Consequences

The completed predecessor remains technically reproducible but cannot support research claims.
Only a new, separately approved T16 successor may produce replacement research evidence. T11–T15
need not be recomputed because their sealed inputs and event-side semantics are unchanged.
