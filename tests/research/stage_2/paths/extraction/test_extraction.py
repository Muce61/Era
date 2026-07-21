from __future__ import annotations

import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.data.schema.models import ContractPrice1s, NormalizedTrade
from era100x.research.stage_2.contracts.models import MarketEpisode
from era100x.research.stage_2.paths.extraction import PathSource, extract_historical_path

S = 1_000_000_000
H1_HASH = "1" * 64
H2_HASH = "2" * 64


def episode(instrument: str = "BTCUSDT") -> MarketEpisode:
    return MarketEpisode.model_validate(
        {
            "instrument": instrument,
            "data_run_id": "stage1-baseline",
            "dataset_logical_hash": "a" * 64,
            "config_hash": "b" * 64,
            "code_version": "abcdef0",
            "parameter_set_id": "G1-PRIMARY-V1",
            "available_at_ts": 10 * S,
            "market_episode_id": "c" * 64,
            "canonical_candidate_id": "d" * 64,
            "candidate_version_id": "d" * 64,
            "canonical_payload_hash": "e" * 64,
            "venue": "BINANCE_USDM",
            "canonical_key_level_id": "level",
            "sweep_id": "sweep",
            "reclaim_id": "reclaim",
            "hold_id": "hold",
            "trigger_id": "trigger",
            "flow_feature_set_id": None,
            "variant": "V1_PRICE",
            "variant_id": "V1_PRICE",
            "time_combination_id": "T2",
            "research_role": "PRIMARY",
            "primary_eligible": True,
            "sweep_start_ns": 1 * S,
            "episode_status": "CANDIDATE",
        }
    )


def source(level: str, instrument: str = "BTCUSDT") -> PathSource:
    return PathSource.model_validate(
        {
            "instrument": instrument,
            "evidence_level": level,
            "reference_price_type": "CONTRACT" if level == "H1" else "TRADE",
            "data_run_id": "stage1-baseline",
            "dataset_logical_hash": H1_HASH if level == "H1" else H2_HASH,
            "source_manifest_hash": "3" * 64,
        }
    )


def bar(ts: int, close: str = "100", instrument: str = "BTCUSDT") -> ContractPrice1s:
    price = Decimal(close)
    return ContractPrice1s.model_validate(
        {
            "instrument": instrument,
            "ts_event_ns": ts,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": Decimal("5"),
            "source_encoding": "DECIMAL_TEXT",
        }
    )


def trade(
    venue_id: int,
    ts: int,
    *,
    canonical: str | None = None,
    conflict: bool = False,
    instrument: str = "BTCUSDT",
) -> NormalizedTrade:
    return NormalizedTrade.model_validate(
        {
            "instrument": instrument,
            "venue_trade_id": venue_id,
            "canonical_trade_id": canonical or f"{venue_id:064x}",
            "identity_status": "CONFLICTING_VENUE_ID" if conflict else "UNIQUE_VENUE_ID",
            "venue_trade_id_conflict_group": f"{instrument}:{venue_id}" if conflict else None,
            "price": Decimal("100"),
            "quantity": Decimal("1"),
            "quote_quantity": Decimal("100"),
            "ts_event_ns": ts,
            "is_buyer_maker": False,
            "aggressor_side": "BUY",
            "source_sha256": "4" * 64,
        }
    )


def extract(
    h1_rows: list[ContractPrice1s],
    h2_rows: list[NormalizedTrade],
    *,
    market_episode: MarketEpisode | None = None,
    start: int = 10 * S,
    end: int = 13 * S,
):
    selected_episode = market_episode or episode()
    return extract_historical_path(
        episode=selected_episode,
        h1_rows=h1_rows,
        h2_rows=h2_rows,
        h1_source=source("H1", selected_episode.instrument),
        h2_source=source("H2", selected_episode.instrument),
        window_start_ns=start,
        window_end_ns=end,
    )


def test_extracts_h1_h2_in_utc_left_closed_right_open_window() -> None:
    result = extract(
        [bar(9 * S), bar(10 * S), bar(11 * S), bar(12 * S), bar(13 * S)],
        [trade(9, 9 * S), trade(10, 10 * S), trade(11, 12 * S), trade(12, 13 * S)],
    )

    assert [point.ts_event_ns for point in result.h1_points] == [10 * S, 11 * S, 12 * S]
    assert [point.venue_trade_id for point in result.h2_points] == [10, 11]
    assert result.h1_outside_window_count == 2
    assert result.h2_outside_window_count == 2
    assert result.time_semantics == "UTC_EVENT_NS_LEFT_CLOSED_RIGHT_OPEN"
    assert result.quality_status == "COMPLETE"
    assert "real_return" in result.prohibited_execution_fields


def test_h2_same_timestamp_uses_v2_stable_order_and_shuffle_is_deterministic() -> None:
    rows = [
        trade(12, 10 * S, canonical="c" * 64),
        trade(11, 10 * S, canonical="f" * 64),
        trade(11, 10 * S, canonical="a" * 64, conflict=True),
    ]
    shuffled = list(rows)
    random.Random(20260721).shuffle(shuffled)

    first = extract([bar(10 * S)], rows)
    second = extract([bar(10 * S)], shuffled)

    assert first == second
    assert first.output_hash == second.output_hash
    assert [
        (point.ts_event_ns, point.venue_trade_id, point.canonical_trade_id)
        for point in first.h2_points
    ] == [
        (10 * S, 11, "a" * 64),
        (10 * S, 11, "f" * 64),
        (10 * S, 12, "c" * 64),
    ]


