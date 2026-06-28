# Long History Data Expansion

Run timestamp: `2026-06-28T06:30:30.417909+00:00`
Download months: `2020-01` to `2023-12`

Large merged CSV files are stored outside Git under `/Users/muce/1m_data/long_history_1m/merged/`.
This data is expanded discovery/internal validation, not OOS.

## Quality Summary

| symbol   | start_utc                 | end_utc                   |   row_count |   coverage_days |   duplicate_timestamp_count |   missing_range_count |   missing_minute_count |   invalid_ohlc_count |   outlier_count | monotonic_increasing   | path                                                   | sha256                                                           |
|:---------|:--------------------------|:--------------------------|------------:|----------------:|----------------------------:|----------------------:|-----------------------:|---------------------:|----------------:|:-----------------------|:-------------------------------------------------------|:-----------------------------------------------------------------|
| ETHUSDT  | 2020-01-01T00:00:00+00:00 | 2026-06-28T01:05:00+00:00 |     3412866 |         2370.05 |                           0 |                     0 |                      0 |                    0 |               3 | True                   | /Users/muce/1m_data/long_history_1m/merged/ETHUSDT.csv | 477d3d26d4548d9a28613c254b9ba2330743231ab8fd8c0871520fb410e17cb1 |

## Download Status

| symbol   | status               |   months |
|:---------|:---------------------|---------:|
| ETHUSDT  | downloaded_or_cached |       48 |

