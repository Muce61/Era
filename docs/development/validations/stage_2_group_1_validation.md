# Stage 2 Group 1 Validation

## Conclusion

**FAIL**

Recovery status: CR-2026-003 path repair IMPLEMENTED/TESTED; CR-2026-004 RESOLVED with
validation PASS; S2-T10 v1.5 dual full build IN_PROGRESS. This remains a FAIL draft until two new
complete deterministic full runs satisfy the Group-1 gate.

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

## Failure disposition

Run `stage2-g1-full-a-20260716-4c15e46` is `FAILED_UNPUBLISHED`. Its staging and failure evidence
remain intact. [CR-2026-003](../changes/CR-2026-003.md) corrected the path resolver; the separate
[CR-2026-004](../changes/CR-2026-004.md) validates candidate identity and ownership. Group 1 is
ready to retry S2-T10 but is not ready for final approval.
