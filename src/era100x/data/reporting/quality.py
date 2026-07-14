from __future__ import annotations
import hashlib
import json

REQUIRED = (
    "schema",
    "contract_reader",
    "trades_ingest",
    "normalization",
    "aggressor",
    "integrity",
    "storage",
    "aggregation",
    "historical_null",
    "splits",
)


def sample_quality_report(results: dict[str, bool]) -> dict[str, object]:
    missing = [name for name in REQUIRED if name not in results]
    failed = [name for name in REQUIRED if not results.get(name, False)]
    if missing or failed:
        raise ValueError(f"sample gates incomplete: missing={missing}, failed={failed}")
    payload: dict[str, object] = {
        "scope": "SMALL_FIXTURE",
        "full_data_status": "NOT_RUN_FULL_DATA",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "gates": {k: True for k in sorted(REQUIRED)},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["report_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload
