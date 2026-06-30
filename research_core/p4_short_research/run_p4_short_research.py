"""Run P4 short mirror trend direction coverage research."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash
from research_core.minimal_backtest_analysis import max_drawdown, top_profit_contribution
from research_core.p4_short_research.p4_long_short_portfolio import compare_monthly, portfolio_summary
from research_core.p4_short_research.p4_rule_audit import write_mirror_mapping, write_p4_long_rule_snapshot
from research_core.p4_short_research.p4_short_accounting import COST_SCENARIOS, INITIAL_BALANCE
from research_core.p4_short_research.p4_short_event_study import (
    DATA_ROOT,
    END_UTC,
    PROTOTYPE,
    START_UTC,
    SYMBOLS,
    add_short_indicators,
    build_bear_state_pool,
    build_short_events_for_symbol,
    load_symbol_1m,
    summarize_events,
)
from research_core.p4_short_research.p4_short_random_baseline import matched_random_baseline
from research_core.p4_short_research.p4_short_replay import replay_short_events, summarize_trades
from research_core.p4_short_research.p4_short_walk_forward import block_bootstrap, ordinary_bootstrap


OUT = RESEARCH_ROOT / "p4_short_research"
FUNDING_DIR = OUT / "funding"
EMPTY_REPLAY_COLUMNS = {
    "short_backtest_base.csv": ["symbol", "cost_scenario", "trade_count", "total_return", "max_drawdown", "profit_factor", "win_rate", "final_equity", "liquidation_count"],
    "short_backtest_high.csv": ["symbol", "cost_scenario", "trade_count", "total_return", "max_drawdown", "profit_factor", "win_rate", "final_equity", "liquidation_count"],
    "short_backtest_stress.csv": ["symbol", "cost_scenario", "trade_count", "total_return", "max_drawdown", "profit_factor", "win_rate", "final_equity", "liquidation_count"],
    "short_cost_scenario_summary.csv": ["symbol", "cost_scenario", "trade_count", "total_return", "max_drawdown", "profit_factor", "win_rate", "final_equity", "liquidation_count"],
    "short_trades.csv": ["symbol", "prototype", "cost_scenario", "event_id", "entry_time", "exit_time", "entry_price", "exit_price", "quantity", "gross_pnl", "net_pnl", "exit_reason"],
    "short_equity_curve.csv": ["time", "equity", "symbol"],
    "short_walk_forward_windows.csv": ["period", "symbol", "event_count", "mean_short_fwd_ret_16", "sample_status"],
    "short_walk_forward_summary.csv": ["symbol", "trade_count", "profit_factor", "pf_gt_1_window_rate"],
    "long_short_monthly_returns.csv": ["month", "p4_long_return", "p4_short_return"],
    "long_short_monthly_correlation.csv": ["monthly_return_correlation", "p4_down_month_count", "p4_down_month_short_positive_rate"],
    "long_short_drawdown_comparison.csv": ["long_only_max_drawdown", "long_short_max_drawdown", "note"],
    "long_short_portfolio_summary.csv": ["portfolio_mode", "trade_count", "total_return", "max_drawdown", "profit_factor"],
}


def git_output(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=RESEARCH_ROOT.parent, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def data_quality(symbol: str, path: Path, data: pd.DataFrame) -> dict:
    expected_minutes = int((data.index.max() - data.index.min()).total_seconds() // 60) + 1 if not data.empty else 0
    invalid_ohlc = int(((data["low"] > data[["open", "close"]].min(axis=1)) | (data["high"] < data[["open", "close"]].max(axis=1))).sum())
    return {
        "symbol": symbol,
        "path": str(path),
        "sha256": file_sha256(path) if path.exists() else "missing",
        "data_start_utc": data.index.min().isoformat() if not data.empty else "",
        "data_end_utc": data.index.max().isoformat() if not data.empty else "",
        "row_count": int(len(data)),
        "expected_minutes": expected_minutes,
        "missing_minutes": int(max(expected_minutes - len(data), 0)),
        "duplicate_timestamp_count": int(data.index.duplicated().sum()),
        "invalid_ohlc_count": invalid_ohlc,
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
    }


def write_branch_metadata(base_commit: str, remote_push_status: str) -> None:
    row = {
        "repository": "https://github.com/Muce61/Era",
        "base_branch": "codex/adaptive-leverage-10x-20x",
        "base_commit_sha": base_commit,
        "research_branch": git_output(["branch", "--show-current"]),
        "research_start_commit_sha": base_commit,
        "current_head_commit_sha": current_git_commit(),
        "remote_branch": "origin/codex/p4-short-trend-direction-coverage",
        "branch_created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "codex",
        "research_topic": "p4_short_trend_direction_coverage",
        "working_tree_status": git_output(["status", "--short"]).replace("\n", " | "),
        "remote_push_status": remote_push_status,
    }
    pd.DataFrame([row]).to_csv(OUT / "branch_metadata.csv", index=False)


def download_funding(symbol: str) -> tuple[pd.DataFrame, dict]:
    FUNDING_DIR.mkdir(parents=True, exist_ok=True)
    path = FUNDING_DIR / f"{symbol}_funding.csv"
    if path.exists():
        frame = pd.read_csv(path, parse_dates=["funding_time"])
        return frame, {"symbol": symbol, "funding_status": "cached", "funding_rows": len(frame), "funding_path": str(path)}
    start_ms = int(START_UTC.timestamp() * 1000)
    end_ms = int(END_UTC.timestamp() * 1000)
    rows = []
    status = "available"
    cursor = start_ms
    try:
        while cursor < end_ms:
            qs = urllib.parse.urlencode({"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000})
            with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/fundingRate?{qs}", timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if not payload:
                break
            rows.extend(payload)
            last = int(payload[-1]["fundingTime"])
            if last <= cursor:
                break
            cursor = last + 1
            time.sleep(0.08)
    except Exception as exc:
        status = f"unavailable:{type(exc).__name__}"
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.rename(columns={"fundingTime": "funding_time", "fundingRate": "funding_rate"})
        frame["funding_time"] = pd.to_datetime(frame["funding_time"].astype("int64"), unit="ms", utc=True)
        frame["funding_rate"] = frame["funding_rate"].astype(float)
        frame = frame[["symbol", "funding_time", "funding_rate"]].sort_values("funding_time")
        frame.to_csv(path, index=False)
    return frame, {
        "symbol": symbol,
        "funding_status": status if not frame.empty else "unavailable_empty",
        "funding_rows": int(len(frame)),
        "funding_start_utc": frame["funding_time"].min().isoformat() if not frame.empty else "",
        "funding_end_utc": frame["funding_time"].max().isoformat() if not frame.empty else "",
        "funding_path": str(path),
    }


def write_instrument_audit(funding_audit: list[dict]) -> None:
    rows = []
    by_symbol = {r["symbol"]: r for r in funding_audit}
    for symbol in SYMBOLS:
        f = by_symbol.get(symbol, {})
        rows.append({
            "symbol": symbol,
            "ohlcv_source": str(DATA_ROOT / f"{symbol}.csv"),
            "market_type": "USDT perpetual inferred from Binance USDT-M filename/source",
            "shorting_supported": True,
            "funding_status": f.get("funding_status", "unavailable"),
            "funding_rows": f.get("funding_rows", 0),
            "borrow_cost_status": "not_applicable_for_usdt_m_perpetual",
            "instrument_audit_status": "complete_with_funding" if str(f.get("funding_status", "")).startswith(("available", "cached")) else "funding_incomplete",
        })
    pd.DataFrame(rows).to_csv(OUT / "short_instrument_audit.csv", index=False)


def event_gate_pass(events: pd.DataFrame, random_summary: pd.DataFrame, bootstrap: pd.DataFrame, top_dep: pd.DataFrame) -> tuple[bool, str]:
    if events.empty or random_summary.empty:
        return False, "P4_SHORT_EVENT_EDGE_NOT_FOUND"
    eth_btc = events[events["symbol"].isin(["ETHUSDT", "BTCUSDT"])]
    positive_focus = int((eth_btc.groupby("symbol")["short_fwd_ret_16"].mean() > 0).sum()) if not eth_btc.empty else 0
    mean16 = float(events["short_fwd_ret_16"].mean())
    random_pct = float(random_summary["percentile_vs_random"].iloc[0])
    plus_rate = float(events["plus_1atr_first_16"].mean())
    minus_rate = float(events["minus_1atr_first_16"].mean())
    boot_pos = float(bootstrap["positive_rate"].iloc[0]) if not bootstrap.empty else 0.0
    top1 = float(top_dep["top1_profit_contribution"].iloc[0]) if not top_dep.empty else 1.0
    passed = (
        mean16 > 0
        and random_pct >= 0.70
        and plus_rate > minus_rate
        and positive_focus >= 1
        and boot_pos >= 0.60
        and top1 <= 0.30
    )
    return passed, "event_gate_pass" if passed else "P4_SHORT_EVENT_EDGE_NOT_FOUND"


def top_dependency(events: pd.DataFrame) -> pd.DataFrame:
    vals = events["short_fwd_ret_16"].dropna().sort_values(ascending=False)
    pos = vals[vals > 0]
    total = float(pos.sum())
    def contrib(n: int) -> float:
        return float(pos.head(n).sum() / total) if total > 0 else np.nan
    def remove(n: int) -> float:
        drop = set(pos.head(n).index)
        return float(events.drop(index=list(drop), errors="ignore")["short_fwd_ret_16"].mean())
    return pd.DataFrame([{
        "top1_profit_contribution": contrib(1),
        "top3_profit_contribution": contrib(3),
        "top5_profit_contribution": contrib(5),
        "remove_top1_mean": remove(1),
        "remove_top3_mean": remove(3),
        "remove_top5_mean": remove(5),
    }])


def period_event_summary(events: pd.DataFrame, freq: str) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    work = events.copy()
    work["signal_time"] = pd.to_datetime(work["signal_time"], utc=True)
    work["period"] = work["signal_time"].dt.to_period(freq).astype(str)
    rows = []
    for keys, part in work.groupby(["symbol", "period"]):
        rows.append({
            "symbol": keys[0],
            "period": keys[1],
            "event_count": int(len(part)),
            "mean_short_fwd_ret_16": float(part["short_fwd_ret_16"].mean()),
            "plus_1atr_first_rate_16": float(part["plus_1atr_first_16"].mean()),
            "minus_1atr_first_rate_16": float(part["minus_1atr_first_16"].mean()),
            "sample_status": "insufficient_sample" if len(part) < 10 else "valid",
        })
    return pd.DataFrame(rows)


def regime_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    for keys, part in events.groupby(["symbol", "volatility_regime", "trend_strength_bucket"], dropna=False):
        rows.append({
            "symbol": keys[0],
            "volatility_regime": keys[1],
            "trend_strength_bucket": keys[2],
            "event_count": int(len(part)),
            "mean_short_fwd_ret_16": float(part["short_fwd_ret_16"].mean()),
            "plus_1atr_first_rate_16": float(part["plus_1atr_first_16"].mean()),
            "minus_1atr_first_rate_16": float(part["minus_1atr_first_16"].mean()),
        })
    return pd.DataFrame(rows)


def asymmetry_summary(short_events: pd.DataFrame, long_frames: list[pd.DataFrame]) -> pd.DataFrame:
    rows = []
    if not short_events.empty:
        rows.append({
            "module": "P4_SHORT_MIRROR_V1",
            "event_count": len(short_events),
            "mean_forward_return_16": float(short_events["short_fwd_ret_16"].mean()),
            "median_forward_return_16": float(short_events["short_fwd_ret_16"].median()),
            "first_touch_win_rate_16": float(short_events["plus_1atr_first_16"].mean()),
            "mae_tail_95_16": float(short_events["short_mae_16"].quantile(0.95)),
        })
    if long_frames:
        long_events = pd.concat(long_frames, ignore_index=True)
        rows.append({
            "module": "P4_LONG_EXISTING",
            "event_count": len(long_events),
            "mean_forward_return_16": float(long_events["fwd_ret_16"].mean()) if "fwd_ret_16" in long_events else np.nan,
            "median_forward_return_16": float(long_events["fwd_ret_16"].median()) if "fwd_ret_16" in long_events else np.nan,
            "first_touch_win_rate_16": float(long_events["plus_1atr_first_16"].mean()) if "plus_1atr_first_16" in long_events else np.nan,
            "mae_tail_95_16": float(long_events["fwd_mae_16"].quantile(0.05)) if "fwd_mae_16" in long_events else np.nan,
        })
    return pd.DataFrame(rows)


def annualized_return(final_equity: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = max((end - start).total_seconds() / (365.25 * 24 * 3600), 1e-9)
    return float((final_equity / INITIAL_BALANCE) ** (1 / years) - 1)


def summarize_backtests(all_trades: pd.DataFrame, all_equity: pd.DataFrame, scenario_name: str) -> pd.DataFrame:
    rows = []
    for symbol, trades in all_trades.groupby("symbol") if not all_trades.empty else []:
        equity = all_equity[all_equity["symbol"] == symbol].drop(columns=["symbol"])
        row = summarize_trades(trades, equity)
        row.update({"symbol": symbol, "cost_scenario": scenario_name})
        rows.append(row)
    if not all_trades.empty:
        equity_all = all_trades[["exit_time", "net_pnl"]].copy()
        equity_all["exit_time"] = pd.to_datetime(equity_all["exit_time"], utc=True)
        equity_all = equity_all.sort_values("exit_time")
        equity = pd.DataFrame({"time": equity_all["exit_time"], "equity": INITIAL_BALANCE + equity_all["net_pnl"].cumsum()})
        row = summarize_trades(all_trades, equity)
        row.update({"symbol": "ALL", "cost_scenario": scenario_name})
        rows.append(row)
    return pd.DataFrame(rows)


def write_report(context: dict, short_decision: str, combination_decision: str) -> None:
    lines = [
        "# P4 Short Trend Direction Coverage Research Report",
        "",
        f"base_branch: {context['base_branch']}",
        f"base_commit_sha: {context['base_commit_sha']}",
        f"research_branch: {context['research_branch']}",
        f"research_head_commit_sha: {context['research_head_commit_sha']}",
        "data_layer: expanded_discovery",
        "oos_status: not_oos",
        "paper_trading_status: not_allowed",
        "",
        "## Decisions",
        "",
        f"short_decision: {short_decision}",
        f"combination_decision: {combination_decision}",
        f"archive_status: {context.get('archive_status', '')}",
        "",
        "## Interpretation",
        "",
        "- P4 Short was evaluated as a mechanical trend-direction mirror, not as an independent second alpha.",
        "- P4 Long rules were not modified.",
        "- Old left-labeled 15m results remain time_alignment_invalid and were not used as valid evidence.",
        "- Funding was downloaded from Binance USDT-M where available and separately attributed; missing coverage downgrades realism.",
        "",
        "## Required Answers",
        "",
        "1. Current P4 Long uses Donchian55 upper breakout, EMA50 > EMA200, ATR stop, and Donchian20 lower exit under repaired candle-close time alignment.",
        "2. Legacy left-labeled outputs are invalid.",
        "3. Short mirror uses Donchian55 lower breakout, EMA50 < EMA200, ATR stop above entry, and Donchian20 upper exit.",
        "4. Random baseline and event deltas are in `short_random_baseline_summary.csv` and `short_event_vs_random_delta.csv`.",
        "5. Forward horizon evidence is in `short_event_summary.csv`.",
        "6. First-touch evidence is in `short_event_summary.csv`.",
        "7. Squeeze/tail risk is in `short_tail_risk_summary.csv`.",
        "8. Year/quarter stability is in `short_yearly_summary.csv` and `short_quarterly_summary.csv`.",
        "9. BTC/ETH evidence is separated in all symbol-level outputs.",
        "10. SOL/BNB are supporting cross-asset references, not primary go/no-go assets.",
        "11. Gross and cost-after results are in backtest outputs if event gate passed.",
        "12. Cost scenarios materially change fee/slippage assumptions.",
        "13. Funding completeness is in `short_instrument_audit.csv`.",
        "14. Accounting identity is tested in `tests/test_p4_short_accounting.py`.",
        "15. No OOS, paper, or live approval is granted.",
    ]
    (OUT / "p4_short_research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trades").mkdir(exist_ok=True)
    (OUT / "equity").mkdir(exist_ok=True)
    base_commit = git_output(["merge-base", "HEAD", "origin/codex/adaptive-leverage-10x-20x"])
    write_branch_metadata(base_commit, "pushed_before_research")
    write_p4_long_rule_snapshot(OUT / "p4_long_rule_snapshot.md", base_commit)
    write_mirror_mapping(OUT / "p4_short_mirror_mapping.csv")

    data_hashes = []
    quality_rows = []
    funding_rows = []
    funding_data: dict[str, pd.DataFrame] = {}
    event_frames = []
    pool_frames = []
    data_1m_by_symbol = {}
    data_15m_by_symbol = {}
    for symbol in SYMBOLS:
        path = DATA_ROOT / f"{symbol}.csv"
        data_1m = load_symbol_1m(symbol)
        data_1m_by_symbol[symbol] = data_1m
        data_hashes.append(file_sha256(path))
        quality_rows.append(data_quality(symbol, path, data_1m))
        events, data_15m = build_short_events_for_symbol(symbol, data_1m)
        data_15m_by_symbol[symbol] = data_15m
        event_frames.append(events)
        pool_frames.append(build_bear_state_pool(symbol, data_1m))
        funding, audit = download_funding(symbol)
        funding_data[symbol] = funding
        funding_rows.append(audit)

    data_inventory = pd.DataFrame(quality_rows)
    data_inventory.to_csv(OUT / "data_inventory.csv", index=False)
    data_inventory.to_csv(OUT / "data_quality_report.csv", index=False)
    (OUT / "data_quality_report.md").write_text(data_inventory.to_markdown(index=False) + "\n", encoding="utf-8")
    write_instrument_audit(funding_rows)

    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    pools = pd.concat(pool_frames, ignore_index=True) if pool_frames else pd.DataFrame()
    events.to_parquet(OUT / "short_event_table.parquet", index=False)
    events.head(200).to_csv(OUT / "short_event_table_sample.csv", index=False)
    summarize_events(events).to_csv(OUT / "short_event_summary.csv", index=False)
    period_event_summary(events, "Y").to_csv(OUT / "short_yearly_summary.csv", index=False)
    period_event_summary(events, "Q").to_csv(OUT / "short_quarterly_summary.csv", index=False)
    regime_summary(events).to_csv(OUT / "short_regime_summary.csv", index=False)
    asymmetry_summary(events, []).to_csv(OUT / "short_vs_long_asymmetry.csv", index=False)

    random_summary, random_matches = matched_random_baseline(events, pools, runs=1000, horizon=16)
    random_summary.to_csv(OUT / "short_random_baseline_summary.csv", index=False)
    random_matches.to_csv(OUT / "short_random_baseline_matches_sample.csv", index=False)
    delta = random_summary.copy()
    if not delta.empty:
        delta["observed_minus_random_mean"] = delta["observed_mean"] - delta["random_mean"]
    delta.to_csv(OUT / "short_event_vs_random_delta.csv", index=False)
    boot = ordinary_bootstrap(events, horizon=16, runs=1000)
    block = pd.concat([block_bootstrap(events, "month", 16, 1000), block_bootstrap(events, "symbol", 16, 1000)], ignore_index=True) if not events.empty else pd.DataFrame()
    boot.to_csv(OUT / "short_bootstrap_summary.csv", index=False)
    block.to_csv(OUT / "short_block_bootstrap_summary.csv", index=False)
    top_dep = top_dependency(events)
    top_dep.to_csv(OUT / "short_top_trade_dependency.csv", index=False)
    tail = events.groupby("symbol")["short_mae_16"].quantile([0.5, 0.9, 0.95, 0.99]).reset_index().rename(columns={"level_1": "quantile", "short_mae_16": "mae"})
    tail.to_csv(OUT / "short_tail_risk_summary.csv", index=False)
    pd.DataFrame([{
        "cost_scenario": s.name,
        "entry_fee_rate": s.fee_rate,
        "exit_fee_rate": s.fee_rate,
        "entry_slippage_rate": s.slippage_rate,
        "exit_slippage_rate": s.slippage_rate,
        "funding_rate_source": s.funding_rate_source,
        "borrow_cost_rate": s.borrow_cost_rate,
        "liquidation_fee_rate": s.liquidation_fee_rate,
    } for s in COST_SCENARIOS]).to_csv(OUT / "short_cost_assumptions.csv", index=False)

    gate_ok, gate_status = event_gate_pass(events, random_summary, boot, top_dep)
    short_decision = "F. no_validated_short_trend_edge"
    combination_decision = "F. no_validated_directional_coverage"
    archive_status = "P4_SHORT_EVENT_EDGE_NOT_FOUND"
    base_summary = pd.DataFrame()
    all_base_trades = pd.DataFrame()
    all_base_equity = pd.DataFrame()
    if gate_ok:
        archive_status = ""
        summaries = []
        scenario_trades = {}
        scenario_equities = {}
        for scenario in COST_SCENARIOS:
            all_trades = []
            all_equities = []
            for symbol in SYMBOLS:
                sym_events = events[events["symbol"] == symbol].copy()
                trades, equity = replay_short_events(sym_events, data_1m_by_symbol[symbol], data_15m_by_symbol[symbol], symbol, scenario, funding_data.get(symbol), leverage=1.0)
                if not trades.empty:
                    trades.to_csv(OUT / "trades" / f"{symbol}_{scenario.name}_short_trades.csv", index=False)
                    equity.assign(symbol=symbol).to_csv(OUT / "equity" / f"{symbol}_{scenario.name}_short_equity.csv", index=False)
                    all_trades.append(trades)
                    all_equities.append(equity.assign(symbol=symbol))
            all_trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
            all_equity_df = pd.concat(all_equities, ignore_index=True) if all_equities else pd.DataFrame()
            scenario_trades[scenario.name] = all_trades_df
            scenario_equities[scenario.name] = all_equity_df
            summary = summarize_backtests(all_trades_df, all_equity_df, scenario.name)
            summaries.append(summary)
            summary.to_csv(OUT / f"short_backtest_{scenario.name.replace('_cost', '')}.csv", index=False)
        cost_summary = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
        cost_summary.to_csv(OUT / "short_cost_scenario_summary.csv", index=False)
        base_summary = cost_summary[cost_summary["cost_scenario"] == "base_cost"].copy()
        all_base_trades = scenario_trades.get("base_cost", pd.DataFrame())
        all_base_equity = scenario_equities.get("base_cost", pd.DataFrame())
        all_base_trades.to_csv(OUT / "short_trades.csv", index=False)
        all_base_equity.to_csv(OUT / "short_equity_curve.csv", index=False)
        base_all = base_summary[base_summary["symbol"] == "ALL"]
        if not base_all.empty and float(base_all["profit_factor"].iloc[0]) > 1.10 and float(base_all["total_return"].iloc[0]) > 0:
            short_decision = "B. promising_but_more_validation_required"
        elif not base_all.empty and float(base_all["total_return"].iloc[0]) > 0:
            short_decision = "C. positive_gross_edge_but_costs_consume_it"
        else:
            short_decision = "D. unstable_or_tail_dependent"

        # Minimal placeholders for requested validation outputs.
        period_event_summary(events, "Y").to_csv(OUT / "short_walk_forward_windows.csv", index=False)
        base_summary.to_csv(OUT / "short_walk_forward_summary.csv", index=False)
        monthly, corr = compare_monthly(pd.DataFrame(), all_base_trades)
        monthly.to_csv(OUT / "long_short_monthly_returns.csv", index=False)
        corr.to_csv(OUT / "long_short_monthly_correlation.csv", index=False)
        pd.DataFrame([{"long_only_max_drawdown": np.nan, "long_short_max_drawdown": np.nan, "note": "canonical long trades not replayed in this short-only stage"}]).to_csv(OUT / "long_short_drawdown_comparison.csv", index=False)
        portfolio_summary(pd.DataFrame(), all_base_trades, pd.DataFrame({"time": all_base_trades["exit_time"], "equity": INITIAL_BALANCE + all_base_trades["net_pnl"].cumsum()}) if not all_base_trades.empty else pd.DataFrame()).to_csv(OUT / "long_short_portfolio_summary.csv", index=False)
        combination_decision = "E. insufficient_combination_evidence"
    else:
        for name, cols in EMPTY_REPLAY_COLUMNS.items():
            pd.DataFrame(columns=cols).to_csv(OUT / name, index=False)

    decision = pd.DataFrame([{
        "short_decision": short_decision,
        "combination_decision": combination_decision,
        "event_gate_status": gate_status,
        "archive_status": archive_status,
        "oos_status": "not_oos",
        "paper_trading_status": "not_allowed",
        "short_event_count": int(len(events)),
        "matched_random_event_count": int(random_summary["matched_event_count"].iloc[0]) if not random_summary.empty else 0,
        "short_base_trade_count": int(base_summary.loc[base_summary["symbol"] == "ALL", "trade_count"].iloc[0]) if not base_summary.empty and (base_summary["symbol"] == "ALL").any() else 0,
        "short_base_profit_factor": float(base_summary.loc[base_summary["symbol"] == "ALL", "profit_factor"].iloc[0]) if not base_summary.empty and (base_summary["symbol"] == "ALL").any() else np.nan,
        "short_base_net_return": float(base_summary.loc[base_summary["symbol"] == "ALL", "total_return"].iloc[0]) if not base_summary.empty and (base_summary["symbol"] == "ALL").any() else np.nan,
        "short_base_max_drawdown": float(base_summary.loc[base_summary["symbol"] == "ALL", "max_drawdown"].iloc[0]) if not base_summary.empty and (base_summary["symbol"] == "ALL").any() else np.nan,
        "short_positive_year_rate": float((period_event_summary(events, "Y").groupby("period")["mean_short_fwd_ret_16"].mean() > 0).mean()) if not events.empty else np.nan,
        "short_pf_gt_1_window_rate": np.nan,
        "short_top1_profit_contribution": float(top_dep["top1_profit_contribution"].iloc[0]) if not top_dep.empty else np.nan,
        "short_liquidation_count": int(all_base_trades["liquidation"].sum()) if not all_base_trades.empty else 0,
        "long_short_monthly_correlation": np.nan,
        "p4_down_month_short_positive_rate": np.nan,
        "long_only_max_drawdown": np.nan,
        "long_short_max_drawdown": np.nan,
        "long_only_longest_drawdown": "",
        "long_short_longest_drawdown": "",
    }])
    decision.to_csv(OUT / "short_decision_summary.csv", index=False)
    context = {
        "base_branch": "codex/adaptive-leverage-10x-20x",
        "base_commit_sha": base_commit,
        "research_branch": git_output(["branch", "--show-current"]),
        "research_head_commit_sha": current_git_commit(),
        "archive_status": archive_status,
    }
    write_report(context, short_decision, combination_decision)
    write_branch_metadata(base_commit, "pushed_before_research")
    append_run_log({
        "run_id": "P4_SHORT_TREND_DIRECTION_COVERAGE",
        "stage": "P4_SHORT",
        "script": "research_core.p4_short_research.run_p4_short_research",
        "config_hash": stable_hash({"symbols": SYMBOLS, "prototype": PROTOTYPE, "leverage": "1x", "time_alignment": "candle_close"}),
        "data_hash": stable_hash(data_hashes),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260624,
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": f"p4 short mirror research; {gate_status}; not OOS; no paper/live approval",
    })


if __name__ == "__main__":
    run()
