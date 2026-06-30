#!/usr/bin/env python3
"""Funding event study using real historical funding rates with known-at-time.

Key timing semantics (validity fix):
- event_time from calc_time: the moment the funding rate is known/published.
- The rate in the row (last_funding_rate) at T is treated as applying to / proxy for the *upcoming* period's income (per prompt guidance).
- known_rate: rate observed at decision time T (no lookahead).
- realized_rate_next (shift(-1)): the rate published at next settlement; used as proxy for the actual income rate received for the period started after decision at T.
- forward_delta = realized_rate_next - known_rate (delta, not absolute level; sign indicates continuation vs mean-reversion).
- All decisions use only data known at or before event_time.
- Outputs include cost coverage estimate (using base per-period cost proxy).
"""

from pathlib import Path
import pandas as pd
import numpy as np

def run_funding_event_study(data_dir: Path, symbols: list, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    all_events = []
    for sym in symbols:
        f = data_dir / "derivatives_data" / f"{sym}_fundingRate.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        df["event_time"] = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
        df = df.sort_values("event_time").reset_index(drop=True)
        df["symbol"] = sym
        # Treat row rate as known for upcoming period decision
        df["known_rate"] = df["last_funding_rate"]
        # realized for the upcoming period = rate at next settlement (proxy for income locked by acting at T)
        df["realized_rate_next"] = df["last_funding_rate"].shift(-1)
        df["forward_delta"] = df["realized_rate_next"] - df["known_rate"]
        df["funding_period_start"] = df["event_time"]
        df["funding_rate_known_at_entry"] = df["event_time"]
        # For attribution: income proxy for decision at this row uses realized next (next settled)
        df["realized_income_rate"] = df["realized_rate_next"]
        all_events.append(df[["symbol", "event_time", "known_rate", "realized_rate_next", "forward_delta", "funding_period_start", "funding_rate_known_at_entry", "realized_income_rate"]])
    if all_events:
        ev = pd.concat(all_events, ignore_index=True)
        ev.to_parquet(output_dir / "funding_event_table.parquet", index=False)
        ev.head(500).to_csv(output_dir / "funding_event_table_sample.csv", index=False)
        summ = ev.groupby("symbol").agg(
            n_events=("known_rate", "count"),
            mean_known=("known_rate", "mean"),
            mean_realized=("realized_rate_next", "mean"),
            mean_forward_delta=("forward_delta", "mean"),
            pos_realized=("realized_rate_next", lambda x: (x > 0).mean()),
            pos_delta=("forward_delta", lambda x: (x > 0).mean()),
        ).reset_index()
        # Rough per-period cost coverage (base: ~8bp roundtrip / 2 legs amortized or fixed 5bp example)
        base_period_cost = 0.0005  # 5bp proxy per period for illustration
        summ["mean_realized_bp"] = summ["mean_realized"] * 10000
        summ["est_cost_coverage"] = summ["mean_realized"] / base_period_cost
        summ.to_csv(output_dir / "funding_event_summary.csv", index=False)
        summ.to_csv(output_dir / "funding_persistence_summary.csv", index=False)
        print(f"Funding event study complete for {len(all_events)} symbols. Total events: {len(ev)}")
        print("Note: realized_income_rate uses next settled rate (shift) for upcoming period attribution.")
        return ev
    return pd.DataFrame()

if __name__ == "__main__":
    data_dir = Path("/Users/muce/1m_data")
    symbols = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
    output_dir = Path("research_core/carry_research")
    run_funding_event_study(data_dir, symbols, output_dir)
