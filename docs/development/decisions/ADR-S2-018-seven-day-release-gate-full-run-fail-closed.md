# ADR-S2-018 — Seven-day rehearsal is the release gate; the full Run remains fail-closed

## Status

APPROVED — 2026-07-23 by Muce

## Context

ADR-S2-010 originally required a separate whole-range read-only availability audit before any
formal successor. The source-boundary rehearsal already proved the typed warmup behavior, while
the new Plan v1.3 runner is designed to validate, reconcile and Verify the complete range during
the formal full-data Run.

Requiring both a separate full-range scan and the same fail-closed checks in the formal Run adds a
duplicate pre-execution pass. Muce decided that the final-code seven-day end-to-end rehearsal is
sufficient to decide whether the code and evidence handoffs are ready to start the full Run.

## Decision

The final-code seven-day rehearsal replaces the separate whole-history availability pre-audit as
the `OQ-S2-009` closure gate. It must exercise the real producer and consumer chain, not a fixture
or schema-only test.

This does not waive full-data correctness. During the formal Run:

1. every row and exclusion must reconcile exactly once;
2. boundary warmup and declared gaps must use their frozen typed reasons;
3. complete zero-activity and zero-observation windows remain valid observed states;
4. unknown missingness, unbound partitions and Hash/receipt/source drift fail the Run;
5. no imputation, shortened window, silent skip or missing-as-zero conversion is allowed;
6. no failed full-data result may be published as PASS.

## Compatibility

ADR-S2-010 and CR-2026-031 remain append-only historical records of the original conservative
pre-audit decision. This ADR changes only the release-gate sequence; it does not weaken their
missingness taxonomy or fail-closed actions.

CR-2026-040 later clarifies the governance classification: because the behavior is fully decided,
OQ-S2-009 is `RESOLVED` and the rehearsal is tracked as the independent
`FINAL_CODE_7_DAY_REHEARSAL` execution gate.
