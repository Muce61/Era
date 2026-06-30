# Carry Data Inventory & Quality Report (Grok Build)

Generated: 2026-06-30T00:34:10.894705+00:00

## Summary
- Spot 1m: available (new_backtest_data_1year_1m and long_history).
- Perp funding rates: available (calc_time used as conservative known-time proxy; 8h intervals).
- Perp prices / mark / index at funding times: partial (would need aligned price series at exact calc_time).
- Delivery futures (quarterly etc.): **data_unavailable** — no historical expiry prices + rules discovered in standard locations.

## Recommendation
Proceed with **Funding Carry (perp funding income + perp-spot basis)**.
Basis convergence on delivery contracts cannot be studied with current data — mark explicitly.

## Known-Time Note
Funding: use calc_time (or equivalent) as the time the rate becomes known for entry decisions.
Never use post-settlement realized rate for pre-settlement decisions.

## Files
- data_inventory.csv (this run)
