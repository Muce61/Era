"""Stage 2.0 audit for Stage 1 metric definitions and reporting."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.metrics import profit_factor
from research.trend_research_pipeline import first_touch
from strategy.eth_trend_signals import load_ohlcv_1m


STAGE1_ROOT = Path("backtest_results/stage1")
AUDIT_ROOT = Path("backtest_results/stage2/audit")
DATA_PATH = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/ETHUSDT.csv")
START = "2024-12-01 00:00:00"
END = "2025-12-12 20:00:00"
HORIZONS = [1, 4, 8, 16, 32]


def top_n_profit_contribution(pnl, top_n: int) -> float:
    pnl = pd.Series(pnl).dropna()
    total_net = pnl.sum()
    if total_net <= 0:
        return 0.0
    winners = pnl[pnl > 0].sort_values(ascending=False)
    if winners.empty:
        return 0.0
    return float(winners.head(top_n).sum() / total_net * 100)


def first_touch_outcome(path: pd.DataFrame, entry: float, atr: float) -> str:
    outcome, _, ambiguous = first_touch(path, entry, atr, "LONG", 1, 1)
    if ambiguous:
        return "ambiguous"
    return outcome


def recompute_event_first_touch(detail: pd.DataFrame, data_1m: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, event in detail.iterrows():
        row = event.to_dict()
        signal_time = pd.Timestamp(event["signal_time"])
        entry = float(event["entry_price_1m_open"])
        atr = float(event["atr"])

        for horizon in HORIZONS:
            path_start = signal_time + pd.Timedelta(minutes=1)
            path_end = signal_time + pd.Timedelta(minutes=15 * horizon)
            path = data_1m.loc[path_start:path_end]
            outcome = first_touch_outcome(path, entry, atr) if not path.empty and atr > 0 else "none"
            row[f"first_touch_1atr_{horizon}"] = outcome
            row[f"plus_1atr_first_{horizon}"] = outcome == "profit"
            row[f"minus_1atr_first_{horizon}"] = outcome == "loss"
            row[f"ambiguous_1atr_{horizon}"] = outcome == "ambiguous"
            row[f"none_1atr_{horizon}"] = outcome == "none"

        rows.append(row)
    return pd.DataFrame(rows)


def build_corrected_event_summary(corrected_detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for entry_mode, grp in corrected_detail.groupby("entry_mode", dropna=False):
        row = {"entry_mode": entry_mode, "signal_count": len(grp)}
        for horizon in HORIZONS:
            row[f"mean_forward_return_{horizon}"] = grp[f"forward_return_{horizon}"].mean()
            row[f"mean_future_mae_pct_{horizon}"] = grp[f"future_mae_{horizon}"].mean()
            row[f"plus_1atr_rate_{horizon}"] = grp[f"plus_1atr_first_{horizon}"].mean()
            row[f"minus_1atr_rate_{horizon}"] = grp[f"minus_1atr_first_{horizon}"].mean()
            row[f"ambiguous_1atr_rate_{horizon}"] = grp[f"ambiguous_1atr_{horizon}"].mean()
            row[f"none_1atr_rate_{horizon}"] = grp[f"none_1atr_{horizon}"].mean()
        rows.append(row)
    return pd.DataFrame(rows).sort_values("entry_mode")


def build_corrected_stage1_summary() -> pd.DataFrame:
    base = pd.read_csv(STAGE1_ROOT / "experiment_summary.csv")
    rows = []
    for _, summary in base.iterrows():
        label = summary["label"]
        trades_path = STAGE1_ROOT / label / "trades.csv"
        trades = pd.read_csv(trades_path)
        pnl = trades["net_pnl"] if "net_pnl" in trades else pd.Series(dtype=float)

        row = summary.to_dict()
        row["profit_factor_recomputed_net_pnl"] = profit_factor(pnl)
        row["top_1_profit_contribution"] = top_n_profit_contribution(pnl, 1)
        row["top_3_profit_contribution"] = top_n_profit_contribution(pnl, 3)
        row["top_5_profit_contribution"] = top_n_profit_contribution(pnl, 5)
        row["top_10_profit_contribution"] = top_n_profit_contribution(pnl, 10)
        row["pf_source"] = "recomputed_from_trade_net_pnl"
        rows.append(row)
    return pd.DataFrame(rows)


def write_metric_definitions(path: Path) -> None:
    path.write_text(
        """# Metric Definitions

