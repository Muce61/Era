from decimal import Decimal
from era100x.data.schema.models import NormalizedTrade
from era100x.data.normalize.identity import canonical_trade_identity
from era100x.data.trades import with_aggressor_side


def trade(maker: bool) -> NormalizedTrade:
    canonical_id = canonical_trade_identity(
        instrument="ETHUSDT",
        venue_trade_id=1,
        ts_event_ns=1,
        price=Decimal("1"),
        quantity=Decimal("2"),
        quote_quantity=Decimal("2"),
        is_buyer_maker=maker,
    )
    return NormalizedTrade(
        instrument="ETHUSDT",
        venue_trade_id=1,
        canonical_trade_id=canonical_id,
        identity_status="UNIQUE_VENUE_ID",
        price=Decimal("1"),
        quantity=Decimal("2"),
        quote_quantity=Decimal("2"),
        ts_event_ns=1,
        is_buyer_maker=maker,
        source_sha256="a",
    )


def test_buyer_maker_means_sell_aggressor() -> None:
    assert with_aggressor_side(trade(True)).aggressor_side == "SELL"
    assert with_aggressor_side(trade(False)).aggressor_side == "BUY"
    assert trade(True).aggressor_side is None
