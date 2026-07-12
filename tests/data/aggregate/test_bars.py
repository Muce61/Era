from decimal import Decimal
import pytest
from era100x.data.aggregate import aggregate_trade_bars
from era100x.data.schema.models import NormalizedTrade


def t(i: int, ts: int, price: str, symbol: str = "BTCUSDT") -> NormalizedTrade:
    return NormalizedTrade(
        instrument=symbol,
        trade_id=i,
        price=Decimal(price),
        quantity=Decimal("1"),
        quote_quantity=Decimal(price),
        ts_event_ns=ts,
        is_buyer_maker=True,
        aggressor_side="SELL",
        source_sha256="x",
    )


def test_utc_bucket_and_stable_tie_breaker() -> None:
    rows = [t(2, 500, "102"), t(1, 500, "100"), t(3, 1_000_000_001, "99")]
    assert aggregate_trade_bars(rows) == aggregate_trade_bars(list(reversed(rows)))
    bars = aggregate_trade_bars(rows)
    assert (bars[0].open, bars[0].close, bars[0].high) == (
        Decimal("100"),
        Decimal("102"),
        Decimal("102"),
    )
    assert bars[1].bucket_start_ns == 1_000_000_000


def test_mixed_sources_and_bad_interval_fail() -> None:
    with pytest.raises(ValueError, match="mixed"):
        aggregate_trade_bars([t(1, 1, "1"), t(2, 2, "1", "ETHUSDT")])
    with pytest.raises(ValueError):
        aggregate_trade_bars([], 0)
