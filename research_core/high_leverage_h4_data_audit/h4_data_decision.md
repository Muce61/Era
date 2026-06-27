# H4 Data Decision

discovery_end: 2026-06-24T12:05:00+00:00
time_oos_status: blocked
time_oos_reason: oos_data_unavailable_or_insufficient
time_oos_best_path: /Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv
time_oos_coverage_days: 2.5729
holdout_symbols: ['XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT']
holdout_symbol_count: 5
finer_data_available: False

H4 uses time OOS first. If time OOS is insufficient, it uses cross_asset_holdout, which is not time OOS.

## Inventory

| symbol   | is_discovery_symbol   |   path_count | paths                                                                                                           | candidate_layer     |
|:---------|:----------------------|-------------:|:----------------------------------------------------------------------------------------------------------------|:--------------------|
| XRPUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/XRPUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/XRPUSDT.csv   | cross_asset_holdout |
| ADAUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/ADAUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/ADAUSDT.csv   | cross_asset_holdout |
| DOGEUSDT | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/DOGEUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/DOGEUSDT.csv | cross_asset_holdout |
| AVAXUSDT | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/AVAXUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/AVAXUSDT.csv | cross_asset_holdout |
| LINKUSDT | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/LINKUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/LINKUSDT.csv | cross_asset_holdout |
| LTCUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/LTCUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/LTCUSDT.csv   | cross_asset_holdout |
| BCHUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/BCHUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/BCHUSDT.csv   | cross_asset_holdout |
| DOTUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/DOTUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/DOTUSDT.csv   | cross_asset_holdout |
| TRXUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/TRXUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/TRXUSDT.csv   | cross_asset_holdout |
| OPUSDT   | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/OPUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/OPUSDT.csv     | cross_asset_holdout |
| ARBUSDT  | False                 |            2 | /Users/muce/1m_data/2024_validation_1m/ARBUSDT.csv|/Users/muce/1m_data/new_backtest_data_1year_1m/ARBUSDT.csv   | cross_asset_holdout |
