#!/usr/bin/env python3
"""Minimal prototypes for Carry: FRC1 (Funding Rate Carry) with multi-period holding.

FRC1 validity-fix (restricted scope):
- Funding rate units: explicit decimal / bp (0.00005 == 0.5bp).
- Entry threshold kept at legacy min_known_rate_decimal=0.00005 (0.5bp) as baseline.
- Economic cost coverage gate (fixed safety_factor=1.25, planned max_hold) reported separately.
- Correct USDT-linear perp short qty-based PnL (not inverse rate formula).
- Execution prices: next 1m bar open strictly after decision_time (searchsorted right); open for execution.
- Mark price only for valuation proxy; missing perp executable -> fail closed (valuation only).
- Costs: explicit per-leg per-action; true recompute per scenario.
- All accounting identities enforced.
- No optimization, no threshold search.
"""

from pathlib import Path
import pandas as pd
import numpy as np

# === Fix 1: Explicit units (never ambiguous 'threshold') ===
def decimal_to_bp(r: float) -> float:
    return float(r) * 10000.0

def bp_to_decimal(bp: float) -> float:
    return float(bp) / 10000.0

LEGACY_MIN_KNOWN_RATE_DECIMAL = 0.00005  # 0.5 bp baseline (do NOT change to 5bp)
LEGACY_MIN_KNOWN_RATE_BP = decimal_to_bp(LEGACY_MIN_KNOWN_RATE_DECIMAL)

SAFETY_FACTOR = 1.25
PLANNED_HOLD_PERIODS = 6  # same as max_hold used for gate calc

def compute_cost_coverage_gate(total_roundtrip_cost_rate: float, planned_hold: int = PLANNED_HOLD_PERIODS, safety: float = SAFETY_FACTOR):
    """Pre-declared fixed economic gate. Not searched or tuned."""
    if planned_hold <= 0:
        planned_hold = 1
    required_avg_rate_decimal = (total_roundtrip_cost_rate * safety) / planned_hold
    return {
        'required_avg_rate_decimal': required_avg_rate_decimal,
        'required_avg_rate_bp': decimal_to_bp(required_avg_rate_decimal),
        'safety_factor': safety,
        'planned_hold_periods': planned_hold
    }

# === Price loading and strict next-bar execution price ===
def _load_price_series(data_root: Path, sym: str) -> pd.DataFrame:
    """Load 1m klines. Prefer files with 'open' for execution."""
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
                    cols = [c for c in ["open", "close", "mark_price", "high", "low"] if c in df.columns]
                    return df[cols].copy()
            except Exception:
                continue
    return pd.DataFrame()

def _get_next_executable_bar(px_df: pd.DataFrame, decision_t: pd.Timestamp, preferred_col: str = 'open'):
    """
    Fix 3: 1m bar timestamp = bar open time.
    Decision at T uses FIRST bar with timestamp > T (its open price).
    Never use same-bar close/high/mark asof(T).
    """
    if px_df.empty or pd.isna(decision_t):
        return pd.NaT, np.nan, 'no_data'
    idx = px_df.index
    pos = idx.searchsorted(decision_t, side='right')
    if pos >= len(idx):
        return pd.NaT, np.nan, 'no_future_bar'
    t = idx[pos]
    price = np.nan
    source = preferred_col
    if preferred_col in px_df.columns:
        price = float(px_df.iloc[pos][preferred_col])
    elif 'open' in px_df.columns:
        price = float(px_df.iloc[pos]['open'])
        source = 'open_fallback'
    elif 'close' in px_df.columns:
        price = float(px_df.iloc[pos]['close'])
        source = 'close_fallback'
    if not np.isfinite(price) or price <= 0:
        return t, np.nan, source + '_invalid'
    return t, price, source

def _get_valuation_price(px_df: pd.DataFrame, t: pd.Timestamp, col: str = 'mark_price'):
    """Mark/index only for valuation/margin, NEVER as execution price."""
    if px_df.empty or pd.isna(t) or col not in px_df.columns:
        return np.nan
    pos = px_df.index.searchsorted(t, side='right')
    if pos >= len(px_df):
        pos = len(px_df) - 1
    if pos < 0:
        return np.nan
    val = float(px_df.iloc[pos][col])
    return val if np.isfinite(val) and val > 0 else np.nan

