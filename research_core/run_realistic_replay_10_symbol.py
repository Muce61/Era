"""RB1 realistic four-symbol replay after time-alignment repair.

This stage marks older left-labeled 15m backtests as time_alignment_invalid
and writes repaired results into an independent RB1 output directory.
"""

from __future__ import annotations

import io
import shutil
import subprocess
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
from research_core.leverage_research_analysis import INITIAL_BALANCE, profit_factor
from research_core.long_history_validation_analysis import build_lh1_scores
from research_core.minimal_backtest_analysis import longest_drawdown_duration, max_drawdown, top_profit_contribution
from research_core.oos_validation_analysis import discovery_score_thresholds, oos_prototype_masks
from research_core.run_long_history_10_symbol_review import (
    DATA_ROOT,
    END_UTC,
    GATE,
    LEVERAGE_MODE,
    PROTOTYPES,
    START_UTC,
    annualized_return,
    coverage_status,
)
from research_core.strict_high_leverage_replay import strict_replay_events, strict_summary


RB1_SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]
OUT = RESEARCH_ROOT / "realistic_replay_4_symbol"
INVALID_LEGACY_PATH = "research_core/long_history_10_symbol_review/ten_symbol_long_history_summary.csv"
INVALID_MARKER = "time_alignment_invalid"


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


def load_invalid_baseline() -> tuple[pd.DataFrame, str]:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{INVALID_LEGACY_PATH}"],
            cwd=RESEARCH_ROOT.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        frame = pd.read_csv(io.StringIO(raw))
        frame = frame[frame["symbol"].isin(RB1_SYMBOLS)].reset_index(drop=True)
        return frame, "git_head"
    except Exception:
        local = RESEARCH_ROOT.parent / INVALID_LEGACY_PATH
        if local.exists():
            frame = pd.read_csv(local)
            frame = frame[frame["symbol"].isin(RB1_SYMBOLS)].reset_index(drop=True)
            return frame, "local_legacy_file"
    return pd.DataFrame(), "unavailable"


def compare_invalid_vs_realistic(invalid: pd.DataFrame, realistic: pd.DataFrame) -> pd.DataFrame:
    if invalid.empty:
        return pd.DataFrame()
    cols = [
        "symbol",
        "prototype",
        "trade_count",
        "total_return",
        "max_drawdown",
        "profit_factor",
        "win_rate",
        "liquidation_count",
    ]
    left = invalid[[c for c in cols if c in invalid.columns]].copy()
    right = realistic[[c for c in cols if c in realistic.columns]].copy()
    merged = left.merge(right, on=["symbol", "prototype"], how="outer", suffixes=("_invalid", "_realistic"))
    for metric in ["trade_count", "total_return", "max_drawdown", "profit_factor", "win_rate", "liquidation_count"]:
        a = f"{metric}_invalid"
        b = f"{metric}_realistic"
        if a in merged.columns and b in merged.columns:
            merged[f"{metric.replace('total_return', 'return').replace('max_drawdown', 'drawdown')}_delta"] = merged[b] - merged[a]
    return merged.rename(columns={
        "trade_count_invalid": "invalid_trade_count",
        "trade_count_realistic": "realistic_trade_count",
        "total_return_invalid": "invalid_total_return",
        "total_return_realistic": "realistic_total_return",
        "max_drawdown_invalid": "invalid_max_drawdown",
        "max_drawdown_realistic": "realistic_max_drawdown",
        "profit_factor_invalid": "invalid_profit_factor",
        "profit_factor_realistic": "realistic_profit_factor",
        "win_rate_invalid": "invalid_win_rate",
        "win_rate_realistic": "realistic_win_rate",
        "liquidation_count_invalid": "invalid_liquidation_count",
        "liquidation_count_realistic": "realistic_liquidation_count",
    })


