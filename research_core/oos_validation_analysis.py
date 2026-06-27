"""R9 OOS data discovery and validation helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research_core.common import END_UTC
from research_core.family_validation_analysis import FAMILY_FACTORS, compute_family_score


DISCOVERY_END = pd.Timestamp(END_UTC)
MIN_OOS_DAYS = 90
OOS_PROTOTYPES = [
    "P1_C1_FIRST_BREAKOUT",
    "P2_STRONG_BREAKOUT",
    "P3_MOMENTUM_TOP20",
    "P4_BREAKOUT_TOP20",
    "P5_MOMENTUM_AND_BREAKOUT_TOP40",
    "P6_MOMENTUM_OR_BREAKOUT_TOP20",
]


def candidate_csv_paths(search_roots: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            name = path.name.lower()
            if "ethusdt" in name and "funding" not in name and "metrics" not in name:
                paths.append(path)
    return sorted(set(paths))


def read_timestamp_column(path: Path) -> tuple[str | None, pd.Series]:
    try:
        cols = pd.read_csv(path, nrows=0).columns.tolist()
    except Exception:
        return None, pd.Series(dtype="datetime64[ns, UTC]")
    candidates = [c for c in cols if c.lower() in {"timestamp", "open_time", "time", "date", "datetime"}]
    if not candidates:
        candidates = [cols[0]] if cols else []
    if not candidates:
        return None, pd.Series(dtype="datetime64[ns, UTC]")
    tcol = candidates[0]
    try:
        raw = pd.read_csv(path, usecols=[tcol])[tcol]
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        return tcol, ts.dropna()
    except Exception:
        return tcol, pd.Series(dtype="datetime64[ns, UTC]")


def build_data_inventory(paths: list[Path], discovery_end: pd.Timestamp = DISCOVERY_END) -> pd.DataFrame:
    rows = []
    for path in paths:
        tcol, ts = read_timestamp_column(path)
        row = {
            "path": str(path),
            "timestamp_column": tcol or "",
            "row_count": int(len(ts)),
            "start_utc": "",
            "end_utc": "",
            "has_rows_after_discovery_end": False,
            "oos_rows_after_discovery_end": 0,
            "oos_start_utc": "",
            "oos_end_utc": "",
            "oos_coverage_days": 0.0,
            "candidate_status": "unreadable_or_no_timestamp",
        }
        if not ts.empty:
            ts = ts.sort_values()
            oos = ts[ts > discovery_end]
            row.update({
                "start_utc": ts.iloc[0].isoformat(),
                "end_utc": ts.iloc[-1].isoformat(),
                "has_rows_after_discovery_end": bool(not oos.empty),
                "oos_rows_after_discovery_end": int(len(oos)),
                "candidate_status": "has_oos_rows" if not oos.empty else "no_oos_rows",
            })
            if not oos.empty:
                row.update({
                    "oos_start_utc": oos.iloc[0].isoformat(),
                    "oos_end_utc": oos.iloc[-1].isoformat(),
                    "oos_coverage_days": float((oos.iloc[-1] - oos.iloc[0]).total_seconds() / 86400),
                })
        rows.append(row)
    return pd.DataFrame(rows)


def load_ohlcv_candidate(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp"])[required].sort_values("timestamp")


def missing_ranges(ts: pd.Series) -> pd.DataFrame:
    if ts.empty:
        return pd.DataFrame(columns=["missing_start", "missing_end", "missing_minutes"])
    ordered = pd.Series(pd.to_datetime(ts, utc=True)).dropna().drop_duplicates().sort_values()
    diffs = ordered.diff()
    rows = []
    gaps = diffs[diffs > pd.Timedelta(minutes=1)]
    for idx, diff in gaps.items():
        end = ordered.loc[idx]
        start = ordered.shift(1).loc[idx]
        rows.append({
            "missing_start": (start + pd.Timedelta(minutes=1)).isoformat(),
            "missing_end": (end - pd.Timedelta(minutes=1)).isoformat(),
            "missing_minutes": int(diff / pd.Timedelta(minutes=1) - 1),
        })
    return pd.DataFrame(rows)


def audit_ohlcv(path: Path, discovery_end: pd.Timestamp = DISCOVERY_END) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = load_ohlcv_candidate(path)
    oos = df[df["timestamp"] > discovery_end].copy()
    duplicate_rows = oos[oos["timestamp"].duplicated(keep=False)]
    invalid = oos[
        (oos["low"] > oos[["open", "close"]].min(axis=1))
        | (oos["high"] < oos[["open", "close"]].max(axis=1))
        | (oos[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (oos["volume"] < 0)
    ]
    ret = oos["close"].pct_change().abs()
    outlier_rows = oos[ret > 0.10]
    missing = missing_ranges(oos["timestamp"])
    coverage_days = 0.0 if oos.empty else float((oos["timestamp"].max() - oos["timestamp"].min()).total_seconds() / 86400)
    report = {
        "path": str(path),
        "full_start_utc": df["timestamp"].min().isoformat() if not df.empty else "",
        "full_end_utc": df["timestamp"].max().isoformat() if not df.empty else "",
        "oos_start_utc": oos["timestamp"].min().isoformat() if not oos.empty else "",
        "oos_end_utc": oos["timestamp"].max().isoformat() if not oos.empty else "",
        "oos_row_count": int(len(oos)),
        "oos_coverage_days": coverage_days,
        "timestamp_utc_assumed": True,
        "monotonic_increasing": bool(oos["timestamp"].is_monotonic_increasing),
        "duplicate_timestamp_count": int(len(duplicate_rows)),
        "missing_range_count": int(len(missing)),
        "missing_minute_count": int(missing["missing_minutes"].sum()) if not missing.empty else 0,
        "invalid_ohlc_count": int(len(invalid)),
        "outlier_count": int(len(outlier_rows)),
        "overlaps_discovery": bool((df["timestamp"] <= discovery_end).any() and (df["timestamp"] > discovery_end).any()),
        "coverage_status": "sufficient" if coverage_days >= MIN_OOS_DAYS else "insufficient",
    }
    return report, missing, duplicate_rows, invalid, outlier_rows


def coverage_decision(inventory: pd.DataFrame, min_days: int = MIN_OOS_DAYS) -> dict:
    if inventory.empty or not inventory["has_rows_after_discovery_end"].any():
        return {
            "status": "blocked",
            "reason": "oos_data_unavailable",
            "best_path": "",
            "coverage_days": 0.0,
            "conclusion": "E. OOS 数据不足，无法判断",
        }
    best = inventory.sort_values("oos_coverage_days", ascending=False).iloc[0]
    days = float(best["oos_coverage_days"])
    return {
        "status": "success" if days >= min_days else "blocked",
        "reason": "sufficient_oos_data" if days >= min_days else "oos_data_unavailable_or_insufficient",
        "best_path": str(best["path"]),
        "coverage_days": days,
        "oos_start_utc": str(best["oos_start_utc"]),
        "oos_end_utc": str(best["oos_end_utc"]),
        "conclusion": "pending_full_oos_validation" if days >= min_days else "E. OOS 数据不足，无法判断",
    }


def validate_no_discovery_overlap(oos: pd.DataFrame, discovery_end: pd.Timestamp = DISCOVERY_END) -> bool:
    if "timestamp" in oos.columns:
        ts = pd.to_datetime(oos["timestamp"], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(oos.index, utc=True, errors="coerce")
    return bool((ts > discovery_end).all())


def transform_oos_scores(oos_events: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """Transform OOS scores using discovery-fitted R6 metadata only."""
    out = oos_events[["event_id", "signal_time", "execution_time"]].copy()
    for family, factors in FAMILY_FACTORS.items():
        params = metadata[metadata["family"] == family]
        available = [f for f in factors if f in oos_events.columns]
        score = compute_family_score(oos_events, available, params)
        short = "momentum" if family == "momentum_continuation" else "breakout"
        out[f"{family}_score"] = score
        out[f"{short}_score"] = score
    return out


def discovery_score_thresholds(discovery_scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for short, col in [("momentum", "momentum_continuation_score"), ("breakout", "breakout_conviction_score")]:
        rows.append({"score": short, "quantile": 0.60, "threshold": float(discovery_scores[col].quantile(0.60))})
        rows.append({"score": short, "quantile": 0.80, "threshold": float(discovery_scores[col].quantile(0.80))})
    return pd.DataFrame(rows)


def oos_prototype_masks(oos_scores: pd.DataFrame, events: pd.DataFrame, thresholds: pd.DataFrame) -> dict[str, pd.Series]:
    t = thresholds.set_index(["score", "quantile"])["threshold"]
    momentum = pd.to_numeric(oos_scores["momentum_score"], errors="coerce")
    breakout = pd.to_numeric(oos_scores["breakout_score"], errors="coerce")
    c1 = events["first_breakout_after_flat"].fillna(False).astype(bool)
    strong = events["strong_breakout"].fillna(False).astype(bool)
    return {
        "P1_C1_FIRST_BREAKOUT": c1,
        "P2_STRONG_BREAKOUT": strong,
        "P3_MOMENTUM_TOP20": momentum >= t.loc[("momentum", 0.80)],
        "P4_BREAKOUT_TOP20": breakout >= t.loc[("breakout", 0.80)],
        "P5_MOMENTUM_AND_BREAKOUT_TOP40": (momentum >= t.loc[("momentum", 0.60)]) & (breakout >= t.loc[("breakout", 0.60)]),
        "P6_MOMENTUM_OR_BREAKOUT_TOP20": (momentum >= t.loc[("momentum", 0.80)]) | (breakout >= t.loc[("breakout", 0.80)]),
    }


def retention_status(discovery: pd.Series, oos: pd.Series) -> str:
    if int(oos.get("trade_count", 0)) < 30:
        return "insufficient_oos_sample"
    if oos.get("total_return", 0) <= 0 or oos.get("profit_factor", 0) <= 1:
        return "oos_failed"
    pf_retention = oos.get("profit_factor", np.nan) / discovery.get("profit_factor", np.nan)
    if pd.notna(pf_retention) and pf_retention >= 0.5:
        return "oos_confirmed"
    return "oos_weakened"


def discovery_vs_oos_comparison(discovery_summary: pd.DataFrame, oos_summary: pd.DataFrame) -> pd.DataFrame:
    d = discovery_summary[discovery_summary["sizing_mode"] == "fixed_2x"].set_index("prototype")
    o = oos_summary[oos_summary["sizing_mode"] == "fixed_2x"].set_index("prototype")
    rows = []
    for prototype in OOS_PROTOTYPES:
        if prototype not in d.index or prototype not in o.index:
            continue
        dr = d.loc[prototype]
        oo = o.loc[prototype]
        rows.append({
            "prototype": prototype,
            "discovery_trade_count": int(dr["trade_count"]),
            "oos_trade_count": int(oo["trade_count"]),
            "discovery_total_return": float(dr["total_return"]),
            "oos_total_return": float(oo["total_return"]),
            "discovery_profit_factor": float(dr["profit_factor"]),
            "oos_profit_factor": float(oo["profit_factor"]),
            "discovery_max_drawdown": float(dr["max_drawdown"]),
            "oos_max_drawdown": float(oo["max_drawdown"]),
            "discovery_win_rate": float(dr["win_rate"]),
            "oos_win_rate": float(oo["win_rate"]),
            "discovery_top1_contribution": float(dr["top1_profit_contribution"]),
            "oos_top1_contribution": float(oo["top1_profit_contribution"]),
            "performance_retention_ratio": float(oo["total_return"] / dr["total_return"]) if dr["total_return"] else np.nan,
            "pf_retention_ratio": float(oo["profit_factor"] / dr["profit_factor"]) if dr["profit_factor"] else np.nan,
            "oos_status": retention_status(dr, oo),
        })
    return pd.DataFrame(rows)