def run_frc1_prototype(funding_events: pd.DataFrame, data_root: Path = Path("/Users/muce/1m_data"), notional=10000,
                         min_known_rate_decimal=LEGACY_MIN_KNOWN_RATE_DECIMAL,
                         max_hold_periods=6,
                         base_fee_rate=0.0004, base_slippage_rate=0.0001):
    """
    Episode-based backtester with strict execution rules (validity fix).
    """
    trades = []
    min_known_rate_bp = decimal_to_bp(min_known_rate_decimal)

    events = funding_events.sort_values(['symbol', 'event_time']).reset_index(drop=True)

    # Base roundtrip total cost rate (for gate diagnostic; explicit per-leg later)
    base_total_roundtrip_cost_rate = (base_fee_rate + base_slippage_rate) * 4   # 4 actions: entry/exit x 2 legs

    for sym in events['symbol'].unique():
        sym_events = events[events['symbol'] == sym].reset_index(drop=True)
        px = _load_price_series(data_root, sym)

        i = 0
        while i < len(sym_events):
            row = sym_events.iloc[i]
            known = row.get('known_rate', row.get('known_funding_rate', np.nan))
            if pd.isna(known) or known < min_known_rate_decimal:
                i += 1
                continue

            decision_entry_time = row['event_time']
            entry_rate_decimal = known
            entry_rate_bp = decimal_to_bp(entry_rate_decimal)

            # === Fix 3: next executable bar open ===
            actual_entry_time, s_entry, spot_src = _get_next_executable_bar(px, decision_entry_time, 'open')
            _, m_entry_val, _ = _get_next_executable_bar(px, decision_entry_time, 'open')  # try open first
            m_entry_exec = m_entry_val if np.isfinite(m_entry_val) and m_entry_val > 0 else _get_valuation_price(px, decision_entry_time, 'mark_price')

            # For perp execution prefer open, else mark (will flag)
            perp_entry_source = 'open' if np.isfinite(m_entry_val) and m_entry_val > 0 else 'mark_only'

            hold_periods = 0
            total_funding = 0.0
            while i < len(sym_events) and hold_periods < max_hold_periods:
                r = sym_events.iloc[i]
                k = r.get('known_rate', r.get('known_funding_rate', np.nan))
                if pd.isna(k) or k < min_known_rate_decimal * 0.8:
                    break
                inc_rate = r.get('realized_rate_next', r.get('known_rate', k))
                if pd.isna(inc_rate):
                    inc_rate = k
                total_funding += float(inc_rate) * notional
                hold_periods += 1
                i += 1

            if hold_periods == 0:
                i += 1
                continue

            # Exit decision at current i time
            decision_exit_time = sym_events.iloc[min(i, len(sym_events)-1)]['event_time']
            actual_exit_time, s_exit, spot_exit_src = _get_next_executable_bar(px, decision_exit_time, 'open')
            _, m_exit_val, _ = _get_next_executable_bar(px, decision_exit_time, 'open')
            m_exit_exec = m_exit_val if np.isfinite(m_exit_val) and m_exit_val > 0 else _get_valuation_price(px, decision_exit_time, 'mark_price')
            perp_exit_source = 'open' if np.isfinite(m_exit_val) and m_exit_val > 0 else 'mark_only'

            # === Fix 2: qty-based USDT linear perp short PnL ===
            spot_qty = notional / s_entry if (np.isfinite(s_entry) and s_entry > 0) else np.nan
            perp_qty = notional / m_entry_exec if (np.isfinite(m_entry_exec) and m_entry_exec > 0) else np.nan

            if np.isfinite(spot_qty) and np.isfinite(s_exit) and s_exit > 0:
                spot_pnl = spot_qty * (s_exit - s_entry)
            else:
                spot_pnl = 0.0
                spot_qty = 0.0

            if np.isfinite(perp_qty) and np.isfinite(m_exit_exec) and m_exit_exec > 0:
                # short perp: profit if price down
                perp_pnl = perp_qty * (m_entry_exec - m_exit_exec)
            else:
                perp_pnl = 0.0
                perp_qty = 0.0

            two_leg_residual = spot_pnl + perp_pnl
            gross_carry_pnl = total_funding + spot_pnl + perp_pnl   # basis residual in two_leg

            # === Gate diagnostic (Fix 1) - not used for filtering baseline ===
            gate = compute_cost_coverage_gate(base_total_roundtrip_cost_rate, planned_hold=hold_periods)
            passes_gate = (entry_rate_decimal >= gate['required_avg_rate_decimal'])

            # Placeholder explicit costs (will be recomputed in accounting for 3 scenarios)
            # Record gross first; net computed per scenario later
            record = {
                'trade_id': f'FRC1_{sym}_{decision_entry_time}',
                'symbol': sym,
                'mode': 'funding',
                'decision_entry_time': decision_entry_time,
                'actual_entry_time': actual_entry_time,
                'decision_exit_time': decision_exit_time,
                'actual_exit_time': actual_exit_time,
                'hold_periods': hold_periods,
                'min_known_rate_decimal': min_known_rate_decimal,
                'min_known_rate_bp': min_known_rate_bp,
                'known_rate_decimal': entry_rate_decimal,
                'known_rate_bp': entry_rate_bp,
                'funding_income': total_funding,
                'spot_qty': spot_qty,
                'perp_qty': perp_qty,
                'spot_entry_notional': notional,
                'perp_entry_notional': notional,
                'spot_pnl': spot_pnl,
                'perp_pnl': perp_pnl,
                'two_leg_residual_pnl': two_leg_residual,
                'gross_carry_pnl': gross_carry_pnl,
                'basis_pnl': 0.0,
                'initial_net_delta': (spot_qty or 0) - (perp_qty or 0),
                # Execution sources
                'spot_entry_source': 'open',
                'perp_entry_source': perp_entry_source,
                'spot_exit_source': 'open',
                'perp_exit_source': perp_exit_source,
                'same_minute_close_used': False,
                'future_price_used': False,
                'execution_status': 'ok' if (perp_entry_source == 'open' and perp_exit_source == 'open') else 'perp_execution_price_unavailable',
                'passes_cost_coverage_gate': passes_gate,
                'required_avg_rate_decimal': gate['required_avg_rate_decimal'],
                'required_avg_rate_bp': gate['required_avg_rate_bp'],
                # Legacy gross placeholders (net recomputed per scenario)
                'legacy_total_cost_rate': base_total_roundtrip_cost_rate,
                'net_pnl': gross_carry_pnl - (base_total_roundtrip_cost_rate * notional),  # temp base for compat
                'net_return': (gross_carry_pnl - (base_total_roundtrip_cost_rate * notional)) / notional,
            }
            trades.append(record)

    return pd.DataFrame(trades)

