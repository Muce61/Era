# S2P13-T12 — Path extraction successor

## Metadata

- task_id: S2P13-T12
- stage_plan_version: 1.3
- task_version: 1.0
- status: APPROVED / IMPLEMENTATION AUTHORIZED / RUN GATED
- dependencies: S2P13-T11 PASS; immutable S2-T10

## Contract

Reuse the accepted path-extraction computation through an explicit Plan v1.3 source binding.
S2P13-T11 is a required PASS/Run/Hash execution gate only. Raw event paths continue to be derived
exclusively from immutable S2-T10 MarketEpisode and Stage 1 price/trade evidence. Lifecycle rows,
exit states and lifecycle outcomes are forbidden inputs.

Preserve BTC/ETH separation, UTC windows, H1/H2 evidence labels, historical identity
`(instrument, canonical_trade_id)` and stable H2 order
`(ts_event_ns, venue_trade_id, canonical_trade_id)`.

Implementation, tests, isolated rehearsal and read-only UI are authorized. Formal Authority/Run
and S2P13-T13+ execution remain gated by the chain supervisor.
