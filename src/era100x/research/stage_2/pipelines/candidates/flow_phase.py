from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import polars as pl

Instrument = Literal["BTCUSDT", "ETHUSDT"]
SECOND_NS = 1_000_000_000
UNAVAILABLE_FIELDS = [
    "bid",
    "ask",
    "spread",
    "ts_recv",
    "l2_depth",
    "queue_position",
    "actual_partial_fill",
    "actual_slippage",
    "private_order_flow",
]


def build_flow_day(
    *,
    stage1_trades_root: Path,
    instrument: Instrument,
    day: date,
    windows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    path = stage1_trades_root / instrument / f"date={day.isoformat()}" / "part-000.parquet"
    if not path.exists():
        raise FileNotFoundError(f"missing published Stage 1 Trades partition: {path}")
    frame = pl.read_parquet(
        path, columns=["ts_event_ns", "quantity", "aggressor_side", "canonical_trade_id"]
    ).sort(["ts_event_ns", "canonical_trade_id"])
    timestamps = frame["ts_event_ns"].to_list()
    quantities = frame["quantity"].to_list()
    sides = frame["aggressor_side"].to_list()
    import bisect

    features: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    for window in windows:
        start = int(window["window_start_ts"])
        end = int(window["window_end_ts"])
        left = bisect.bisect_left(timestamps, start)
        right = bisect.bisect_left(timestamps, end)
        buy = Decimal(0)
        sell = Decimal(0)
        latest = 0
        for index in range(left, right):
            quantity = Decimal(str(quantities[index]))
            if sides[index] == "BUY":
                buy += quantity
            elif sides[index] == "SELL":
                sell += quantity
            if timestamps[index] >= end - SECOND_NS:
                latest += 1
        total = buy + sell
        previous_mean = Decimal((right - left) - latest) / Decimal(4)
        imbalance = None if total == 0 else (buy - sell) / total
        passed = imbalance is not None and imbalance > 0 and Decimal(latest) > previous_mean
        feature_id = _sha(
            "flow-feature-set-v1",
            instrument,
            window["trigger_id"],
            start,
            end,
            window["event_parameter_set_id"],
        )
        feature = {
            "flow_feature_set_id": feature_id,
            "instrument": instrument,
            "window_start_ts": start,
            "window_end_ts": end,
            "buy_quantity": str(buy),
            "sell_quantity": str(sell),
            "signed_quantity_imbalance": None if imbalance is None else str(imbalance),
            "latest_1s_trade_count": latest,
            "previous_4s_per_second_mean": str(previous_mean),
            "status": "PASS" if passed else ("UNAVAILABLE" if total == 0 else "REJECTED"),
            "unavailable_fields": UNAVAILABLE_FIELDS,
            "reason_code": "FLOW_CONFIRMED"
            if passed
            else ("FLOW_TRADES_UNAVAILABLE" if total == 0 else "FLOW_THRESHOLD_NOT_MET"),
            "market_episode_id": window["market_episode_id"],
            "event_parameter_set_id": window["event_parameter_set_id"],
        }
        features.append(feature)
        if passed:
            episodes.append(
                {
                    "market_episode_id": window["market_episode_id"],
                    "candidate_version_id": _sha(
                        "candidate-version-v1-flow",
                        window["candidate_version_id"],
                        feature_id,
                    ),
                    "instrument": instrument,
                    "variant": "V1_FLOW",
                    "available_at_ts": end,
                    "flow_feature_set_id": feature_id,
                    "event_parameter_set_id": window["event_parameter_set_id"],
                    "episode_status": "CANDIDATE",
                    "consumed": False,
                }
            )
    return {"flow_features": features, "market_episodes": episodes}


def _sha(*parts: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
