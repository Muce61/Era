# Stage 2 Group 1 Validation

## Conclusion

**FAIL**

Recovery status: CR-2026-003 path repair IMPLEMENTED/TESTED; CR-2026-004 RESOLVED with
validation PASS; the first S2-T10 v1.5 Run A failed unpublished during BTC PRICE finalization.
CR-2026-005 is open and blocks any replacement Run A or Run B. This remains FAIL.

S2-T19 and S2-T01～S2-T09 passed their directed tests and small-sample integration. S2-T10
failed during the first full BTCUSDT Flow partition because its Stage 1 Trades physical-path
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
| No blocker for S2-T10 recovery | PASS |
| v1.5 Run A BTC PRICE daily construction | PASS, 2376/2376 |
| v1.5 Run A candidate finalization | FAIL: 2 same-identity/different-payload groups |
| v1.5 Run A publication | NONE / FAILED_UNPUBLISHED |
| v1.5 independent Run B | NOT CREATED |
| CR-2026-005 decision | BLOCKED / HUMAN DECISION REQUIRED |

## Failure disposition

Run `stage2-g1-full-a-20260716-4c15e46` is `FAILED_UNPUBLISHED`. Its staging and failure evidence
remain intact. [CR-2026-003](../changes/CR-2026-003.md) corrected the path resolver; the separate
[CR-2026-004](../changes/CR-2026-004.md) validates candidate identity and ownership. Group 1 is
ready to retry S2-T10 but is not ready for final approval.

The later v1.5 Run A is retained separately as
`stage2-g1-full-a-20260716T122601Z-0247d30f9f62`. It is `FAILED_UNPUBLISHED` after the approved
hard-conflict gate detected two adjacent-minute snapshot payload conflicts on 2020-04-27. It may
not be resumed or published. [CR-2026-005](../changes/CR-2026-005.md) records the new blocker.
