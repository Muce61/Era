from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from era100x.research.stage_2.baselines.conditional.execution_run import (
    _copy_tree_files,
    _publication_entries,
)


def test_catalog_and_copy_ignore_appledouble_beside_real_parquet(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    parquet_path = source / "result.parquet"
    pq.write_table(pa.table({"value": [1, 2, 3]}), parquet_path)
    (source / "._result.parquet").write_bytes(b"AppleDouble metadata, not Parquet")

    entries = _publication_entries(source)
    assert [entry["relative_path"] for entry in entries] == ["result.parquet"]
    assert entries[0]["row_count"] == 3

    destination = tmp_path / "destination"
    _copy_tree_files(source, destination)
    assert (destination / "result.parquet").is_file()
    assert not (destination / "._result.parquet").exists()
