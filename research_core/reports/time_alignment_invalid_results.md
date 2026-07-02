# Time Alignment Invalid Results

status: time_alignment_invalid

The older Research Core backtests used 15m candles with the Pandas default left label as if that timestamp were the candle close time. This allowed signals and Donchian exits to execute before the 15m candle was actually complete.

Invalidated evidence scope:

- R8 minimal backtest
- R9 OOS validation if it used the old event table
- Cross Asset Validation
- L1/L2 leverage research
- H1/H2/H3/H4 high leverage research
- LH1 ETH long history
- 10-symbol long history first run

These files are retained as historical artifacts, but they must not be cited as valid strategy evidence. RB1 realistic replay is the new canonical repaired output.
