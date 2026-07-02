"""10-symbol long-history strict replay review.

Large 1m CSV files are read from ``/Users/muce/1m_data`` and are not copied
into the repository. This stage is expanded discovery/internal validation, not
OOS, and reuses fixed discovery prototype and H3 gate thresholds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research_core.build_long_history_data import audit_data
from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.event_table import add_base_indicators, build_event_candidates, load_ohlcv_1m, strict_resample_15m
from research_core.high_leverage_gate_analysis import gate_mask_fixed, high_risk_mask_fixed
from research_core.high_leverage_h4_validation_analysis import discovery_percentile
from research_core.leverage_research_analysis import INITIAL_BALANCE
from research_core.long_history_validation_analysis import build_lh1_scores
from research_core.minimal_backtest_analysis import longest_drawdown_duration
from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks
from research_core.strict_high_leverage_replay import strict_replay_events, strict_summary


SYMBOLS = [
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
]
PROTOTYPES = ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
GATE = "G1_SINGLE_BEST_PATH_SAFETY"
LEVERAGE_MODE = "adaptive_3x_8x_v1"
START_UTC = pd.Timestamp("2020-01-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
DATA_ROOT = Path("/Users/muce/1m_data/long_history_1m/merged")
OUT = RESEARCH_ROOT / "long_history_10_symbol_review"


def coverage_status(start: pd.Timestamp, end: pd.Timestamp) -> str:
    if start > START_UTC:
        return "late_listing_partial_coverage"
    if end < END_UTC:
        return "incomplete_end_coverage"
    return "full_coverage"


def annualized_return(final_equity: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).total_seconds() / (365.25 * 86400), 1e-9)
    if final_equity <= 0:
        return -1.0
    return float((final_equity / INITIAL_BALANCE) ** (1 / years) - 1)


def build_symbol_events(symbol: str, data_1m: pd.DataFrame, event_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_15m = add_base_indicators(strict_resample_15m(data_1m))
    if event_path.exists():
        events = pd.read_parquet(event_path)
    else:
        events, data_15m = build_event_candidates(data_1m, symbol=symbol)
        events.to_parquet(event_path, index=False)
    if not events.empty:
        events["signal_time"] = pd.to_datetime(events["signal_time"], utc=True)
        events["execution_time"] = pd.to_datetime(events["execution_time"], utc=True)
    return events.reset_index(drop=True), data_15m


def build_gate_events(symbol: str, events: pd.DataFrame, scores: pd.DataFrame, discovery_scores: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    thresholds = discovery_score_thresholds(discovery_scores)
    masks = oos_prototype_masks(scores, events, thresholds)
    merged = events.merge(
        scores[["event_id", "momentum_score", "breakout_score", "momentum_score_quantile", "breakout_score_quantile"]],
        on="event_id",
        how="left",
    )
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
        "momentum_score_quantile",
        "breakout_score_quantile",
    ]
    frames = []
    for prototype in PROTOTYPES:
        cols = [c for c in base_cols if c in merged.columns]
        part = merged.loc[masks[prototype], cols].copy()
        part["symbol"] = symbol
        part["prototype"] = prototype
        frames.append(part)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out["atr_pct_rank"] = discovery_percentile(out["atr_pct"], events["atr_pct"])
        out["data_layer"] = "expanded_discovery"
        out["gate_threshold_source"] = "fixed_h3_discovery_thresholds"
    return out


def plot_symbol_equity(symbol: str, equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for frame in equity_frames:
        if frame.empty:
            continue
        label = frame["prototype"].iloc[0]
        plt.plot(pd.to_datetime(frame["time"], utc=True), frame["equity"], label=label, linewidth=1.3)
    plt.yscale("log")
    plt.title(f"{symbol} Long History Equity Curve (G1 + adaptive_3x_8x)")
    plt.xlabel("time")
    plt.ylabel("equity, log scale")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_all_equity(equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(14, 8))
    for frame in equity_frames:
        if frame.empty:
            continue
        label = f"{frame['symbol'].iloc[0]} {frame['prototype'].iloc[0].split('_')[0]}"
        plt.plot(pd.to_datetime(frame["time"], utc=True), frame["equity"], label=label, linewidth=0.9)
    plt.yscale("log")
    plt.title("10-Symbol Long History Equity Comparison (G1 + adaptive_3x_8x)")
    plt.xlabel("time")
    plt.ylabel("equity, log scale")
    plt.legend(fontsize=7, ncol=2)
    plt.tight_layout()
    plt.savefig(path, dpi=170)
    plt.close()


def data_quality_row(symbol: str, data: pd.DataFrame, path: Path) -> dict:
    quality, _, _, _ = audit_data(symbol, data.reset_index().rename(columns={"index": "timestamp"}))
    start = pd.Timestamp(quality["start_utc"])
    end = pd.Timestamp(quality["end_utc"])
    quality.update({
        "data_start_utc": start.isoformat(),
        "data_end_utc": end.isoformat(),
        "coverage_status": coverage_status(start, end),
        "path": str(path),
        "sha256": file_sha256(path),
        "data_layer": "expanded_discovery",
        "oos_eligible": False,
    })
    return quality


def summary_row(
    symbol: str,
    prototype: str,
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    cov_status: str,
    candidate_count: int,
    accepted_count: int,
    trades: pd.DataFrame,
    equity: pd.DataFrame,
) -> dict:
    summary = strict_summary(trades, equity)
    summary["annualized_return"] = annualized_return(summary["final_equity"], data_start, data_end)
    summary["top10_profit_contribution"] = np.nan
    if not trades.empty:
        from research_core.minimal_backtest_analysis import top_profit_contribution

        summary["top10_profit_contribution"] = top_profit_contribution(trades["net_pnl"], 10)
        summary["longest_drawdown_duration"] = longest_drawdown_duration(equity)
    return {
        "symbol": symbol,
        "prototype": prototype,
        "data_start_utc": data_start.isoformat(),
        "data_end_utc": data_end.isoformat(),
        "coverage_status": cov_status,
        "candidate_event_count": candidate_count,
        "accepted_event_count": accepted_count,
        **summary,
    }


def write_report(summary: pd.DataFrame, quality: pd.DataFrame) -> None:
    plain = summary[[
        "symbol",
        "prototype",
        "data_start_utc",
        "data_end_utc",
        "trade_count",
        "total_return",
        "max_drawdown",
        "profit_factor",
        "win_rate",
        "liquidation_count",
        "final_equity",
    ]].copy()
    plain = plain.rename(columns={
        "symbol": "币种",
        "prototype": "原型",
        "data_start_utc": "数据起点",
        "data_end_utc": "数据终点",
        "trade_count": "交易数",
        "total_return": "总收益",
        "max_drawdown": "最大回撤",
        "profit_factor": "PF",
        "win_rate": "胜率",
        "liquidation_count": "强平次数",
        "final_equity": "最终资金",
    })
    lines = [
        "# 10-Symbol Long History Review",
        "",
        "data_layer: expanded_discovery / cross_asset_internal_validation",
        "oos_status: not_oos",
        "deployable_strategy_generated: false",
        f"target_range: {START_UTC.isoformat()} to {END_UTC.isoformat()}",
        "",
        "Rules are frozen: P4/P6 + G1_SINGLE_BEST_PATH_SAFETY + adaptive_3x_8x_v1, strict 1m replay, fixed discovery score thresholds, fixed H3/H4 gate thresholds.",
        "",
        "## 大白话效果表",
        "",
        plain.to_markdown(index=False),
        "",
        "## Data Quality",
        "",
        quality[[
            "symbol",
            "data_start_utc",
            "data_end_utc",
            "coverage_status",
            "row_count",
            "missing_minute_count",
            "duplicate_timestamp_count",
            "invalid_ohlc_count",
            "outlier_count",
        ]].to_markdown(index=False),
        "",
        "## Guardrails",
        "",
        "- large 1m CSV files are outside Git",
        "- no alpha rule changed",
        "- fixed discovery thresholds",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    (OUT / "ten_symbol_long_history_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events_dir = OUT / "events"
    trades_dir = OUT / "trades"
    equity_dir = OUT / "equity_curves"
    for directory in [events_dir, trades_dir, equity_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    gate_thresholds = pd.read_csv(RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_gate_fixed_thresholds.csv")

    quality_rows = []
    summary_rows = []
    threshold_rows = []
    all_equity = []
    all_liquidations = []
    run_meta_rows = []
    score_thresholds = discovery_score_thresholds(discovery_scores).assign(threshold_type="prototype_score")
    gate_thresholds_out = gate_thresholds.assign(threshold_type="path_gate")
    pd.concat([score_thresholds, gate_thresholds_out], ignore_index=True, sort=False).to_csv(
        OUT / "ten_symbol_long_history_thresholds_used.csv",
        index=False,
    )

    for symbol in SYMBOLS:
        data_path = DATA_ROOT / f"{symbol}.csv"
        if not data_path.exists():
            raise FileNotFoundError(f"Missing long history CSV for {symbol}: {data_path}")
        data_1m = load_ohlcv_1m(data_path)
        data_1m = data_1m[(data_1m.index >= START_UTC) & (data_1m.index <= END_UTC)].copy()
        if data_1m.empty:
            raise ValueError(f"No data in target range for {symbol}")
        data_start = data_1m.index.min()
        data_end = data_1m.index.max()
        cov_status = coverage_status(data_start, data_end)
        quality_rows.append(data_quality_row(symbol, data_1m, data_path))
        events, data_15m = build_symbol_events(symbol, data_1m, events_dir / f"{symbol}_events.parquet")
        scores, score_check = build_lh1_scores(events, metadata, discovery_scores)
        scores.to_parquet(events_dir / f"{symbol}_scores.parquet", index=False)
        score_check.assign(symbol=symbol).to_csv(events_dir / f"{symbol}_score_distribution_check.csv", index=False)
        gate_events = build_gate_events(symbol, events, scores, discovery_scores)
        gate_events.to_parquet(events_dir / f"{symbol}_gate_events.parquet", index=False)
        symbol_equity = []
        for prototype in PROTOTYPES:
            proto = gate_events[gate_events["prototype"] == prototype].reset_index(drop=True)
            candidate_count = int(len(proto))
            high_risk = high_risk_mask_fixed(proto, gate_factors, gate_thresholds, prototype) if not proto.empty else pd.Series(dtype=bool)
            proto = proto.assign(gate_high_risk=high_risk)
            mask, gate_status = gate_mask_fixed(proto, gate_factors, gate_thresholds, prototype, GATE)
            accepted = proto.loc[mask].copy()
            trades, equity, audit = strict_replay_events(accepted, data_1m, data_15m, symbol, prototype, GATE, LEVERAGE_MODE)
            if not trades.empty:
                trades.to_csv(trades_dir / f"{symbol}_{prototype}_trades.csv", index=False)
                liq = trades[trades["liquidation"]].copy()
                if not liq.empty:
                    all_liquidations.append(liq)
            else:
                pd.DataFrame().to_csv(trades_dir / f"{symbol}_{prototype}_trades.csv", index=False)
            equity = equity.copy()
            equity["symbol"] = symbol
            equity["prototype"] = prototype
            equity["gate"] = GATE
            equity["leverage_mode"] = LEVERAGE_MODE
            equity.to_csv(equity_dir / f"{symbol}_{prototype}_equity.csv", index=False)
            all_equity.append(equity)
            symbol_equity.append(equity)
            audit.to_csv(trades_dir / f"{symbol}_{prototype}_adaptive_audit.csv", index=False)
            summary_rows.append(summary_row(
                symbol,
                prototype,
                data_start,
                data_end,
                cov_status,
                candidate_count,
                int(len(accepted)),
                trades,
                equity,
            ))
            threshold_rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "gate": GATE,
                "gate_status": gate_status,
                "candidate_event_count": candidate_count,
                "accepted_event_count": int(len(accepted)),
                "prototype_threshold_source": "original_discovery_score_distribution",
                "gate_threshold_source": "fixed_h3_discovery_thresholds",
                "rank_or_fit_in_long_history": False,
            })
        plot_symbol_equity(symbol, symbol_equity, OUT / f"{symbol}_equity_curve.png")
        run_meta_rows.append({
            "symbol": symbol,
            "data_path": str(data_path),
            "data_sha256": file_sha256(data_path),
            "data_start_utc": data_start.isoformat(),
            "data_end_utc": data_end.isoformat(),
            "data_layer": "expanded_discovery",
            "oos_eligible": False,
        })

    summary = pd.DataFrame(summary_rows)
    quality = pd.DataFrame(quality_rows)
    thresholds = pd.DataFrame(threshold_rows)
    run_meta = pd.DataFrame(run_meta_rows)
    summary.to_csv(OUT / "ten_symbol_long_history_summary.csv", index=False)
    quality.to_csv(OUT / "ten_symbol_long_history_data_quality.csv", index=False)
    thresholds.to_csv(OUT / "ten_symbol_long_history_gate_audit.csv", index=False)
    run_meta.to_csv(OUT / "ten_symbol_long_history_run_metadata.csv", index=False)
    liquidations = pd.concat(all_liquidations, ignore_index=True) if all_liquidations else pd.DataFrame()
    liquidations.to_csv(OUT / "ten_symbol_long_history_liquidation_events.csv", index=False)
    plot_all_equity(all_equity, OUT / "ten_symbol_equity_comparison.png")
    write_report(summary, quality)

    run_ts = datetime.now(timezone.utc).isoformat()
    append_run_log({
        "run_id": "LH10_SYMBOL_LONG_HISTORY_REVIEW",
        "stage": "LH10",
        "script": "research_core.run_long_history_10_symbol_review",
        "config_hash": stable_hash({
            "symbols": SYMBOLS,
            "prototypes": PROTOTYPES,
            "gate": GATE,
            "leverage_mode": LEVERAGE_MODE,
            "fixed_thresholds": True,
            "target_start": START_UTC,
            "target_end": END_UTC,
        }),
        "data_hash": stable_hash(run_meta["data_sha256"].tolist()),
        "git_commit": current_git_commit(),
        "run_timestamp": run_ts,
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "10-symbol long history strict replay; no alpha rule changed; fixed discovery thresholds; not OOS; no deployable strategy rule generated",
    })


if __name__ == "__main__":
    run()
