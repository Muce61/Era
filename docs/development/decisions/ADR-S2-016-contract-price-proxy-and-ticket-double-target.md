# ADR-S2-016 — Contract Price is the Stage 2 H3 proxy and 20bp is auxiliary

## Status

APPROVED — 2026-07-23 by Muce

## Decision

Stage 2 lifecycle price comparisons use the same Contract Price/canonical Trade historical path
already authorized by V1.3.5. Reports must call this a proxy and set
`historical_mark_price_claim=false`.

The T2 20bp crossing is auxiliary evidence. It does not terminate the continuation policy. The
continuation target is the first observation where net scenario PnL is at least the original 10U
ticket, making terminal ticket equity at least 20U. With 8U margin, 100x proxy notional and 11bp
main cost, the no-funding threshold is approximately 136bp. Funding changes the exact threshold.

## Consequences

The engine must evaluate ticket equity after costs and accumulated funding rather than hard-code a
136bp exit. A 20bp crossing can be reported while the position remains alive. This decision does
not provide missing funding rows, authorize zero funding, freeze a live liquidation working type,
or unlock Stage 3.
