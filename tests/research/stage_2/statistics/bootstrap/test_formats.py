from __future__ import annotations

from pathlib import Path

from era100x.research.stage_2.statistics.bootstrap.runner import _parquet_files


def test_appledouble_parquet_is_excluded(tmp_path: Path) -> None:
    real = tmp_path / "part.parquet"
    sidecar = tmp_path / "._part.parquet"
    real.write_bytes(b"parquet")
    sidecar.write_bytes(b"apple-double")
    assert _parquet_files(tmp_path) == (real,)
