# Stage 2 Group 1 Validation

## Conclusion

**FAIL**

Recovery status: CR-2026-003 and CR-2026-004 are implemented and validated; CR-2026-005 is
RESOLVED. The current v1.6 Run A completed 9508/9508 generation items; its isolated CR-2026-006
release child remains authorized, while the legacy parent and legacy Run B are stopped.
CR-2026-007/008 authorize S2-T10 v1.8 to build a complete Feature Foundation, perform a fresh V2
Group-1 Run B and compare its full canonical owner-day projection exactly with formal Run A.
Run A publication, V2 Run B and cross-implementation comparison are not yet complete. This remains
FAIL.

S2-T19 and S2-T01～S2-T09 passed their directed tests and small-sample integration. The original
S2-T10 v1.3 attempt failed during the first full BTCUSDT Flow partition because its Stage 1 Trades physical-path
resolver omitted the frozen `archive=YYYY-MM` partition level. The full run was not published,
ETH and Run B were not executed, and deterministic full-run acceptance is unavailable.

The approved CR-2026-003 path fix passes its regression and unified quality gate. CR-2026-004
proved the 2,810 legacy excess rows were parameter/timing identity collisions, not exact
duplicates. The corrected identity maps all 3,781 rows to 3,781 unique canonical candidates with
zero conflict and deterministic replay. No new Execution Manifest or recovery run was created.

## Acceptance summary

| Requirement | Result |
| --- | --- |
| S2-T19, S2-T01～S2-T09 PASSED | PASS |
| Small-sample deterministic integration | PASS |
| BTC/ETH isolation | PASS in tested capability; full ETH NOT RUN |
| BTC full price partitions | PASS, 2376/2376 |
| BTC full Flow partitions | FAIL at first partition |
| ETH full candidate generation | NOT RUN |
| Two complete deterministic runs | NOT RUN |
| No future-data or forbidden execution capability | PASS in completed tests |
| No Stage 1 mutation | PASS |
| Failure does not publish | PASS |
| No Group 2～4 execution | PASS |
| CR-2026-003 archive path correction | PASS in code/regression |
| Candidate identity/ownership correction | PASS: CR-2026-004 |
| CR-2026-005 bounded correction and diagnostic | PASS; full-run approval still required |
| v1.5 Run A BTC PRICE daily construction | PASS, 2376/2376 |
| v1.5 Run A candidate finalization | FAIL: 2 same-identity/different-payload groups |
| v1.5 Run A publication | NONE / FAILED_UNPUBLISHED |
| v1.5 independent Run B | NOT CREATED |
| CR-2026-005 decision | Option A RESOLVED / IMPLEMENTED / VALIDATED |
| Historical S2-T10 v1.6 state | APPROVED_FOR_REEXECUTION; superseded by v1.8 hybrid path |
| S2-T10 v1.8 hybrid authorization | APPROVED / IN_PROGRESS; Run A child retained, legacy Run B suppressed |
| Feature Foundation and fresh V2 Run B | NOT RUN |
| Exact cross-layout semantic comparison | NOT RUN |

## Failure disposition

Run `stage2-g1-full-a-20260716-4c15e46` is `FAILED_UNPUBLISHED`. Its staging and failure evidence
remain intact. [CR-2026-003](../changes/CR-2026-003.md) corrected the path resolver; the separate
[CR-2026-004](../changes/CR-2026-004.md) validates candidate identity and ownership. Group 1 is
ready for a new S2-T10 full-run approval but is not ready for final approval.

The later v1.5 Run A is retained separately as
`stage2-g1-full-a-20260716T122601Z-0247d30f9f62`. It is `FAILED_UNPUBLISHED` after the approved
hard-conflict gate detected two adjacent-minute snapshot payload conflicts on 2020-04-27. It may
not be resumed or published. [CR-2026-005](../changes/CR-2026-005.md) records the implemented
Option A correction. Its bounded forward/reverse diagnostic replay produced 236 unique
candidates, zero conflicts and identical logical hash
`0e55874df0fdd0cdf669af4af8c645879ed7596fb450d6fa380e5f7438425a52`; no formal data was
published. Group 1 remains FAIL until separately approved dual full builds complete.

## S2-T10 v1.8 acceptance path

Plan v1.2 and the Task DAG remain unchanged. S2-T10 is still the sole Group-1 full builder. Group 1
can advance only after the isolated Run A release reaches Quality PASS, the complete frozen-source
Feature Foundation and fresh V2 Run B publish with Quality PASS, and CR-2026-008 proves exact
semantic equality for all owner-day projections. This internal platform work creates no S2-T21,
S2-T22 or S2-T23 and authorizes no S2-T11 through S2-T20 execution.

## S2-T10 v1.9 memory correction readiness

