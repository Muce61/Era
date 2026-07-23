from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import polars as pl

from era100x.research.stage_2.contracts.identity import (
    canonical_candidate_identity,
    canonical_candidate_payload_hash,
)
from era100x.research.stage_2.manifests.configuration import research_classification
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import owner_partition

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
    trade_paths: Sequence[Path],
    instrument: Instrument,
    windows: list[dict[str, Any]],
    processing_partition: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not windows:
        return {"flow_features": [], "candidate_attempts": []}
    if not trade_paths:
        raise FileNotFoundError("no Catalog-authorized Stage 1 Trades partitions for Flow windows")
    columns = ["ts_event_ns", "quantity", "aggressor_side", "canonical_trade_id"]
    frames = [pl.read_parquet(path, columns=columns) for path in trade_paths]
    frame = pl.concat(frames).sort(["ts_event_ns", "canonical_trade_id"])
    timestamps = frame["ts_event_ns"].to_list()
    quantities = frame["quantity"].to_list()
    sides = frame["aggressor_side"].to_list()
    import bisect

    features: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
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
        research_role, primary_eligible = research_classification(
            str(window["event_parameter_set_id"]), str(window["time_combination_id"])
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
            "variant_id": "V1_FLOW",
            "time_combination_id": window["time_combination_id"],
            "research_role": research_role,
            "primary_eligible": primary_eligible,
        }
        features.append(feature)
        if passed:
            identity_payload = {
                "variant": "V1_FLOW",
                "instrument": instrument,
                "direction": window["direction"],
                "key_level_id": window["canonical_key_level_id"],
                "sweep_id": window["sweep_id"],
                "reclaim_id": window["reclaim_id"],
                "hold_id": window["hold_id"],
                "price_trigger_id": window["trigger_id"],
                "time_combination_id": window["time_combination_id"],
                "event_parameter_set_id": window["event_parameter_set_id"],
                "available_at_ts": end,
                "stage1_data_run_id": window["data_run_id"],
                "stage1_instrument_logical_hash": window["dataset_logical_hash"],
                "config_hash": window["config_hash"],
                "flow_feature_set_id": feature_id,
            }
            canonical_id = canonical_candidate_identity(identity_payload)
            payload_hash = canonical_candidate_payload_hash(
                {
                    "identity": identity_payload,
                    "market_episode_id": window["market_episode_id"],
                    "venue": window["venue"],
                    "sweep_start_ns": window["sweep_start_ns"],
                    "episode_status": "CANDIDATE",
                    "parent_price_canonical_candidate_id": window["canonical_candidate_id"],
                    "parent_price_payload_hash": window["canonical_payload_hash"],
                    "flow_feature": feature,
                    "variant_id": "V1_FLOW",
                    "research_role": research_role,
                    "primary_eligible": primary_eligible,
                }
            )
            ordinal = len(attempts)
            source_partition = processing_partition or str(
                window.get("owner_partition", owner_partition(end))
            )
            attempts.append(
                {
                    "market_episode_id": window["market_episode_id"],
                    "canonical_candidate_id": canonical_id,
                    "candidate_version_id": canonical_id,
                    "canonical_payload_hash": payload_hash,
                    "instrument": instrument,
                    "direction": window["direction"],
                    "data_run_id": window["data_run_id"],
                    "dataset_logical_hash": window["dataset_logical_hash"],
                    "config_hash": window["config_hash"],
                    "code_version": window["code_version"],
                    "parameter_set_id": window["event_parameter_set_id"],
                    "variant": "V1_FLOW",
                    "variant_id": "V1_FLOW",
                    "available_at_ts": end,
                    "venue": window["venue"],
                    "canonical_key_level_id": window["canonical_key_level_id"],
                    "sweep_id": window["sweep_id"],
                    "reclaim_id": window["reclaim_id"],
                    "hold_id": window["hold_id"],
                    "trigger_id": window["trigger_id"],
                    "flow_feature_set_id": feature_id,
                    "time_combination_id": window["time_combination_id"],
                    "research_role": research_role,
                    "primary_eligible": primary_eligible,
                    "sweep_start_ns": window["sweep_start_ns"],
                    "episode_status": "CANDIDATE",
                    "consumed": False,
                    "consumed_by_intent_id": None,
                    "rearm_eligible_at_ns": None,
                    "event_parameter_set_id": window["event_parameter_set_id"],
                    "source_processing_partition": source_partition,
                    "source_row_ordinal": ordinal,
                    "source_file_logical_path": (
                        f"instrument={instrument}/variant=V1_FLOW/"
                        f"candidate_attempts/date={source_partition}/part-000.parquet"
                    ),
                }
            )
    return {"flow_features": features, "candidate_attempts": attempts}


def _sha(*parts: object) -> str:
    import hashlib

    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
