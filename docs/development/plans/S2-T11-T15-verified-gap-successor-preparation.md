# S2-T11 through S2-T15 verified-gap successor preparation

## Metadata

- preparation_id: `S2-T11-T15-VERIFIED-GAP-SUCCESSOR-PREP-v0.1`
- status: `DRAFT / READY_FOR_HUMAN_SCOPE_APPROVAL`
- source_commit: `78a4648fa4bbb36742e0409376b65cead3d18332`
- governance: [CR-2026-031](../changes/CR-2026-031.md) and
  [ADR-S2-010](../decisions/ADR-S2-010-venue-trade-id-discontinuity.md)
- approved_activity: read-only audit and preparation only
- implementation_authority: `FORBIDDEN`
- formal_authority_or_run_authorized: `NONE`
- later_tasks_authorized: `NONE`
- Stage_3: `LOCKED`

## Purpose

Prepare an append-only rerun of S2-T11 through S2-T15 under the approved distinction between an
uncorroborated numeric venue Trade ID discontinuity and a verified public-Trade gap. This document
freezes the proposed dependency boundary, rehearsal gates, evidence inventory and stop conditions.
It does not approve code changes, create an Authority, create a Run ID or publish a revised result.

## Applicable rules

- `EVENT-CONSUME-MARKET-EPISODE`
- `STRATEGY-V1-PRICE-ONLY-HISTORICAL`
- Historical fact identity remains `(instrument, canonical_trade_id)`.
- Stable Trade ordering remains `(ts_event_ns, venue_trade_id, canonical_trade_id)`.
- BTC and ETH remain separate.
- H1/H2/H3 remain historical evidence and must not be described as real returns.
- Existing sealed evidence is immutable; every revised artifact is append-only and versioned.

## Why S2-T12 is in the successor chain

S2-T12 directly consumes the sealed S2-T11 Manifest and propagates S2-T11 path quality into its
metric rows. The accepted S2-T12 Catalog currently reports:

| Instrument | Metric rows | `COMPLETE` | `WITH_GAPS` |
| --- | ---: | ---: | ---: |
| BTCUSDT | 440,402 | 8,366 | 432,036 |
| ETHUSDT | 625,014 | 23,242 | 601,772 |

Reusing that S2-T12 output after changing the T11 quality semantic would mix two incompatible
contracts. S2-T12 must therefore receive its own append-only successor even though its MFE, MAE
and timing formulas do not change.

## Immutable accepted and failed evidence inventory

The following evidence must remain unchanged and continues to describe its original contract:

| Task | Accepted or diagnostic evidence | Counts and bindings |
| --- | --- | --- |
| S2-T11 v1.3 | Run `stage2-s2t11-paths-20260721T023117Z-029707f3c111`; Manifest `d4d6a2f5c72a9fb8c964585a009d2c11048b1baa34432d3d16fb68ee9ff3979c`; Catalog `82f065f1af9fb39a597572fd4ae0b1f7fed4b05e6fb046726486b5c855189362` | 220,201 BTC and 312,507 ETH Episodes; 298,196 BTC and 416,322 ETH H2 slices |
| S2-T12 v1.3 | Run `stage2-s2t12-metrics-20260721T040435Z-de9aaea56f2a`; Manifest `482a9a8c3a3d3bb219155c50f2f3cedf20769d04e1cadc5beee792e59b12530d`; Catalog `d1a9fa0224ae20dabe1611337e998109463cb0ccc2ae4ac874373204d43eb422` | 1,065,416 metric rows; binds the accepted T11 Manifest |
| S2-T13 v1.3 | Run `stage2-s2t13-first-passage-20260721T110224Z-d3f0c0331395`; Manifest `24c404179037ab7db08afd96b94fd284e7896db18801011e4267081680e0aaed`; Catalog `8511c27310e40fd103f9eeccde2067ed5c1279765377c8b35652dd9072c8889e` | 1,065,416 H1/H2 path rows and 31,962,480 classifications |
| S2-T14 v1.3 | Run `stage2-s2t14-ambiguity-bounds-20260721T140507Z-8b4cf765602d`; Manifest `a6182c2ea80af92d081631f41864d5e54c6b8c4494ebe56c18a7a4df0894276a`; Catalog `ab9abf9635ec263888bb4b6f9d5ae350fac44745544590098f3c12ceb8ecdf19` | 31,962,480 classifications and 2,280 compact distributions |
| S2-T15 v1.4 | Runs `stage2-s2t15-conditional-20260722T071250Z-871c404c5f43` and `stage2-s2t15-conditional-20260722T120658Z-023f47cffef2` | Both are `FAILED_UNPUBLISHED`; neither is a research result and neither may be resumed or relabelled |

