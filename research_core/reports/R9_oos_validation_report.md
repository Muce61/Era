# R9 OOS Validation Report

data_layer: oos
status: blocked
reason: oos_data_unavailable_or_insufficient
final_conclusion: E. OOS 数据不足，无法判断

当前本地新增 ETHUSDT 1m 数据不足 3 个月，因此 R9 按规则停止，不生成策略性 OOS 结论。

## Required Answers

1. 是否存在合格 OOS 数据：否，覆盖不足。最佳候选 `/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv`。
2. OOS 数据覆盖多久：约 2.5729 天。
3. OOS 事件数量是否足够：未构建 OOS 事件表，因为数据覆盖不足。
4. P4 是否仍优于 P1/C1：无法判断。
5. P6 是否仍优于 P1/C1：无法判断。
6. P3 是否仍值得保留：无法判断，等待新增数据。
7. P5 是否仍值得保留：无法判断，等待新增数据。
8. discovery 到 OOS 是否明显衰减：无法判断。
9. 是否存在 selection-on-discovery 偏差：仍然存在该风险，因为没有足够 OOS。
10. 是否允许进入 R10 模拟盘观察准备：不允许。

## Best Candidate Quality

| path                                                       | full_start_utc            | full_end_utc              | oos_start_utc             | oos_end_utc               |   oos_row_count |   oos_coverage_days | timestamp_utc_assumed   | monotonic_increasing   |   duplicate_timestamp_count |   missing_range_count |   missing_minute_count |   invalid_ohlc_count |   outlier_count | overlaps_discovery   | coverage_status   |
|:-----------------------------------------------------------|:--------------------------|:--------------------------|:--------------------------|:--------------------------|----------------:|--------------------:|:------------------------|:-----------------------|----------------------------:|----------------------:|-----------------------:|---------------------:|----------------:|:---------------------|:------------------|
| /Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv | 2024-12-01T00:00:00+00:00 | 2026-06-27T01:51:00+00:00 | 2026-06-24T12:06:00+00:00 | 2026-06-27T01:51:00+00:00 |            3706 |             2.57292 | True                    | True                   |                           0 |                     0 |                      0 |                    0 |               0 | True                 | insufficient      |
