#!/usr/bin/env python3
"""Minimal prototypes for Carry: FRC1 (Funding Rate Carry) with multi-period holding.

FRC1 (validity fixed):
- Observe known funding rate at settlement time T (calc_time proxy).
- Rate in row treated as proxy for upcoming period.
- Decision uses only known_rate at/prior to entry (no future rates).
- Hold across multiple 8h periods while rate attractive (hysteresis to reduce turnover).
- Roundtrip costs charged only on entry + exit (not per period).
- Funding income attribution uses realized_rate_next (next settled) where available for the period; fallback to known.
- Two-leg PnL: load real close (spot proxy) + mark_price (perp) at entry/exit via asof (no future prices).
- Net = funding_income + (spot_pnl + deriv_pnl) - costs ; basis/residual captured in price diff.
"""

from pathlib import Path
import pandas as pd
import numpy as np

def _load_price_series(data_root: Path, sym: str) -> pd.DataFrame:
    """Load 1m klines with close + mark_price for a symbol if available. Return time-indexed df or empty."""
    candidates = [
        data_root / "new_backtest_data_1year_1m" / f"{sym}.csv",
        data_root / "merged_backtest_data_1m" / f"{sym}_enriched.csv",
        data_root / "mark_price_1m" / f"{sym}.csv",
    ]
    for p in candidates:
        if p.exists():
            try:
                df = pd.read_csv(p)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                    df = df.set_index("timestamp").sort_index()
                    # keep only needed
                    cols = [c for c in ["close", "mark_price", "open", "high", "low"] if c in df.columns]
                    return df[cols].copy()
            except Exception:
                continue
    return pd.DataFrame()

def _get_price_at(px_df: pd.DataFrame, t: pd.Timestamp, col: str) -> float:
    """Get price at or just before t (no lookahead). Returns nan if unavailable."""
    if px_df.empty or col not in px_df.columns or pd.isna(t):
        return np.nan
    try:
        # asof gets last <= t
        val = px_df[col].asof(t)
        return float(val) if pd.notna(val) else np.nan
    except Exception:
        return np.nan

def run_frc1_prototype(funding_events: pd.DataFrame, data_root: Path = Path("/Users/muce/1m_data"), notional=10000, threshold=0.00005, max_hold_periods=6, fee_pct=0.0004, slippage_pct=0.0001):
    """
    Episode-based backtester with real price two-leg where data allows.
    """
    trades = []
    events = funding_events.sort_values(['symbol', 'event_time']).reset_index(drop=True)
    for sym in events['symbol'].unique():
        sym_events = events[events['symbol'] == sym].reset_index(drop=True)
        px = _load_price_series(data_root, sym)
        i = 0
        while i < len(sym_events):
            row = sym_events.iloc[i]
            known = row.get('known_rate', row.get('known_funding_rate', np.nan))
            if pd.isna(known) or known < threshold:
                i += 1
                continue
            entry_time = row['event_time']
            entry_rate = known
            # real prices at entry (asof <= entry)
            s_entry = _get_price_at(px, entry_time, 'close')
            m_entry = _get_price_at(px, entry_time, 'mark_price')
            hold_periods = 0
            total_funding = 0.0
            while i < len(sym_events) and hold_periods < max_hold_periods:
                r = sym_events.iloc[i]
                k = r.get('known_rate', r.get('known_funding_rate', np.nan))
                if pd.isna(k) or k < threshold * 0.8:  # hysteresis
                    break
                # Attribution: prefer realized next settled for this period; fallback known
                inc_rate = r.get('realized_rate_next', r.get('known_rate', k))
                if pd.isna(inc_rate):
                    inc_rate = k
                total_funding += float(inc_rate) * notional
                hold_periods += 1
                i += 1
            if hold_periods == 0:
                i += 1
                continue
            # exit time/price (use current i or last)
            exit_idx = min(i, len(sym_events) - 1)
            exit_time = sym_events.iloc[exit_idx]['event_time']
            s_exit = _get_price_at(px, exit_time, 'close')
            m_exit = _get_price_at(px, exit_time, 'mark_price')
            # Two-leg PnL (delta neutral approx): long spot, short perp using mark
            if pd.notna(s_entry) and pd.notna(s_exit) and s_entry > 0:
                spot_pnl = (s_exit / s_entry - 1.0) * notional
            else:
                spot_pnl = 0.0
            if pd.notna(m_entry) and pd.notna(m_exit) and m_entry > 0:
                # short perp: profit when price falls
                deriv_pnl = (m_entry / m_exit - 1.0) * notional
            else:
                deriv_pnl = 0.0
            basis_pnl = 0.0  # residual basis change embedded in (spot_pnl + deriv_pnl)
            # Costs only on entry/exit (2 legs roundtrip)
            costs = notional * (fee_pct + slippage_pct) * 2
            net = total_funding + spot_pnl + deriv_pnl - costs
            trades.append({
                'trade_id': f'FRC1_{sym}_{entry_time}',
                'symbol': sym,
                'mode': 'funding',
                'entry_time': entry_time,
                'exit_time': exit_time,
                'hold_periods': hold_periods,
                'initial_delta': 0.0,
                'funding_income': total_funding,
                'basis_pnl': basis_pnl,
                'spot_pnl': spot_pnl,
                'deriv_pnl': deriv_pnl,
                'fees': costs / 2,
                'slippage': costs / 2,
                'net_pnl': net,
                'net_return': net / notional,
                'annualized': (net / notional) * (365 / (hold_periods * 8 / 24.0)) if hold_periods > 0 else 0,
                'exit_reason': 'rate_drop_or_max_hold',
                's_entry': s_entry if pd.notna(s_entry) else 0,
                'm_entry': m_entry if pd.notna(m_entry) else 0,
                's_exit': s_exit if pd.notna(s_exit) else 0,
                'm_exit': m_exit if pd.notna(m_exit) else 0,
            })
    return pd.DataFrame(trades)

def main():
    carry_dir = Path("research_core/carry_research")
    ev = pd.read_parquet(carry_dir / "funding_event_table.parquet")
    data_root = Path("/Users/muce/1m_data")
    trades = run_frc1_prototype(ev, data_root=data_root, threshold=0.00005, max_hold_periods=6)
    if not trades.empty:
        trades.to_csv(carry_dir / "carry_trade_decomposition.csv", index=False)
        print(f"Multi-period FRC1 prototype: {len(trades)} episodes (real prices where available)")
        print(trades[['symbol', 'hold_periods', 'net_return', 'annualized']].describe())
        # Also save a summary of two-leg residuals
        if 'spot_pnl' in trades.columns:
            print("Two-leg residual (spot+deriv) mean:", (trades['spot_pnl'] + trades['deriv_pnl']).mean())
    # Update costs with high/stress
    costs = pd.DataFrame([
        {'scenario': 'base_cost', 'roundtrip_fee_pct': 0.0004, 'slippage_pct': 0.0001, 'borrow_daily': 0.0},
        {'scenario': 'high_cost', 'roundtrip_fee_pct': 0.0008, 'slippage_pct': 0.0003, 'borrow_daily': 0.0001},
        {'scenario': 'stress_cost', 'roundtrip_fee_pct': 0.0015, 'slippage_pct': 0.0006, 'borrow_daily': 0.0005}
    ])
    costs.to_csv(carry_dir / "carry_cost_assumptions.csv", index=False)
    print("Cost scenarios expanded.")

if __name__ == "__main__":
    main()
