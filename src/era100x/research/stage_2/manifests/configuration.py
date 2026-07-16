"""Approved Stage 2 Group 1 parameter and preregistration construction."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import ParameterSet, TimeConfiguration, canonical_json, sha256_text


def timing_configurations() -> tuple[TimeConfiguration, ...]:
    return (
        TimeConfiguration(
            timing_id="T1",
            role="EXPLORATORY_SENSITIVITY",
            reclaim_timeout_seconds=15,
            hold_window_seconds=15,
            first_passage_horizon_seconds=60,
        ),
        TimeConfiguration(
            timing_id="T2",
            role="PRIMARY",
            reclaim_timeout_seconds=30,
            hold_window_seconds=30,
            first_passage_horizon_seconds=180,
        ),
        TimeConfiguration(
            timing_id="T3",
            role="EXPLORATORY_SENSITIVITY",
            reclaim_timeout_seconds=60,
            hold_window_seconds=30,
            first_passage_horizon_seconds=300,
        ),
        TimeConfiguration(
            timing_id="T4",
            role="EXPLORATORY_SENSITIVITY",
            reclaim_timeout_seconds=60,
            hold_window_seconds=60,
            first_passage_horizon_seconds=600,
        ),
    )


def parameter_sets() -> tuple[ParameterSet, ...]:
    base: dict[str, Any] = {
        "parameter_set_version": "1.0",
        "status": "RESEARCH",
        "timing_id": "T2",
        "merge_tolerance_bps": Decimal("10"),
        "minimum_episode_gap_seconds": 300,
        "rearm_above_level_seconds": 900,
        "sweep_confirmation_bps": Decimal("2"),
        "reclaim_buffer_bps": Decimal("1"),
        "hold_failure_buffer_bps": Decimal("1"),
    }
    axes: list[tuple[str, str, object]] = [
        ("PRIMARY", "PRIMARY", "T2"),
        ("TIMING_T1", "timing_id", "T1"),
        ("TIMING_T3", "timing_id", "T3"),
        ("TIMING_T4", "timing_id", "T4"),
        ("MERGE_5", "merge_tolerance_bps", Decimal("5")),
        ("MERGE_15", "merge_tolerance_bps", Decimal("15")),
        ("GAP_60", "minimum_episode_gap_seconds", 60),
        ("GAP_900", "minimum_episode_gap_seconds", 900),
        ("REARM_300", "rearm_above_level_seconds", 300),
        ("REARM_1800", "rearm_above_level_seconds", 1800),
        ("SWEEP_5", "sweep_confirmation_bps", Decimal("5")),
        ("SWEEP_10", "sweep_confirmation_bps", Decimal("10")),
        ("SWEEP_15", "sweep_confirmation_bps", Decimal("15")),
        ("SWEEP_25", "sweep_confirmation_bps", Decimal("25")),
        ("RECLAIM_0", "reclaim_buffer_bps", Decimal("0")),
        ("RECLAIM_2", "reclaim_buffer_bps", Decimal("2")),
        ("RECLAIM_3", "reclaim_buffer_bps", Decimal("3")),
        ("HOLD_0", "hold_failure_buffer_bps", Decimal("0")),
        ("HOLD_2", "hold_failure_buffer_bps", Decimal("2")),
        ("HOLD_3", "hold_failure_buffer_bps", Decimal("3")),
    ]
    result: list[ParameterSet] = []
    for name, field, value in axes:
        values = dict(base)
        values["parameter_set_id"] = f"G1-{name}-V1"
        values["changed_axis"] = field
        if field != "PRIMARY":
            values[field] = value
        if name == "PRIMARY":
            values["status"] = "BASELINE"
        result.append(ParameterSet.model_validate(values))
    return tuple(result)


def config_hash() -> str:
    payload = {
        "timing_configurations": [
            item.model_dump(mode="python") for item in timing_configurations()
        ],
        "parameter_sets": [item.model_dump(mode="python") for item in parameter_sets()],
        "g1": "closed_1h_close_vs_causal_ema20_up_only",
        "g3": "first_strict_positive_1s_and_5s_within_30s_no_new_structural_low",
        "g4": "trades_[t-5s,t)_positive_signed_qty_and_count_acceleration",
        "market_episode_identity": "sha256(venue|instrument|canonical_key_level_id|sweep_start_ns)",
    }
    return sha256_text(canonical_json(payload))
