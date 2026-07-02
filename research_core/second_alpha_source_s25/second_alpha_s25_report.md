# S2.5 IDLE_MR1 State Breakdown Report

source_status: temp_run_not_canonical
data_layer: expanded_discovery
oos_status: not_oos
strategy_backtest_generated: false

## Final Decision

E. 当前 S2 来源不是 canonical，无法形成正式判断

## Summary

- IDLE_MR1 events analyzed: 26752
- Overall mean_fwd_ret_16: -0.00013107
- Subsequent trend breakout rate: 0.2537

## Direction Breakdown

| side   |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:-------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| long   |         15846 |     -4.66266e-05 |     -0.000220904 |     -0.000330208 |      -0.000169569 |       0.000409592 |                  0.464245 |                   0.504359 |   -0.0117153  |    0.00984533 |                   0.00276455 |               -0.00021026  |
| short  |         10906 |     -3.60213e-05 |     -0.000118673 |     -0.000122918 |      -7.51845e-05 |       2.59873e-05 |                  0.495599 |                   0.474876 |   -0.00932813 |    0.00931395 |                   0.00224111 |               -9.95515e-05 |

## Symbol Breakdown

| symbol   |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:---------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| BNBUSDT  |          7074 |     -1.99116e-05 |     -5.69085e-05 |     -6.3791e-05  |       0.000133352 |       0.00031015  |                  0.494555 |                   0.483241 |   -0.00871636 |    0.0079878  |                   0.00375908 |                0.00010087  |
| BTCUSDT  |          6611 |     -3.49435e-06 |     -5.67482e-05 |     -9.28403e-05 |       0.000138894 |       0.000690981 |                  0.482446 |                   0.483505 |   -0.00783196 |    0.00730693 |                   0.00386453 |                9.8611e-05  |
| ETHUSDT  |          6327 |     -9.09763e-05 |     -0.000307406 |     -0.000391858 |      -0.000497737 |      -0.000275842 |                  0.468997 |                   0.492724 |   -0.0126425  |    0.0109933  |                   0.00400932 |               -0.000561306 |
| SOLUSDT  |          6740 |     -5.81796e-05 |     -0.000307418 |     -0.000449382 |      -0.000329367 |       0.000259755 |                  0.460876 |                   0.510171 |   -0.0139382  |    0.012348   |                   0.00531826 |               -0.000425104 |

## P4 Phase Breakdown

| p4_phase                 |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:-------------------------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| after_p4_exit_0_4_bars   |          1032 |     -0.000119071 |     -0.000479308 |     -0.000384912 |       0.00031751  |       0.000820864 |                  0.45155  |                   0.522287 |   -0.0104975  |    0.00948122 |                   0.0353037  |               -6.50614e-05 |
| after_p4_exit_17_64_bars |          5006 |      8.30321e-05 |      5.56213e-07 |     -5.49306e-05 |       0.000339495 |       0.000918159 |                  0.490807 |                   0.485811 |   -0.0092187  |    0.00858519 |                   0.00508868 |                0.000299205 |
| after_p4_exit_5_16_bars  |          1562 |      3.92989e-05 |      0.000412937 |      0.00118993  |       0.00191452  |       0.00287647  |                  0.472365 |                   0.456941 |   -0.00887449 |    0.010344   |                   0.0257299  |                0.00150385  |
| deep_idle                |         14996 |     -4.85592e-05 |     -0.000233345 |     -0.000421388 |      -0.000391038 |       4.75046e-05 |                  0.472578 |                   0.500267 |   -0.01176    |    0.0101343  |                   0.00180523 |               -0.000417369 |
| p4_held                  |          4156 |     -0.000182305 |     -0.000348553 |     -0.000345017 |      -0.000637357 |      -0.000929619 |                  0.484601 |                   0.477382 |   -0.00966188 |    0.00882968 |                   0.00630111 |               -0.000697117 |

## Volatility Breakdown

