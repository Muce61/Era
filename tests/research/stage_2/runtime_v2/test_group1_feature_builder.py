from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from era100x.data.schema.models import ContractBar
from era100x.research.stage_2.pipelines.candidates import price_phase
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash
from era100x.research.stage_2.runtime_v2.foundation_build import (
    CONTRACT_PRICE_SCHEMA,
    PRICE_BAR_SCHEMA,
    TRADE_PRIMITIVE_SCHEMA,
)
from era100x.research.stage_2.runtime_v2.group1_feature_builder import (
    FLOW_DATASETS,
    PRICE_DATASETS,
    PRICE_PRE_FINALIZATION_DATASETS,
    FeatureFoundationContractError,
    Group1Lineage,
    _contract_bars,
    _contract_prices,
    _project_direct_price_records,
    build_flow_owner_day_from_primitives,
    build_group1_feature_range,
    build_price_processing_day_from_features,
    compare_group1_legacy_projection,
)

SECOND_NS = 1_000_000_000
DAY_NS = 86_400 * SECOND_NS
OWNER = date(2020, 1, 2)
OWNER_START = int(datetime(2020, 1, 2, tzinfo=UTC).timestamp()) * SECOND_NS
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
LINEAGE = Group1Lineage(
    data_run_id="stage1-fixture",
    dataset_logical_hash=HASH_A,
    config_hash=HASH_B,
    code_version="abcdef0",
)


def _sparse_frame(start_ns: int, minutes: int) -> pl.DataFrame:
    timestamps = [start_ns + minute * 60 * SECOND_NS for minute in range(minutes)]
    return pl.DataFrame(
        {
            "ts_event_ns": timestamps,
            "open": [100.0] * minutes,
            "high": [101.0] * minutes,
            "low": [99.0] * minutes,
            "close": [100.0] * minutes,
            "volume": [1.0] * minutes,
        }
    )


def _price_table(frame: pl.DataFrame, instrument: str = "BTCUSDT") -> pa.Table:
    timestamps = frame["ts_event_ns"].to_list()
    return pa.Table.from_pydict(
        {
            "instrument": [instrument] * len(timestamps),
            "event_ts_ns": timestamps,
            "available_at_ns": [item + SECOND_NS for item in timestamps],
            "open": [Decimal(str(item)) for item in frame["open"].to_list()],
            "high": [Decimal(str(item)) for item in frame["high"].to_list()],
            "low": [Decimal(str(item)) for item in frame["low"].to_list()],
            "close": [Decimal(str(item)) for item in frame["close"].to_list()],
            "volume": [Decimal(str(item)) for item in frame["volume"].to_list()],
            "source_file_sha256": [HASH_C] * len(timestamps),
        },
        schema=CONTRACT_PRICE_SCHEMA,
    )


def _bar_table(frame: pl.DataFrame, instrument: str = "BTCUSDT") -> pa.Table:
    bars: list[ContractBar] = []
    for interval in (60, 300, 900, 3600, 14_400, 86_400):
        bars.extend(price_phase._bars(frame, instrument, interval))
    return pa.Table.from_pydict(
        {
            "instrument": [item.instrument for item in bars],
            "interval_seconds": [item.interval_seconds for item in bars],
            "event_ts_ns": [item.bucket_start_ns for item in bars],
            "available_at_ns": [
                item.bucket_start_ns + item.interval_seconds * SECOND_NS for item in bars
            ],
            "open": [item.open for item in bars],
            "high": [item.high for item in bars],
            "low": [item.low for item in bars],
            "close": [item.close for item in bars],
            "volume": [item.volume for item in bars],
            "source_file_sha256": [HASH_C] * len(bars),
        },
        schema=PRICE_BAR_SCHEMA,
    )


def _empty_foundation() -> tuple[pa.Table, pa.Table, pa.Table]:
    return (
        pa.Table.from_batches([], schema=CONTRACT_PRICE_SCHEMA),
        pa.Table.from_batches([], schema=PRICE_BAR_SCHEMA),
        pa.Table.from_batches([], schema=TRADE_PRIMITIVE_SCHEMA),
    )


