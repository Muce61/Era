"""Verify micro position MFE using 1s data vs 1m engine (3-month window)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from backtest.eth_trend_engine import EthTrendEngine
from backtest.stage4_config import load_stage4_frozen_config, run_config_from_label

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "backtest_results" / "micro_mfe_1s_verify"

WINDOW_START = "2025-04-01 00:00:00"
WINDOW_END = "2025-06-30 23:59:59"
SYMBOL = "ETHUSDT"
MODES = ["B2", "B3"]
DATA_1M = REPO_ROOT / "backtest_results" / "stage2" / "data_audit" / "merged_ethusdt_1m.csv"
DATA_1S_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg/ETHUSDT_1s_agg")


def load_1s_day(date_str: str) -> pd.DataFrame:
    parquet = DATA_1S_ROOT / f"ETHUSDT_1s_{date_str}.parquet"
    csv = DATA_1S_ROOT / f"ETHUSDT_1s_{date_str}.csv"
    if parquet.exists():
        df = pd.read_parquet(parquet)
        if "timestamp" not in df.columns:
            df = df.reset_index()
        ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
        df["timestamp"] = pd.to_datetime(df[ts_col], utc=True)
    elif csv.exists():
        df = pd.read_csv(csv)
        df["timestamp"] = pd.to_datetime(df["ts_sec"], unit="ms", utc=True)
    else:
        return pd.DataFrame()
    return df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp")


def load_1s_range(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    start = start.tz_convert("UTC")
    end = end.tz_convert("UTC")
    parts = []
    cur = start.normalize()
    while cur <= end.normalize():
        day = load_1s_day(cur.strftime("%Y%m%d"))
        if not day.empty:
            parts.append(day)
        cur += timedelta(days=1)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp", keep="first")
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()


def pos_mfe_pct(entry_price: float, high_price: float, notional: float, balance_before: float) -> float:
    if entry_price <= 0 or balance_before <= 0:
        return 0.0
    return (high_price - entry_price) / entry_price * notional / balance_before * 100


def bucket_label(v: float) -> str:
    if v <= 0:
        return "0"
    if v <= 0.5:
        return "(0,0.5%]"
    if v <= 1.0:
        return "(0.5-1%]"
    return ">1%"


def run_mode(mode: str) -> pd.DataFrame:
    frozen = load_stage4_frozen_config(mode)
    engine = EthTrendEngine(
        config=run_config_from_label(mode),
        data_path=DATA_1M,
        symbol=SYMBOL,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        initial_balance=frozen["initial_balance"],
    )
    engine.run(verbose=False)
    trades = pd.DataFrame(engine.trades)
    if trades.empty:
        return pd.DataFrame()

    trades["entry_time"] = pd.to_datetime(trades["entry_time"], utc=True)
    trades["exit_time"] = pd.to_datetime(trades["exit_time"], utc=True)
    rows = []
    for idx, row in trades.iterrows():
        entry_t, exit_t = row["entry_time"], row["exit_time"]
        entry_price = float(row["entry_price"])
        notional = float(row["notional"])
        bb = float(row["balance_before"])
        mfe_1m = float(row["mfe_pct"]) * notional / bb * 100
        seg = load_1s_range(entry_t, exit_t)
        if seg.empty:
            mfe_1s = None
            high_1s = None
            bars_1s = 0
        else:
            high_1s = float(seg["high"].max())
            mfe_1s = pos_mfe_pct(entry_price, high_1s, notional, bb)
            bars_1s = len(seg)
        entry_fee_pct = float(row["entry_fee"]) / bb * 100
        exit_fee_pct = 0.0005 * notional / bb * 100
        net_peak_1s = (mfe_1s - entry_fee_pct - exit_fee_pct) if mfe_1s is not None else None
        rows.append({
            "mode": mode,
            "entry_time": entry_t,
            "exit_time": exit_t,
            "entry_price": entry_price,
            "reason": row["reason"],
            "ret_pct": float(row["return_pct_on_equity"]),
            "mfe_pos_1m": mfe_1m,
            "mfe_pos_1s": mfe_1s,
            "mfe_delta_1s_minus_1m": (mfe_1s - mfe_1m) if mfe_1s is not None else None,
            "high_1s": high_1s,
            "bars_1s": bars_1s,
            "duration_min": (exit_t - entry_t).total_seconds() / 60,
            "net_at_peak_1s_pct": net_peak_1s,
            "notional": notional,
            "balance_before": bb,
        })
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_detail = []
    summary_rows = []

    for mode in MODES:
        detail = run_mode(mode)
        if detail.empty:
            continue
        all_detail.append(detail)
        valid = detail.dropna(subset=["mfe_pos_1s"])
        micro_1m = valid[(valid["mfe_pos_1m"] > 0) & (valid["mfe_pos_1m"] <= 0.5)]
        micro_1s = valid[(valid["mfe_pos_1s"] > 0) & (valid["mfe_pos_1s"] <= 0.5)]
        summary_rows.append({
            "mode": mode,
            "trades": len(detail),
            "micro_1m": len(micro_1m),
            "micro_1s": len(micro_1s),
            "micro_1m_all_loss": int((micro_1m["ret_pct"] <= 0).sum()) if len(micro_1m) else 0,
            "micro_1s_net_peak_pos": int((micro_1s["net_at_peak_1s_pct"] > 0).sum()) if len(micro_1s) else 0,
            "mean_delta_1s_1m": valid["mfe_delta_1s_minus_1m"].mean(),
            "overstate_1m": int((valid["mfe_delta_1s_minus_1m"] < 0).sum()),
            "understate_1m": int((valid["mfe_delta_1s_minus_1m"] > 0).sum()),
            "exact_match": int((valid["mfe_delta_1s_minus_1m"].abs() < 1e-9).sum()),
        })

    if not all_detail:
        print("No trades")
        return

    detail = pd.concat(all_detail, ignore_index=True)
    detail["bucket_1m"] = detail["mfe_pos_1m"].apply(bucket_label)
    detail["bucket_1s"] = detail["mfe_pos_1s"].apply(lambda x: bucket_label(x) if pd.notna(x) else "na")
    detail.to_csv(OUT_DIR / "trade_mfe_1s_vs_1m.csv", index=False)

    summary = pd.DataFrame(summary_rows)
    summary.insert(0, "window_start", WINDOW_START)
    summary.insert(1, "window_end", WINDOW_END)
    summary.to_csv(OUT_DIR / "summary_by_mode.csv", index=False)

    lines = [
        "# Micro MFE 1s verification",
        "",
        f"Window: **{WINDOW_START}** ~ **{WINDOW_END}** (3 months, inside 1s coverage)",
        f"Symbol: {SYMBOL}",
        "",
        "Compare holding-period high from 1s bars vs engine 1m `mfe_pct`.",
        "",
        "## Summary by mode",
        summary.to_markdown(index=False),
        "",
    ]

    for mode in MODES:
        sub = detail[detail["mode"] == mode].dropna(subset=["mfe_pos_1s"])
        if sub.empty:
            continue
        cross = pd.crosstab(sub["bucket_1m"], sub["bucket_1s"])
        lines.append(f"## {mode} bucket crosstab (1m -> 1s)")
        lines.append(cross.to_markdown())
        lines.append("")
        micro = sub[(sub["mfe_pos_1m"] > 0) & (sub["mfe_pos_1m"] <= 0.5)]
        if not micro.empty:
            lines.append(f"### {mode} 1m micro (0,0.5%] trades")
            cols = ["entry_time", "mfe_pos_1m", "mfe_pos_1s", "mfe_delta_1s_minus_1m", "ret_pct", "net_at_peak_1s_pct", "reason"]
            lines.append(micro[cols].to_markdown(index=False))
            lines.append("")

    (OUT_DIR / "micro_mfe_1s_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"Window: {WINDOW_START} ~ {WINDOW_END}")
    print(summary.to_string(index=False))
    print(f"\nWritten to {OUT_DIR}")


if __name__ == "__main__":
    main()
