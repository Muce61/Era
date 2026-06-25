# Era

ETH trend research and backtesting workspace.

This repository is a lightweight migration of the local research codebase. It keeps source code, strategy modules, configs, tests, and lightweight research summaries. Heavy generated artifacts are intentionally excluded from git.

## Included

- Backtest and research scripts under `backtest/`
- Strategy modules under `strategy/`
- Shared research helpers under `research/`
- Config files under `config/` and `configs/`
- Tests under `tests/`
- Lightweight `backtest_results` summaries, conclusions, and metadata

## Excluded

- Raw 1m market data
- Large trade/equity CSV files
- Generated chart PNG files
- Cache directories and Python bytecode
- Local environment files

## Current Research Status

The latest research direction is to stop optimizing individual candlestick entry rules and rebuild the workflow around:

1. event candidate tables,
2. factor extraction,
3. factor monotonicity and stability checks,
4. matched random baselines,
5. bootstrap and path stress tests,
6. fixed-risk validation,
7. true out-of-sample or paper-trading gates.

The currently observed local data window is below the original 3-year minimum, so historical results in this repository are research evidence only and not simulation/live-trading approval.

