"""S2.5 IDLE_MR1 state-breakdown helpers.

This stage is descriptive event research only. It does not create a trading
strategy or change P4 rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import RESEARCH_ROOT
from research_core.event_table import add_base_indicators, load_ohlcv_1m, strict_resample_15m


CANONICAL_S2_DIR = RESEARCH_ROOT / "second_alpha_source_s2"
TEMP_S2_DIR = Path("/tmp/Era_s2/research_core/second_alpha_source_s2")
DATA_ROOT_1Y = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
START_UTC = pd.Timestamp("2024-12-01 00:00:00+00:00")
END_UTC = pd.Timestamp("2026-06-28 01:05:00+00:00")
IDLE_CANDIDATE = "IDLE_MR1_P4_IDLE_REVERSION"
RANDOM_SEED = 20260624


@dataclass(frozen=True)
class S2Source:
    path: Path
    source_status: str


def resolve_s2_source() -> S2Source:
    if (CANONICAL_S2_DIR / "candidate_event_table.parquet").exists():
        return S2Source(CANONICAL_S2_DIR, "canonical")
    if (TEMP_S2_DIR / "candidate_event_table.parquet").exists():
        return S2Source(TEMP_S2_DIR, "temp_run_not_canonical")
    raise FileNotFoundError("S2 event table not found in canonical or /tmp/Era_s2 paths")


def load_idle_events(source: S2Source) -> pd.DataFrame:
    events = pd.read_parquet(source.path / "candidate_event_table.parquet")
    idle = events[events["candidate"] == IDLE_CANDIDATE].copy()
    if idle.empty:
        return idle
    for col in ["signal_time", "execution_time"]:
        idle[col] = pd.to_datetime(idle[col], utc=True)
    return idle.sort_values(["symbol", "signal_time", "event_id"]).reset_index(drop=True)


def simulate_p4_phase(data_1m: pd.DataFrame) -> pd.DataFrame:
    """Simulate P4 held state and post-exit phase on close-labeled 15m bars.

    Phase labels use only the current and past bars. A true "before breakout"
    label would require future knowledge, so this function only emits it when
    the current bar already satisfies the P4 entry condition and the position
    has not yet been marked held. Normal idle bars before an unknown future
    breakout remain deep_idle/unknown by design.
    """
    bars = add_base_indicators(strict_resample_15m(data_1m))
    p4_entry = (bars["close"] > bars["donchian55_upper"]) & (bars["ema50"] > bars["ema200"]) & bars["atr14"].notna()
    p4_exit = bars["close"] < bars["donchian20_lower"]
    held = False
    last_exit_loc: int | None = None
    rows = []
    for loc, (ts, row) in enumerate(bars.iterrows()):
        entry_now = bool(p4_entry.iloc[loc])
        exit_now = bool(p4_exit.iloc[loc])
        phase = "unknown"
        held_before = held
        if held:
            phase = "p4_held"
            if exit_now:
                held = False
                last_exit_loc = loc
                phase = "after_p4_exit_0_4_bars"
        else:
            if last_exit_loc is not None:
                bars_after_exit = loc - last_exit_loc
                if bars_after_exit <= 4:
                    phase = "after_p4_exit_0_4_bars"
                elif bars_after_exit <= 16:
                    phase = "after_p4_exit_5_16_bars"
                elif bars_after_exit <= 64:
                    phase = "after_p4_exit_17_64_bars"
                else:
                    phase = "deep_idle"
            elif entry_now:
                phase = "before_p4_breakout"
            else:
                phase = "deep_idle"
            if entry_now:
                held = True
        rows.append({
            "signal_time": ts,
            "p4_held": bool(held_before),
            "p4_entry_condition": entry_now,
            "p4_exit_condition": exit_now,
            "p4_phase": phase,
            "bars_since_p4_exit": (loc - last_exit_loc) if last_exit_loc is not None else np.nan,
        })
    return pd.DataFrame(rows).set_index("signal_time")


def attach_p4_phase(events: pd.DataFrame, data_root: Path = DATA_ROOT_1Y) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    enriched = []
    for symbol, part in events.groupby("symbol", sort=False):
        data_path = data_root / f"{symbol}.csv"
        if not data_path.exists():
            tmp = part.copy()
            tmp["p4_phase"] = "unknown"
            tmp["p4_held"] = np.nan
            enriched.append(tmp)
            continue
        data = load_ohlcv_1m(data_path)
        data = data[(data.index >= START_UTC) & (data.index <= END_UTC)].copy()
        phase = simulate_p4_phase(data)
        tmp = part.copy()
        tmp = tmp.merge(
            phase.reset_index()[["signal_time", "p4_phase", "p4_held", "bars_since_p4_exit"]],
            on="signal_time",
            how="left",
        )
        tmp["p4_phase"] = tmp["p4_phase"].fillna("unknown")
        enriched.append(tmp)
    return pd.concat(enriched, ignore_index=True)


def top_positive_contribution(values: pd.Series, n: int) -> float:
    positives = values.dropna().sort_values(ascending=False)
    positives = positives[positives > 0]
    total = positives.sum()
    return float(positives.head(n).sum() / total) if total > 0 else np.nan


def breakdown(events: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    if events.empty:
        return pd.DataFrame()
    for keys, part in events.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update({
            "event_count": int(len(part)),
            "mean_fwd_ret_1": part["fwd_ret_1"].mean(),
            "mean_fwd_ret_4": part["fwd_ret_4"].mean(),
            "mean_fwd_ret_8": part["fwd_ret_8"].mean(),
            "mean_fwd_ret_16": part["fwd_ret_16"].mean(),
            "mean_fwd_ret_32": part["fwd_ret_32"].mean(),
            "plus_1atr_first_rate_16": part["plus_1atr_first_16"].mean(),
            "minus_1atr_first_rate_16": part["minus_1atr_first_16"].mean(),
            "mean_mae_16": part["fwd_mae_16"].mean(),
            "mean_mfe_16": part["fwd_mfe_16"].mean(),
            "top1_positive_contribution": top_positive_contribution(part["fwd_ret_16"], 1),
            "remove_top3_mean_fwd_ret": part["fwd_ret_16"].sort_values(ascending=False).iloc[3:].mean() if len(part) > 3 else np.nan,
        })
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def add_time_buckets(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    out["month"] = out["signal_time"].dt.to_period("M").astype(str)
    out["quarter"] = out["signal_time"].dt.to_period("Q").astype(str)
    return out


def add_trend_strength_bucket(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    out["trend_strength_bucket"] = pd.cut(
        out["trend_strength_atr"],
        bins=[-np.inf, 0.5, 1.0, 1.5, 2.5, np.inf],
        labels=["0_0.5", "0.5_1.0", "1.0_1.5", "1.5_2.5", "gt_2.5"],
    ).astype("object").fillna("unknown")
    return out


def failure_case_sample(events: pd.DataFrame, seed: int = RANDOM_SEED) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    cols = [
        "event_id",
        "symbol",
        "side",
        "signal_time",
        "execution_time",
        "execution_open",
        "p4_phase",
        "trend_strength_atr",
        "volatility_regime",
        "deviation_ema20_atr",
        "fwd_ret_16",
        "fwd_mae_16",
        "fwd_mfe_16",
        "plus_1atr_first_16",
        "minus_1atr_first_16",
        "subsequent_trend_breakout",
    ]
    worst_ret = events.nsmallest(20, "fwd_ret_16").assign(sample_reason="worst_return")
    worst_mae = events.nsmallest(20, "fwd_mae_16").assign(sample_reason="worst_mae")
    minus = events[events["minus_1atr_first_16"] == True]  # noqa: E712
    minus_sample = minus.sample(n=min(50, len(minus)), random_state=seed).assign(sample_reason="minus_1atr_random")
    sample = pd.concat([worst_ret, worst_mae, minus_sample], ignore_index=True)
    return sample[["sample_reason", *cols]].reset_index(drop=True)


def random_baseline_diagnostics(events: pd.DataFrame) -> pd.DataFrame:
    """Diagnostic matched baseline for IDLE_MR1 using event table only.

    This is not a replacement for a full market-time random baseline; it is a
    transparency report showing whether event-level matching is narrow or
    fallback-heavy.
    """
    rows = []
    if events.empty:
        return pd.DataFrame()
    work = add_time_buckets(events)
    work["trend_bucket"] = pd.cut(
        work["trend_strength_atr"].fillna(0),
        [-np.inf, 1, 2, 3, np.inf],
        labels=["t0", "t1", "t2", "t3"],
    ).astype("object")
    work["vol_bucket"] = work["volatility_regime"].astype(str)
    primary_cols = ["symbol", "side", "month", "vol_bucket", "trend_bucket", "p4_phase"]
    fallback_cols = ["symbol", "side", "vol_bucket", "p4_phase"]
    primary_sizes = work.groupby(primary_cols, observed=True).size().to_dict()
    fallback_sizes = work.groupby(fallback_cols, observed=True).size().to_dict()
    groups = {
        "overall": work,
        **{f"symbol:{k}": v for k, v in work.groupby("symbol")},
        **{f"side:{k}": v for k, v in work.groupby("side")},
        **{f"p4_phase:{k}": v for k, v in work.groupby("p4_phase")},
    }
    for name, part in groups.items():
        matched = 0
        fallback = 0
        unmatched = 0
        for _, event in part.iterrows():
            pkey = tuple(event[col] for col in primary_cols)
            fkey = tuple(event[col] for col in fallback_cols)
            if primary_sizes.get(pkey, 0) > 1:
                matched += 1
            elif fallback_sizes.get(fkey, 0) > 1:
                fallback += 1
            else:
                unmatched += 1
        rows.append({
            "group": name,
            "event_count": int(len(part)),
            "matched_sample_count": int(matched + fallback),
            "unmatched_event_count": int(unmatched),
            "fallback_match_rate": float(fallback / len(part)) if len(part) else np.nan,
            "observed_mean": float(part["fwd_ret_16"].mean()) if len(part) else np.nan,
            "baseline_mean": np.nan,
            "percentile": np.nan,
            "note": "diagnostic only; baseline values require full market-state pool",
        })
    return pd.DataFrame(rows)


def hypothesis_summary(direction: pd.DataFrame, symbol: pd.DataFrame, phase: pd.DataFrame, vol: pd.DataFrame, trend: pd.DataFrame) -> pd.DataFrame:
    rows = []
    candidates = []
    for name, frame, key in [
        ("side", direction, "side"),
        ("symbol", symbol, "symbol"),
        ("p4_phase", phase, "p4_phase"),
        ("volatility", vol, "volatility_regime"),
        ("trend_strength", trend, "trend_strength_bucket"),
    ]:
        if frame.empty:
            continue
        best = frame.sort_values("mean_fwd_ret_16", ascending=False).head(1).iloc[0]
        candidates.append((name, best[key], float(best["mean_fwd_ret_16"]), int(best["event_count"])))
    for name, value, edge, count in candidates:
        rows.append({
            "dimension": name,
            "best_bucket": value,
            "event_count": count,
            "mean_fwd_ret_16": edge,
            "hypothesis_status": "weak_positive_bucket" if edge > 0 and count >= 50 else "no_positive_bucket",
        })
    return pd.DataFrame(rows)


def blocked_strategy_summary() -> pd.DataFrame:
    return pd.DataFrame([{
        "status": "blocked_event_research_only",
        "data_layer": "expanded_discovery",
        "oos_status": "not_oos",
        "deployable_strategy_generated": False,
        "reason": "S2.5 is descriptive state breakdown only; no strategy backtest is allowed",
    }])
