# 100x High-Confirmation Gambling Trading System

This repository is the governed research and engineering workspace for the system defined by the V1.3.4 final manual. It does not claim profitability, completed implementation, or passed backtests.

- Current specification: `docs/spec/system_manual_v1.3.4_final.md`
- Archived source documents and mapping: `docs/spec/README.md`
- Development governance: `docs/development/README.md`
- Current status: specification imported; governance initialized; business development not started.

Stage and Task planning exists under `docs/development/`. Only explicitly approved Tasks may be executed, one at a time. Do not run this repository against testnet or real funds, and do not treat any historical scenario as live execution evidence.

## Development status

Stage 0 Plan v1.0 is approved. S0-T01 establishes only the Python 3.12 project skeleton under `src/era100x/`; no data, research, strategy, risk, state-machine, execution, Binance, testnet, or live-trading capability exists.

From the repository root, the S0-T01 checks are:

```bash
python3.12 -m compileall -q src tests
python3.12 -m unittest tests/test_package_import.py
```

On this workstation, `/opt/homebrew/anaconda3/bin` must be present on `PATH` for the `python3.12` executable.
