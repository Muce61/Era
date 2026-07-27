from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa

from era100x.research.stage_2.metrics.path import full_run


def test_build_instrument_creates_destination_parent_before_writer(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(full_run, "_load_inputs", lambda _instrument: ([], {}, {}, [], []))
    monkeypatch.setattr(full_run.CatalogReaderV2, "open", lambda *args, **kwargs: object())
    destination = tmp_path / "BTCUSDT" / "path_metrics.parquet"

    summary = full_run._build_instrument(
        "BTCUSDT",
        destination,
        thresholds=(full_run.Decimal("20"),),
        source={
            "source_s2t11_manifest_hash": "1" * 64,
            "source_s2t11_catalog_hash": "2" * 64,
        },
        references={},
    )

    assert destination.is_file()
    assert destination.with_suffix(".summary.json").is_file()
    assert summary["path_metrics"]["row_count"] == 0


def test_latest_preflight_uses_recency_not_authority_hash_order(
    tmp_path: Path, monkeypatch
) -> None:
    older = tmp_path / f"{'f' * 64}.json"
    newer = tmp_path / f"{'0' * 64}.json"
    older.write_text("{}")
    newer.write_text("{}")
    os.utime(older, ns=(1, 1))
    os.utime(newer, ns=(2, 2))
    monkeypatch.setattr(full_run, "AUTHORITY_ROOT", tmp_path)

    assert full_run.latest_preflight_manifest() == newer


def test_v2_stable_order_check_avoids_sort_copy_and_detects_each_key_level() -> None:
    def table(rows: list[tuple[int, int, str]]) -> pa.Table:
        return pa.table(
            {
                "ts_event_ns": [row[0] for row in rows],
                "venue_trade_id": [row[1] for row in rows],
                "canonical_trade_id": [row[2] for row in rows],
            }
        )

    assert full_run._is_v2_stably_ordered(
        table([(1, 2, "a"), (1, 2, "b"), (1, 3, "a"), (2, 1, "a")])
    )
    assert not full_run._is_v2_stably_ordered(table([(2, 1, "a"), (1, 2, "a")]))
    assert not full_run._is_v2_stably_ordered(table([(1, 2, "a"), (1, 1, "z")]))
    assert not full_run._is_v2_stably_ordered(table([(1, 2, "b"), (1, 2, "a")]))
    assert not full_run._is_v2_stably_ordered(
        pa.table(
            {
                "ts_event_ns": pa.array([1, None], type=pa.int64()),
                "venue_trade_id": [1, 2],
                "canonical_trade_id": ["a", "b"],
            }
        )
    )
