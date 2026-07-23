# CR-2026-014 Performance Optimization History

- scope: DIAGNOSTIC_ONLY Group-1 PRICE/FLOW execution
- frozen window: BTCUSDT + ETHUSDT `[2020-07-01, 2020-08-01)`
- semantic rows: 9,314,723
- frozen packed aggregate hash:
  `b04b217c97d872a52ca14fb8e8ca1e43c7aa06e8f19531de5535d02891d175af`
- evidence root: `/Volumes/FuckingLife/era100x_stage2/diagnostics/cr-2026-014`

## Full-window history

| Revision | Main change | Wall seconds | Speedup | Average cores | Semantic result | Disposition |
| --- | --- | ---: | ---: | ---: | --- | --- |
| baseline-r2 | Frozen pre-optimization implementation | 996.780 | 1.00x | 0.03 | Reference | Retained |
| r4 | Processing-day cache, Foundation cache, month workers, streaming spool | 482.935 | 2.06x | 1.72 | Exact | Superseded |
| r5 | Correctness and recovery refinements | 457.051 | 2.18x | 1.73 | Exact | Superseded |
| r6 | Trusted Arrow normalization, selected Flow seconds, native JSON encoding | 331.833 | 3.00x | 1.54 | Exact | Superseded by r8 |
| r7 | Experimental three-way owner-month segmentation | 484.561 | 2.06x | 2.20 | Exact | Rejected: repeated Foundation reads and duplicate setup work |
| r8 | Reverted segmentation; exact nested-map JSON compatibility fix | 329.687 | 3.02x | 1.62 | Exact | Accepted implementation baseline |

All full-window accepted comparisons reproduce 806 logical receipts, all legacy/V2/identity/payload
roots, 64 processing-day executions, 198 physical Foundation reads, 652 legacy sorted runs and zero
daily temporary bytes. The r8 comparison receipt Hash is
`179fbe8f171eaccfa3d9216b6d5310840ffa015580ac731fa37a0f55099b02b0`.

## Rejected and diagnostic experiments

The r7 segmentation experiment split each instrument-month into three compute ranges so that three
processes could run concurrently. It increased average CPU use but caused every segment to reload
and revalidate large Foundation objects. Physical Foundation reads increased from 198 to 336,
processing-day executions increased from 64 to 67, CPU work increased from 512.13 to 1,068.20
seconds and wall time regressed from 331.83 to 484.56 seconds. The code was removed before the
accepted implementation was frozen.

A three-day hot-path experiment reduced wall time from 39.43 to 21.11 seconds by removing a Python
scan of every encoded JSON byte. A later frozen-schema encoder experiment produced exact three-day
Hash results but measured 24.84 seconds and was not promoted without an exact full-month result.
Likewise, the multi-domain Arrow Hash experiment remained unpromoted and was removed. Diagnostic
directories and reports remain append-only evidence; rejected implementation code is not part of
the accepted runtime.

## Human performance decision

On 2026-07-19 Muce accepted the reproducible r8 result as the practical performance ceiling for the
current external-disk architecture and authorized progression to the final quality gate and full
replacement run. The former 4x and 2.5-core goals remain recorded as unmet performance objectives,
not integrity failures. They no longer block Authority freeze or full re-execution. Exact semantic
equality, integrity, ownership, leakage, append-only and Run-A comparison gates remain mandatory and
unchanged.
