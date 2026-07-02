"""Download and audit longer 1m Binance futures history.

Large merged CSV files are intentionally written outside the repository under
``/Users/muce/1m_data``. Research Core keeps only small audit artifacts.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from research_core.common import RESEARCH_ROOT, append_run_log, current_git_commit, file_sha256, stable_hash


BINANCE_MONTHLY_URL = "https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip"
DEFAULT_SYMBOLS = [
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "LTCUSDT",
]
DEFAULT_START_MONTH = "2020-01"
DEFAULT_END_MONTH = "2023-12"
LOCAL_1M_SOURCES = [
    Path("/Users/muce/1m_data/2024_validation_1m/{symbol}.csv"),
    Path("/Users/muce/1m_data/new_backtest_data_1year_1m/{symbol}.csv"),
    Path("/Users/muce/PycharmProjects/20260621/eth/backtest_results/stage2/data_audit/merged_ethusdt_1m.csv"),
]
OUTPUT_ROOT = Path("/Users/muce/1m_data/long_history_1m")
ARTIFACT_ROOT = RESEARCH_ROOT / "long_history_data"


@dataclass(frozen=True)
class DownloadResult:
    symbol: str
    month: str
    status: str
    rows: int
    path: str
    note: str


def month_range(start_month: str, end_month: str) -> list[str]:
    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    if start > end:
        raise ValueError("start_month must be <= end_month")
    return [str(p) for p in pd.period_range(start, end, freq="M")]


def read_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).lower() for c in df.columns]
    if "timestamp" not in df.columns:
        raise ValueError(f"{path} has no timestamp column")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    keep = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")
    out = df[keep].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])


def parse_binance_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        csv_names = [name for name in zf.namelist() if name.endswith(".csv")]
        if not csv_names:
            raise ValueError("zip file contains no CSV")
        with zf.open(csv_names[0]) as f:
            df = pd.read_csv(f, header=None)
    if len(df.columns) < 6:
        raise ValueError("unexpected Binance kline CSV format")
    df = df.iloc[:, :6].copy()
    df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])


def fetch_month(symbol: str, month: str, cache_dir: Path, sleep_seconds: float = 0.15) -> DownloadResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"{symbol}-1m-{month}.zip"
    url = BINANCE_MONTHLY_URL.format(symbol=symbol, month=month)
    try:
        if not zip_path.exists():
            req = Request(url, headers={"User-Agent": "EraResearchCore/1.0"})
            with urlopen(req, timeout=60) as response:
                zip_path.write_bytes(response.read())
            time.sleep(sleep_seconds)
        rows = len(parse_binance_zip(zip_path.read_bytes()))
        return DownloadResult(symbol, month, "downloaded_or_cached", rows, str(zip_path), "")
    except HTTPError as exc:
        if exc.code == 404:
            return DownloadResult(symbol, month, "missing_remote", 0, str(zip_path), "HTTP 404")
        return DownloadResult(symbol, month, "failed", 0, str(zip_path), f"HTTP {exc.code}: {exc.reason}")
    except (URLError, TimeoutError, ValueError, zipfile.BadZipFile) as exc:
        return DownloadResult(symbol, month, "failed", 0, str(zip_path), str(exc))


def load_cached_months(symbol: str, months: list[str], cache_dir: Path) -> list[pd.DataFrame]:
    frames = []
    for month in months:
        zip_path = cache_dir / f"{symbol}-1m-{month}.zip"
        if zip_path.exists():
            frames.append(parse_binance_zip(zip_path.read_bytes()))
    return frames


def local_source_paths(symbol: str) -> list[Path]:
    paths = []
    for template in LOCAL_1M_SOURCES:
        path = Path(str(template).format(symbol=symbol))
        if symbol != "ETHUSDT" and "merged_ethusdt_1m" in str(path):
            continue
        if path.exists():
            paths.append(path)
    return paths


def merge_symbol_history(symbol: str, downloaded_frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = list(downloaded_frames)
    for path in local_source_paths(symbol):
        frames.append(read_ohlcv_csv(path))
    if not frames:
        raise FileNotFoundError(f"No data frames available for {symbol}")
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"], keep="last")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged


def audit_data(symbol: str, data: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ts = pd.to_datetime(data["timestamp"], utc=True)
    diff = ts.diff()
    gaps = data.loc[diff > pd.Timedelta(minutes=1), ["timestamp"]].copy()
    if not gaps.empty:
        gaps["previous_timestamp"] = ts.shift(1).loc[gaps.index].values
        gaps["missing_minutes"] = (diff.loc[gaps.index] / pd.Timedelta(minutes=1) - 1).astype(int).values
        gaps = gaps[["previous_timestamp", "timestamp", "missing_minutes"]]

    duplicates = data[data["timestamp"].duplicated(keep=False)].copy()
    invalid = data[
        (data["low"] > data[["open", "close"]].min(axis=1))
        | (data["high"] < data[["open", "close"]].max(axis=1))
        | (data[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (data["volume"] < 0)
    ].copy()
    pct = data["close"].pct_change().abs()
    outliers = data.loc[pct > 0.10, ["timestamp", "open", "high", "low", "close", "volume"]].copy()
    outliers["abs_close_change_pct"] = pct.loc[outliers.index].values
    report = {
        "symbol": symbol,
        "start_utc": ts.min().isoformat(),
        "end_utc": ts.max().isoformat(),
        "row_count": int(len(data)),
        "coverage_days": round(float((ts.max() - ts.min()).total_seconds() / 86400), 4),
        "duplicate_timestamp_count": int(duplicates["timestamp"].nunique()) if not duplicates.empty else 0,
        "missing_range_count": int(len(gaps)),
        "missing_minute_count": int(gaps["missing_minutes"].sum()) if not gaps.empty else 0,
        "invalid_ohlc_count": int(len(invalid)),
        "outlier_count": int(len(outliers)),
        "monotonic_increasing": bool(ts.is_monotonic_increasing),
    }
    return report, gaps, invalid, outliers


def build_long_history(
    symbols: list[str] | None = None,
    start_month: str = DEFAULT_START_MONTH,
    end_month: str = DEFAULT_END_MONTH,
) -> dict[str, Path]:
    symbols = symbols or DEFAULT_SYMBOLS
    months = month_range(start_month, end_month)
    cache_root = OUTPUT_ROOT / "_binance_monthly_cache"
    merged_root = OUTPUT_ROOT / "merged"
    merged_root.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    download_rows = []
    quality_rows = []
    output_paths: dict[str, Path] = {}
    manifest_records = []
    for symbol in symbols:
        cache_dir = cache_root / symbol
        results = [fetch_month(symbol, month, cache_dir) for month in months]
        download_rows.extend([r.__dict__ for r in results])
        frames = load_cached_months(symbol, months, cache_dir)
        merged = merge_symbol_history(symbol, frames)
        output_path = merged_root / f"{symbol}.csv"
        merged.to_csv(output_path, index=False)
        output_paths[symbol] = output_path

        quality, gaps, invalid, outliers = audit_data(symbol, merged)
        quality["path"] = str(output_path)
        quality["sha256"] = file_sha256(output_path)
        quality_rows.append(quality)
        gaps.to_csv(ARTIFACT_ROOT / f"{symbol}_missing_ranges.csv", index=False)
        invalid.to_csv(ARTIFACT_ROOT / f"{symbol}_invalid_ohlc_rows.csv", index=False)
        outliers.to_csv(ARTIFACT_ROOT / f"{symbol}_outlier_rows.csv", index=False)
        manifest_records.append({
            "dataset_name": "long_history_1m",
            "symbol": symbol,
            "timeframe": "1m",
            "path": str(output_path),
            "start_utc": quality["start_utc"],
            "end_utc": quality["end_utc"],
            "row_count": quality["row_count"],
            "sha256": quality["sha256"],
            "data_layer": "expanded_discovery",
            "oos_eligible": False,
            "notes": "Merged Binance public monthly futures klines with existing local 2024-2026 data; not OOS.",
        })

    downloads = pd.DataFrame(download_rows)
    quality_df = pd.DataFrame(quality_rows)
    manifest = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Binance public futures monthly klines + local audited data",
        "download_start_month": start_month,
        "download_end_month": end_month,
        "symbols": symbols,
        "records": manifest_records,
    }
    downloads.to_csv(ARTIFACT_ROOT / "download_inventory.csv", index=False)
    quality_df.to_csv(ARTIFACT_ROOT / "long_history_quality_report.csv", index=False)
    (ARTIFACT_ROOT / "long_history_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(downloads, quality_df, manifest)

    append_run_log({
        "run_id": "LONG_HISTORY_DATA_EXPANSION",
        "stage": "DATA",
        "script": "research_core.build_long_history_data",
        "config_hash": stable_hash({"symbols": symbols, "start_month": start_month, "end_month": end_month}),
        "data_hash": stable_hash([r["sha256"] for r in manifest_records]),
        "git_commit": current_git_commit(),
        "run_timestamp": manifest["run_timestamp"],
        "random_seed": "",
        "data_layer": "expanded_discovery",
        "status": "success",
        "notes": "longer local history generated; large CSV stored outside git; not OOS",
    })
    return output_paths


def write_report(downloads: pd.DataFrame, quality: pd.DataFrame, manifest: dict) -> None:
    lines = [
        "# Long History Data Expansion",
        "",
        f"Run timestamp: `{manifest['run_timestamp']}`",
        f"Download months: `{manifest['download_start_month']}` to `{manifest['download_end_month']}`",
        "",
        "Large merged CSV files are stored outside Git under `/Users/muce/1m_data/long_history_1m/merged/`.",
        "This data is expanded discovery/internal validation, not OOS.",
        "",
        "## Quality Summary",
        "",
        quality.to_markdown(index=False),
        "",
        "## Download Status",
        "",
        downloads.groupby(["symbol", "status"]).size().reset_index(name="months").to_markdown(index=False),
        "",
    ]
    (ARTIFACT_ROOT / "long_history_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download, merge, and audit long 1m Binance futures history.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="Symbols to build; defaults to the fixed 10-symbol research set.")
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH)
    parser.add_argument("--end-month", default=DEFAULT_END_MONTH)
    args = parser.parse_args()
    build_long_history(args.symbols, args.start_month, args.end_month)
