from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel
from era100x.research.stage_2.episodes.sweep import detect_sweep


def level() -> CanonicalKeyLevel:
    return CanonicalKeyLevel(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=1,
        key_level_id="3" * 64,
        source_type="range_low",
        source_id="source",
        source_timeframe="1H",
        source_start_ts=0,
        source_end_ts=1,
        level_price=Decimal("100"),
        priority=3,
        normalization_group="group",
        member_key_level_ids=("4" * 64,),
        formed_at_ns=1,
        expires_at_ns=100_000_000_000,
        status="ACTIVE",
        reason_code="TEST",
    )


def price(ts: int, low: str, close: str = "100") -> ContractPrice1s:
    return ContractPrice1s(
        instrument="BTCUSDT",
        ts_event_ns=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        source_encoding="DECIMAL_TEXT",
    )


def test_sweep_threshold_and_detection_time_are_causal() -> None:
    rows = [price(0, "100"), price(1_000_000_000, "99.98", "99.99")]
    sweep = detect_sweep(level(), rows, confirmation_bps=Decimal("2"))
    assert sweep is not None
    assert sweep.status == "DETECTED"
    assert sweep.sweep_start_ts == 1_000_000_000
    assert sweep.sweep_detection_ts == 2_000_000_000
    assert sweep.available_at_ts == sweep.sweep_detection_ts
    assert detect_sweep(level(), rows, confirmation_bps=Decimal("5")) is None


def test_excessive_depth_invalidates_without_reclaim_input() -> None:
    sweep = detect_sweep(level(), [price(0, "99.70")], confirmation_bps=Decimal("2"))
    assert sweep is not None
    assert sweep.status == "INVALIDATED"
    assert sweep.reason_code == "SWEEP_DEPTH_EXCEEDED"


def test_future_prices_do_not_change_detection_snapshot() -> None:
    initial = [price(0, "99.98")]
    detected = detect_sweep(level(), initial, confirmation_bps=Decimal("2"))
    assert detected == detect_sweep(
        level(), initial + [price(1_000_000_000, "99.90")], confirmation_bps=Decimal("2")
    )
