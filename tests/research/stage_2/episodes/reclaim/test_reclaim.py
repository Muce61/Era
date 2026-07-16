from decimal import Decimal

from era100x.data.schema.models import ContractPrice1s
from era100x.research.stage_2.contracts.models import CanonicalKeyLevel, SweepEpisode
from era100x.research.stage_2.episodes.reclaim import detect_reclaim


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


def sweep() -> SweepEpisode:
    return SweepEpisode(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=2_000_000_000,
        sweep_id="5" * 64,
        key_level_id="3" * 64,
        sweep_start_ts=1_000_000_000,
        sweep_detection_ts=2_000_000_000,
        sweep_extreme_ts=1_000_000_000,
        sweep_extreme_price=Decimal("99.98"),
        sweep_depth=Decimal("2"),
        pre_sweep_reference=Decimal("100"),
        status="DETECTED",
        reason_code="SWEEP_CONFIRMED",
    )


def price(ts: int, close: str) -> ContractPrice1s:
    value = Decimal(close)
    return ContractPrice1s(
        instrument="BTCUSDT",
        ts_event_ns=ts,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
        source_encoding="DECIMAL_TEXT",
    )


def test_normal_reclaim_and_available_time() -> None:
    event = detect_reclaim(
        sweep(),
        level(),
        [price(2_000_000_000, "100.01")],
        reclaim_buffer_bps=Decimal("1"),
        timeout_seconds=30,
    )
    assert event.status == "RECLAIMED"
    assert event.reclaim_ts == 2_000_000_000
    assert event.available_at_ts == 3_000_000_000


def test_end_boundary_is_excluded_and_times_out() -> None:
    at_deadline = price(31_000_000_000, "101")
    event = detect_reclaim(
        sweep(), level(), [at_deadline], reclaim_buffer_bps=Decimal("1"), timeout_seconds=30
    )
    assert event.status == "TIMED_OUT"
    assert event.available_at_ts == 32_000_000_000


def test_hold_outcome_cannot_change_reclaim() -> None:
    rows = [price(2_000_000_000, "100.01")]
    assert detect_reclaim(
        sweep(), level(), rows, reclaim_buffer_bps=Decimal("1"), timeout_seconds=15
    ) == detect_reclaim(sweep(), level(), rows, reclaim_buffer_bps=Decimal("1"), timeout_seconds=15)
