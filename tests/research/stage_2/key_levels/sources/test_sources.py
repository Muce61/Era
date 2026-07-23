from decimal import Decimal

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.key_levels.sources.common import SourceLineage
from era100x.research.stage_2.key_levels.sources.range_low import generate_range_lows
from era100x.research.stage_2.key_levels.sources.rolling_low_1m import generate_rolling_lows_1m
from era100x.research.stage_2.key_levels.sources.rolling_low_5m import generate_rolling_lows_5m


LINEAGE = SourceLineage("stage1", "1" * 64, "2" * 64, "abcdef0", "G1-PRIMARY-V1")


def bars(count: int, seconds: int, instrument: str = "BTCUSDT") -> list[ContractBar]:
    return [
        ContractBar(
            instrument=instrument,
            source_type="CONTRACT",
            interval_seconds=seconds,
            bucket_start_ns=i * seconds * 1_000_000_000,
            open=Decimal("101"),
            high=Decimal("102"),
            low=Decimal(100 - i),
            close=Decimal("101"),
            volume=Decimal("1"),
        )
        for i in range(count)
    ]


def test_rolling_sources_use_only_closed_window() -> None:
    one_minute = bars(61, 60)
    first = generate_rolling_lows_1m(one_minute[:60], LINEAGE)
    perturbed_future = list(one_minute)
    perturbed_future[-1] = perturbed_future[-1].model_copy(update={"low": Decimal("1")})
    assert first == generate_rolling_lows_1m(perturbed_future[:60], LINEAGE)
    assert first[0].available_at_ts == 60 * 60 * 1_000_000_000
    assert first[0].level_price == Decimal("41")

    five_minute = generate_rolling_lows_5m(bars(12, 300), LINEAGE)
    assert len(five_minute) == 1
    assert five_minute[0].source_type == "rolling_low_5m"


def test_range_sources_are_independent_and_instrument_isolated() -> None:
    btc = generate_range_lows(bars(1, 86400), "1D", LINEAGE)[0]
    eth = generate_range_lows(bars(1, 86400, "ETHUSDT"), "1D", LINEAGE)[0]
    assert btc.priority == 1
    assert btc.available_at_ts == 86400 * 1_000_000_000
    assert btc.raw_key_level_id != eth.raw_key_level_id