| volatility_regime   |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:--------------------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| high_vol            |         13300 |     -9.0278e-05  |     -0.000290146 |     -0.000492528 |      -0.000537072 |      -7.84581e-05 |                  0.462782 |                   0.495188 |   -0.0124149  |    0.0104183  |                   0.00164334 |               -0.000561622 |
| low_vol             |          6462 |      2.72839e-05 |     -4.69145e-05 |     -3.26184e-05 |       0.000212405 |       0.000293195 |                  0.49094  |                   0.493418 |   -0.00851134 |    0.00830254 |                   0.00801168 |                0.000112796 |
| mid_vol             |          6987 |     -1.55916e-05 |     -9.00275e-05 |      2.54817e-05 |       0.000321736 |       0.000847211 |                  0.491256 |                   0.485952 |   -0.00961841 |    0.00934997 |                   0.00412863 |                0.000266645 |
| unknown             |             3 |      0.000544915 |     -0.0011877   |      0.00433687  |       0.00762978  |       0.00344461  |                  0.666667 |                   0.333333 |   -0.00419464 |    0.0103897  |                   0.660785   |              nan           |

## Trend Strength Breakdown

| trend_strength_bucket   |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:------------------------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| 0.5_1.0                 |          5772 |     -8.10131e-05 |     -0.000167816 |     -0.000251148 |      -0.000206501 |      -0.000155872 |                  0.472352 |                   0.494193 |    -0.010242  |    0.00953571 |                   0.0075139  |               -0.000294555 |
| 0_0.5                   |          5926 |     -6.06561e-05 |     -0.000265907 |     -0.000282854 |       8.68694e-05 |       0.000807619 |                  0.472964 |                   0.495945 |    -0.0103106 |    0.00958752 |                   0.00466558 |                1.92551e-05 |
| 1.0_1.5                 |          5558 |     -4.19404e-05 |     -0.000270577 |     -0.000157669 |      -0.000481236 |      -0.000641632 |                  0.466895 |                   0.501439 |    -0.0108909 |    0.00955303 |                   0.00854354 |               -0.00059734  |
| 1.5_2.5                 |          9496 |     -7.53283e-06 |     -7.86034e-05 |     -0.000270687 |      -1.60484e-05 |       0.000679564 |                  0.488357 |                   0.483616 |    -0.0112265 |    0.00975486 |                   0.0023322  |               -4.63113e-05 |

## Random Baseline Diagnostics

| group                             |   event_count |   matched_sample_count |   unmatched_event_count |   fallback_match_rate |   observed_mean |   baseline_mean |   percentile | note                                                            |
|:----------------------------------|--------------:|-----------------------:|------------------------:|----------------------:|----------------:|----------------:|-------------:|:----------------------------------------------------------------|
| overall                           |         26752 |                  26746 |                       6 |            0.0223535  |    -0.000131068 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| symbol:BNBUSDT                    |          7074 |                   7073 |                       1 |            0.0192253  |     0.000133352 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| symbol:BTCUSDT                    |          6611 |                   6610 |                       1 |            0.0240508  |     0.000138894 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| symbol:ETHUSDT                    |          6327 |                   6326 |                       1 |            0.0249723  |    -0.000497737 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| symbol:SOLUSDT                    |          6740 |                   6737 |                       3 |            0.0215134  |    -0.000329367 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| side:long                         |         15846 |                  15846 |                       0 |            0.0214565  |    -0.000169569 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| side:short                        |         10906 |                  10900 |                       6 |            0.0236567  |    -7.51845e-05 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| p4_phase:after_p4_exit_0_4_bars   |          1032 |                   1029 |                       3 |            0.0891473  |     0.00031751  |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| p4_phase:after_p4_exit_17_64_bars |          5006 |                   5006 |                       0 |            0.0437475  |     0.000339495 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| p4_phase:after_p4_exit_5_16_bars  |          1562 |                   1562 |                       0 |            0.0723431  |     0.00191452  |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| p4_phase:deep_idle                |         14996 |                  14994 |                       2 |            0.00486796 |    -0.000391038 |             nan |          nan | diagnostic only; baseline values require full market-state pool |
| p4_phase:p4_held                  |          4156 |                   4155 |                       1 |            0.0243022  |    -0.000637357 |             nan |          nan | diagnostic only; baseline values require full market-state pool |

