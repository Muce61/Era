# ADR-S2-023 — T18 cluster-bootstrap contract

## Status

APPROVED — 2026-07-27 by Muce

## Decision

1. Use `instrument | UTC Monday week_start_ns` from the source real Episode as the cluster identity
   for real, placebo and paired statistics.
2. Bootstrap 5,000 cluster samples with replacement using independently derived PCG64 seeds rooted
   at `20260716`.
3. Calculate two-sided 95% percentile confidence intervals for T16 real delta, T17 placebo delta
   and the complete-case paired real-minus-placebo delta.
4. Calculate null-centered two-sided bootstrap p-values with add-one correction. Exclude the sole
   Primary cell from Benjamini-Hochberg correction; correct each BTC/ETH, metric and analysis-scope
   family at `q <= 0.10`.
5. Use integer weekly sufficient statistics and bounded NumPy float64 batches internally. No
   binary float may enter canonical JSON, Parquet evidence or Hash payloads; published statistics
   are Decimal strings quantized to `1e-18`.
6. Report FOLD, PERIOD and OVERALL scopes. Fewer than two clusters yields
   `INSUFFICIENT_CLUSTERS`, not a fabricated interval.

## Consequences

The result is `STATISTICAL_EVIDENCE_ONLY_FINAL_GATE_PENDING`. T18 reports uncertainty and
multiplicity evidence but does not apply the final F1–F10 or ETH replication decision, does not
report real execution performance and does not unlock Stage 3.
