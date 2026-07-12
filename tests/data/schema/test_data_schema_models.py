from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.data.schema.models import ContractPrice1s, DataQuality, HistoricalEvidenceRow


def test_contract_price_decimal_and_float_source_label() -> None:
    row = ContractPrice1s(
        instrument="BTCUSDT",
        ts_event_ns=1,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("1"),
        close=Decimal("2"),
        volume=Decimal("0"),
        source_encoding="SOURCE_FLOAT64",
    )
    assert row.volume == Decimal("0")
    with pytest.raises(ValidationError):
        ContractPrice1s(
            instrument="BTCUSDT",
            ts_event_ns=1,
            open=1.0,
            high=Decimal("2"),
            low=Decimal("1"),
            close=Decimal("2"),
            volume=Decimal("0"),
            source_encoding="DECIMAL_TEXT",
        )


def test_historical_fields_are_null_only_and_unknown_rejected() -> None:
    row = HistoricalEvidenceRow(evidence_level="H2", reference_price_type="TRADE")
    assert row.reference_ask is None
    with pytest.raises(ValidationError):
        HistoricalEvidenceRow(evidence_level="H2", reference_price_type="TRADE", spread_bps=0)
    with pytest.raises(ValidationError):
        HistoricalEvidenceRow(evidence_level="H1", reference_price_type="CONTRACT", unknown=1)


def test_quality_round_trip() -> None:
    q = DataQuality(
        instrument="ETHUSDT",
        issue_code="GAP",
        severity="WARN",
        date=date(2020, 1, 1),
        count=2,
    )
    assert DataQuality.model_validate_json(q.model_dump_json()) == q