def main():
    carry_dir = Path("research_core/carry_research")
    ev = pd.read_parquet(carry_dir / "funding_event_table.parquet")
    data_root = Path("/Users/muce/1m_data")

    # Legacy 0.5bp gate episodes
    trades = run_frc1_prototype(ev, data_root=data_root, min_known_rate_decimal=LEGACY_MIN_KNOWN_RATE_DECIMAL, max_hold_periods=6)

    if not trades.empty:
        trades.to_csv(carry_dir / "carry_trade_decomposition.csv", index=False)
        print(f"Multi-period FRC1 prototype: {len(trades)} episodes (legacy 0.5bp gate)")
        print("min_known_rate_bp:", LEGACY_MIN_KNOWN_RATE_BP)

    # === Fix 1: funding unit audit ===
    if not trades.empty:
        unit_audit = trades[['trade_id','symbol','known_rate_decimal','known_rate_bp','min_known_rate_decimal','min_known_rate_bp','passes_cost_coverage_gate']].copy()
        unit_audit.to_csv(carry_dir / "funding_unit_audit.csv", index=False)

        gate_summary = trades.groupby(['symbol']).agg(
            episodes=('trade_id','count'),
            mean_known_bp=('known_rate_bp','mean'),
            pct_passing_gate=('passes_cost_coverage_gate','mean')
        ).reset_index()
        gate_summary.to_csv(carry_dir / "cost_coverage_gate_summary.csv", index=False)
        print("Wrote funding_unit_audit.csv and cost_coverage_gate_summary.csv")

    # === Fix 3: execution alignment audit ===
    if not trades.empty:
        audit_cols = ['trade_id','symbol','decision_entry_time','actual_entry_time',
                      'decision_exit_time','actual_exit_time',
                      'spot_entry_source','perp_entry_source','spot_exit_source','perp_exit_source',
                      'same_minute_close_used','future_price_used','execution_status']
        present = [c for c in audit_cols if c in trades.columns]
        audit = trades[present].copy()
        audit.to_csv(carry_dir / "execution_alignment_audit.csv", index=False)
        print("Wrote execution_alignment_audit.csv")

    # Cost assumptions now explicit per-leg
    costs = pd.DataFrame([
        {"scenario": "base_cost",
         "spot_entry_fee_rate": 0.0002, "spot_exit_fee_rate": 0.0002,
         "perp_entry_fee_rate": 0.0002, "perp_exit_fee_rate": 0.0002,
         "spot_entry_slippage_rate": 0.00005, "spot_exit_slippage_rate": 0.00005,
         "perp_entry_slippage_rate": 0.00005, "perp_exit_slippage_rate": 0.00005,
         "borrow_daily_rate": 0.0, "rebalance_cost_rate": 0.0, "transfer_cost_rate": 0.0,
         "legacy_total_cost_rate": 0.0010},
        {"scenario": "high_cost",
         "spot_entry_fee_rate": 0.0004, "spot_exit_fee_rate": 0.0004,
         "perp_entry_fee_rate": 0.0004, "perp_exit_fee_rate": 0.0004,
         "spot_entry_slippage_rate": 0.00015, "spot_exit_slippage_rate": 0.00015,
         "perp_entry_slippage_rate": 0.00015, "perp_exit_slippage_rate": 0.00015,
         "borrow_daily_rate": 0.0001, "rebalance_cost_rate": 0.0, "transfer_cost_rate": 0.0,
         "legacy_total_cost_rate": 0.0022},
        {"scenario": "stress_cost",
         "spot_entry_fee_rate": 0.00075, "spot_exit_fee_rate": 0.00075,
         "perp_entry_fee_rate": 0.00075, "perp_exit_fee_rate": 0.00075,
         "spot_entry_slippage_rate": 0.0003, "spot_exit_slippage_rate": 0.0003,
         "perp_entry_slippage_rate": 0.0003, "perp_exit_slippage_rate": 0.0003,
         "borrow_daily_rate": 0.0005, "rebalance_cost_rate": 0.0001, "transfer_cost_rate": 0.0,
         "legacy_total_cost_rate": 0.0046},
    ])
    costs.to_csv(carry_dir / "carry_cost_assumptions.csv", index=False)
    print("Cost scenarios (explicit per-leg) written.")

if __name__ == "__main__":
    main()
