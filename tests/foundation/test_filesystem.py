from pathlib import Path

from era100x.foundation.filesystem import iter_evidence_files


def test_evidence_discovery_ignores_appledouble_files_and_directories(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "rows.parquet").write_bytes(b"real")
    (tmp_path / "real" / "._rows.parquet").write_bytes(b"sidecar")
    (tmp_path / "._metadata").mkdir()
    (tmp_path / "._metadata" / "hidden.json").write_text("{}", encoding="utf-8")

    assert [path.relative_to(tmp_path) for path in iter_evidence_files(tmp_path)] == [
        Path("real/rows.parquet")
    ]