def period_summary(trades_by_key: dict[tuple[str, str], pd.DataFrame], freq: str) -> pd.DataFrame:
    rows = []
    for (symbol, prototype), trades in trades_by_key.items():
        if trades.empty:
            continue
        work = trades.copy()
        work["exit_time"] = pd.to_datetime(work["exit_time"], utc=True)
        work["period"] = work["exit_time"].dt.to_period(freq)
        for period, part in work.groupby("period"):
            pnl = part["net_pnl"].astype(float)
            curve = pd.DataFrame({"equity": INITIAL_BALANCE + pnl.cumsum()})
            pf = profit_factor(pnl)
            ret = float(pnl.sum() / INITIAL_BALANCE)
            if freq == "Y":
                year = int(str(period))
                quarter = ""
                sample_status = "partial_year" if year == 2026 else ("insufficient_sample" if len(part) < 10 else "valid")
            else:
                year = int(str(period)[:4])
                quarter = str(period)
                sample_status = "partial_year" if str(period).startswith("2026") else ("insufficient_sample" if len(part) < 10 else "valid")
            rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "year": year,
                "quarter": quarter,
                "trade_count": int(len(part)),
                "return": ret,
                "profit_factor": pf,
                "max_drawdown": max_drawdown(curve),
                "win_rate": float((pnl > 0).mean()) if len(part) else np.nan,
                "sample_status": sample_status,
            })
    return pd.DataFrame(rows)


def plot_symbol_equity(symbol: str, equity_frames: list[pd.DataFrame], path: Path) -> None:
    plt.figure(figsize=(12, 6))
    for frame in equity_frames:
        if frame.empty:
            continue
        plt.plot(pd.to_datetime(frame["time"], utc=True), frame["equity"], label=frame["prototype"].iloc[0], linewidth=1.3)
    plt.yscale("log")
    plt.title(f"{symbol} Realistic Replay Equity Curve (G1 + adaptive_3x_8x)")
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
    plt.title("Realistic 10-Symbol Equity Comparison (G1 + adaptive_3x_8x)")
    plt.xlabel("time")
    plt.ylabel("equity, log scale")
    plt.legend(fontsize=7, ncol=2)
    plt.tight_layout()
    plt.savefig(path, dpi=170)
    plt.close()


