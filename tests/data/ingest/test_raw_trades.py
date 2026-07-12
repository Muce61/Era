import hashlib
from pathlib import Path
import pytest
from era100x.data.ingest import archive_url, download_verified


class Response:
    def __init__(self, data: bytes, status: int = 200):
        self.data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int) -> bytes:
        result, self.data = self.data[:size], self.data[size:]
        return result


def test_official_url_only() -> None:
    assert (
        archive_url("BTCUSDT", "2020-01")
        == "https://data.binance.vision/data/futures/um/monthly/trades/BTCUSDT/BTCUSDT-trades-2020-01.zip"
    )


def test_download_is_verified_idempotent_and_immutable(tmp_path: Path) -> None:
    data = b"official"
    expected = hashlib.sha256(data).hexdigest()
    dest = tmp_path / "x.zip"

    def opener(request: object, timeout: int) -> Response:
        return Response(data)

    assert download_verified("https://data.binance.vision/x", dest, expected, opener=opener) == dest
    assert download_verified("https://data.binance.vision/x", dest, expected, opener=opener) == dest
    with pytest.raises(FileExistsError):
        download_verified("x", dest, "0" * 64, opener=opener)


def test_checksum_and_refused_range_fail(tmp_path: Path) -> None:
    dest = tmp_path / "x.zip"
    part = tmp_path / "x.zip.part"
    part.write_bytes(b"a")
    with pytest.raises(OSError, match="Range"):
        download_verified(
            "https://data.binance.vision/x",
            dest,
            hashlib.sha256(b"ab").hexdigest(),
            opener=lambda r, timeout: Response(b"b", 200),
            max_attempts=1,
        )
    with pytest.raises(ValueError, match="checksum"):
        download_verified(
            "https://data.binance.vision/x",
            dest,
            "0" * 64,
            opener=lambda r, timeout: Response(b"bad"),
            max_attempts=1,
        )
