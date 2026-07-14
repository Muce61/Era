from pathlib import Path
from scripts.audit_stage1_assets import audit


def test_inventory_is_deterministic_and_ignores_unknown(tmp_path: Path) -> None:
    for symbol in ("BTCUSDT", "ETHUSDT"):
        d = tmp_path / f"{symbol}_1s_agg"
        d.mkdir()
        (d / f"{symbol}_1s_20200101.csv").write_text("x")
        (d / f"{symbol}_1s_20200101.parquet").write_bytes(b"y")
        (d / "ignore.tmp").write_text("z")
    first = audit(tmp_path)
    assert first == audit(tmp_path)
    assert first["BTCUSDT"]["date_count"] == 1
    assert first["BTCUSDT"]["overlap_dates"] == ["20200101"]
