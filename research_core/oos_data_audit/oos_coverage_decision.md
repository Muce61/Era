# R9 OOS Coverage Decision

discovery_end: 2026-06-24T12:05:00+00:00
status: blocked
reason: oos_data_unavailable_or_insufficient
best_path: /Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv
coverage_days: 2.5729
conclusion: E. OOS 数据不足，无法判断

R9 requires at least 90 days of ETHUSDT 1m data strictly after the discovery end.

## Inventory Summary

- candidate_files: 51
- files_with_oos_rows: 2

## Quality Summary

| path                                                            | full_start_utc            | full_end_utc              | oos_start_utc             | oos_end_utc               |   oos_row_count |   oos_coverage_days | timestamp_utc_assumed   | monotonic_increasing   |   duplicate_timestamp_count |   missing_range_count |   missing_minute_count |   invalid_ohlc_count |   outlier_count | overlaps_discovery   | coverage_status   |
|:----------------------------------------------------------------|:--------------------------|:--------------------------|:--------------------------|:--------------------------|----------------:|--------------------:|:------------------------|:-----------------------|----------------------------:|----------------------:|-----------------------:|---------------------:|----------------:|:---------------------|:------------------|
| /Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv      | 2024-12-01T00:00:00+00:00 | 2026-06-27T01:51:00+00:00 | 2026-06-24T12:06:00+00:00 | 2026-06-27T01:51:00+00:00 |            3706 |             2.57292 | True                    | True                   |                           0 |                     0 |                      0 |                    0 |               0 | True                 | insufficient      |
| /Users/muce/1m_data/new_backtest_data_1year_1m/NEIROETHUSDT.csv | 2024-12-01T00:00:00+00:00 | 2026-06-27T01:16:00+00:00 | 2026-06-24T12:06:00+00:00 | 2026-06-27T01:16:00+00:00 |            3671 |             2.54861 | True                    | True                   |                           0 |                     0 |                      0 |                    0 |               0 | True                 | insufficient      |
