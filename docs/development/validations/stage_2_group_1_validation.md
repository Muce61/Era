# Stage 2 Group 1 Validation

## Conclusion

**FAIL**

Recovery status: CR-2026-003 path repair IMPLEMENTED/TESTED; S2-T10 v1.4 BLOCKED by proposed
CR-2026-004. This remains a FAIL draft and cannot become PASS until the candidate-deduplication
integration is explicitly approved, corrected, and followed by two complete deterministic runs.

S2-T19 and S2-T01～S2-T09 passed their directed tests and small-sample integration. S2-T10
failed during the first full BTCUSDT Flow partition because its Stage 1 Trades physical-path
resolver omitted the frozen `archive=YYYY-MM` partition level. The full run was not published,
ETH and Run B were not executed, and deterministic full-run acceptance is unavailable.

The approved CR-2026-003 path fix now passes its regression and unified quality gate. Mandatory
pre-run inspection then found 2,810 duplicate identities among 3,781 rows in the first 50 retained
BTC PRICE MarketEpisode partitions, with duplicate inclusion rows all marked included. Because
CR-2026-003 forbids changing PRICE results, CR-2026-004 must be approved before implementation.
No new Execution Manifest or recovery run was created.

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
| Candidate identity deduplication | FAIL: `CR-2026-004` pending approval |
| No blocker | FAIL: `CR-2026-004` |

## Failure disposition

Run `stage2-g1-full-a-20260716-4c15e46` is `FAILED_UNPUBLISHED`. Its staging and failure evidence
remain intact. [CR-2026-003](../changes/CR-2026-003.md) corrected the path resolver; the separate
[CR-2026-004](../changes/CR-2026-004.md) records the blocked candidate-deduplication integration.
Group 1 is not ready for final approval.
