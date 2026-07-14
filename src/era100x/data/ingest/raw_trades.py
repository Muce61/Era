from __future__ import annotations
import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.request import Request, urlopen

BASE = "https://data.binance.vision/data/futures/um"


def archive_url(
    symbol: Literal["BTCUSDT", "ETHUSDT"],
    period: str,
    frequency: Literal["monthly", "daily"] = "monthly",
) -> str:
    name = f"{symbol}-trades-{period}.zip"
    return f"{BASE}/{frequency}/trades/{symbol}/{name}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def download_verified(
    url: str,
    destination: Path,
    expected_sha256: str,
    *,
    opener: Callable[..., Any] = urlopen,
    max_attempts: int = 3,
) -> Path:
    if destination.exists():
        if sha256(destination) != expected_sha256:
            raise FileExistsError("immutable raw archive conflicts")
        return destination
    part = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_attempts):
        offset = part.stat().st_size if part.exists() else 0
        request = Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with opener(request, timeout=30) as response:
                status = getattr(response, "status", 200)
                if offset and status != 206:
                    part.unlink(missing_ok=True)
                    raise OSError("server refused Range resume")
                with part.open("ab" if offset else "wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
            if sha256(part) != expected_sha256:
                raise ValueError("archive checksum mismatch")
            os.chmod(part, 0o444)
            part.replace(destination)
            return destination
        except Exception:
            if attempt + 1 == max_attempts:
                raise
            time.sleep(2**attempt / 100)
    raise AssertionError("unreachable")
