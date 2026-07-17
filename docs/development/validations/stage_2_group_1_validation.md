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
