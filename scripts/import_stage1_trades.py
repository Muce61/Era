"""Explicit CLI for verified official public Trades archives; no account API."""

from __future__ import annotations
import argparse
from pathlib import Path
from era100x.data.ingest import download_verified


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--destination", type=Path, required=True)
    a = p.parse_args()
    if not a.url.startswith("https://data.binance.vision/data/futures/um/"):
        raise ValueError("only official USD-M public archive is allowed")
    download_verified(a.url, a.destination, a.sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
