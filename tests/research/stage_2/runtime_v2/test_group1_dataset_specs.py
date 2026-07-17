from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from era100x.research.stage_2.contracts.models import (
    CandidateInclusionRecord,
    CanonicalKeyLevel,
    HoldEvent,
    MarketEpisode,
    PriceTriggerFact,
    RawKeyLevel,
    ReclaimEvent,
    SweepEpisode,
)
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    finalize_candidate_attempts,
)
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.runtime_v2.dataset_specs import group1_dataset_binding
from era100x.research.stage_2.runtime_v2.group1_adapter import prepare_group1_partition

DAY_START = 1_577_836_800_000_000_000
SNAPSHOT = "a" * 64


def _field_names(variant: str, dataset: str) -> set[str]:
    return {field.name for field in group1_dataset_binding(variant, dataset).spec.fields}


def _price_attempt() -> dict[str, object]:
    candidate_id = "1" * 64
    return {
        "instrument": "BTCUSDT",
        "data_run_id": "stage1",
        "dataset_logical_hash": "a" * 64,
        "config_hash": "b" * 64,
        "code_version": "abcdef0",
        "parameter_set_id": "G1-PRIMARY-V1",
        "available_at_ts": DAY_START + 10_000_000_000,
        "market_episode_id": "c" * 64,
        "canonical_candidate_id": candidate_id,
        "candidate_version_id": candidate_id,
        "canonical_payload_hash": "2" * 64,
        "venue": "BINANCE_USDM",
        "direction": "LONG",
        "canonical_key_level_id": "d" * 64,
        "sweep_id": "e" * 64,
        "reclaim_id": "f" * 64,
        "hold_id": "0" * 64,
        "trigger_id": "3" * 64,
        "flow_feature_set_id": None,
        "variant": "V1_PRICE",
        "variant_id": "V1_PRICE",
        "time_combination_id": "T2",
        "research_role": "PRIMARY",
        "primary_eligible": True,
        "sweep_start_ns": DAY_START,
        "episode_status": "CANDIDATE",
        "consumed": False,
        "consumed_by_intent_id": None,
        "rearm_eligible_at_ns": None,
        "event_parameter_set_id": "G1-PRIMARY-V1",
        "trigger_available_at_ts": DAY_START + 10_000_000_000,
        "window_start_ts": DAY_START + 5_000_000_000,
        "window_end_ts": DAY_START + 10_000_000_000,
        "source_processing_partition": "2020-01-01",
        "source_row_ordinal": 0,
        "source_file_logical_path": (
            "instrument=BTCUSDT/variant=V1_PRICE/candidate_attempts/"
            "date=2020-01-01/part-000.parquet"
        ),
    }


def test_specs_track_the_exact_approved_pydantic_record_fields() -> None:
    assert _field_names("V1_PRICE", "raw_key_levels") == set(RawKeyLevel.model_fields)
    assert _field_names("V1_PRICE", "canonical_key_levels") == {
        *CanonicalKeyLevel.model_fields,
        "event_parameter_set_id",
    }
    assert _field_names("V1_PRICE", "sweeps") == {
        *SweepEpisode.model_fields,
        "event_parameter_set_id",
    }
    assert _field_names("V1_PRICE", "reclaims") == {
        *ReclaimEvent.model_fields,
        "event_parameter_set_id",
    }
    assert _field_names("V1_PRICE", "holds") == {
        *HoldEvent.model_fields,
        "event_parameter_set_id",
    }
    assert _field_names("V1_PRICE", "price_triggers") == {
        *PriceTriggerFact.model_fields,
        "event_parameter_set_id",
    }
    assert _field_names("V1_PRICE", "market_episodes") == set(MarketEpisode.model_fields)
    assert _field_names("V1_FLOW", "market_episodes") == set(MarketEpisode.model_fields)
    assert _field_names("V1_PRICE", "candidate_inclusion") == {
        *CandidateInclusionRecord.model_fields,
        "owner_partition",
    }


def test_finalizer_and_flow_outputs_match_specs_and_prepare_for_v2(tmp_path: Path) -> None:
    price = finalize_candidate_attempts([_price_attempt()])
    owner = "2020-01-01"
    episode = price.market_episodes_by_date[owner][0]
    inclusion = price.inclusion_by_date[owner][0]
    window = price.flow_windows_by_date[owner][0]
    assert set(episode) == _field_names("V1_PRICE", "market_episodes")
    assert set(inclusion) == _field_names("V1_PRICE", "candidate_inclusion")
    assert set(window) == _field_names("V1_PRICE", "flow_windows")

    trade_path = tmp_path / "part-000.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [DAY_START + 9_000_000_000],
            "quantity": ["1"],
            "aggressor_side": ["BUY"],
            "canonical_trade_id": ["trade-1"],
        }
    ).write_parquet(trade_path)
    flow = build_flow_day(
        trade_paths=(trade_path,),
        instrument="BTCUSDT",
        windows=[window],
        processing_partition=owner,
    )
    feature = flow["flow_features"][0]
    assert set(feature) == _field_names("V1_FLOW", "flow_features")
    finalized_flow = finalize_candidate_attempts(
        flow["candidate_attempts"], include_flow_windows=False
    )
    flow_episode = finalized_flow.market_episodes_by_date[owner][0]
    flow_inclusion = finalized_flow.inclusion_by_date[owner][0]
    assert set(flow_episode) == _field_names("V1_FLOW", "market_episodes")
    assert set(flow_inclusion) == _field_names("V1_FLOW", "candidate_inclusion")

    for variant, dataset, records in (
        ("V1_PRICE", "market_episodes", [episode]),
        ("V1_PRICE", "candidate_inclusion", [inclusion]),
        ("V1_PRICE", "flow_windows", [window]),
        ("V1_FLOW", "flow_features", [feature]),
        ("V1_FLOW", "market_episodes", [flow_episode]),
        ("V1_FLOW", "candidate_inclusion", [flow_inclusion]),
    ):
        prepared = prepare_group1_partition(
            snapshot_id=SNAPSHOT,
            instrument="BTCUSDT",
            variant=variant,
            dataset=dataset,
            owner_date=date(2020, 1, 1),
            records=records,
        )
        assert prepared.row_count == 1
