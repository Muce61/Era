# RB2 Low Leverage Portfolio Report

data_layer: expanded_discovery
oos_status: not_oos
deployable_strategy_generated: false

## Conclusion

C. P4 low leverage remains a research candidate but is not ready for OOS/shadow preparation

## Backtest Summary

| symbol   | gate       | leverage_mode     |   trade_count |   total_return |   max_drawdown |   profit_factor |   win_rate |   final_equity |   top1_profit_contribution |
|:---------|:-----------|:------------------|--------------:|---------------:|---------------:|----------------:|-----------:|---------------:|---------------------------:|
| ETHUSDT  | P4_NO_GATE | fixed_1x          |           488 |       0.57932  |      -0.506761 |         1.10079 |   0.340164 |        1579.32 |                   0.600995 |
| ETHUSDT  | P4_NO_GATE | fixed_2x          |           488 |       0.677071 |      -0.784653 |         1.05288 |   0.340164 |        1677.07 |                   1.43544  |
| ETHUSDT  | P4_NO_GATE | fixed_3x          |           488 |       0.26595  |      -0.916249 |         1.01377 |   0.340164 |        1265.95 |                   7.0076   |
| ETHUSDT  | P4_NO_GATE | adaptive_1x_3x_v1 |           488 |       0.623563 |      -0.506761 |         1.09681 |   0.340164 |        1623.56 |                   0.573994 |
| ETHUSDT  | P4_NO_GATE | adaptive_1x_5x_v1 |           488 |       1.13704  |      -0.506761 |         1.13432 |   0.340164 |        2137.04 |                   0.45246  |
| ETHUSDT  | P4_G1_GATE | fixed_1x          |           341 |       2.729    |      -0.261918 |         1.35345 |   0.384164 |        3729    |                   0.312841 |
| ETHUSDT  | P4_G1_GATE | fixed_2x          |           341 |       9.15918  |      -0.459999 |         1.25108 |   0.384164 |       10159.2  |                   0.395342 |
| ETHUSDT  | P4_G1_GATE | fixed_3x          |           341 |      20.1706   |      -0.613328 |         1.18267 |   0.384164 |       21170.6  |                   0.466161 |
| ETHUSDT  | P4_G1_GATE | adaptive_1x_3x_v1 |           341 |       9.50953  |      -0.27189  |         1.43583 |   0.384164 |       10509.5  |                   0.210833 |
| ETHUSDT  | P4_G1_GATE | adaptive_1x_5x_v1 |           341 |      13.5381   |      -0.298098 |         1.36462 |   0.384164 |       14538.1  |                   0.247719 |
| BTCUSDT  | P4_NO_GATE | fixed_1x          |           488 |       1.54532  |      -0.213177 |         1.27064 |   0.346311 |        2545.32 |                   0.192012 |
| BTCUSDT  | P4_NO_GATE | fixed_2x          |           488 |       4.01212  |      -0.386253 |         1.21129 |   0.346311 |        5012.12 |                   0.234615 |
| BTCUSDT  | P4_NO_GATE | fixed_3x          |           488 |       6.8342   |      -0.525507 |         1.15954 |   0.346311 |        7834.2  |                   0.276217 |
| BTCUSDT  | P4_NO_GATE | adaptive_1x_3x_v1 |           488 |       1.66524  |      -0.239608 |         1.20533 |   0.346311 |        2665.24 |                   0.38872  |
| BTCUSDT  | P4_NO_GATE | adaptive_1x_5x_v1 |           488 |       3.38257  |      -0.250733 |         1.28888 |   0.346311 |        4382.57 |                   0.431997 |
| BTCUSDT  | P4_G1_GATE | fixed_1x          |           349 |       1.33643  |      -0.182517 |         1.38965 |   0.389685 |        2336.43 |                   0.180514 |
| BTCUSDT  | P4_G1_GATE | fixed_2x          |           349 |       3.52171  |      -0.347946 |         1.34687 |   0.389685 |        4521.71 |                   0.187709 |
| BTCUSDT  | P4_G1_GATE | fixed_3x          |           349 |       6.38208  |      -0.491633 |         1.29401 |   0.389685 |        7382.08 |                   0.198555 |
| BTCUSDT  | P4_G1_GATE | adaptive_1x_3x_v1 |           349 |       1.25032  |      -0.188673 |         1.27415 |   0.389685 |        2250.32 |                   0.335978 |
| BTCUSDT  | P4_G1_GATE | adaptive_1x_5x_v1 |           349 |       1.32835  |      -0.23708  |         1.27169 |   0.389685 |        2328.35 |                   0.507316 |

## Portfolio Summary

| portfolio            | prototype         | gate       | leverage_mode     | component_symbols   |   total_return |   max_drawdown |   final_equity | longest_drawdown_duration   |
|:---------------------|:------------------|:-----------|:------------------|:--------------------|---------------:|---------------:|---------------:|:----------------------------|
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_NO_GATE | fixed_1x          | ETHUSDT,BTCUSDT     |        1.06232 |      -0.282441 |        2062.32 | 1150 days 13:04:00          |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_NO_GATE | fixed_2x          | ETHUSDT,BTCUSDT     |        2.34459 |      -0.53303  |        3344.59 | 1150 days 13:04:00          |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_NO_GATE | fixed_3x          | ETHUSDT,BTCUSDT     |        3.55008 |      -0.71468  |        4550.08 | 1150 days 13:04:00          |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_NO_GATE | adaptive_1x_3x_v1 | ETHUSDT,BTCUSDT     |        1.1444  |      -0.261264 |        2144.4  | 802 days 04:34:00           |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_NO_GATE | adaptive_1x_5x_v1 | ETHUSDT,BTCUSDT     |        2.2598  |      -0.265671 |        3259.8  | 772 days 19:04:00           |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_G1_GATE | fixed_1x          | ETHUSDT,BTCUSDT     |        2.03272 |      -0.168527 |        3032.72 | 507 days 21:56:00           |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_G1_GATE | fixed_2x          | ETHUSDT,BTCUSDT     |        6.34045 |      -0.390798 |        7340.45 | 943 days 05:41:00           |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_G1_GATE | fixed_3x          | ETHUSDT,BTCUSDT     |       13.2763  |      -0.572064 |       14276.3  | 1117 days 22:26:00          |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_G1_GATE | adaptive_1x_3x_v1 | ETHUSDT,BTCUSDT     |        5.37992 |      -0.214951 |        6379.92 | 943 days 05:41:00           |
| ETH_BTC_EQUAL_WEIGHT | P4_BREAKOUT_TOP20 | P4_G1_GATE | adaptive_1x_5x_v1 | ETHUSDT,BTCUSDT     |        7.43325 |      -0.24567  |        8433.25 | 1116 days 03:11:00          |

## Interpretation

- RB2 uses only ETH/BTC P4 and realistic candle-close time alignment.
- Results remain expanded_discovery, not OOS.
- If low leverage still has deep drawdown or weak walk-forward, do not move to simulation.
