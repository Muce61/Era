"""Read-only HEAD and disk preflight. It never creates the Stage 1 work root."""

from __future__ import annotations
import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from era100x.data.ingest import archive_url


Symbol = Literal["BTCUSDT", "ETHUSDT"]
Frequency = Literal["monthly", "daily"]


def periods() -> list[tuple[Symbol, str, Frequency]]:
    result: list[tuple[Symbol, str, Frequency]] = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        year, month = 2020, 1
        while (year, month) <= (2026, 6):
            result.append((symbol, f"{year:04d}-{month:02d}", "monthly"))
            month += 1
            if month == 13:
                year += 1
                month = 1
        for day in range(1, 4):
            result.append((symbol, f"2026-07-{day:02d}", "daily"))
    return result


def head_size(item: tuple[Symbol, str, Frequency]) -> tuple[str, int | None]:
    symbol, period, frequency = item
    url = archive_url(symbol, period, frequency)
    try:
        with urlopen(Request(url, method="HEAD"), timeout=30) as response:
            return url, int(response.headers["Content-Length"])
    except HTTPError as exc:
        if exc.code == 404:
            return url, None
        raise


def estimate(
    compressed: int, largest: int, contract_bytes: int, available: int
) -> dict[str, object]:
    published = compressed * 2
    contract_index = contract_bytes // 5
    stream_temp = largest * 6
    repeat_temp = largest * 2
    reports = max(1_073_741_824, compressed // 100)
    peak = int(
        (compressed + published + contract_index + stream_temp + repeat_temp + reports) * 1.05
    )
    required = int(peak * 1.20)
    return {
        "compressed_download_bytes": compressed,
        "published_estimate_bytes": published,
        "contract_index_estimate_bytes": contract_index,
        "stream_temp_bytes": stream_temp,
        "repeat_build_temp_bytes": repeat_temp,
        "catalog_manifest_report_bytes": reports,
        "peak_estimate_bytes": peak,
        "required_with_20pct_margin_bytes": required,
        "available_bytes": available,
        "passes_space_gate": available >= required,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--contract-root", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    a = p.parse_args()
    if a.work_root.exists():
        raise FileExistsError("work root must not exist before passing preflight")
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(head_size, periods()))
    sizes = [size for _, size in results if size is not None]
    disk = shutil.disk_usage(a.work_root.parent)
    contract_bytes = sum(
        p.stat().st_size
        for s in ("BTCUSDT", "ETHUSDT")
        for p in (a.contract_root / f"{s}_1s_agg").iterdir()
        if p.suffix in {".csv", ".parquet"}
    )
    output = estimate(sum(sizes), max(sizes), contract_bytes, disk.free)
    output["archive_count"] = len(sizes)
    output["missing_archives"] = [url for url, size in results if size is None]
    output["estimated_runtime_seconds_at_25MiBps"] = sum(sizes) // (25 * 1024 * 1024)
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["passes_space_gate"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
