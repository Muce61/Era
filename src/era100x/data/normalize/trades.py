from decimal import Decimal, InvalidOperation
from era100x.data.normalize.identity import canonical_trade_identity
from era100x.data.schema.models import NormalizedTrade, RawTrade


def normalize_trade(raw: RawTrade) -> NormalizedTrade:
    try:
        price = Decimal(raw.price_text)
        qty = Decimal(raw.qty_text)
        quote = Decimal(raw.quote_qty_text)
    except InvalidOperation as exc:
        raise ValueError("invalid trade decimal") from exc
    if price <= 0 or qty <= 0 or quote < 0 or raw.venue_trade_id < 0 or raw.ts_event_ms < 0:
        raise ValueError("invalid trade value")
    ts_event_ns = raw.ts_event_ms * 1_000_000
    return NormalizedTrade(
        instrument=raw.instrument,
        venue_trade_id=raw.venue_trade_id,
        canonical_trade_id=canonical_trade_identity(
            instrument=raw.instrument,
            venue_trade_id=raw.venue_trade_id,
            ts_event_ns=ts_event_ns,
            price=price,
            quantity=qty,
            quote_quantity=quote,
            is_buyer_maker=raw.is_buyer_maker,
        ),
        identity_status="UNIQUE_VENUE_ID",
        price=price,
        quantity=qty,
        quote_quantity=quote,
        ts_event_ns=ts_event_ns,
        is_buyer_maker=raw.is_buyer_maker,
        source_sha256=raw.source_sha256,
    )
