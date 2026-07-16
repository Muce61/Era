from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel, ReclaimEvent
from era100x.research.stage_2.episodes.hold import detect_hold

SECOND = 1_000_000_000


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
        expires_at_ns=100 * SECOND,
        status="ACTIVE",
        reason_code="TEST",
    )


def reclaim() -> ReclaimEvent:
    return ReclaimEvent(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=3 * SECOND,
        reclaim_id="5" * 64,
        sweep_id="6" * 64,
        reclaim_ts=2 * SECOND,
        reclaim_price=Decimal("100.01"),
        status="RECLAIMED",
        reason_code="RECLAIM_CONFIRMED",
    )


def price(ts: int, low: str) -> ContractPrice1s:
    value = Decimal(low)
    return ContractPrice1s(
        instrument="BTCUSDT",
        ts_event_ns=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=value,
        close=Decimal("100"),
        volume=Decimal("1"),
        source_encoding="DECIMAL_TEXT",
    )


def test_hold_passes_complete_window_and_equal_failure_boundary() -> None:
    rows = [price((3 + i) * SECOND, "99.99") for i in range(3)]
    event = detect_hold(
        reclaim(), level(), rows, hold_window_seconds=3, failure_buffer_bps=Decimal("1")
    )
    assert event.hold_result == "PASS"
    assert event.available_at_ts == 6 * SECOND


def test_hold_fails_strict_break_without_trigger_input() -> None:
    rows = [price(3 * SECOND, "99.989")]
    event = detect_hold(
        reclaim(), level(), rows, hold_window_seconds=3, failure_buffer_bps=Decimal("1")
    )
    assert event.hold_result == "FAIL"
    assert event.available_at_ts == 4 * SECOND
    assert event.failure_reason == "HOLD_FAILURE_BREAK"


def test_incomplete_or_end_boundary_data_does_not_pass() -> None:
    rows = [price(3 * SECOND, "100"), price(6 * SECOND, "100")]
    event = detect_hold(
        reclaim(), level(), rows, hold_window_seconds=3, failure_buffer_bps=Decimal("1")
    )
    assert event.hold_result == "INSUFFICIENT_WINDOW"
    assert event.available_at_ts == 6 * SECOND
