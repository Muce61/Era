from decimal import Decimal

import pytest

from era100x.research.stage_2.contracts.identity import stable_id
from era100x.research.stage_2.contracts.models import RawKeyLevel


BASE = {
    "instrument": "BTCUSDT",
    "data_run_id": "stage1",
    "dataset_logical_hash": "1" * 64,
    "config_hash": "2" * 64,
    "code_version": "abcdef0",
    "parameter_set_id": "G1-PRIMARY-V1",
    "available_at_ts": 120,
}


def test_raw_level_rejects_future_availability_and_unknown_fields() -> None:
    payload = {
        **BASE,
        "raw_key_level_id": "3" * 64,
        "source_type": "rolling_low_1m",
        "source_id": "source",
        "source_timeframe": "1m",
        "source_start_ts": 0,
        "source_end_ts": 121,
        "level_price": Decimal("100"),
        "priority": 6,
        "quality_status": "ACCEPTED",
    }
    with pytest.raises(ValueError, match="source closes"):
        RawKeyLevel.model_validate(payload)
    payload["source_end_ts"] = 120
    payload["future_label"] = "forbidden"
    with pytest.raises(ValueError, match="Extra inputs"):
        RawKeyLevel.model_validate(payload)


def test_stable_id_is_decimal_exact_and_instrument_isolated() -> None:
    first = stable_id("key-level", "v1", "BTCUSDT", Decimal("100.00"), 1)
    assert first == stable_id("key-level", "v1", "BTCUSDT", Decimal("100.00"), 1)
    assert first != stable_id("key-level", "v1", "ETHUSDT", Decimal("100.00"), 1)
    with pytest.raises(TypeError, match="binary floats"):
        stable_id("key-level", "v1", "BTCUSDT", 100.0)