def test_conflicting_venue_ids_are_preserved_not_deduplicated() -> None:
    result = extract(
        [bar(10 * S), bar(11 * S), bar(12 * S)],
        [
            trade(10, 10 * S, canonical="a" * 64, conflict=True),
            trade(10, 10 * S, canonical="b" * 64, conflict=True),
        ],
    )

    assert len(result.h2_points) == 2
    assert result.h2_duplicate_count == 0
    assert result.ambiguity_codes == ("H2_CONFLICTING_VENUE_ID",)
    assert result.quality_status == "AMBIGUOUS"


def test_canonical_fact_identity_folds_only_exact_repeated_fact() -> None:
    repeated = trade(10, 10 * S)
    result = extract([bar(10 * S)], [repeated, repeated])

    assert len(result.h2_points) == 1
    assert result.h2_duplicate_count == 1

    conflicting_payload = repeated.model_copy(update={"price": Decimal("101")})
    with pytest.raises(ValueError, match="canonical historical fact identity"):
        extract([bar(10 * S)], [repeated, conflicting_payload])


def test_h1_and_h2_gaps_are_auditable() -> None:
    result = extract(
        [bar(10 * S), bar(12 * S)],
        [trade(10, 10 * S), trade(13, 12 * S)],
    )

    assert [(gap.reason_code, gap.missing_count) for gap in result.gaps] == [
        ("H1_MISSING_SECONDS", 1),
        ("H2_VENUE_TRADE_ID_GAP", 2),
    ]
    assert result.quality_status == "WITH_GAPS"


def test_h1_leading_trailing_and_empty_window_gaps_are_auditable() -> None:
    partial = extract([bar(11 * S)], [trade(10, 10 * S)])
    assert [
        (gap.preceding_ts_event_ns, gap.following_ts_event_ns, gap.missing_count)
        for gap in partial.gaps
    ] == [
        (10 * S, 11 * S, 1),
        (11 * S, 13 * S, 1),
    ]

    empty = extract([], [trade(10, 10 * S)])
    assert len(empty.gaps) == 1
    assert empty.gaps[0].missing_count == 3


def test_event_time_venue_id_reversal_is_retained_and_marked_ambiguous() -> None:
    result = extract(
        [bar(10 * S), bar(11 * S), bar(12 * S)],
        [trade(20, 10 * S), trade(19, 11 * S)],
    )

    assert result.gaps[0].reason_code == "H2_VENUE_TRADE_ID_REVERSAL"
    assert result.ambiguity_codes == ("H2_EVENT_TIME_VENUE_REVERSAL",)
    assert result.quality_status == "WITH_GAPS_AND_AMBIGUITY"


def test_h1_conflicting_same_second_is_preserved_and_marked_ambiguous() -> None:
    result = extract([bar(10 * S, "100"), bar(10 * S, "101")], [trade(10, 10 * S)])

    assert len(result.h1_points) == 2
    assert result.ambiguity_codes == ("H1_CONFLICTING_SAME_SECOND",)


def test_episode_lineage_is_preserved() -> None:
    market_episode = episode("ETHUSDT")
    result = extract(
        [bar(10 * S, instrument="ETHUSDT")],
        [trade(10, 10 * S, instrument="ETHUSDT")],
        market_episode=market_episode,
    )

    assert result.instrument == "ETHUSDT"
    assert result.market_episode_id == market_episode.market_episode_id
    assert result.canonical_candidate_id == market_episode.canonical_candidate_id
    assert result.canonical_payload_hash == market_episode.canonical_payload_hash
    assert result.h1_source.dataset_logical_hash == H1_HASH
    assert result.h2_source.dataset_logical_hash == H2_HASH


def test_rejects_cross_instrument_and_pre_episode_windows() -> None:
    with pytest.raises(ValueError, match="BTC and ETH"):
        extract([bar(10 * S, instrument="ETHUSDT")], [trade(10, 10 * S)])
    with pytest.raises(ValueError, match="before the MarketEpisode"):
        extract([bar(10 * S)], [trade(10, 10 * S)], start=9 * S)
    with pytest.raises(ValueError, match="source instrument"):
        extract_historical_path(
            episode=episode(),
            h1_rows=[bar(10 * S)],
            h2_rows=[trade(10, 10 * S)],
            h1_source=source("H1", "ETHUSDT"),
            h2_source=source("H2"),
            window_start_ns=10 * S,
            window_end_ns=13 * S,
        )


def test_rejects_non_candidate_episode_and_tampered_output_hash() -> None:
    rejected = episode().model_copy(update={"episode_status": "REJECTED"})
    with pytest.raises(ValueError, match="only CANDIDATE"):
        extract([bar(10 * S)], [trade(10, 10 * S)], market_episode=rejected)

    result = extract([bar(10 * S)], [trade(10, 10 * S)])
    with pytest.raises(ValidationError, match="output_hash mismatch"):
        type(result).model_validate({**result.model_dump(mode="python"), "output_hash": "9" * 64})
