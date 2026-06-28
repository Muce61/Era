"""LH1 ETH long-history validation helpers."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research_core.event_table import add_base_indicators, build_event_candidates, load_ohlcv_1m, strict_resample_15m
from research_core.high_leverage_gate_analysis import gate_mask_fixed, high_risk_mask_fixed
from research_core.high_leverage_h4_validation_analysis import discovery_percentile
from research_core.minimal_backtest_analysis import (
    BacktestParams,
    SIZING_MODES,
    enrich_events_with_exit_info,
    period_trade_summary,
    prepare_market_data,
    run_prototype_backtest,
    summarize_backtest,
)
from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks, transform_oos_scores
from research_core.strict_high_leverage_replay import strict_replay_events, strict_summary


LH1_PROTOTYPES = [
    "P1_C1_FIRST_BREAKOUT",
    "P2_STRONG_BREAKOUT",
    "P4_BREAKOUT_TOP20",
    "P6_MOMENTUM_OR_BREAKOUT_TOP20",
]
LH1_STRICT_PROTOTYPES = ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
LH1_GATES = ["G0_NO_PATH_GATE", "G1_SINGLE_BEST_PATH_SAFETY", "G4_RISK_MONITOR_DOWNSHIFT"]
LH1_LEVERAGE_MODES = ["fixed_10x", "fixed_20x", "adaptive_3x_8x_v1", "adaptive_4x_10x_v1", "adaptive_5x_12x_v1"]
LH1_HORIZONS = [1, 4, 8, 16, 32]


def load_or_build_long_events(data_path: Path, event_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_1m = load_ohlcv_1m(data_path)
    data_15m = add_base_indicators(strict_resample_15m(data_1m))
    if event_path.exists():
        events = pd.read_parquet(event_path)
    else:
        events, data_15m = build_event_candidates(data_1m, symbol="ETHUSDT")
        event_path.parent.mkdir(parents=True, exist_ok=True)
        events.to_parquet(event_path, index=False)
    events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
    events["execution_time"] = pd.to_datetime(events["execution_time"], utc=True)
    return data_1m, data_15m, events.reset_index(drop=True)


def build_lh1_scores(events: pd.DataFrame, metadata: pd.DataFrame, discovery_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scores = transform_oos_scores(events, metadata)
    scores["momentum_score_quantile"] = discovery_percentile(
        scores["momentum_score"],
        discovery_scores["momentum_continuation_score"],
    )
    scores["breakout_score_quantile"] = discovery_percentile(
        scores["breakout_score"],
        discovery_scores["breakout_conviction_score"],
    )
    checks = []
    for col in ["momentum_score", "breakout_score", "momentum_score_quantile", "breakout_score_quantile"]:
        values = pd.to_numeric(scores[col], errors="coerce")
        checks.append({
            "field": col,
            "missing_rate": float(values.isna().mean()),
            "min": float(values.min()),
            "p05": float(values.quantile(0.05)),
            "p50": float(values.quantile(0.50)),
            "p95": float(values.quantile(0.95)),
            "max": float(values.max()),
            "source": "discovery_metadata_transform",
        })
    return scores, pd.DataFrame(checks)


def prototype_frames(events: pd.DataFrame, scores: pd.DataFrame, discovery_scores: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    thresholds = discovery_score_thresholds(discovery_scores)
    masks = oos_prototype_masks(scores, events, thresholds)
    frames = {
        name: events.loc[masks[name]].sort_values("execution_time").reset_index(drop=True)
        for name in LH1_PROTOTYPES
    }
    thresholds = thresholds.assign(threshold_source="original_discovery_score_distribution")
    return frames, thresholds


def build_gate_events(events: pd.DataFrame, scores: pd.DataFrame, discovery_scores: pd.DataFrame) -> pd.DataFrame:
    thresholds = discovery_score_thresholds(discovery_scores)
    masks = oos_prototype_masks(scores, events, thresholds)
    frames = []
    base_cols = [
        "event_id",
        "symbol",
        "signal_time",
        "execution_time",
        "execution_open",
        "atr14",
        "atr_pct",
        "range_atr",
        "volatility_ratio_short_long",
        "breakout_distance_atr",
        "body_ratio",
        "close_location",
    ]
    merged = events.merge(
        scores[["event_id", "momentum_score", "breakout_score", "momentum_score_quantile", "breakout_score_quantile"]],
        on="event_id",
        how="left",
    )
    for prototype in LH1_STRICT_PROTOTYPES:
        part = merged.loc[masks[prototype], [c for c in base_cols + ["momentum_score_quantile", "breakout_score_quantile"] if c in merged.columns]].copy()
        part["prototype"] = prototype
        frames.append(part)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out["atr_pct_rank"] = discovery_percentile(out["atr_pct"], events["atr_pct"])
        out["data_layer"] = "expanded_discovery"
        out["gate_threshold_source"] = "fixed_h3_discovery_thresholds"
    return out


def gate_assignments(gate_events: pd.DataFrame, gate_factors: pd.DataFrame, gate_thresholds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype in LH1_STRICT_PROTOTYPES:
        part = gate_events[gate_events["prototype"] == prototype].reset_index(drop=True)
        for gate in LH1_GATES:
            mask, status = gate_mask_fixed(part, gate_factors, gate_thresholds, prototype, gate)
            rows.extend({
                "data_layer": "expanded_discovery",
                "symbol": row["symbol"],
                "event_id": row["event_id"],
                "prototype": prototype,
                "gate": gate,
                "accepted": bool(mask.iloc[i]),
                "gate_status": status,
                "threshold_source": "fixed_h3_discovery_thresholds",
            } for i, row in part.iterrows())
    return pd.DataFrame(rows)


def event_summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for prototype, part in frames.items():
        for horizon in LH1_HORIZONS:
            rows.append({
                "prototype": prototype,
                "horizon": horizon,
                "event_count": int(len(part)),
                "mean_fwd_ret": float(part[f"fwd_ret_{horizon}"].mean()),
                "median_fwd_ret": float(part[f"fwd_ret_{horizon}"].median()),
                "mean_mfe": float(part[f"fwd_mfe_{horizon}"].mean()),
                "mean_mae": float(part[f"fwd_mae_{horizon}"].mean()),
                "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()),
                "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()),
                "ambiguous_rate": float(part[f"ambiguous_touch_{horizon}"].mean()),
                "sample_status": "valid" if len(part) >= 30 else "insufficient_sample",
            })
    return pd.DataFrame(rows)


def yearly_event_summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for prototype, frame in frames.items():
        data = frame.copy()
        data["year"] = pd.to_datetime(data["signal_time"], utc=True).dt.year
        for (year, part) in data.groupby("year"):
            for horizon in LH1_HORIZONS:
                rows.append({
                    "year": int(year),
                    "partial_year": bool(year == 2026),
                    "prototype": prototype,
                    "horizon": horizon,
                    "event_count": int(len(part)),
                    "mean_fwd_ret": float(part[f"fwd_ret_{horizon}"].mean()),
                    "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()),
                    "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()),
                    "sample_status": "partial_year" if year == 2026 else "valid" if len(part) >= 10 else "insufficient_sample",
                })
    return pd.DataFrame(rows)


def regime_event_summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for prototype, frame in frames.items():
        data = frame.copy()
        data["year"] = pd.to_datetime(data["signal_time"], utc=True).dt.year
        data["market_phase"] = data["year"].map({
            2020: "bull_recovery",
            2021: "bull_market",
            2022: "bear_market",
            2023: "range_recovery",
            2024: "recent_discovery",
            2025: "recent_discovery",
            2026: "partial_recent",
        }).fillna("unknown")
        for (phase, part) in data.groupby("market_phase"):
            for horizon in [16, 32]:
                rows.append({
                    "market_phase": phase,
                    "prototype": prototype,
                    "horizon": horizon,
                    "event_count": int(len(part)),
                    "mean_fwd_ret": float(part[f"fwd_ret_{horizon}"].mean()),
                    "plus_1atr_first_rate": float(part[f"plus_1atr_first_{horizon}"].mean()),
                    "minus_1atr_first_rate": float(part[f"minus_1atr_first_{horizon}"].mean()),
                    "sample_status": "valid" if len(part) >= 10 else "insufficient_sample",
                })
    return pd.DataFrame(rows)


def run_minimal_backtests(
    frames: dict[str, pd.DataFrame],
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    params: BacktestParams,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, list[pd.DataFrame]]:
    trades_dir = out_dir / "lh1_trades"
    equity_dir = out_dir / "lh1_equity_curves"
    trades_dir.mkdir(parents=True, exist_ok=True)
    equity_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    all_trades = []
    equity_frames = []
    start, end = data_1m.index.min(), data_1m.index.max()
    for prototype, frame in frames.items():
        enriched = enrich_events_with_exit_info(frame, data_1m, data_15m, params)
        for sizing_mode in SIZING_MODES:
            trades, equity = run_prototype_backtest(enriched, data_1m, data_15m, params, prototype, sizing_mode)
            summary_rows.append(summarize_backtest(prototype, sizing_mode, trades, equity, params.initial_balance, start, end))
            trades.to_csv(trades_dir / f"{prototype}_{sizing_mode}_trades.csv", index=False)
            equity.to_csv(equity_dir / f"{prototype}_{sizing_mode}_equity.csv", index=False)
            if not trades.empty:
                all_trades.append(trades)
            equity_frames.append(equity)
    return pd.DataFrame(summary_rows), pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(), equity_frames


def year_quarter_trade_summary(trades: pd.DataFrame, initial_balance: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame()
    data = trades.copy()
    exit_ts = pd.to_datetime(data["exit_time"], utc=True)
    data["year"] = exit_ts.dt.year
    data["quarter"] = exit_ts.dt.year.astype(str) + "Q" + exit_ts.dt.quarter.astype(str)
    year_rows = []
    quarter_rows = []
    for keys, part in data.groupby(["year", "prototype", "sizing_mode"]):
        year, prototype, sizing_mode = keys
        year_rows.append(_period_row(part, prototype, sizing_mode, int(year), "", initial_balance, year == 2026))
    for keys, part in data.groupby(["quarter", "prototype", "sizing_mode"]):
        quarter, prototype, sizing_mode = keys
        quarter_rows.append(_period_row(part, prototype, sizing_mode, "", quarter, initial_balance, str(quarter).startswith("2026")))
    return pd.DataFrame(year_rows), pd.DataFrame(quarter_rows)


def _period_row(part: pd.DataFrame, prototype: str, sizing_mode: str, year, quarter, initial_balance: float, partial: bool) -> dict:
    from research_core.minimal_backtest_analysis import max_drawdown, profit_factor, top_profit_contribution

    pnl = part["net_pnl"]
    eq = initial_balance + pnl.cumsum()
    count = len(part)
    status = "partial_year" if partial else "valid" if count >= 10 else "insufficient_sample"
    return {
        "year": year,
        "quarter": quarter,
        "prototype": prototype,
        "sizing_mode": sizing_mode,
        "trade_count": int(count),
        "return": float(pnl.sum() / initial_balance),
        "profit_factor": profit_factor(pnl),
        "max_drawdown": max_drawdown(eq),
        "win_rate": float((pnl > 0).mean()) if count else np.nan,
        "avg_trade": float(pnl.mean()) if count else np.nan,
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "sample_status": status,
    }


def run_strict_lh1(
    gate_events: pd.DataFrame,
    gate_factors: pd.DataFrame,
    gate_thresholds: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
    out_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades_dir = out_dir / "lh1_strict_trades"
    equity_dir = out_dir / "lh1_strict_equity_curves"
    trades_dir.mkdir(parents=True, exist_ok=True)
    equity_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    liquidations = []
    proxy_rows = []
    for prototype in LH1_STRICT_PROTOTYPES:
        proto = gate_events[gate_events["prototype"] == prototype].reset_index(drop=True)
        high_risk = high_risk_mask_fixed(proto, gate_factors, gate_thresholds, prototype)
        proto = proto.assign(gate_high_risk=high_risk)
        for gate in LH1_GATES:
            mask, status = gate_mask_fixed(proto, gate_factors, gate_thresholds, prototype, gate)
            accepted = proto if gate == "G4_RISK_MONITOR_DOWNSHIFT" else proto.loc[mask].copy()
            for mode in LH1_LEVERAGE_MODES:
                trades, equity, _ = strict_replay_events(accepted, data_1m, data_15m, "ETHUSDT", prototype, gate, mode)
                summary_rows.append({
                    "prototype": prototype,
                    "gate": gate,
                    "leverage_mode": mode,
                    "gate_status": status,
                    "candidate_event_count": int(len(proto)),
                    "accepted_event_count": int(len(accepted)),
                    **strict_summary(trades, equity),
                })
                trades.to_csv(trades_dir / f"ETHUSDT_{prototype}_{gate}_{mode}_trades.csv", index=False)
                equity.to_csv(equity_dir / f"ETHUSDT_{prototype}_{gate}_{mode}_equity.csv", index=False)
                if not trades.empty:
                    liq = trades[trades["liquidation"]].copy()
                    if not liq.empty:
                        liquidations.append(liq)
                proxy_rows.append({
                    "prototype": prototype,
                    "gate": gate,
                    "leverage_mode": mode,
                    "strict_trade_count": int(len(trades)),
                    "strict_liquidation_count": int(trades["liquidation"].sum()) if not trades.empty else 0,
                    "comparison_note": "strict_1m_replay_only_no_proxy_in_lh1",
                })
    return pd.DataFrame(summary_rows), pd.concat(liquidations, ignore_index=True) if liquidations else pd.DataFrame(), pd.DataFrame(proxy_rows)


def walk_forward_strict_lh1(
    gate_events: pd.DataFrame,
    gate_factors: pd.DataFrame,
    gate_thresholds: pd.DataFrame,
    data_1m: pd.DataFrame,
    data_15m: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    start = pd.to_datetime(gate_events["signal_time"], utc=True).min().normalize()
    end = pd.to_datetime(gate_events["signal_time"], utc=True).max()
    window_id = 0
    train_start = start
    while train_start + pd.DateOffset(months=30) <= end + pd.Timedelta(days=1):
        train_end = train_start + pd.DateOffset(months=24)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=6)
        test = gate_events[(gate_events["signal_time"] >= test_start) & (gate_events["signal_time"] < test_end)].copy()
        for prototype in LH1_STRICT_PROTOTYPES:
            proto = test[test["prototype"] == prototype].reset_index(drop=True)
            if proto.empty:
                iterable = [(gate, mode, pd.DataFrame(), "insufficient_sample") for gate in LH1_GATES for mode in ["adaptive_3x_8x_v1", "fixed_20x"]]
            else:
                high_risk = high_risk_mask_fixed(proto, gate_factors, gate_thresholds, prototype)
                proto = proto.assign(gate_high_risk=high_risk)
                iterable = []
                for gate in LH1_GATES:
                    mask, status = gate_mask_fixed(proto, gate_factors, gate_thresholds, prototype, gate)
                    accepted = proto if gate == "G4_RISK_MONITOR_DOWNSHIFT" else proto.loc[mask].copy()
                    for mode in ["adaptive_3x_8x_v1", "fixed_20x"]:
                        iterable.append((gate, mode, accepted, status))
            for gate, mode, accepted, status in iterable:
                trades, equity, _ = strict_replay_events(accepted, data_1m, data_15m, "ETHUSDT", prototype, gate, mode) if not accepted.empty else (pd.DataFrame(), pd.DataFrame([{"time": test_start, "equity": 1000.0}]), pd.DataFrame())
                summary = strict_summary(trades, equity)
                rows.append({
                    "window_id": window_id,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "prototype": prototype,
                    "gate": gate,
                    "leverage_mode": mode,
                    "trade_count": summary["trade_count"],
                    "total_return": summary["total_return"],
                    "profit_factor": summary["profit_factor"],
                    "max_drawdown": summary["max_drawdown"],
                    "liquidation_count": summary["liquidation_count"],
                    "sample_status": "valid" if summary["trade_count"] >= 5 and status != "gate_unavailable" else "insufficient_sample",
                })
        train_start = train_start + pd.DateOffset(months=6)
        window_id += 1
    windows = pd.DataFrame(rows)
    summary_rows = []
    for (prototype, gate, mode), part in windows.groupby(["prototype", "gate", "leverage_mode"]):
        valid = part[part["sample_status"] == "valid"]
        pos = float((valid["total_return"] > 0).mean()) if not valid.empty else np.nan
        pf = float((valid["profit_factor"] > 1).mean()) if not valid.empty else np.nan
        liq_free = float((valid["liquidation_count"] == 0).mean()) if not valid.empty else np.nan
        if valid.empty:
            status = "insufficient_sample"
        elif pos >= 0.6 and pf >= 0.6 and liq_free == 1.0:
            status = "wf_pass"
        elif pos >= 0.5 and liq_free >= 0.8:
            status = "wf_weak"
        else:
            status = "wf_fail"
        summary_rows.append({
            "prototype": prototype,
            "gate": gate,
            "leverage_mode": mode,
            "window_count": int(len(part)),
            "valid_window_count": int(len(valid)),
            "positive_window_rate": pos,
            "pf_gt_1_window_rate": pf,
            "liquidation_free_window_rate": liq_free,
            "median_return": float(valid["total_return"].median()) if not valid.empty else np.nan,
            "worst_return": float(valid["total_return"].min()) if not valid.empty else np.nan,
            "median_pf": float(valid["profit_factor"].replace(np.inf, np.nan).median()) if not valid.empty else np.nan,
            "walk_forward_status": status,
        })
    return windows, pd.DataFrame(summary_rows)


def plot_lh1_equity(equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(13, 7))
    for frame in equity_frames:
        if frame.empty or frame["sizing_mode"].iloc[0] != "fixed_2x":
            continue
        plt.plot(pd.to_datetime(frame["time"], utc=True), frame["equity"], label=frame["prototype"].iloc[0], linewidth=1.4)
    plt.title("LH1 ETH Long History Equity Comparison (fixed_2x)")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_lh1_drawdown(equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(13, 7))
    for frame in equity_frames:
        if frame.empty or frame["sizing_mode"].iloc[0] != "fixed_2x":
            continue
        equity = frame["equity"]
        dd = equity / equity.cummax() - 1
        plt.plot(pd.to_datetime(frame["time"], utc=True), dd, label=frame["prototype"].iloc[0], linewidth=1.4)
    plt.title("LH1 ETH Long History Drawdown Comparison (fixed_2x)")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()

