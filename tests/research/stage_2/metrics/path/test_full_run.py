from __future__ import annotations

import os
from pathlib import Path

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
