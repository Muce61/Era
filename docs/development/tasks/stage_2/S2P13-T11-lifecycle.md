# S2P13-T11 — Seven-day theoretical lifecycle

## Metadata

- task_id: S2P13-T11
- stage_plan_version: 1.3
- task_version: 1.0
- status: APPROVED / IMPLEMENTATION AUTHORIZED / RUN GATED
- dependencies: S2-T10 PASS; S2P13-T20 preregistration frozen
- approved_by: Muce
- approved_at: 2026-07-23

## Contract

Implement only V1.3.5 §14.2. Consume sealed MarketEpisode and registered entry/path facts read-only.
Produce paired immediate-exit and continue-holding lifecycle evidence. Preserve BTC/ETH separation,
Decimal arithmetic, source lineage, explicit scenario IDs, complete quantity reconciliation and
right-censor reasons.

Contract Price/canonical Trades are labelled `CONTRACT_PRICE_H3_PROXY`, never historical Mark.
T2 20bp is an auxiliary First Passage observation. The continuation target is dynamic terminal
ticket doubling after costs and accumulated published funding, approximately 136bp in the
zero-funding main-cost example.

Publish `PRIMARY_HISTORICAL_ACTUAL`, adverse 1.5x/2x and no-credit funding tracks separately.
Stress requires the same bound historical source and cannot turn missing funding into zero.
Theoretical liquidation is Contract-Price net margin depletion at `scenario_net_pnl <= -8U`.

Allowed implementation paths are
`src/era100x/research/stage_2/lifecycle/**`,
`tests/research/stage_2/lifecycle/**`, the direct CLI, governance/traceability, validation and
read-only progress projection.

Forbidden are Stage 1, sealed T10-T15 artifacts, real execution, Stage 3 implementation, S2P13-T17+
execution and any claim of real return or live probability.

## Required validation

Directed lifecycle tests, full quality gate and a real seven-day end-to-end rehearsal are mandatory
before Authority or Run creation. Primary right-censor count above zero yields
`INCONCLUSIVE_RIGHT_CENSORING`, never PASS.

## CR-2026-043 source supplement amendment

The physically truncated sealed `BTCUSDT/2022-03-01` Trade Parquet remains immutable failure
evidence. ADR-S2-020 permits one exact-key, append-only rebuilt partition only when it reproduces
the original receipt's byte Hash, logical Hash, row count and quality statistics from the already
accepted official monthly archive. Policy, approval and ChainAuthority must bind its acceptance
Hash. The normal seven-day release rehearsal and an additional seven-day scope containing the
repaired date must both pass before a successor can be approved.