## Profit Factor

`profit_factor = sum(net_pnl > 0) / abs(sum(net_pnl <= 0))`

All Stage 2 reports use trade-level `net_pnl` after entry fee, exit fee, and slippage embedded in executed prices.

## Top-N Profit Contribution

```python
top_n_profit_contribution = (
    top_n_winning_trades_net_pnl / total_net_pnl
)
```

If `total_net_pnl <= 0`, contribution is reported as `0.0` because profit concentration is not meaningful for a losing system.

## Event Forward MAE/MFE

Event-study forward MAE/MFE are measured on all signal events, not only executed trades.

- `future_mae_{h}`: percentage adverse excursion over the next `h` 15m bars.
- `future_mfe_{h}`: percentage favorable excursion over the next `h` 15m bars.
- These are not the same as trade-level full-holding `mae_atr` / `mfe_atr`.

## Trade MAE/MFE

Trade MAE/MFE are measured only for executed trades over the full holding period.

- `mae_atr`: full-holding adverse excursion normalized by entry ATR.
- `mfe_atr`: full-holding favorable excursion normalized by entry ATR.

## First Touch +1 ATR / -1 ATR

For each signal event, the path starts at the next 1m bar after the 15m signal close.

- `profit`: +1 ATR touched before -1 ATR.
- `loss`: -1 ATR touched before +1 ATR.
- `ambiguous`: both thresholds touched in the same 1m candle.
- `none`: neither threshold touched inside the horizon.

Ambiguous events are never counted as favorable hits.
""",
        encoding="utf-8",
    )


def write_stage1_corrections(path: Path, corrected_event: pd.DataFrame, corrected_summary: pd.DataFrame) -> None:
    b1 = corrected_summary.loc[corrected_summary["label"] == "B1"].iloc[0]
    h16 = corrected_event[["entry_mode", "plus_1atr_rate_16", "minus_1atr_rate_16", "ambiguous_1atr_rate_16"]]
    lines = [
        "# Stage 1 Corrections",
        "",
        "## Event Study Text Correction",
        "",
        "The Stage 1 report sentence saying B3 +1 ATR first-touch was higher than B1 is incorrect.",
        "Correct 16-bar +1 ATR first-touch rates are:",
        "",
        h16.to_markdown(index=False),
        "",
        "B3 remains below B1 on +1 ATR first-touch rate at the 16-bar horizon.",
        "",
        "## Profit Factor Canonical Source",
        "",
        f"B1 official repaired-accounting PF is `{b1['profit_factor_recomputed_net_pnl']:.6f}`.",
        "Older PF values around 1.09 came from the pre-repair/prototype result and are not the Stage 2 baseline.",
        "",
        "## MAE Warning",
        "",
        "Do not compare event-study fixed-horizon percentage MAE directly with trade-level full-holding ATR-normalized MAE.",
        "They answer different questions and have different denominators, sample sets, and holding windows.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    data_1m = load_ohlcv_1m(DATA_PATH, START, END)
    detail = pd.read_csv(STAGE1_ROOT / "event_study_detail.csv", parse_dates=["signal_time"])

    corrected_detail = recompute_event_first_touch(detail, data_1m)
    corrected_event = build_corrected_event_summary(corrected_detail)
    corrected_summary = build_corrected_stage1_summary()

    corrected_summary.to_csv(AUDIT_ROOT / "corrected_stage1_summary.csv", index=False)
    corrected_event.to_csv(AUDIT_ROOT / "corrected_event_summary.csv", index=False)
    corrected_detail.to_csv(AUDIT_ROOT / "corrected_event_detail.csv", index=False)
    write_metric_definitions(AUDIT_ROOT / "metric_definitions.md")
    write_stage1_corrections(AUDIT_ROOT / "stage1_corrections.md", corrected_event, corrected_summary)

    metadata = {
        "data_path": str(DATA_PATH),
        "stage1_root": str(STAGE1_ROOT),
        "start": START,
        "end": END,
        "horizons": HORIZONS,
    }
    (AUDIT_ROOT / "audit_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Stage 2 audit outputs written to {AUDIT_ROOT}")


if __name__ == "__main__":
    main()
