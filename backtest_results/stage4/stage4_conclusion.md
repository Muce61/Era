# ETH Stage 4 Conclusion

data_coverage_limitation = true
data_coverage_status = below_original_minimum
data_window = 2024-01-01 00:00:00 UTC 到 2026-06-24 12:05:00 UTC

## Comparison (engine, fixed 2x)

| label   |   total_trades |   total_return_pct |   max_drawdown_pct |   profit_factor |
|:--------|---------------:|-------------------:|-------------------:|----------------:|
| B0      |            401 |           -58.1721 |           -72.1707 |        0.893358 |
| B1      |            324 |           -14.2392 |           -55.3104 |        0.978362 |
| B2      |            195 |            41.5996 |           -39.2485 |        1.10274  |
| B3      |             84 |           104.006  |           -24.6885 |        1.58409  |
| C1      |            371 |           -66.2558 |           -77.7619 |        0.867646 |

## Random Baseline (C0' matched to C1 trade count)

|   total_return |   profit_factor |   max_drawdown |    calmar |   avg_mae_atr |   avg_mfe_atr |   top5_profit_contribution |   return_percentile |   pf_percentile |   drawdown_percentile |   calmar_percentile |   mfe_mae_percentile |   c1_trade_count |   candidate_count |   random_runs |   exact_trade_count_match_rate | low_sample_random_baseline   |
|---------------:|----------------:|---------------:|----------:|--------------:|--------------:|---------------------------:|--------------------:|----------------:|----------------------:|--------------------:|---------------------:|-----------------:|------------------:|--------------:|-------------------------------:|:-----------------------------|
|       -66.2558 |        0.867646 |       -77.7619 | -0.456473 |       -2.0797 |       4.67798 |                          0 |               94.58 |           99.46 |                 12.88 |                96.1 |                  100 |              371 |             18179 |          5000 |                              1 | False                        |

## Bootstrap C1 trade-level

| label   | method          |   runs |   median_final_return |   median_max_drawdown |   median_pf |   loss_probability |   pf_lt_1_probability |   equity_below_80_probability | bootstrap_low_trade_count   |
|:--------|:----------------|-------:|----------------------:|----------------------:|------------:|-------------------:|----------------------:|------------------------------:|:----------------------------|
| C1      | trade           |   5000 |              -68.1642 |              -97.3496 |    0.863291 |             0.802  |                0.802  |                        0.9308 | False                       |
| C1      | monthly_block   |   5000 |              -65.7636 |              -91.1176 |    0.867912 |             0.812  |                0.812  |                        0.922  | False                       |
| C1      | quarterly_block |   5000 |              -60.3432 |              -79.9077 |    0.878237 |             0.9018 |                0.9018 |                        0.9386 | False                       |

## Final Verdict

D. C1 未通过阶段2级检验（全样本 PF<1，Bootstrap 多数 PF<1）

模拟盘：本地数据不足 3 年，不允许正式模拟盘准入。