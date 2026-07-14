from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.contracts.models import EvidenceFields, ExitOrderLeg


def test_historical_execution_fields_can_be_null() -> None:
    row = EvidenceFields(
        reference_price=Decimal("1"),
        reference_ask=None,
        spread_bps=None,
        receive_latency_ms=None,
        actual_fill_price=None,
        scenario_slippage_bps=None,
        data_quality="OK",
        evidence_level="H1",
        cost_scenario_id=None,
    )
    assert row.reference_ask is None


def test_float_rejected_for_decimal_field() -> None:
    with pytest.raises(ValidationError):
        EvidenceFields(
            reference_price=1.0,
            reference_ask=None,
            spread_bps=None,
            receive_latency_ms=None,
            actual_fill_price=None,
            scenario_slippage_bps=None,
            data_quality="OK",
            evidence_level="H1",
            cost_scenario_id=None,
        )


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceFields.model_validate({"unexpected": True})


def test_exit_leg_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        ExitOrderLeg.model_validate({"exit_order_leg_id": "leg-1"})
