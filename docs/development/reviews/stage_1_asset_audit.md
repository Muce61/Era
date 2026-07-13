# Stage 1 Asset Audit

- Root: `/Users/muce/1m_data/klines_data_usdm_1s_agg` (read-only policy).
- BTCUSDT and ETHUSDT each contain 2016 CSV and 371 Parquet files covering 2376 continuous UTC dates from 2020-01-01 through 2026-07-03.
- Eleven dates (2025-12-07 through 2025-12-17) exist in both formats. Full-row comparison found equal timestamps and OHLCV values; CSV is canonical on overlap.
- CSV uses decimal text and millisecond `ts_sec`; Parquet uses timestamp[ns] and float64 OHLCV. Parquet-only evidence must be marked `SOURCE_FLOAT64` and converted through stable string representation.
- Each daily file contains 86,400 rows in inspected boundary/overlap samples. Zero-volume seconds exist and must not be mistaken for missing executable quotes.
- Total BTC directory size is approximately 9.1 GiB; ETH approximately 9.0 GiB. The broader root contains unrelated instruments and must not be scanned as Stage 1 input beyond these two approved subdirectories.
- Current writable root is `/Volumes/FuckingLife/era100x_stage1` (approved 2026-07-13). `/Users/muce/1m_data/era100x_stage1` is SUPERSEDED and must not be used as a write target.
