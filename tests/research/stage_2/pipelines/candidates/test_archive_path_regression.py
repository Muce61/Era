from __future__ import annotations

from pathlib import Path

import polars as pl

from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day


def test_flow_reader_uses_frozen_archive_partition_layout(tmp_path: Path) -> None:
    partition = tmp_path / "BTCUSDT" / "archive=2020-01" / "date=2020-01-01" / "part-000.parquet"
    partition.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "ts_event_ns": [1_577_836_799_000_000_000],
            "quantity": ["1"],
            "aggressor_side": ["BUY"],
            "canonical_trade_id": ["trade-1"],
        }
    ).write_parquet(partition)

    result = build_flow_day(
        trade_paths=(partition,),
        instrument="BTCUSDT",
        windows=[
            {
                "window_start_ts": 1_577_836_795_000_000_000,
                "window_end_ts": 1_577_836_800_000_000_000,
                "trigger_id": "trigger-1",
                "event_parameter_set_id": "G1-PRIMARY-V1",
                "market_episode_id": "episode-1",
                "canonical_candidate_id": "1" * 64,
                "candidate_version_id": "1" * 64,
                "canonical_payload_hash": "2" * 64,
                "direction": "LONG",
                "canonical_key_level_id": "3" * 64,
                "sweep_id": "4" * 64,
                "reclaim_id": "5" * 64,
                "hold_id": "6" * 64,
                "time_combination_id": "T2",
                "data_run_id": "stage1",
                "dataset_logical_hash": "7" * 64,
                "config_hash": "8" * 64,
                "code_version": "abcdef0",
                "venue": "BINANCE_USDM",
                "sweep_start_ns": 1_577_836_790_000_000_000,
            }
        ],
    )

    assert len(result["flow_features"]) == 1
