# Stage 2 Group 1 Validation

## Conclusion

**FAIL**

S2-T19 and S2-T01～S2-T09 passed their directed tests and small-sample integration. S2-T10
failed during the first full BTCUSDT Flow partition because its Stage 1 Trades physical-path
resolver omitted the frozen `archive=YYYY-MM` partition level. The full run was not published,
ETH and Run B were not executed, and deterministic full-run acceptance is unavailable.

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
| No blocker | FAIL: `CR-2026-003` |

## Failure disposition

Run `stage2-g1-full-a-20260716-4c15e46` is `FAILED_UNPUBLISHED`. Its staging and failure evidence
must remain intact until audit and explicitly approved cleanup. [CR-2026-003](../changes/CR-2026-003.md)
proposes an L1 path-resolution correction, full preflight coverage and two new full runs. Group 1
is not ready for final approval.