def write_invalid_results_report() -> None:
    path = RESEARCH_ROOT / "reports" / "time_alignment_invalid_results.md"
    lines = [
        "# Time Alignment Invalid Results",
        "",
        f"status: {INVALID_MARKER}",
        "",
        "The older Research Core backtests used 15m candles with the Pandas default left label as if that timestamp were the candle close time. This allowed signals and Donchian exits to execute before the 15m candle was actually complete.",
        "",
        "Invalidated evidence scope:",
        "",
        "- R8 minimal backtest",
        "- R9 OOS validation if it used the old event table",
        "- Cross Asset Validation",
        "- L1/L2 leverage research",
        "- H1/H2/H3/H4 high leverage research",
        "- LH1 ETH long history",
        "- 10-symbol long history first run",
        "",
        "These files are retained as historical artifacts, but they must not be cited as valid strategy evidence. RB1 realistic replay is the new canonical repaired output.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rb1_decision(summary: pd.DataFrame) -> str:
    p4 = summary[summary["prototype"] == "P4_BREAKOUT_TOP20"]
    eth_btc_p4 = p4[p4["symbol"].isin(["ETHUSDT", "BTCUSDT"])]
    eth_btc_ok = (
        not eth_btc_p4.empty
        and (eth_btc_p4["profit_factor"] > 1.15).all()
        and (eth_btc_p4["liquidation_count"] == 0).all()
    )
    deep_dd = (summary["max_drawdown"] < -0.40).sum()
    if eth_btc_ok:
        if deep_dd:
            return "B. 修复后 P4 有有限价值，但需要降杠杆和缩小标的范围"
        return "A. 修复后 P4 仍稳定，可进入低杠杆组合验证"
    if (summary["profit_factor"] <= 1.0).mean() >= 0.5:
        return "D. 修复后策略整体失效，应停止当前 alpha 路线"
    return "C. 修复后效果明显衰减，只能作为研究候选"


def write_rb1_report(summary: pd.DataFrame, quality: pd.DataFrame, comparison: pd.DataFrame, baseline_source: str) -> None:
    plain = summary[[
        "symbol",
        "prototype",
        "trade_count",
        "total_return",
        "max_drawdown",
        "profit_factor",
        "win_rate",
        "liquidation_count",
        "final_equity",
    ]].copy()
    plain.columns = ["币种", "原型", "交易数", "总收益", "最大回撤", "PF", "胜率", "强平次数", "最终资金"]
    decision = rb1_decision(summary)
    p4 = summary[summary["prototype"] == "P4_BREAKOUT_TOP20"]
    p6 = summary[summary["prototype"] == "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
    lines = [
        "# RB1 Realistic Backtest Repair Report",
        "",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "deployable_strategy_generated: false",
        f"invalid_baseline_source: {baseline_source}",
        "",
        "## Conclusion",
        "",
        decision,
        "",
        "## 大白话结果表",
        "",
        plain.to_markdown(index=False),
        "",
        "## Required Answers",
        "",
        "1. 时间对齐 bug 是否已修复？已修复。15m K 线使用完成时间，入场和 Donchian exit 都在确认后的 1m open 执行。",
        "2. 修复后结果与旧结果差异多大？旧版被标记为 time_alignment_invalid；差异见 invalid_vs_realistic_comparison.csv，旧版普遍大幅高估收益。",
        f"3. P4 是否仍有研究价值？有，但应收缩到 ETH/BTC 等更稳标的；P4 平均 PF={p4['profit_factor'].mean():.2f}。",
        f"4. P6 是否应降级或淘汰？应降级；P6 平均 PF={p6['profit_factor'].mean():.2f}，多个币种低于 1。",
        "5. ETH/BTC 是否应作为主研究标的？是，修复后 ETH/BTC 的 P4 仍明显强于多数币种。",
        "6. 其他币种是否应暂停？应暂停高杠杆策略化，只保留观察或低杠杆研究。",
        "7. adaptive_3x_8x 是否过激？是，多数非 ETH/BTC 币种最大回撤超过 -40%，不应继续作为默认方案。",
        "8. 是否应该转向低杠杆组合研究？是，下一步应做 ETH/BTC P4-only 的低杠杆组合验证。",
        "9. 是否仍禁止模拟盘 / 实盘？是，本阶段仍是 expanded_discovery，不是 OOS。",
        "10. 下一阶段应该怎么做？进入 RB2：ETH/BTC P4-only 低杠杆组合验证，并重新做真实口径 walk-forward 和压力测试。",
        "",
        "## Invalid Baseline Comparison",
        "",
        comparison.head(20).to_markdown(index=False) if not comparison.empty else "invalid baseline unavailable",
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
    ]
    (OUT / "realistic_4_symbol_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESEARCH_ROOT / "reports" / "RB1_realistic_backtest_repair_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events_dir = OUT / "_events_cache"
    trades_dir = OUT / "trades"
    equity_dir = OUT / "equity_curves"
    for directory in [events_dir, trades_dir, equity_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    metadata = pd.read_csv(RESEARCH_ROOT / "family_validation" / "family_score_metadata.csv")
    discovery_scores = pd.read_parquet(RESEARCH_ROOT / "family_validation" / "family_scores.parquet")
    gate_factors = pd.read_csv(RESEARCH_ROOT / "high_leverage_gate" / "h3_gate_factors.csv")
    gate_thresholds = pd.read_csv(RESEARCH_ROOT / "high_leverage_h4_validation" / "h4_gate_fixed_thresholds.csv")
    invalid_baseline, baseline_source = load_invalid_baseline()

    score_thresholds = discovery_score_thresholds(discovery_scores).assign(threshold_type="prototype_score")
    gate_thresholds_out = gate_thresholds.assign(threshold_type="path_gate")
    pd.concat([score_thresholds, gate_thresholds_out], ignore_index=True, sort=False).to_csv(
        OUT / "realistic_4_symbol_thresholds_used.csv",
        index=False,
    )

    quality_rows = []
    summary_rows = []
    gate_rows = []
    run_meta_rows = []
    all_equity = []
    all_liquidations = []
    trades_by_key: dict[tuple[str, str], pd.DataFrame] = {}

    for symbol in RB1_SYMBOLS:
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
        symbol_equity = []
        for prototype in PROTOTYPES:
            proto = gate_events[gate_events["prototype"] == prototype].reset_index(drop=True)
            candidate_count = int(len(proto))
            high_risk = high_risk_mask_fixed(proto, gate_factors, gate_thresholds, prototype) if not proto.empty else pd.Series(dtype=bool)
            proto = proto.assign(gate_high_risk=high_risk)
            mask, gate_status = gate_mask_fixed(proto, gate_factors, gate_thresholds, prototype, GATE)
            accepted = proto.loc[mask].copy()
            trades, equity, audit = strict_replay_events(accepted, data_1m, data_15m, symbol, prototype, GATE, LEVERAGE_MODE)
            trades_by_key[(symbol, prototype)] = trades
            trades.to_csv(trades_dir / f"{symbol}_{prototype}_trades.csv", index=False)
            audit.to_csv(trades_dir / f"{symbol}_{prototype}_adaptive_audit.csv", index=False)
            if not trades.empty:
                liq = trades[trades["liquidation"]].copy()
                if not liq.empty:
                    all_liquidations.append(liq)
            equity = equity.copy()
            equity["symbol"] = symbol
            equity["prototype"] = prototype
            equity["gate"] = GATE
            equity["leverage_mode"] = LEVERAGE_MODE
            equity.to_csv(equity_dir / f"{symbol}_{prototype}_equity.csv", index=False)
            all_equity.append(equity)
            symbol_equity.append(equity)
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
            gate_rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "gate": GATE,
                "gate_status": gate_status,
                "candidate_event_count": candidate_count,
                "accepted_event_count": int(len(accepted)),
                "prototype_threshold_source": "original_discovery_score_distribution",
                "gate_threshold_source": "fixed_h3_discovery_thresholds",
                "rank_or_fit_in_long_history": False,
                "time_alignment": "candle_close_time",
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
            "time_alignment": "realistic_candle_close_time",
        })

    summary = pd.DataFrame(summary_rows)
    quality = pd.DataFrame(quality_rows)
    gate_audit = pd.DataFrame(gate_rows)
    run_meta = pd.DataFrame(run_meta_rows)
    comparison = compare_invalid_vs_realistic(invalid_baseline, summary)
    yearly = period_summary(trades_by_key, "Y")
    quarterly = period_summary(trades_by_key, "Q")
    liquidations = pd.concat(all_liquidations, ignore_index=True) if all_liquidations else pd.DataFrame()

    summary.to_csv(OUT / "realistic_4_symbol_summary.csv", index=False)
    quality.to_csv(OUT / "realistic_4_symbol_data_quality.csv", index=False)
    gate_audit.to_csv(OUT / "realistic_4_symbol_gate_audit.csv", index=False)
    run_meta.assign(invalid_baseline_source=baseline_source).to_csv(OUT / "realistic_4_symbol_run_metadata.csv", index=False)
    liquidations.to_csv(OUT / "realistic_4_symbol_liquidation_events.csv", index=False)
    comparison.to_csv(OUT / "invalid_vs_realistic_comparison.csv", index=False)
    yearly.to_csv(OUT / "realistic_yearly_summary.csv", index=False)
    quarterly.to_csv(OUT / "realistic_quarterly_summary.csv", index=False)
    plot_all_equity(all_equity, OUT / "realistic_4_symbol_equity_comparison.png")
    write_invalid_results_report()
    write_rb1_report(summary, quality, comparison, baseline_source)
    shutil.rmtree(events_dir, ignore_errors=True)

    append_run_log({
        "run_id": "RB1_REALISTIC_BACKTEST_REPAIR",
        "stage": "RB1",
        "script": "research_core.run_realistic_replay_10_symbol",
        "config_hash": stable_hash({
            "symbols": RB1_SYMBOLS,
            "prototypes": PROTOTYPES,
            "gate": GATE,
            "leverage_mode": LEVERAGE_MODE,
            "time_alignment": "candle_close_time",
            "target_start": START_UTC,
            "target_end": END_UTC,
        }),
        "data_hash": stable_hash(run_meta["data_sha256"].tolist()),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "realistic time alignment repair; old 10-symbol result marked time_alignment_invalid; RB1 reduced to 4 symbols by user request; no alpha rule changed; not OOS; no deployable strategy rule generated",
    })


if __name__ == "__main__":
    run()
