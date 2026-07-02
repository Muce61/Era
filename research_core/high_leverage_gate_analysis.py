"""H3 high-leverage path-safety gate helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.leverage_research_analysis import (
    INITIAL_BALANCE,
    L2_LEVERAGE_MODES,
    STRESS_CASES,
    StressConfig,
    apply_stress_prices,
    fixed_leverage_for_mode,
    min_trade_price,
    plot_leverage_equity,
    recent_loss_count,
    shifted_liquidation_price,
    stress_status,
    summarize_leverage,
    adaptive_leverage_by_mode,
    FEE_RATE,
    TARGET_PROTOTYPES,
)


H3_LEVERAGE_MODES = [
    "fixed_10x",
    "fixed_20x",
    "adaptive_3x_8x_v1",
    "adaptive_4x_10x_v1",
    "adaptive_5x_12x_v1",
]
H3_GATES = [
    "G0_NO_PATH_GATE",
    "G1_SINGLE_BEST_PATH_SAFETY",
    "G2_CONSENSUS_TWO_FACTORS",
    "G3_STRICT_CONSENSUS",
    "G4_RISK_MONITOR_DOWNSHIFT",
]
SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]


def unique_event_labels(labels: pd.DataFrame) -> pd.DataFrame:
    frame = labels.copy()
    if "forward_window" in frame.columns and (frame["forward_window"] == "60m").any():
        frame = frame[frame["forward_window"] == "60m"].copy()
    sort_cols = [c for c in ["symbol", "prototype", "event_id", "forward_minutes"] if c in frame.columns]
    if sort_cols:
        frame = frame.sort_values(sort_cols)
    return frame.drop_duplicates(["symbol", "prototype", "event_id"], keep="last").reset_index(drop=True)


def eligible_factors(
    decision: pd.DataFrame,
    role: pd.DataFrame,
    boot: pd.DataFrame,
    stress: pd.DataFrame,
    horizon: pd.DataFrame,
    failure: pd.DataFrame,
) -> pd.DataFrame:
    candidates = decision[
        (decision["decision_status"] == "candidate_for_H3_prototype")
        & (decision["allowed_next_step"] == "H3_minimal_gate_prototype")
    ].copy()
    rows = []
    for _, candidate in candidates.iterrows():
        factor = candidate["factor"]
        prototype = candidate["prototype"]
        role_part = role[
            (role["factor"] == factor)
            & (role["prototype"] == prototype)
            & (role["factor_role"].isin(["path_safety_only", "dual_use_candidate"]))
        ]
        boot_ok = ((boot["factor"] == factor) & (boot["prototype"] == prototype) & (boot["bootstrap_status"] == "robust_path_safety_candidate")).any()
        stress_ok = ((stress["factor"] == factor) & (stress["prototype"] == prototype) & (stress["stress_status"] == "stress_pass")).any()
        hrow = horizon[(horizon["factor"] == factor) & (horizon["prototype"] == prototype)]
        horizon_ok = not hrow.empty and hrow.iloc[0]["window_role"] not in ["invalid_or_sparse", "window_reversal"]
        frow = failure[(failure["factor"] == factor) & (failure["prototype"] == prototype)]
        failure_status = frow.iloc[0]["explainability_status"] if not frow.empty else "invalid_or_sparse"
        failure_ok = failure_status in ["explains_failures", "weak_explanation"]
        if role_part.empty or not (boot_ok and stress_ok and horizon_ok and failure_ok):
            continue
        best = role_part.sort_values(["safe20_edge", "event_count"], ascending=[False, False]).iloc[0]
        rows.append({
            "factor": factor,
            "prototype": prototype,
            "best_window": best["forward_window"],
            "safe20_edge": float(best["safe20_edge"]),
            "factor_role": best["factor_role"],
            "failure_explainability": failure_status,
            "window_role": hrow.iloc[0]["window_role"],
            "rank_score": float(best["safe20_edge"]) + float(frow.iloc[0].get("lift", 0) if not frow.empty else 0) / 100.0,
        })
    if not rows:
        return pd.DataFrame(columns=["factor", "prototype", "best_window", "safe20_edge", "rank_score"])
    return pd.DataFrame(rows).sort_values(["prototype", "rank_score"], ascending=[True, False]).reset_index(drop=True)


def factor_ranks(events: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    out = events.copy()
    for factor in factors:
        if factor in out.columns:
            out[f"{factor}__rank"] = out.groupby(["symbol", "prototype"])[factor].rank(method="first", pct=True)
    return out


def factor_is_high_safe(factors: pd.DataFrame, prototype: str, factor: str) -> bool:
    part = factors[(factors["prototype"] == prototype) & (factors["factor"] == factor)]
    if part.empty:
        return True
    return float(part.iloc[0]["safe20_edge"]) >= 0


def safe_mask_for_factor(events: pd.DataFrame, factors: pd.DataFrame, prototype: str, factor: str, keep_fraction: float) -> pd.Series:
    rank_col = f"{factor}__rank"
    if rank_col not in events.columns:
        return pd.Series(False, index=events.index)
    ranks = events[rank_col]
    if factor_is_high_safe(factors, prototype, factor):
        return ranks > (1.0 - keep_fraction)
    return ranks < keep_fraction


def build_fixed_gate_thresholds(discovery_events: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in factors.iterrows():
        prototype = row["prototype"]
        factor = row["factor"]
        if factor not in discovery_events.columns:
            continue
        values = pd.to_numeric(
            discovery_events.loc[discovery_events["prototype"] == prototype, factor],
            errors="coerce",
        ).dropna()
        high_safe = factor_is_high_safe(factors, prototype, factor)
        for keep_fraction in [0.60, 0.70]:
            quantile = 1.0 - keep_fraction if high_safe else keep_fraction
            threshold = float(values.quantile(quantile)) if len(values) else np.nan
            rows.append({
                "prototype": prototype,
                "factor": factor,
                "keep_fraction": keep_fraction,
                "threshold_quantile": quantile,
                "threshold": threshold,
                "safe_direction": "high" if high_safe else "low",
                "source_event_count": int(len(values)),
                "source_data_layer": "h3_discovery_core_symbols",
            })
    return pd.DataFrame(rows)


def safe_mask_for_factor_fixed(
    events: pd.DataFrame,
    thresholds: pd.DataFrame,
    prototype: str,
    factor: str,
    keep_fraction: float,
) -> pd.Series:
    if factor not in events.columns:
        return pd.Series(False, index=events.index)
    part = thresholds[
        (thresholds["prototype"] == prototype)
        & (thresholds["factor"] == factor)
        & (np.isclose(thresholds["keep_fraction"].astype(float), keep_fraction))
    ]
    if part.empty or not np.isfinite(float(part.iloc[0]["threshold"])):
        return pd.Series(False, index=events.index)
    threshold = float(part.iloc[0]["threshold"])
    values = pd.to_numeric(events[factor], errors="coerce")
    if part.iloc[0]["safe_direction"] == "high":
        return values > threshold
    return values < threshold


def gate_mask_fixed(
    events: pd.DataFrame,
    factors: pd.DataFrame,
    thresholds: pd.DataFrame,
    prototype: str,
    gate: str,
) -> tuple[pd.Series, str]:
    proto_factors = factors[factors["prototype"] == prototype]["factor"].tolist()
    if gate == "G0_NO_PATH_GATE" or gate == "G4_RISK_MONITOR_DOWNSHIFT":
        return pd.Series(True, index=events.index), "usable"
    if gate == "G1_SINGLE_BEST_PATH_SAFETY":
        if len(proto_factors) < 1:
            return pd.Series(False, index=events.index), "gate_unavailable"
        return safe_mask_for_factor_fixed(events, thresholds, prototype, proto_factors[0], 0.60), "usable"
    if gate == "G2_CONSENSUS_TWO_FACTORS":
        if len(proto_factors) < 2:
            return pd.Series(False, index=events.index), "gate_unavailable"
        mask = pd.Series(True, index=events.index)
        for factor in proto_factors[:2]:
            mask &= safe_mask_for_factor_fixed(events, thresholds, prototype, factor, 0.70)
        return mask, "usable"
    if gate == "G3_STRICT_CONSENSUS":
        if len(proto_factors) < 3:
            return pd.Series(False, index=events.index), "gate_unavailable"
        masks = [safe_mask_for_factor_fixed(events, thresholds, prototype, factor, 0.60) for factor in proto_factors[:3]]
        return (sum(m.astype(int) for m in masks) >= 2), "usable"
    raise ValueError(f"Unknown gate: {gate}")


def high_risk_mask_fixed(events: pd.DataFrame, factors: pd.DataFrame, thresholds: pd.DataFrame, prototype: str) -> pd.Series:
    proto_factors = factors[factors["prototype"] == prototype]["factor"].tolist()
    if not proto_factors:
        return pd.Series(False, index=events.index)
    safe, _ = gate_mask_fixed(events, factors, thresholds, prototype, "G1_SINGLE_BEST_PATH_SAFETY")
    return ~safe


def gate_mask(events: pd.DataFrame, factors: pd.DataFrame, prototype: str, gate: str) -> tuple[pd.Series, str]:
    proto_factors = factors[factors["prototype"] == prototype]["factor"].tolist()
    if gate == "G0_NO_PATH_GATE" or gate == "G4_RISK_MONITOR_DOWNSHIFT":
        return pd.Series(True, index=events.index), "usable"
    if gate == "G1_SINGLE_BEST_PATH_SAFETY":
        if len(proto_factors) < 1:
            return pd.Series(False, index=events.index), "gate_unavailable"
        return safe_mask_for_factor(events, factors, prototype, proto_factors[0], 0.60), "usable"
    if gate == "G2_CONSENSUS_TWO_FACTORS":
        if len(proto_factors) < 2:
            return pd.Series(False, index=events.index), "gate_unavailable"
        mask = pd.Series(True, index=events.index)
        for factor in proto_factors[:2]:
            mask &= safe_mask_for_factor(events, factors, prototype, factor, 0.70)
        return mask, "usable"
    if gate == "G3_STRICT_CONSENSUS":
        if len(proto_factors) < 3:
            return pd.Series(False, index=events.index), "gate_unavailable"
        masks = [safe_mask_for_factor(events, factors, prototype, factor, 0.60) for factor in proto_factors[:3]]
        return (sum(m.astype(int) for m in masks) >= 2), "usable"
    raise ValueError(f"Unknown gate: {gate}")


def high_risk_mask(events: pd.DataFrame, factors: pd.DataFrame, prototype: str) -> pd.Series:
    proto_factors = factors[factors["prototype"] == prototype]["factor"].tolist()
    if not proto_factors:
        return pd.Series(False, index=events.index)
    safe, _ = gate_mask(events, factors, prototype, "G1_SINGLE_BEST_PATH_SAFETY")
    return ~safe


def coverage_status(gate: str, available: str, acceptance_rate: float) -> str:
    if available == "gate_unavailable":
        return "gate_unavailable"
    if gate == "G4_RISK_MONITOR_DOWNSHIFT":
        return "usable"
    if acceptance_rate < 0.25:
        return "too_restrictive"
    if gate != "G0_NO_PATH_GATE" and acceptance_rate > 0.95:
        return "too_loose"
    return "usable"


def load_h3_trade_inputs(repo_root: Path) -> dict[tuple[str, str], pd.DataFrame]:
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


def enrich_trades_with_gate_metadata(trades: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "symbol",
        "prototype",
        "event_id",
        "atr_pct",
        "atr_pct_rank",
        "breakout_score_quantile",
        "momentum_score_quantile",
    ]
    rank_cols = [c for c in events.columns if c.endswith("__rank")]
    return trades.merge(events[[c for c in cols + rank_cols if c in events.columns]], on=["symbol", "prototype", "event_id"], how="left")


def downshift_leverage(leverage_mode: str, leverage: float, high_risk: bool) -> tuple[float, str]:
    if not high_risk:
        return leverage, "path_gate_not_high_risk"
    if leverage_mode == "fixed_10x":
        return 5.0, "g4_fixed_10x_to_5x"
    if leverage_mode == "fixed_20x":
        return 8.0, "g4_fixed_20x_to_8x"
    if leverage_mode == "adaptive_3x_8x_v1":
        return min(leverage, 4.0), "g4_adaptive_cap_50pct"
    if leverage_mode == "adaptive_4x_10x_v1":
        return min(leverage, 5.0), "g4_adaptive_cap_50pct"
    if leverage_mode == "adaptive_5x_12x_v1":
        return min(leverage, 6.0), "g4_adaptive_cap_50pct"
    return leverage, "path_gate_no_downshift_rule"


def simulate_gate_leverage_path(
    trades: pd.DataFrame,
    symbol: str,
    prototype: str,
    gate: str,
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
        else:
            leverage = fixed_leverage_for_mode(leverage_mode)
            reason = leverage_mode
            base_leverage = leverage
        if gate == "G4_RISK_MONITOR_DOWNSHIFT":
            leverage, gate_reason = downshift_leverage(leverage_mode, leverage, bool(trade.get("gate_high_risk", False)))
            reason = f"{reason}|{gate_reason}"
        audit_rows.append({
            "symbol": symbol,
            "prototype": prototype,
            "gate": gate,
            "trade_id": trade_id,
            "entry_time": trade["entry_time"],
            "leverage_mode": leverage_mode,
            "base_leverage": base_leverage,
            "final_leverage": leverage,
            "gate_high_risk": bool(trade.get("gate_high_risk", False)),
            "atr_pct": trade.get("atr_pct", np.nan),
            "atr_pct_rank": trade.get("atr_pct_rank", np.nan),
            "equity_drawdown_before_entry": drawdown,
            "recent_3_loss_count": losses,
            "reason": reason,
        })
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
            "gate": gate,
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


def risk_reduction_status(base: pd.Series, gated: pd.Series) -> str:
    if int(gated.get("trade_count", 0)) < 30:
        return "insufficient_sample"
    liq_reduced = int(gated.get("liquidation_count", 0)) < int(base.get("liquidation_count", 0))
    dd_improved = float(gated.get("max_drawdown", np.nan)) > float(base.get("max_drawdown", np.nan))
    pf_ok = float(gated.get("profit_factor", np.nan)) >= max(1.0, float(base.get("profit_factor", 0)) * 0.75)
    ret_ok = float(gated.get("total_return", np.nan)) >= float(base.get("total_return", 0)) * 0.35
    if (liq_reduced or dd_improved) and pf_ok and ret_ok:
        return "clear_risk_reduction"
    if (liq_reduced or dd_improved) and not ret_ok:
        return "return_too_damaged"
    if float(gated.get("profit_factor", np.nan)) < float(base.get("profit_factor", np.nan)) and not liq_reduced and not dd_improved:
        return "worse_than_base"
    return "no_risk_reduction"


def h3_decision_status(row: pd.Series, stress_liq: int, acceptance_rate: float, cross_ok: bool) -> tuple[str, str]:
    if row.get("gate") in ["G2_CONSENSUS_TWO_FACTORS", "G3_STRICT_CONSENSUS"] and row.get("trade_count", 0) == 0:
        return "gate_unavailable", "discard"
    if acceptance_rate < 0.25 or row["trade_count"] < 50:
        return "too_restrictive", "needs_more_data"
    eth_ok = (
        row["symbol"] == "ETHUSDT"
        and row["trade_count"] >= 50
        and row["profit_factor"] > 1.3
        and row["max_drawdown"] >= -0.35
        and row["liquidation_count"] == 0
    )
    stress_ok = stress_liq == 0
    if eth_ok and cross_ok and stress_ok:
        return "candidate_for_H4_oos_or_finer_data_validation", "H4_new_data_or_1s_validation"
    if row["liquidation_count"] == 0 and row["profit_factor"] > 1.0 and stress_ok:
        return "risk_monitor_only", "keep_as_risk_monitor"
    if row["liquidation_count"] > 0 or stress_liq > 0:
        return "unsafe_high_leverage", "discard"
    return "discard_for_now", "discard"


def build_incremental(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keyed = summary.set_index(["symbol", "prototype", "leverage_mode", "gate"])
    for (symbol, prototype, leverage_mode), part in summary.groupby(["symbol", "prototype", "leverage_mode"]):
        if (symbol, prototype, leverage_mode, "G0_NO_PATH_GATE") not in keyed.index:
            continue
        base = keyed.loc[(symbol, prototype, leverage_mode, "G0_NO_PATH_GATE")]
        for gate in ["G1_SINGLE_BEST_PATH_SAFETY", "G2_CONSENSUS_TWO_FACTORS", "G3_STRICT_CONSENSUS", "G4_RISK_MONITOR_DOWNSHIFT"]:
            if (symbol, prototype, leverage_mode, gate) not in keyed.index:
                rows.append({
                    "symbol": symbol,
                    "prototype": prototype,
                    "leverage_mode": leverage_mode,
                    "gate": gate,
                    "base_gate": "G0_NO_PATH_GATE",
                    "risk_reduction_status": "gate_unavailable",
                })
                continue
            gated = keyed.loc[(symbol, prototype, leverage_mode, gate)]
            unavailable = str(gated.get("coverage_status", "")) == "gate_unavailable"
            rows.append({
                "symbol": symbol,
                "prototype": prototype,
                "leverage_mode": leverage_mode,
                "gate": gate,
                "base_gate": "G0_NO_PATH_GATE",
                "base_trade_count": int(base["trade_count"]),
                "gate_trade_count": int(gated["trade_count"]),
                "trade_count_change": int(gated["trade_count"]) - int(base["trade_count"]),
                "base_total_return": float(base["total_return"]),
                "gate_total_return": float(gated["total_return"]),
                "return_change": float(gated["total_return"]) - float(base["total_return"]),
                "base_max_drawdown": float(base["max_drawdown"]),
                "gate_max_drawdown": float(gated["max_drawdown"]),
                "drawdown_improvement": float(gated["max_drawdown"]) - float(base["max_drawdown"]),
                "base_liquidation_count": int(base["liquidation_count"]),
                "gate_liquidation_count": int(gated["liquidation_count"]),
                "liquidation_reduction": int(base["liquidation_count"]) - int(gated["liquidation_count"]),
                "base_profit_factor": float(base["profit_factor"]),
                "gate_profit_factor": float(gated["profit_factor"]),
                "pf_change": float(gated["profit_factor"]) - float(base["profit_factor"]),
                "risk_reduction_status": "gate_unavailable" if unavailable else risk_reduction_status(base, gated),
            })
    return pd.DataFrame(rows)


def write_h3_report(
    factors: pd.DataFrame,
    coverage: pd.DataFrame,
    summary: pd.DataFrame,
    incremental: pd.DataFrame,
    stress: pd.DataFrame,
    decision: pd.DataFrame,
    final_code: str,
    final_text: str,
) -> str:
    liq_by_gate = summary.groupby(["gate", "leverage_mode"])["liquidation_count"].sum().reset_index()
    stress_counts = stress.groupby(["gate", "leverage_mode", "stress_status"]).size().reset_index(name="count")
    candidates = decision[decision["decision_status"] == "candidate_for_H4_oos_or_finer_data_validation"]
    lines = [
        "# H3 High Leverage Gate Report",
        "",
        "branch: codex/adaptive-leverage-10x-20x",
        "data_layer: high_leverage_research",
        "oos_status: not_oos",
        "simulation_approval: not_allowed",
        "",
        "This stage keeps P4/P6 alpha unchanged and tests path-safety gate behavior only.",
        "",
        "## H2 Gate Factors",
        "",
        factors.to_markdown(index=False) if not factors.empty else "No eligible H2 path-safety factors.",
        "",
        "## Coverage",
        "",
        coverage.to_markdown(index=False),
        "",
        "## Leverage Summary",
        "",
        summary.to_markdown(index=False),
        "",
        "## Liquidation By Gate",
        "",
        liq_by_gate.to_markdown(index=False),
        "",
        "## Incremental Risk Reduction",
        "",
        incremental.to_markdown(index=False),
        "",
        "## Stress Counts",
        "",
        stress_counts.to_markdown(index=False) if not stress_counts.empty else "unavailable",
        "",
        "## H4 Candidates",
        "",
        candidates.to_markdown(index=False) if not candidates.empty else "none",
        "",
        "## Required Answers",
        "",
        f"1. H2 因子是否足以构建高杠杆准入：{'yes' if not factors.empty else 'no'}，但是否通过以 decision summary 为准。",
        "2. G1/G2/G3 哪个降低风险最明显：见 gate_incremental_risk_reduction.csv 的 liquidation_reduction 和 drawdown_improvement。",
        "3. G4 risk monitor 是否比直接过滤更好：比较 G4 与 G1/G2/G3 的 return_change、liquidation_reduction 和 stress_status。",
        "4. fixed_10x 是否可接受：见 fixed_10x 的 H3 decision_status。",
        "5. fixed_20x 是否仍不可接受：见 fixed_20x 的 liquidation_count 与压力测试。",
        "6. adaptive_3x_8x / 4x_10x / 5x_12x 哪个最稳：按 liquidation_count、max_drawdown、stress_liquidation_cases 排序。",
        "7. ETH 上是否可行：见 ETHUSDT rows in h3_decision_summary.csv。",
        "8. BTC/SOL/BNB 横向是否支持：见 cross symbols 的 liquidation_count、PF、max_drawdown。",
        "9. 高杠杆失败是 alpha 问题还是路径安全问题：本阶段只证明 gate 是否能改善路径风险；不改变 alpha。",
        f"10. 是否允许进入 H4：{not candidates.empty}。",
        "",
        f"## Final Decision\n\n{final_code}. {final_text}",
        "",
        "## Guardrails",
        "",
        "- no alpha rule changed",
        "- path safety gate research only",
        "- not OOS",
        "- no deployable strategy rule generated",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "H3_GATES",
    "H3_LEVERAGE_MODES",
    "SYMBOLS",
    "eligible_factors",
    "factor_ranks",
    "build_fixed_gate_thresholds",
    "gate_mask_fixed",
    "gate_mask",
    "high_risk_mask_fixed",
    "high_risk_mask",
    "coverage_status",
    "load_h3_trade_inputs",
    "enrich_trades_with_gate_metadata",
    "downshift_leverage",
    "simulate_gate_leverage_path",
    "build_incremental",
    "h3_decision_status",
    "plot_leverage_equity",
    "write_h3_report",
]
