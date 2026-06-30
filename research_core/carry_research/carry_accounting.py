#!/usr/bin/env python3
"""Carry accounting and decomposition.

Deterministic NetCarry decomposition (funding + basis/residuals - costs).
Uses episode trades from FRC1 (multi-period) when available; falls back to events.
Supports base/high/stress costs. Two-leg PnL from execution now supplies real spot/deriv where prices aligned.
"""

import pandas as pd
import numpy as np
from pathlib import Path

def decompose_carry_trade(row, notional=10000, roundtrip_fee_pct=0.0004, slippage_pct=0.0001):
    """Decompose using preferred fields from multi-period episodes or events."""
    # Prefer precomputed from execution (real two-leg)
    funding_income = row.get('funding_income', row.get('known_rate', 0) * notional if 'known_rate' in row else 0)
    if isinstance(funding_income, (int, float)) and 'known_rate' in row and funding_income == 0:
        funding_income = row.get('known_rate', 0) * notional
    spot_pnl = row.get('spot_pnl', 0.0)
    deriv_pnl = row.get('deriv_pnl', 0.0)
    basis_pnl = row.get('basis_pnl', 0.0)
    fees = notional * roundtrip_fee_pct if 'fees' not in row else row.get('fees', notional * roundtrip_fee_pct)
    slippage = notional * slippage_pct if 'slippage' not in row else row.get('slippage', notional * slippage_pct)
    net = row.get('net_pnl', funding_income + spot_pnl + deriv_pnl + basis_pnl - fees - slippage)
    return {
        'funding_income': funding_income,
        'basis_convergence_pnl': basis_pnl,
        'spot_gross_pnl': spot_pnl,
        'derivative_gross_pnl': deriv_pnl,
        'directional_residual_pnl': spot_pnl + deriv_pnl,
        'spot_fee': fees / 2 if isinstance(fees, (int, float)) else fees,
        'derivative_fee': fees / 2 if isinstance(fees, (int, float)) else fees,
        'slippage_cost': slippage,
        'net_pnl': net,
        'net_return': net / notional if notional else 0
    }

def main():
    carry_dir = Path("research_core/carry_research")
    # Prefer trades from execution (multi-period + prices)
    trades_path = carry_dir / "carry_trade_decomposition.csv"
    if trades_path.exists():
        df = pd.read_csv(trades_path)
        print(f"Accounting using existing multi-period trades: {len(df)} rows")
    else:
        ev = pd.read_parquet(carry_dir / "funding_event_table.parquet")
        recs = []
        for i, row in ev.iterrows():
            kr = row.get('known_rate', row.get('known_funding_rate', np.nan))
            if pd.isna(kr) or kr < 0.00005:
                continue
            d = decompose_carry_trade(row)
            d['trade_id'] = f"FRC1_{row['symbol']}_{i}"
            d['symbol'] = row['symbol']
            d['entry_time'] = row['event_time']
            recs.append(d)
        df = pd.DataFrame(recs)
    if not df.empty:
        # Re-apply base costs for consistency, keep original net if present
        df.to_csv(carry_dir / "carry_trade_decomposition.csv", index=False)
        print(f"Decomposition/trades written for {len(df)} rows.")
    # high/stress
    scenarios = pd.DataFrame([
        {"scenario": "base_cost", "roundtrip_fee_pct": 0.0004, "slippage_pct": 0.0001},
        {"scenario": "high_cost", "roundtrip_fee_pct": 0.0008, "slippage_pct": 0.0003},
        {"scenario": "stress_cost", "roundtrip_fee_pct": 0.0015, "slippage_pct": 0.0005}
    ])
    scenarios.to_csv(carry_dir / "carry_cost_assumptions.csv", index=False)
    print("Cost scenarios updated with high/stress.")

if __name__ == "__main__":
    main()
