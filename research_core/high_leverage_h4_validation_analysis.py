"""H4 OOS, holdout cross-asset, and finer-path validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import END_UTC
from research_core.cross_asset_validation_analysis import audit_symbol_data, default_symbol_paths
from research_core.high_leverage_gate_analysis import (
    H3_LEVERAGE_MODES,
    enrich_trades_with_gate_metadata,
    gate_mask_fixed,
    high_risk_mask_fixed,
    simulate_gate_leverage_path,
)
from research_core.leverage_research_analysis import STRESS_CASES, stress_status, summarize_leverage
from research_core.minimal_backtest_analysis import BacktestParams


DISCOVERY_SYMBOLS = {"ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"}
DISCOVERY_END = pd.Timestamp(END_UTC)
MIN_OOS_DAYS = 90
MIN_HOLDOUT_SYMBOLS = 3
HOLDOUT_PRIORITY_SYMBOLS = [
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "DOTUSDT",
    "TRXUSDT",
    "OPUSDT",
    "ARBUSDT",
]
H4_PROTOTYPES = ["P4_BREAKOUT_TOP20", "P6_MOMENTUM_OR_BREAKOUT_TOP20"]
H4_GATES = ["G0_NO_PATH_GATE", "G1_SINGLE_BEST_PATH_SAFETY", "G2_CONSENSUS_TWO_FACTORS", "G4_RISK_MONITOR_DOWNSHIFT"]
H4_LEVERAGE_MODES = ["fixed_10x", "fixed_20x", "adaptive_3x_8x_v1", "adaptive_4x_10x_v1", "adaptive_5x_12x_v1"]


@dataclass(frozen=True)
class H4DataDecision:
    status: str
    primary_layer: str
    time_oos_symbols: tuple[str, ...]
    holdout_symbols: tuple[str, ...]
    finer_data_available: bool
    reason: str


def validate_oos_no_overlap(frame: pd.DataFrame, discovery_end: pd.Timestamp = DISCOVERY_END) -> bool:
    ts = pd.to_datetime(frame["timestamp"] if "timestamp" in frame.columns else frame.index, utc=True, errors="coerce")
    return bool((ts > discovery_end).all())


def oos_coverage_days(frame: pd.DataFrame, discovery_end: pd.Timestamp = DISCOVERY_END) -> float:
    ts = pd.to_datetime(frame["timestamp"] if "timestamp" in frame.columns else frame.index, utc=True, errors="coerce")
    ts = ts[ts > discovery_end].dropna().sort_values()
    if ts.empty:
        return 0.0
    return float((ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400)


def is_time_oos_sufficient(frame: pd.DataFrame, min_days: int = MIN_OOS_DAYS) -> bool:
    return validate_oos_no_overlap(frame) and oos_coverage_days(frame) >= min_days


def is_holdout_symbol(symbol: str) -> bool:
    return symbol.upper() not in DISCOVERY_SYMBOLS


def holdout_sample_status(symbols: list[str], min_symbols: int = MIN_HOLDOUT_SYMBOLS) -> str:
    unique = sorted({s.upper() for s in symbols if is_holdout_symbol(s)})
    return "valid" if len(unique) >= min_symbols else "insufficient_sample"


def discover_symbol_files(symbols: list[str] = HOLDOUT_PRIORITY_SYMBOLS) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        paths = default_symbol_paths(symbol)
        existing = [p for p in paths if p.exists()]
        rows.append({
            "symbol": symbol,
            "is_discovery_symbol": symbol in DISCOVERY_SYMBOLS,
            "path_count": len(existing),
            "paths": "|".join(str(p) for p in existing),
            "candidate_layer": "cross_asset_holdout" if symbol not in DISCOVERY_SYMBOLS and existing else "unavailable",
        })
    return pd.DataFrame(rows)


def choose_holdout_symbols(inventory: pd.DataFrame, max_symbols: int = 5) -> list[str]:
    available = inventory[
        (inventory["candidate_layer"] == "cross_asset_holdout")
        & (~inventory["is_discovery_symbol"].astype(bool))
        & (inventory["path_count"] >= 1)
    ]["symbol"].tolist()
    return available[:max_symbols]


def compare_finer_liquidation(row: pd.Series) -> dict:
    hit_1m = bool(row["low_1m"] <= row["liquidation_price"])
    hit_finer = bool(row["low_finer"] <= row["liquidation_price"])
    entry = float(row["entry_price"])
    mae_1m = float(row["low_1m"] / entry - 1.0)
    mae_finer = float(row["low_finer"] / entry - 1.0)
    return {
        "hit_liq_1m": hit_1m,
        "hit_liq_finer": hit_finer,
        "mae_1m_pct": mae_1m,
        "mae_finer_pct": mae_finer,
        "finer_worse_than_1m": bool(mae_finer < mae_1m),
        "audit_status": "finer_found_extra_liquidation" if hit_finer and not hit_1m else "matched_or_better",
    }


def risk_retention_status(h3: pd.Series, h4: pd.Series) -> str:
    if int(h4.get("trade_count", 0)) < 30:
        return "insufficient_h4_sample"
    if int(h4.get("liquidation_count", 0)) > int(h3.get("liquidation_count", 0)):
        return "risk_control_failed"
    if float(h4.get("max_drawdown", 0)) < -0.45:
        return "risk_control_failed"
    if float(h4.get("profit_factor", 0)) >= 1.2 and int(h4.get("liquidation_count", 0)) == 0:
        return "risk_control_confirmed"
    return "risk_control_weakened"


def validation_status(summary: dict) -> str:
    if int(summary.get("trade_count", 0)) < 30:
        return "insufficient_sample"
    if int(summary.get("liquidation_count", 0)) > 0:
        return "validation_fail"
    if float(summary.get("profit_factor", 0)) > 1.2 and float(summary.get("max_drawdown", 0)) >= -0.35:
        return "validation_pass"
    if float(summary.get("profit_factor", 0)) > 1.0 and float(summary.get("max_drawdown", 0)) >= -0.45:
        return "validation_weak"
    return "validation_fail"


def final_h4_decision(has_time_oos: bool, holdout_status: str, has_finer: bool, validation: pd.DataFrame) -> tuple[str, str]:
    if validation.empty:
        return "E", "数据不足，无法判断"
    if has_time_oos and (validation["validation_status"] == "validation_pass").any():
        return "A", "time OOS 支持 H3，可进入 H5 模拟盘观察准备"
    if not has_time_oos and holdout_status in {"cross_asset_holdout_pass", "cross_asset_holdout_weak"}:
        return "B", "无 time OOS，但 cross_asset_holdout / finer path 部分支持，可继续等待 OOS"
    if not has_time_oos and holdout_status == "cross_asset_holdout_fail":
        return "C", "新验证层显示风险控制明显衰减"
    if has_finer and (validation["validation_status"] == "validation_fail").any():
        return "D", "H3 gate 在新验证中失败，应停止高杠杆策略化"
    return "E", "数据不足，无法判断"


def discovery_percentile(values: pd.Series, discovery_values: pd.Series) -> pd.Series:
    base = np.sort(pd.to_numeric(discovery_values, errors="coerce").dropna().to_numpy(float))
    current = pd.to_numeric(values, errors="coerce").to_numpy(float)
    if len(base) == 0:
        return pd.Series(np.nan, index=values.index)
    ranks = np.searchsorted(base, current, side="right") / len(base)
    ranks[~np.isfinite(current)] = np.nan
    return pd.Series(ranks, index=values.index)


def build_holdout_gate_events(
    events: pd.DataFrame,
    scores: pd.DataFrame,
    gate_factors: pd.DataFrame,
    discovery_scores: pd.DataFrame,
) -> pd.DataFrame:
    base = events.merge(scores[["event_id", "momentum_score", "breakout_score"]], on="event_id", how="left")
    base["momentum_score_quantile"] = discovery_percentile(
        base["momentum_score"],
        discovery_scores["momentum_continuation_score"],
    )
    base["breakout_score_quantile"] = discovery_percentile(
        base["breakout_score"],
        discovery_scores["breakout_conviction_score"],
    )
    base["gate_threshold_source"] = "fixed_h3_discovery_thresholds"
    return base


def gate_assignments_for_symbol(events: pd.DataFrame, gate_factors: pd.DataFrame, gate_thresholds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for prototype in H4_PROTOTYPES:
        part = events[events["prototype"] == prototype].copy()
        if part.empty:
            continue
        for gate in H4_GATES:
            if gate == "G2_CONSENSUS_TWO_FACTORS" and prototype != "P6_MOMENTUM_OR_BREAKOUT_TOP20":
                continue
            mask, status = gate_mask_fixed(part, gate_factors, gate_thresholds, prototype, gate)
            rows.extend({
                "data_layer": part.iloc[i]["data_layer"],
                "symbol": part.iloc[i]["symbol"],
                "event_id": part.iloc[i]["event_id"],
                "prototype": prototype,
                "gate": gate,
                "leverage_mode_eligible": "|".join(H4_LEVERAGE_MODES),
                "gate_status": status,
                "accepted": bool(mask.iloc[i]),
            } for i in range(len(part)))
    return pd.DataFrame(rows)


def h4_gate_backtest_symbol(
    data_layer: str,
    symbol: str,
    trades: pd.DataFrame,
    events: pd.DataFrame,
    gate_factors: pd.DataFrame,
    gate_thresholds: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    stress_rows = []
    liquidations = []
    audit_rows = []
    equity_frames = []
    for prototype in H4_PROTOTYPES:
        event_part = events[(events["symbol"] == symbol) & (events["prototype"] == prototype)].reset_index(drop=True)
        trade_part = trades[(trades["symbol"] == symbol) & (trades["prototype"] == prototype) & (trades["sizing_mode"] == "fixed_2x")].copy()
        if event_part.empty or trade_part.empty:
            continue
        high_risk = high_risk_mask_fixed(event_part, gate_factors, gate_thresholds, prototype)
        event_with_risk = event_part.assign(gate_high_risk=high_risk)
        enriched_all = enrich_trades_with_gate_metadata(trade_part, event_with_risk)
        for gate in H4_GATES:
            if gate == "G2_CONSENSUS_TWO_FACTORS" and prototype != "P6_MOMENTUM_OR_BREAKOUT_TOP20":
                continue
            mask, gate_status = gate_mask_fixed(event_part, gate_factors, gate_thresholds, prototype, gate)
            accepted = set(event_part.loc[mask, "event_id"].astype(str))
            if gate == "G4_RISK_MONITOR_DOWNSHIFT":
                enriched = enriched_all.copy()
                risk_map = event_with_risk.set_index("event_id")["gate_high_risk"].to_dict()
                enriched["gate_high_risk"] = enriched["event_id"].map(risk_map).fillna(False)
            else:
                enriched = enriched_all[enriched_all["event_id"].astype(str).isin(accepted)].copy()
            for leverage_mode in H4_LEVERAGE_MODES:
                sim, equity, audit = simulate_gate_leverage_path(enriched, symbol, prototype, gate, leverage_mode)
                summary = summarize_leverage(sim, equity)
                summary_rows.append({
                    "data_layer": data_layer,
                    "symbol": symbol,
                    "prototype": prototype,
                    "gate": gate,
                    "leverage_mode": leverage_mode,
                    **summary,
                    "stress_liquidation_cases": 0,
                    "validation_status": validation_status(summary),
                })
                equity_frames.append(equity.assign(data_layer=data_layer, symbol=symbol, prototype=prototype, gate=gate, leverage_mode=leverage_mode))
                if not sim.empty:
                    sim = sim.assign(data_layer=data_layer)
                    liq = sim[sim["liquidation"]].copy()
                    if not liq.empty:
                        liquidations.append(liq)
                if not audit.empty:
                    audit_rows.append(audit.assign(data_layer=data_layer))
                for stress in STRESS_CASES:
                    if stress.name == "base":
                        continue
                    stress_sim, stress_equity, _ = simulate_gate_leverage_path(enriched, symbol, prototype, gate, leverage_mode, stress=stress)
                    stress_summary = summarize_leverage(stress_sim, stress_equity)
                    stress_rows.append({
                        "data_layer": data_layer,
                        "symbol": symbol,
                        "prototype": prototype,
                        "gate": gate,
                        "leverage_mode": leverage_mode,
                        "stress_case": stress.name,
                        "trade_count": stress_summary["trade_count"],
                        "total_return": stress_summary["total_return"],
                        "max_drawdown": stress_summary["max_drawdown"],
                        "profit_factor": stress_summary["profit_factor"],
                        "liquidation_count": stress_summary["liquidation_count"],
                        "final_equity": stress_summary["final_equity"],
                        "stress_status": stress_status(stress_summary),
                    })
    summary = pd.DataFrame(summary_rows)
    stress = pd.DataFrame(stress_rows)
    if not summary.empty and not stress.empty:
        critical = stress[stress["stress_case"].isin(["fee_2x", "slippage_2x", "liquidation_price_up_10pct"])]
        stress_liq = critical.groupby(["data_layer", "symbol", "prototype", "gate", "leverage_mode"])["liquidation_count"].sum().reset_index(name="stress_liquidation_cases")
        summary = summary.drop(columns=["stress_liquidation_cases"]).merge(stress_liq, on=["data_layer", "symbol", "prototype", "gate", "leverage_mode"], how="left")
        summary["stress_liquidation_cases"] = summary["stress_liquidation_cases"].fillna(0).astype(int)
    return (
        summary,
        stress,
        pd.concat(liquidations, ignore_index=True) if liquidations else pd.DataFrame(),
        pd.concat(audit_rows, ignore_index=True) if audit_rows else pd.DataFrame(),
        pd.concat(equity_frames, ignore_index=True) if equity_frames else pd.DataFrame(),
    )


def holdout_asset_decision(summary: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if summary.empty:
        return pd.DataFrame(), "cross_asset_holdout_fail"
    candidate = summary[summary["leverage_mode"].str.startswith("adaptive_")].copy()
    by_symbol = candidate.groupby("symbol").agg(
        best_profit_factor=("profit_factor", "max"),
        min_liquidation_count=("liquidation_count", "min"),
        worst_max_drawdown=("max_drawdown", "min"),
        best_validation=("validation_status", lambda s: "validation_pass" if (s == "validation_pass").any() else "validation_weak" if (s == "validation_weak").any() else "validation_fail"),
    ).reset_index()
    no_liq = int((by_symbol["min_liquidation_count"] == 0).sum())
    pf_ok = int((by_symbol["best_profit_factor"] > 1.1).sum())
    dd_ok = bool((by_symbol["worst_max_drawdown"] >= -0.45).all()) if not by_symbol.empty else False
    if len(by_symbol) >= 3 and no_liq >= 2 and pf_ok >= 2 and dd_ok:
        status = "cross_asset_holdout_pass"
    elif len(by_symbol) >= 3 and no_liq >= 2:
        status = "cross_asset_holdout_weak"
    else:
        status = "cross_asset_holdout_fail"
    by_symbol["holdout_status"] = status
    return by_symbol, status


def h3_vs_h4_comparison(h3_summary: pd.DataFrame, h4_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    h3 = h3_summary.set_index(["symbol", "prototype", "gate", "leverage_mode"])
    for _, row in h4_summary.iterrows():
        key = (row["symbol"], row["prototype"], row["gate"], row["leverage_mode"])
        if key in h3.index:
            base = h3.loc[key]
        else:
            base = pd.Series(dtype=object)
        status = risk_retention_status(base, row) if not base.empty else "insufficient_h4_sample"
        rows.append({
            "data_layer": row["data_layer"],
            "symbol": row["symbol"],
            "prototype": row["prototype"],
            "gate": row["gate"],
            "leverage_mode": row["leverage_mode"],
            "h3_trade_count": base.get("trade_count", np.nan),
            "h4_trade_count": row.get("trade_count", np.nan),
            "h3_profit_factor": base.get("profit_factor", np.nan),
            "h4_profit_factor": row.get("profit_factor", np.nan),
            "h3_max_drawdown": base.get("max_drawdown", np.nan),
            "h4_max_drawdown": row.get("max_drawdown", np.nan),
            "h3_liquidation_count": base.get("liquidation_count", np.nan),
            "h4_liquidation_count": row.get("liquidation_count", np.nan),
            "h3_stress_liquidation_cases": np.nan,
            "h4_stress_liquidation_cases": row.get("stress_liquidation_cases", np.nan),
            "risk_retention_status": status,
        })
    return pd.DataFrame(rows)


def audit_holdout_symbol(symbol: str, data: pd.DataFrame) -> dict:
    report = audit_symbol_data(symbol, data)
    report["data_layer"] = "cross_asset_holdout"
    report["quality_status"] = "pass" if report["invalid_ohlc_count"] == 0 and report["duplicate_timestamp_count"] == 0 else "fail"
    return report
