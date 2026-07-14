"""Stage 1 Trade Identity v2 canonicalization."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

SCHEMA_VERSION = "stage1-trades-v2"


def canonical_decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("trade decimal must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def canonical_trade_identity(
    *,
    instrument: str,
    venue_trade_id: int,
    ts_event_ns: int,
    price: Decimal,
    quantity: Decimal,
    quote_quantity: Decimal,
    is_buyer_maker: bool,
) -> str:
    payload = {
        "instrument": instrument,
        "is_buyer_maker": is_buyer_maker,
        "price": canonical_decimal_text(price),
        "quantity": canonical_decimal_text(quantity),
        "quote_quantity": canonical_decimal_text(quote_quantity),
        "schema_version": SCHEMA_VERSION,
        "ts_event_ns": ts_event_ns,
        "venue_trade_id": venue_trade_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
