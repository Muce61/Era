from decimal import Decimal
from pathlib import Path
import pytest
from era100x.data.schema.models import NormalizedTrade
from era100x.data.normalize.identity import canonical_trade_identity
from era100x.data.storage import publish_partition


def trade(i: int) -> NormalizedTrade:
    ts = 1577836800000000000 + i
    canonical_id = canonical_trade_identity(
        instrument="BTCUSDT",
        venue_trade_id=i,
        ts_event_ns=ts,
        price=Decimal("100"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("100"),
        is_buyer_maker=True,
    )
    return NormalizedTrade(
        instrument="BTCUSDT",
        venue_trade_id=i,
        canonical_trade_id=canonical_id,
        identity_status="UNIQUE_VENUE_ID",
        price=Decimal("100"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("100"),
        ts_event_ns=ts,
        is_buyer_maker=True,
        aggressor_side="SELL",
        source_sha256="x",
    )


def test_publish_is_sorted_atomic_and_logically_deterministic(tmp_path: Path) -> None:
    a = publish_partition([trade(2), trade(1)], tmp_path, "a")
    b = publish_partition([trade(1), trade(2)], tmp_path, "b")
    assert a["logical_sha256"] == b["logical_sha256"]
    assert (tmp_path / "a/catalog.json").exists() and not (tmp_path / ".a.tmp").exists()


def test_existing_run_and_mixed_instrument_fail(tmp_path: Path) -> None:
    publish_partition([trade(1)], tmp_path, "a")
    with pytest.raises(FileExistsError):
        publish_partition([trade(1)], tmp_path, "a")
    other = trade(2).model_copy(update={"instrument": "ETHUSDT"})
    with pytest.raises(ValueError, match="mixed instruments"):
        publish_partition([trade(1), other], tmp_path, "b")