The accepted T13 H2 input baseline remains 532,708 paths and 15,981,240 outcome cells until the
successor T11/T13 audit reports its actual revised count. The old count must not be copied into a
new Manifest without a fresh read and reconciliation.

## Proposed successor versions and dependency graph

These versions are proposals and require a separate affected-scope approval:

| Task | Proposed version | Change boundary |
| --- | --- | --- |
| S2-T11 | v1.4 | Emit verified-gap main quality plus legacy any-discontinuity sensitivity; no path-price or ordering change |
| S2-T12 | v1.4 | Rebind metrics to T11 v1.4 and propagate both quality projections; metric formulas unchanged |
| S2-T13 | v1.4 | Main labels use verified gaps; legacy projection preserves any-discontinuity sensitivity; crossing semantics unchanged |
| S2-T14 | v1.4 | Recompute bounds from T13 v1.4 without altering the approved AMBIGUOUS policy |
| S2-T15 | v1.5 | Rebind the conditional baseline to the new T11/T13/T14 evidence; matching, rolling folds, bins and 30-cell matrix contract unchanged |

Required execution order:

`immutable Stage 1 facts + versioned quality supplement`
→ `S2-T11 v1.4`
→ `S2-T12 v1.4`
→ `S2-T13 v1.4`
→ `S2-T14 v1.4`
→ `S2-T15 v1.5`

No downstream successor may freeze its Authority before the direct upstream successor has passed
full Verify and its Manifest/Catalog Hashes are fixed. The first approved execution should remain
sequential. Parallel execution is not part of this preparation.

## Proposed semantic outputs

Each applicable path and downstream summary must retain enough evidence to distinguish:

- `VENUE_ID_DISCONTINUITY_UNCORROBORATED`: numeric jump observed, main H2 path remains usable;
- `VERIFIED_PUBLIC_TRADE_GAP`: independent immutable evidence proves a promised Trade fact is
  absent; a pre-decision intersection may produce `AMBIGUOUS / SOURCE_GAP_BEFORE_DECISION`;
- `SOURCE_INTEGRITY_FAILURE`: missing, corrupt, truncated, checksum-invalid, Catalog-inconsistent
  or unbound source; fail closed.

Both projections are predeclared:

1. main projection using verified-gap semantics;
2. conservative sensitivity projection using the legacy any-discontinuity interpretation.

The observed event result may not select which projection is reported. Existing legacy artifacts
remain the historical reference for the second projection and are not rewritten.

## Read-only audit gate

Before implementation approval, the CR-2026-031 audit must produce, separately for BTC and ETH and
by year/month:

- archive, checksum, UTC-partition, Catalog/object and row-count reconciliation;
- canonical identity duplicates/conflicts, timestamp reversals and venue-ID discontinuities;
- discontinuity range-size and adjacent-event-time distributions;
- independently verified missing/corrupt/truncated partitions;
- T11 H1/H2 window intersections;
- T12 quality-row impact;
- T13 main-versus-legacy label impact;
- T14 bound impact;
- P1/P2/P3 and F0-F3 impact, with P3/F3 explicit;
- proof status for every candidate `VERIFIED_PUBLIC_TRADE_GAP`.

A discontinuity with no approved independent proof remains uncorroborated. The audit must not query
a real account API, fill a missing ID, synthesize a Trade or change any accepted object.

## Mandatory seven-day rehearsals

Every long/full-data successor task must first pass a fresh seven-complete-UTC-day rehearsal from
the exact final clean code that will be frozen. The rehearsal writes only to a new isolated,
unpublished root and does not create a formal Authority or Run ID.

Proposed representative windows, subject to affected-scope approval:

| Window | Purpose |
| --- | --- |
| `[2026-01-02T00:00:00Z, 2026-01-09T00:00:00Z)` | Primary high-density P3 test where legacy discontinuity amplification is severe |
| `[2022-08-29T00:00:00Z, 2022-09-05T00:00:00Z)` | Compatibility test crossing a UTC month boundary in P2 |

