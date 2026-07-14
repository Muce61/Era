from __future__ import annotations
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
import polars as pl
from era100x.data.schema.models import NormalizedTrade


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish_partition(rows: list[NormalizedTrade], root: Path, run_id: str) -> dict[str, object]:
    if not rows:
        raise ValueError("empty partition")
    ordered = sorted(
        rows,
        key=lambda r: (r.instrument, r.ts_event_ns, r.venue_trade_id, r.canonical_trade_id),
    )
    symbol = ordered[0].instrument
    if any(r.instrument != symbol for r in ordered):
        raise ValueError("mixed instruments")
    date = datetime.fromtimestamp(ordered[0].ts_event_ns / 1e9, tz=UTC).date().isoformat()
    if any(
        datetime.fromtimestamp(r.ts_event_ns / 1e9, tz=UTC).date().isoformat() != date
        for r in ordered
    ):
        raise ValueError("mixed dates")
    final = root / run_id
    temp = root / f".{run_id}.tmp"
    if final.exists() or temp.exists():
        raise FileExistsError("run_id already exists")
    temp.mkdir(parents=True)
    relative = Path(f"instrument={symbol}/date={date}/part-000.parquet")
    path = temp / relative
    path.parent.mkdir(parents=True)
    records = [
        {
            "instrument": r.instrument,
            "venue_trade_id": r.venue_trade_id,
            "canonical_trade_id": r.canonical_trade_id,
            "identity_status": r.identity_status,
            "venue_trade_id_conflict_group": r.venue_trade_id_conflict_group,
            "price": str(r.price),
            "quantity": str(r.quantity),
            "quote_quantity": str(r.quote_quantity),
            "ts_event_ns": r.ts_event_ns,
            "is_buyer_maker": r.is_buyer_maker,
            "aggressor_side": r.aggressor_side,
            "source_sha256": r.source_sha256,
        }
        for r in ordered
    ]
    logical = b"\n".join(
        json.dumps(x, sort_keys=True, separators=(",", ":")).encode() for x in records
    )
    pl.DataFrame(records).write_parquet(path, compression="zstd", statistics=True)
    catalog = {
        "run_id": run_id,
        "relative_path": str(relative),
        "rows": len(records),
        "byte_sha256": _sha(path.read_bytes()),
        "logical_sha256": _sha(logical),
    }
    (temp / "catalog.json").write_text(json.dumps(catalog, sort_keys=True, indent=2) + "\n")
    temp.replace(final)
    return catalog
