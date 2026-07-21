from __future__ import annotations

import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.data.schema.models import ContractPrice1s, NormalizedTrade
from era100x.research.stage_2.contracts.models import MarketEpisode
from era100x.research.stage_2.metrics.path import (
    compute_h1_path_metrics,
    compute_h2_path_metrics,
)
from era100x.research.stage_2.paths.extraction import PathSource, extract_historical_path

S = 1_000_000_000
THRESHOLDS = (Decimal("15"), Decimal("20"), Decimal("100"))


def _episode(instrument: str = "BTCUSDT") -> MarketEpisode:
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
            "sweep_start_ns": S,
            "episode_status": "CANDIDATE",
        }
    )


def _source(level: str, instrument: str = "BTCUSDT") -> PathSource:
    return PathSource.model_validate(
        {
            "instrument": instrument,
            "evidence_level": level,
            "reference_price_type": "CONTRACT" if level == "H1" else "TRADE",
            "data_run_id": "stage1-baseline",
            "dataset_logical_hash": ("1" if level == "H1" else "2") * 64,
            "source_manifest_hash": "3" * 64,
        }
    )


def _bar(
    ts: int,
    *,
    high: str,
    low: str,
    instrument: str = "BTCUSDT",
) -> ContractPrice1s:
    high_price = Decimal(high)
    low_price = Decimal(low)
    middle = (high_price + low_price) / 2
    return ContractPrice1s.model_validate(
        {
            "instrument": instrument,
            "ts_event_ns": ts,
            "open": middle,
            "high": high_price,
            "low": low_price,
            "close": middle,
            "volume": Decimal("5"),
            "source_encoding": "DECIMAL_TEXT",
        }
    )


def _trade(
    venue_id: int,
    ts: int,
    price: str,
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
            "price": Decimal(price),
            "quantity": Decimal("1"),
            "quote_quantity": Decimal(price),
            "ts_event_ns": ts,
            "is_buyer_maker": False,
            "aggressor_side": "BUY",
            "source_sha256": "4" * 64,
        }
    )


def _path(
    h1_rows: list[ContractPrice1s],
    h2_rows: list[NormalizedTrade],
    *,
    instrument: str = "BTCUSDT",
):
    return extract_historical_path(
        episode=_episode(instrument),
        h1_rows=h1_rows,
        h2_rows=h2_rows,
        h1_source=_source("H1", instrument),
        h2_source=_source("H2", instrument),
        window_start_ns=10 * S,
        window_end_ns=14 * S,
    )


def test_h1_decimal_signs_extrema_and_time_since_mfe() -> None:
    path = _path(
        [
            _bar(10 * S, high="100.10", low="99.90"),
            _bar(11 * S, high="100.25", low="99.80"),
            _bar(12 * S, high="100.25", low="99.70"),
            _bar(13 * S, high="100.20", low="99.95"),
        ],
        [],
    )

    result = compute_h1_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
    )

    assert result.mfe_bps == Decimal("25.0000")
    assert result.mae_bps == Decimal("-30.0000")
    assert result.mfe_first_ts_event_ns == 11 * S
    assert result.mae_first_ts_event_ns == 12 * S
    assert result.time_since_mfe_ns == 2 * S
    assert [item.activated for item in result.activations] == [True, True, False]
    assert result.activations[1].time_to_activation_ns == S
    assert "RETURN" in result.prohibited_interpretations


def test_h2_v2_order_uses_first_stable_tie_and_preserves_conflicts() -> None:
    rows = [
        _trade(9, 10 * S, "100.10", canonical="f" * 64),
        _trade(10, 11 * S, "100.30", canonical="b" * 64, conflict=True),
        _trade(10, 11 * S, "100.30", canonical="a" * 64, conflict=True),
        _trade(11, 12 * S, "99.75", canonical="c" * 64),
    ]
    path = _path([], rows)

    result = compute_h2_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
    )

    assert result.observation_count == 4
    assert result.mfe_bps == Decimal("30.0000")
    assert result.mae_bps == Decimal("-25.0000")
    assert result.mfe_first_ts_event_ns == 11 * S
    assert result.source_quality_status == "WITH_GAPS_AND_AMBIGUITY"
    assert result.source_ambiguity_codes == ("H2_CONFLICTING_VENUE_ID",)