def _window() -> dict[str, Any]:
    end = OWNER_START + 100 * SECOND_NS
    return {
        "instrument": "BTCUSDT",
        "direction": "LONG",
        "canonical_key_level_id": "1" * 64,
        "sweep_id": "2" * 64,
        "reclaim_id": "3" * 64,
        "hold_id": "4" * 64,
        "trigger_id": "5" * 64,
        "time_combination_id": "T2",
        "parameter_set_id": "G1-PRIMARY-V1",
        "available_at_ts": end,
        "data_run_id": "stage1-fixture",
        "dataset_logical_hash": HASH_A,
        "config_hash": HASH_B,
        "code_version": "abcdef0",
        "venue": "BINANCE_USDM",
        "sweep_start_ns": OWNER_START + 60 * SECOND_NS,
        "market_episode_id": "6" * 64,
        "canonical_candidate_id": "7" * 64,
        "canonical_payload_hash": "8" * 64,
        "variant_id": "V1_PRICE",
        "research_role": "PRIMARY",
        "primary_eligible": True,
        "candidate_version_id": "7" * 64,
        "trigger_available_at_ts": end,
        "window_start_ts": end - 5 * SECOND_NS,
        "window_end_ts": end,
        "event_parameter_set_id": "G1-PRIMARY-V1",
        "owner_partition": OWNER.isoformat(),
    }


def _trade_primitive_table() -> pa.Table:
    end = OWNER_START + 100 * SECOND_NS
    starts = [end - 5 * SECOND_NS, end - SECOND_NS]
    return pa.Table.from_pydict(
        {
            "instrument": ["BTCUSDT", "BTCUSDT"],
            "event_ts_ns": starts,
            "second_end_ns": [item + SECOND_NS for item in starts],
            "available_at_ns": [item + SECOND_NS for item in starts],
            "trade_count": [1, 2],
            "aggressor_buy_count": [0, 2],
            "aggressor_sell_count": [1, 0],
            "aggressor_buy_qty": [Decimal("0"), Decimal("4")],
            "aggressor_sell_qty": [Decimal("1"), Decimal("0")],
            "signed_qty": [Decimal("-1"), Decimal("4")],
            "source_logical_hash": [HASH_A, HASH_A],
        },
        schema=TRADE_PRIMITIVE_SCHEMA,
    )


def _trade_primitive_mapping() -> dict[int, dict[str, Any]]:
    table = _trade_primitive_table()
    return {
        int(table["event_ts_ns"][index].as_py()): {
            "trade_count": int(table["trade_count"][index].as_py()),
            "aggressor_buy_qty": table["aggressor_buy_qty"][index].as_py(),
            "aggressor_sell_qty": table["aggressor_sell_qty"][index].as_py(),
        }
        for index in range(table.num_rows)
    }


def test_price_feature_builder_matches_approved_v1_fixed_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _sparse_frame(OWNER_START - DAY_NS, 1_440)
    current = _sparse_frame(OWNER_START, 120)
    following = _sparse_frame(OWNER_START + DAY_NS, 3)
    frames = {
        OWNER - timedelta(days=1): previous,
        OWNER: current,
        OWNER + timedelta(days=1): following,
    }
    monkeypatch.setattr(
        price_phase,
        "_path",
        lambda _root, _instrument, observed: Path(observed.isoformat()),
    )
    monkeypatch.setattr(
        price_phase,
        "_read",
        lambda path: frames[date.fromisoformat(path.name)],
    )
    expected = price_phase.build_price_day(
        contract_root=Path("/not-read"),
        instrument="BTCUSDT",
        day=OWNER,
        data_run_id=LINEAGE.data_run_id,
        dataset_logical_hash=LINEAGE.dataset_logical_hash,
        config_hash=LINEAGE.config_hash,
        code_version=LINEAGE.code_version,
    )
    combined = pl.concat((previous, current, following)).sort("ts_event_ns")
    # Exercise the real Arrow Decimal128 boundary.  Fixed scale padding must
    # not change any V1 identifier or daily legacy hash.
    prices = _contract_prices(_price_table(combined), "BTCUSDT")
    bars = _contract_bars(_bar_table(combined), "BTCUSDT")
    actual = build_price_processing_day_from_features(
        instrument="BTCUSDT",
        processing_date=OWNER,
        contract_prices=prices,
        causal_bars=bars,
        lineage=LINEAGE,
    )

    assert tuple(actual) == tuple(expected)
    for dataset in expected:
        assert records_logical_hash(actual[dataset], dataset) == records_logical_hash(
            expected[dataset], dataset
        )

    streamed: dict[str, list[dict[str, Any]]] = {
        dataset: [] for dataset in PRICE_PRE_FINALIZATION_DATASETS
    }
    retained = build_price_processing_day_from_features(
        instrument="BTCUSDT",
        processing_date=OWNER,
        contract_prices=prices,
        causal_bars=bars,
        lineage=LINEAGE,
        record_sink=lambda dataset, record: streamed[dataset].append(dict(record)),
        retained_outputs=frozenset({"candidate_attempts"}),
    )
    assert tuple(retained) == ("candidate_attempts",)
    assert retained["candidate_attempts"] == expected["candidate_attempts"]
    assert streamed == {dataset: expected[dataset] for dataset in PRICE_PRE_FINALIZATION_DATASETS}


