import pytest
from era100x.data.evidence import historical_evidence

FIELDS = [
    "reference_ask",
    "bid",
    "spread_bps",
    "ts_recv_ns",
    "receive_latency_ms",
    "queue_position",
    "partial_fill",
    "actual_slippage_bps",
]


def test_all_unavailable_fields_round_trip_as_null() -> None:
    row = historical_evidence("H2", "TRADE", **{f: None for f in FIELDS})
    assert all(getattr(row, f) is None for f in FIELDS)


@pytest.mark.parametrize("field", FIELDS)
def test_ut_data_013_zero_or_fact_is_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="must be NULL"):
        historical_evidence("H1", "CONTRACT", **{field: 0})
