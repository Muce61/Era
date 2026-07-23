# ADR-S2-019 — Minimum price-only lifecycle producer

## Status

APPROVED — 2026-07-23 by Muce

## Context

CR-2026-041 exposed that the lifecycle model contained protection and structure booleans without
an approved historical source. It also exposed missing producer choices for Contract Price versus
Trade ordering, funding notional and single-position collision handling. Defaulting unknown
execution facts to `false` or importing Stage 3 rules would change research results without
authority.

## Decision

Stage 2 reports protection and structure as `NOT_MODELLED_STAGE2` and does not trigger those exits.
Contract Price 1s owns scenario valuation, activation, near-zero, theoretical liquidation and
funding notional. Canonical Trades own target/stop crossing. Contract risk state is evaluated
before Trade crossings in the same second.

The fixed proxy quantity is `800 / entry_price`. Signed funding cash flow at a settlement is
`quantity × settlement Contract Price × historical rate`. Immediate and continue policies replay
separate single-position timelines; occupied Episodes are skipped and a right-censored position
never becomes assumed flat.

## Consequences

The lifecycle remains a bounded H3 historical conditional proxy. It does not claim real protection,
real structure exits, Mark Price, actual funding debits, real liquidation or live probability.
Stage 3 retains ownership of calibrated protection, structure and execution-state behavior.
