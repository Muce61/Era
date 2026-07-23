# CR-2026-031/032 Seven-Day Audit Validation

## Conclusion

- Audit window: `[2020-01-01T00:00:00Z, 2020-01-08T00:00:00Z)`.
- Input: accepted read-only T10/T11/T12/T13 evidence; BTC and ETH separate.
- Feature availability and strict serialization: **PASS**.
- Raw event-path non-pollution: **PASS**.
- Theoretical-full-lifecycle handoff: **BLOCKED**.
- Formal Authority / Binning Set / Run ID / research result created: **0 / 0 / 0 / 0**.
- S2-T16+ executed: **NO**.
- Stage 3 entered: **NO**.

This is an isolated simulation/audit result, not a strategy result and not evidence of live return.

## Acceptance criteria frozen before the clean rerun

- exactly seven complete UTC days and 10,080 minute-grid anchors per instrument;
- real accepted inputs and separate BTC/ETH accounting;
- the known source-boundary warmup must be typed rather than filled or shortened;
- T1-T4 raw paths must remain byte-identical after T12/T13 consumption;
- every raw path must bind exactly one H1 and one H2 T12 row and one H1 and one H2 T13 row;
- strict Parquet/Decimal/JSON receipt read-back and quantity reconciliation;
- no OQ-S2-010 value, H3 PnL, `POSITION_FLAT`, Authority or Run may be invented.

## First attempt and audit-tool bug

The first run at code commit `9c38c53` stopped before producing a report. The checker incorrectly
required every consecutive anchor across the full seven days to differ by exactly 60 seconds.
`CONTROL_GRID_1M_DAILY_OFFSET_V1` intentionally derives a new 0-59 second offset for each UTC day,
so the interval across midnight is not necessarily 60 seconds even though every daily grid is
correct.

The correction validates each UTC day independently: exactly 1,440 unique anchors and 60-second
spacing within the day, while allowing the frozen deterministic offset to change at midnight. A
regression test covers seven different daily offsets. The failed directory remains preserved at
`/private/tmp/s2t-cr031-cr032-seven-day-audit-9c38c53`.

## Clean rerun evidence

The complete audit restarted from the beginning at clean commit
`be507ff55d9036fb4c6068738fb21ada2e714ef8` in
`/private/tmp/s2t-cr031-cr032-seven-day-audit-be507ff`.

### Feature availability

| Instrument | Grid anchors | Valid | Boundary warmup unavailable | Activity unavailable | Context unavailable |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 10,080 | 10,019 | 61 | 0 | 0 |
| ETHUSDT | 10,080 | 10,019 | 61 | 0 | 0 |
| Total | 20,160 | 20,038 | 122 | 0 | 0 |

BTC exclusions run from `2020-01-01T00:00:09Z` through `01:00:09Z`; ETH exclusions run from
`2020-01-01T00:00:28Z` through `01:00:28Z`. Each series contains 61 one-minute anchors. No value
was filled, interpolated, shortened or converted to zero. This seven-day PASS does not replace the
required whole-history BTC/ETH audit under OQ-S2-009.

### Raw event-path non-pollution

| Instrument | Raw T1-T4 rows | T12 rows | T13 rows | Early-decision cells | T4 H2 rows | T4 Primary EXPIRED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 583 | 1,166 | 1,166 | 4,116 | 27 | 10 |
| ETHUSDT | 628 | 1,256 | 1,256 | 8,448 | 25 | 9 |
| Total | 1,211 | 2,422 | 2,422 | 12,564 | 52 | 19 |

Every raw path has exactly one H1 and one H2 row in both T12 and T13. Derived identities, source
snapshot bindings and requested/source window endpoints match T11. All T11 episode-path, H2-slice,
lineage and quality file Hashes were identical before and after the audit. Early T13 decisions did
not truncate or rewrite the raw path. The event-research half of CR-2026-032 therefore passes this
seven-day audit.

### Theoretical full lifecycle

The lifecycle handoff is correctly `BLOCKED` for three independent reasons:

1. OQ-S2-010 executable landmark, activation, near-zero, cost, exit and censor values remain open.
2. No approved `THEORETICAL_FULLY_FLAT` lifecycle schema/consumer exists.
3. Accepted T11 event paths stop at T4/600 seconds. In this seven-day window, 19 of 52 H2 T4 rows
   are still `EXPIRED` for the Primary `target=20|stop=25` cell, proving that a full-lifecycle
   consumer would need evidence after the current maximum raw horizon.

This is a scope/contract gap, not permission to extend T11 in place or choose an exit rule after
seeing outcomes. The future lifecycle source must be a separate variable-length evidence family
with an approved maximum right-censor horizon and H3 contract.

## Strict verify

- audit report Hash: `a47b6488606c21e82c282374f3a6571189d04d4f86b8f181c66076dce911b344`
- audit receipt Hash: `fed27311c1f21cb3105ef86eea2ced0cf74714e9daa18f24c593d6a50acaa905`
- strict files read back: 5
- receipt/Parquet row counts and byte Hashes: **PASS**
- Verify status: **PASS**, with underlying audit status correctly retained as `BLOCKED`.
- UI projection: not in the approved scope; no UI file was changed and no PASS was projected.

## Repository quality

- directed conditional-baseline pytest: **67 passed**;
- Ruff format: **310 files PASS**;
- Ruff lint: **PASS**;
- strict mypy: **208 source files PASS**;
- strict Traceability: **32 rules, 41 INV, 18 contracts, 52 reasons, 10 gates PASS**;
- complete repository pytest: **608 passed**.

## Go / No-Go

- GO: continue the separate whole-history read-only OQ-S2-009 availability audit.
- NO-GO: new T15 Authority/bin/Run.
- NO-GO: theoretical-full-lifecycle implementation until OQ-S2-010 and a separate variable-length
  source/Task contract are approved.
- NO-GO: S2-T16+, Stage 3 execution, F1, testnet or real funds.
