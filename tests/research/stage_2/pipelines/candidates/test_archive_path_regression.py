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
                "candidate_version_id": "candidate-1",
            }
        ],
    )

    assert len(result["flow_features"]) == 1