The P3 window is the mandatory rehearsal. The P2 window is an additional proposed compatibility
rehearsal because it exercises month-boundary serialization; it is not yet an approved extra gate.

For each task, simulated acceptance criteria must be written before execution and must cover the
real handoff used by the long run:

1. producer computation;
2. serialization plus checkpoint/receipt creation;
3. strict read-back by the next consumer;
4. exact row/cell and reason-code reconciliation;
5. independent Verify;
6. evidence-driven read-only Web UI projection where in scope;
7. deterministic replay with matching logical Hashes.

Example: the T11 rehearsal is not accepted merely because it writes Parquet. T12 and T13 must read
those exact rehearsal files strictly, both semantic projections must reconcile, and the UI must
show rehearsal state from evidence rather than an HTML `PASSED` constant.

Any Decimal, timestamp, schema, path, Hash, reason-code, checkpoint, receiver or UI-format failure
blocks the full run. After a fix, the whole seven-day rehearsal restarts from the beginning.

## Space and operational preflight

- Current observation on 2026-07-22: `/Volumes/FuckingLife` has about 1.4 TiB available and
  `/private/tmp` has about 230 GiB available. These figures are observations, not a future pass.
- Each rehearsal must record input bytes, output bytes, temporary peak bytes, duration and peak
  memory for BTC and ETH separately.
- Before each formal successor, available space must be at least measured projected peak usage
  multiplied by 1.20, including append-only outputs and temporary files.
- Output roots must be explicit, empty, isolated and outside every accepted sealed run.
- No automatic cleanup, overwrite, symlink retarget or deletion of old evidence is permitted.
- A process/run uniqueness check and a write probe must pass before a formal Run ID is created.

## Allowed preparation files

- `docs/development/changes/CR-2026-031.md`
- `docs/development/decisions/ADR-S2-010-venue-trade-id-discontinuity.md`
- `docs/development/OPEN_QUESTIONS.md`
- `docs/development/TRACEABILITY.md`
- this preparation document
- future read-only audit reports in a separately approved path

## Forbidden during preparation

- `docs/spec/**`
- Stage 1 raw, published, Catalog, Manifest or implementation objects
- accepted S2-T10 through S2-T14 artifacts
- failed S2-T15 artifacts
- any T11-T15 production implementation before affected-scope approval
- Authority, Binning Snapshot, Run ID, publication or PASS validation
- S2-T16 through S2-T20, Stage 3, H3, PnL, testnet, live API or real funds

## Stop conditions

Stop before a formal successor if any of the following occurs:

- source Hash, row count, UTC coverage, symlink or Catalog binding drifts;
- a numeric jump is promoted to a verified gap without independent immutable proof;
- main and conservative projections cannot both be produced and reconciled;
- a direct consumer cannot strictly read the producer's serialized output;
- any global count differs from the sum of BTC/ETH, period/fold or reason-code groups;
- T12 is omitted or old/new semantic versions are mixed;
- T15 reads an old T13/T14 binding after a new T11 successor exists;
- Web UI needs a hard-coded task PASS or cannot distinguish legacy and successor evidence;
- available disk is below measured peak times 1.20;
- implementation would require modifying accepted evidence, `docs/spec/**`, T16+ or Stage 3.

## Approval and execution gates

1. Complete and review the CR-2026-031 read-only audit.
2. Approve the affected Task versions, file scopes, reason codes, compatibility declarations and
   invalidation graph.
3. Implement the minimum versioned quality overlay and downstream receivers on an isolated branch.
4. Run targeted tests, Ruff, strict mypy, strict Traceability and full pytest; record actual counts.
5. Run the mandatory seven-day producer-to-consumer rehearsals from final clean code.
6. Rerun the read-only upstream audit and pass the measured space/preflight gates.
7. Freeze and execute one append-only successor per Task in dependency order; independently Verify
   each before allowing the next Task.
8. Confirm evidence-driven Web UI projections and create separate validations.
9. Stop after S2-T15 and wait for human acceptance. Do not start S2-T16 or unlock Stage 3.

## Current Go/No-Go

- Read-only audit and preparation: `GO`.
- T11-T15 code changes: `NO-GO` until affected-scope approval.
- Formal successor Authorities/Runs: `NO-GO` until audit, implementation quality and seven-day
  rehearsals pass.
- S2-T16+ and Stage 3: `NO-GO`.
