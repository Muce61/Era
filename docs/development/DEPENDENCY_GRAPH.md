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
| S2-T19, S2-T01～T18 | preregistered manifest, key levels, episodes, labels and clusters | S2-T20, Stages 3～5 | manifest/event/label/cluster change |
| S3-T01～T15 | H3 scenarios, replay and conditional probability | Stages 4,5,7,9 | cost/latency/exit/replay change |
| S0-T12 + Stage 5 evidence | capability facts and F1 distributions | Stages 6～7 | Binance API/SDK/account mode or observed distribution change |
| Stage 6 protocol | execution/state/closure evidence | Stages 7～8 | transaction/state/fault-test change |
| Stage 8 rounds | final round results | Stage 9 | Round definition, sample or execution attribution change |

Within a Stage, read-only audit/schema documentation may run in parallel where Task dependencies allow. Different data sources or report views may run in parallel only after their shared contract is frozen. Tasks must not concurrently modify configuration precedence, schema registry, PnL formulas, event identity/labels, ExitEpoch/ExitOrderLeg transactions, state/Reason enums, RoundState, or the same manifest/baseline. Acceptance Tasks depend on every prior Task in their Stage.

An upstream Stage marked REOPENED causes every consumer of changed contracts to become INVALIDATED. Recovery requires impact analysis, a new approved Plan version, regression, and re-acceptance; old evidence remains archived and must not be overwritten.

## Stage 2 Plan v1.2 Task DAG

```text
Stage 1 PASSED / VALID + Plan APPROVED + OQ cleared
  → S2-T19
  → S2-T01 → T02 → T03 → T04 → T05 → T06 → T07
S2-T19 + Stage 1 H2 Trades → S2-T08
S2-T06 + T07 + T08 → S2-T09
S2-T01～T09 PASS + locked Group-1 Manifest → S2-T10
S2-T10 → T11 → T12
              └→ T13 → T14
S2-T12 + T14 + T19 → T15, T16
S2-T10 + T14 + T19 → T17
S2-T15 + T16 + T17 → T18
S2-T01～T19 PASS → T20
```

S2-T19 is the first preregistration capability and has no dependency on another Stage 2 Task. S2-T01～T09 own fixture capability only; S2-T10 exclusively owns full candidate generation. The graph must remain acyclic and all Stage 2 Task references must resolve before approval.

Current approval state: Plan v1.2 remains APPROVED. S2-T19 and S2-T01～S2-T14 are PASSED. S2-T15 is STOPPED with no formal published research result; only its approved read-only audit/verification scope may continue while OQ-S2-009/010/011 remain open. S2-T16～S2-T18 and S2-T20 remain DRAFT_NOT_APPROVED, Groups 2～4 remain unexecuted, and Stage 3 remains locked. SRP-S2-001 and the proposed variable-length lifecycle study add no executable edge to this DAG.

CR-2026-014 advances only the internal S2-T10 execution version to v1.12. Its bounded sequence is
`processing-day cache → deterministic month workers → Foundation/Group-1 publication → exact Run-A
comparison`; it changes no Task edge and cannot authorize S2-T11 or any later Task.

### S2-T10 v1.8 internal hybrid execution

```text
isolated CR-2026-006 Run A release child ───────────────┐
                                                        ├→ exact semantic comparison → S2-T10 PASS
Stage 1 + locked prereg/config + CR-2026-007/008         │
  → complete Feature Foundation → fresh V2 Run B ───────┘
```

The legacy CR-2026-006 parent and its legacy Run B are suppressed. These are internal phases of
S2-T10, not additional Task nodes, and do not authorize S2-T11 through S2-T20. A Run A failure, V2
Foundation failure, Run B failure or semantic mismatch stops S2-T10; no branch can rescue another.

CR-2026-015 advances only the internal S2-T10 execution version to v1.13. It adds no Task edge:
terminal Run B audit → new Authority/preflight → verified monthly evidence adoption → final packing
→ release → verify → exact Run A/Run B comparison. It never authorizes S2-T11 through S2-T20.

CR-2026-018 and CR-2026-019 complete that existing edge without adding a new Task: the fixed Run
published and verified 80,784 partitions, then matched all 61,776 Group-1 partitions against Run A
with zero differences. The `S2-T10 → T11` dependency is factually satisfied. S2-T11～S2-T14 were
subsequently approved, executed, verified and accepted; those later facts do not authorize T15 writes,
S2-T16+ or Stage 3.
