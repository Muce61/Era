"""L1 adaptive high-leverage research helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from research_core.minimal_backtest_analysis import max_drawdown, profit_factor, top_profit_contribution, longest_drawdown_duration


TARGET_PROTOTYPES = ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
LEVERAGE_MODES = ["baseline_fixed_2x", "fixed_10x", "fixed_20x", "adaptive_10x_20x_v1"]
L2_LEVERAGE_MODES = [
    "baseline_fixed_2x",
    "fixed_3x",
    "fixed_5x",
    "fixed_8x",
    "fixed_10x",
    "adaptive_3x_8x_v1",
    "adaptive_4x_10x_v1",
    "adaptive_5x_12x_v1",
]
INITIAL_BALANCE = 1000.0
FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0002
MAINTENANCE_MARGIN_RATE = 0.005


@dataclass(frozen=True)
class StressConfig:
    name: str
    fee_mult: float = 1.0
    slippage_mult: float = 1.0
    entry_delay_minutes: int = 0
    exit_delay_minutes: int = 0
    liquidation_up_shift: float = 0.0


STRESS_CASES = [
    StressConfig("base"),
    StressConfig("fee_2x", fee_mult=2.0),
    StressConfig("slippage_2x", slippage_mult=2.0),
    StressConfig("entry_delay_1m", entry_delay_minutes=1),
    StressConfig("entry_delay_3m", entry_delay_minutes=3),
    StressConfig("exit_delay_1m", exit_delay_minutes=1),
    StressConfig("exit_delay_3m", exit_delay_minutes=3),
    StressConfig("liquidation_price_up_10pct", liquidation_up_shift=0.10),
    StressConfig("liquidation_price_up_20pct", liquidation_up_shift=0.20),
]


def liquidation_price(entry_price: float, leverage: float, maintenance_margin_rate: float = MAINTENANCE_MARGIN_RATE) -> float:
    return entry_price * (1 - 1 / leverage + maintenance_margin_rate)


def shifted_liquidation_price(entry_price: float, leverage: float, shift: float) -> float:
    base = liquidation_price(entry_price, leverage)
    return entry_price - (entry_price - base) * (1 - shift)


def min_trade_price(trade: pd.Series) -> float:
    return float(trade["entry_price"] + trade["mae_atr"] * trade["atr"])


def load_trade_inputs(repo_root: Path) -> dict[tuple[str, str], pd.DataFrame]:
    out: dict[tuple[str, str], pd.DataFrame] = {}
    for prototype in TARGET_PROTOTYPES:
        path = repo_root / "research_core" / "minimal_backtest" / "prototype_trades" / f"{prototype}_fixed_2x_trades.csv"
        frame = pd.read_csv(path)
        frame["symbol"] = "ETHUSDT"
        out[("ETHUSDT", prototype)] = frame
    for symbol in ["BTCUSDT", "SOLUSDT", "BNBUSDT"]:
        path = repo_root / "research_core" / "cross_asset_validation" / "prototype_trades" / f"{symbol}_trades.csv"
        frame = pd.read_csv(path)
        for prototype in TARGET_PROTOTYPES:
            part = frame[(frame["prototype"] == prototype) & (frame["sizing_mode"] == "fixed_2x")].copy()
            out[(symbol, prototype)] = part
    return out


def load_event_metadata(repo_root: Path) -> pd.DataFrame:
    frames = []
    eth_events = pd.read_parquet(repo_root / "research_core" / "events" / "event_candidates.parquet")
    eth_scores = pd.read_parquet(repo_root / "research_core" / "family_validation" / "family_scores.parquet")
    eth = eth_events[["event_id", "atr_pct"]].merge(
        eth_scores[["event_id", "breakout_score_quantile"]],
        on="event_id",
        how="left",
    )
    eth["symbol"] = "ETHUSDT"
    frames.append(eth)
    for symbol in ["BTCUSDT", "SOLUSDT", "BNBUSDT"]:
        events_path = repo_root / "research_core" / "cross_asset_validation" / "events" / f"{symbol}_event_candidates.parquet"
        scores_path = repo_root / "research_core" / "cross_asset_validation" / "scores" / f"{symbol}_family_scores.parquet"
        events = pd.read_parquet(events_path)
        scores = pd.read_parquet(scores_path)
        part = events[["event_id", "atr_pct"]].merge(scores[["event_id", "breakout_score"]], on="event_id", how="left")
        part["breakout_score_quantile"] = part["breakout_score"].rank(pct=True, method="first")
        part["symbol"] = symbol
        frames.append(part[["event_id", "atr_pct", "breakout_score_quantile", "symbol"]])
    meta = pd.concat(frames, ignore_index=True)
    meta["atr_pct_rank"] = meta.groupby("symbol")["atr_pct"].rank(pct=True, method="average")
    return meta


def attach_metadata(trades: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    return trades.merge(metadata[["event_id", "atr_pct", "atr_pct_rank", "breakout_score_quantile"]], on="event_id", how="left")


def fixed_leverage_for_mode(mode: str) -> float:
    if mode == "baseline_fixed_2x":
        return 2.0
    if mode == "fixed_3x":
        return 3.0
    if mode == "fixed_5x":
        return 5.0
    if mode == "fixed_8x":
        return 8.0
    if mode == "fixed_10x":
        return 10.0
    if mode == "fixed_20x":
        return 20.0
    raise ValueError(f"Not a fixed leverage mode: {mode}")


def recent_loss_count(pnls: list[float], window: int = 3) -> int:
    return int(sum(1 for pnl in pnls[-window:] if pnl < 0))


def adaptive_leverage(
    prototype: str,
    breakout_score_quantile: float,
    atr_pct_rank: float,
    equity_drawdown: float,
    recent_3_losses: int,
) -> tuple[float, str]:
    if equity_drawdown > 0.20:
        return 3.0, "drawdown_gt_20pct"
    if equity_drawdown > 0.10:
        return 6.0, "drawdown_gt_10pct"
    if recent_3_losses >= 3:
        return 5.0, "recent_3_losses"
    if atr_pct_rank > 0.80:
        return 8.0, "atr_pct_rank_gt_80pct"
    if (
        prototype in TARGET_PROTOTYPES
        and breakout_score_quantile >= 0.80
        and atr_pct_rank <= 0.60
        and equity_drawdown <= 0.05
        and recent_3_losses < 3
    ):
        return 20.0, "all_raise_conditions_met"
    return 10.0, "default_10x"


def adaptive_leverage_by_mode(
    mode: str,
    prototype: str,
    breakout_score_quantile: float,
    atr_pct_rank: float,
    equity_drawdown: float,
    recent_3_losses: int,
) -> tuple[float, str, float]:
    if mode == "adaptive_10x_20x_v1":
        leverage, reason = adaptive_leverage(
            prototype,
            breakout_score_quantile,
            atr_pct_rank,
            equity_drawdown,
            recent_3_losses,
        )
        return leverage, reason, 10.0
    specs = {
        "adaptive_3x_8x_v1": {
            "base": 3.0,
            "max": 8.0,
            "high_atr": 2.0,
            "dd10": 2.0,
            "dd20": 1.0,
            "losses": 2.0,
            "default_reason": "default_3x",
        },
        "adaptive_4x_10x_v1": {
            "base": 4.0,
            "max": 10.0,
            "high_atr": 3.0,
            "dd10": 2.0,
            "dd20": 1.0,
            "losses": 2.0,
            "default_reason": "default_4x",
        },
        "adaptive_5x_12x_v1": {
            "base": 5.0,
            "max": 12.0,
            "high_atr": 3.0,
            "dd10": 2.0,
            "dd20": 1.0,
            "losses": 2.0,
            "default_reason": "default_5x",
        },
    }
    if mode not in specs:
        raise ValueError(f"Not an adaptive leverage mode: {mode}")
    spec = specs[mode]
    if equity_drawdown > 0.20:
        return spec["dd20"], "drawdown_gt_20pct", spec["base"]
    if equity_drawdown > 0.10:
        return spec["dd10"], "drawdown_gt_10pct", spec["base"]
    if recent_3_losses >= 3:
        return spec["losses"], "recent_3_losses", spec["base"]
    if atr_pct_rank > 0.80:
        return spec["high_atr"], "atr_pct_rank_gt_80pct", spec["base"]
    if (
        prototype in TARGET_PROTOTYPES
        and breakout_score_quantile >= 0.80
        and atr_pct_rank <= 0.60
        and equity_drawdown <= 0.05
        and recent_3_losses < 3
    ):
        return spec["max"], "all_raise_conditions_met", spec["base"]
    return spec["base"], spec["default_reason"], spec["base"]


def apply_stress_prices(trade: pd.Series, stress: StressConfig) -> tuple[float, float]:
    entry = float(trade["entry_price"])
    exit_price = float(trade["exit_price"])
    # Delay is modeled as adverse drift in L1 because minute bars are not persisted in trade files.
    entry *= 1 + 0.0005 * stress.entry_delay_minutes
    exit_price *= 1 - 0.0005 * stress.exit_delay_minutes
    extra_slip = max(stress.slippage_mult - 1.0, 0.0) * SLIPPAGE_RATE
    entry *= 1 + extra_slip
    exit_price *= 1 - extra_slip
    return entry, exit_price


def simulate_leverage_path(
    trades: pd.DataFrame,
    symbol: str,
    prototype: str,
    leverage_mode: str,
    stress: StressConfig = StressConfig("base"),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    equity = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    rows = []
    equity_rows = [{"time": trades["entry_time"].iloc[0] if not trades.empty else "", "equity": equity}]
    audit_rows = []
    pnl_history: list[float] = []
    for trade_id, (_, trade) in enumerate(trades.sort_values("entry_time").iterrows(), start=1):
        equity_before = equity
        peak = max(peak, equity_before)
        drawdown = 1 - equity_before / peak if peak else 0.0
        losses = recent_loss_count(pnl_history)
        if leverage_mode.startswith("adaptive_"):
            leverage, reason, base_leverage = adaptive_leverage_by_mode(
                leverage_mode,
                prototype,
                float(trade.get("breakout_score_quantile", np.nan)),
                float(trade.get("atr_pct_rank", np.nan)),
                drawdown,
                losses,
            )
            audit_rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "trade_id": trade_id,
                "entry_time": trade["entry_time"],
                "base_leverage": base_leverage,
                "final_leverage": leverage,
                "atr_pct": trade.get("atr_pct", np.nan),
                "atr_pct_rank": trade.get("atr_pct_rank", np.nan),
                "equity_drawdown_before_entry": drawdown,
                "recent_3_loss_count": losses,
                "reason": reason,
            })
        else:
            leverage = fixed_leverage_for_mode(leverage_mode)
            reason = leverage_mode
        entry, exit_price = apply_stress_prices(trade, stress)
        liq = shifted_liquidation_price(entry, leverage, stress.liquidation_up_shift)
        min_price = min_trade_price(trade)
        liquidated = min_price <= liq
        risk_event = ""
        if liquidated:
            net_pnl = -equity_before * 0.95
            equity = equity_before * 0.05
            exit_used = liq
            risk_event = "liquidation_price"
        else:
            quantity = equity_before * leverage / entry
            gross = (exit_price - entry) * quantity
            entry_fee = equity_before * leverage * FEE_RATE * stress.fee_mult
            exit_fee = quantity * exit_price * FEE_RATE * stress.fee_mult
            net_pnl = gross - entry_fee - exit_fee
            exit_used = exit_price
            projected_equity = equity_before + net_pnl
            if projected_equity <= equity_before * 0.05:
                liquidated = True
                net_pnl = -equity_before * 0.95
                equity = equity_before * 0.05
                risk_event = "account_floor_after_costs"
            else:
                equity = projected_equity
        pnl_history.append(net_pnl)
        rows.append({
            "symbol": symbol,
            "prototype": prototype,
            "leverage_mode": leverage_mode,
            "stress_case": stress.name,
            "trade_id": trade_id,
            "event_id": trade.get("event_id", ""),
            "entry_time": trade["entry_time"],
            "exit_time": trade["exit_time"],
            "entry_price": entry,
            "exit_price": exit_used,
            "min_trade_price": min_price,
            "liquidation_price": liq,
            "leverage": leverage,
            "net_pnl": net_pnl,
            "trade_return": net_pnl / equity_before if equity_before else np.nan,
            "equity_before": equity_before,
            "equity_after": equity,
            "liquidation": liquidated,
            "risk_event": risk_event,
            "reason": reason,
        })
        equity_rows.append({"time": trade["exit_time"], "equity": equity})
    return pd.DataFrame(rows), pd.DataFrame(equity_rows), pd.DataFrame(audit_rows)


def summarize_leverage(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    final_equity = float(equity["equity"].iloc[-1]) if not equity.empty else INITIAL_BALANCE
    eq = equity["equity"] if not equity.empty else pd.Series([INITIAL_BALANCE])
    return {
        "trade_count": int(len(trades)),
        "total_return": final_equity / INITIAL_BALANCE - 1,
        "annualized_return": np.nan,
        "max_drawdown": max_drawdown(eq),
        "profit_factor": profit_factor(pnl),
        "win_rate": float((pnl > 0).mean()) if len(pnl) else np.nan,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else np.nan,
        "liquidation_count": int(trades["liquidation"].sum()) if "liquidation" in trades else 0,
        "liquidation_rate": float(trades["liquidation"].mean()) if "liquidation" in trades and len(trades) else np.nan,
        "min_equity": float(eq.min()),
        "final_equity": final_equity,
        "top1_profit_contribution": top_profit_contribution(pnl, 1),
        "top3_profit_contribution": top_profit_contribution(pnl, 3),
        "top5_profit_contribution": top_profit_contribution(pnl, 5),
        "longest_drawdown_duration": longest_drawdown_duration(equity.rename(columns={"time": "time", "equity": "equity"})),
    }


def stress_status(summary: dict) -> str:
    if summary["final_equity"] <= INITIAL_BALANCE * 0.1:
        return "account_destroyed"
    if summary["liquidation_count"] > 0:
        return "liquidation_risk"
    if summary["profit_factor"] < 1 or summary["max_drawdown"] < -0.5:
        return "stress_fragile"
    return "stress_pass"


def leverage_decision(summary: pd.DataFrame, stress: pd.DataFrame) -> tuple[str, str]:
    adaptive = summary[summary["leverage_mode"] == "adaptive_10x_20x_v1"]
    eth = adaptive[adaptive["symbol"] == "ETHUSDT"]
    eth_ok = (
        (eth["final_equity"] > summary[(summary["symbol"] == "ETHUSDT") & (summary["leverage_mode"] == "baseline_fixed_2x")]["final_equity"].max())
        & (eth["max_drawdown"] >= -0.35)
        & (eth["liquidation_count"] == 0)
        & (eth["profit_factor"] > 1.2)
    ).any()
    cross = adaptive[adaptive["symbol"].isin(["BTCUSDT", "SOLUSDT", "BNBUSDT"])]
    cross_ok = int((cross["liquidation_count"] == 0).sum()) >= 2 and int((cross["profit_factor"] > 1.1).sum()) >= 2
    stress_ad = stress[stress["leverage_mode"] == "adaptive_10x_20x_v1"]
    critical = stress_ad[stress_ad["stress_case"].isin(["fee_2x", "slippage_2x", "liquidation_price_up_10pct"])]
    stress_ok = critical["liquidation_count"].sum() == 0 if not critical.empty else False
    fixed20_liq = summary[summary["leverage_mode"] == "fixed_20x"]["liquidation_count"].sum() > 0
    adaptive_liq = adaptive["liquidation_count"].sum() > 0
    if eth_ok and cross_ok and stress_ok and fixed20_liq and not adaptive_liq:
        return "A", "adaptive_10x_20x_v1 有明显风险控制价值，可进入 L2"
    if eth_ok and cross_ok and not adaptive_liq:
        return "B", "adaptive 有一定价值，但需要降低杠杆上限"
    if adaptive_liq:
        return "C", "高杠杆收益提高但爆仓风险不可接受"
    return "D", "高杠杆没有优于 2x 的风险调整表现"


def plot_leverage_equity(equity_frames: list[pd.DataFrame], path: Path, kind: str = "equity") -> None:
    plt.figure(figsize=(12, 6))
    for frame in equity_frames:
        if frame.empty:
            continue
        label = f"{frame['symbol'].iloc[0]} {frame['prototype'].iloc[0]} {frame['leverage_mode'].iloc[0]}"
        y = frame["equity"]
        if kind == "drawdown":
            y = y / y.cummax() - 1
        plt.plot(pd.to_datetime(frame["time"], utc=True), y, label=label, linewidth=1)
    plt.legend(fontsize=6)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
