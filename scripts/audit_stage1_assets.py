"""Read-only Stage 1 asset inventory."""

from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

PATTERN = re.compile(r"^(BTCUSDT|ETHUSDT)_1s_(\d{8})\.(csv|parquet)$")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(root: Path) -> dict[str, object]:
    out: dict[str, object] = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        directory = root / f"{symbol}_1s_agg"
        dates: dict[str, list[str]] = {}
        total = 0
        for p in directory.iterdir():
            m = PATTERN.match(p.name)
            if not m:
                continue
            dates.setdefault(m.group(2), []).append(m.group(3))
            total += p.stat().st_size
        ordered = sorted(dates)
        overlaps = [d for d in ordered if len(dates[d]) > 1]
        samples = [
            directory / f"{symbol}_1s_{d}.{sorted(dates[d])[0]}" for d in (ordered[0], ordered[-1])
        ]
        out[symbol] = {
            "date_count": len(ordered),
            "start": ordered[0],
            "end_inclusive": ordered[-1],
            "overlap_dates": overlaps,
            "csv_count": sum("csv" in v for v in dates.values()),
            "parquet_count": sum("parquet" in v for v in dates.values()),
            "bytes": total,
            "sample_sha256": {p.name: digest(p) for p in samples},
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path)
    result = audit(p.parse_args().root)
    text = json.dumps(result, sort_keys=True, indent=2)
    if p.parse_args().output:
        raise RuntimeError("output option is intentionally unsupported in read-only audit")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
