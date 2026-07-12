from decimal import Decimal, InvalidOperation
from era100x.data.schema.models import NormalizedTrade, RawTrade


def normalize_trade(raw: RawTrade) -> NormalizedTrade:
    try:
        price = Decimal(raw.price_text)
        qty = Decimal(raw.qty_text)
        quote = Decimal(raw.quote_qty_text)
    except InvalidOperation as exc:
        raise ValueError("invalid trade decimal") from exc
    if price <= 0 or qty <= 0 or quote < 0 or raw.trade_id < 0 or raw.ts_event_ms < 0:
        raise ValueError("invalid trade value")
    return NormalizedTrade(
        instrument=raw.instrument,
        trade_id=raw.trade_id,
        price=price,
        quantity=qty,
        quote_quantity=quote,
        ts_event_ns=raw.ts_event_ms * 1_000_000,
        is_buyer_maker=raw.is_buyer_maker,
        source_sha256=raw.source_sha256,
    )