def test_flow_primitives_match_approved_raw_trade_reader(tmp_path: Path) -> None:
    end = OWNER_START + 100 * SECOND_NS
    path = tmp_path / "trades.parquet"
    pl.DataFrame(
        {
            "ts_event_ns": [end - 5 * SECOND_NS, end - SECOND_NS, end - SECOND_NS + 1],
            "quantity": ["1", "2", "2"],
            "aggressor_side": ["SELL", "BUY", "BUY"],
            "canonical_trade_id": ["1" * 64, "2" * 64, "3" * 64],
        }
    ).with_columns(pl.col("quantity").cast(pl.Decimal(38, 18))).write_parquet(path)
    expected = build_flow_day(
        trade_paths=(path,),
        instrument="BTCUSDT",
        windows=[_window()],
        processing_partition=OWNER.isoformat(),
    )
    actual = build_flow_owner_day_from_primitives(
        instrument="BTCUSDT",
        owner_date=OWNER,
        windows=[_window()],
        trade_seconds=_trade_primitive_mapping(),
        trade_source_day_status={OWNER: "COMPLETE"},
    )

    assert actual == expected


def test_missing_primitive_is_zero_only_for_complete_source_day() -> None:
    complete = build_flow_owner_day_from_primitives(
        instrument="BTCUSDT",
        owner_date=OWNER,
        windows=[_window()],
        trade_seconds=_trade_primitive_mapping(),
        trade_source_day_status={OWNER: "COMPLETE"},
    )
    incomplete = build_flow_owner_day_from_primitives(
        instrument="BTCUSDT",
        owner_date=OWNER,
        windows=[_window()],
        trade_seconds=_trade_primitive_mapping(),
        trade_source_day_status={OWNER: "INCOMPLETE"},
    )

    assert complete["flow_features"][0]["status"] == "PASS"
    assert len(complete["candidate_attempts"]) == 1
    assert incomplete["flow_features"][0]["status"] == "UNAVAILABLE"
    assert incomplete["flow_features"][0]["signed_quantity_imbalance"] is None
    assert incomplete["candidate_attempts"] == []


@pytest.mark.parametrize(
    ("buy", "sell", "expected_buy", "expected_sell"),
    (
        (Decimal("2.000000000000000000"), Decimal("0E-18"), "4.000000000000000000", "0"),
        (Decimal("0E-18"), Decimal("2.000000000000000000"), "0", "4.000000000000000000"),
        (Decimal("0E-18"), Decimal("0E-18"), "0", "0"),
    ),
)
def test_flow_zero_side_uses_v1_decimal_zero_without_losing_nonzero_scale(
    buy: Decimal,
    sell: Decimal,
    expected_buy: str,
    expected_sell: str,
) -> None:
    end = OWNER_START + 100 * SECOND_NS
    trade_seconds = {
        end - 5 * SECOND_NS: {
            "trade_count": 1,
            "aggressor_buy_qty": buy,
            "aggressor_sell_qty": sell,
        },
        end - SECOND_NS: {
            "trade_count": 2,
            "aggressor_buy_qty": buy,
            "aggressor_sell_qty": sell,
        },
    }
    result = build_flow_owner_day_from_primitives(
        instrument="BTCUSDT",
        owner_date=OWNER,
        windows=[_window()],
        trade_seconds=trade_seconds,
        trade_source_day_status={OWNER: "COMPLETE"},
    )
    feature = result["flow_features"][0]
    assert feature["buy_quantity"] == expected_buy
    assert feature["sell_quantity"] == expected_sell


