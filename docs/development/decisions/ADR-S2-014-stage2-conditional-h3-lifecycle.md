# ADR-S2-014 — Stage 2 may produce bounded conditional H3 lifecycle evidence

## Status

APPROVED — 2026-07-23 by Muce

## Decision

Stage 2 may run one preregistered, isolated H3 lifecycle proxy that compares immediate exit with
continued holding for a maximum of seven days. It uses scenario costs and historical facts, never
fabricated execution. Its evidence level is `H3_HISTORICAL_CONDITIONAL_LIFECYCLE`.

The Task cannot emit `POSITION_FLAT`, realized PnL, unconditional live probability, Stage 3 PASS or
live rules. Stage 3 keeps full ownership of cost calibration, execution-distribution validation,
state-machine replay and its stage gate.

Old T1-T4 paths and accepted T10-T15 evidence are immutable. The lifecycle is a separate
append-only evidence family ending in `THEORETICAL_FULLY_FLAT` or an explicit censor reason.
