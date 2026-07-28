# V1.3.5 Dependency Graph

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

Historical Plan v1.2 closure state: S2-T19 and S2-T01～S2-T14 were PASSED while S2-T15 stopped
without a formal published research result. Its successor work did not reuse or mutate that
failed chain. OQ-S2-009/010/011 were subsequently resolved. This paragraph preserves the Plan
v1.2 boundary and is not the current Stage 2 operation projection.

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

## Stage 2 Plan v1.3 successor DAG

Plan v1.2 identities and artifacts stay immutable. Plan v1.3 tasks use the full
`(stage_plan_version, task_id)` identity:

```text
Plan v1.2 sealed T10/T11/T13/T14 evidence
  → S2P13-T20 preregistration freeze
  → S2P13-T11 seven-day theoretical lifecycle
  → S2P13-T12 path extraction
      ├→ S2P13-T13 path metrics ───────────────────────┐
      └→ S2P13-T14 first passage → S2P13-T15 ambiguity ├→ S2P13-T16 conditional baseline
S2P13-T11 + S2P13-T20 ─────────────────────────────────┘
```

Plan v1.3 closed at its approved S2P13-T16 execution ceiling after the final successor completed
serialization, strict consumer readback, reconciliation, Verify and UI projection. The historical
commit-bound approval bound the applicable rehearsal or CR-2026-044 waiver before its Authority
and Run IDs. CR-2026-042 resolves OQ-S2-012; no producer may invent protection/structure facts or
import a Stage 3 rule. OQ-S2-009/010/011 are resolved. Contract Price/Trades remain the approved
Stage 2 H3 price proxy, and CR-2026-038 binds the accepted historical funding source.
S2P13-T17～T21 were not executed; any continuation requires a new approved plan/version and Stage 3
remains locked.

## Stage 2 Plans v1.4–v1.8 successor DAG and current repair

Each later Plan used a new namespaced Task identity and separately approved machine Policy:

```text
verified S2P13-T16
  → Plan v1.4 / S2P14-T17 placebo
  → Plan v1.5 / S2P15-T18 cluster bootstrap
  → Plan v1.6 / S2P16-T19 evidence gate
  → Plan v1.7 / S2P17-T20 final evidence acceptance
  → Plan v1.8 / S2P18-T11–T20 lifecycle repair successor
```

Legacy Plan v1.2 `S2-T15` remains `STOPPED_FAILED_UNPUBLISHED`; it is immutable historical
evidence and does not block its `S2P13-T16` successor. The successor relationship replaces the
capability identity only and never promotes the failed legacy Run into a formal result.

T17 through T20 passed their historical engineering, publication, reconciliation and independent
Verify gates. T20 closed that evidence chain as `STAGE2_NO_GO_CURRENT_EVIDENCE`: BTC and ETH
Primary failed, while lifecycle remained `INCONCLUSIVE_SOURCE_GAP_CENSORING`.

Plan v1.8 reopens implementation only. Its internal DAG is T11→T12→T13/T14→T15→T16→T17→T18→
T19→T20, with T11 also feeding T16 and T19. No downstream task unlocks before its producers,
Catalog, Manifest and Verify pass. Formal execution is gated by clean-commit approval. Stage 2 is
`IN_PROGRESS`, not research PASS, and Stage 3 remains locked.
