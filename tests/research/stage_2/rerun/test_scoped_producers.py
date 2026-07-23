from __future__ import annotations

from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.rerun.scoped_producers import _tree_summary


def test_tree_summary_ignores_external_volume_appledouble_sidecars(tmp_path: Path) -> None:
    pq.write_table(pa.table({"value": [1, 2]}), tmp_path / "rows.parquet")
    (tmp_path / "._rows.parquet").write_bytes(b"AppleDouble metadata, not Parquet")

    result = _tree_summary(tmp_path)

    assert result["file_count"] == 1
    assert result["row_count"] == 2
    assert result["files"][0]["relative_path"] == "rows.parquet"