def test_range_contract_always_emits_exactly_thirteen_approved_datasets() -> None:
    prices, bars, trades = _empty_foundation()
    result = build_group1_feature_range(
        instrument="BTCUSDT",
        owner_dates=(OWNER,),
        contract_price_1s=prices,
        causal_price_bars=bars,
        trade_second_primitives=trades,
        trade_source_day_status={OWNER: "COMPLETE"},
        lineage=LINEAGE,
    )
    day = result.day(OWNER)

    assert tuple(day.price) == PRICE_DATASETS
    assert tuple(day.flow) == FLOW_DATASETS
    assert len(day.legacy_hashes()) == 13
    assert all(not records for records in (*day.price.values(), *day.flow.values()))


def test_seven_upstream_price_facts_preserve_v1_processing_date_across_midnight() -> None:
    next_day = OWNER + timedelta(days=1)
    next_day_ns = OWNER_START + DAY_NS + SECOND_NS
    processing_output = {
        dataset: [
            {
                "dataset": dataset,
                "available_at_ts": next_day_ns,
            }
        ]
        for dataset in PRICE_PRE_FINALIZATION_DATASETS
    }
    # Arbitration has no timestamp in the formal V1 record.  Its partition is
    # inherited from the canonical processing task, not inferred later.
    processing_output["arbitration"] = [{"dataset": "arbitration"}]

    projected = _project_direct_price_records(
        ((OWNER, processing_output),),
        (OWNER, next_day),
    )

    assert all(
        len(projected[OWNER.isoformat()][dataset]) == 1
        for dataset in PRICE_PRE_FINALIZATION_DATASETS
    )
    assert all(
        projected[next_day.isoformat()][dataset] == []
        for dataset in PRICE_PRE_FINALIZATION_DATASETS
    )


def test_legacy_projection_comparison_scales_to_preregistered_thirty_days() -> None:
    prices, bars, trades = _empty_foundation()
    owner_dates = tuple(OWNER + timedelta(days=offset) for offset in range(30))
    result = build_group1_feature_range(
        instrument="BTCUSDT",
        owner_dates=owner_dates,
        contract_price_1s=prices,
        causal_price_bars=bars,
        trade_second_primitives=trades,
        trade_source_day_status={owner: "COMPLETE" for owner in owner_dates},
        lineage=LINEAGE,
    )
    expected = {
        item.owner_date: {
            "V1_PRICE": item.price,
            "V1_FLOW": item.flow,
        }
        for item in result.days
    }
    comparisons = compare_group1_legacy_projection(result, expected)

    assert len(comparisons) == 30 * 13
    assert all(item.matches for item in comparisons)


def test_foundation_input_fails_closed_on_cross_instrument_rows() -> None:
    frame = _sparse_frame(OWNER_START, 1)
    with pytest.raises(FeatureFoundationContractError, match="mixes instruments"):
        build_group1_feature_range(
            instrument="BTCUSDT",
            owner_dates=(OWNER,),
            contract_price_1s=_price_table(frame, "ETHUSDT"),
            causal_price_bars=pa.Table.from_batches([], schema=PRICE_BAR_SCHEMA),
            trade_second_primitives=pa.Table.from_batches([], schema=TRADE_PRIMITIVE_SCHEMA),
            trade_source_day_status={OWNER: "COMPLETE"},
            lineage=LINEAGE,
        )


def test_flow_result_is_independent_of_primitive_input_order() -> None:
    forward = _trade_primitive_table()
    reverse = forward.take(pa.array([1, 0], type=pa.int64()))
    empty_prices, empty_bars, _ = _empty_foundation()
    common = {
        "instrument": "BTCUSDT",
        "owner_dates": (OWNER,),
        "contract_price_1s": empty_prices,
        "causal_price_bars": empty_bars,
        "trade_source_day_status": {OWNER: "COMPLETE"},
        "lineage": LINEAGE,
    }
    # No Flow window is produced by the empty PRICE setup, so exercise the
    # primitive parser through the full public boundary and require identical
    # thirteen-partition hashes.
    first = build_group1_feature_range(trade_second_primitives=forward, **common)
    second = build_group1_feature_range(trade_second_primitives=reverse, **common)

    assert first.day(OWNER).legacy_hashes() == second.day(OWNER).legacy_hashes()
