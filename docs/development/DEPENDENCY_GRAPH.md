# V1.3.4 Dependency Graph

```text
Stage 0 → Stage 1 → Stage 2 → Stage 3 → Stage 4
   └─ S0-T12 Execution Capability ─┐
Stage 4 ────────────────────────────┴→ Stage 5 → Stage 6
Stage 6 + approved F1 evidence → Stage 7 → Stage 8 → Stage 9
```

## Shared Contracts

| Producer | Contract | Consumers | Invalidation |
| --- | --- | --- | --- |
| S0-T03～T09 | configuration, RuleMetadata, primitives, manifest/audit, PnL, core contracts, states/reasons | all later Stages | schema, enum, formula, config precedence or identifier change |
| S1-T02～T12 | schemas, normalized Trades/bars, catalog, hashes, time splits | Stages 2～4 | data/schema/hash/split/purge change |
| S2-T01～T19 | key levels, episodes, labels, clusters, experiment manifest | Stages 3～5 | event/label/cluster/manifest change |
| S3-T01～T15 | H3 scenarios, replay and conditional probability | Stages 4,5,7,9 | cost/latency/exit/replay change |
| S0-T12 + Stage 5 evidence | capability facts and F1 distributions | Stages 6～7 | Binance API/SDK/account mode or observed distribution change |
| Stage 6 protocol | execution/state/closure evidence | Stages 7～8 | transaction/state/fault-test change |
| Stage 8 rounds | final round results | Stage 9 | Round definition, sample or execution attribution change |

Within a Stage, read-only audit/schema documentation may run in parallel where Task dependencies allow. Different data sources or report views may run in parallel only after their shared contract is frozen. Tasks must not concurrently modify configuration precedence, schema registry, PnL formulas, event identity/labels, ExitEpoch/ExitOrderLeg transactions, state/Reason enums, RoundState, or the same manifest/baseline. Acceptance Tasks depend on every prior Task in their Stage.

An upstream Stage marked REOPENED causes every consumer of changed contracts to become INVALIDATED. Recovery requires impact analysis, a new approved Plan version, regression, and re-acceptance; old evidence remains archived and must not be overwritten.