Formal Run A is now PUBLISHED / Quality PASS with 61,776 Group-1 logical partitions and immutable
logical Hash `8583f220dc880bf5b7e7ace1435ca2285e59b80dd48aa7d15bd2f8cacac60870`.
The first V2 Run B remained `FAILED_UNPUBLISHED` with zero completed tasks after the obsolete
absolute 900 MiB peak-RSS gate rejected its first BTC Foundation task. It has no reusable staging
or published output.

CR-2026-011's row-group Trades aggregation, sequential phase sealing/release and separate Arrow,
current-RSS and baseline-relative RSS gates pass real-data failure-date, archive-boundary and
highest-volume profiles. Runtime V2 181/181 and unified repository 387/387 tests pass. This makes
one final-code Authority refreeze and one unique replacement Run B conditionally executable, but
does not change this Validation conclusion. Group 1 remains **FAIL** until the replacement builds
all 80,784 V2 partitions, publishes with Quality PASS and matches all 61,776 Run A Group-1
partitions exactly.

## S2-T10 v1.10 finalization memory-gate correction

The CR-2026-011 replacement Run B completed 316 BTC monthly and 82 BTC packed Foundation
checkpoints, then failed before Task evidence sealing. The failure used process-lifetime
`ru_maxrss` delta as a phase-local limit even though no published file or semantic mismatch
existed. CR-2026-012 is APPROVED to retain lifetime peak as audit-only evidence and enforce
continuously sampled phase-current RSS. Group 1 remains **FAIL** until a newly frozen replacement
builds 80,784 partitions, publishes with Quality PASS and exactly matches all 61,776 Run A
Group-1 partitions. The real finalization diagnostic scanned 82 packed objects and 9,504 row
groups with maximum Arrow `15,120,000`, current RSS `544,030,720` and phase-current delta
`384,630,784` bytes; its report SHA-256 is
`cb84ce635f31d0eb5562602916042d68177ff3c3da0738ec09da7b4ee3c9d691`. Code validation PASS does
not change the current Group-1 FAIL conclusion.

## S2-T10 v1.11 resource anomaly correction

The next replacement Run B `stage2-g1-v2-b-20260718T141137Z-f0c150bfa1c9` completed all 316 BTC
month-level Foundation objects and failed unpublished before packing because a resource observation
threshold was classified as terminal research failure. It has zero published files and remains
immutable. CR-2026-013 is APPROVED to make memory, Arrow, object-count, object-size, capacity and
performance thresholds append-only anomalies, while preserving hard failure for integrity and
exact comparison defects. A new run may adopt the 316 objects only after complete per-object
verification. This draft remains **FAIL** until the replacement publishes and all 61,776 Group-1
partitions exactly match Run A.

## S2-T10 v1.12 execution optimization

CR-2026-014 is APPROVED to remove duplicate processing-day work, reuse verified Foundation
fragments, execute isolated instrument-month workers, stream exact compatibility hashes and expose
read-only progress. The currently stopped Run B remains unpublished evidence and cannot provide
Group-1 data to the successor. Group 1 remains **FAIL** until final quality validation, complete
replacement publication and exact Run-A comparison all pass.

The accepted r8 July benchmark preserves all legacy/V2/identity/payload Hashes and improves wall
time from 996.78 to 329.69 seconds (3.02x). Muce accepted this as the current external-disk ceiling;
the unmet 4x and 2.5-core objectives remain performance history rather than blockers. Group 1
remains **FAIL / IN_PROGRESS** until the replacement Run B and exact comparison pass. No replacement
Run B or later-group artifact exists yet.
## S2-T10 v1.13 final packing recovery

CR-2026-015 is APPROVED. The latest Run B computed all Group-1 logical partitions but failed
unpublished at final component packing because producer and consumer sort contracts differed. The
19 packed artifacts are physically unique; no data duplicate was found. Group 1 remains **FAIL /
INCOMPLETE** until a new run adopts verified monthly evidence, repeats final packing and passes
release, verification and all 61,776 Run A/Run B semantic comparisons.

## S2-T10 v1.14 final Group-1 acceptance

CR-2026-018 reused the unchanged 208 sealed results without resume or repacking and completed
atomic publication plus independent verification over all 80,784 V2 partitions. CR-2026-019 then
corrected only the comparator algorithm-authority call, passed the complete 431-test repository
gate and executed only Exact Compare under append-only comparison Authority.

Run A and Run B each contain 61,776 Group-1 partitions. All 61,776 daily row Hashes match, global
distributions are equal, and missing, extra and difference counts are all zero. Comparison report
SHA-256 is `69298e5d05161223b354e1b60a65ef032e9370e4017da487e35657264af8e9f0`.
S2-T10 v1.14 and Group 1 are **PASS**. This result does not authorize S2-T11 through S2-T20 and
does not unlock Stage 3.