## Edge Hypotheses

| dimension      | best_bucket             |   event_count |   mean_fwd_ret_16 | hypothesis_status    |
|:---------------|:------------------------|--------------:|------------------:|:---------------------|
| side           | short                   |         10906 |      -7.51845e-05 | no_positive_bucket   |
| symbol         | BTCUSDT                 |          6611 |       0.000138894 | weak_positive_bucket |
| p4_phase       | after_p4_exit_5_16_bars |          1562 |       0.00191452  | weak_positive_bucket |
| volatility     | unknown                 |             3 |       0.00762978  | no_positive_bucket   |
| trend_strength | 0_0.5                   |          5926 |       8.68694e-05 | weak_positive_bucket |

## Required Answers

1. IDLE_MR1 的 long 和 short 哪个更差？long mean=-0.00016957, short mean=-0.00007518，较低者更差。
2. 哪个币种拖累最大？当前最差 symbol=ETHUSDT。
3. 是否存在有效月份或有效季度？见 idle_mr1_monthly_breakdown.csv，最好的 5 个月如下：
| month   |   event_count |   mean_fwd_ret_1 |   mean_fwd_ret_4 |   mean_fwd_ret_8 |   mean_fwd_ret_16 |   mean_fwd_ret_32 |   plus_1atr_first_rate_16 |   minus_1atr_first_rate_16 |   mean_mae_16 |   mean_mfe_16 |   top1_positive_contribution |   remove_top3_mean_fwd_ret |
|:--------|--------------:|-----------------:|-----------------:|-----------------:|------------------:|------------------:|--------------------------:|---------------------------:|--------------:|--------------:|-----------------------------:|---------------------------:|
| 2026-06 |          1148 |      9.3471e-07  |      9.66799e-05 |      5.99152e-05 |       0.00220307  |       0.00258663  |                  0.49735  |                   0.471731 |   -0.00990327 |    0.011037   |                   0.00833809 |                 0.00207361 |
| 2024-12 |          1593 |      0.000154417 |      0.000383392 |      0.000509366 |       0.00179785  |       0.00249643  |                  0.490898 |                   0.496547 |   -0.0125355  |    0.0121807  |                   0.00638345 |                 0.00168324 |
| 2025-05 |          1537 |      0.000198361 |      0.000404281 |      0.000799901 |       0.00128554  |      -0.00025608  |                  0.49447  |                   0.493169 |   -0.0092988  |    0.0096191  |                   0.0105679  |                 0.00115989 |
| 2025-12 |          1541 |     -0.000244192 |     -0.000335394 |      0.000101022 |       0.00127219  |       0.00279844  |                  0.512005 |                   0.447112 |   -0.00940016 |    0.0103003  |                   0.00954577 |                 0.00113019 |
| 2025-09 |          1292 |      6.93791e-05 |      0.000268673 |      0.000681518 |       0.000502578 |       0.000260676 |                  0.483746 |                   0.47678  |   -0.00753535 |    0.00735148 |                   0.00860615 |                 0.00041282 |
4. 是否在 P4 刚退出后更有效？见 p4_phase breakdown；当前最佳 phase=after_p4_exit_5_16_bars。
5. deep_idle 是否有效？见 idle_mr1_p4_phase_breakdown.csv 的 deep_idle 行。
6. 高波动是否导致失败？high_vol mean_fwd_ret_16=-0.00053707。
7. 趋势强度是否解释失败？最差 trend bucket=1.0_1.5。
8. 失败案例是否经常演变为真趋势突破？整体 subsequent_trend_breakout_rate=0.2537。
9. percentile 高但 mean return 负的原因是什么？S2.5 诊断倾向于：IDLE_MR1 可能比匹配事件少亏，但自身 16-bar forward mean 仍未转正；还需要 full market-state random baseline 才能最终解释。
10. 是否值得进入 S2.6？只有 canonical S2 且出现明确正收益局部状态时才进入；当前若 source_status 非 canonical，则不能进入正式 S2.6。