def test_zero_baseline_and_unreached_activation_are_not_missing() -> None:
    path = _path(
        [_bar(10 * S, high="100", low="100"), _bar(11 * S, high="100", low="100")],
        [],
    )
    result = compute_h1_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
    )

    assert result.metric_status == "COMPUTED"
    assert result.mfe_bps == 0
    assert result.mae_bps == 0
    assert result.mfe_first_ts_event_ns == 10 * S
    assert result.time_since_mfe_ns == S
    assert all(not item.activated for item in result.activations)
    assert all(item.time_to_activation_ns is None for item in result.activations)


def test_empty_evidence_is_no_observations_not_zero() -> None:
    path = _path([], [])
    result = compute_h2_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
    )

    assert result.metric_status == "NO_OBSERVATIONS"
    assert result.mfe_bps is None
    assert result.mae_bps is None
    assert result.time_since_mfe_ns is None
    assert result.source_gap_codes == ("H1_MISSING_SECONDS",)


def test_activation_boundary_is_inclusive_and_window_end_is_excluded() -> None:
    path = _path(
        [_bar(10 * S, high="100.20", low="100")],
        [_trade(1, 10 * S, "100.20"), _trade(2, 14 * S, "102")],
    )
    h1 = compute_h1_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=(Decimal("20"),),
    )
    h2 = compute_h2_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=(Decimal("20"),),
    )

    assert h1.activations[0].activated
    assert h1.activations[0].time_to_activation_ns == 0
    assert h2.observation_count == 1
    assert h2.activations[0].activated


def test_gap_truncation_and_lineage_are_propagated() -> None:
    path = _path([_bar(11 * S, high="100.2", low="99.8")], [])
    result = compute_h1_path_metrics(
        path,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
        window_truncated=True,
    )

    assert result.window_truncated
    assert result.source_quality_status == "WITH_GAPS"
    assert result.source_gap_codes == ("H1_MISSING_SECONDS",)
    assert result.market_episode_id == path.market_episode_id
    assert result.canonical_candidate_id == path.canonical_candidate_id
    assert result.source_path_hash == path.output_hash


def test_shuffle_and_threshold_order_are_deterministic() -> None:
    h1_rows = [
        _bar(10 * S, high="100.1", low="99.9"),
        _bar(11 * S, high="100.3", low="99.8"),
    ]
    h2_rows = [_trade(1, 10 * S, "100.1"), _trade(2, 11 * S, "100.3")]
    shuffled_h1 = list(h1_rows)
    shuffled_h2 = list(h2_rows)
    random.Random(20260721).shuffle(shuffled_h1)
    random.Random(20260722).shuffle(shuffled_h2)
    first = _path(h1_rows, h2_rows)
    second = _path(shuffled_h1, shuffled_h2)

    one = compute_h2_path_metrics(
        first,
        reference_price=Decimal("100"),
        activation_thresholds_bps=(Decimal("100"), Decimal("15"), Decimal("20")),
    )
    two = compute_h2_path_metrics(
        second,
        reference_price=Decimal("100"),
        activation_thresholds_bps=THRESHOLDS,
    )
    assert one == two
    assert one.output_hash == two.output_hash


def test_btc_eth_are_separate_and_invalid_contracts_fail_closed() -> None:
    btc = _path([_bar(10 * S, high="100.2", low="99.8")], [])
    eth = _path(
        [_bar(10 * S, high="100.2", low="99.8", instrument="ETHUSDT")],
        [],
        instrument="ETHUSDT",
    )
    btc_result = compute_h1_path_metrics(
        btc, reference_price=Decimal("100"), activation_thresholds_bps=THRESHOLDS
    )
    eth_result = compute_h1_path_metrics(
        eth, reference_price=Decimal("100"), activation_thresholds_bps=THRESHOLDS
    )
    assert btc_result.instrument == "BTCUSDT"
    assert eth_result.instrument == "ETHUSDT"
    assert btc_result.output_hash != eth_result.output_hash

    with pytest.raises(ValueError, match="positive"):
        compute_h1_path_metrics(
            btc, reference_price=Decimal("0"), activation_thresholds_bps=THRESHOLDS
        )
    with pytest.raises(ValueError, match="positive Decimal"):
        compute_h1_path_metrics(
            btc,
            reference_price=Decimal("100"),
            activation_thresholds_bps=(Decimal("0"),),
        )
    with pytest.raises(ValidationError, match="output_hash mismatch"):
        type(btc_result).model_validate(
            {**btc_result.model_dump(mode="python"), "output_hash": "9" * 64}
        )
