# ADR-S2-010 — Venue Trade ID discontinuity is not sufficient proof of an H2 source gap

## Status

APPROVED — 2026-07-22T15:39:25Z by Muce

## Context

The historical H2 contract consumes official Binance USD-M Futures public Trades. Stage 1
currently detects every positive numeric jump in adjacent `venue_trade_id` values and downstream
T11/T13 treat that jump as a possible missing price observation. In high-density 2025–2026 data,
this turns a roughly 0.14% skipped-ID fraction into source-gap ambiguity for nearly every
three-minute P3/F3 primary path.

Neither the accepted public-data source description nor the official market-trades endpoint
promises integer continuity. ADR-2026-001 also establishes that `venue_trade_id` is an exchange
attribute rather than historical fact identity. Numeric discontinuity is therefore useful audit
evidence, but it is not sufficient proof that a public Trade promised by the accepted source
contract is absent.

Source-contract references are the
[Binance public data README](https://github.com/binance/binance-public-data#trades-1) and the
[official Binance Futures Connector endpoint definitions](https://github.com/binance/binance-futures-connector-python/blob/main/binance/um_futures/market.py#L68-L125).

## Proposed decision

1. Keep historical fact identity as `(instrument, canonical_trade_id)` and stable order as
   `(ts_event_ns, venue_trade_id, canonical_trade_id)`.
2. Preserve every observed venue ID and every discontinuity. Do not fill, renumber, delete or hide
   them.
3. Classify a numeric jump without independent corroboration as
   `VENUE_ID_DISCONTINUITY_UNCORROBORATED`. It is a quality anomaly and sensitivity dimension, not
   an automatic semantic source gap.
4. Reserve `VERIFIED_PUBLIC_TRADE_GAP` for cases where independent immutable evidence proves that
   the accepted public Trades contract is incomplete.
5. Reserve `SOURCE_INTEGRITY_FAILURE` for missing, corrupt, truncated, checksum-invalid,
   Catalog-inconsistent or unbound source objects. These failures remain fail-closed.
6. T13 may emit `AMBIGUOUS / SOURCE_GAP_BEFORE_DECISION` only when a
   `VERIFIED_PUBLIC_TRADE_GAP` intersects the path before a target/stop decision, or when source
   integrity/binding prevents a valid classification. A bare venue-ID jump is insufficient.
7. Report two predeclared projections:
   - main H2 public-archive projection under verified-gap semantics;
   - conservative sensitivity projection under the legacy any-discontinuity semantics.
8. BTC and ETH remain separate. P1/P2/P3 and F0-F3 remain separately reported. No interpretation
   may be selected after observing the event delta.
9. Existing evidence remains immutable and keeps its original semantic version. Revised evidence
   must be append-only, versioned and must not be joined with legacy labels without an explicit
   compatibility declaration.

## Rationale

An ID is evidence about an exchange-assigned identifier, not automatically evidence about the
completeness promise of a public dataset. A universal continuity requirement needs an explicit
source contract or independent reconciliation. Without that proof, turning every skipped integer
into a missing price observation overstates uncertainty and makes ambiguity depend mainly on trade
density rather than demonstrated source loss.

## Consequences

- Stage 1 raw and published canonical Trades remain unchanged.
- Stage 1 quality output needs a new derived semantic version; legacy counts remain available.
- T11, T13, T14 and T15 require explicit impact analysis and append-only successor evidence.
- P3/F3 may recover many classifiable paths, but the direction and magnitude are unknown until a
  preregistered rerun completes.
- The legacy interpretation remains available as a conservative bound rather than being erased.
- Low or negative event delta under the revised rule remains a research result and cannot justify
  another rule change.

## Rejected alternatives

### Keep every numeric jump as a hard H2 source gap

Rejected as the proposed main semantic because integer continuity is not an accepted public-source
guarantee and the rule causes trade-density-driven near-total P3 ambiguity.

### Ignore and stop reporting numeric discontinuities

Rejected because the anomalies are real observed properties and remain useful for audit,
sensitivity analysis and future source reconciliation.

### Fill skipped IDs or synthesize missing Trades

Rejected. Historical Trades, prices, timestamps, quantities and order-side facts must never be
fabricated or interpolated.

### Replace individual Trades with aggTrades

Rejected without a separate approved source/identity/path contract. Aggregate trades cannot be
silently substituted for the accepted H2 individual-Trade evidence.

## Approval and implementation boundary

This ADR and CR-2026-031 were approved by Muce at `2026-07-22T15:39:25Z`. The approved semantic
boundary authorizes the required read-only audit only. Code changes, evidence successors,
Authority, Run and publication remain blocked until that audit passes and the affected Task
versions, rule mappings, reason codes and invalidation graph receive separate approval. S2-T16+
and Stage 3 remain unauthorized.
