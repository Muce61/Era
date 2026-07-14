from decimal import Decimal
from era100x.data.quality import inspect_contract_gaps, inspect_trades
from era100x.data.schema.models import ContractPrice1s, NormalizedTrade
from era100x.data.normalize.identity import canonical_trade_identity


def trade(i: int, ts: int, price: str = "1") -> NormalizedTrade:
    decimal_price = Decimal(price)
    canonical_id = canonical_trade_identity(
        instrument="BTCUSDT",
        venue_trade_id=i,
        ts_event_ns=ts,
        price=decimal_price,
        quantity=Decimal("1"),
        quote_quantity=Decimal("1"),
        is_buyer_maker=True,
    )
    return NormalizedTrade(
        instrument="BTCUSDT",
        venue_trade_id=i,
        canonical_trade_id=canonical_id,
        identity_status="UNIQUE_VENUE_ID",
        price=decimal_price,
        quantity=Decimal("1"),
        quote_quantity=Decimal("1"),
        ts_event_ns=ts,
        is_buyer_maker=True,
        aggressor_side="SELL",
        source_sha256="x",
    )


def test_duplicates_conflicts_reversal_and_gap_are_distinct() -> None:
    a = trade(1, 10)
    rows = [a, a, trade(1, 10, "2"), trade(3, 9)]
    clean, issues = inspect_trades(rows)
    assert [x.code for x in issues] == [
        "DUPLICATE_EXACT",
        "TIME_REVERSAL",
        "TRADE_ID_GAP",
        "VENUE_ID_CONFLICT",
    ]
    assert len(clean) == 3
    assert clean[0].identity_status == clean[1].identity_status == "CONFLICTING_VENUE_ID"


def test_contract_gap_is_not_filled() -> None:
    def row(ts: int) -> ContractPrice1s:
        return ContractPrice1s(
            instrument="ETHUSDT",
            ts_event_ns=ts,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("0"),
            source_encoding="DECIMAL_TEXT",
        )

    rows = [row(0), row(2_000_000_000)]
    issues = inspect_contract_gaps(rows)
    assert issues[0].code == "CONTRACT_SECOND_GAP" and len(rows) == 2
