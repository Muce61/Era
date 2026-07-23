from decimal import Decimal

from era100x.research.stage_2.contracts.models import RawKeyLevel
from era100x.research.stage_2.key_levels.arbitration import arbitrate_key_levels


def raw(identifier: str, price: str, priority: int, formed: int) -> RawKeyLevel:
    return RawKeyLevel(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=formed,
        raw_key_level_id=identifier * 64,
        source_type="range_low" if priority < 5 else "rolling_low_5m",
        source_id=f"source-{identifier}",
        source_timeframe="1D" if priority == 1 else "5m",
        source_start_ts=formed - 10,
        source_end_ts=formed,
        level_price=Decimal(price),
        priority=priority,
        quality_status="ACCEPTED",
    )


def test_arbitration_is_permutation_invariant_and_preserves_members() -> None:
    low_priority = raw("a", "100", 5, 100)
    high_priority = raw("b", "100.05", 1, 101)
    first = arbitrate_key_levels(
        [low_priority, high_priority], merge_tolerance_bps=Decimal("10"), expires_at_ns=1000
    )
    second = arbitrate_key_levels(
        [high_priority, low_priority], merge_tolerance_bps=Decimal("10"), expires_at_ns=1000
    )
    assert first == second
    assert first[0].level_price == Decimal("100.05")
    assert first[0].member_key_level_ids == ("a" * 64, "b" * 64)
    assert first[0].available_at_ts == 101


def test_exact_tolerance_is_not_merged_and_expiry_is_explicit() -> None:
    left = raw("a", "100", 1, 100)
    right = raw("b", "100.1", 5, 100)
    result = arbitrate_key_levels(
        [left, right], merge_tolerance_bps=Decimal("10"), expires_at_ns=200
    )
    assert len(result) == 2
    assert {item.expires_at_ns for item in result} == {200}
