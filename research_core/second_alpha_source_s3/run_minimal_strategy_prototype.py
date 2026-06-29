"""Run S3 exit-window minimal strategy prototype."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from research_core.common import append_run_log, current_git_commit, stable_hash
from research_core.leverage_research_analysis import INITIAL_BALANCE
from research_core.second_alpha_source_s3.minimal_strategy_prototype import (
    S3_DIR,
    SIZING_MODES,
    SIDE_SCOPES,
    SYMBOLS,
    combine_equity_curves,
    decision_summary,
    event_to_trade_conversion,
    input_validation,
    load_events,
    load_symbol_data,
    p4_complement_summary,
    period_summary,
    portfolio_comparison,
    run_backtest_for_symbol,
    summarize_trades,
    symbol_side_summary,
    tail_dependency,
)


RANDOM_SEED = 20260624


def write_report(input_val, summary, conversion, tail, complement, portfolio, decision) -> None:
    letter = decision["decision_letter"].iloc[0] if not decision.empty else "E"
    text = {
        "A": "A. 真实交易后仍有正期望，可进入 S4 OOS / shadow 准备",
        "B": "B. 真实交易后有弱正期望，但需要更保守组合验证",
        "C": "C. 事件 edge 被交易成本 / 持仓冲突 / 退出规则吃掉",
        "D": "D. 真实交易后依赖少数标的或少数交易，不适合策略化",
        "E": "E. 输入或实现问题导致无法判断",
    }[letter]
    focus = summary[(summary["symbol"] == "ALL") & (summary["side_scope"] == "both") & (summary["sizing_mode"] == "fixed_1x")]
    lines = [
        "# S3 Exit-Window IDLE_MR1 最小策略原型回测报告",
        "",
        "data_layer: expanded_discovery_long_history",
        "oos_status: not_oos",
        "funding_status: unavailable",
        "",
        "## 输入验收",
        "",
        input_val.to_markdown(index=False),
        "",
        "## 核心结果",
        "",
        focus.to_markdown(index=False) if not focus.empty else "No ALL fixed_1x summary.",
        "",
        "## 必答问题",
        "",
        "1. 事件 edge 是否转化为真实交易收益：见 `s3_backtest_summary.csv` 的 ALL fixed_1x。",
        "2. 交易成本是否吃掉 edge：见 `fee_to_gross_profit_ratio`。",
        "3. BTC 是否仍拖累：见 `s3_symbol_side_summary.csv`。",
        "4. ETH 是否仍头部依赖：见 `s3_tail_dependency.csv`。",
        "5. SOL/BNB 是否仍强：见 `s3_backtest_summary.csv` 和 symbol-side summary。",
        "6. long/short 是否都值得保留：long_only/short_only 只作诊断，见 summary。",
        "7. 与 P4 是否低相关：见 `s3_p4_complement_summary.csv`。",
        "8. 是否改善 P4 弱月份：见 `s3_p4_complement_summary.csv`。",
        "9. 组合后是否降低回撤或缩短回撤时间：见 `s3_portfolio_comparison.csv`，当前 P4 侧为月度 proxy。",
        "10. 是否允许进入 S4：见 `s3_decision_summary.csv`。",
        "",
        "## Event-to-Trade Conversion",
        "",
        conversion.head(20).to_markdown(index=False) if not conversion.empty else "No conversion rows.",
        "",
        "## Portfolio Comparison",
        "",
        portfolio.to_markdown(index=False) if not portfolio.empty else "No portfolio comparison.",
        "",
        "## 最终结论",
        "",
        text,
        "",
        "本阶段不称为 OOS，不作为模拟盘或实盘准入依据。",
    ]
    (S3_DIR / "second_alpha_s3_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_blocked(input_val: pd.DataFrame) -> None:
    empty = pd.DataFrame()
    for name in [
        "s3_event_to_trade_conversion.csv",
        "s3_backtest_summary.csv",
        "s3_monthly_summary.csv",
        "s3_quarterly_summary.csv",
        "s3_yearly_summary.csv",
        "s3_symbol_side_summary.csv",
        "s3_tail_dependency.csv",
        "s3_p4_complement_summary.csv",
        "s3_portfolio_comparison.csv",
    ]:
        empty.to_csv(S3_DIR / name, index=False)
    decision = pd.DataFrame([{
        "decision_letter": "E",
        "decision_status": "input_or_implementation_problem",
        "strategy_backtest_generated": False,
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
    }])
    decision.to_csv(S3_DIR / "s3_decision_summary.csv", index=False)
    write_report(input_val, empty, empty, empty, empty, empty, decision)


def main() -> None:
    S3_DIR.mkdir(parents=True, exist_ok=True)
    (S3_DIR / "s3_trades").mkdir(parents=True, exist_ok=True)
    (S3_DIR / "s3_equity_curves").mkdir(parents=True, exist_ok=True)
    input_val = input_validation()
    input_val.to_csv(S3_DIR / "s3_input_validation.csv", index=False)
    status = "success"
    if input_val["input_validation_status"].iloc[0] != "pass":
        _write_blocked(input_val)
        status = "blocked"
    else:
        events = load_events()
        data_by_symbol = {}
        all_trades = []
        all_equities = {}
        all_conversions = []
        summary_rows = []
        for symbol in SYMBOLS:
            data_1m, data_15m = load_symbol_data(symbol)
            data_by_symbol[symbol] = data_1m
            symbol_events = events[events["symbol"] == symbol].copy()
            for sizing_mode in SIZING_MODES:
                trades, equity, conv = run_backtest_for_symbol(symbol_events, data_1m, data_15m, symbol, sizing_mode, "both")
                all_equities[(symbol, "both", sizing_mode)] = equity
                if not trades.empty:
                    all_trades.append(trades)
                all_conversions.append(conv.assign(side_scope="both", sizing_mode=sizing_mode))
                trades.to_csv(S3_DIR / "s3_trades" / f"{symbol}_both_{sizing_mode}_trades.csv", index=False)
                equity.to_csv(S3_DIR / "s3_equity_curves" / f"{symbol}_both_{sizing_mode}_equity.csv", index=False)
                summary_rows.append(summarize_trades(symbol, "both", sizing_mode, trades, equity, data_1m.index.min(), data_1m.index.max()))
                # Diagnostic side-only rows are derived from actual both-mode fills.
                for side_scope, side in [("long_only", "long"), ("short_only", "short")]:
                    part = trades[trades["side"] == side].copy() if not trades.empty else trades.copy()
                    if not part.empty:
                        eq_diag = pd.DataFrame({
                            "time": pd.to_datetime(part["exit_time"], utc=True).reset_index(drop=True),
                            "equity": (INITIAL_BALANCE + part["net_pnl"].cumsum()).reset_index(drop=True),
                            "symbol": symbol,
                            "sizing_mode": sizing_mode,
                            "side_scope": side_scope,
                        })
                    else:
                        eq_diag = pd.DataFrame({"time": [data_1m.index.min()], "equity": [INITIAL_BALANCE], "symbol": symbol, "sizing_mode": sizing_mode, "side_scope": side_scope})
                    all_equities[(symbol, side_scope, sizing_mode)] = eq_diag
                    part = part.assign(side_scope=side_scope)
                    if not part.empty:
                        all_trades.append(part)
                    part.to_csv(S3_DIR / "s3_trades" / f"{symbol}_{side_scope}_{sizing_mode}_trades.csv", index=False)
                    eq_diag.to_csv(S3_DIR / "s3_equity_curves" / f"{symbol}_{side_scope}_{sizing_mode}_equity.csv", index=False)
                    summary_rows.append(summarize_trades(symbol, side_scope, sizing_mode, part, eq_diag, data_1m.index.min(), data_1m.index.max()))
        trades_all = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
        conversions = pd.concat(all_conversions, ignore_index=True) if all_conversions else pd.DataFrame()
        for side_scope in SIDE_SCOPES:
            for sizing_mode in SIZING_MODES:
                eqs = [all_equities[(symbol, side_scope, sizing_mode)] for symbol in SYMBOLS if (symbol, side_scope, sizing_mode) in all_equities]
                combined = combine_equity_curves(eqs)
                combined.to_csv(S3_DIR / "s3_equity_curves" / f"ALL_{side_scope}_{sizing_mode}_equity.csv", index=False)
                part = trades_all[(trades_all["side_scope"] == side_scope) & (trades_all["sizing_mode"] == sizing_mode)].copy()
                summary_rows.append(summarize_trades("ALL", side_scope, sizing_mode, part, combined, pd.to_datetime(combined["time"]).min(), pd.to_datetime(combined["time"]).max()))
        summary = pd.DataFrame(summary_rows)
        summary.to_csv(S3_DIR / "s3_backtest_summary.csv", index=False)
        event_to_trade_conversion(conversions[conversions["side_scope"] == "both"]).to_csv(S3_DIR / "s3_event_to_trade_conversion.csv", index=False)
        period_summary(trades_all[trades_all["side_scope"] == "both"], "M").to_csv(S3_DIR / "s3_monthly_summary.csv", index=False)
        period_summary(trades_all[trades_all["side_scope"] == "both"], "Q").to_csv(S3_DIR / "s3_quarterly_summary.csv", index=False)
        period_summary(trades_all[trades_all["side_scope"] == "both"], "Y").to_csv(S3_DIR / "s3_yearly_summary.csv", index=False)
        symbol_side_summary(trades_all[trades_all["side_scope"] == "both"]).to_csv(S3_DIR / "s3_symbol_side_summary.csv", index=False)
        tail = tail_dependency(pd.concat([
            trades_all[trades_all["side_scope"] == "both"],
            trades_all[trades_all["side_scope"] == "both"].assign(symbol="ALL"),
        ], ignore_index=True))
        tail.to_csv(S3_DIR / "s3_tail_dependency.csv", index=False)
        p4_proxy_path = S3_DIR.parent / "second_alpha_source_s28" / "p4_monthly_proxy.csv"
        p4_proxy = pd.read_csv(p4_proxy_path)
        complement = p4_complement_summary(trades_all[(trades_all["side_scope"] == "both") & (trades_all["sizing_mode"] == "fixed_1x")], p4_proxy)
        complement.to_csv(S3_DIR / "s3_p4_complement_summary.csv", index=False)
        combined_eq = pd.read_csv(S3_DIR / "s3_equity_curves" / "ALL_both_fixed_1x_equity.csv")
        portfolio = portfolio_comparison(trades_all[(trades_all["side_scope"] == "both") & (trades_all["sizing_mode"] == "fixed_1x")], combined_eq, p4_proxy)
        portfolio.to_csv(S3_DIR / "s3_portfolio_comparison.csv", index=False)
        decision = decision_summary(summary, tail, complement)
        decision.to_csv(S3_DIR / "s3_decision_summary.csv", index=False)
        write_report(input_val, summary, event_to_trade_conversion(conversions[conversions["side_scope"] == "both"]), tail, complement, portfolio, decision)
    metadata = pd.DataFrame([{
        "run_id": "S3_EXIT_WINDOW_MINIMAL_STRATEGY_PROTOTYPE",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "config_hash": stable_hash({"candidate": "IDLE_MR1", "bucket": "after_p4_exit_5_16", "sizing": SIZING_MODES}),
        "data_hash": stable_hash({"source": "long_history_exit_window_events"}),
        "git_commit": current_git_commit(),
        "data_layer": "expanded_discovery_long_history",
        "oos_status": "not_oos",
        "status": status,
    }])
    metadata.to_csv(S3_DIR / "s3_run_metadata.csv", index=False)
    append_run_log({
        "run_id": "S3_EXIT_WINDOW_MINIMAL_STRATEGY_PROTOTYPE",
        "stage": "S3",
        "script": "research_core/second_alpha_source_s3/run_minimal_strategy_prototype.py",
        "config_hash": stable_hash({"candidate": "IDLE_MR1", "bucket": "after_p4_exit_5_16", "sizing": SIZING_MODES}),
        "data_hash": stable_hash({"source": "long_history_exit_window_events"}),
        "git_commit": current_git_commit(),
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_layer": "expanded_discovery_long_history",
        "status": status,
        "notes": "minimal strategy prototype; not OOS; no deployable strategy generated",
    })


if __name__ == "__main__":
    main()
