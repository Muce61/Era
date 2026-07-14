import pytest
from era100x.data.normalize import normalize_trade
from era100x.data.schema.models import RawTrade


def raw(**changes: object) -> RawTrade:
    values = dict(
        instrument="BTCUSDT",
        venue_trade_id=1,
        price_text="100.00",
        qty_text="0.10",
        quote_qty_text="10.000",
        ts_event_ms=1577836800000,
        is_buyer_maker=True,
        source_sha256="a" * 64,
    )
    values.update(changes)
    return RawTrade(**values)


def test_normalization_is_deterministic_and_preserves_lineage() -> None:
    result = normalize_trade(raw())
    assert result == normalize_trade(raw())
    assert (
        str(result.price) == "100.00"
        and result.ts_event_ns == 1577836800000000000
        and result.source_sha256 == "a" * 64
    )
    assert len(result.canonical_trade_id) == 64
    assert result.identity_status == "UNIQUE_VENUE_ID"


def test_decimal_equivalent_text_has_same_canonical_identity() -> None:
    assert (
        normalize_trade(raw(price_text="100.0")).canonical_trade_id
        == normalize_trade(raw(price_text="100.000")).canonical_trade_id
    )


@pytest.mark.parametrize(
    "field,value",
    [("price_text", "0"), ("qty_text", "-1"), ("venue_trade_id", -1), ("ts_event_ms", -1)],
)
def test_invalid_values_fail(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        normalize_trade(raw(**{field: value}))
